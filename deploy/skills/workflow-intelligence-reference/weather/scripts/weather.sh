#!/usr/bin/env bash
# Two-call REST reference: resolve a place name to coordinates, then fetch the
# forecast for those coordinates. Open-Meteo needs no API key.
#   Geocoding API: https://open-meteo.com/en/docs/geocoding-api
#   Forecast API:  https://open-meteo.com/en/docs
#
# The shape is the point. A CRM or SaaS skill mirrors it: call 1 resolves a human
# identifier (company name, email) to a stable ID, call 2 reads by that ID. Each
# call fails loudly on its own, and output is compact JSON the agent can quote.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: weather.sh PLACE [--days N] [--units metric|imperial]

  PLACE     City or place name, e.g. "Denver" or "Berlin". Add a country to
            disambiguate: "Paris, US" matches on the country code after a comma.
  --days    Forecast days, 1 to 16 (default 3).
  --units   metric (C, km/h, mm) or imperial (F, mph, inch). Default metric.

Prints one JSON object on stdout. Exits 2 on bad input, 3 if the place is not
found, 4 if an API call fails.
EOF
}

place=""
days=3
units=metric
while [ $# -gt 0 ]; do
  case "$1" in
    --days)
      days="${2:-}"
      shift 2 || { usage >&2; exit 2; }
      ;;
    --units)
      units="${2:-}"
      shift 2 || { usage >&2; exit 2; }
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    -*)
      echo "unknown option: $1" >&2
      exit 2
      ;;
    *)
      place="$1"
      shift
      ;;
  esac
done

[ -n "$place" ] || { usage >&2; exit 2; }
[[ "$days" =~ ^[0-9]+$ ]] && [ "$days" -ge 1 ] && [ "$days" -le 16 ] || { echo "--days must be 1 to 16" >&2; exit 2; }
case "$units" in
  metric) unit_args=() ;;
  imperial) unit_args=(--data-urlencode temperature_unit=fahrenheit --data-urlencode wind_speed_unit=mph --data-urlencode precipitation_unit=inch) ;;
  *) echo "--units must be metric or imperial" >&2; exit 2 ;;
esac

# "Paris, US" -> name=Paris, country filter US.
name="${place%%,*}"
country=""
if [[ "$place" == *,* ]]; then
  country="$(printf '%s' "${place#*,}" | tr -d '[:space:]' | tr '[:lower:]' '[:upper:]')"
fi

http_get() {
  curl -fsS --max-time 15 --retry 2 --get "$@" || exit 4
}

# Call 1: geocode. Ask for several matches so the country filter has candidates.
geo="$(http_get https://geocoding-api.open-meteo.com/v1/search \
  --data-urlencode "name=$name" --data-urlencode count=10 \
  --data-urlencode language=en --data-urlencode format=json)"

location="$(GEO="$geo" COUNTRY="$country" python3 - <<'PY'
import json, os
results = json.loads(os.environ["GEO"]).get("results") or []
country = os.environ["COUNTRY"]
if country:
    results = [r for r in results if r.get("country_code", "").upper() == country]
if results:
    r = results[0]
    print(json.dumps({k: r.get(k) for k in ("name", "admin1", "country", "country_code", "latitude", "longitude", "timezone")}))
PY
)"
[ -n "$location" ] || { echo "place not found: $place" >&2; exit 3; }

read -r lat lon < <(LOC="$location" python3 -c 'import json,os; l=json.loads(os.environ["LOC"]); print(l["latitude"], l["longitude"])')

# Call 2: forecast for the resolved coordinates.
forecast="$(http_get https://api.open-meteo.com/v1/forecast \
  --data-urlencode "latitude=$lat" --data-urlencode "longitude=$lon" \
  --data-urlencode current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m \
  --data-urlencode daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max \
  --data-urlencode timezone=auto --data-urlencode "forecast_days=$days" \
  "${unit_args[@]}")"

LOC="$location" FC="$forecast" python3 - <<'PY'
import json, os
fc = json.loads(os.environ["FC"])
print(json.dumps({
    "location": json.loads(os.environ["LOC"]),
    "current": fc.get("current"),
    "current_units": fc.get("current_units"),
    "daily": fc.get("daily"),
    "daily_units": fc.get("daily_units"),
}, ensure_ascii=False))
PY

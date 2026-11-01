---
name: weather
description: Current conditions and a short daily forecast for a named place, via the keyless Open-Meteo API (geocode, then forecast).
version: 1.0.0
author: Workflow Intelligence Kit
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [reference, weather, rest]
    category: workflow-intelligence-reference
    requires_toolsets: [terminal]
---

# Weather (reference skill)

This skill is the kit's worked example of the two-call REST pattern. Forks copy
its shape for CRM and SaaS skills: resolve a human identifier to a stable ID,
then read by that ID. It is read-only and needs no credentials.

## When to Use

- The operator asks about weather, temperature, rain, or wind for a place.
- A scheduled pulse asks for the day's forecast.

Do not use it for historical weather or severe-weather alerts; Open-Meteo's
forecast endpoint does not provide official warnings.

## Procedure

1. Pick the place name from the request. If it is ambiguous (Springfield,
   Paris), add the ISO country code after a comma, or ask once.
2. Run the bundled script, which makes both calls and prints one JSON object:

       bash ${HERMES_SKILL_DIR}/scripts/weather.sh "Denver, US" --days 3 --units imperial

   Use `--units imperial` for operators in the US, metric otherwise, unless the
   operator has said which they prefer.
3. Read `location` to confirm the right place was matched, then summarize
   `current` and `daily` in two or three sentences. Translate `weather_code`
   with the table below. Quote units from `current_units` / `daily_units`.

If the script is unavailable, make the same two calls with curl:

    curl -fsS --get https://geocoding-api.open-meteo.com/v1/search \
      --data-urlencode name=Denver --data-urlencode count=1 --data-urlencode format=json
    curl -fsS --get https://api.open-meteo.com/v1/forecast \
      --data-urlencode latitude=39.739 --data-urlencode longitude=-104.985 \
      --data-urlencode current=temperature_2m,weather_code,wind_speed_10m \
      --data-urlencode daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max \
      --data-urlencode timezone=auto

## WMO weather codes

| Code | Meaning |
|------|---------|
| 0 | Clear sky |
| 1, 2, 3 | Mainly clear, partly cloudy, overcast |
| 45, 48 | Fog, depositing rime fog |
| 51, 53, 55 | Drizzle: light, moderate, dense |
| 56, 57 | Freezing drizzle |
| 61, 63, 65 | Rain: slight, moderate, heavy |
| 66, 67 | Freezing rain |
| 71, 73, 75 | Snow: slight, moderate, heavy |
| 77 | Snow grains |
| 80, 81, 82 | Rain showers: slight, moderate, violent |
| 85, 86 | Snow showers: slight, heavy |
| 95 | Thunderstorm |
| 96, 99 | Thunderstorm with hail |

Source: the "WMO Weather interpretation codes" table at https://open-meteo.com/en/docs

## Pitfalls

- Exit 3 means the geocoder found no match. Try the larger nearby city or drop
  the country filter; do not guess coordinates.
- Exit 4 means an HTTP call failed. Report that the weather service is
  unreachable instead of answering from memory.
- `daily.time` is in the place's local timezone (`timezone=auto`), not the
  server's.

## Verification

`bash ${HERMES_SKILL_DIR}/scripts/weather.sh Berlin --days 1` prints JSON whose
`location.country_code` is `DE` and whose `daily.time` has one date.

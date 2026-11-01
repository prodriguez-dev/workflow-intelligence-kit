"""Read-only estimate sources behind one two-call REST shape.

Call 1 lists the IDs of open estimates; call 2 reads one estimate by ID. This
mirrors the weather reference skill (resolve, then read by ID) and is the seam a
fork swaps for a real CRM:

    GET {base_url}/estimates?status=open  -> {"results": [{"id": "..."}], "next": null}
    GET {base_url}/estimates/{id}         -> one estimate record, or 404

Both sources expose only these two reads. There is no code path that sends
anything other than GET, so the skill cannot write to the system it reads.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

# Record fields that hold dates. FixtureSource shifts these when asked to.
DATE_FIELDS = ("sent_at", "expires_on", "last_customer_reply_at", "last_follow_up_at")
MAX_PAGES = 50
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class SourceError(Exception):
    """The source could not be read. The CLI exits 4 on this."""


def _shift_value(value, days):
    if not isinstance(value, str) or not value.strip() or days == 0:
        return value
    try:
        if len(value) == 10:
            return (date.fromisoformat(value) + timedelta(days=days)).isoformat()
        return (datetime.fromisoformat(value) + timedelta(days=days)).isoformat()
    except ValueError:
        return value  # leave bad data bad; selection reports it


def shift_record(record, days):
    """Return a copy of an estimate record with its dates moved by `days`."""
    shifted = dict(record)
    for field in DATE_FIELDS:
        if field in shifted:
            shifted[field] = _shift_value(shifted[field], days)
    return shifted


class FixtureSource:
    """Serves a JSON fixture with the same two calls as the HTTP API.

    The fixture file is {"as_of": "YYYY-MM-DD", "estimates": [record, ...]}.
    With shift_dates, every date moves by (today - as_of) so the fixture reads
    as if it were exported today. The kit's shipped demo stays meaningful on any
    date; the logic under test never sees the shift.
    """

    kind = "fixture"

    def __init__(self, path, today=None, shift_dates=False):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            raise SourceError(f"cannot read fixture {path}: {exc}") from exc
        records = data.get("estimates") if isinstance(data, dict) else None
        if not isinstance(records, list):
            raise SourceError(f"fixture {path} has no 'estimates' list")
        delta = 0
        if shift_dates and today is not None and data.get("as_of"):
            delta = (today - date.fromisoformat(data["as_of"])).days
        self.as_of = data.get("as_of")
        self.shift_days = delta
        self._records = [shift_record(r, delta) for r in records if isinstance(r, dict) and r.get("id")]
        self._by_id = {r["id"]: r for r in self._records}
        self.calls = []

    # Call 1
    def list_open_ids(self):
        self.calls.append("fixture GET /estimates?status=open")
        return [r["id"] for r in self._records if r.get("status") == "open"]

    # Call 2
    def get_estimate(self, estimate_id):
        self.calls.append(f"fixture GET /estimates/{urllib.parse.quote(estimate_id, safe='')}")
        record = self._by_id.get(estimate_id)
        return dict(record) if record is not None else None

    def all_records(self):
        """Every record, open or not. For the fixture server and docs only."""
        return [dict(r) for r in self._records]


class HttpSource:
    """GET-only client for any API that serves the two-call shape."""

    kind = "http"

    def __init__(self, base_url, token=None, timeout=15, retries=2, token_env=""):
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise SourceError(f"not an http(s) URL: {base_url}")
        if parsed.scheme == "http" and parsed.hostname not in LOOPBACK_HOSTS:
            # A bearer token over plain HTTP is readable on the wire.
            raise SourceError(f"refusing plain http to a non-local host: {parsed.hostname} (use https)")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.token_env = token_env
        self.timeout = timeout
        self.retries = retries
        self.calls = []

    def _get(self, url):
        headers = {"Accept": "application/json", "User-Agent": "wik-estimate-followup/1"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        parts = urllib.parse.urlsplit(url)
        label = parts.path + (f"?{parts.query}" if parts.query else "")
        for attempt in range(self.retries + 1):
            request = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    body = resp.read()
                    self.calls.append(f"GET {label} -> {resp.status}")
                    try:
                        return json.loads(body)
                    except ValueError as exc:
                        raise SourceError(f"GET {label}: response is not JSON") from exc
            except urllib.error.HTTPError as exc:
                self.calls.append(f"GET {label} -> {exc.code}")
                if exc.code == 404:
                    return None
                if exc.code in (401, 403):
                    hint = f" (check {self.token_env} in .env)" if self.token_env else ""
                    raise SourceError(f"GET {label}: HTTP {exc.code}, token missing or rejected{hint}") from exc
                if exc.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(2**attempt)
                    continue
                raise SourceError(f"GET {label}: HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                self.calls.append(f"GET {label} -> unreachable")
                if attempt < self.retries:
                    time.sleep(2**attempt)
                    continue
                raise SourceError(f"GET {label}: unreachable ({exc})") from exc
        raise SourceError(f"GET {label}: gave up")  # not reached

    # Call 1
    def list_open_ids(self):
        url = f"{self.base_url}/estimates?status=open"
        ids = []
        for _ in range(MAX_PAGES):
            page = self._get(url)
            if not isinstance(page, dict) or not isinstance(page.get("results"), list):
                raise SourceError("list call: expected {\"results\": [...]}")
            ids.extend(str(r["id"]) for r in page["results"] if isinstance(r, dict) and r.get("id"))
            nxt = page.get("next")
            if not nxt:
                return ids
            url = urllib.parse.urljoin(url, nxt)
        raise SourceError(f"list call: more than {MAX_PAGES} pages")

    # Call 2
    def get_estimate(self, estimate_id):
        record = self._get(f"{self.base_url}/estimates/{urllib.parse.quote(estimate_id, safe='')}")
        if record is not None and not isinstance(record, dict):
            raise SourceError(f"read call for {estimate_id}: expected a JSON object")
        return record


def open_source(base_url, skill_dir, today, token_env="", shift_dates=False, timeout=15):
    """Pick the source from base_url: http(s) URL, or a fixture path."""
    if base_url.startswith(("http://", "https://")):
        token = os.environ.get(token_env, "").strip() if token_env else ""
        return HttpSource(base_url, token=token or None, timeout=timeout, token_env=token_env)
    path = base_url if os.path.isabs(base_url) else os.path.join(skill_dir, base_url)
    return FixtureSource(path, today=today, shift_dates=shift_dates)

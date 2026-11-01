"""Load and validate config.toml. Every tunable lives there, not in code."""

from __future__ import annotations

import os
import string
import tomllib
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Placeholders the voice templates may use. drafts.py fills every one of them.
PLACEHOLDERS = frozenset({
    "greeting", "first_name", "customer_name", "job_title", "job_address",
    "amount", "sent_on", "days_waiting", "expires_on", "expiry_sentence",
    "final_sentence", "business_name", "sender_name", "business_phone",
})
TEMPLATE_KEYS = (
    "greeting", "greeting_fallback", "email_subject", "email_body", "sms_body",
    "expiry_sentence", "final_sentence",
)
CHANNELS = ("email", "sms")


class ConfigError(Exception):
    """config.toml is missing, malformed, or inconsistent. The CLI exits 2."""


@dataclass(frozen=True)
class Selection:
    followup_after_days: int = 3
    max_followups: int = 2
    redraft_after_days: int = 3
    max_drafts_per_run: int = 8
    channel_preference: tuple = CHANNELS


@dataclass(frozen=True)
class Business:
    name: str = "Example Business"
    sender_name: str = "The team"
    phone: str = ""
    timezone: str = "UTC"
    currency_symbol: str = "$"

    @property
    def tz(self):
        return ZoneInfo(self.timezone)


@dataclass(frozen=True)
class Voice:
    greeting: str = "Hi {first_name},"
    greeting_fallback: str = "Hi there,"
    email_subject: str = "Following up on your {job_title} estimate"
    email_body: str = "{greeting}\n\nChecking in on the {job_title} estimate from {sent_on}.\n\n{sender_name}"
    sms_body: str = "{greeting} checking in on the {job_title} estimate from {sent_on}. {sender_name}"
    expiry_sentence: str = "Pricing holds through {expires_on}."
    final_sentence: str = ""
    job_fallback: str = "project"
    style_notes: str = ""


@dataclass(frozen=True)
class Config:
    source_base_url: str
    source_token_env: str = ""
    fixture_shift_dates: bool = False
    timeout_seconds: int = 15
    state_path: str = ""
    selection: Selection = field(default_factory=Selection)
    business: Business = field(default_factory=Business)
    voice: Voice = field(default_factory=Voice)


def _int(section, key, value, minimum):
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ConfigError(f"[{section}] {key} must be an integer >= {minimum}, got {value!r}")
    return value


def _check_template(key, text):
    if not isinstance(text, str):
        raise ConfigError(f"[voice] {key} must be a string")
    try:
        fields = {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}
    except ValueError as exc:
        raise ConfigError(f"[voice] {key}: {exc} (write a literal brace as {{{{ or }}}})") from exc
    unknown = sorted(f for f in fields if f not in PLACEHOLDERS)
    if unknown:
        raise ConfigError(
            f"[voice] {key} uses unknown placeholder(s) {', '.join('{' + u + '}' for u in unknown)}; "
            f"allowed: {', '.join(sorted(PLACEHOLDERS))}"
        )
    # A sentence template must not pull in itself or the other sentence.
    if key in ("expiry_sentence", "final_sentence", "greeting", "greeting_fallback"):
        nested = fields & {"expiry_sentence", "final_sentence", "greeting"}
        if nested:
            raise ConfigError(f"[voice] {key} cannot use {', '.join(sorted(nested))}")


def default_state_path():
    home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
    return os.path.join(home, "estimate-followup", "surfaced.json")


def load(path):
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config {path} is not valid TOML: {exc}") from exc
    return from_dict(raw)


def from_dict(raw):
    src = raw.get("source", {})
    sel = raw.get("selection", {})
    biz = raw.get("business", {})
    voice = raw.get("voice", {})
    state = raw.get("state", {})

    base_url = src.get("base_url", "")
    if not isinstance(base_url, str) or not base_url.strip():
        raise ConfigError("[source] base_url is required (a fixture path or an https URL)")

    prefs = sel.get("channel_preference", list(CHANNELS))
    if not isinstance(prefs, list) or not prefs or any(p not in CHANNELS for p in prefs):
        raise ConfigError(f"[selection] channel_preference must be a non-empty list of {CHANNELS}")
    selection = Selection(
        followup_after_days=_int("selection", "followup_after_days", sel.get("followup_after_days", 3), 1),
        max_followups=_int("selection", "max_followups", sel.get("max_followups", 2), 1),
        redraft_after_days=_int("selection", "redraft_after_days", sel.get("redraft_after_days", 3), 1),
        max_drafts_per_run=_int("selection", "max_drafts_per_run", sel.get("max_drafts_per_run", 8), 1),
        channel_preference=tuple(prefs),
    )

    business = Business(**{k: str(v) for k, v in biz.items() if k in Business.__dataclass_fields__})
    try:
        business.tz
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"[business] timezone is not an IANA zone name: {business.timezone!r}") from exc

    unknown_voice = sorted(set(voice) - set(Voice.__dataclass_fields__))
    if unknown_voice:
        raise ConfigError(f"[voice] unknown key(s): {', '.join(unknown_voice)}")
    voice_cfg = Voice(**voice)
    for key in TEMPLATE_KEYS:
        _check_template(key, getattr(voice_cfg, key))

    return Config(
        source_base_url=base_url.strip(),
        source_token_env=str(src.get("token_env", "")),
        fixture_shift_dates=bool(src.get("fixture_shift_dates", False)),
        timeout_seconds=_int("source", "timeout_seconds", src.get("timeout_seconds", 15), 1),
        state_path=os.path.expanduser(str(state.get("path", ""))) or default_state_path(),
        selection=selection,
        business=business,
        voice=voice_cfg,
    )

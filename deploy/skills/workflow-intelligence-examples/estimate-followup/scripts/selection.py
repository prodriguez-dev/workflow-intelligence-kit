"""Decide which open estimates get a follow-up draft today.

Pure functions over plain dicts: no I/O, no clock. The caller passes `today`
(a date in the business's time zone), so tests pin every edge case.

An estimate qualifies when all of these hold, checked in this order (the first
failure is the reason it is skipped):

  1. status is "open"                                  else not_open
  2. the customer is not marked do-not-contact         else do_not_contact
  3. sent_at is present and parses                     else bad_data (operator sees it)
  4. no customer reply on or after sent_at             else replied
  5. not past expires_on (expiring today still counts) else expired
  6. fewer than max_followups follow-ups already sent  else max_followups
  7. at least followup_after_days since the last touch else not_due
     (last touch = the later of sent_at and last_follow_up_at)
  8. not surfaced to the operator in the last
     redraft_after_days days (local ledger)            else surfaced_recently
     (bad_data from step 3 respects this window too)
  9. has a usable email or phone                       else missing_contact (operator sees it)

A reply from before the estimate was sent (an early inquiry) does not count.
Days are calendar days in the business time zone, so an estimate sent at
11:30 pm is one day old the next morning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

ATTENTION_REASONS = frozenset({"bad_data", "missing_contact"})
REASON_LABELS = {
    "not_open": "no longer open",
    "do_not_contact": "do-not-contact",
    "bad_data": "bad data",
    "replied": "replied",
    "expired": "expired",
    "max_followups": "follow-up limit reached",
    "not_due": "not due yet",
    "surfaced_recently": "already in a recent message",
    "missing_contact": "no usable email or phone on file",
    "not_found": "gone from the CRM",
    "held_over": "held for the next run (daily cap)",
}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class Decision:
    estimate_id: str
    action: str  # "draft" or "skip"
    reason: str = ""
    detail: str = ""
    record: dict = field(default_factory=dict)
    days_waiting: int | None = None
    followup_number: int = 0  # 1 for the first follow-up after the estimate
    is_final: bool = False
    channel: str = ""
    to: str = ""
    previously_surfaced_on: str | None = None

    @property
    def needs_attention(self):
        return self.action == "skip" and self.reason in ATTENTION_REASONS


def parse_when(value, tz):
    """Parse an ISO 8601 date or datetime into an aware datetime.

    Naive values are taken as business-local time. Returns None for empty
    values and raises ValueError for unparseable ones.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise ValueError(f"not a string: {value!r}")
    text = value.strip()
    if len(text) == 10:
        d = date.fromisoformat(text)
        return datetime(d.year, d.month, d.day, tzinfo=tz)
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


def parse_day(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return date.fromisoformat(str(value).strip()[:10])


def usable_email(value):
    text = (value or "").strip() if isinstance(value, str) else ""
    return text if EMAIL_RE.match(text) else ""


def usable_phone(value):
    text = (value or "").strip() if isinstance(value, str) else ""
    return text if len(re.sub(r"\D", "", text)) >= 7 else ""


def customer_name(record):
    c = record.get("customer") or {}
    name = " ".join(p for p in ((c.get("first_name") or "").strip(), (c.get("last_name") or "").strip()) if p)
    return name or (c.get("company") or "").strip() or "(no name)"


def evaluate(record, today, tz, selection, surfaced=None):
    """Return a Decision for one estimate record."""
    surfaced = surfaced or {}
    eid = str(record.get("id", ""))
    customer = record.get("customer") or {}

    def skip(reason, detail=""):
        return Decision(eid, "skip", reason, detail, record)

    def recently_surfaced():
        previously = surfaced.get(eid)
        try:
            age = (today - date.fromisoformat(previously)).days if previously else None
        except ValueError:
            age = None
        return previously if age is not None and 0 <= age < selection.redraft_after_days else None

    def attention(reason, detail=""):
        # Operator-facing problems also respect the redraft window, so a broken
        # record is reported every few days, not every morning.
        previously = recently_surfaced()
        if previously:
            return skip("surfaced_recently", f"reported to the operator {previously}")
        return skip(reason, detail)

    status = record.get("status")
    if status != "open":
        return skip("not_open", f"status is {status!r}")
    if customer.get("do_not_contact"):
        return skip("do_not_contact")

    try:
        sent = parse_when(record.get("sent_at"), tz)
    except ValueError:
        return attention("bad_data", f"sent_at is not a date: {record.get('sent_at')!r}")
    if sent is None:
        return attention("bad_data", "sent_at is missing")
    try:
        replied = parse_when(record.get("last_customer_reply_at"), tz)
        last_follow_up = parse_when(record.get("last_follow_up_at"), tz)
        expires = parse_day(record.get("expires_on"))
    except ValueError as exc:
        return attention("bad_data", f"unparseable date ({exc})")

    if replied is not None and replied >= sent:
        return skip("replied", f"customer replied {replied.astimezone(tz).date().isoformat()}")
    if expires is not None and expires < today:
        return skip("expired", f"expired {expires.isoformat()}")

    count = record.get("follow_up_count") or 0
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return attention("bad_data", f"follow_up_count is not a count: {count!r}")
    if last_follow_up is not None:
        count = max(count, 1)
    if count >= selection.max_followups:
        return skip("max_followups", f"{count} follow-up{'s' if count != 1 else ''} already sent")

    last_touch = max(sent, last_follow_up) if last_follow_up is not None else sent
    days = (today - last_touch.astimezone(tz).date()).days
    if days < selection.followup_after_days:
        d = skip("not_due", f"{days} day{'s' if days != 1 else ''} since last touch")
        d.days_waiting = days
        return d

    recent = recently_surfaced()
    if recent:
        d = skip("surfaced_recently", f"sent to the operator {recent}")
        d.days_waiting = days
        return d
    previously = surfaced.get(eid)

    channel = to = ""
    for pref in selection.channel_preference:
        to = usable_email(customer.get("email")) if pref == "email" else usable_phone(customer.get("phone"))
        if to:
            channel = pref
            break
    if not channel:
        d = skip("missing_contact")
        d.days_waiting = days
        return d

    return Decision(
        eid, "draft", record=record, days_waiting=days,
        followup_number=count + 1, is_final=count + 1 >= selection.max_followups,
        channel=channel, to=to, previously_surfaced_on=previously or None,
    )


def select(records, today, tz, selection, surfaced=None):
    """Evaluate every record; cap drafts at max_drafts_per_run, oldest first.

    Returns (drafts, skipped). Drafts past the cap are skipped as held_over so
    they come back on the next run instead of being lost.
    """
    decisions = [evaluate(r, today, tz, selection, surfaced) for r in records]
    drafts = [d for d in decisions if d.action == "draft"]
    skipped = [d for d in decisions if d.action == "skip"]

    def amount(d):
        value = d.record.get("amount")
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0

    drafts.sort(key=lambda d: (-d.days_waiting, -amount(d), d.estimate_id))
    cap = selection.max_drafts_per_run
    for d in drafts[cap:]:
        d.action, d.reason, d.detail = "skip", "held_over", f"over the cap of {cap} per run"
        skipped.append(d)
    return drafts[:cap], skipped

"""Render follow-up drafts in the business's voice, and the Telegram review message.

Wording comes from [voice] in config.toml; this module only fills placeholders
and lays out the operator's review message. Nothing here sends anything.
"""

from __future__ import annotations

from collections import Counter

from selection import REASON_LABELS, customer_name, parse_day, parse_when

SILENT = "[SILENT]"


def short_date(d):
    return f"{d:%b} {d.day}"


def money(value, symbol):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return ""
    if float(value).is_integer():
        return f"{symbol}{int(value):,}"
    return f"{symbol}{value:,.2f}"


def _fields(decision, cfg):
    r = decision.record
    c = r.get("customer") or {}
    job = r.get("job") or {}
    tz = cfg.business.tz
    sent = parse_when(r.get("sent_at"), tz).astimezone(tz).date()
    expires = parse_day(r.get("expires_on"))
    first = (c.get("first_name") or "").strip()
    base = {
        "first_name": first,
        "customer_name": customer_name(r),
        "job_title": (job.get("title") or "").strip() or cfg.voice.job_fallback,
        "job_address": (job.get("address") or "").strip(),
        "amount": money(r.get("amount"), cfg.business.currency_symbol),
        "sent_on": short_date(sent),
        "days_waiting": str(decision.days_waiting),
        "expires_on": short_date(expires) if expires else "",
        "business_name": cfg.business.name,
        "sender_name": cfg.business.sender_name,
        "business_phone": cfg.business.phone,
    }
    v = cfg.voice
    base["greeting"] = (v.greeting if first else v.greeting_fallback).format(**base, expiry_sentence="", final_sentence="")
    base["expiry_sentence"] = v.expiry_sentence.format(**base, final_sentence="") if expires else ""
    base["final_sentence"] = v.final_sentence.format(**base) if decision.is_final else ""
    return base


def _tidy(text):
    """Drop blank lines and doubled spaces left by empty optional sentences."""
    lines = [" ".join(line.split()) for line in text.strip().splitlines()]
    out = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def render_draft(decision, cfg):
    """Return {"subject", "body"} for one qualifying estimate."""
    f = _fields(decision, cfg)
    if decision.channel == "email":
        return {"subject": _tidy(cfg.voice.email_subject.format(**f)), "body": _tidy(cfg.voice.email_body.format(**f))}
    return {"subject": "", "body": _tidy(cfg.voice.sms_body.format(**f))}


def _ordinal(n):
    return {1: "First", 2: "Second", 3: "Third"}.get(n, f"#{n}")


def render_telegram(drafts, rendered, skipped, today, cfg, notes=()):
    """The one message the operator gets. SILENT when there is nothing to do."""
    attention = [d for d in skipped if d.needs_attention]
    if not drafts and not attention and not notes:
        return SILENT

    n = len(drafts)
    header = f"Estimate follow-ups, {today:%a} {short_date(today)}: "
    header += f"{n} draft{'s' if n != 1 else ''} to review" if n else "nothing to draft"
    parts = [header]

    for i, (d, text) in enumerate(zip(drafts, rendered), start=1):
        r = d.record
        job = r.get("job") or {}
        sent = parse_when(r.get("sent_at"), cfg.business.tz).astimezone(cfg.business.tz).date()
        what = " ".join(p for p in (money(r.get("amount"), cfg.business.currency_symbol), (job.get("title") or "").strip()) if p)
        lines = [f"[{i}/{n}] {d.estimate_id} · {customer_name(r)}" + (f" · {what}" if what else "")]
        if job.get("address"):
            lines.append(job["address"].strip())
        ago = f"{d.days_waiting} day{'s' if d.days_waiting != 1 else ''} ago"
        last_fu = parse_when(r.get("last_follow_up_at"), cfg.business.tz)
        if last_fu is not None:
            status = f"Sent {short_date(sent)}, last follow-up {short_date(last_fu.astimezone(cfg.business.tz).date())} ({ago}), no reply."
        else:
            status = f"Sent {short_date(sent)} ({ago}), no reply."
        status += f" {_ordinal(d.followup_number)} follow-up" + (" (last one)." if d.is_final else ".")
        lines.append(status)
        if d.previously_surfaced_on:
            lines.append(f"Drafted before on {short_date(parse_day(d.previously_surfaced_on))} and still unanswered.")
        if d.channel == "email":
            lines.append(f"Email to {d.to}")
            lines.append(f"Subject: {text['subject']}")
        else:
            lines.append(f"Text to {d.to}")
        lines.append("")
        lines.append(text["body"])
        parts.append("\n".join(lines))

    if attention:
        lines = ["Needs a fix in the CRM:"]
        for d in attention:
            why = REASON_LABELS[d.reason] + (f", {d.detail}" if d.detail else "")
            lines.append(f"- {d.estimate_id} {customer_name(d.record)}: {why}")
        parts.append("\n".join(lines))

    quiet = Counter(d.reason for d in skipped if not d.needs_attention)
    if quiet:
        order = list(REASON_LABELS)
        summary = ", ".join(f"{quiet[k]} {REASON_LABELS[k]}" for k in sorted(quiet, key=order.index))
        parts.append(f"Not drafted: {summary}.")

    parts.extend(notes)
    if drafts:
        parts.append(
            "Nothing has been sent. Reply \"edit 2: ...\" to change a draft. "
            "Send the ones you approve from your own inbox or phone."
        )
    return "\n\n".join(parts)

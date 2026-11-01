#!/usr/bin/env python3
"""Find open estimates that need a follow-up and draft one for each.

Reads open estimates through the two-call source (list open IDs, then read each
by ID), applies the rules in selection.py with the threshold from config.toml,
and renders drafts in the [voice] from config.toml. It never sends email or
texts and never writes to the source.

Exit codes: 0 ok, 2 bad config or arguments, 4 the source could not be read.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime

sys.dont_write_bytecode = True  # keep the deployed skill directory clean

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

import config as config_mod  # noqa: E402
import drafts as drafts_mod  # noqa: E402
import ledger as ledger_mod  # noqa: E402
from selection import REASON_LABELS, Decision, customer_name, select  # noqa: E402
from source import SourceError, open_source  # noqa: E402


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--config", default=os.path.join(SKILL_DIR, "config.toml"), help="config file (default: the skill's config.toml)")
    p.add_argument("--source", help="override [source] base_url: a fixture path or an https URL")
    p.add_argument("--today", help="pretend today is YYYY-MM-DD (default: today in [business] timezone)")
    p.add_argument("--format", choices=("telegram", "json"), default="json", help="telegram prints only the operator message")
    p.add_argument("--record", action="store_true", help="remember surfaced estimates so the next run does not repeat them (the scheduled pulse uses this)")
    p.add_argument("--state", help="override the ledger path")
    p.add_argument("-v", "--verbose", action="store_true", help="log each source call to stderr")
    return p.parse_args(argv)


def run(argv=None):
    args = parse_args(argv)
    try:
        cfg = config_mod.load(args.config)
    except config_mod.ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    tz = cfg.business.tz
    if args.today:
        try:
            today = date.fromisoformat(args.today)
        except ValueError:
            print(f"--today must be YYYY-MM-DD, got {args.today!r}", file=sys.stderr)
            return 2
    else:
        today = datetime.now(tz).date()

    base_url = args.source or cfg.source_base_url
    state_path = args.state or cfg.state_path
    surfaced, warning = ledger_mod.load(state_path)
    if warning:
        print(f"warning: {warning}", file=sys.stderr)

    source = None
    try:
        source = open_source(base_url, SKILL_DIR, today, token_env=cfg.source_token_env,
                             shift_dates=cfg.fixture_shift_dates, timeout=cfg.timeout_seconds)
        open_ids = list(dict.fromkeys(source.list_open_ids()))  # call 1, de-duplicated
        records, missing = [], []
        for eid in open_ids:
            record = source.get_estimate(eid)  # call 2
            if record is None:
                missing.append(eid)
            else:
                records.append(record)
    except SourceError as exc:
        if args.verbose and source is not None:
            for line in source.calls:
                print(f"source: {line}", file=sys.stderr)
        print(f"source error: {exc}", file=sys.stderr)
        return 4
    if args.verbose:
        for line in source.calls:
            print(f"source: {line}", file=sys.stderr)

    drafts, skipped = select(records, today, tz, cfg.selection, surfaced)
    rendered = [drafts_mod.render_draft(d, cfg) for d in drafts]

    notes = []
    if args.record:
        newly = [d.estimate_id for d in drafts] + [d.estimate_id for d in skipped if d.needs_attention]
        try:
            ledger_mod.save(state_path, ledger_mod.updated(surfaced, set(open_ids), newly, today))
        except OSError as exc:
            print(f"warning: could not save ledger {state_path}: {exc}", file=sys.stderr)
            notes.append("Note: could not save the list of drafted estimates, so these may repeat on the next run.")

    skipped.extend(Decision(eid, "skip", "not_found", "listed as open but the read returned 404") for eid in missing)
    telegram = drafts_mod.render_telegram(drafts, rendered, skipped, today, cfg, notes)

    if args.format == "telegram":
        print(telegram)
        return 0
    out = {
        "as_of": today.isoformat(),
        "source": source.kind,
        "followup_after_days": cfg.selection.followup_after_days,
        "drafts": [
            {
                "n": i, "estimate_id": d.estimate_id, "customer": customer_name(d.record),
                "channel": d.channel, "to": d.to, "days_waiting": d.days_waiting,
                "followup_number": d.followup_number, "is_final": d.is_final,
                "previously_surfaced_on": d.previously_surfaced_on, **text,
            }
            for i, (d, text) in enumerate(zip(drafts, rendered), start=1)
        ],
        "needs_attention": [
            {"estimate_id": d.estimate_id, "customer": customer_name(d.record), "reason": d.reason, "detail": d.detail}
            for d in skipped if d.needs_attention
        ],
        "skipped": [
            {"estimate_id": d.estimate_id, "reason": d.reason, "label": REASON_LABELS[d.reason], "detail": d.detail}
            for d in skipped if not d.needs_attention
        ],
        "recorded": bool(args.record) and not notes,
        "telegram": telegram,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(run())

#!/usr/bin/env python3
"""Generate docs/demo/estimate-followup.md by running the skill for real.

Starts the fixture server on 127.0.0.1, runs the skill's CLI against it as a
subprocess (the same command the pulse runs, plus --today and --state so the
output is reproducible), and writes what came out. Nothing in the walkthrough
output sections is typed by hand.

    python3 docs/demo/generate_estimate_followup.py          # rewrite the doc
    python3 docs/demo/generate_estimate_followup.py --check  # exit 1 if stale

The skill's test suite runs --check, so a change to the logic, config, or
fixture that changes the output fails the tests until the doc is regenerated.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib

sys.dont_write_bytecode = True
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SKILL = os.path.join(REPO, "deploy", "skills", "workflow-intelligence-examples", "estimate-followup")
SCRIPTS = os.path.join(SKILL, "scripts")
CLI = os.path.join(SCRIPTS, "estimate_followup.py")
DOC = os.path.join(REPO, "docs", "demo", "estimate-followup.md")
TODAY = "2026-11-02"
sys.path.insert(0, SCRIPTS)

import fixture_server  # noqa: E402
from selection import REASON_LABELS  # noqa: E402


def run_cli(*args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", ESTIMATES_API_TOKEN="")
    proc = subprocess.run([sys.executable, CLI, *args], capture_output=True, text=True, env=env, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"CLI exited {proc.returncode}: {proc.stderr}")
    return proc.stdout, proc.stderr


def fence(text, lang="text"):
    return f"```{lang}\n{text.rstrip()}\n```"


def cell(value):
    if value in (None, ""):
        return "(none)"
    return str(value).replace("|", "\\|")


def build():
    with open(os.path.join(SKILL, "fixtures", "estimates.json"), encoding="utf-8") as fh:
        fixture = json.load(fh)
    with open(os.path.join(SKILL, "config.toml"), "rb") as fh:
        cfg = tomllib.load(fh)

    server, url = fixture_server.start(today=None)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            state = os.path.join(tmp, "surfaced.json")
            common = ["--source", url, "--today", TODAY, "--state", state]
            telegram, calls = run_cli(*common, "--format", "telegram", "--record", "-v")
            with open(state, encoding="utf-8") as fh:
                ledger = json.load(fh)
            second, _ = run_cli(*common, "--format", "telegram", "--record")
            # The decision trail, from a run with a fresh ledger.
            first_json, _ = run_cli("--source", url, "--today", TODAY, "--state", os.path.join(tmp, "fresh.json"))
    finally:
        server.shutdown()
        server.server_close()

    calls = re.sub(r"127\.0\.0\.1:\d+", "127.0.0.1:PORT", calls)
    result = json.loads(first_json)
    sel, biz = cfg["selection"], cfg["business"]

    rows = ["| ID | Customer | Job | Amount | Status | Sent | Expires | Last reply | Follow-ups | Email / phone |",
            "|----|----------|-----|--------|--------|------|---------|------------|------------|---------------|"]
    for e in fixture["estimates"]:
        c, j = e["customer"], e["job"]
        name = " ".join(p for p in (c.get("first_name") or "", c.get("last_name") or "") if p)
        contact = " / ".join(cell(v) for v in (c.get("email"), c.get("phone")))
        if c.get("do_not_contact"):
            contact += " (do not contact)"
        fu = str(e.get("follow_up_count") or 0)
        if e.get("last_follow_up_at"):
            fu += f", last {e['last_follow_up_at'][:10]}"
        rows.append("| " + " | ".join(cell(v) for v in (
            e["id"], name, j.get("title"), e.get("amount"), e.get("status"), (e.get("sent_at") or "")[:16],
            e.get("expires_on"), (e.get("last_customer_reply_at") or "")[:10], fu)) + f" | {contact} |")

    outcome = {d["estimate_id"]: f"Draft #{d['n']} ({d['channel']}, {d['days_waiting']} days, follow-up {d['followup_number']}"
               + (", last one)" if d["is_final"] else ")") for d in result["drafts"]}
    for a in result["needs_attention"]:
        outcome[a["estimate_id"]] = f"Flagged for the operator: {REASON_LABELS[a['reason']]}" + (f", {a['detail']}" if a["detail"] else "")
    for s in result["skipped"]:
        outcome[s["estimate_id"]] = f"Skipped: {s['label']}" + (f" ({s['detail']})" if s["detail"] else "")
    open_ids = {e["id"] for e in fixture["estimates"] if e.get("status") == "open"}
    trail = ["| ID | Outcome |", "|----|---------|"]
    for e in fixture["estimates"]:
        if e["id"] in open_ids:
            trail.append(f"| {e['id']} | {cell(outcome.get(e['id'], 'missing from output'))} |")
        else:
            trail.append(f"| {e['id']} | Not listed by call 1 (status {e['status']}) |")

    sample = json.dumps(result["drafts"][0], indent=2, ensure_ascii=False)

    return "\n".join([
        "# Demo: estimate follow-up",
        "",
        "<!-- Generated by docs/demo/generate_estimate_followup.py. Do not edit by hand;",
        "     change the skill, config, or fixture and re-run the generator. -->",
        "",
        "A walkthrough of the `estimate-followup` example skill",
        "(`deploy/skills/workflow-intelligence-examples/estimate-followup/`) on its shipped",
        "fixture. Nothing below is typed by hand: the settings and the fixture table",
        "are read from the shipped files, and the call log, the Telegram message, the",
        "ledger, and the JSON come from running the skill's CLI. The generator script",
        "named above rewrites this file, and the skill's tests fail if it falls out of",
        "date.",
        "",
        f"The business is a made-up roofing company, {biz['name']}. All names, addresses,",
        "phone numbers (555-01xx), and emails (example.com, example.net) are fake.",
        "",
        "## Setup",
        "",
        f"The run is pinned to Monday {TODAY} so it is reproducible. The relevant",
        "settings from `config.toml`:",
        "",
        fence("\n".join([
            "[selection]",
            f"followup_after_days = {sel['followup_after_days']}",
            f"max_followups = {sel['max_followups']}",
            f"redraft_after_days = {sel['redraft_after_days']}",
            f"max_drafts_per_run = {sel['max_drafts_per_run']}",
            "",
            "[business]",
            f"name = \"{biz['name']}\"",
            f"sender_name = \"{biz['sender_name']}\"",
            f"timezone = \"{biz['timezone']}\"",
        ]), "toml"),
        "",
        "The voice templates are in the same file, under `[voice]`.",
        "",
        "## Fixture in",
        "",
        f"`fixtures/estimates.json`, {len(fixture['estimates'])} estimates, `as_of` {fixture['as_of']}:",
        "",
        *rows,
        "",
        "## The run",
        "",
        "The generator serves the fixture with `scripts/fixture_server.py` and points",
        "the skill at it, so this run goes through the real HTTP client, the same",
        "path a fork's CRM would use. The command is the pulse's command plus",
        "`--source`, `--today`, `--state`, and `-v` (log each call):",
        "",
        fence("python3 scripts/estimate_followup.py --format telegram --record \\\n"
              f"  --source http://127.0.0.1:PORT --today {TODAY} --state /tmp/.../surfaced.json -v", "bash"),
        "",
        "Source calls (stderr). Call 1 lists open estimate IDs; call 2 reads each one:",
        "",
        fence(calls),
        "",
        "### Telegram message out",
        "",
        "This is stdout, which the agent delivers verbatim to the operator's",
        "Telegram home channel:",
        "",
        fence(telegram),
        "",
        "The operator reads this, edits any draft by replying (for example \"edit 2:",
        "mention we can start the week of the 16th\"), and sends the ones they approve",
        "from their own inbox or phone. That reply loop is the agent rewriting a",
        "draft under the rules in SKILL.md; it is model output, not deterministic, so",
        "it is not reproduced here. For replies to reach the agent with the drafts in",
        "context, turn on continuable cron deliveries (see",
        "`workspace-docs/HEARTBEAT.md`).",
        "",
        "### Why each estimate landed where it did",
        "",
        *trail,
        "",
        "## Second run the same morning",
        "",
        "The first run recorded what it put in front of the operator:",
        "",
        fence(json.dumps(ledger, indent=2), "json"),
        "",
        "Run again with the same ledger and nothing is new (everything surfaced is",
        f"inside the {sel['redraft_after_days']}-day redraft window), so the output is the marker that tells",
        "Hermes cron to deliver nothing:",
        "",
        fence(second),
        "",
        "## What the agent sees on a chat preview",
        "",
        "When the operator asks in chat (\"which estimates need a follow-up?\"), the",
        "agent runs `--format json` without `--record`, so the preview never",
        "changes what the next pulse sends. Draft #1 from a fresh run, as JSON:",
        "",
        fence(sample, "json"),
        "",
        "## Reproduce",
        "",
        fence("python3 docs/demo/generate_estimate_followup.py\n"
              "python3 -m unittest discover -s deploy/skills/workflow-intelligence-examples/estimate-followup/tests -t deploy/skills/workflow-intelligence-examples/estimate-followup/tests", "bash"),
        "",
    ])


def main():
    text = build()
    if "--check" in sys.argv[1:]:
        with open(DOC, encoding="utf-8") as fh:
            current = fh.read()
        if current != text:
            print(f"{os.path.relpath(DOC, REPO)} is stale; run {os.path.relpath(__file__, REPO)}", file=sys.stderr)
            return 1
        return 0
    with open(DOC, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {os.path.relpath(DOC, REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

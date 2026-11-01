---
name: estimate-followup
description: Find open estimates with no customer reply after N days and draft a short follow-up for each, for the operator to approve and send. Read-only; never sends.
version: 1.0.0
author: Workflow Intelligence Kit
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [example, sales, estimates, follow-up, drafts]
    category: workflow-intelligence-examples
    requires_toolsets: [terminal]
    related_skills: [weather]
# Fork with a real CRM: uncomment this so Hermes passes the token through to
# the script's terminal and cron preflight blocks the job when it is missing.
# The fixture needs no token, so the kit ships it commented out.
# required_environment_variables:
#   - name: ESTIMATES_API_TOKEN
#     prompt: Read-only API token for the estimates source
#     required_for: reading open estimates
---

# Estimate follow-up (example workflow skill)

Service businesses lose jobs because nobody follows up on estimates. This skill
reads open estimates, picks the ones that have waited `followup_after_days`
with no reply, and drafts a follow-up for each in the business's voice. The
operator reviews the drafts in Telegram and sends the ones they approve from
their own inbox or phone.

It ships pointed at a fixture of fake estimates for a made-up roofing company.
A fork points `[source] base_url` in `config.toml` at its CRM.

## Rules for this skill

These come from SOUL.md and are restated because this skill drafts messages
addressed to customers:

- **You never send.** Not email, not SMS, not a scheduled send, not through any
  other tool or skill. The output is drafts for the operator.
- **You never write to the estimates source.** The script only reads. Do not
  try to mark estimates as followed up anywhere.
- **The drafts you deliver are the script's drafts.** Do not rewrite them in a
  scheduled run. Change a draft only when the operator asks.

## When to Use

- A scheduled pulse asks for today's estimate follow-ups.
- The operator asks which estimates need a follow-up, or asks to see drafts.
- The operator replies to a follow-up delivery asking to change a draft.

## Procedure

### Scheduled run (the pulse)

Run, with `--record` so tomorrow's run does not repeat today's drafts:

    python3 ${HERMES_SKILL_DIR}/scripts/estimate_followup.py --format telegram --record

Reply with the script's stdout exactly as printed, and nothing else. When there
is nothing to draft and nothing for the operator to fix, the script prints
`[SILENT]`, which tells Hermes not to deliver anything. If the script exits
non-zero, do not improvise drafts: see Pitfalls.

### Operator asks in chat

Preview without `--record`, so the next scheduled run is unaffected:

    python3 ${HERMES_SKILL_DIR}/scripts/estimate_followup.py --format json

Answer from the JSON: `drafts` (numbered as in Telegram), `needs_attention`
(records the operator must fix in the CRM), and `skipped` (with a `reason`).
Show a draft's `subject` and `body` verbatim when asked for it.

### Operator asks to change a draft

Example: "edit 2: mention we can start the week of the 16th". Rewrite only that
draft. Follow `style_notes` and the sign-off in `[voice]` of
`${HERMES_SKILL_DIR}/config.toml`. Add only facts the operator gave you; never
invent prices, dates, discounts, or warranty terms. Reply with the full revised
draft so it can be copied in one go, and remind the operator that nothing has
been sent.

If the operator says "send it", explain that this skill only drafts and they
send it themselves. Do not look for another way to send.

## Exit codes

| Code | Meaning | What to tell the operator |
|------|---------|---------------------------|
| 0 | Ran; output is on stdout | Deliver it as described above |
| 2 | Bad config or arguments; the message is on stderr | "estimate-followup config error:" plus the stderr line |
| 4 | Estimates source unreachable or rejected the token | "Could not read estimates:" plus the stderr line. No drafts today |

For code 2 or 4 in a scheduled run, put `[CRON_FAILURE]` alone on the first
line of the reply, then the explanation, so Hermes records the run as failed.

## Pitfalls

- A 401 or 403 means the token in `.env` (named by `[source] token_env`) is
  missing or rejected. Say which variable; never print its value.
- Estimates listed as open but returning 404 on read are counted as "gone from
  the CRM". That is normal when a record is deleted between the two calls.
- "N days" is calendar days in `[business] timezone`, from the later of the
  send date and the last logged follow-up.
- A draft marked "Drafted before on ..." was already sent to the operator once
  and the estimate is still unanswered. Do not suggest the customer was
  contacted; the CRM shows no follow-up.

## Verification

    python3 ${HERMES_SKILL_DIR}/scripts/estimate_followup.py --today 2026-11-02 --format telegram --state /tmp/ef-check.json

With the shipped fixture this prints 5 drafts (EST-2041, 2043, 2051, 2053,
2042), flags EST-2046 and EST-2054 for a CRM fix, and does not write anywhere
except the throwaway `--state` path, which it only reads.

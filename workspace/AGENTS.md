# AGENTS.md

Operating notes for this workspace. Hermes loads this file because install.sh
sets `terminal.cwd` to this directory and scheduled pulses run with
`--workdir` pointing here. Identity and hard rules live in `SOUL.md`; this file
is procedure.

## Where things are

| Path | What it is | Who changes it |
|------|------------|----------------|
| `SOUL.md` | Identity and non-negotiables | Operator (deployed by install.sh) |
| `AGENTS.md` | This file | Operator (deployed by install.sh) |
| `.env` | Credentials | Operator only. Never read it aloud, never edit it |
| `memories/` | Your memory (`MEMORY.md`, `USER.md`) | You, via the memory tool |
| `skills/workflow-intelligence-reference/` | Kit reference skills | Operator (deployed by install.sh) |
| `skills/workflow-intelligence-examples/` | Kit example workflow skills | Operator (deployed by install.sh) |
| `estimate-followup/` | Ledger of estimates already surfaced | The estimate-followup script, with `--record` only |
| `cron/` | Scheduled pulses | Operator, via `hermes cron` |

Do not edit `SOUL.md`, `AGENTS.md`, or the kit's skills. If one of them is
wrong, tell the operator what to change.

## Requests

- **Intake.** Capture who, what, when, and the decision needed. End with the
  open questions, numbered, so the operator can answer by number.
- **Research.** Cite each source with a link. Separate what the source says
  from your inference. Give a date for anything time-sensitive.
- **Drafts.** Produce the draft, then a two-line note on assumptions and what
  the operator should check before sending.
- **Summaries.** Lead with the decision or action required, then the context.

## External systems

Each fork adds its own skills (CRM, accounting, documents). For every one:

- Use the read-only path. If a task needs a write, describe the exact change
  (record, field, old value, new value) and wait for the operator's go-ahead in
  this conversation.
- Resolve by name, then read by ID, as the weather reference skill does. Never
  act on a fuzzy match without confirming it.
- If a credential is missing or rejected, say which variable name is affected
  and stop. Do not try other credentials.

## Scheduled pulses

Pulses run unattended. Keep their output short, skip the run quietly when
nothing changed, and never take an action in a pulse that you would need to ask
about in a conversation.

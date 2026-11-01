# HEARTBEAT.md

The operator's runbook for scheduled pulses. Operator-facing: never deployed.

Pulses are Hermes cron jobs created with `hermes cron create`. The kit adds no
systemd timers of its own; the Hermes scheduler runs inside the gateway.
([Scheduled tasks](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron))

Not to be confused with Hermes's `/heartbeat` chat command, which repeats a
prompt inside one conversation. Pulses are standalone jobs.

## Pulses the kit ships

| Name | Schedule | What it does | Created as |
|------|----------|--------------|------------|
| `wik-reference-weather` | `0 7 * * *` (07:00 in `HERMES_TIMEZONE`) | Two-sentence forecast for `WIK_PULSE_LOCATION` via the weather skill, delivered to the Telegram home channel | Paused |

It exists to prove the full path (scheduler, skill, model, Telegram delivery)
on a new host. Forks usually replace it.

## Everyday commands

Run as the service user (`sudo -iu hermes`):

```bash
hermes cron list --all                   # ids, schedules, paused state
hermes cron run <job_id>                 # run once on the next tick
hermes cron pause <job_id>
hermes cron resume <job_id>
hermes cron edit <job_id> --prompt "..." # or --schedule, --deliver, --name
hermes cron remove <job_id>
hermes cron doctor                       # failed runs, missed schedules
```

To change the reference pulse's place, edit its prompt:

```bash
hermes cron edit <job_id> --prompt "Use the weather skill to get today's forecast for Denver, US. Reply in two sentences: conditions now, then today's high, low, and chance of rain."
```

## Adding a pulse in a fork

Rules that keep pulses cheap and safe:

1. **Create it paused**, run it once with `hermes cron run`, read the output,
   then resume. Use `--paused --paused-reason "..."` on create.
2. **Pass `--workdir ~/.hermes`** so the run loads AGENTS.md. SOUL.md loads
   regardless.
3. **Attach the skill** with `--skill <name>` rather than describing the API in
   the prompt.
4. **Stay read-only.** A pulse runs unattended; anything that would need the
   operator's go-ahead in chat does not belong in a pulse.
5. **Prefer silence.** Ask for output only when something changed. For pure
   threshold checks, a `--no-agent --script` job costs no model call at all.
6. **Name it** with a fork prefix (`acme-pipeline-digest`) so `cron list` stays
   readable.

Example:

```bash
hermes cron create "0 8 * * 1-5" \
  "Summarize deals that changed stage since yesterday. If none, reply with nothing." \
  --name acme-deal-digest --skill hubspot-read --deliver telegram \
  --workdir ~/.hermes --paused --paused-reason "First run review"
```

Record each new pulse in the table above in the fork's copy of this file.

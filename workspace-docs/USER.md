# USER.md

Operator intake sheet. Fill it in per deployment, keep it in the fork, and
never deploy it.

Why it stays out of `~/.hermes/`: Hermes keeps its own `USER.md` under
`~/.hermes/memories/`, written by the agent through its memory tool. A second
hand-edited copy would compete with it. Use this sheet to decide what goes into
`SOUL.md` (durable role and tone) and what to tell the agent so it saves the
fact to memory itself.
([Which file does what](https://hermes-agent.nousresearch.com/docs/user-guide/which-file-does-what))

## Operator

- Name:
- Role:
- Time zone (also set `HERMES_TIMEZONE` in `.env`):
- Preferred units (metric or imperial):
- Working hours (pulses should land just before these):

## Business

- Company and what it does, in one sentence:
- Who the clients are:
- Systems of record (CRM, accounting, documents):
- Words the business uses that an outsider would not know:

## Assistant scope

- Top three jobs it should do every week:
- Things it must never do (beyond SOUL.md's non-negotiables):
- Who else, if anyone, may see its output:

## Credentials requested

One line per system. Read-only unless a write scope is justified here.

| System | Variable name in `.env` | Scopes | Write access? Why? |
|--------|-------------------------|--------|--------------------|
| Telegram | `TELEGRAM_BOT_TOKEN` | Bot | n/a |
| | | | |

## Where each answer went

- [ ] Role and tone reflected in `workspace/SOUL.md`
- [ ] Procedures reflected in `workspace/AGENTS.md`
- [ ] Personal facts told to the agent in chat (it stores them in memory)
- [ ] Credentials placed in `~/.hermes/.env` on the host, nowhere else

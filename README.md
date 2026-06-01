# Workflow Intelligence Kit

Reusable foundation for deploying client-specific AI assistants and workflow automation for service businesses.

**Status:** Design locked; v1 scaffolding underway. The architectural decisions are settled, but the install scripts, systemd templates, and operator docs referenced below have not yet landed in the repo. This README documents the shape of the system, not its current contents.

## What this is

Workflow Intelligence Kit is an upstream foundation for business-specific AI assistants. It exists to be forked and adapted for real operating contexts: a sales assistant that supports HubSpot CRM cleanup and deal intelligence, a CPA assistant that supports QuickBooks and client intake, or a real-estate/insurance assistant that handles lead qualification, research, proposal support, document analysis, and internal knowledge workflows.

Each downstream fork inherits the same skeleton: install script, hardening orchestration, workspace seeds, reference skill, systemd templates, and operator docs. The fork then adds its domain: CRM integration and sales workflows in one case; QuickBooks and client-intake heuristics in another. The kit stays generic. The fork carries the integration. Drift between forks is intentional, not accidental.

## Lineage

The pattern, the discipline, and most of the install ergonomics come from RShuken/flyn-agent and the postmortem Ryan published after his first month running it. flyn-agent was the load-bearing reference during design; the gotchas it surfaced — install ordering, secrets layering, the real cost of MCP-to-agent-turn scaffolding on the framework versions we care about — shaped what this kit does and does not include. The framework target is Hermes Agent, NousResearch's MIT-licensed successor to OpenClaw.

## Design shape

v1 targets Ubuntu 24.04 LTS on a Hetzner-class VPS, deliberately avoiding provider lock-in and Mac-specific paths. systemd handles services, not launchd; Hermes Agent handles the agent loop, memory, and built-in tooling, so this kit does not reinvent any of it. Authentication is Codex OAuth on a single tier: both interactive turns and background pulses run through the same credential, with a cheaper background tier deferred until pulse volume justifies the split.

The audience is single-operator and Telegram-only: drafting, thinking, intake, research, summaries, and internal operations, with no customer-facing surface in v1. Data access is read-only by design where possible: scoped private-app tokens for the SaaS systems each fork talks to, no write scopes requested unless the fork explicitly needs them, email is drafts-only by policy, and credentials live in Hermes's `.env` rather than a parallel auth-profile layer that would create dual state.

## Use cases

The kit is built for practical business workflows, not demo-only chatbots:

- Lead qualification and customer intake
- HubSpot CRM cleanup and deal intelligence
- QuickBooks-supported CPA intake workflows
- Proposal generation and content drafting
- Research and competitive intelligence
- Document analysis and summarization
- Internal wiki/search assistants and knowledge workflows
- Human-in-the-loop review for high-trust operations

## Scope and non-goals

In v1:

- Idempotent `install.sh` targeting fresh Ubuntu 24.04 hosts
- Hardening orchestration: `harden.sh` plus `ufw-rules.sh`, `ssh-hardening.sh`, `fail2ban-setup.sh`, `unattended-upgrades.sh`
- Workspace file pattern: `SOUL.md` and `AGENTS.md` deployed to `~/.hermes/`, plus operator-facing `BOOTSTRAP.md`, `HEARTBEAT.md`, `USER.md` that never deploy
- Reference skill: weather via Open-Meteo, no API key, two-call REST pattern that real CRM and SaaS skills can mirror
- A single systemd unit template, rendered at install time
- Scheduled pulses via Hermes's built-in `hermes cron create` rather than custom systemd timer scaffolding

Explicitly out:

- MCP-to-agent-turn scaffolding that is brittle on the framework versions we target
- Local GPU model assumptions
- Mac and launchd paths
- Committed live config (`hermes.json` or equivalent)
- A `deploy/auth-profiles/` layer parallel to Hermes's `.env`
- A generic `deploy/kg/` knowledge-graph layer; that decision belongs in each fork's scope, not the base

## What lives where

Implementation will land in `install.sh`, `deploy/hardening/`, `deploy/skills/workflow-intelligence-reference/weather/`, `deploy/systemd/`, `workspace/`, and `workspace-docs/`. Deeper rationale and deviations from the reference architecture will live in `docs/ARCHITECTURE.md`; per-host setup walks through `BOOTSTRAP.md`. None of these paths exist in the repo yet; they appear as the build executes.

## License

MIT.

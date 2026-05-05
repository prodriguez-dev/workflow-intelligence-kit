# agent-base

Upstream base for personal AI-agent deploys on a Linux VPS.

**Status:** Design locked; v1 scaffolding underway. The architectural decisions are settled, but the install scripts, systemd templates, and operator docs referenced below have not yet landed in the repo. This README documents the shape of the system, not its current contents.

## What this is

This repo is the upstream base. It exists to be forked. Each downstream fork — `marketing-agent` for a CMO running HubSpot, `cpa-agent` for a sole practitioner on QuickBooks, and so on — inherits the same skeleton: install script, hardening orchestration, workspace seeds, reference skill, systemd templates. The fork then adds its domain: HubSpot integration and brand-specific workspace files in marketing-agent's case; QuickBooks and tax-season heuristics in cpa-agent's. The base stays generic. The fork carries the integration. Drift between forks is intentional, not accidental.

## Lineage

The pattern, the discipline, and most of the install ergonomics come from RShuken/flyn-agent and the postmortem Ryan published on 2026-04-21 after his first month running it. flyn-agent was the load-bearing reference during design; the gotchas it surfaced — install ordering, secrets layering, the real cost of MCP-to-agent-turn scaffolding on the framework versions we care about — shaped what this base does and does not include. The framework target is Hermes Agent, NousResearch's MIT-licensed successor to OpenClaw 🦞.

## Design shape

v1 targets Ubuntu 24.04 LTS on a Hetzner-class VPS, deliberately avoiding provider lock-in and Mac-specific paths. systemd handles services, not launchd; Hermes Agent handles the agent loop, memory, and built-in tooling, so this base does not reinvent any of it. Authentication is Codex OAuth on a single tier — both interactive turns and background pulses run through the same credential, with a Haiku-for-background tier deferred until pulse volume justifies the split. The audience is single-operator and Telegram-only: drafting, thinking, and voice-memo capture, with no customer-facing surface in v1. Data access is read-only by design — scoped private-app tokens for the SaaS systems each fork talks to, no write scopes requested, email is drafts-only by policy, and credentials live in Hermes's `.env` rather than a parallel auth-profile layer that would create dual state.

## Scope and non-goals

In v1:

- Idempotent `install.sh` (nine steps) targeting fresh Ubuntu 24.04 hosts
- Hardening orchestration: `harden.sh` plus `ufw-rules.sh`, `ssh-hardening.sh`, `fail2ban-setup.sh`, `unattended-upgrades.sh`
- Workspace file pattern: `SOUL.md` and `AGENTS.md` deployed to `~/.hermes/`, plus operator-facing `BOOTSTRAP.md`, `HEARTBEAT.md`, `USER.md` that never deploy
- Reference skill: weather via Open-Meteo, no API key, two-call REST pattern that real CRM and SaaS skills will mirror
- A single systemd unit template, rendered at install time
- Scheduled pulses via Hermes's built-in `hermes cron create` rather than custom systemd timer scaffolding

Explicitly out:

- MCP-to-agent-turn scaffolding (brittle on the framework versions we target)
- Local GPU model assumptions (VPS hosts at this price class don't have them)
- Mac and launchd paths
- Committed live config (`hermes.json` or equivalent)
- A `deploy/auth-profiles/` layer parallel to Hermes's `.env`
- A `deploy/kg/` knowledge-graph layer — that decision belongs in each fork's scope, not the base

## What lives where

Implementation will land in `install.sh`, `deploy/hardening/`, `deploy/skills/agent-base-reference/weather/`, `deploy/systemd/`, `workspace/`, and `workspace-docs/`. Deeper rationale and the deviations from flyn-agent will live in `docs/ARCHITECTURE.md`; per-host setup walks through `BOOTSTRAP.md`. None of these paths exist in the repo yet — they appear as Step 3 of the build executes.

## License

MIT (mirrors Hermes Agent; confirm before first public push).

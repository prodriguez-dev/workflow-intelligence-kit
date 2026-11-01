# Architecture

This document records the decisions behind the v1 scaffolding and where it
deviates from the README's shorthand. The README stays the scope contract; this
file explains how the scaffolding meets it.

Hermes Agent behavior cited here was checked against the official docs at
https://hermes-agent.nousresearch.com/docs/ (Hermes v0.22.x, October 2026).
Each script also cites the specific page it depends on.

## Layout on the host

| Path | Owner | Written by | Purpose |
|------|-------|------------|---------|
| `/opt/workflow-intelligence-kit/` (any path) | root | git clone | The kit checkout. install.sh runs from here |
| `/home/hermes/` | hermes | `useradd` | Service user home |
| `/home/hermes/.hermes/` | hermes | Hermes installer | `HERMES_HOME`: config, `.env`, memories, sessions, skills, cron |
| `/home/hermes/.hermes/hermes-agent/` | hermes | Hermes installer | Hermes source checkout |
| `/home/hermes/.local/bin/hermes` | hermes | Hermes installer | CLI wrapper |
| `/home/hermes/.hermes/{SOUL,AGENTS}.md` | hermes | install.sh | Workspace seeds |
| `/home/hermes/.hermes/skills/workflow-intelligence-reference/` | hermes | install.sh | Reference skill |
| `/home/hermes/.hermes/.wik-managed` | hermes | install.sh | Checksums of kit-deployed files |
| `/home/hermes/.config/systemd/user/hermes-gateway.service.d/workflow-intelligence.conf` | hermes | install.sh | Gateway drop-in |
| `/etc/ssh/sshd_config.d/10-wik-hardening.conf` | root | ssh-hardening.sh | Key-only SSH |
| `/etc/fail2ban/jail.d/wik-sshd.local` | root | fail2ban-setup.sh | sshd jail |
| `/etc/apt/apt.conf.d/{20auto-upgrades,52wik-unattended-upgrades}` | root | unattended-upgrades.sh | Security updates |

The service user name defaults to `hermes` and is set with `WIK_USER`.

## Install model

**Run as root, install as the service user.** install.sh needs root for
packages, hardening, the user account, and lingering. Hermes itself is
installed by running the official installer as the service user, which is what
the Hermes docs prescribe for service accounts: running the installer as root
would put everything in root's home.
([Non-sudo / system service user installs](https://hermes-agent.nousresearch.com/docs/getting-started/installation#non-sudo--system-service-user-installs))

**Idempotency is check-then-act.** Every step reads current state first and acts
only on a difference: packages via `dpkg-query`, files via `cmp` plus mode and
owner, ufw via `ufw status verbose`, users via `id`, lingering via
`/var/lib/systemd/linger/`, the pulse via `cron/jobs.json`. Each script counts
the changes it makes and prints the total, so a second run reporting
`0 change(s)` is the idempotency check. Files are written to a temp name and
renamed, so a reader never sees a partial file.

**Dry run is a mode of the same code path,** not a separate script. State
changes go through one helper (`run` in `deploy/lib/common.sh`) that prints
instead of executing; file writes print a diff or the full new content.
Read-only probes still run, so the dry run reflects the real host.

**Hermes is installed once, then owned by Hermes.** If `~/.local/bin/hermes`
exists, install.sh leaves it alone. Upgrades are `hermes update`, run by the
operator as the service user. Pin a version for reproducible hosts with
`WIK_HERMES_COMMIT` (passed to the installer's `--commit`).

Installer flags used, all from the installer's own `--help`:

- `--non-interactive`: skip setup and gateway prompts; BOOTSTRAP.md covers them.
- `--skip-browser`, `--skip-computer-use`: a headless, Telegram-only assistant
  has no use for Chromium or a desktop driver, and fewer binaries means a
  smaller patch surface. A fork that needs browsing runs
  `hermes pm install agent-browser`.

`libatomic1` is installed up front because Hermes's managed Node.js links it and
the installer would otherwise try `sudo -n`, which the service user cannot do.

The installer is fetched over HTTPS from the documented URL. Hermes does not
publish a checksum for it, so there is nothing to verify against beyond TLS.
TODO: if Hermes starts publishing installer checksums or signatures, verify
them here; until then, pinning `WIK_HERMES_COMMIT` is the reproducibility lever.

## Workspace files

**SOUL.md** is loaded by Hermes from `HERMES_HOME` only, into the first slot of
the system prompt, in every session including cron runs. The kit puts its
non-negotiables (read-only, drafts-only email, secrets, no escalation) here
because it is the one file guaranteed to load everywhere.
([Context files](https://hermes-agent.nousresearch.com/docs/user-guide/features/context-files))

**AGENTS.md** is not read from `HERMES_HOME`. Hermes loads it from the turn's
working directory. Gateway turns start in `terminal.cwd`, or `$HOME` when that
is unset. So install.sh sets `terminal.cwd` to `~/.hermes` (only if the
operator has not set it), and the reference pulse is created with
`--workdir ~/.hermes`. That makes "AGENTS.md deployed to `~/.hermes/`" from the
README actually take effect.
([Configuration: working directory](https://hermes-agent.nousresearch.com/docs/user-guide/configuration))

The cost is that agent shell commands start in the directory that holds
`.env`. With Hermes's local backend the agent can already read anything the
service user can, so this changes the default path, not the exposure. The
mitigations are the SOUL.md secrets rule, a dedicated service user with no
sudo, and `NoNewPrivileges` on the gateway.

**Managed-file policy.** Hermes seeds a starter SOUL.md on first run and the
operator may edit deployed files on the host. install.sh tracks the checksum of
every file it deploys in `~/.hermes/.wik-managed`:

| Live file | Action |
|-----------|--------|
| Missing | Deploy |
| Same as the kit's | No change |
| Matches the checksum install.sh last deployed | Update to the new kit version |
| Never deployed by the kit (for example Hermes's starter SOUL.md) | Back up to `<file>.pre-wik.<timestamp>`, then deploy |
| Edited since install.sh deployed it | Leave it, print a warning |

The intended workflow is to change `workspace/` in the fork and re-run
install.sh, not to edit the host.

**workspace-docs/ never deploys.** BOOTSTRAP.md and HEARTBEAT.md are operator
runbooks. USER.md is an intake sheet; it stays out of `~/.hermes/` because
Hermes keeps its own agent-written `USER.md` under `~/.hermes/memories/`, and a
hand-edited copy would compete with it.
([Which file does what](https://hermes-agent.nousresearch.com/docs/user-guide/which-file-does-what))
HEARTBEAT.md is unrelated to Hermes's `/heartbeat` chat command; it documents
cron pulses.

## systemd

**Deviation from the README wording.** The README calls for "a single systemd
unit template, rendered at install time." The template that ships is a
**drop-in** for Hermes's own unit, not a standalone unit:
`deploy/systemd/hermes-gateway-wik.conf.in`, rendered to
`~/.config/systemd/user/hermes-gateway.service.d/workflow-intelligence.conf`.

Why not a full unit:

- `hermes gateway install` generates `hermes-gateway.service` with
  install-specific paths (launcher, managed Node and npm, `HERMES_HOME`) and
  lifecycle hooks (a planned-stop marker in `ExecStop`, cgroup cleanup, exit
  code 75 for supervised restarts).
- `hermes update` and `hermes gateway status` compare the installed unit with
  the one Hermes would generate and repair it when it differs. A kit-owned unit
  under the same name would be overwritten; one under another name would miss
  Hermes's restart and update handling, and the docs warn against running two
  gateway units.
- A drop-in survives regeneration and still gives the kit one rendered file to
  own.

([Service management](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/#service-management))

What the drop-in sets:

- `NoNewPrivileges=yes`: agent turns run shell commands inside this service;
  nothing in the read-only design needs sudo or setuid binaries. One side effect:
  if Hermes ever needs root during an in-chat update (for example to install a
  distro library), that step fails and Hermes prints the command for the
  operator to run, which is the intended outcome.
- `UMask=0077`: sessions, memories, and logs are private to the service user.
- `MemoryMax=` (default `75%`, `WIK_GATEWAY_MEMORY_MAX`): a ceiling for a
  runaway turn. It applies only where the memory controller is delegated to the
  user manager; otherwise systemd ignores it.

The drop-in deliberately avoids `ExecStopPost=`, which the Hermes docs say
causes a restart loop.

**User service with lingering, not a system service.** The Hermes docs
recommend a user service plus `loginctl enable-linger` for headless hosts: it
starts at boot, and `hermes update` can restart it without root. install.sh
enables lingering; the operator runs `hermes gateway install` in BOOTSTRAP.md
step 6, after credentials exist, so the gateway never starts unconfigured.

**No kit timers.** Scheduled work runs in the Hermes cron ticker inside the
gateway, per the README.

## Scheduled pulses

The reference pulse is created with:

```text
hermes cron create "0 7 * * *" "<prompt>" --name wik-reference-weather \
  --skill weather --deliver telegram --workdir ~/.hermes \
  --paused --paused-reason "..."
```

Every flag is in `hermes cron create --help` and the
[cron docs](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron).
It is created paused because delivery needs the Telegram home channel, which
does not exist until BOOTSTRAP.md step 6. install.sh detects an existing job by
name in `~/.hermes/cron/jobs.json`, so re-runs never duplicate it.

## Secrets

- Credentials live only in `~/.hermes/.env`, mode 600, owned by the service
  user. install.sh creates the file empty if missing and fixes its permissions;
  it never writes values.
- Codex OAuth is set up with `hermes model` and stored in Hermes's own auth
  store. It never appears in `.env` or in the repo.
- `.env.example` lists the names the kit uses, with empty values.
- There is no `deploy/auth-profiles/` layer (README: explicitly out).

## Read-only posture

Layers, from strongest to weakest:

1. **Credentials.** Forks request read-only scopes. A missing write scope is the
   only control that holds even if the model misbehaves.
2. **OS.** Dedicated user, no sudo, `NoNewPrivileges` on the gateway.
3. **Policy.** SOUL.md non-negotiables: read-only by default, drafts-only email,
   secrets never printed, no escalation.

Email drafts-only is a policy in v1: the kit ships no email integration. A fork
that adds one should enforce it at the credential (drafts scope only) as well.

## Hardening

`harden.sh` runs four standalone scripts in a fixed order:

1. `unattended-upgrades.sh`: enables the daily security run. Auto-reboot is off
   by default (`WIK_AUTO_REBOOT`), so a reboot never lands mid-conversation.
2. `fail2ban-setup.sh`: sshd jail on the systemd journal backend, in a `.local`
   file so package upgrades never prompt about it.
3. `ssh-hardening.sh`: key-only auth in `sshd_config.d/10-wik-hardening.conf`.
   The `10-` prefix sorts before cloud-init's `50-cloud-init.conf`, and sshd
   keeps the first value it reads.
4. `ufw-rules.sh`: deny inbound, allow outbound, rate-limited SSH. Last, so it
   only runs once SSH is known good. The SSH rule is added before ufw is
   enabled.

Lockout guards in `ssh-hardening.sh`:

- It refuses to disable password login unless root or `WIK_ADMIN_USER` has an
  authorized key.
- `PermitRootLogin no` only when `WIK_ADMIN_USER` has a key and sudo; otherwise
  `prohibit-password`.
- `sshd -t` validates the result; on failure the previous file is restored.
- It reloads with `try-reload-or-restart`, which keeps existing sessions.

The SSH port is not moved. Ubuntu 24.04 runs sshd socket-activated, so moving
the port means overriding `ssh.socket`, and the security gain over key-only auth
with fail2ban is small. `WIK_SSH_PORT` exists for hosts where sshd already
listens elsewhere.

Telegram uses outbound long polling, so no inbound port besides SSH is opened.

## Reference skill

`deploy/skills/workflow-intelligence-reference/weather/` follows the Hermes
SKILL.md format and is deployed to `~/.hermes/skills/<category>/<skill>/`.
([Skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills),
[Creating skills](https://hermes-agent.nousresearch.com/docs/developer-guide/creating-skills))

The pattern forks copy:

1. Call 1 resolves a human identifier to a stable ID (place name to
   coordinates; in a CRM, company name to record ID).
2. Call 2 reads by that ID.
3. Each call fails with its own exit code (not found vs unreachable), so the
   agent reports the right thing instead of guessing.
4. Output is one compact JSON object the agent can quote.

The SKILL.md runs its script through `${HERMES_SKILL_DIR}`, which Hermes
substitutes with the skill's absolute path when the skill loads.

## Known gaps

- TODO: installer checksum verification (see Install model).
- `MemoryMax` is best effort; see systemd above.
- The kit does not move sshd off port 22 (see Hardening).

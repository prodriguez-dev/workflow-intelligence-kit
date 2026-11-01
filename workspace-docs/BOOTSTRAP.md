# BOOTSTRAP.md

Per-host setup, from a fresh Ubuntu 24.04 VPS to an assistant answering on
Telegram. Operator-facing: this file is never deployed to the host's `~/.hermes/`.

Commands marked `root$` run as root (or with sudo). Commands marked `hermes$`
run as the service user (`sudo -iu hermes`).

## 0. Before you start

- A Ubuntu 24.04 LTS VPS with your SSH public key installed for root (Hetzner
  and most providers do this at creation time).
- A ChatGPT plan that includes Codex, for the Codex OAuth sign-in.
- A Telegram account.

Optional but recommended: create a non-root admin user with your key and sudo,
so hardening can disable root login entirely:

```bash
root$ adduser --disabled-password --gecos "" ops
root$ usermod -aG sudo ops
root$ install -d -m 700 -o ops -g ops /home/ops/.ssh
root$ install -m 600 -o ops -g ops /root/.ssh/authorized_keys /home/ops/.ssh/authorized_keys
root$ passwd ops    # sudo needs a password; SSH login stays key-only
```

Then pass `WIK_ADMIN_USER=ops` to install.sh below. Without it, root login
stays enabled but key-only (`PermitRootLogin prohibit-password`).

## 1. Get the kit onto the host

```bash
root$ apt-get update && apt-get install -y git
root$ git clone https://github.com/prodriguez-dev/workflow-intelligence-kit.git /opt/workflow-intelligence-kit
root$ cd /opt/workflow-intelligence-kit
```

For a fork, clone the fork instead.

## 2. Dry run, then install

```bash
root$ ./install.sh --dry-run          # read every planned action
root$ WIK_ADMIN_USER=ops ./install.sh # or just ./install.sh
```

Keep your current SSH session open until step 3 succeeds. Hardening validates
the SSH config before reloading and keeps existing sessions, but a second
session is the real test.

Re-running `./install.sh` is safe. A second run should end with
`done: 0 change(s) made` (plus a per-step count from each hardening script).

Useful variables (see `./install.sh --help`): `WIK_HERMES_COMMIT` to pin Hermes,
`WIK_PULSE_LOCATION` for the reference pulse, `WIK_SSH_PORT` if sshd already
listens on a non-default port.

## 3. Confirm you can still get in

From your workstation, in a **new** terminal:

```bash
ssh ops@<host>      # or root@<host> if you skipped the admin user
```

If that fails, fix it from the session you kept open:
`rm /etc/ssh/sshd_config.d/10-wik-hardening.conf && systemctl reload ssh`.

## 4. Sign in to Codex

```bash
root$ sudo -iu hermes
hermes$ hermes model
```

Choose the OpenAI Codex provider and a model. The default sign-in is a device
code: open the printed URL on any device, approve, and Hermes polls until it
completes. No SSH tunnel is needed.
([OAuth over SSH](https://hermes-agent.nousresearch.com/docs/guides/oauth-over-ssh))

Check it: `hermes auth status openai-codex`.

## 5. Connect Telegram

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`,
   and copy the token.
2. Message [@userinfobot](https://t.me/userinfobot) to get your numeric user ID.
3. Put both in the service user's `.env` (see `.env.example` in the repo for
   every name the kit uses):

   ```bash
   hermes$ nano ~/.hermes/.env
   ```

   ```text
   TELEGRAM_BOT_TOKEN=<token from BotFather>
   TELEGRAM_ALLOWED_USERS=<your user id>
   HERMES_TIMEZONE=<your IANA zone, e.g. America/Denver>
   ```

   An editor keeps the token out of shell history. `hermes gateway setup` is
   the interactive alternative.
   ([Telegram setup](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram))

## 6. Start the gateway

```bash
hermes$ hermes gateway install   # user service; lingering is already enabled
hermes$ hermes gateway start
hermes$ hermes gateway status
```

The kit's drop-in (`~/.config/systemd/user/hermes-gateway.service.d/workflow-intelligence.conf`)
applies automatically. Confirm with
`systemctl --user cat hermes-gateway.service`: the drop-in appears after the unit.
([Service management](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/#service-management))

Send the bot a message. In the chat, send `/sethome` so scheduled pulses have a
destination.

## 7. Turn on the reference pulse

install.sh created `wik-reference-weather` paused. See HEARTBEAT.md for what it
does and how to change it.

```bash
hermes$ hermes cron list --all       # note the job id
hermes$ hermes cron run <job_id>     # one test run on the next tick
hermes$ hermes cron resume <job_id>  # schedule it
```

## 8. Fill in the fork

- Edit `~/.hermes/SOUL.md` on the host only if this host differs from the fork.
  Prefer changing `workspace/SOUL.md` in the fork and re-running install.sh.
  install.sh will not overwrite a deployed file you edited by hand; it warns
  instead.
- Use USER.md (this directory) to collect operator facts, then tell the agent
  the ones it should remember.

## Health checks

```bash
hermes$ hermes doctor
hermes$ hermes cron doctor
hermes$ journalctl --user -u hermes-gateway -n 50
root$  ufw status verbose
root$  fail2ban-client status sshd
```

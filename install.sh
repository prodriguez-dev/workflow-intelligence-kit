#!/usr/bin/env bash
# Workflow Intelligence Kit installer for a fresh Ubuntu 24.04 host.
#
# Idempotent: every step checks current state first, so a second run on the same
# host reports "0 change(s)". --dry-run prints every action and changes nothing.
#
# Steps:
#   1. Base packages Hermes's installer expects
#   2. Host hardening (deploy/hardening/harden.sh), unless --skip-hardening
#   3. Unprivileged service user, with systemd lingering
#   4. Hermes Agent, via the official installer, run as the service user
#   5. Workspace seeds (SOUL.md, AGENTS.md) and the reference skill
#   6. terminal.cwd, so gateway turns load AGENTS.md
#   7. .env permissions (credentials themselves are never written here)
#   8. systemd drop-in for the Hermes gateway user unit
#   9. Reference pulse via `hermes cron create`, created paused
#
# Operator steps that need a human (Codex OAuth, Telegram bot token, starting the
# gateway) are in workspace-docs/BOOTSTRAP.md.
set -euo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIK_LOG_PREFIX="install"
# shellcheck source=deploy/lib/common.sh
. "$KIT_DIR/deploy/lib/common.sh"

WIK_USER="${WIK_USER:-hermes}"
# Official one-line installer for Linux, macOS, and WSL2.
# https://hermes-agent.nousresearch.com/docs/getting-started/installation
HERMES_INSTALL_URL="${WIK_HERMES_INSTALL_URL:-https://hermes-agent.nousresearch.com/install.sh}"
HERMES_COMMIT="${WIK_HERMES_COMMIT:-}"
GATEWAY_MEMORY_MAX="${WIK_GATEWAY_MEMORY_MAX:-75%}"
PULSE_NAME="wik-reference-weather"
PULSE_SCHEDULE="${WIK_PULSE_SCHEDULE:-0 7 * * *}"
PULSE_LOCATION="${WIK_PULSE_LOCATION:-London, GB}"
SKIP_HARDENING=0

usage() {
  cat <<'EOF'
Usage: sudo ./install.sh [--dry-run] [--skip-hardening]

  --dry-run          Print every action without changing the system.
  --skip-hardening   Skip deploy/hardening/harden.sh (for hosts hardened elsewhere).

Environment (all optional):
  WIK_USER                 Service user that runs Hermes (default: hermes)
  WIK_HERMES_COMMIT        Pin Hermes to a commit (passed as --commit)
  WIK_HERMES_INSTALL_URL   Hermes installer URL (default: the official one)
  WIK_GATEWAY_MEMORY_MAX   MemoryMax for the gateway, e.g. 75% or 2G (default: 75%)
  WIK_PULSE_LOCATION       Place for the reference weather pulse (default: London, GB)
  WIK_PULSE_SCHEDULE       Cron expression for the pulse (default: 0 7 * * *)
  WIK_ALLOW_UNSUPPORTED=1  Run on something other than Ubuntu 24.04
  Hardening variables (WIK_SSH_PORT, WIK_ADMIN_USER, WIK_AUTO_REBOOT, ...)
  are documented in each deploy/hardening/*.sh --help.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --dry-run) WIK_DRY_RUN=1 ;;
    --skip-hardening) SKIP_HARDENING=1 ;;
    -h | --help)
      usage
      exit 0
      ;;
    *) die "unknown option: $arg (see --help)" ;;
  esac
done
export WIK_DRY_RUN

# --- Preflight ---------------------------------------------------------------

os_id="" os_version=""
if [ -r /etc/os-release ]; then
  os_id="$(. /etc/os-release && printf '%s' "${ID:-}")"
  os_version="$(. /etc/os-release && printf '%s' "${VERSION_ID:-}")"
fi
if [ "$os_id" != ubuntu ] || [ "$os_version" != 24.04 ]; then
  if is_dry_run || [ "${WIK_ALLOW_UNSUPPORTED:-0}" = 1 ]; then
    warn "targets Ubuntu 24.04; this host is ${os_id:-unknown} ${os_version:-unknown}"
  else
    die "targets Ubuntu 24.04; this host is ${os_id:-unknown} ${os_version:-unknown} (set WIK_ALLOW_UNSUPPORTED=1 to override)"
  fi
fi
require_root

[[ "$WIK_USER" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || die "WIK_USER is not a valid user name: $WIK_USER"
[ "$WIK_USER" != root ] || die "WIK_USER must not be root; Hermes runs unprivileged"
[[ "$GATEWAY_MEMORY_MAX" =~ ^([0-9]+[KMGT]?|[0-9]{1,2}%|100%|infinity)$ ]] ||
  die "WIK_GATEWAY_MEMORY_MAX must look like 75%, 2G, or infinity, got: $GATEWAY_MEMORY_MAX"

# --- 1. Base packages --------------------------------------------------------

log "step 1: base packages"
# git, curl, tar, and sha256sum are the source installer's documented
# prerequisites. libatomic1 is needed by Hermes's managed Node.js; the installer
# would try `sudo -n` for it, which the unprivileged service user cannot do.
# https://hermes-agent.nousresearch.com/docs/getting-started/installation#prerequisites
# python3 is used here to read cron/jobs.json and by the skill scripts. tzdata
# backs Python's zoneinfo, which estimate-followup uses for its business time zone.
ensure_packages ca-certificates curl git tar coreutils libatomic1 python3 tzdata

# --- 2. Hardening ------------------------------------------------------------

if [ "$SKIP_HARDENING" = 1 ]; then
  log "step 2: hardening skipped (--skip-hardening)"
else
  log "step 2: hardening"
  bash "$KIT_DIR/deploy/hardening/harden.sh"
fi

# --- 3. Service user ---------------------------------------------------------

log "step 3: service user $WIK_USER"
if id -u "$WIK_USER" >/dev/null 2>&1; then
  log "user exists: $WIK_USER"
else
  # No password and no sudo: the account is reachable only via root.
  run useradd --create-home --shell /bin/bash --comment "Hermes Agent (workflow-intelligence-kit)" "$WIK_USER"
fi
WIK_HOME="$(getent passwd "$WIK_USER" | cut -d: -f6 || true)"
WIK_HOME="${WIK_HOME:-/home/$WIK_USER}"
HERMES_HOME="$WIK_HOME/.hermes"
HERMES_BIN="$WIK_HOME/.local/bin/hermes"

# Lingering starts the user's systemd manager at boot, so the gateway user
# service runs without anyone logged in.
# https://hermes-agent.nousresearch.com/docs/getting-started/installation#non-sudo--system-service-user-installs
if ! has_systemd; then
  warn "systemd is not running here; skipping lingering and user units"
elif [ -f "/var/lib/systemd/linger/$WIK_USER" ]; then
  log "lingering already enabled for $WIK_USER"
else
  run loginctl enable-linger "$WIK_USER"
fi

user_uid() { id -u "$WIK_USER" 2>/dev/null || echo 0; }

# as_user CMD...: run CMD as the service user with a clean login-like environment.
as_user() {
  runuser -u "$WIK_USER" -- env -i -C "$WIK_HOME" \
    HOME="$WIK_HOME" USER="$WIK_USER" LOGNAME="$WIK_USER" SHELL=/bin/bash \
    LANG="${LANG:-C.UTF-8}" PATH="$WIK_HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" \
    XDG_RUNTIME_DIR="/run/user/$(user_uid)" HERMES_HOME="$HERMES_HOME" "$@"
}

# ensure_user_path DIR: create DIR and any missing parents under $WIK_HOME,
# each owned by the service user (install -D would leave parents owned by root).
ensure_user_path() {
  local rel="${1#"$WIK_HOME"/}" cur="$WIK_HOME" part
  local -a parts
  IFS='/' read -ra parts <<<"$rel"
  for part in "${parts[@]}"; do
    cur="$cur/$part"
    ensure_dir "$cur" 0700 "$WIK_USER"
  done
}

# --- 4. Hermes Agent ---------------------------------------------------------

log "step 4: Hermes Agent"
if [ -x "$HERMES_BIN" ]; then
  log "Hermes present: $(as_user "$HERMES_BIN" --version 2>/dev/null | head -n 1 || echo unknown version)"
  log "upgrades are Hermes's job: run 'hermes update' as $WIK_USER"
else
  # --non-interactive skips setup and gateway prompts (BOOTSTRAP.md covers them).
  # Browser and computer-use tools are skipped: a headless, Telegram-only
  # assistant does not drive a desktop, and fewer binaries means less to patch.
  installer_args=(--non-interactive --skip-browser --skip-computer-use)
  [ -n "$HERMES_COMMIT" ] && installer_args+=(--commit "$HERMES_COMMIT")
  if is_dry_run; then
    WIK_CHANGES=$((WIK_CHANGES + 1))
    printf '[dry-run] download %s and run it as %s: bash -s -- %s\n' \
      "$HERMES_INSTALL_URL" "$WIK_USER" "${installer_args[*]}"
  else
    installer="$WIK_TMPDIR/hermes-install.sh"
    curl -fsSL --proto '=https' --tlsv1.2 "$HERMES_INSTALL_URL" -o "$installer"
    # Piped on stdin, as with the documented `curl ... | bash`, so the
    # service user never needs to read root's temp directory.
    run as_user bash -s -- "${installer_args[@]}" <"$installer"
    [ -x "$HERMES_BIN" ] || die "Hermes installer finished but $HERMES_BIN is missing"
  fi
fi

# --- 5. Workspace and reference skill ----------------------------------------

log "step 5: workspace seeds and reference skill"
# Files the kit deploys into ~/.hermes are tracked by checksum in this state
# file. A deployed file that the operator has since edited is left alone (with a
# warning); a pre-existing file the kit never deployed, such as the starter
# SOUL.md Hermes seeds on first run, is backed up once and then replaced.
STATE_FILE="$HERMES_HOME/.wik-managed"
declare -A managed_sha=()
if [ -f "$STATE_FILE" ]; then
  while read -r sha path; do
    [ -n "$path" ] && managed_sha["$path"]="$sha"
  done <"$STATE_FILE"
fi

sha_of() { sha256sum "$1" | cut -d' ' -f1; }

# deploy_managed SRC REL MODE: deploy SRC to $HERMES_HOME/REL.
deploy_managed() {
  local src="$1" rel="$2" mode="$3"
  local dest="$HERMES_HOME/$rel" src_sha live_sha recorded
  src_sha="$(sha_of "$src")"
  recorded="${managed_sha[$rel]:-}"
  ensure_user_path "$(dirname "$dest")"

  if [ -f "$dest" ]; then
    live_sha="$(sha_of "$dest")"
    if [ "$live_sha" != "$src_sha" ] && [ -n "$recorded" ] && [ "$live_sha" != "$recorded" ]; then
      warn "kept local edits in $dest; the kit version is $src (diff them, or delete $dest and re-run)"
      return 0
    fi
    if [ "$live_sha" != "$src_sha" ] && [ -z "$recorded" ]; then
      run cp -p "$dest" "$dest.pre-wik.$(date +%Y%m%d%H%M%S)"
    fi
  fi
  write_file "$src" "$dest" "$mode" "$WIK_USER"
  managed_sha["$rel"]="$src_sha"
}

deploy_managed "$KIT_DIR/workspace/SOUL.md" SOUL.md 0644
deploy_managed "$KIT_DIR/workspace/AGENTS.md" AGENTS.md 0644

# Skills live under ~/.hermes/skills/<category>/<skill>/.
# https://hermes-agent.nousresearch.com/docs/user-guide/features/skills#skill-directory-structure
# Skill tests and Python bytecode stay in the checkout; the host gets only what
# the agent runs.
skill_src="$KIT_DIR/deploy/skills"
while IFS= read -r -d '' file; do
  rel="skills/${file#"$skill_src"/}"
  case "$file" in
    */scripts/*) mode=0755 ;;
    *) mode=0644 ;;
  esac
  deploy_managed "$file" "$rel" "$mode"
done < <(find "$skill_src" \( -name tests -o -name __pycache__ \) -prune -o -type f ! -name '*.pyc' -print0 | sort -z)

state_content="$WIK_TMPDIR/wik-managed"
for path in "${!managed_sha[@]}"; do
  printf '%s %s\n' "${managed_sha[$path]}" "$path"
done | sort -k2 >"$state_content"
ensure_user_path "$HERMES_HOME"
write_file "$state_content" "$STATE_FILE" 0600 "$WIK_USER"

# --- 6. terminal.cwd ---------------------------------------------------------

log "step 6: terminal.cwd"
# Hermes loads AGENTS.md from the turn's working directory, never from
# HERMES_HOME. Gateway turns start in terminal.cwd, or $HOME when it is unset.
# https://hermes-agent.nousresearch.com/docs/user-guide/features/context-files
# https://hermes-agent.nousresearch.com/docs/user-guide/configuration
if [ -x "$HERMES_BIN" ]; then
  current_cwd="$(as_user "$HERMES_BIN" config get terminal.cwd --raw 2>/dev/null | tail -n 1 || true)"
  if [ "$current_cwd" = "$HERMES_HOME" ]; then
    log "terminal.cwd already $HERMES_HOME"
  elif [ -z "$current_cwd" ] || [ "$current_cwd" = . ]; then
    run as_user "$HERMES_BIN" config set terminal.cwd "$HERMES_HOME"
  else
    warn "terminal.cwd is $current_cwd (set by the operator); leaving it, but AGENTS.md in $HERMES_HOME will not load for gateway turns"
  fi
else
  WIK_CHANGES=$((WIK_CHANGES + 1))
  printf '[dry-run] %s\n' "$(quote_cmd hermes config set terminal.cwd "$HERMES_HOME") (as $WIK_USER)"
fi

# --- 7. .env -----------------------------------------------------------------

log "step 7: .env permissions"
# Hermes reads credentials from $HERMES_HOME/.env. The kit never writes values;
# .env.example in the repo lists the variable names BOOTSTRAP.md asks for.
# https://hermes-agent.nousresearch.com/docs/reference/environment-variables
env_file="$HERMES_HOME/.env"
if [ -f "$env_file" ]; then
  if [ "$(stat -c '%a %U' "$env_file")" = "600 $WIK_USER" ]; then
    log ".env present with mode 600"
  else
    run chown "$WIK_USER:$WIK_USER" "$env_file"
    run chmod 600 "$env_file"
  fi
else
  ensure_user_path "$HERMES_HOME"
  run install -m 600 -o "$WIK_USER" -g "$WIK_USER" /dev/null "$env_file"
fi

# --- 8. systemd drop-in ------------------------------------------------------

log "step 8: systemd drop-in for hermes-gateway.service"
dropin_dir="$WIK_HOME/.config/systemd/user/hermes-gateway.service.d"
rendered="$WIK_TMPDIR/hermes-gateway-wik.conf"
sed -e "s|@WIK_USER@|$WIK_USER|g" \
  -e "s|@WIK_GATEWAY_MEMORY_MAX@|$GATEWAY_MEMORY_MAX|g" \
  "$KIT_DIR/deploy/systemd/hermes-gateway-wik.conf.in" >"$rendered"
if grep -q '@[A-Z_]*@' "$rendered"; then
  die "unrendered placeholder in deploy/systemd/hermes-gateway-wik.conf.in: $(grep -o '@[A-Z_]*@' "$rendered" | head -n 1)"
fi
ensure_user_path "$dropin_dir"
write_file "$rendered" "$dropin_dir/workflow-intelligence.conf" 0644 "$WIK_USER"
if [ "$WIK_FILE_CHANGED" = 1 ] && has_systemd && [ -S "/run/user/$(user_uid)/bus" ]; then
  run as_user systemctl --user daemon-reload
  if as_user systemctl --user is-active --quiet hermes-gateway.service 2>/dev/null; then
    log "gateway is running; apply the drop-in with: sudo -u $WIK_USER hermes gateway restart"
  fi
fi

# --- 9. Reference pulse ------------------------------------------------------

log "step 9: reference pulse ($PULSE_NAME)"
# Created paused: delivery needs the Telegram setup in BOOTSTRAP.md first.
# `--workdir` makes the run load AGENTS.md from the workspace.
# https://hermes-agent.nousresearch.com/docs/user-guide/features/cron
pulse_exists() {
  local jobs="$HERMES_HOME/cron/jobs.json"
  [ -f "$jobs" ] || return 1
  python3 - "$jobs" "$PULSE_NAME" 2>/dev/null <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    data = json.load(fh)
jobs = data.get("jobs", []) if isinstance(data, dict) else data
sys.exit(0 if any(j.get("name") == sys.argv[2] for j in jobs) else 1)
PY
}
pulse_prompt="Use the weather skill to get today's forecast for $PULSE_LOCATION. Reply in two sentences: conditions now, then today's high, low, and chance of rain."
pulse_cmd=("$HERMES_BIN" cron create "$PULSE_SCHEDULE" "$pulse_prompt"
  --name "$PULSE_NAME" --skill weather --deliver telegram --workdir "$HERMES_HOME"
  --paused --paused-reason "Created by workflow-intelligence-kit install.sh; resume after BOOTSTRAP.md")
if pulse_exists; then
  log "pulse exists: $PULSE_NAME"
elif [ -x "$HERMES_BIN" ]; then
  run as_user "${pulse_cmd[@]}"
else
  WIK_CHANGES=$((WIK_CHANGES + 1))
  printf '[dry-run] %s (as %s)\n' "$(quote_cmd "${pulse_cmd[@]}")" "$WIK_USER"
fi

# --- Done --------------------------------------------------------------------

summary
cat <<EOF

Next: finish setup by hand, as described in workspace-docs/BOOTSTRAP.md:
  1. sudo -iu $WIK_USER
  2. hermes model   (pick the OpenAI Codex provider; sign-in uses a device code)
  3. put TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USERS in $env_file
  4. hermes gateway install && hermes gateway start
EOF

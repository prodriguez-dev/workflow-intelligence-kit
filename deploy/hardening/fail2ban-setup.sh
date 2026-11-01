#!/usr/bin/env bash
# Install fail2ban and enable an sshd jail that reads the systemd journal.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIK_LOG_PREFIX="fail2ban-setup"
# shellcheck source=SCRIPTDIR/../lib/common.sh
. "$SCRIPT_DIR/../lib/common.sh"

usage() {
  cat <<'EOF'
Usage: fail2ban-setup.sh [--dry-run]

Installs fail2ban and writes /etc/fail2ban/jail.d/wik-sshd.local.

Environment:
  WIK_SSH_PORT   Port sshd listens on (default 22). Must match ufw-rules.sh.
EOF
}

parse_common_args usage "$@"
require_root

SSH_PORT="${WIK_SSH_PORT:-22}"
[[ "$SSH_PORT" =~ ^[0-9]+$ ]] || die "WIK_SSH_PORT must be numeric, got: $SSH_PORT"

# python3-systemd lets the jail read the journal (backend = systemd), which works
# whether or not rsyslog is writing /var/log/auth.log.
ensure_packages fail2ban python3-systemd

# A .local file in jail.d overrides the packaged defaults-debian.conf without
# editing package-owned files, so apt upgrades never prompt about it.
write_stdin /etc/fail2ban/jail.d/wik-sshd.local 0644 root:root <<EOF
# Managed by workflow-intelligence-kit (deploy/hardening/fail2ban-setup.sh).
# Local edits are overwritten on the next run.
[sshd]
enabled  = true
backend  = systemd
port     = $SSH_PORT
maxretry = 5
findtime = 10m
bantime  = 1h
EOF
jail_changed="$WIK_FILE_CHANGED"

if ! is_dry_run; then
  fail2ban-client --test >/dev/null || die "fail2ban rejected its configuration; see: fail2ban-client --test"
fi

if has_systemd && [ "$jail_changed" = 1 ] && systemctl is-active --quiet fail2ban 2>/dev/null; then
  run systemctl reload fail2ban
fi
ensure_service_running fail2ban

summary

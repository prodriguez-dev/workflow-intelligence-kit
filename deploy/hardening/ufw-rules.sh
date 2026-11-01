#!/usr/bin/env bash
# Default-deny inbound firewall with rate-limited SSH as the only open port.
# The assistant talks to Telegram by outbound long polling, so nothing else
# needs to listen on a public interface.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIK_LOG_PREFIX="ufw-rules"
# shellcheck source=SCRIPTDIR/../lib/common.sh
. "$SCRIPT_DIR/../lib/common.sh"

usage() {
  cat <<'EOF'
Usage: ufw-rules.sh [--dry-run]

Sets ufw to deny inbound, allow outbound, and rate-limit SSH, then enables it.
The SSH rule is added before ufw is enabled, so an active SSH session survives.

Environment:
  WIK_SSH_PORT   Port sshd listens on (default 22). This script does not move
                 sshd; set this only if sshd already listens elsewhere.
EOF
}

parse_common_args usage "$@"
require_root

SSH_PORT="${WIK_SSH_PORT:-22}"
[[ "$SSH_PORT" =~ ^[0-9]+$ ]] || die "WIK_SSH_PORT must be numeric, got: $SSH_PORT"

ensure_packages ufw

# Read current state first so a re-run on a configured host issues no ufw
# commands at all. Without root (dry run only) the status is unreadable and every
# step is listed.
status=""
if is_root && command -v ufw >/dev/null 2>&1; then
  status="$(ufw status verbose 2>/dev/null || true)"
fi

if grep -q 'Default: deny (incoming), allow (outgoing)' <<<"$status"; then
  log "default policy already deny incoming, allow outgoing"
else
  run ufw default deny incoming
  run ufw default allow outgoing
fi

# `ufw status` lists rules only while ufw is active, so on an inactive host this
# re-adds the rule and ufw itself skips the duplicate.
if grep -Eq "^${SSH_PORT}/tcp +LIMIT IN" <<<"$status"; then
  log "ssh rule present: ${SSH_PORT}/tcp LIMIT"
else
  run ufw limit "${SSH_PORT}/tcp" comment 'wik: ssh'
fi

if grep -q '^Status: active' <<<"$status"; then
  log "ufw already active"
else
  run ufw --force enable
fi

summary

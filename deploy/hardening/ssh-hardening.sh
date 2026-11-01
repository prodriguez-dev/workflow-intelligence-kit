#!/usr/bin/env bash
# Key-only SSH via a drop-in under /etc/ssh/sshd_config.d/.
#
# Lockout guards, in order:
#   1. Refuse to disable password login unless root or WIK_ADMIN_USER has an
#      authorized key.
#   2. Use PermitRootLogin no only when WIK_ADMIN_USER has a key and sudo;
#      otherwise prohibit-password, which keeps key-based root login working.
#   3. Validate with `sshd -t` and restore the previous file if it fails.
# sshd keeps existing sessions across a reload, so a mistake here does not drop
# the shell you are running it from.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIK_LOG_PREFIX="ssh-hardening"
# shellcheck source=SCRIPTDIR/../lib/common.sh
. "$SCRIPT_DIR/../lib/common.sh"

usage() {
  cat <<'EOF'
Usage: ssh-hardening.sh [--dry-run]

Writes /etc/ssh/sshd_config.d/10-wik-hardening.conf (key-only auth), validates
it with `sshd -t`, and reloads ssh.

Environment:
  WIK_ADMIN_USER   Non-root sudo user you log in as. When set and that user has
                   an authorized key, root login is disabled outright.
EOF
}

parse_common_args usage "$@"
require_root

DROPIN=/etc/ssh/sshd_config.d/10-wik-hardening.conf
ADMIN_USER="${WIK_ADMIN_USER:-}"

command -v sshd >/dev/null 2>&1 || die "sshd not found; install openssh-server first"

# Ubuntu's stock sshd_config includes sshd_config.d/*.conf before its own
# settings, and sshd keeps the first value it reads, so a 10- prefix also wins
# over cloud-init's 50-cloud-init.conf (which often sets PasswordAuthentication yes).
grep -Eq '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/\*\.conf' /etc/ssh/sshd_config ||
  die "/etc/ssh/sshd_config does not include sshd_config.d/*.conf; refusing to guess where settings take effect"

# has_authorized_key USER: true if USER's authorized_keys holds at least one key line.
has_authorized_key() {
  local home
  home="$(getent passwd "$1" | cut -d: -f6)"
  [ -n "$home" ] && [ -r "$home/.ssh/authorized_keys" ] &&
    grep -Eq '^[^#]*(ssh-(ed25519|rsa|dss)|ecdsa-sha2-|sk-)' "$home/.ssh/authorized_keys"
}

root_has_key=0
admin_has_key=0
admin_is_sudoer=0
has_authorized_key root && root_has_key=1
if [ -n "$ADMIN_USER" ]; then
  getent passwd "$ADMIN_USER" >/dev/null || die "WIK_ADMIN_USER=$ADMIN_USER does not exist"
  has_authorized_key "$ADMIN_USER" && admin_has_key=1
  id -nG "$ADMIN_USER" | tr ' ' '\n' | grep -qx sudo && admin_is_sudoer=1
fi

if [ "$root_has_key" = 0 ] && [ "$admin_has_key" = 0 ]; then
  if is_dry_run && ! is_root; then
    warn "cannot read authorized_keys without root; a real run checks this before changing anything"
  else
    die "no authorized SSH key found for root${ADMIN_USER:+ or $ADMIN_USER}; refusing to disable password login"
  fi
fi

if [ "$admin_has_key" = 1 ] && [ "$admin_is_sudoer" = 1 ]; then
  permit_root=no
else
  permit_root=prohibit-password
  [ -n "$ADMIN_USER" ] && warn "$ADMIN_USER lacks an authorized key or sudo membership; keeping key-only root login"
fi

backup=""
if [ -f "$DROPIN" ]; then
  backup="$WIK_TMPDIR/sshd-dropin.prev"
  cp -p "$DROPIN" "$backup"
fi

write_stdin "$DROPIN" 0644 root:root <<EOF
# Managed by workflow-intelligence-kit (deploy/hardening/ssh-hardening.sh).
# Local edits are overwritten on the next run.
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
PermitRootLogin $permit_root
MaxAuthTries 3
LoginGraceTime 30
X11Forwarding no
AllowAgentForwarding no
ClientAliveInterval 300
ClientAliveCountMax 2
EOF

if [ "$WIK_FILE_CHANGED" = 0 ]; then
  summary
  exit 0
fi

if is_dry_run; then
  printf '[dry-run] validate with: sshd -t, then: systemctl try-reload-or-restart ssh.service\n'
  summary
  exit 0
fi

# On 24.04 sshd is socket activated and may be idle; `sshd -t` still needs its
# privilege separation directory, which ssh.service normally creates at start.
[ -d /run/sshd ] || install -d -m 0755 /run/sshd
if ! sshd -t; then
  if [ -n "$backup" ]; then
    cp -p "$backup" "$DROPIN"
  else
    rm -f "$DROPIN"
  fi
  die "sshd -t rejected the new configuration; previous state restored"
fi

if has_systemd; then
  run systemctl try-reload-or-restart ssh.service
fi

# Confirm the effective value, not just the file contents.
effective="$(sshd -T -C user=root,host=localhost,addr=127.0.0.1 2>/dev/null | awk '$1 == "passwordauthentication" {print $2}')"
[ "$effective" = no ] || warn "sshd reports passwordauthentication=$effective; another drop-in may sort before $DROPIN"

summary

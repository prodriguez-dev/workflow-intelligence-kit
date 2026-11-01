#!/usr/bin/env bash
# Enable unattended security upgrades on Ubuntu 24.04.
# Ubuntu's stock 50unattended-upgrades already limits upgrades to the security
# pocket; this script turns the periodic run on and pins the reboot policy.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIK_LOG_PREFIX="unattended-upgrades"
# shellcheck source=SCRIPTDIR/../lib/common.sh
. "$SCRIPT_DIR/../lib/common.sh"

usage() {
  cat <<'EOF'
Usage: unattended-upgrades.sh [--dry-run]

Installs unattended-upgrades and enables the daily periodic run.

Environment:
  WIK_AUTO_REBOOT       "true" or "false" (default false). Reboot after upgrades
                        that need it. Off by default so a reboot never surprises
                        the operator mid-conversation.
  WIK_AUTO_REBOOT_TIME  HH:MM, local time (default 04:00). Used only when
                        WIK_AUTO_REBOOT=true.
EOF
}

parse_common_args usage "$@"
require_root

AUTO_REBOOT="${WIK_AUTO_REBOOT:-false}"
AUTO_REBOOT_TIME="${WIK_AUTO_REBOOT_TIME:-04:00}"
case "$AUTO_REBOOT" in
  true | false) ;;
  *) die "WIK_AUTO_REBOOT must be true or false, got: $AUTO_REBOOT" ;;
esac
[[ "$AUTO_REBOOT_TIME" =~ ^[0-2][0-9]:[0-5][0-9]$ ]] || die "WIK_AUTO_REBOOT_TIME must be HH:MM, got: $AUTO_REBOOT_TIME"

ensure_packages unattended-upgrades

# Same content Ubuntu's debconf writes when you answer "yes" to automatic updates,
# so on most cloud images this is already in place and reports unchanged.
write_stdin /etc/apt/apt.conf.d/20auto-upgrades 0644 root:root <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

write_stdin /etc/apt/apt.conf.d/52wik-unattended-upgrades 0644 root:root <<EOF
// Managed by workflow-intelligence-kit (deploy/hardening/unattended-upgrades.sh).
// Local edits are overwritten on the next run; change WIK_AUTO_REBOOT* instead.
Unattended-Upgrade::Automatic-Reboot "$AUTO_REBOOT";
Unattended-Upgrade::Automatic-Reboot-Time "$AUTO_REBOOT_TIME";
EOF

# The periodic run is driven by these two timers; both ship enabled, so this is
# normally a no-op that only repairs a host where someone disabled them.
ensure_service_running apt-daily.timer
ensure_service_running apt-daily-upgrade.timer

summary

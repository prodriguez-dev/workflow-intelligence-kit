#!/usr/bin/env bash
# Host hardening orchestrator. Each step is a standalone, idempotent script that
# can also be run on its own; this file only fixes the order.
#
# Order matters: package-level protections first, then SSH (which can refuse to
# run if it would lock you out), and the firewall last, after SSH is known good.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIK_LOG_PREFIX="harden"
# shellcheck source=SCRIPTDIR/../lib/common.sh
. "$SCRIPT_DIR/../lib/common.sh"

STEPS=(
  unattended-upgrades.sh
  fail2ban-setup.sh
  ssh-hardening.sh
  ufw-rules.sh
)

usage() {
  cat <<EOF
Usage: harden.sh [--dry-run]

Runs, in order: ${STEPS[*]}
--dry-run is passed to every step; nothing on the host changes.
See each script's --help for the environment variables it reads.
EOF
}

parse_common_args usage "$@"
require_root

for step in "${STEPS[@]}"; do
  log "step: $step"
  bash "$SCRIPT_DIR/$step"
done

log "all hardening steps finished"

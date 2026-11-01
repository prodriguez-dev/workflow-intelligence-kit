# shellcheck shell=bash
# Shared helpers for install.sh and deploy/hardening/*.sh. Sourced, never executed.
#
# Contract for every script that sources this file:
#   - State-changing commands go through run() so --dry-run can print them instead.
#   - Files go through write_file()/write_stdin() so re-runs compare before writing.
#   - Read-only probes (stat, cmp, dpkg-query, systemctl is-active) run in both modes.
# WIK_CHANGES counts the changes a run made (or would make under --dry-run), so a
# second real run printing "0 change(s)" is the idempotency check.

WIK_DRY_RUN="${WIK_DRY_RUN:-0}"
WIK_CHANGES=0
WIK_APT_UPDATED=0
WIK_FILE_CHANGED=0
WIK_LOG_PREFIX="${WIK_LOG_PREFIX:-wik}"
declare -A WIK_PLANNED_DIRS=()

log() { printf '[%s] %s\n' "$WIK_LOG_PREFIX" "$*"; }
warn() { printf '[%s] WARN: %s\n' "$WIK_LOG_PREFIX" "$*" >&2; }
die() {
  printf '[%s] ERROR: %s\n' "$WIK_LOG_PREFIX" "$*" >&2
  exit 1
}

is_dry_run() { [ "$WIK_DRY_RUN" = 1 ]; }
is_root() { [ "$(id -u)" -eq 0 ]; }
has_systemd() { [ -d /run/systemd/system ]; }

# quote_cmd ARGS...: render a command as a copy-pasteable shell line.
quote_cmd() {
  local out="" arg q="'"
  for arg in "$@"; do
    if [[ "$arg" =~ ^[A-Za-z0-9_./:=@%+,-]+$ ]]; then
      out+="$arg "
    else
      out+="'${arg//$q/$q\\$q$q}' "
    fi
  done
  printf '%s' "${out% }"
}

# run CMD [ARGS...]: execute a state-changing command, or print it under --dry-run.
run() {
  WIK_CHANGES=$((WIK_CHANGES + 1))
  if is_dry_run; then
    printf '[dry-run] %s\n' "$(quote_cmd "$@")"
    return 0
  fi
  log "run: $(quote_cmd "$@")"
  "$@"
}

# parse_common_args USAGE_FN ARGS...: handles --dry-run and --help for scripts
# that take no other options.
parse_common_args() {
  local usage_fn="$1"
  shift
  local arg
  for arg in "$@"; do
    case "$arg" in
      --dry-run) WIK_DRY_RUN=1 ;;
      -h | --help)
        "$usage_fn"
        exit 0
        ;;
      *) die "unknown option: $arg (see --help)" ;;
    esac
  done
  export WIK_DRY_RUN
}

require_root() {
  if is_root; then
    return 0
  fi
  if is_dry_run; then
    warn "not running as root: the dry run continues, but some checks cannot read root-only state"
    return 0
  fi
  die "must run as root (try: sudo $0)"
}

# Temp space for rendered files. Removed on exit.
WIK_TMPDIR="$(mktemp -d)"
trap 'rm -rf "$WIK_TMPDIR"' EXIT

# write_file SRC DEST MODE OWNER[:GROUP]
# Installs SRC at DEST only when content, mode, or owner differ. Sets WIK_FILE_CHANGED.
# shellcheck disable=SC2034 # WIK_FILE_CHANGED is read by the scripts that source this file
write_file() {
  local src="$1" dest="$2" mode="$3" owner="$4"
  local user="${owner%%:*}" group="${owner#*:}"
  [ "$group" = "$owner" ] && group="$user"
  WIK_FILE_CHANGED=0

  if [ -f "$dest" ] && cmp -s "$src" "$dest"; then
    local cur_mode cur_owner
    cur_mode="$(stat -c '%a' "$dest")"
    cur_owner="$(stat -c '%U:%G' "$dest")"
    if [ "$cur_mode" = "${mode#0}" ] && [ "$cur_owner" = "$user:$group" ]; then
      log "unchanged: $dest"
      return 0
    fi
    WIK_FILE_CHANGED=1
    run chmod "$mode" "$dest"
    run chown "$user:$group" "$dest"
    return 0
  fi

  WIK_FILE_CHANGED=1
  WIK_CHANGES=$((WIK_CHANGES + 1))
  if is_dry_run; then
    if [ -f "$dest" ]; then
      printf '[dry-run] update %s (mode %s, owner %s:%s); diff:\n' "$dest" "$mode" "$user" "$group"
      diff -u "$dest" "$src" | sed 's/^/    /' || true
    else
      printf '[dry-run] create %s (mode %s, owner %s:%s):\n' "$dest" "$mode" "$user" "$group"
      sed 's/^/    /' "$src"
    fi
    return 0
  fi

  # Write next to the target, then rename, so readers never see a half-written file.
  local staged
  staged="$(dirname "$dest")/.$(basename "$dest").wik-tmp"
  install -D -m "$mode" -o "$user" -g "$group" "$src" "$staged"
  mv -f "$staged" "$dest"
  log "wrote: $dest"
}

# write_stdin DEST MODE OWNER[:GROUP] <<'EOF' ... EOF
write_stdin() {
  local staged
  staged="$(mktemp "$WIK_TMPDIR/content.XXXXXX")"
  cat >"$staged"
  write_file "$staged" "$@"
}

# ensure_dir PATH MODE OWNER[:GROUP]: create PATH if missing. An existing
# directory is left as is, so the kit never fights Hermes over its own dirs.
ensure_dir() {
  local path="$1" mode="$2" owner="$3"
  local user="${owner%%:*}" group="${owner#*:}"
  [ "$group" = "$owner" ] && group="$user"
  [ -d "$path" ] && return 0
  # Under --dry-run nothing is created, so remember what was already listed.
  [ -n "${WIK_PLANNED_DIRS[$path]:-}" ] && return 0
  WIK_PLANNED_DIRS["$path"]=1
  run install -d -m "$mode" -o "$user" -g "$group" "$path"
}

pkg_installed() {
  dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'install ok installed'
}

# ensure_packages PKG...: apt-get install only the packages that are missing.
ensure_packages() {
  local missing=() pkg
  for pkg in "$@"; do
    pkg_installed "$pkg" || missing+=("$pkg")
  done
  if [ "${#missing[@]}" -eq 0 ]; then
    log "packages present: $*"
    return 0
  fi
  if [ "$WIK_APT_UPDATED" = 0 ]; then
    run env DEBIAN_FRONTEND=noninteractive apt-get update -q
    WIK_APT_UPDATED=1
  fi
  run env DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends "${missing[@]}"
}

# ensure_service_running UNIT: enable at boot and start, only if not already so.
ensure_service_running() {
  local unit="$1"
  if ! has_systemd; then
    warn "systemd is not running here; skipping enable/start of $unit"
    return 0
  fi
  if systemctl is-enabled --quiet "$unit" 2>/dev/null && systemctl is-active --quiet "$unit" 2>/dev/null; then
    log "service enabled and active: $unit"
    return 0
  fi
  run systemctl enable --now "$unit"
}

summary() {
  if is_dry_run; then
    log "dry run complete: $WIK_CHANGES change(s) would be made"
  else
    log "done: $WIK_CHANGES change(s) made"
  fi
}

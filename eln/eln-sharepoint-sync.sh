#!/usr/bin/env bash
#
# One-way backup of the Ereztech ELN notebook to SharePoint.
#
# The ELN keeps local disk as its system of record: it writes each file to
# <name>.tmp and then os.replace()s it, which is atomic on a POSIX filesystem
# and is NOT atomic across a FUSE/cloud mount. So the notebook is never served
# from SharePoint — it is copied there, one way, on a timer.
#
# Usage:
#   eln-sharepoint-sync.sh            # perform the sync
#   eln-sharepoint-sync.sh --dry-run  # show what would change, touch nothing
#
set -euo pipefail

# cron runs without a login shell, so ~/bin is not on PATH. Resolve the binary
# explicitly and prefer the up-to-date one we installed over the old distro
# build at /usr/bin/rclone, whose token format is incompatible.
RCLONE="$HOME/bin/rclone"
[ -x "$RCLONE" ] || RCLONE="$(command -v rclone || true)"
[ -n "$RCLONE" ] || { echo "$(date -Is) ERROR: no rclone binary found." >&2; exit 1; }

REMOTE="${ELN_RCLONE_REMOTE:-sharepoint}"
DEST_PATH="${ELN_RCLONE_PATH:-Ereztech ELN/notebook-backup}"
SRC="/home/nallen/ereztech-eln/data"
ELN_CONTAINER="${ELN_CONTAINER:-ereztech-eln-eln-1}"
LOG_DIR="/home/nallen/ereztech-eln/logs"
LOG="$LOG_DIR/sharepoint-sync.log"
LOCK="/home/nallen/ereztech-eln/.sharepoint-sync.lock"
STAMP="$(date +%F-%H%M%S)"

mkdir -p "$LOG_DIR"

# Refuse to run rather than fail obscurely mid-sync.
if ! "$RCLONE" listremotes 2>/dev/null | grep -qx "${REMOTE}:"; then
  echo "$(date -Is) ERROR: rclone remote '${REMOTE}:' is not configured. See ELN-SHAREPOINT.md." | tee -a "$LOG"
  exit 1
fi
if [ ! -d "$SRC" ]; then
  echo "$(date -Is) ERROR: source $SRC not found." | tee -a "$LOG"
  exit 1
fi

DRY=()
[ "${1:-}" = "--dry-run" ] && DRY=(--dry-run)

# Only one run at a time: a slow upload must never overlap the next timer tick.
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(date -Is) skipped: a sync is already running." >> "$LOG"
  exit 0
fi

echo "$(date -Is) --- sync start ${DRY[*]:-} ---" >> "$LOG"

# The ELN container runs as root and writes some files 0600 (roles.json,
# equipment.json, users.json), which this account cannot read directly. So take
# a snapshot through the container instead of reading the host directory. That
# also gives a point-in-time copy, so a file being rewritten mid-sync cannot be
# uploaded half-formed.
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

if ! docker cp "${ELN_CONTAINER}:/data/." "$STAGE/" >/dev/null 2>&1; then
  echo "$(date -Is) ERROR: could not snapshot /data from ${ELN_CONTAINER}." | tee -a "$LOG"
  exit 1
fi

# Drop credentials from the snapshot itself, not just from the transfer: the
# hashes must never exist outside the ELN's own directory.
rm -f "$STAGE/users.json"
find "$STAGE" -name "*.tmp" -delete 2>/dev/null || true

if [ -e "$STAGE/users.json" ]; then
  echo "$(date -Is) ERROR: users.json still present in snapshot — refusing to sync." | tee -a "$LOG"
  exit 1
fi

# --backup-dir : anything the sync would overwrite or delete is moved aside on
#     the remote instead of destroyed, so a bad local state can never erase
#     notebook history that is already backed up.
"$RCLONE" sync "$STAGE" "${REMOTE}:${DEST_PATH}" \
  "${DRY[@]}" \
  --exclude "users.json" \
  --exclude "*.tmp" \
  --exclude ".*" \
  --backup-dir "${REMOTE}:${DEST_PATH}-superseded/${STAMP}" \
  --transfers 4 \
  --retries 3 \
  --log-level INFO \
  --log-file "$LOG"

echo "$(date -Is) --- sync ok ---" >> "$LOG"

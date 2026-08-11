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
# Distinguish "never configured" from "configured but unreadable" — the second
# happens if something running as root rewrites rclone.conf and takes ownership,
# and it is not obvious from a "remote not configured" message.
CONF="${RCLONE_CONFIG:-$HOME/.config/rclone/rclone.conf}"
if [ -e "$CONF" ] && [ ! -r "$CONF" ]; then
  echo "$(date -Is) ERROR: $CONF exists but is not readable by $(id -un) (owner $(stat -c %U "$CONF" 2>/dev/null)). Fix ownership; see ELN-SHAREPOINT.md." | tee -a "$LOG"
  exit 1
fi
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

# Notebook folders are named by the internal ELN-YYYY-NNNN key on disk, which is
# not what a page is called in the lab and must not appear in SharePoint. Rename
# each to its chemist-notebook-page reference before upload. The id itself is
# preserved inside entry.md, so nothing is lost by renaming the folder. Entries
# with no page reference yet are dropped rather than filed under a wrong name.
python3 - "$STAGE" <<'RELABEL'
import os, re, shutil, sys
stage = sys.argv[1]
root = os.path.join(stage, "notebook")
if os.path.isdir(root):
    for book in os.listdir(root):
        bookdir = os.path.join(root, book)
        if not os.path.isdir(bookdir):
            continue
        for eid in list(os.listdir(bookdir)):
            src = os.path.join(bookdir, eid)
            md = os.path.join(src, "entry.md")
            if not (re.fullmatch(r"ELN-\d{4}-\d{4}", eid) and os.path.isfile(md)):
                continue
            # frontmatter scalars only; avoids requiring PyYAML on the host
            head = open(md, encoding="utf-8", errors="replace").read(4000)
            def field(name):
                m = re.search(r"^%s:\s*['\"]?([0-9]+)" % name, head, re.M)
                return "%03d" % int(m.group(1)) if m else None
            c, n, pg = field("chemist_number"), field("notebook_number"), field("page_number")
            if not (c and n and pg):
                shutil.rmtree(src, ignore_errors=True)   # unlabelled: keep it off SharePoint
                continue
            dst = os.path.join(bookdir, "%s-%s-%s" % (c, n, pg))
            if os.path.exists(dst):
                shutil.rmtree(src, ignore_errors=True)
            else:
                os.rename(src, dst)
RELABEL

# A PDF of every entry travels with the notebook, so the SharePoint copy is
# readable by someone who has the folder and nothing else. Rendering happens in
# the container (it needs the app's templates) and is content-cached, so an
# unchanged entry yields byte-identical output and rclone skips re-uploading it.
PDF_CACHE="/home/nallen/ereztech-eln/pdf-cache"
mkdir -p "$PDF_CACHE"
if docker exec "$ELN_CONTAINER" sh -c 'rm -rf /tmp/eln-pdfs && mkdir -p /tmp/eln-pdfs /tmp/eln-pdfcache' 2>/dev/null; then
  docker cp "$PDF_CACHE/." "${ELN_CONTAINER}:/tmp/eln-pdfcache/" >/dev/null 2>&1 || true
  if docker exec "$ELN_CONTAINER" python -m app.renderpdf /tmp/eln-pdfs /tmp/eln-pdfcache \
        > "$STAGE/.pdfmap" 2>>"$LOG"; then
    docker cp "${ELN_CONTAINER}:/tmp/eln-pdfs/." "$STAGE/.pdfs/" >/dev/null 2>&1 || true
    docker cp "${ELN_CONTAINER}:/tmp/eln-pdfcache/." "$PDF_CACHE/" >/dev/null 2>&1 || true
    # file each PDF beside the entry it documents
    while read -r label author; do
      [ -n "$label" ] || continue
      dest="$STAGE/notebook/$author/$label"
      [ -d "$dest" ] && [ -f "$STAGE/.pdfs/$label.pdf" ] && cp "$STAGE/.pdfs/$label.pdf" "$dest/"
    done < "$STAGE/.pdfmap"
    echo "$(date -Is) rendered PDFs for $(wc -l < "$STAGE/.pdfmap") entries" >> "$LOG"
  else
    echo "$(date -Is) WARNING: PDF rendering failed; syncing files without PDFs." >> "$LOG"
  fi
  rm -rf "$STAGE/.pdfs" "$STAGE/.pdfmap"
fi

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
  --exclude "document/**" \
  --backup-dir "${REMOTE}:${DEST_PATH}-superseded/${STAMP}" \
  --transfers 4 \
  --retries 3 \
  --log-level INFO \
  --log-file "$LOG"

echo "$(date -Is) --- sync ok ---" >> "$LOG"

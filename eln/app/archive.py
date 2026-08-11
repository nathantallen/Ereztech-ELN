"""Cold storage for closed-out entries: bulk files live in OneDrive, the
notebook's index stays on local disk.

WHAT NEVER LEAVES LOCAL DISK, and why
    `entry.md` and `audit.log` always stay. Three things in storage.py derive
    from reading them off the filesystem:

      * list_entries()     — builds the notebook index
      * next_entry_id()    — allocates the next ELN-YYYY-NNNN
      * next_page_number() — the immutable page number in a chemist's book

    Removing an archived entry's `entry.md` would make the index need a network
    round trip per entry, and — far worse — would let the app reissue an entry
    id or a page number that already exists. For a notebook that is a legal
    record, a duplicate page number is not a performance problem, it is a
    corrupt record. Those two files total tens of kilobytes across the whole
    notebook, so keeping them costs nothing.

WHAT MOVES
    `structures/`, `photos/` and `attachments/` — effectively all of the bytes.
    They are uploaded, verified by downloading them back and comparing content,
    and only then deleted locally. A manifest is left behind so the app knows
    what exists without touching the network.

READING AN ARCHIVED FILE
    ensure_local() pulls a file back into place on demand, so the normal
    send_from_directory() path serves it unchanged. Restored files stay on disk
    as a cache; they can be re-pruned at any time because the manifest records
    what is safely in OneDrive.
"""
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import threading

ARCHIVE_SUBDIRS = ("structures", "photos", "attachments", "document")
MANIFEST = ".archived.json"
# A rendered copy of the entry travels with the files, so the archive is
# readable by someone who has the OneDrive folder and nothing else — no ELN, no
# Markdown, no structure viewer.
PDF_NAME = "%s.pdf"

_LOCK = threading.RLock()


class ArchiveError(RuntimeError):
    """Archiving failed. Nothing has been deleted when this is raised."""


def page_ref(meta):
    """The notebook page label: zero-padded chemist-notebook-page, e.g. 067-001-009.

    This is what a page is called in the lab. The ELN-YYYY-NNNN id is an
    internal key — it names the directory on disk and is what storage.py's
    id allocation and cross-references run on — but it is never what anything
    outside the app should be labelled with.

    Returns None when the entry has no page reference yet; such an entry cannot
    be archived, because there would be nothing correct to call it.
    """
    def part(value):
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        return "%03d" % int(digits) if digits else None

    chemist = part(meta.get("chemist_number"))
    notebook = part(meta.get("notebook_number"))
    page = part(meta.get("page_number"))
    if not (chemist and notebook and page):
        return None
    return "%s-%s-%s" % (chemist, notebook, page)


def _rclone_bin():
    return os.environ.get("ELN_RCLONE_BIN", "rclone")


def remote_base():
    """`remote:path` under which entries are archived, or None if unconfigured."""
    return os.environ.get("ELN_ARCHIVE_REMOTE") or None


def configured():
    return bool(remote_base())


def _run(args, timeout=900):
    """Run rclone. Returns stdout; raises ArchiveError with stderr on failure."""
    proc = subprocess.run(
        [_rclone_bin()] + args,
        capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise ArchiveError(
            "rclone %s failed (%d): %s"
            % (args[0], proc.returncode, (proc.stderr or "").strip()[:500])
        )
    return proc.stdout


def entry_remote(label):
    base = remote_base()
    if not base:
        raise ArchiveError("ELN_ARCHIVE_REMOTE is not set.")
    return "%s/%s" % (base.rstrip("/"), label)


# ---------- manifest ----------

def manifest_path(entry_dir):
    return os.path.join(entry_dir, MANIFEST)


def read_manifest(entry_dir):
    try:
        with open(manifest_path(entry_dir), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def is_archived(entry_dir):
    return os.path.isfile(manifest_path(entry_dir))


def archived_files(entry_dir):
    m = read_manifest(entry_dir) or {}
    return {f["path"]: f for f in m.get("files", [])}


# ---------- helpers ----------

def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _collect(entry_dir):
    """Relative paths of every file eligible to be archived."""
    out = []
    for sub in ARCHIVE_SUBDIRS:
        root = os.path.join(entry_dir, sub)
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                full = os.path.join(dirpath, name)
                out.append(os.path.relpath(full, entry_dir))
    return sorted(out)


def _safe_join(entry_dir, relpath):
    """Resolve relpath under entry_dir, refusing anything that escapes it."""
    base = os.path.realpath(entry_dir)
    full = os.path.realpath(os.path.join(base, relpath))
    if full != base and not full.startswith(base + os.sep):
        raise ArchiveError("path escapes the entry directory")
    return full


# ---------- archive ----------

def archive_entry(entry_dir, eid, username, pdf_bytes=None, label=None):
    """Upload this entry's bulk files, verify them, then delete them locally.

    Verification downloads the uploaded copies and compares content — metadata
    agreement is not enough to justify deleting the only local copy of a
    witnessed record. Nothing is deleted unless every file verifies.
    """
    if not configured():
        raise ArchiveError(
            "Archiving is not configured. Set ELN_ARCHIVE_REMOTE (e.g. "
            "'sharepoint:Ereztech ELN/archive')."
        )
    if not label:
        raise ArchiveError(
            "This entry has no chemist/notebook/page number, so there is no "
            "notebook page label to file it under. Set those on the entry first."
        )
    with _LOCK:
        # Write the rendered record alongside the files so it is uploaded and
        # verified by exactly the same path as everything else.
        pdf_rel = None
        if pdf_bytes:
            pdf_rel = PDF_NAME % label
            pdf_dir = os.path.join(entry_dir, "document")
            os.makedirs(pdf_dir, exist_ok=True)
            tmp = os.path.join(pdf_dir, pdf_rel + ".tmp")
            with open(tmp, "wb") as f:
                f.write(pdf_bytes)
            os.replace(tmp, os.path.join(pdf_dir, pdf_rel))

        files = _collect(entry_dir)
        if not files:
            return {"archived": 0, "bytes": 0, "message": "No files to archive."}

        remote = entry_remote(label)
        manifest = {
            "eid": eid,
            "label": label,
            "archived_at": datetime.datetime.now(datetime.timezone.utc)
                            .replace(microsecond=0).isoformat(),
            "archived_by": username,
            "remote": remote,
            "files": [],
        }
        total = 0
        for rel in files:
            full = os.path.join(entry_dir, rel)
            size = os.path.getsize(full)
            total += size
            manifest["files"].append(
                {"path": rel.replace(os.sep, "/"), "size": size, "sha256": _sha256(full)}
            )

        # Upload only the archivable subdirectories, never entry.md/audit.log.
        for sub in ARCHIVE_SUBDIRS:
            local_sub = os.path.join(entry_dir, sub)
            if os.path.isdir(local_sub):
                _run(["copy", local_sub, "%s/%s" % (remote, sub),
                      "--transfers", "4", "--retries", "3"])

        # Verify by content, not by size/modtime.
        for sub in ARCHIVE_SUBDIRS:
            local_sub = os.path.join(entry_dir, sub)
            if os.path.isdir(local_sub):
                _run(["check", local_sub, "%s/%s" % (remote, sub),
                      "--download", "--one-way"])

        # Verified — safe to reclaim the space.
        for rel in files:
            try:
                os.remove(os.path.join(entry_dir, rel))
            except OSError:
                pass
        for sub in ARCHIVE_SUBDIRS:
            local_sub = os.path.join(entry_dir, sub)
            if os.path.isdir(local_sub):
                shutil.rmtree(local_sub, ignore_errors=True)

        tmp = manifest_path(entry_dir) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, sort_keys=True)
        os.replace(tmp, manifest_path(entry_dir))

        return {"archived": len(files), "bytes": total, "pdf": pdf_rel,
                "message": "Archived %d file(s), %.1f KB reclaimed%s."
                           % (len(files), total / 1024.0,
                              " (including a PDF of the entry)" if pdf_rel else "")}


# ---------- read-back ----------

def _remote_for(entry_dir, eid):
    """Where this entry's files live, taken from the manifest written at archive
    time so a later change to the labelling scheme cannot orphan them."""
    m = read_manifest(entry_dir) or {}
    if m.get("remote"):
        return m["remote"]
    if m.get("label"):
        return entry_remote(m["label"])
    raise ArchiveError("no archive location recorded for %s" % eid)


def ensure_local(entry_dir, eid, relpath):
    """Make `relpath` readable on local disk, fetching it back if archived.

    Returns True when the file is present afterwards. Restoring in place means
    the ordinary file-serving path needs no special case.
    """
    full = _safe_join(entry_dir, relpath)
    if os.path.isfile(full):
        return True
    if not is_archived(entry_dir):
        return False

    rel_key = relpath.replace(os.sep, "/")
    known = archived_files(entry_dir)
    if rel_key not in known:
        return False
    if not configured():
        raise ArchiveError(
            "%s is archived in OneDrive but archiving is not configured on this "
            "server, so it cannot be fetched." % rel_key
        )

    with _LOCK:
        if os.path.isfile(full):  # another thread won the race
            return True
        os.makedirs(os.path.dirname(full), exist_ok=True)
        _run(["copyto", "%s/%s" % (_remote_for(entry_dir, eid), rel_key), full,
              "--retries", "3"], timeout=300)
        if not os.path.isfile(full):
            raise ArchiveError("fetched %s but it did not appear locally" % rel_key)
        # A restored file must be the file we archived.
        expected = known[rel_key].get("sha256")
        if expected and _sha256(full) != expected:
            os.remove(full)
            raise ArchiveError(
                "%s came back from OneDrive with different content than was "
                "archived — refusing to serve it." % rel_key
            )
        return True


def ensure_entry_local(entry_dir, eid):
    """Restore every missing archived file for this entry in one transfer.

    Opening an archived entry renders its structure drawings inline, so the
    alternative is one rclone call per drawing — twenty round trips and a page
    that takes twenty seconds. This pulls the whole entry back at once, and is a
    no-op when nothing is missing.
    """
    if not is_archived(entry_dir):
        return 0
    known = archived_files(entry_dir)
    missing = [
        rel for rel in known
        if not os.path.isfile(os.path.join(entry_dir, rel))
    ]
    if not missing:
        return 0
    if not configured():
        raise ArchiveError(
            "This entry's files are archived in OneDrive but archiving is not "
            "configured on this server."
        )
    with _LOCK:
        missing = [
            rel for rel in known
            if not os.path.isfile(os.path.join(entry_dir, rel))
        ]
        if not missing:
            return 0
        for sub in ARCHIVE_SUBDIRS:
            if any(rel.startswith(sub + "/") for rel in missing):
                _run(["copy", "%s/%s" % (_remote_for(entry_dir, eid), sub),
                      os.path.join(entry_dir, sub),
                      "--transfers", "4", "--retries", "3"], timeout=600)
        return len(missing)


def status(entry_dir):
    """Small summary for the UI."""
    m = read_manifest(entry_dir)
    if not m:
        return {"archived": False}
    files = m.get("files", [])
    present = sum(
        1 for f in files if os.path.isfile(os.path.join(entry_dir, f["path"]))
    )
    return {
        "archived": True,
        "at": m.get("archived_at"),
        "by": m.get("archived_by"),
        "count": len(files),
        "bytes": sum(f.get("size", 0) for f in files),
        "cached_locally": present,
    }

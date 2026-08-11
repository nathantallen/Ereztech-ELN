# ELN notebook backup to SharePoint

**Status: live.** Hourly one-way copy of the ELN data directory into the
SharePoint document library. SharePoint is a backup and a read-only window —
never the live store.

| | |
|---|---|
| Script | `/home/nallen/ereztech-eln/eln-sharepoint-sync.sh` |
| Schedule | cron, hourly at :17 (`crontab -l`) |
| Log | `/home/nallen/ereztech-eln/logs/sharepoint-sync.log` |
| rclone remote | `sharepoint:` (type `onedrive`, `drive_type = documentLibrary`) |
| Destination | `sharepoint:Ereztech ELN/notebook-backup` |
| Superseded files | `sharepoint:Ereztech ELN/notebook-backup-superseded/<timestamp>/` |

## Why the notebook is not served from SharePoint

The ELN has no database — the files *are* the notebook (`app/storage.py`). Every
save writes `<name>.tmp` then `os.replace()`s it, which is atomic on a POSIX
filesystem. Across an rclone FUSE mount that guarantee disappears: a rename
becomes a sequence of API calls, SharePoint versions every write, and the
in-process `threading.RLock()` does not span gunicorn workers. For a notebook
holding signed and witnessed entries that is the wrong trade, so local disk
stays the system of record and SharePoint receives a copy.

## How a run works

1. **Snapshot through the container.** The ELN runs as root and writes
   `roles.json`, `equipment.json` and `users.json` as mode 0600, which the
   `nallen` account cannot read from the host. So the script takes the snapshot
   with `docker cp` from inside the container rather than reading `data/`
   directly. This also yields a point-in-time copy, so a file being rewritten
   mid-sync can never be uploaded half-formed.
2. **Strip credentials from the snapshot.** `users.json` holds scrypt
   **password hashes**. It is deleted from the snapshot — not merely excluded
   from the transfer — and the script aborts if it is somehow still present.
   Keep that file in the server-side backups instead.
3. **Sync**, with `--backup-dir` so anything overwritten or deleted on the
   remote is moved aside rather than destroyed. Notebook history already backed
   up cannot be erased by a bad local state.

A `flock` means a slow upload can never overlap the next hourly tick.

## rclone install note

The distro rclone at `/usr/bin/rclone` is **v1.60.1-DEV** (late 2022) and its
token format is incompatible with current rclone — pasting a token minted by a
newer rclone fails with *"Couldn't decode response … unexpected end of JSON
input"*. The working binary is **v1.75.0** at `~/bin/rclone`, installed from the
official release with its SHA256 verified against the release manifest. The
system copy is untouched.

The script resolves `~/bin/rclone` explicitly, because cron does not get a login
shell and would otherwise silently fall back to the old binary.

## Checking on it

```bash
tail -40 /home/nallen/ereztech-eln/logs/sharepoint-sync.log
```

```bash
~/bin/rclone size "sharepoint:Ereztech ELN/notebook-backup"
```

A healthy run ends with `--- sync ok ---` and no `ERROR` lines. Object count at
the destination should match the source minus `users.json`:

```bash
docker exec ereztech-eln-eln-1 sh -c 'find /data -type f ! -name users.json ! -name "*.tmp" | wc -l'
```

## Restoring

The copy is plain Markdown, JSON and attachments — no restore tool needed. Pull
it back with `rclone copy` into a scratch directory and move files across
deliberately. Never `rclone sync` onto the live data directory while the ELN is
running.

## Re-authenticating

The OAuth refresh token lives only in `~/.config/rclone/rclone.conf` on the
server. If it is ever revoked or expires:

```bash
~/bin/rclone config reconnect sharepoint:
```

Answer `n` to "Use auto config?" and paste a token from `rclone authorize
"onedrive"` on a machine with a browser — both sides must be on the same rclone
version. Alternatively reconnect over an SSH forward
(`ssh -L 53682:localhost:53682 …`) and answer `y`, which needs no paste.

---

# Archiving closed-out entries (`app/archive.py`)

Separate from the hourly backup above. A per-entry **Archive to OneDrive** button
on the entry page (author or admin) renders the entry to PDF, uploads it with the
entry's `structures/`, `photos/` and `attachments/`, verifies everything, and only
then frees the local copies.

| | |
|---|---|
| Trigger | Manual, per entry. Nothing moves on its own. |
| Destination | `sharepoint:Ereztech ELN/archive/<ELN-id>/` |
| Enabled by | `ELN_ARCHIVE_REMOTE` in `.env` (unset → button hidden) |

**What never moves:** `entry.md` and `audit.log`. `list_entries()`,
`next_entry_id()` and `next_page_number()` all read them off the filesystem, so
removing them would make the index need a network round trip per entry and — far
worse — let the app reissue an entry id or a page number that already exists.
They total tens of KB across the whole notebook.

**Verification before deletion:** files are uploaded, then `rclone check
--download` compares actual bytes, not size and timestamp. Nothing is deleted
unless every file matches. Restored files are re-checked against the SHA-256 in
the manifest and refused if they differ.

**Reading is unchanged:** opening an archived entry pulls its files back in one
transfer (not one call per drawing) and they are served normally. `.archived.json`
records what is in OneDrive, so the entry list stays instant and offline.

## Interaction with the hourly backup

The two write to different paths and together hold the whole notebook:

* `notebook-backup/` mirrors what is **currently on local disk**
* `archive/<ELN-id>/` holds what has been **moved off local disk**

When an entry is archived, its files leave the local directory, so the next hourly
`rclone sync` moves them out of `notebook-backup/` into
`notebook-backup-superseded/<timestamp>/`. That is expected — the authoritative
copy is under `archive/`. Do not treat a file vanishing from `notebook-backup/`
as data loss.

## PDF rendering

WeasyPrint renders `entry_print.html`, the same layout the print dialog uses.
Two deliberate differences: no JavaScript (so timestamps stay as the server
rendered them, which is what an archived record wants) and no network (the URL
fetcher serves only the app's own static files, so a slow webfont CDN cannot
stall an archive).

`pydyf` is pinned to 0.10.0. WeasyPrint 62.x uses the pre-0.11 pydyf Stream API;
a newer pydyf fails at render time with
`'super' object has no attribute 'transform'`.

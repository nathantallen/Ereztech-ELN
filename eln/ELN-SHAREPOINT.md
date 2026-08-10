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

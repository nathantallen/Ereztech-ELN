"""File-based storage for the EreZtech ELN.

Everything lives under one data directory (a mounted NAS / SharePoint-synced
folder). All records are human-readable: Markdown with YAML frontmatter for
entries, materials and batches; JSON for users; plain-text append-only audit
logs. No database — the files ARE the notebook.

Layout:
    <root>/
      users.json
      notebook/<username>/ELN-2026-0001/entry.md
                                        audit.log
                                        structures/struct-01.mol|.svg
                                        attachments/<files>
      materials/<slug>/material.md
                       batches/<lot>.md
                       attachments/<lot>/<files>

Entries are grouped into a folder per author (their personal lab book) but keep
globally-unique ids (ELN-YEAR-SEQ) so cross-references resolve regardless of who
owns them.
"""
import datetime
import json
import os
import re
import threading

import yaml

_LOCK = threading.RLock()

ENTRY_SECTIONS = ["Objective", "Procedure", "Results & Conclusions"]
ENTRY_STATUSES = ["draft", "signed", "witnessed"]
BATCH_STATUSES = ["In Stock", "Open", "Depleted", "Quarantined"]
ATMOSPHERES = ["N2 glovebox", "Ar glovebox", "Ar Schlenk line", "Vacuum line", "Fume hood (air)", "Other"]

VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
DATA_EXT = {".csv", ".tsv", ".json", ".txt", ".log", ".dat", ".xml"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".tif", ".tiff"}


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "item"


def attachment_kind(filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in IMAGE_EXT:
        return "image"
    if ext in DATA_EXT:
        return "data"
    return "file"


def load_md(path):
    """Read a markdown file with YAML frontmatter -> (meta, body)."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    meta, body = {}, text
    if text.startswith("---"):
        parts = text.split("\n---\n", 1)
        if len(parts) == 2:
            meta = yaml.safe_load(parts[0][3:]) or {}
            body = parts[1].lstrip("\n")
    return meta, body


def dump_md(path, meta, body):
    """Atomically write meta + body as frontmatter markdown."""
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=False)
    text = "---\n" + front + "---\n\n" + (body or "").strip() + "\n"
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def parse_sections(body):
    """Split a markdown body on '## ' headings -> {heading: text}."""
    sections = {}
    current, buf = None, []
    for line in (body or "").splitlines():
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current, buf = line[3:].strip(), []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def compose_sections(sections):
    """Compose the standard sections, then preserve any legacy/extra headings
    (e.g. 'Observations & Data' from entries created before the operations log)."""
    parts = []
    for heading in ENTRY_SECTIONS:
        parts.append("## %s\n\n%s\n" % (heading, (sections.get(heading) or "").strip()))
    for heading, text in sections.items():
        if heading not in ENTRY_SECTIONS and (text or "").strip():
            parts.append("## %s\n\n%s\n" % (heading, text.strip()))
    return "\n".join(parts)


class Storage:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.notebook_dir = os.path.join(self.root, "notebook")
        self.materials_dir = os.path.join(self.root, "materials")
        self.users_file = os.path.join(self.root, "users.json")
        from .chem import PropertyDB
        self.properties = PropertyDB(os.path.join(self.root, "properties.json"))
        # eid -> containing folder; an entry never moves once created, so this
        # is safe to cache and just saves rescanning user folders on read paths
        self._entry_dir_cache = {}

    # ---------- layout / seed ----------

    def ensure_layout(self):
        os.makedirs(self.notebook_dir, exist_ok=True)
        os.makedirs(self.materials_dir, exist_ok=True)
        self.properties.ensure()
        self._migrate_notebook_by_user()
        if not os.path.exists(self.users_file):
            from .seed import seed_initial_data
            seed_initial_data(self)

    def _migrate_notebook_by_user(self):
        """One-time migration: entries used to live at notebook/ELN-*; they now
        live in per-user folders, notebook/<username>/ELN-*."""
        for name in list(os.listdir(self.notebook_dir)):
            src = os.path.join(self.notebook_dir, name)
            if not (re.fullmatch(r"ELN-\d{4}-\d{4}", name)
                    and os.path.isfile(os.path.join(src, "entry.md"))):
                continue
            try:
                meta, _ = load_md(os.path.join(src, "entry.md"))
            except (OSError, ValueError):
                continue
            dest_dir = self.user_notebook_dir(meta.get("author"))
            dest = os.path.join(dest_dir, name)
            if os.path.exists(dest):
                # an entry with this id already exists in the user's book — never
                # rename onto it (data loss). Preserve the flat one, out of the way,
                # for an admin to reconcile.
                conflicts = os.path.join(self.root, "migration_conflicts")
                os.makedirs(conflicts, exist_ok=True)
                try:
                    os.rename(src, os.path.join(
                        conflicts, "%s-%s" % (name, utcnow().replace(":", ""))))
                except OSError:
                    pass
                continue
            try:
                os.makedirs(dest_dir, exist_ok=True)
                os.rename(src, dest)
            except OSError:
                continue

    # ---------- app settings (small key/value config, travels with the data) ----------

    def get_settings(self):
        path = os.path.join(self.root, "settings.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save_settings(self, d):
        with _LOCK:
            path = os.path.join(self.root, "settings.json")
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)

    def get_timezone(self):
        """IANA tz name for displaying timestamps, or '' meaning viewer-local."""
        return (self.get_settings().get("timezone") or "").strip()

    def set_timezone(self, tz):
        d = self.get_settings()
        d["timezone"] = tz or ""
        self.save_settings(d)

    # ---------- techniques (customizable; seeded from the classic set) ----------

    def get_techniques(self):
        path = os.path.join(self.root, "techniques.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                ts = json.load(f).get("techniques", [])
        except (OSError, ValueError):
            ts = []
        if not ts:
            ts = list(ATMOSPHERES)
            self._save_techniques(ts)
        return ts

    def add_technique(self, name):
        name = (name or "").strip()
        if not name:
            return
        ts = self.get_techniques()
        if name.lower() not in [t.lower() for t in ts]:
            ts.append(name)
            self._save_techniques(ts)

    def _save_techniques(self, ts):
        with _LOCK:
            path = os.path.join(self.root, "techniques.json")
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"techniques": ts}, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)

    # ---------- users ----------

    def get_users(self):
        with _LOCK:
            try:
                with open(self.users_file, "r", encoding="utf-8") as f:
                    return json.load(f).get("users", [])
            except (OSError, ValueError):
                return []

    def save_users(self, users):
        with _LOCK:
            tmp = self.users_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"users": users}, f, indent=2)
            os.replace(tmp, self.users_file)

    def find_user(self, username):
        for u in self.get_users():
            if u["username"] == username:
                return u
        return None

    # ---------- notebook entries (grouped into per-user lab books) ----------

    @staticmethod
    def user_folder_name(username):
        """A filesystem-safe, human-readable folder name confined to a single
        subdirectory. Neutralises names that are all dots (".", "..", …) so a
        username can never resolve to a path-traversal component."""
        name = (username or "unassigned").strip()
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
        if not safe or not safe.strip("."):     # empty, ".", "..", "..." → unsafe
            return "unassigned"
        return safe

    def user_notebook_dir(self, username):
        return os.path.join(self.notebook_dir, self.user_folder_name(username))

    def _iter_entry_paths(self):
        """Yield (eid, entry.md path) across every user's lab book."""
        for folder in os.listdir(self.notebook_dir):
            book = os.path.join(self.notebook_dir, folder)
            if not os.path.isdir(book):
                continue
            for eid in os.listdir(book):
                path = os.path.join(book, eid, "entry.md")
                if re.fullmatch(r"ELN-\d{4}-\d{4}", eid) and os.path.isfile(path):
                    yield eid, path

    def entry_dir(self, eid, author=None):
        """Folder for an entry. With `author`, compute where it belongs (used
        when creating/saving). Without, locate the existing folder across users."""
        if not re.fullmatch(r"ELN-\d{4}-\d{4}", eid):
            raise ValueError("bad entry id")
        if author:
            return os.path.join(self.user_notebook_dir(author), eid)
        cached = self._entry_dir_cache.get(eid)
        if cached and os.path.isdir(cached):
            return cached
        for folder in os.listdir(self.notebook_dir):
            cand = os.path.join(self.notebook_dir, folder, eid)
            if os.path.isdir(cand):
                self._entry_dir_cache[eid] = cand
                return cand
        # unknown entry: a path that won't exist (callers guard on isfile)
        return os.path.join(self.notebook_dir, "unassigned", eid)

    def next_entry_id(self):
        year = datetime.date.today().year
        prefix = "ELN-%d-" % year
        seq = 0
        for eid, _ in self._iter_entry_paths():
            if eid.startswith(prefix):
                try:
                    seq = max(seq, int(eid[len(prefix):]))
                except ValueError:
                    pass
        return "%s%04d" % (prefix, seq + 1)

    def list_entries(self):
        entries = []
        for eid, path in self._iter_entry_paths():
            try:
                meta, _ = load_md(path)
                entries.append(meta)
            except Exception:
                continue
        entries.sort(key=lambda m: str(m.get("created", "")), reverse=True)
        return entries

    def get_entry(self, eid):
        path = os.path.join(self.entry_dir(eid), "entry.md")
        if not os.path.isfile(path):
            return None, None
        return load_md(path)

    def save_entry(self, eid, meta, body):
        with _LOCK:
            # author is stable for an entry, so this resolves to its own folder
            d = self.entry_dir(eid, author=meta.get("author"))
            os.makedirs(d, exist_ok=True)
            dump_md(os.path.join(d, "entry.md"), meta, body)
            self._entry_dir_cache[eid] = d

    def create_entry(self, meta, body):
        with _LOCK:
            eid = self.next_entry_id()
            meta["id"] = eid
            self.save_entry(eid, meta, body)
            return eid

    def audit(self, eid, username, action, detail=""):
        with _LOCK:
            d = self.entry_dir(eid)
            os.makedirs(d, exist_ok=True)
            line = "%s | %s | %s" % (utcnow(), username, action)
            if detail:
                line += " | " + detail.replace("\n", " ")
            with open(os.path.join(d, "audit.log"), "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def read_audit(self, eid):
        path = os.path.join(self.entry_dir(eid), "audit.log")
        if not os.path.isfile(path):
            return []
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                parts = [p.strip() for p in line.rstrip("\n").split(" | ", 3)]
                if len(parts) >= 3:
                    rows.append({
                        "at": parts[0], "by": parts[1], "action": parts[2],
                        "detail": parts[3] if len(parts) > 3 else "",
                    })
        return rows

    # ---------- operational log (timestamped observations) ----------

    def append_observation(self, eid, username, kind, text, elapsed=""):
        """Append one timestamped block to observations.md. kind: note|photo|system."""
        with _LOCK:
            d = self.entry_dir(eid)
            os.makedirs(d, exist_ok=True)
            header = "## %s | %s | %s | %s" % (utcnow(), elapsed or "--:--:--",
                                               username, kind)
            with open(os.path.join(d, "observations.md"), "a", encoding="utf-8") as f:
                f.write(header + "\n\n" + (text or "").strip() + "\n\n")

    def read_observations(self, eid):
        path = os.path.join(self.entry_dir(eid), "observations.md")
        if not os.path.isfile(path):
            return []
        blocks = []
        current = None
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("## "):
                    if current:
                        blocks.append(current)
                    parts = [p.strip() for p in line[3:].split("|")]
                    current = {"at": parts[0] if parts else "",
                               "elapsed": parts[1] if len(parts) > 1 else "",
                               "by": parts[2] if len(parts) > 2 else "",
                               "kind": parts[3] if len(parts) > 3 else "note",
                               "text": ""}
                elif current is not None:
                    current["text"] += line
        if current:
            blocks.append(current)
        for b in blocks:
            b["text"] = b["text"].strip()
        return blocks

    # ---------- sensor logs (one CSV per entity, human-readable) ----------

    def sensors_dir(self, eid):
        return os.path.join(self.entry_dir(eid), "sensors")

    def append_sensor_point(self, eid, entity, label, unit, value):
        d = self.sensors_dir(eid)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, entity + ".csv")
        new = not os.path.exists(path)
        with open(path, "a", encoding="utf-8") as f:
            if new:
                f.write("# entity=%s label=%s unit=%s\n" % (entity, label, unit))
                f.write("timestamp,value\n")
            f.write("%s,%s\n" % (utcnow(), value))

    def read_sensor_series(self, eid, max_points=4000):
        d = self.sensors_dir(eid)
        series = []
        if not os.path.isdir(d):
            return series
        for name in sorted(os.listdir(d)):
            if not name.endswith(".csv"):
                continue
            path = os.path.join(d, name)
            label, unit = name[:-4], ""
            points = []
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("#"):
                            m = re.search(r"label=(.*?) unit=(.*)$", line)
                            if m:
                                label, unit = m.group(1), m.group(2)
                        elif "," in line and not line.startswith("timestamp"):
                            ts, _, val = line.partition(",")
                            try:
                                points.append([ts, float(val)])
                            except ValueError:
                                pass
            except OSError:
                continue
            series.append({"entity": name[:-4], "label": label, "unit": unit,
                           "points": points[-max_points:]})
        return series

    # ---------- materials & batches ----------

    def material_dir(self, slug):
        if not re.fullmatch(r"[a-z0-9-]+", slug):
            raise ValueError("bad material slug")
        return os.path.join(self.materials_dir, slug)

    def list_materials(self):
        mats = []
        for name in sorted(os.listdir(self.materials_dir)):
            path = os.path.join(self.materials_dir, name, "material.md")
            if os.path.isfile(path):
                try:
                    meta, body = load_md(path)
                    meta["_notes"] = body
                    meta["_batch_count"] = len(self.list_batches(name))
                    mats.append(meta)
                except Exception:
                    continue
        return mats

    def get_material(self, slug):
        path = os.path.join(self.material_dir(slug), "material.md")
        if not os.path.isfile(path):
            return None, None
        return load_md(path)

    def save_material(self, slug, meta, notes):
        with _LOCK:
            d = self.material_dir(slug)
            os.makedirs(os.path.join(d, "batches"), exist_ok=True)
            dump_md(os.path.join(d, "material.md"), meta, notes)

    def list_batches(self, slug):
        d = os.path.join(self.material_dir(slug), "batches")
        batches = []
        if os.path.isdir(d):
            for name in sorted(os.listdir(d)):
                if name.endswith(".md"):
                    try:
                        meta, body = load_md(os.path.join(d, name))
                        meta["_notes"] = body
                        batches.append(meta)
                    except Exception:
                        continue
        batches.sort(key=lambda b: str(b.get("received", "")), reverse=True)
        return batches

    def get_batch(self, slug, lot_slug):
        path = os.path.join(self.material_dir(slug), "batches", lot_slug + ".md")
        if not os.path.isfile(path):
            return None, None
        return load_md(path)

    def save_batch(self, slug, lot_slug, meta, notes):
        with _LOCK:
            d = os.path.join(self.material_dir(slug), "batches")
            os.makedirs(d, exist_ok=True)
            dump_md(os.path.join(d, lot_slug + ".md"), meta, notes)

    def all_batches_by_material(self):
        """{slug: {'name': ..., 'batches': [lot, ...]}} for entry forms."""
        out = {}
        for m in self.list_materials():
            slug = m.get("slug")
            out[slug] = {
                "name": m.get("name", slug),
                "batches": [b.get("lot") for b in self.list_batches(slug)],
            }
        return out

    # ---------- entry usage lookups (deletion guards / cross-links) ----------

    def entries_using_batch(self, slug, lot):
        hits = []
        for meta in self.list_entries():
            for used in meta.get("materials") or []:
                if used.get("material") == slug and used.get("lot") == lot:
                    hits.append(meta["id"])
                    break
        return hits

    def entries_using_material(self, slug):
        hits = []
        for meta in self.list_entries():
            for used in meta.get("materials") or []:
                if used.get("material") == slug:
                    hits.append(meta["id"])
                    break
        return hits

    # ---------- stats ----------

    def stats(self):
        entries = self.list_entries()
        mats = self.list_materials()
        batch_count = sum(m.get("_batch_count", 0) for m in mats)
        return {
            "entries": len(entries),
            "drafts": sum(1 for e in entries if e.get("status") == "draft"),
            "witnessed": sum(1 for e in entries if e.get("status") == "witnessed"),
            "materials": len(mats),
            "batches": batch_count,
        }

"""File-based storage for the Ereztech ELN.

Everything lives under one data directory (a mounted NAS / SharePoint-synced
folder). All records are human-readable: Markdown with YAML frontmatter for
entries, materials and batches; JSON for users; plain-text append-only audit
logs. No database — the files ARE the notebook.

Layout:
    <root>/
      users.json
      notebook/<username>/ELN-2026-0001/entry.md
                                        audit.log
                                        structures/struct-01.ket|.mol|.v2000.mol|.svg
                                        attachments/<files>
      materials/<slug>/material.md
                       batches/<lot>.md
                       attachments/<lot>/<files>
      inventory_transactions.jsonl

Entries are grouped into a folder per author (their personal lab book) but keep
globally-unique ids (ELN-YEAR-SEQ) so cross-references resolve regardless of who
owns them.
"""
import datetime
import copy
import json
import os
import re
import threading
import uuid
from contextlib import contextmanager

import yaml

_LOCK = threading.RLock()


def _chmod_private(path):
    """Owner-only permissions for files holding secrets (password hashes,
    tokens). Best-effort: network mounts (SMB/NFS) may not support chmod."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

ENTRY_SECTIONS = ["Objective", "Procedure", "Results & Conclusions"]
ENTRY_STATUSES = ["draft", "signed", "witnessed"]
DEFAULT_ROLES = [
    {"key": "admin", "label": "Administrator", "color": "#7a00df",
     "can_admin": True, "can_edit": True},
    {"key": "scientist", "label": "Scientist", "color": "#04194e",
     "can_admin": False, "can_edit": True},
    {"key": "viewer", "label": "Viewer", "color": "#8a8797",
     "can_admin": False, "can_edit": False},
]
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
    (e.g. 'Observations & Data' from entries created before Actions and Observations)."""
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
        self.roles_file = os.path.join(self.root, "roles.json")
        self.inventory_file = os.path.join(self.root, "inventory_transactions.jsonl")
        from .chem import PropertyDB
        self.properties = PropertyDB(os.path.join(self.root, "properties.json"))
        # eid -> containing folder; an entry never moves once created, so this
        # is safe to cache and just saves rescanning user folders on read paths
        self._entry_dir_cache = {}
        # path -> (mtime_ns, size, parsed metadata). Entry list pages only need
        # frontmatter, so unchanged YAML is not reparsed on every request.
        self._entry_meta_cache = {}

    @contextmanager
    def mutation_lock(self):
        """Serialize read-modify-write requests within the Gunicorn worker."""
        with _LOCK:
            yield

    # ---------- layout / seed ----------

    def ensure_layout(self):
        os.makedirs(self.notebook_dir, exist_ok=True)
        os.makedirs(self.materials_dir, exist_ok=True)
        self.properties.ensure()
        self.ensure_roles()
        self._migrate_notebook_by_user()
        if not os.path.exists(self.users_file):
            from .seed import seed_initial_data
            seed_initial_data(self)
        self._ensure_inventory_opening_balances()

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

    def ensure_roles(self):
        if not os.path.exists(self.roles_file):
            self.save_roles(copy.deepcopy(DEFAULT_ROLES))

    def get_roles(self):
        with _LOCK:
            try:
                with open(self.roles_file, "r", encoding="utf-8") as f:
                    roles = json.load(f).get("roles", [])
            except (OSError, ValueError):
                roles = []
            return roles or copy.deepcopy(DEFAULT_ROLES)

    def save_roles(self, roles):
        with _LOCK:
            tmp = self.roles_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"roles": roles}, f, indent=2, ensure_ascii=False)
            _chmod_private(tmp)
            os.replace(tmp, self.roles_file)

    def find_role(self, key):
        return next((r for r in self.get_roles() if r.get("key") == key), None)

    def role_can_admin(self, key):
        role = self.find_role(key) or {}
        return bool(role.get("can_admin"))

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
            _chmod_private(tmp)    # password hashes — owner-only
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

    def next_page_number(self, author, chemist_number, notebook_number):
        """Return the next immutable page in one chemist's selected notebook."""
        highest = 0
        for _, path in self._iter_entry_paths():
            try:
                meta, _ = load_md(path)
            except Exception:
                continue
            if (meta.get("author") == author
                    and str(meta.get("chemist_number", "")) == chemist_number
                    and str(meta.get("notebook_number", "")) == notebook_number):
                try:
                    highest = max(highest, int(meta.get("page_number", 0)))
                except (TypeError, ValueError):
                    pass
        return highest + 1

    def list_entries(self):
        entries = []
        live_paths = set()
        for eid, path in self._iter_entry_paths():
            live_paths.add(path)
            try:
                stat = os.stat(path)
                cached = self._entry_meta_cache.get(path)
                signature = (stat.st_mtime_ns, stat.st_size)
                if cached and cached[:2] == signature:
                    meta = cached[2]
                else:
                    meta, _ = load_md(path)
                    self._entry_meta_cache[path] = (signature[0], signature[1], meta)
                entries.append(copy.deepcopy(meta))
            except Exception:
                continue
        # under the lock: a concurrent writer inserting mid-iteration would
        # raise "dictionary changed size during iteration" and 500 the listing
        with _LOCK:
            for stale in set(self._entry_meta_cache) - live_paths:
                self._entry_meta_cache.pop(stale, None)
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
            self._entry_meta_cache.pop(os.path.join(d, "entry.md"), None)

    def create_entry(self, meta, body):
        with _LOCK:
            eid = self.next_entry_id()
            user = self.find_user(meta.get("author")) or {}
            chemist_number = str(user.get("chemist_number", "")).strip()
            notebook_number = str(user.get("notebook_number", "")).strip()
            if not chemist_number or not notebook_number:
                raise ValueError("chemist and notebook numbers must be set before creating an entry")
            meta["chemist_number"] = chemist_number
            meta["notebook_number"] = notebook_number
            meta["page_number"] = self.next_page_number(
                meta.get("author"), chemist_number, notebook_number)
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
            if b["kind"] == "photo":
                # Photo observations historically store a Markdown link. Expose
                # its target separately so the log can render a thumbnail while
                # remaining compatible with existing notebook files.
                match = re.search(r"\[([^\]]+)\]\(([^)]+)\)", b["text"])
                if match:
                    b["photo_name"] = match.group(1)
                    b["photo_url"] = match.group(2)
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

    # ---------- inventory ledger ----------

    def record_inventory_transaction(self, record):
        """Append one immutable, human-readable JSON transaction."""
        row = dict(record)
        row.setdefault("id", uuid.uuid4().hex)
        row.setdefault("at", utcnow())
        with _LOCK:
            with open(self.inventory_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return row

    def inventory_transactions(self, material=None, lot_slug=None, eid=None):
        rows = []
        try:
            with open(self.inventory_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        row = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    if material is not None and row.get("material") != material:
                        continue
                    if lot_slug is not None and row.get("lot_slug") != lot_slug:
                        continue
                    if eid is not None and row.get("entry_id") != eid:
                        continue
                    rows.append(row)
        except OSError:
            pass
        rows.reverse()
        return rows

    def apply_inventory_delta(self, slug, lot_slug, delta_base, base_unit,
                              username, action, preferred_unit=None, **context):
        """Adjust a batch balance and append the matching ledger record."""
        from .inventory import batch_quantity, format_base, set_batch_quantity, unit_family
        with _LOCK:
            delta_base = float(delta_base)
            meta, notes = self.get_batch(slug, lot_slug)
            if meta is None:
                raise ValueError("The selected inventory batch no longer exists.")
            current = batch_quantity(meta)
            if unit_family(current["base_unit"]) != unit_family(base_unit):
                raise ValueError("The reported unit is not compatible with this batch.")
            new_balance = current["base_value"] + delta_base
            if new_balance < -1e-9:
                raise ValueError("Insufficient inventory in batch %s." % meta.get("lot", lot_slug))
            new_balance = max(0.0, new_balance)
            display_unit = preferred_unit or current["unit"]
            set_batch_quantity(meta, new_balance, current["base_unit"], display_unit)
            if new_balance <= 1e-12 and meta.get("status") in ("In Stock", "Open"):
                meta["status"] = "Depleted"
            elif new_balance > 1e-12 and meta.get("status") == "Depleted":
                meta["status"] = "Open"
            meta["inventory_updated"] = utcnow()
            meta["inventory_updated_by"] = username
            self.save_batch(slug, lot_slug, meta, notes)
            signed_delta = ("+" if delta_base > 0 else "−" if delta_base < 0 else "")
            row = {
                "material": slug, "lot_slug": lot_slug,
                "lot": meta.get("lot", lot_slug), "by": username,
                "action": action, "delta_base": round(delta_base, 12),
                "base_unit": current["base_unit"],
                "delta_display": signed_delta + format_base(abs(delta_base),
                                                              current["base_unit"], display_unit),
                "balance_after_base": round(new_balance, 12),
                "balance_display": format_base(new_balance, current["base_unit"], display_unit),
            }
            row.update({k: v for k, v in context.items() if v is not None})
            return meta, self.record_inventory_transaction(row)

    def _ensure_inventory_opening_balances(self):
        """Normalize legacy quantities and establish an audited opening balance."""
        from .inventory import batch_quantity, parse_legacy_quantity, set_batch_quantity
        existing = {(r.get("material"), r.get("lot_slug"))
                    for r in self.inventory_transactions()}
        for material in self.list_materials():
            slug = material.get("slug")
            if not slug:
                continue
            for batch in self.list_batches(slug):
                lot_slug = batch.get("lot_slug")
                if not lot_slug or (slug, lot_slug) in existing:
                    continue
                has_normalized = batch.get("quantity_base") is not None
                if not has_normalized and not parse_legacy_quantity(batch.get("quantity")):
                    continue
                quantity = batch_quantity(batch)
                notes = batch.pop("_notes", "")
                set_batch_quantity(batch, quantity["base_value"], quantity["base_unit"],
                                   quantity["unit"])
                self.save_batch(slug, lot_slug, batch, notes)
                self.record_inventory_transaction({
                    "material": slug, "lot_slug": lot_slug,
                    "lot": batch.get("lot", lot_slug), "by": "system",
                    "action": "opening balance", "delta_base": quantity["base_value"],
                    "base_unit": quantity["base_unit"],
                    "delta_display": "+" + quantity["display"],
                    "balance_after_base": quantity["base_value"],
                    "balance_display": quantity["display"],
                    "detail": "Inventory ledger initialized from the recorded batch quantity.",
                })

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
            records = list(meta.get("materials") or []) + list(
                meta.get("inventory_allocations") or [])
            for used in records:
                if used.get("material") == slug and used.get("lot") == lot:
                    hits.append(meta["id"])
                    break
        return hits

    def entries_using_material(self, slug):
        hits = []
        for meta in self.list_entries():
            records = list(meta.get("materials") or []) + list(
                meta.get("inventory_allocations") or [])
            for used in records:
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

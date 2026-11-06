"""File-based storage for the Ereztech Safety Training app.

Everything lives under one data directory (a mounted NAS / SharePoint-synced
folder). All records are human-readable: YAML for the curriculum, JSON for
users and settings, Markdown with YAML frontmatter for sign-off records, and
append-only JSON-lines / plain-text logs for watch history, quiz attempts and
the audit trail. No database — the files ARE the training record.

Layout:
    <root>/
      users.json  roles.json  settings.json  .secret_key
      curriculum/playlist.yaml        parts, tracks, videos + context text
      curriculum/quiz.yaml            questions with answer letters
      records/<username>/
        watched.jsonl                 one line per "marked watched" event
        attempts.jsonl                one line per scored quiz attempt
        completions/TRN-2026-0001.md  signed / verified training records
        audit.log                     append-only event history
"""
import copy
import datetime
import json
import os
import re
import shutil
import threading
import uuid
from contextlib import contextmanager

import yaml

_LOCK = threading.RLock()

DEFAULT_ROLES = [
    {"key": "admin", "label": "Administrator", "color": "#7a00df",
     "can_admin": True, "can_verify": True},
    {"key": "trainer", "label": "Trainer", "color": "#04194e",
     "can_admin": False, "can_verify": True},
    {"key": "trainee", "label": "Trainee", "color": "#8a8797",
     "can_admin": False, "can_verify": False},
]
DEFAULT_SETTINGS = {"retrain_months": 12, "due_soon_days": 30, "timezone": "America/Chicago"}
COMPLETION_STATUSES = ["signed", "verified", "returned"]
CONTENT_DIR = os.path.join(os.path.dirname(__file__), "content")


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(s):
    if not s:
        return None
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None


def _chmod_private(path):
    """Owner-only permissions for files holding secrets (password hashes).
    Best-effort: network mounts (SMB/NFS) may not support chmod."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


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


def _write_json(path, data, private=False):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    if private:
        _chmod_private(tmp)
    os.replace(tmp, path)


def _read_jsonl(path):
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue    # a torn line never hides the rest of the history
    return rows


class Storage:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.users_file = os.path.join(self.root, "users.json")
        self.roles_file = os.path.join(self.root, "roles.json")
        self.settings_file = os.path.join(self.root, "settings.json")
        self.curriculum_dir = os.path.join(self.root, "curriculum")
        self.records_dir = os.path.join(self.root, "records")
        # path -> (mtime_ns, size, parsed) so edited YAML on the share is picked
        # up on the next request without reparsing on every page view
        self._yaml_cache = {}

    @contextmanager
    def mutation_lock(self):
        """Serialize read-modify-write requests within the Gunicorn worker."""
        with _LOCK:
            yield

    # ---------- layout / seed ----------

    def ensure_layout(self):
        os.makedirs(self.curriculum_dir, exist_ok=True)
        os.makedirs(self.records_dir, exist_ok=True)
        for name in ("playlist.yaml", "quiz.yaml"):
            target = os.path.join(self.curriculum_dir, name)
            if not os.path.exists(target):
                shutil.copyfile(os.path.join(CONTENT_DIR, name), target)
        if not os.path.exists(self.roles_file):
            self.save_roles(copy.deepcopy(DEFAULT_ROLES))
        if not os.path.exists(self.settings_file):
            self.save_settings(dict(DEFAULT_SETTINGS))
        if not os.path.exists(self.users_file):
            from .seed import seed_initial_data
            seed_initial_data(self)

    # ---------- settings ----------

    def get_settings(self):
        with _LOCK:
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = {}
        merged = dict(DEFAULT_SETTINGS)
        merged.update({k: v for k, v in data.items() if v is not None})
        return merged

    def save_settings(self, data):
        with _LOCK:
            _write_json(self.settings_file, data)

    # ---------- roles & users ----------

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
            _write_json(self.roles_file, {"roles": roles})

    def find_role(self, key):
        return next((r for r in self.get_roles() if r.get("key") == key), None)

    def get_users(self):
        with _LOCK:
            try:
                with open(self.users_file, "r", encoding="utf-8") as f:
                    return json.load(f).get("users", [])
            except (OSError, ValueError):
                return []

    def save_users(self, users):
        with _LOCK:
            _write_json(self.users_file, {"users": users}, private=True)  # password hashes

    def find_user(self, username):
        for u in self.get_users():
            if u["username"] == username:
                return u
        return None

    # ---------- curriculum (YAML on the share, hot-reloaded) ----------

    def _load_yaml(self, name):
        path = os.path.join(self.curriculum_dir, name)
        try:
            st = os.stat(path)
        except OSError:
            path = os.path.join(CONTENT_DIR, name)
            st = os.stat(path)
        key = (st.st_mtime_ns, st.st_size)
        cached = self._yaml_cache.get(path)
        if cached and cached[0] == key:
            return cached[1]
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        self._yaml_cache[path] = (key, data)
        return data

    def playlist(self):
        return self._load_yaml("playlist.yaml")

    def quiz(self):
        return self._load_yaml("quiz.yaml")

    # ---------- per-user training records ----------

    @staticmethod
    def user_folder_name(username):
        """A filesystem-safe folder name confined to a single subdirectory.
        Neutralises names that are all dots so a username can never resolve to
        a path-traversal component."""
        name = (username or "unassigned").strip()
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
        if not safe or not safe.strip("."):
            return "unassigned"
        return safe

    def user_dir(self, username, create=False):
        d = os.path.join(self.records_dir, self.user_folder_name(username))
        if create:
            os.makedirs(os.path.join(d, "completions"), exist_ok=True)
        return d

    def _append_jsonl(self, username, name, record):
        with _LOCK:
            d = self.user_dir(username, create=True)
            with open(os.path.join(d, name), "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def mark_watched(self, username, video_id, title):
        rec = {"at": utcnow(), "video": video_id, "title": title}
        self._append_jsonl(username, "watched.jsonl", rec)
        return rec

    def watch_history(self, username):
        return _read_jsonl(os.path.join(self.user_dir(username), "watched.jsonl"))

    def add_attempt(self, username, attempt):
        attempt = dict(attempt)
        attempt.setdefault("at", utcnow())
        attempt["id"] = "QA-%s-%s" % (attempt["at"][:10].replace("-", ""), uuid.uuid4().hex[:6])
        attempt["username"] = username
        self._append_jsonl(username, "attempts.jsonl", attempt)
        return attempt

    def attempts(self, username):
        return _read_jsonl(os.path.join(self.user_dir(username), "attempts.jsonl"))

    def get_attempt(self, username, attempt_id):
        return next((a for a in self.attempts(username) if a.get("id") == attempt_id), None)

    # ---------- sign-off records (TRN-YYYY-NNNN) ----------

    def _completion_paths(self):
        if not os.path.isdir(self.records_dir):
            return
        for user in sorted(os.listdir(self.records_dir)):
            cdir = os.path.join(self.records_dir, user, "completions")
            if not os.path.isdir(cdir):
                continue
            for name in sorted(os.listdir(cdir)):
                if name.endswith(".md"):
                    yield os.path.join(cdir, name)

    def next_completion_id(self):
        year = datetime.datetime.now(datetime.timezone.utc).year
        prefix = "TRN-%d-" % year
        nums = [int(os.path.basename(p)[len(prefix):-3])
                for p in self._completion_paths()
                if os.path.basename(p).startswith(prefix)
                and os.path.basename(p)[len(prefix):-3].isdigit()]
        return "%s%04d" % (prefix, (max(nums) + 1) if nums else 1)

    def completions(self, username):
        cdir = os.path.join(self.user_dir(username), "completions")
        out = []
        if os.path.isdir(cdir):
            for name in sorted(os.listdir(cdir)):
                if name.endswith(".md"):
                    meta, body = load_md(os.path.join(cdir, name))
                    meta["_body"] = body
                    out.append(meta)
        return out

    def get_completion(self, username, cid):
        if not re.fullmatch(r"TRN-\d{4}-\d{4}", cid or ""):
            return None
        path = os.path.join(self.user_dir(username), "completions", cid + ".md")
        if not os.path.isfile(path):
            return None
        meta, body = load_md(path)
        meta["_body"] = body
        return meta

    def save_completion(self, username, meta, body):
        with _LOCK:
            d = os.path.join(self.user_dir(username, create=True), "completions")
            clean = {k: v for k, v in meta.items() if not k.startswith("_")}
            dump_md(os.path.join(d, clean["id"] + ".md"), clean, body)

    # ---------- audit trail ----------

    def audit(self, username, actor, action, detail=""):
        with _LOCK:
            d = self.user_dir(username, create=True)
            line = "%s | %s | %s" % (utcnow(), actor, action)
            if detail:
                line += " | " + detail.replace("\n", " ")
            with open(os.path.join(d, "audit.log"), "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def read_audit(self, username):
        path = os.path.join(self.user_dir(username), "audit.log")
        if not os.path.isfile(path):
            return []
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                parts = [p.strip() for p in line.rstrip("\n").split(" | ", 3)]
                if len(parts) >= 3:
                    rows.append({"at": parts[0], "by": parts[1], "action": parts[2],
                                 "detail": parts[3] if len(parts) > 3 else ""})
        return rows

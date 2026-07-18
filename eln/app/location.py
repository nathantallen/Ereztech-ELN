"""Assignable data-storage location.

The notebook's data directory can be re-pointed at runtime to any folder the
container can see — typically a mounted NAS / SharePoint share — chosen by
browsing the filesystem. Which folder is active is remembered in a tiny pointer
file that lives OUTSIDE the data directory (so it survives the data dir moving),
in a small config directory that persists across container restarts.

Browsing is constrained to a configured set of roots (ELN_BROWSE_ROOTS) so the
UI can only reach intended mount points, never the whole container filesystem.
"""
import json
import os
import re
import shutil

_CONFIG_DIR = None


def config_dir():
    """A small, writable, persistent directory for the location pointer."""
    global _CONFIG_DIR
    if _CONFIG_DIR:
        return _CONFIG_DIR
    candidates = [os.environ.get("ELN_CONFIG_DIR"), "/config",
                  os.path.join(os.getcwd(), ".eln-config")]
    for cand in candidates:
        if not cand:
            continue
        try:
            os.makedirs(cand, exist_ok=True)
            test = os.path.join(cand, ".writetest")
            with open(test, "w", encoding="utf-8") as f:
                f.write("")
            os.remove(test)
            _CONFIG_DIR = cand
            return cand
        except OSError:
            continue
    _CONFIG_DIR = os.getcwd()
    return _CONFIG_DIR


def _pointer_file():
    return os.path.join(config_dir(), "location.json")


def default_data_dir():
    return os.environ.get("ELN_DATA_DIR") or os.path.join(os.getcwd(), "data")


def get_pointer_target():
    """The data dir the admin last assigned (regardless of whether it is
    currently reachable), or None if never assigned."""
    try:
        with open(_pointer_file(), "r", encoding="utf-8") as f:
            path = json.load(f).get("data_dir")
        return os.path.abspath(path) if path else None
    except (OSError, ValueError):
        return None


def get_data_dir():
    """Active data directory: the pointer's target if set & present, else default."""
    target = get_pointer_target()
    if target and os.path.isdir(target):
        return target
    return os.path.abspath(default_data_dir())


def set_data_dir(path):
    tmp = _pointer_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"data_dir": os.path.abspath(path)}, f, indent=2)
    os.replace(tmp, _pointer_file())


# ---------- browsing ----------

def browse_roots():
    env = os.environ.get("ELN_BROWSE_ROOTS")
    roots = [r for r in (env.split(os.pathsep) if env else []) if r]
    if not roots:
        roots = ["/mnt", "/browse", "/nas", "/data"]
    roots = [os.path.abspath(r) for r in roots if os.path.isdir(r)]
    # make sure the current location is always reachable (it may be a re-pointed
    # folder not listed in ELN_BROWSE_ROOTS), but never widen to the FS root
    cur = get_data_dir()
    if os.path.isdir(cur) and not any(
            cur == r or cur.startswith(r + os.sep) for r in roots):
        roots.append(cur)
    return roots


def is_allowed(path):
    """True if `path` sits within one of the browse roots (symlinks resolved)."""
    try:
        rp = os.path.realpath(path)
    except OSError:
        return False
    for root in browse_roots():
        rr = os.path.realpath(root)
        if rp == rr or rp.startswith(rr + os.sep):
            return True
    return False


def list_dir(path):
    """List sub-directories of an allowed path, for the browse UI."""
    path = os.path.abspath(path or "")
    if not path or not is_allowed(path) or not os.path.isdir(path):
        return None
    dirs = []
    try:
        for name in sorted(os.listdir(path), key=str.lower):
            full = os.path.join(path, name)
            if os.path.isdir(full) and not name.startswith("."):
                dirs.append({"name": name, "path": full,
                             "is_eln": os.path.isfile(os.path.join(full, "users.json"))})
    except OSError:
        return None
    parent = os.path.dirname(path)
    is_store = os.path.isfile(os.path.join(path, "users.json"))
    return {
        "path": path,
        "parent": parent if (parent != path and is_allowed(parent)) else None,
        "is_eln_store": is_store,
        "has_content": _dir_has_content(path),
        "writable": os.access(path, os.W_OK),
        "dirs": dirs,
    }


def make_dir(parent, name):
    """Create a single new sub-folder inside an allowed parent. Returns the new
    absolute path, or None on any validation/OS error."""
    if not parent or not is_allowed(parent) or not os.path.isdir(parent):
        return None
    name = (name or "").strip()
    if (not name or os.sep in name or (os.altsep and os.altsep in name)
            or name in (".", "..") or not re.fullmatch(r"[A-Za-z0-9 ._-]+", name)):
        return None
    new_path = os.path.abspath(os.path.join(parent, name))
    if not is_allowed(new_path):
        return None
    try:
        os.makedirs(new_path, exist_ok=True)
    except OSError:
        return None
    return new_path


# ---------- applying a new location ----------

def _within(child, parent):
    """True if `child` is `parent` or nested inside it. Uses commonpath so it is
    correct at the filesystem root and immune to sibling-prefix ("/nas" vs
    "/nasty") false positives."""
    child, parent = os.path.realpath(child), os.path.realpath(parent)
    if child == parent:
        return True
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:      # different drives / mixed abs+rel
        return False


def _dir_has_content(path):
    """True if the directory holds anything other than dotfiles."""
    try:
        return any(not n.startswith(".") for n in os.listdir(path))
    except OSError:
        return False


def active_run_blockers(app):
    """Names of things that would be writing during a relocation: entries whose
    lab work is in progress, plus any live poller/recording. Empty list == safe
    to relocate."""
    from . import ha
    blockers = []
    try:
        for meta in app.extensions["storage"].list_entries():
            ops = meta.get("operations") or {}
            if ops.get("started_at") and not ops.get("ended_at"):
                blockers.append(meta.get("id", "?"))
    except Exception:
        pass
    if ha.background_active():
        blockers.append("a sensor log or recording")
    return blockers


def switch(app, target, make_subdir=None):
    """Re-point the app's data store at `target` (optionally creating a new
    subfolder in it first). Returns (ok, message).

    - If the target already holds an ELN store (users.json), it is adopted as-is.
    - If the target is an EMPTY folder, the current data is copied in (moving the
      notebook to the new location) so nothing is lost and logins keep working.
    - A non-empty folder that is NOT an ELN store is refused, so we never merge
      over / clobber unrelated content.

    Relocation is refused while any experiment is running (so there are no live
    writers), and for the duration of the copy the app enters MAINTENANCE mode:
    reads/login still work, but every mutating request is refused, so nothing can
    write into the source mid-copy. users.json is copied LAST, so an interrupted
    copy is never mistaken for a complete store on a later retry.
    """
    from .storage import Storage
    from . import ha

    if not is_allowed(target):
        return False, "That location is outside the allowed browse roots."
    if make_subdir:
        safe = make_subdir.strip()
        if (os.sep in safe or (os.altsep and os.altsep in safe)
                or safe in (".", "..") or not re.fullmatch(r"[A-Za-z0-9 ._-]+", safe)):
            return False, "Invalid new-folder name."
        target = os.path.join(target, safe)
    target_abs = os.path.abspath(target)
    # re-validate the FINAL target: a make_subdir of ".." (now blocked above) or
    # any other trickery must not escape the allowed roots
    if not is_allowed(target_abs):
        return False, "That location is outside the allowed browse roots."

    current = os.path.abspath(app.config["DATA_DIR"])
    if target_abs == current:
        return False, "That is already the current data location."
    if _within(target_abs, current) or _within(current, target_abs):
        return False, ("The new location cannot be inside the current data "
                       "folder (or vice versa).")

    # do not relocate a store that is being actively written to
    blockers = active_run_blockers(app)
    if blockers:
        return False, ("Cannot relocate while lab work is in progress (%s). End "
                       "the run(s) first, then try again." % ", ".join(blockers))

    try:
        os.makedirs(target_abs, exist_ok=True)
    except OSError as e:
        return False, "Could not create %s: %s" % (target_abs, e)
    if not os.access(target_abs, os.W_OK):
        return False, "That location is not writable by the app."

    target_is_store = os.path.isfile(os.path.join(target_abs, "users.json"))
    if not target_is_store and _dir_has_content(target_abs):
        return False, ("That folder isn't empty and isn't an existing EreZtech "
                       "notebook. Choose an empty folder, or create a new subfolder "
                       "in it.")

    # MAINTENANCE mode: the before_request gate now refuses every mutating request
    # (POST/PUT/DELETE) so no request thread can write into the source during the
    # copy, while reads and login keep working. Guaranteed cleared in finally.
    app.config["MAINTENANCE"] = True
    try:
        ha.stop_all()   # belt-and-suspenders: no live pollers given the guard above
        copied = False
        if not target_is_store:
            try:
                names = sorted(os.listdir(current), key=lambda n: n == "users.json")
                for name in names:                       # users.json copied LAST
                    src = os.path.join(current, name)
                    dst = os.path.join(target_abs, name)
                    if os.path.isdir(src):
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)
                copied = True
            except OSError as e:
                # roll back the partial copy so a retry sees a clean, empty target
                for name in os.listdir(target_abs):
                    p = os.path.join(target_abs, name)
                    try:
                        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
                    except OSError:
                        pass
                return False, "Copy to new location failed (rolled back): %s" % e

        new_storage = Storage(target_abs)
        new_storage.ensure_layout()
        app.config["DATA_DIR"] = target_abs
        app.config["STORAGE_FALLBACK"] = None
        app.config["TIMEZONE"] = new_storage.get_timezone()   # follows the new store
        app.extensions["storage"] = new_storage
        set_data_dir(target_abs)
    finally:
        app.config["MAINTENANCE"] = False
        # Always revive pollers — on the active store, whichever it ended up being
        # (the new one on success; the old one still in place on any failure/return).
        ha.resume_pollers(app.extensions["storage"])

    if target_is_store:
        return True, "Now using the existing notebook at %s." % target_abs
    return True, ("Data moved to %s. The previous copy at %s was left in place; "
                  "delete it once you've confirmed everything works."
                  % (target_abs, current))

import os
import shutil

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required

from . import location

bp = Blueprint("main", __name__)

# curated IANA zones for the picker; any valid zoneinfo name is also accepted
COMMON_TIMEZONES = [
    "UTC",
    "America/New_York", "America/Chicago", "America/Denver", "America/Phoenix",
    "America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu",
    "America/Toronto", "America/Sao_Paulo",
    "Europe/London", "Europe/Berlin", "Europe/Paris", "Europe/Madrid",
    "Europe/Amsterdam", "Europe/Zurich",
    "Asia/Jerusalem", "Asia/Dubai", "Asia/Kolkata", "Asia/Shanghai",
    "Asia/Singapore", "Asia/Tokyo", "Asia/Seoul",
    "Australia/Sydney", "Pacific/Auckland",
]


def _storage():
    return current_app.extensions["storage"]


@bp.route("/")
@login_required
def home():
    return redirect(url_for("entries.list_entries"))


@bp.route("/settings")
@login_required
def settings():
    storage = _storage()
    data_dir = storage.root
    try:
        usage = shutil.disk_usage(data_dir)
        disk = {"total_gb": usage.total / 1e9, "free_gb": usage.free / 1e9}
    except OSError:
        disk = None
    tree = []
    for name in ("users.json", "notebook", "materials"):
        tree.append({"name": name, "exists": os.path.exists(os.path.join(data_dir, name))})
    current_tz = current_app.config.get("TIMEZONE") or ""
    tz_options = list(COMMON_TIMEZONES)
    if current_tz and current_tz not in tz_options:
        tz_options.insert(0, current_tz)
    return render_template("settings.html", data_dir=data_dir, disk=disk, tree=tree,
                           browse_roots=location.browse_roots(),
                           config_dir=location.config_dir(),
                           timezone=current_tz, tz_options=tz_options,
                           max_upload_mb=current_app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024))


@bp.route("/settings/timezone", methods=["POST"])
@login_required
def set_timezone():
    if not current_user.is_admin:
        abort(403)
    tz = request.form.get("timezone", "").strip()
    if tz:
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(tz)          # validate against the tz database
        except Exception:
            flash("Unknown time zone: %s" % tz, "error")
            return redirect(url_for("main.settings"))
    _storage().set_timezone(tz)
    current_app.config["TIMEZONE"] = tz
    flash("Time zone set to %s." % (tz or "viewer's local time"), "success")
    return redirect(url_for("main.settings"))


@bp.route("/settings/browse")
@login_required
def browse():
    """JSON directory listing for the storage-location picker (admin only)."""
    if not current_user.is_admin:
        abort(403)
    path = request.args.get("path", "")
    if not path:
        roots = location.browse_roots()
        return jsonify({"roots": roots,
                        "path": "", "parent": None, "dirs": [
                            {"name": r, "path": r,
                             "is_eln": os.path.isfile(os.path.join(r, "users.json"))}
                            for r in roots]})
    listing = location.list_dir(path)
    if listing is None:
        return jsonify({"error": "That folder can't be browsed."}), 400
    listing["roots"] = location.browse_roots()
    return jsonify(listing)


@bp.route("/settings/mkdir", methods=["POST"])
@login_required
def mkdir():
    """Create a new sub-folder inside an allowed parent (the dialog's New Folder)."""
    if not current_user.is_admin:
        abort(403)
    parent = (request.get_json(silent=True) or {}).get("parent", "")
    name = (request.get_json(silent=True) or {}).get("name", "").strip()
    new_path = location.make_dir(parent, name)
    if not new_path:
        return jsonify({"error": "Could not create that folder."}), 400
    return jsonify({"path": new_path})


@bp.route("/settings/location", methods=["POST"])
@login_required
def set_location():
    if not current_user.is_admin:
        abort(403)
    target = request.form.get("path", "").strip()
    make_subdir = request.form.get("new_folder", "").strip() or None
    if not target:
        flash("No location selected.", "error")
        return redirect(url_for("main.settings"))
    ok, message = location.switch(current_app._get_current_object(), target, make_subdir)
    flash(message, "success" if ok else "error")
    return redirect(url_for("main.settings"))

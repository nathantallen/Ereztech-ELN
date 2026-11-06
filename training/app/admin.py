import re

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.security import generate_password_hash

bp = Blueprint("admin", __name__, url_prefix="/admin")

ROLE_KEY_RE = re.compile(r"[a-z0-9_-]+")
# a username also becomes a records folder name, so keep it to a safe charset
USERNAME_RE = re.compile(r"[a-z0-9._-]+")
MIN_PASSWORD = 8


def _storage():
    return current_app.extensions["storage"]


def _require_admin():
    if not current_user.is_admin:
        abort(403)


def _role_can_admin(roles, key):
    return any(r.get("key") == key and r.get("can_admin") for r in roles)


def _active_admin_count(users, roles, exclude_username=None):
    admin_roles = {r["key"] for r in roles if r.get("can_admin")}
    return sum(1 for u in users if u.get("active", True)
               and u.get("role") in admin_roles
               and u.get("username") != exclude_username)


def _valid_tracks(form):
    keys = {t["key"] for t in _storage().playlist().get("tracks", [])}
    return [t for t in form.getlist("tracks") if t in keys and t != "core"]


@bp.route("/users")
@login_required
def list_users():
    _require_admin()
    storage = _storage()
    return render_template("users.html", users=storage.get_users(), roles=storage.get_roles(),
                           tracks=storage.playlist().get("tracks", []))


@bp.route("/users/new", methods=["GET", "POST"])
@bp.route("/users/<username>/edit", methods=["GET", "POST"])
@login_required
def user_form(username=None):
    _require_admin()
    storage = _storage()
    users = storage.get_users()
    roles = storage.get_roles()
    role_keys = {r["key"] for r in roles}
    tracks = storage.playlist().get("tracks", [])
    user = next((u for u in users if u["username"] == username), None) if username else None
    if username and not user:
        abort(404)
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        role = request.form.get("role", "")
        if role not in role_keys:
            # fail closed: never silently substitute a role
            flash("Unknown role %r — it may have been renamed or deleted. "
                  "Reload the page and try again." % role, "error")
            return redirect(url_for("admin.list_users"))
        password = request.form.get("password", "")
        if password and len(password) < MIN_PASSWORD:
            flash("Passwords must be at least %d characters." % MIN_PASSWORD, "error")
            return redirect(request.path)
        active = bool(request.form.get("active"))
        chosen = _valid_tracks(request.form)
        if user:
            if user["username"] == current_user.username and not active:
                flash("You cannot deactivate your own account.", "error")
                return redirect(url_for("admin.list_users"))
            was_admin = _role_can_admin(roles, user.get("role")) and user.get("active", True)
            still_admin = _role_can_admin(roles, role) and active
            if was_admin and not still_admin and _active_admin_count(users, roles, user["username"]) == 0:
                flash("You can't remove the last administrator. Promote another user to admin first.", "error")
                return redirect(url_for("admin.list_users"))
            before = sorted(user.get("tracks") or [])
            user["full_name"] = full_name or user["full_name"]
            user["role"] = role
            user["active"] = active
            user["tracks"] = chosen
            if password:
                user["password_hash"] = generate_password_hash(password)
            if before != sorted(chosen):
                storage.audit(user["username"], current_user.username, "tracks assigned",
                              ", ".join(["core"] + chosen))
        else:
            uname = request.form.get("username", "").strip().lower()
            if not uname or not password:
                flash("Username and password are required.", "error")
                return redirect(url_for("admin.user_form"))
            if uname in (".", "..") or not USERNAME_RE.fullmatch(uname):
                flash("Username may only contain letters, numbers, dot, dash and underscore.", "error")
                return redirect(url_for("admin.user_form"))
            if any(u["username"] == uname for u in users):
                flash("That username already exists.", "error")
                return redirect(url_for("admin.user_form"))
            users.append({
                "username": uname,
                "full_name": full_name or uname,
                "password_hash": generate_password_hash(password),
                "role": role,
                "tracks": chosen,
                "active": True,
            })
            storage.audit(uname, current_user.username, "user created",
                          "tracks: " + ", ".join(["core"] + chosen))
        storage.save_users(users)
        flash("User saved.", "success")
        return redirect(url_for("admin.list_users"))
    return render_template("user_form.html", user=user, roles=roles, tracks=tracks)


@bp.route("/roles/new", methods=["GET", "POST"])
@bp.route("/roles/<key>/edit", methods=["GET", "POST"])
@login_required
def role_form(key=None):
    _require_admin()
    storage = _storage()
    roles = storage.get_roles()
    role = next((r for r in roles if r.get("key") == key), None) if key else None
    if key and not role:
        abort(404)
    if request.method == "POST":
        new_key = key or request.form.get("key", "").strip().lower()
        label = request.form.get("label", "").strip()
        color = request.form.get("color", "#8a8797").strip()
        can_admin = bool(request.form.get("can_admin"))
        can_verify = bool(request.form.get("can_verify")) or can_admin
        if not ROLE_KEY_RE.fullmatch(new_key) or not label:
            flash("Role key and display name are required. Keys may use letters, numbers, dash and underscore.", "error")
            return render_template("role_form.html", role=role)
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            color = "#8a8797"
        if not role and any(r.get("key") == new_key for r in roles):
            flash("That role key already exists.", "error")
            return render_template("role_form.html", role=role)
        updated = {"key": new_key, "label": label, "color": color,
                   "can_admin": can_admin, "can_verify": can_verify}
        candidate = [updated if r.get("key") == key else r for r in roles] if role else roles + [updated]
        if _active_admin_count(storage.get_users(), candidate) == 0:
            flash("At least one active user must retain an administrator-capable role.", "error")
            return render_template("role_form.html", role=role)
        storage.save_roles(candidate)
        flash("Role saved.", "success")
        return redirect(url_for("admin.list_users"))
    return render_template("role_form.html", role=role)


@bp.route("/roles/<key>/delete", methods=["POST"])
@login_required
def delete_role(key):
    _require_admin()
    storage = _storage()
    roles = storage.get_roles()
    if not any(r.get("key") == key for r in roles):
        abort(404)
    if any(u.get("role") == key for u in storage.get_users()):
        flash("That role is assigned to one or more users and cannot be deleted.", "error")
        return redirect(url_for("admin.list_users"))
    candidate = [r for r in roles if r.get("key") != key]
    if not candidate:
        flash("At least one role is required.", "error")
        return redirect(url_for("admin.list_users"))
    storage.save_roles(candidate)
    flash("Role deleted.", "success")
    return redirect(url_for("admin.list_users"))


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    _require_admin()
    storage = _storage()
    current = storage.get_settings()
    if request.method == "POST":
        try:
            months = int(request.form.get("retrain_months", "12"))
            soon = int(request.form.get("due_soon_days", "30"))
        except ValueError:
            months, soon = -1, -1
        tz = request.form.get("timezone", "").strip()
        if not 1 <= months <= 60 or not 0 <= soon <= 365:
            flash("Retraining interval must be 1–60 months and the warning window 0–365 days.", "error")
            return render_template("settings.html", settings=current), 400
        if tz:
            try:
                from zoneinfo import ZoneInfo
                ZoneInfo(tz)
            except Exception:
                flash("Unknown timezone %r. Use an IANA name such as America/Chicago." % tz, "error")
                return render_template("settings.html", settings=current), 400
        current.update({"retrain_months": months, "due_soon_days": soon, "timezone": tz})
        storage.save_settings(current)
        flash("Settings saved.", "success")
        return redirect(url_for("admin.settings"))
    return render_template("settings.html", settings=current,
                           playlist=storage.playlist(), quiz=storage.quiz(), data_dir=storage.root)

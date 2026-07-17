import re

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.security import generate_password_hash

bp = Blueprint("admin", __name__, url_prefix="/admin")

ROLES = ("admin", "scientist", "viewer")
# a username also becomes a lab-book folder name, so keep it to a safe charset
USERNAME_RE = re.compile(r"[a-z0-9._-]+")


def _storage():
    return current_app.extensions["storage"]


def _require_admin():
    if not current_user.is_admin:
        abort(403)


@bp.route("/users")
@login_required
def list_users():
    _require_admin()
    return render_template("users.html", users=_storage().get_users())


@bp.route("/users/new", methods=["GET", "POST"])
@bp.route("/users/<username>/edit", methods=["GET", "POST"])
@login_required
def user_form(username=None):
    _require_admin()
    storage = _storage()
    users = storage.get_users()
    user = next((u for u in users if u["username"] == username), None) if username else None
    if username and not user:
        abort(404)
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        role = request.form.get("role", "viewer")
        role = role if role in ROLES else "viewer"
        password = request.form.get("password", "")
        active = bool(request.form.get("active"))
        if user:
            if user["username"] == current_user.username and not active:
                flash("You cannot deactivate your own account.", "error")
                return redirect(url_for("admin.list_users"))
            user["full_name"] = full_name or user["full_name"]
            user["role"] = role
            user["active"] = active
            if password:
                user["password_hash"] = generate_password_hash(password)
        else:
            uname = request.form.get("username", "").strip().lower()
            if not uname or not password:
                flash("Username and password are required.", "error")
                return redirect(url_for("admin.user_form"))
            if uname in (".", "..") or not USERNAME_RE.fullmatch(uname):
                flash("Username may only contain letters, numbers, dot, dash and "
                      "underscore.", "error")
                return redirect(url_for("admin.user_form"))
            if any(u["username"] == uname for u in users):
                flash("That username already exists.", "error")
                return redirect(url_for("admin.user_form"))
            users.append({
                "username": uname,
                "full_name": full_name or uname,
                "password_hash": generate_password_hash(password),
                "role": role,
                "active": True,
            })
        storage.save_users(users)
        flash("User saved.", "success")
        return redirect(url_for("admin.list_users"))
    return render_template("user_form.html", user=user, roles=ROLES)

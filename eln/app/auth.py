from urllib.parse import urlparse

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required, login_user, logout_user
from werkzeug.security import check_password_hash

bp = Blueprint("auth", __name__)


def _storage():
    return current_app.extensions["storage"]


def _safe_next(target):
    """Only allow same-site relative redirect targets — never an absolute or
    protocol-relative URL — so ?next= can't be used for post-login phishing."""
    if not target or not target.startswith("/") or target.startswith(("//", "/\\")):
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return None
    return target


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        rec = _storage().find_user(username)
        if rec and rec.get("active", True) and check_password_hash(rec["password_hash"], password):
            from . import User
            login_user(User(rec))
            return redirect(_safe_next(request.args.get("next")) or url_for("main.dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))

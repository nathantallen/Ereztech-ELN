import threading
import time
from urllib.parse import urlparse

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required, login_user, logout_user
from werkzeug.security import check_password_hash

bp = Blueprint("auth", __name__)
_ATTEMPTS = {}
_ATTEMPTS_LOCK = threading.Lock()
_WINDOW_SECONDS = 15 * 60
_MAX_FAILURES = 5


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


def _attempt_key(username):
    return (request.remote_addr or "unknown", username.lower())


def _blocked(key):
    now = time.monotonic()
    with _ATTEMPTS_LOCK:
        recent = [t for t in _ATTEMPTS.get(key, []) if now - t < _WINDOW_SECONDS]
        _ATTEMPTS[key] = recent
        return len(recent) >= _MAX_FAILURES


def _failed(key):
    with _ATTEMPTS_LOCK:
        _ATTEMPTS.setdefault(key, []).append(time.monotonic())


def _succeeded(key):
    with _ATTEMPTS_LOCK:
        _ATTEMPTS.pop(key, None)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        key = _attempt_key(username)
        if _blocked(key):
            flash("Too many sign-in attempts. Try again in 15 minutes.", "error")
            return render_template("login.html"), 429
        rec = _storage().find_user(username)
        if rec and rec.get("active", True) and check_password_hash(rec["password_hash"], password):
            _succeeded(key)
            from . import User
            rec = dict(rec)
            rec["_role"] = _storage().find_role(rec.get("role")) or {}
            login_user(User(rec))
            return redirect(_safe_next(request.args.get("next")) or url_for("entries.list_entries"))
        _failed(key)
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))

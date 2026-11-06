import threading
import time
from urllib.parse import urlparse

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

bp = Blueprint("auth", __name__)
MIN_PASSWORD = 8
_ATTEMPTS = {}
_ATTEMPTS_LOCK = threading.Lock()
_WINDOW_SECONDS = 15 * 60
_MAX_FAILURES = 5
_MAX_TRACKED_KEYS = 5000
_LAST_PRUNE = 0.0


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


def _prune_attempts(now, force=False):
    global _LAST_PRUNE
    if not force and len(_ATTEMPTS) < _MAX_TRACKED_KEYS and now - _LAST_PRUNE < 30:
        return
    _LAST_PRUNE = now
    for old_key, times in list(_ATTEMPTS.items()):
        recent = [t for t in times if now - t < _WINDOW_SECONDS]
        if recent:
            _ATTEMPTS[old_key] = recent
        else:
            _ATTEMPTS.pop(old_key, None)
    while len(_ATTEMPTS) >= _MAX_TRACKED_KEYS:
        oldest = min(_ATTEMPTS, key=lambda k: _ATTEMPTS[k][-1])
        _ATTEMPTS.pop(oldest, None)


def _blocked(key):
    now = time.monotonic()
    with _ATTEMPTS_LOCK:
        _prune_attempts(now, force=len(_ATTEMPTS) >= _MAX_TRACKED_KEYS)
        recent = [t for t in _ATTEMPTS.get(key, []) if now - t < _WINDOW_SECONDS]
        if recent:
            _ATTEMPTS[key] = recent
        return len(recent) >= _MAX_FAILURES


def _failed(key):
    with _ATTEMPTS_LOCK:
        now = time.monotonic()
        _prune_attempts(now)
        _ATTEMPTS.setdefault(key, []).append(now)


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
            return redirect(_safe_next(request.args.get("next")) or url_for("main.dashboard"))
        _failed(key)
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """Change your own password (the same password signs training records)."""
    storage = _storage()
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        rec = storage.find_user(current_user.username)
        if not rec or not check_password_hash(rec["password_hash"], current):
            flash("Current password is incorrect.", "error")
            return render_template("profile.html"), 400
        if len(new) < MIN_PASSWORD or new != confirm:
            flash("New passwords must match and be at least %d characters." % MIN_PASSWORD, "error")
            return render_template("profile.html"), 400
        users = storage.get_users()
        for record in users:
            if record.get("username") == current_user.username:
                record["password_hash"] = generate_password_hash(new)
                break
        storage.save_users(users)
        storage.audit(current_user.username, current_user.username, "password changed")
        flash("Password changed.", "success")
        return redirect(url_for("auth.profile"))
    return render_template("profile.html")

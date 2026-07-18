import datetime
import os
import re
import secrets

import bleach
import markdown as md
from flask import Flask, abort, g, request, session
from flask_login import LoginManager, UserMixin, current_user
from markupsafe import Markup, escape

from .storage import Storage, ENTRY_STATUSES

STATUS_COLORS = {"draft": "#8a8797", "signed": "#F7941E", "witnessed": "#0aa574"}
MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _readable(dt, label):
    """'Jul 16, 2026 3:58 PM CDT' from an aware datetime + tz label."""
    h = dt.hour % 12 or 12
    ap = "AM" if dt.hour < 12 else "PM"
    return "%s %d, %d %d:%02d %s %s" % (MONTHS[dt.month], dt.day, dt.year,
                                        h, dt.minute, ap, label)


class User(UserMixin):
    def __init__(self, record):
        self.record = record
        self.id = record["username"]
        self.username = record["username"]
        self.full_name = record.get("full_name", record["username"])
        self.role = record.get("role", "viewer")
        self.role_record = record.get("_role") or {}
        self.active = record.get("active", True)

    @property
    def is_active(self):
        return self.active

    @property
    def is_admin(self):
        return bool(self.role_record.get("can_admin"))

    @property
    def can_edit(self):
        return bool(self.role_record.get("can_edit")) or self.is_admin


def create_app():
    from . import location
    app = Flask(__name__)
    configured_secret = (os.environ.get("ELN_SECRET_KEY") or "").strip()
    if configured_secret in ("", "change-me-in-production", "eln-dev-secret-change-me"):
        secret_file = os.path.join(location.config_dir(), "secret_key")
        try:
            with open(secret_file, "r", encoding="utf-8") as f:
                configured_secret = f.read().strip()
        except OSError:
            configured_secret = ""
        if not configured_secret:
            configured_secret = secrets.token_hex(32)
            tmp = secret_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(configured_secret)
            os.chmod(tmp, 0o600)
            os.replace(tmp, secret_file)
    app.config["SECRET_KEY"] = configured_secret
    app.config["DATA_DIR"] = location.get_data_dir()   # honours the assignable pointer
    app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("ELN_MAX_UPLOAD_MB", "512")) * 1024 * 1024

    # If a storage location was assigned but is not currently reachable (e.g. the
    # NAS is not mounted yet), we fall back to the default dir — but make that
    # LOUD, never silent, so nobody unknowingly writes into a stale copy.
    pointer = location.get_pointer_target()
    fallback = pointer if (pointer and pointer != app.config["DATA_DIR"]) else None
    app.config["STORAGE_FALLBACK"] = fallback
    if fallback:
        import sys
        print("WARNING: assigned storage %s is unavailable; running on fallback %s"
              % (fallback, app.config["DATA_DIR"]), file=sys.stderr)

    app.config["MAINTENANCE"] = False

    storage = Storage(app.config["DATA_DIR"])
    storage.ensure_layout()
    app.extensions["storage"] = storage
    app.config["TIMEZONE"] = storage.get_timezone()   # '' = viewer-local

    login_manager = LoginManager(app)
    login_manager.login_view = "auth.login"

    @app.before_request
    def _maintenance_gate():
        # while the data store is being relocated, refuse mutating requests so
        # nothing writes into the source mid-copy; reads and login still work.
        if not app.config.get("MAINTENANCE"):
            return None
        if request.method in ("POST", "PUT", "PATCH", "DELETE") \
                and request.endpoint != "main.set_location":
            return ("Storage is being relocated — please retry in a moment.", 503)
        return None

    @app.before_request
    def _protect_mutations():
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return None
        supplied = request.form.get("_csrf_token") or request.headers.get("X-CSRF-Token")
        expected = session.get("_csrf_token")
        # compare as bytes: compare_digest raises TypeError on non-ASCII str
        if not expected or not supplied or not secrets.compare_digest(
                expected.encode("utf-8"), supplied.encode("utf-8")):
            abort(400, description="Invalid or missing CSRF token.")
        # These routes perform slow camera/ffmpeg I/O (photo capture, recording
        # finalize — up to 45s) before a short atomic update; each acquires the
        # lock itself only around that final read-modify-write.
        if request.endpoint in ("entries.ops_photo", "entries.ops_end",
                                "entries.ops_record_stop"):
            return None
        # The app uses file-backed read-modify-write records. One worker serves
        # multiple threads, so hold the shared re-entrant lock for the complete
        # mutation to prevent one request overwriting another request's changes.
        guard = app.extensions["storage"].mutation_lock()
        guard.__enter__()
        g._mutation_guard = guard

    @app.teardown_request
    def _release_mutation_lock(_error):
        guard = getattr(g, "_mutation_guard", None)
        if guard is not None:
            guard.__exit__(None, None, None)

    @app.after_request
    def _inject_csrf_fields(response):
        """Put CSRF tokens in HTML at render time so forms work without JS."""
        if (response.status_code >= 400 or not response.is_sequence
                or not (response.content_type or "").startswith("text/html")):
            return response
        token = session.get("_csrf_token")
        if not token:
            return response
        html = response.get_data(as_text=True)
        form_re = re.compile(r'(<form\b[^>]*\bmethod=["\']post["\'][^>]*>)', re.I)
        hidden = '<input type="hidden" name="_csrf_token" value="%s">' % escape(token)
        html = form_re.sub(lambda match: match.group(1) + hidden, html)
        response.set_data(html)
        return response

    @login_manager.user_loader
    def load_user(username):
        # resolve via app.extensions so it follows a runtime location change
        rec = app.extensions["storage"].find_user(username)
        if rec and rec.get("active", True):
            rec = dict(rec)
            rec["_role"] = app.extensions["storage"].find_role(rec.get("role")) or {}
            return User(rec)
        return None

    from .auth import bp as auth_bp
    from .main import bp as main_bp
    from .entries import bp as entries_bp
    from .materials import bp as materials_bp
    from .admin import bp as admin_bp
    from .equipment import bp as equipment_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(entries_bp)
    app.register_blueprint(materials_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(equipment_bp)

    # restart sensor loggers for experiments that were mid-run at last shutdown
    from . import ha as ha_module
    ha_module.resume_pollers(app.extensions["storage"])

    # On a graceful shutdown (SIGTERM from `docker stop`/redeploy → gunicorn quits
    # the worker → interpreter exit), flush background threads so an in-progress
    # recording's ffmpeg is signalled to finalise the mp4 moov atom instead of
    # being killed mid-write and left unplayable.
    import atexit
    atexit.register(ha_module.stop_all)

    @app.context_processor
    def inject_globals():
        token = session.get("_csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["_csrf_token"] = token
        roles = app.extensions["storage"].get_roles()
        return {
            "is_admin": current_user.is_authenticated and current_user.is_admin,
            "can_edit": current_user.is_authenticated and current_user.can_edit,
            "status_colors": STATUS_COLORS,
            "role_colors": {r["key"]: r.get("color", "#8a8797") for r in roles},
            "role_labels": {r["key"]: r.get("label", r["key"]) for r in roles},
            "entry_statuses": ENTRY_STATUSES,
            "storage_fallback": app.config.get("STORAGE_FALLBACK"),
            "timezone": app.config.get("TIMEZONE") or "",
            "csrf_token": token,
        }

    # entry ids in free text become links to that entry; the lookbehind keeps
    # ids inside URLs/paths (e.g. /entries/ELN-.../files/...) untouched
    eln_ref = re.compile(r"(?<![/\w-])(ELN-\d{4}-\d{4})(?![\w/-])")

    @app.template_filter("markdown")
    def render_markdown(text):
        html = md.markdown(text or "", extensions=["tables", "fenced_code", "nl2br"])
        html = eln_ref.sub(r'<a class="entry-ref" href="/entries/\1">\1</a>', html)
        tags = set(bleach.sanitizer.ALLOWED_TAGS) | {
            "p", "br", "hr", "pre", "h1", "h2", "h3", "h4", "h5", "h6",
            "table", "thead", "tbody", "tr", "th", "td", "del",
        }
        attrs = dict(bleach.sanitizer.ALLOWED_ATTRIBUTES)
        attrs["a"] = ["href", "title", "class"]
        clean = bleach.clean(html, tags=tags, attributes=attrs,
                             protocols={"http", "https", "mailto"}, strip=True)
        return Markup(clean)

    @app.template_filter("nicedate")
    def nicedate(value):
        # Timestamps are stored in UTC (unambiguous in the files). Emit a <time>
        # element carrying the ISO value; localtime.js rewrites it to the
        # configured lab timezone (or the viewer's local tz if none is set). The
        # text content is a readable fallback in the configured tz for when JS
        # is unavailable.
        s = str(value or "")
        if not s:
            return ""
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?Z?", s)
        if not m:
            return Markup(escape(s))
        y, mo, d, hh, mm, ss = (int(x) if x else 0 for x in m.groups())
        dt = datetime.datetime(y, mo, d, hh, mm, ss, tzinfo=datetime.timezone.utc)
        tzname = app.config.get("TIMEZONE") or ""
        fallback = _readable(dt, "UTC")
        if tzname:
            try:
                from zoneinfo import ZoneInfo
                local = dt.astimezone(ZoneInfo(tzname))
                fallback = _readable(local, local.tzname() or tzname)
            except Exception:
                pass
        return Markup('<time class="lt" datetime="%s">%s</time>'
                      % (escape(s), escape(fallback)))

    return app

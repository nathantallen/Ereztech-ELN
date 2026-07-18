import datetime
import os
import re

import markdown as md
from flask import Flask, request
from flask_login import LoginManager, UserMixin, current_user
from markupsafe import Markup, escape

from .storage import Storage, ENTRY_STATUSES

STATUS_COLORS = {"draft": "#8a8797", "signed": "#F7941E", "witnessed": "#0aa574"}
ROLE_COLORS = {"admin": "#7a00df", "scientist": "#04194e", "viewer": "#8a8797"}
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
        self.active = record.get("active", True)

    @property
    def is_active(self):
        return self.active

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def can_edit(self):
        return self.role in ("admin", "scientist")


def create_app():
    from . import location
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("ELN_SECRET_KEY", "eln-dev-secret-change-me")
    app.config["DATA_DIR"] = location.get_data_dir()   # honours the assignable pointer
    app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("ELN_MAX_UPLOAD_MB", "4096")) * 1024 * 1024

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

    @login_manager.user_loader
    def load_user(username):
        # resolve via app.extensions so it follows a runtime location change
        rec = app.extensions["storage"].find_user(username)
        if rec and rec.get("active", True):
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
        return {
            "is_admin": current_user.is_authenticated and current_user.is_admin,
            "can_edit": current_user.is_authenticated and current_user.can_edit,
            "status_colors": STATUS_COLORS,
            "role_colors": ROLE_COLORS,
            "entry_statuses": ENTRY_STATUSES,
            "storage_fallback": app.config.get("STORAGE_FALLBACK"),
            "timezone": app.config.get("TIMEZONE") or "",
        }

    # entry ids in free text become links to that entry; the lookbehind keeps
    # ids inside URLs/paths (e.g. /entries/ELN-.../files/...) untouched
    eln_ref = re.compile(r"(?<![/\w-])(ELN-\d{4}-\d{4})(?![\w/-])")

    @app.template_filter("markdown")
    def render_markdown(text):
        html = md.markdown(text or "", extensions=["tables", "fenced_code", "nl2br"])
        html = eln_ref.sub(r'<a class="entry-ref" href="/entries/\1">\1</a>', html)
        return Markup(html)

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

from flask import Blueprint, current_app, render_template
from flask_login import current_user, login_required

from .progress import training_status

bp = Blueprint("main", __name__)


def _storage():
    return current_app.extensions["storage"]


def part_progress(playlist, status):
    """[(part, [required videos in part], watched count)] for parts that have
    at least one video in the user's tracks."""
    rows = []
    for part in playlist.get("parts", []):
        vids = [v for v in status["required"] if v.get("part") == part["number"]]
        if vids:
            done = sum(1 for v in vids if v["id"] in status["watched"])
            rows.append((part, vids, done))
    return rows


@bp.route("/")
@login_required
def dashboard():
    storage = _storage()
    rec = storage.find_user(current_user.username) or current_user.record
    status = training_status(storage, rec)
    playlist = storage.playlist()
    quiz = storage.quiz()
    return render_template("dashboard.html", status=status, playlist=playlist, quiz=quiz,
                           parts=part_progress(playlist, status))

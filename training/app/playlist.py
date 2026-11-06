import re

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .progress import assigned_tracks, training_status

bp = Blueprint("playlist", __name__)

_YT = re.compile(r"(?:youtube\.com/watch\?(?:.*&)?v=|youtu\.be/)([A-Za-z0-9_-]{11})")


def _storage():
    return current_app.extensions["storage"]


def youtube_id(url):
    m = _YT.search(url or "")
    return m.group(1) if m else None


def _video_or_404(vid):
    video = next((v for v in _storage().playlist().get("videos", []) if v.get("id") == vid), None)
    if not video:
        abort(404)
    return video


@bp.route("/playlist")
@login_required
def list_videos():
    storage = _storage()
    playlist = storage.playlist()
    rec = storage.find_user(current_user.username) or current_user.record
    status = training_status(storage, rec)
    mine = set(assigned_tracks(rec))
    track = request.args.get("track", "")
    track_keys = {t["key"] for t in playlist.get("tracks", [])}
    if track not in track_keys and track not in ("", "mine"):
        track = ""
    parts = []
    for part in playlist.get("parts", []):
        vids = [v for v in playlist.get("videos", []) if v.get("part") == part["number"]]
        if track == "mine":
            vids = [v for v in vids if mine & set(v.get("tracks") or [])]
        elif track:
            vids = [v for v in vids if track in (v.get("tracks") or [])]
        if vids:
            parts.append((part, vids))
    return render_template("playlist.html", playlist=playlist, parts=parts, track=track,
                           mine=mine, status=status)


@bp.route("/videos/<vid>")
@login_required
def video(vid):
    storage = _storage()
    playlist = storage.playlist()
    video = _video_or_404(vid)
    rec = storage.find_user(current_user.username) or current_user.record
    status = training_status(storage, rec)
    part = next((p for p in playlist.get("parts", []) if p["number"] == video.get("part")), {})
    videos = playlist.get("videos", [])
    idx = videos.index(video)
    prev_v = videos[idx - 1] if idx > 0 else None
    next_v = videos[idx + 1] if idx + 1 < len(videos) else None
    return render_template("video.html", video=video, part=part, status=status,
                           assigned=bool(set(assigned_tracks(rec)) & set(video.get("tracks") or [])),
                           yt=youtube_id(video.get("url")), prev_v=prev_v, next_v=next_v)


@bp.route("/videos/<vid>/watched", methods=["POST"])
@login_required
def mark_watched(vid):
    video = _video_or_404(vid)
    storage = _storage()
    storage.mark_watched(current_user.username, vid, video.get("title", ""))
    storage.audit(current_user.username, current_user.username, "watched", "%s: %s" % (vid, video.get("title", "")))
    flash("Marked as watched: %s" % video.get("title", vid), "success")
    nxt = request.form.get("next", "")
    if nxt == "playlist":
        return redirect(url_for("playlist.list_videos", track=request.form.get("track", "")) + "#v-" + vid)
    return redirect(url_for("playlist.video", vid=vid))

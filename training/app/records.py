import csv
import io

from flask import (Blueprint, Response, abort, current_app, flash, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required
from werkzeug.security import check_password_hash

from .progress import STATUS_LABELS, training_status
from .storage import utcnow

bp = Blueprint("records", __name__)


def _storage():
    return current_app.extensions["storage"]


def _check_password(password):
    rec = _storage().find_user(current_user.username)
    return rec and check_password_hash(rec["password_hash"], password or "")


def _require_verify():
    if not current_user.can_verify:
        abort(403)


def _user_or_404(username):
    rec = _storage().find_user(username)
    if not rec:
        abort(404)
    return rec


def _matrix(include_inactive=False):
    storage = _storage()
    rows = []
    for rec in storage.get_users():
        if not include_inactive and not rec.get("active", True):
            continue
        rows.append((rec, training_status(storage, rec)))
    order = ["overdue", "awaiting-verification", "ready-to-sign", "due-soon",
             "in-progress", "not-started", "current"]
    rows.sort(key=lambda r: (order.index(r[1]["key"]), r[0].get("full_name", "").lower()))
    return rows


@bp.route("/records")
@login_required
def matrix():
    _require_verify()
    show_all = request.args.get("all") == "1"
    rows = _matrix(include_inactive=show_all)
    counts = {}
    for _rec, st in rows:
        counts[st["key"]] = counts.get(st["key"], 0) + 1
    return render_template("records.html", rows=rows, counts=counts, labels=STATUS_LABELS,
                           show_all=show_all, playlist=_storage().playlist())


@bp.route("/records.csv")
@login_required
def matrix_csv():
    _require_verify()
    storage = _storage()
    labels = {t["key"]: t["label"] for t in storage.playlist().get("tracks", [])}
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Username", "Name", "Role", "Tracks", "Videos watched", "Videos required",
                "Best quiz %", "Status", "Last verified", "Verified by", "Due"])
    for rec, st in _matrix(include_inactive=True):
        lv = st["last_verified"] or {}
        w.writerow([rec["username"], rec.get("full_name", ""), rec.get("role", ""),
                    "; ".join(labels.get(t, t) for t in st["tracks"]),
                    len(st["watched_required"]), len(st["required_ids"]),
                    (st["best"] or {}).get("pct", ""), st["label"],
                    (lv.get("verified") or {}).get("at", ""), (lv.get("verified") or {}).get("name", ""),
                    st["due"].strftime("%Y-%m-%d") if st["due"] else ""])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=training-records.csv"})


@bp.route("/records/<username>")
@login_required
def detail(username):
    if username != current_user.username and not current_user.can_verify:
        abort(403)
    storage = _storage()
    rec = _user_or_404(username)
    status = training_status(storage, rec)
    comps = sorted(status["completions"], key=lambda c: c.get("id", ""), reverse=True)
    return render_template("record_detail.html", person=rec, status=status, completions=comps,
                           attempts=list(reversed(storage.attempts(username))),
                           audit=list(reversed(storage.read_audit(username))),
                           playlist=storage.playlist())


@bp.route("/record/sign", methods=["POST"])
@login_required
def sign():
    """The trainee signs their own record for the current cycle."""
    storage = _storage()
    rec = _user_or_404(current_user.username)
    status = training_status(storage, rec)
    back = redirect(url_for("main.dashboard"))
    if status["pending"]:
        flash("Your record is already signed and waiting for a trainer to verify it.", "error")
        return back
    if not status["videos_done"]:
        flash("Mark every assigned video as watched before signing.", "error")
        return back
    if not status["latest_pass"]:
        flash("Pass the quiz before signing.", "error")
        return back
    if not request.form.get("attest"):
        flash("Tick the statement to confirm you watched the videos and understood them.", "error")
        return back
    if not _check_password(request.form.get("password")):
        flash("Password confirmation failed — record not signed.", "error")
        return back
    att = status["latest_pass"]
    titles = {v["id"]: v["title"] for v in status["required"]}
    cid = storage.next_completion_id()
    meta = {
        "id": cid,
        "username": rec["username"],
        "full_name": rec.get("full_name", rec["username"]),
        "status": "signed",
        "tracks": status["tracks"],
        "curriculum": storage.playlist().get("version", ""),
        "quiz": {"attempt": att["id"], "version": att.get("version", ""), "score": att["score"],
                 "total": att["total"], "pct": att["pct"], "at": att["at"]},
        "videos": [{"id": vid, "title": titles.get(vid, vid), "watched_at": status["watched"][vid]}
                   for vid in status["required_ids"]],
        "signed": {"by": current_user.username, "name": current_user.full_name, "at": utcnow(),
                   "statement": "I watched the assigned training videos and understand the content."},
    }
    body = ("Chemical safety training record for %s. %d assigned videos watched; quiz %d/%d (%.1f%%)."
            % (meta["full_name"], len(meta["videos"]), att["score"], att["total"], att["pct"]))
    storage.save_completion(rec["username"], meta, body)
    storage.audit(rec["username"], current_user.username, "signed", cid)
    flash("Training record %s signed. A trainer will verify it." % cid, "success")
    return back


def _completion_or_404(username, cid):
    comp = _storage().get_completion(username, cid)
    if not comp:
        abort(404)
    return comp


@bp.route("/records/<username>/<cid>/verify", methods=["POST"])
@login_required
def verify(username, cid):
    _require_verify()
    storage = _storage()
    comp = _completion_or_404(username, cid)
    back = redirect(url_for("records.detail", username=username))
    if comp.get("status") != "signed":
        flash("Only a signed record waiting for verification can be verified.", "error")
        return back
    if (comp.get("signed") or {}).get("by") == current_user.username or username == current_user.username:
        flash("The verifying trainer must be a different person from the trainee.", "error")
        return back
    if not _check_password(request.form.get("password")):
        flash("Password confirmation failed — record not verified.", "error")
        return back
    comp["status"] = "verified"
    comp["verified"] = {"by": current_user.username, "name": current_user.full_name, "at": utcnow(),
                        "note": request.form.get("note", "").strip()[:500]}
    storage.save_completion(username, comp, comp.get("_body", ""))
    storage.audit(username, current_user.username, "verified", cid)
    flash("%s verified. It is now a permanent training record." % cid, "success")
    return back


@bp.route("/records/<username>/<cid>/return", methods=["POST"])
@login_required
def return_record(username, cid):
    _require_verify()
    storage = _storage()
    comp = _completion_or_404(username, cid)
    back = redirect(url_for("records.detail", username=username))
    reason = request.form.get("reason", "").strip()
    if comp.get("status") != "signed":
        flash("Only a signed record waiting for verification can be returned.", "error")
        return back
    if username == current_user.username:
        flash("You can't return your own record.", "error")
        return back
    if not reason:
        flash("Give a reason so the trainee knows what to fix.", "error")
        return back
    comp["status"] = "returned"
    comp["returned"] = {"by": current_user.username, "name": current_user.full_name, "at": utcnow(),
                        "reason": reason[:500]}
    storage.save_completion(username, comp, comp.get("_body", ""))
    storage.audit(username, current_user.username, "returned", "%s: %s" % (cid, reason[:200]))
    flash("%s returned to the trainee." % cid, "success")
    return back

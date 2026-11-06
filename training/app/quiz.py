from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .progress import LETTERS, score_quiz

bp = Blueprint("quiz", __name__, url_prefix="/quiz")


def _storage():
    return current_app.extensions["storage"]


def _grouped(quiz, playlist):
    titles = {p["number"]: p["title"] for p in playlist.get("parts", [])}
    groups = []
    for q in quiz.get("questions", []):
        if not groups or groups[-1][0] != q["part"]:
            groups.append((q["part"], titles.get(q["part"], ""), []))
        groups[-1][2].append(q)
    return groups


def _public(quiz):
    """The questions as sent to the browser before submission: no answer
    letters, explanations or sources."""
    return {**quiz, "questions": [
        {k: q[k] for k in ("n", "part", "site", "question", "options") if k in q}
        for q in quiz.get("questions", [])]}


@bp.route("", methods=["GET", "POST"])
@login_required
def take():
    storage = _storage()
    quiz = storage.quiz()
    playlist = storage.playlist()
    if request.method == "POST":
        answers, missing = {}, []
        for q in quiz.get("questions", []):
            pick = request.form.get("q%d" % q["n"], "")
            if len(pick) == 1 and pick in LETTERS[:len(q.get("options", []))]:
                answers[q["n"]] = pick
            else:
                missing.append(q["n"])
        if missing:
            flash("%d question(s) unanswered, starting with Q%d. Answer every question before submitting."
                  % (len(missing), missing[0]), "error")
            return render_template("quiz.html", quiz=_public(quiz), groups=_grouped(_public(quiz), playlist),
                                   answers=answers, first_missing=missing[0]), 400
        result = score_quiz(quiz, answers)
        attempt = storage.add_attempt(current_user.username, result)
        storage.audit(current_user.username, current_user.username, "quiz attempt",
                      "%s: %d/%d (%.1f%%) %s" % (attempt["id"], result["score"], result["total"],
                                                result["pct"], "pass" if result["passed"] else "below pass mark"))
        return redirect(url_for("quiz.attempt", username=current_user.username, attempt_id=attempt["id"]))
    return render_template("quiz.html", quiz=_public(quiz), groups=_grouped(_public(quiz), playlist),
                           answers={}, first_missing=None)


@bp.route("/attempts/<username>/<attempt_id>")
@login_required
def attempt(username, attempt_id):
    if username != current_user.username and not current_user.can_verify:
        abort(403)
    storage = _storage()
    att = storage.get_attempt(username, attempt_id)
    if not att:
        abort(404)
    quiz = storage.quiz()
    playlist = storage.playlist()
    same_version = att.get("version") == quiz.get("version")
    picked = att.get("answers", "")
    review = []
    if same_version:
        for i, q in enumerate(quiz.get("questions", [])):
            review.append((q, picked[i] if i < len(picked) else "-"))
    user = storage.find_user(username) or {"username": username, "full_name": username}
    titles = {str(p["number"]): p["title"] for p in playlist.get("parts", [])}
    return render_template("attempt.html", att=att, review=review, same_version=same_version,
                           quiz=quiz, person=user, part_titles=titles)

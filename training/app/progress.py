"""Training status rules — pure functions over the stored records.

A training *cycle* starts at the trainee's last verified sign-off (or at the
beginning of time if they have none). Within the current cycle a trainee must:
  1. mark every video in their assigned tracks as watched,
  2. pass the quiz (score >= pass mark),
  3. sign the record (password-confirmed), and
  4. have a trainer verify it (a different person, password-confirmed).
A verified record stays current for `retrain_months`; then the cycle restarts.
"""
import calendar
import datetime

STATUS_LABELS = {
    "current": "Current",
    "due-soon": "Due soon",
    "overdue": "Overdue",
    "awaiting-verification": "Awaiting verification",
    "ready-to-sign": "Ready to sign",
    "in-progress": "In progress",
    "not-started": "Not started",
}
STATUS_BADGES = {
    "current": "badge-approved",
    "due-soon": "badge-in-progress",
    "overdue": "badge-rejected",
    "awaiting-verification": "badge-pending",
    "ready-to-sign": "badge-in-progress",
    "in-progress": "badge-pending",
    "not-started": "badge-on-hold",
}
LETTERS = "ABCD"


def _utc(s):
    from .storage import parse_utc
    return parse_utc(s)


def add_months(dt, months):
    m = dt.month - 1 + int(months)
    year, month = dt.year + m // 12, m % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def track_map(playlist):
    return {t["key"]: t for t in playlist.get("tracks", [])}


def assigned_tracks(user_rec):
    extra = [t for t in (user_rec.get("tracks") or []) if t != "core"]
    return ["core"] + extra


def required_videos(playlist, tracks):
    wanted = set(tracks)
    return [v for v in playlist.get("videos", []) if wanted & set(v.get("tracks") or [])]


def score_quiz(quiz, answers):
    """answers: {question number (int): letter}. Returns the stored attempt
    body. Unanswered questions count as wrong."""
    questions = quiz.get("questions", [])
    per_part, missed, picked = {}, [], []
    right = 0
    for q in questions:
        mine = answers.get(q["n"], "")
        picked.append(mine or "-")
        part = per_part.setdefault(q["part"], {"right": 0, "total": 0})
        part["total"] += 1
        if mine == q["answer"]:
            right += 1
            part["right"] += 1
        else:
            missed.append(q["n"])
    total = len(questions)
    pct = (right * 100.0 / total) if total else 0.0
    return {
        "version": quiz.get("version", ""),
        "score": right, "total": total, "pct": round(pct, 1),
        "passed": bool(total) and pct >= float(quiz.get("pass_mark", 80)),
        "answers": "".join(picked), "missed": missed,
        "per_part": {str(k): v for k, v in sorted(per_part.items())},
    }


def training_status(storage, user_rec, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    username = user_rec["username"]
    settings = storage.get_settings()
    playlist = storage.playlist()
    tracks = assigned_tracks(user_rec)
    required = required_videos(playlist, tracks)
    required_ids = [v["id"] for v in required]

    comps = storage.completions(username)
    verified = [c for c in comps if c.get("status") == "verified" and (c.get("verified") or {}).get("at")]
    verified.sort(key=lambda c: c["verified"]["at"])
    last_verified = verified[-1] if verified else None
    cycle_start = _utc(last_verified["verified"]["at"]) if last_verified else None
    pending = next((c for c in comps if c.get("status") == "signed"), None)

    watched = {}
    for row in storage.watch_history(username):
        at = _utc(row.get("at"))
        if at is None or (cycle_start and at <= cycle_start):
            continue
        watched[row.get("video")] = row.get("at")
    watched_required = [vid for vid in required_ids if vid in watched]

    attempts = [a for a in storage.attempts(username)
                if not cycle_start or (_utc(a.get("at")) or now) > cycle_start]
    best = max(attempts, key=lambda a: (a.get("pct", 0), a.get("at", ""))) if attempts else None
    passing = [a for a in attempts if a.get("passed")]
    latest_pass = passing[-1] if passing else None

    due = add_months(cycle_start, settings.get("retrain_months", 12)) if cycle_start else None
    videos_done = len(watched_required) == len(required_ids)
    ready = videos_done and latest_pass is not None and pending is None

    if pending:
        key = "awaiting-verification"
    elif due and now < due:
        soon = datetime.timedelta(days=int(settings.get("due_soon_days", 30)))
        key = "due-soon" if due - now <= soon else "current"
    elif ready:
        key = "ready-to-sign"
    elif due:
        key = "overdue"
    elif watched or attempts:
        key = "in-progress"
    else:
        key = "not-started"

    return {
        "key": key, "label": STATUS_LABELS[key], "badge": STATUS_BADGES[key],
        "tracks": tracks, "required": required, "required_ids": required_ids,
        "watched": watched, "watched_required": watched_required,
        "videos_done": videos_done,
        "attempts": attempts, "best": best, "latest_pass": latest_pass,
        "pending": pending, "last_verified": last_verified,
        "completions": comps, "cycle_start": cycle_start, "due": due,
        "ready": ready,
    }

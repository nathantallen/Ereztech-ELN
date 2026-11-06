import datetime
import json
import os
import re
import tempfile
import unittest

import yaml

from app import create_app
from app.progress import add_months, score_quiz, training_status
from app.storage import Storage


TOKEN_RE = re.compile(r'name="csrf-token" content="([^"]+)"')


class TrainingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_env = dict(os.environ)
        os.environ["TRAINING_DATA_DIR"] = os.path.join(self.tmp.name, "data")
        os.environ.pop("TRAINING_SECRET_KEY", None)
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.storage = self.app.extensions["storage"]

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_env)
        self.tmp.cleanup()

    # ---------- helpers ----------

    def client_for(self, username, password):
        c = self.app.test_client()
        token = self._token(c)
        r = c.post("/login", data={"username": username, "password": password, "_csrf_token": token})
        self.assertEqual(r.status_code, 302, "login failed for %s" % username)
        return c

    def _token(self, client):
        html = client.get("/login").get_data(as_text=True)
        return TOKEN_RE.search(html).group(1)

    def post(self, client, url, data=None):
        html = client.get("/").get_data(as_text=True)
        data = dict(data or {})
        data["_csrf_token"] = TOKEN_RE.search(html).group(1)
        return client.post(url, data=data)

    def add_user(self, admin, username, role="trainee", tracks=()):
        r = self.post(admin, "/admin/users/new", {
            "username": username, "full_name": username.title(), "role": role,
            "password": "password123", "tracks": list(tracks)})
        self.assertEqual(r.status_code, 302)
        return self.client_for(username, "password123")

    def correct_answers(self):
        return {"q%d" % q["n"]: q["answer"] for q in self.storage.quiz()["questions"]}

    def watch_all(self, client, username):
        rec = self.storage.find_user(username)
        for vid in training_status(self.storage, rec)["required_ids"]:
            self.assertEqual(self.post(client, "/videos/%s/watched" % vid).status_code, 302)

    # ---------- tests ----------

    def test_seed_and_curriculum(self):
        self.assertEqual(len(self.storage.playlist()["videos"]), 62)
        self.assertEqual(len(self.storage.quiz()["questions"]), 55)
        core = [v for v in self.storage.playlist()["videos"] if "core" in v["tracks"]]
        self.assertEqual(len(core), 35)
        for q in self.storage.quiz()["questions"]:
            self.assertIn(q["answer"], "ABCD"[:len(q["options"])])

    def test_mutations_require_csrf(self):
        c = self.app.test_client()
        r = c.post("/login", data={"username": "admin", "password": "ereztech"})
        self.assertEqual(r.status_code, 400)

    def test_quiz_page_never_sends_answers(self):
        admin = self.client_for("admin", "ereztech")
        html = admin.get("/quiz").get_data(as_text=True)
        questions = self.storage.quiz()["questions"]
        self.assertIn(questions[0]["question"], html)
        for q in questions:
            self.assertNotIn(q["why"], html)
        self.assertNotIn("Source:", html)

    def test_incomplete_quiz_is_rejected(self):
        admin = self.client_for("admin", "ereztech")
        data = self.correct_answers()
        data.pop("q7")
        r = self.post(admin, "/quiz", data)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.storage.attempts("admin"), [])

    def test_quiz_scoring_and_attempt_log(self):
        admin = self.client_for("admin", "ereztech")
        data = self.correct_answers()
        data["q1"] = "D" if data["q1"] != "D" else "C"
        r = self.post(admin, "/quiz", data)
        self.assertEqual(r.status_code, 302)
        [att] = self.storage.attempts("admin")
        self.assertEqual((att["score"], att["total"], att["missed"]), (54, 55, [1]))
        self.assertTrue(att["passed"])
        page = admin.get(r.headers["Location"]).get_data(as_text=True)
        self.assertIn("54 / 55", page)

    def test_pass_mark_is_exact_80_percent(self):
        quiz = {"pass_mark": 80, "questions": [
            {"n": i, "part": 1, "answer": "A", "options": ["a", "b"]} for i in range(1, 6)]}
        four = score_quiz(quiz, {1: "A", 2: "A", 3: "A", 4: "A", 5: "B"})
        three = score_quiz(quiz, {1: "A", 2: "A", 3: "A", 4: "B", 5: "B"})
        self.assertTrue(four["passed"])
        self.assertFalse(three["passed"])

    def test_tracks_drive_required_videos(self):
        admin = self.client_for("admin", "ereztech")
        self.add_user(admin, "pat", tracks=["hf", "waste"])
        st = training_status(self.storage, self.storage.find_user("pat"))
        self.assertEqual(st["tracks"], ["core", "hf", "waste"])
        self.assertEqual(len(st["required_ids"]), 35 + 3 + 4)
        self.assertEqual(st["key"], "not-started")

    def test_full_sign_and_verify_cycle(self):
        admin = self.client_for("admin", "ereztech")
        trainee = self.add_user(admin, "pat")
        # signing before the prerequisites are met is refused
        self.post(trainee, "/record/sign", {"attest": "1", "password": "password123"})
        self.assertEqual(self.storage.completions("pat"), [])

        self.watch_all(trainee, "pat")
        self.post(trainee, "/quiz", self.correct_answers())
        self.assertEqual(training_status(self.storage, self.storage.find_user("pat"))["key"], "ready-to-sign")

        self.post(trainee, "/record/sign", {"attest": "1", "password": "wrong-password"})
        self.assertEqual(self.storage.completions("pat"), [])
        self.post(trainee, "/record/sign", {"attest": "1", "password": "password123"})
        [comp] = self.storage.completions("pat")
        self.assertEqual(comp["status"], "signed")
        self.assertEqual(len(comp["videos"]), 35)

        # a trainee cannot verify; nobody verifies their own record
        r = self.post(trainee, "/records/pat/%s/verify" % comp["id"], {"password": "password123"})
        self.assertEqual(r.status_code, 403)
        self.post(admin, "/records/pat/%s/verify" % comp["id"], {"password": "ereztech"})
        st = training_status(self.storage, self.storage.find_user("pat"))
        self.assertEqual(st["key"], "current")
        self.assertEqual(st["last_verified"]["verified"]["by"], "admin")
        self.assertEqual(st["due"].date(), add_months(st["cycle_start"], 12).date())
        log = [row["action"] for row in self.storage.read_audit("pat")]
        for action in ("watched", "quiz attempt", "signed", "verified"):
            self.assertIn(action, log)

    def test_self_verification_is_refused(self):
        admin = self.client_for("admin", "ereztech")
        self.watch_all(admin, "admin")
        self.post(admin, "/quiz", self.correct_answers())
        self.post(admin, "/record/sign", {"attest": "1", "password": "ereztech"})
        [comp] = self.storage.completions("admin")
        self.post(admin, "/records/admin/%s/verify" % comp["id"], {"password": "ereztech"})
        self.assertEqual(self.storage.completions("admin")[0]["status"], "signed")

    def test_returned_record_can_be_resigned(self):
        admin = self.client_for("admin", "ereztech")
        trainee = self.add_user(admin, "lee")
        self.watch_all(trainee, "lee")
        self.post(trainee, "/quiz", self.correct_answers())
        self.post(trainee, "/record/sign", {"attest": "1", "password": "password123"})
        [comp] = self.storage.completions("lee")
        self.post(admin, "/records/lee/%s/return" % comp["id"], {"reason": "Rewatch Part 10 with a trainer"})
        st = training_status(self.storage, self.storage.find_user("lee"))
        self.assertEqual(st["key"], "ready-to-sign")
        self.post(trainee, "/record/sign", {"attest": "1", "password": "password123"})
        statuses = sorted(c["status"] for c in self.storage.completions("lee"))
        self.assertEqual(statuses, ["returned", "signed"])

    def test_overdue_after_retraining_interval(self):
        admin = self.client_for("admin", "ereztech")
        trainee = self.add_user(admin, "sam")
        self.watch_all(trainee, "sam")
        self.post(trainee, "/quiz", self.correct_answers())
        self.post(trainee, "/record/sign", {"attest": "1", "password": "password123"})
        [comp] = self.storage.completions("sam")
        self.post(admin, "/records/sam/%s/verify" % comp["id"], {"password": "ereztech"})
        later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=400)
        st = training_status(self.storage, self.storage.find_user("sam"), now=later)
        self.assertEqual(st["key"], "overdue")
        self.assertEqual(st["watched_required"], [])   # a new cycle starts from zero

    def test_pages_render_for_each_role(self):
        admin = self.client_for("admin", "ereztech")
        trainee = self.add_user(admin, "kim", tracks=["air-sensitive"])
        for path in ("/", "/playlist", "/playlist?track=mine", "/videos/delta-lel-readings",
                     "/quiz", "/records", "/records.csv", "/records/kim", "/admin/users",
                     "/admin/users/kim/edit", "/admin/settings", "/profile"):
            self.assertEqual(admin.get(path).status_code, 200, path)
        for path in ("/", "/playlist", "/videos/glove-box", "/quiz", "/records/kim", "/profile"):
            self.assertEqual(trainee.get(path).status_code, 200, path)
        for path in ("/records", "/records.csv", "/records/admin", "/admin/users", "/admin/settings"):
            self.assertEqual(trainee.get(path).status_code, 403, path)

    def test_markdown_strips_active_content(self):
        render = self.app.jinja_env.filters["markdown"]
        with self.app.app_context():
            html = str(render('<script>alert(1)</script> [x](javascript:alert(1))'))
        self.assertNotIn("<script", html.lower())
        self.assertNotIn("javascript:", html.lower())

    def test_usernames_cannot_escape_records_folder(self):
        self.assertEqual(Storage.user_folder_name(".."), "unassigned")
        for name in ("../etc", "a/../../b", "/abs"):
            folder = Storage.user_folder_name(name)
            self.assertNotIn(os.sep, folder)
            self.assertNotIn(folder, (".", ".."))

    def test_records_are_human_readable(self):
        admin = self.client_for("admin", "ereztech")
        self.post(admin, "/videos/acs-assessing-risks/watched")
        path = os.path.join(self.storage.records_dir, "admin", "watched.jsonl")
        with open(path, encoding="utf-8") as f:
            row = json.loads(f.readline())
        self.assertEqual(row["video"], "acs-assessing-risks")
        with open(os.path.join(self.storage.curriculum_dir, "playlist.yaml"), encoding="utf-8") as f:
            self.assertEqual(yaml.safe_load(f)["parts"][0]["number"], 1)


if __name__ == "__main__":
    unittest.main()

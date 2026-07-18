import os
import re
import tempfile
import unittest

from flask import render_template

from app import User, create_app
from app.svg import sanitize_svg


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_env = dict(os.environ)
        os.environ["ELN_DATA_DIR"] = os.path.join(self.tmp.name, "data")
        os.environ["ELN_CONFIG_DIR"] = os.path.join(self.tmp.name, "config")
        os.environ.pop("ELN_SECRET_KEY", None)
        # location caches its chosen config directory between app instances.
        from app import location
        location._CONFIG_DIR = None
        self.app = create_app()
        self.app.config.update(TESTING=True)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_env)
        self.tmp.cleanup()

    def test_markdown_removes_active_content_and_unsafe_links(self):
        render = self.app.jinja_env.filters["markdown"]
        with self.app.app_context():
            html = str(render('<script>alert(1)</script> [click](javascript:alert(1))'))
        self.assertNotIn("<script", html.lower())
        self.assertNotIn("javascript:", html.lower())

    def test_svg_removes_scripts_events_and_external_urls(self):
        source = ('<svg xmlns="http://www.w3.org/2000/svg" onload="bad()">'
                  '<script>bad()</script><foreignObject><p>x</p></foreignObject>'
                  '<use href="javascript:bad()"/><use href="#atom"/>'
                  '<path id="atom" d="M0 0"/></svg>')
        clean = sanitize_svg(source)
        self.assertNotIn("script", clean.lower())
        self.assertNotIn("foreignObject", clean)
        self.assertNotIn("onload", clean.lower())
        self.assertNotIn("javascript:", clean.lower())
        self.assertIn("#atom", clean)

    def test_post_requires_csrf_token(self):
        client = self.app.test_client()
        login_page = client.get("/login")
        self.assertIn(b'name="_csrf_token"', login_page.data)
        token = re.search(rb'name="_csrf_token" value="([^"]+)"', login_page.data).group(1)
        protected = client.post("/login", data={"username": "x", "password": "x",
                                                "_csrf_token": token.decode()})
        self.assertEqual(protected.status_code, 200)
        response = client.post("/login", data={"username": "x", "password": "x"})
        self.assertEqual(response.status_code, 400)

    def test_login_attempt_cache_is_bounded(self):
        from app import auth
        with auth._ATTEMPTS_LOCK:
            auth._ATTEMPTS.clear()
            auth._LAST_PRUNE = 0.0
        for i in range(auth._MAX_TRACKED_KEYS + 25):
            auth._failed(("127.0.0.1", "user-%d" % i))
        self.assertLessEqual(len(auth._ATTEMPTS), auth._MAX_TRACKED_KEYS)
        with auth._ATTEMPTS_LOCK:
            auth._ATTEMPTS.clear()

    def test_generated_secret_is_persistent(self):
        first = self.app.config["SECRET_KEY"]
        from app import location
        location._CONFIG_DIR = None
        second = create_app().config["SECRET_KEY"]
        self.assertEqual(first, second)
        self.assertGreaterEqual(len(first), 64)

    def test_roles_are_persistent_and_permission_driven(self):
        storage = self.app.extensions["storage"]
        roles = storage.get_roles()
        self.assertTrue(storage.role_can_admin("admin"))
        roles.append({"key": "operator", "label": "Operator", "color": "#123456",
                      "can_admin": False, "can_edit": True})
        storage.save_roles(roles)
        saved = storage.find_role("operator")
        user = User({"username": "op", "role": "operator", "_role": saved})
        self.assertTrue(user.can_edit)
        self.assertFalse(user.is_admin)

    def test_running_operations_bar_includes_assigned_camera(self):
        meta = {"id": "ELN-2026-0001", "equipment": {"camera": "ipcam.hood-one"}}
        ops = {"started_at": "2026-07-18T12:00:00Z"}
        with self.app.test_request_context("/entries/ELN-2026-0001"):
            html = render_template("_operations.html", meta=meta, ops=ops,
                                   ha_configured=True, recording={"active": False})
        self.assertIn('id="ops-camera"', html)
        self.assertIn('/equipment/snapshot/ipcam.hood-one', html)
        self.assertNotIn('/equipment/stream/ipcam.hood-one', html)
        self.assertIn('id="ops-camera-toggle"', html)


if __name__ == "__main__":
    unittest.main()

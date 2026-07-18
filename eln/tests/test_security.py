import os
import tempfile
import unittest

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
        response = client.post("/login", data={"username": "x", "password": "x"})
        self.assertEqual(response.status_code, 400)

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


if __name__ == "__main__":
    unittest.main()

import os
import re
import tempfile
import unittest

from flask import render_template
from werkzeug.security import check_password_hash

from app import User, create_app
from app.chem import formula_and_mw
from app.inventory import batch_quantity, set_batch_quantity, to_base
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

    def test_v3000_formula_supports_organometallic_structures(self):
        molfile = """Trimethylgallium
  ELN

  0  0  0  0  0  0  0  0  0  0999 V3000
M  V30 BEGIN CTAB
M  V30 COUNTS 4 3 0 0 0
M  V30 BEGIN ATOM
M  V30 1 Ga 0 0 0 0
M  V30 2 C 1 0 0 0
M  V30 3 C -1 0 0 0
M  V30 4 C 0 1 0 0
M  V30 END ATOM
M  V30 BEGIN BOND
M  V30 1 1 1 2
M  V30 2 1 1 3
M  V30 3 1 1 4
M  V30 END BOND
M  V30 END CTAB
M  END
"""
        formula, mw = formula_and_mw(molfile)
        self.assertEqual(formula, "C3H9Ga")
        self.assertAlmostEqual(mw, 114.83, places=2)

    def test_v3000_coordinate_bond_does_not_consume_ligand_valence(self):
        molfile = """Amminocopper
  ELN

  0  0  0  0  0  0  0  0  0  0999 V3000
M  V30 BEGIN CTAB
M  V30 COUNTS 5 4 0 0 0
M  V30 BEGIN ATOM
M  V30 1 N 0 0 0 0
M  V30 2 Cu 2 0 0 0
M  V30 3 H -1 0 0 0
M  V30 4 H 0 1 0 0
M  V30 5 H 0 -1 0 0
M  V30 END ATOM
M  V30 BEGIN BOND
M  V30 1 1 1 3
M  V30 2 1 1 4
M  V30 3 1 1 5
M  V30 4 9 1 2
M  V30 END BOND
M  V30 END CTAB
M  END
"""
        formula, _ = formula_and_mw(molfile)
        self.assertEqual(formula, "CuH3N")

    def test_inventory_unit_conversion_and_opening_ledger(self):
        base, unit, family = to_base(2.5, "kg")
        self.assertEqual((base, unit, family), (2500.0, "g", "mass"))
        base, unit, family = to_base(750, "µL")
        self.assertEqual((base, unit, family), (0.75, "mL", "volume"))
        storage = self.app.extensions["storage"]
        batch, _ = storage.get_batch("trimethylgallium", "tmg-2606-a")
        self.assertEqual(batch_quantity(batch)["base_value"], 250.0)
        ledger = storage.inventory_transactions(
            material="trimethylgallium", lot_slug="tmg-2606-a")
        self.assertEqual(ledger[0]["action"], "opening balance")
        self.assertEqual(ledger[0]["balance_display"], "250 g")

    def test_manual_batch_adjustment_requires_reason_and_is_audited(self):
        storage = self.app.extensions["storage"]
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = "admin"
            sess["_fresh"] = True
            sess["_csrf_token"] = "batch-adjustment-token"
        data = {
            "_csrf_token": "batch-adjustment-token", "lot": "TMG-2606-A",
            "supplier": "Ereztech (in-house)", "received": "2026-06-02",
            "expiry": "", "purity": "99.9999% (6N)",
            "quantity_value": "0.2", "quantity_unit": "kg",
            "container": "SS-316 bubbler #14", "location": "Gas cabinet 2, slot A",
            "status": "Open", "notes": "",
        }
        response = client.post(
            "/materials/trimethylgallium/batches/tmg-2606-a/edit", data=data)
        self.assertEqual(response.status_code, 302)
        batch, _ = storage.get_batch("trimethylgallium", "tmg-2606-a")
        self.assertEqual(batch_quantity(batch)["base_value"], 250.0)
        data["adjustment_reason"] = "Transferred 50 g to production."
        response = client.post(
            "/materials/trimethylgallium/batches/tmg-2606-a/edit", data=data)
        self.assertEqual(response.status_code, 302)
        batch, _ = storage.get_batch("trimethylgallium", "tmg-2606-a")
        self.assertEqual(batch_quantity(batch)["base_value"], 200.0)
        latest = storage.inventory_transactions(
            material="trimethylgallium", lot_slug="tmg-2606-a")[0]
        self.assertEqual(latest["action"], "manual adjustment")
        self.assertEqual(latest["delta_display"], "−0.05 kg")
        self.assertEqual(latest["detail"], "Transferred 50 g to production.")

    def test_multi_batch_deduction_and_required_reconciliation(self):
        storage = self.app.extensions["storage"]
        second = {
            "material": "trimethylgallium", "lot_slug": "tmg-2607-b",
            "lot": "TMG-2607-B", "status": "Open", "created": "2026-07-01T00:00:00Z",
            "created_by": "admin",
        }
        set_batch_quantity(second, 20, "g", "g")
        storage.save_batch("trimethylgallium", "tmg-2607-b", second, "")
        storage.record_inventory_transaction({
            "material": "trimethylgallium", "lot_slug": "tmg-2607-b",
            "lot": "TMG-2607-B", "by": "admin", "action": "opening balance",
            "delta_base": 20.0, "base_unit": "g", "delta_display": "+20 g",
            "balance_after_base": 20.0, "balance_display": "20 g",
        })
        meta, body = storage.get_entry("ELN-2026-0001")
        meta["reaction"] = {"components": [{
            "key": 1, "role": "reactant", "name": "Trimethylgallium",
            "mass_g": 35.0,
        }], "next_key": 2}
        meta.pop("operations", None)
        meta.pop("inventory_allocations", None)
        storage.save_entry("ELN-2026-0001", meta, body)

        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = "admin"
            sess["_fresh"] = True
            sess["_csrf_token"] = "inventory-test-token"
        csrf = {"_csrf_token": "inventory-test-token"}
        response = client.post("/entries/ELN-2026-0001/inventory/allocations", data={
            **csrf,
            "allocation_id": ["", ""],
            "allocation_component": ["1", "1"],
            "allocation_batch": ["trimethylgallium|tmg-2606-a",
                                   "trimethylgallium|tmg-2607-b"],
            "allocation_quantity": ["30", "5000"],
            "allocation_unit": ["g", "mg"],
        })
        self.assertEqual(response.status_code, 302)
        meta, _ = storage.get_entry("ELN-2026-0001")
        self.assertEqual(len(meta["inventory_allocations"]), 2)

        response = client.post("/entries/ELN-2026-0001/ops/start", data=csrf)
        self.assertEqual(response.status_code, 302)
        first, _ = storage.get_batch("trimethylgallium", "tmg-2606-a")
        second, _ = storage.get_batch("trimethylgallium", "tmg-2607-b")
        self.assertAlmostEqual(batch_quantity(first)["base_value"], 220.0)
        self.assertAlmostEqual(batch_quantity(second)["base_value"], 15.0)
        meta, _ = storage.get_entry("ELN-2026-0001")
        self.assertTrue(all(a["status"] == "deducted"
                            for a in meta["inventory_allocations"]))
        self.assertEqual(sum(1 for a in storage.read_audit("ELN-2026-0001")
                             if a["action"] == "inventory deducted"), 2)

        response = client.post("/entries/ELN-2026-0001/ops/end", data=csrf)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/ops/reconcile", response.headers["Location"])
        self.assertEqual(client.get(response.headers["Location"]).status_code, 200)

        allocations = {a["lot_slug"]: a for a in meta["inventory_allocations"]}
        reconcile = dict(csrf)
        first_id = allocations["tmg-2606-a"]["id"]
        reconcile.update({
            "unit_" + first_id: "g", "consumed_" + first_id: "25",
            "recovered_" + first_id: "2", "returned_" + first_id: "3",
        })
        second_id = allocations["tmg-2607-b"]["id"]
        reconcile.update({
            "unit_" + second_id: "mg", "consumed_" + second_id: "4000",
            "recovered_" + second_id: "500", "returned_" + second_id: "500",
        })
        response = client.post("/entries/ELN-2026-0001/ops/reconcile", data=reconcile)
        self.assertEqual(response.status_code, 302)
        first, _ = storage.get_batch("trimethylgallium", "tmg-2606-a")
        second, _ = storage.get_batch("trimethylgallium", "tmg-2607-b")
        self.assertAlmostEqual(batch_quantity(first)["base_value"], 223.0)
        self.assertAlmostEqual(batch_quantity(second)["base_value"], 15.5)
        meta, _ = storage.get_entry("ELN-2026-0001")
        self.assertTrue(meta["operations"].get("ended_at"))
        self.assertTrue(all(a["status"] == "reconciled"
                            for a in meta["inventory_allocations"]))
        tx = storage.inventory_transactions(eid="ELN-2026-0001")
        self.assertEqual(sum(1 for row in tx if row["action"] == "experiment deduction"), 2)
        self.assertEqual(sum(1 for row in tx if row["action"] == "experiment reconciliation"), 2)
        self.assertEqual(sum(1 for a in storage.read_audit("ELN-2026-0001")
                             if a["action"] == "inventory reconciled"), 2)

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

    def test_notebook_lot_number_create_search_edit_and_repeat(self):
        storage = self.app.extensions["storage"]
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = "admin"
            sess["_fresh"] = True
            sess["_csrf_token"] = "lot-number-test-token"
        csrf = {"_csrf_token": "lot-number-test-token"}

        response = client.post("/entries/new", data={
            **csrf,
            "title": "Lot-number test experiment",
            "project": "TMGa scale-up",
            "lot_number": "TMG-2607-B",
            "experiment_date": "2026-07-20",
            "technique": "N2 glovebox",
            "tags": "lot-test",
            "section_0": "Verify the notebook lot number.",
            "section_1": "Run the reaction.",
        })
        self.assertEqual(response.status_code, 302)
        eid = response.headers["Location"].rstrip("/").split("/")[-1]
        meta, _ = storage.get_entry(eid)
        self.assertEqual(meta["lot_number"], "TMG-2607-B")

        search = client.get("/entries/?q=TMG-2607-B&author=all")
        self.assertEqual(search.status_code, 200)
        self.assertIn(b"TMG-2607-B", search.data)

        response = client.post("/entries/%s/edit" % eid, data={
            **csrf,
            "title": meta["title"],
            "project": meta["project"],
            "lot_number": "TMG-2607-C",
            "experiment_date": meta["experiment_date"],
            "technique": meta["technique"],
            "tags": "lot-test",
            "section_0": "Verify the notebook lot number.",
            "section_1": "Run the reaction.",
        })
        self.assertEqual(response.status_code, 302)
        meta, _ = storage.get_entry(eid)
        self.assertEqual(meta["lot_number"], "TMG-2607-C")

        response = client.post("/entries/%s/repeat" % eid, data=csrf)
        self.assertEqual(response.status_code, 302)
        repeated = response.headers["Location"].rstrip("/").split("/")[-1]
        repeated_meta, _ = storage.get_entry(repeated)
        self.assertEqual(repeated_meta["repeat_of"], eid)
        self.assertEqual(repeated_meta["lot_number"], "")

    def test_reaction_component_purity_is_saved_and_rendered(self):
        storage = self.app.extensions["storage"]
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = "admin"
            sess["_fresh"] = True
            sess["_csrf_token"] = "purity-test-token"
        response = client.post("/entries/ELN-2026-0001/reaction", data={
            "_csrf_token": "purity-test-token",
            "scale_amount": "10", "scale_unit": "g",
            "comp_key": "1", "comp_role": "reactant", "comp_name": "Test reagent",
            "comp_cas": "", "comp_formula": "C2H6", "comp_mw": "30.07",
            "comp_mw_auto": "0", "comp_density": "0.8", "comp_purity": "80",
            "comp_state": "liquid", "comp_conc": "0.5", "comp_stock_conc": "",
            "comp_solubility": "insoluble", "comp_equiv": "1",
            "comp_limiting": "0", "comp_mmol": "266.046", "comp_mass_g": "10",
            "comp_volume_ml": "12.5", "comp_volume_unit": "mL",
        })
        self.assertEqual(response.status_code, 302)
        meta, _ = storage.get_entry("ELN-2026-0001")
        self.assertEqual(meta["reaction"]["components"][0]["purity"], 80.0)
        self.assertEqual(meta["reaction"]["components"][0]["conc"], 0.5)
        self.assertEqual(meta["reaction"]["components"][0]["solubility"], "insoluble")
        page = client.get("/entries/ELN-2026-0001")
        self.assertIn(b'class="f-purity" value="80.0"', page.data)
        self.assertIn(b'Insoluble in solvent', page.data)

    def test_user_notebook_identity_and_sequential_pages(self):
        storage = self.app.extensions["storage"]
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = "admin"
            sess["_fresh"] = True
            sess["_csrf_token"] = "page-number-test-token"
        csrf = {"_csrf_token": "page-number-test-token"}

        response = client.post("/profile", data={
            **csrf, "chemist_number": "C-1042", "notebook_number": "NB-7",
        })
        self.assertEqual(response.status_code, 302)

        def create(title):
            response = client.post("/entries/new", data={
                **csrf, "title": title, "experiment_date": "2026-07-20",
                "section_0": "Page allocation test.", "section_1": "Test.",
            })
            self.assertEqual(response.status_code, 302)
            eid = response.headers["Location"].rstrip("/").split("/")[-1]
            return storage.get_entry(eid)[0]

        first = create("First numbered experiment")
        second = create("Second numbered experiment")
        self.assertEqual((first["chemist_number"], first["notebook_number"],
                          first["page_number"]), ("C-1042", "NB-7", 1))
        self.assertEqual(second["page_number"], 2)

        client.post("/profile", data={
            **csrf, "chemist_number": "C-1042", "notebook_number": "NB-8",
        })
        other_book = create("New notebook experiment")
        self.assertEqual((other_book["notebook_number"], other_book["page_number"]),
                         ("NB-8", 1))

        client.post("/profile", data={
            **csrf, "chemist_number": "C-1042", "notebook_number": "NB-7",
        })
        resumed = create("Resumed notebook experiment")
        self.assertEqual(resumed["page_number"], 3)
        self.assertEqual(storage.get_entry(first["id"])[0]["notebook_number"], "NB-7")

        page = client.get("/entries/%s" % resumed["id"])
        self.assertIn(b"C-1042 / NB-7 / 3", page.data)
        self.assertIn(("Internal reference %s" % resumed["id"]).encode(), page.data)
        self.assertNotIn(("<h1><span class=\"mono\">%s</span>" % resumed["id"]).encode(),
                         page.data)

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

    def test_fresh_install_uses_documented_admin_password(self):
        admin = self.app.extensions["storage"].find_user("admin")
        self.assertIsNotNone(admin)
        self.assertTrue(check_password_hash(admin["password_hash"], "ereztech"))

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
        components = [
            {"role": "reactant", "name": "Starting material", "mass_g": 1.25},
            {"role": "solvent", "name": "THF", "volume_ml": 20.0,
             "volume_unit": "L"},
        ]
        with self.app.test_request_context("/entries/ELN-2026-0001"):
            html = render_template("_operations.html", meta=meta, ops=ops,
                                   components=components, ha_configured=True,
                                   recording={"active": False})
        self.assertIn('id="ops-camera"', html)
        self.assertIn('/equipment/snapshot/ipcam.hood-one', html)
        self.assertNotIn('/equipment/stream/ipcam.hood-one', html)
        self.assertIn('id="ops-camera-toggle"', html)
        self.assertIn('id="ops-reactant-weights"', html)
        self.assertIn("Starting material: 1.250 g", html)
        self.assertIn('id="ops-solvent-volumes"', html)
        self.assertIn("0.020 L", html)

    def test_notebook_page_fields_are_editable_and_sections_are_ordered(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = "admin"
            sess["_fresh"] = True
        response = client.get("/entries/ELN-2026-0001")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('<details class="card equipment-panel" id="equipment" open>', html)
        self.assertIn('<summary class="equipment-panel-summary">', html)
        self.assertIn('name="title"', html)
        self.assertIn('name="project"', html)
        self.assertIn('name="experiment_date"', html)
        self.assertIn('name="lot_number"', html)
        self.assertIn('name="objective"', html)
        self.assertIn('class="objective-input" rows="1"', html)
        self.assertIn('name="procedure"', html)
        ordered = [
            'name="title"', 'name="project"', 'name="experiment_date"',
            'name="lot_number"', 'name="objective"', 'id="equipment"',
            'id="reaction-form"', 'id="inventory-allocation"',
            'id="procedure"', 'id="operations"', 'Attached files',
            '<h2>References</h2>', '<h2>Sign-off</h2>', '<h2>Audit trail</h2>',
        ]
        positions = [html.index(marker) for marker in ordered]
        self.assertEqual(positions, sorted(positions))

    def test_new_experiment_button_creates_a_notebook_page(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = "admin"
            sess["_fresh"] = True
            sess["_csrf_token"] = "new-page-test-token"
        response = client.get("/entries/")
        html = response.get_data(as_text=True)
        self.assertIn('name="quick_create" value="1"', html)
        response = client.post("/entries/new", data={
            "quick_create": "1", "_csrf_token": "new-page-test-token"},
                               follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertRegex(response.headers["Location"], r"/entries/ELN-\d{4}-\d{4}$")

    def test_structure_editor_has_touch_recovery_and_rich_format_fields(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = "admin"
            sess["_fresh"] = True
        response = client.get("/entries/ELN-2026-0001/structures/new")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="touch-mode-btn"', response.data)
        self.assertIn(b'id="sketcher-fullscreen-btn"', response.data)
        self.assertIn(b'id="sketcher-recovery"', response.data)
        self.assertIn(b'name="molfile_v2000"', response.data)
        self.assertIn(b'name="ket"', response.data)
        self.assertNotIn(b"Organometallic templates", response.data)
        self.assertNotIn(b"structure-template-btn", response.data)
        self.assertNotIn(b"save-company-template", response.data)
        self.assertNotIn(b"Cyclopentadienyl", response.data)
        self.assertNotIn(b"Acetylacetonate", response.data)
        self.assertNotIn(b"Amidinate", response.data)
        self.assertNotIn(b"Carbonyl ligand", response.data)

    def test_structure_template_endpoint_is_removed(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = "admin"
            sess["_fresh"] = True
            sess["_csrf_token"] = "template-test-token"
        response = client.post(
            "/entries/structure-templates",
            headers={"X-CSRF-Token": "template-test-token"},
        )
        self.assertIn(response.status_code, (404, 405))

    def test_top_search_finds_entry_metadata_across_all_books(self):
        storage = self.app.extensions["storage"]
        meta, body = storage.get_entry("ELN-2026-0001")
        meta = dict(meta)
        meta.pop("id", None)
        meta["title"] = "Metadata search target"
        meta["reaction"] = {"components": [{"name": "Test compound", "cas": "867-53-09"}]}
        storage.create_entry(meta, body)
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = "admin"
            sess["_fresh"] = True
        response = client.get("/entries/?author=all&q=867-53-09")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Metadata search target", response.data)
        self.assertIn(b'id="top-search-input"', response.data)


if __name__ == "__main__":
    unittest.main()

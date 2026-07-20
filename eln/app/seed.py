"""First-run seed: default admin login plus a few example records so a fresh
notebook demonstrates the format. Runs only when users.json does not exist."""
from werkzeug.security import generate_password_hash

from .storage import utcnow

TMGA_MOL = """Trimethylgallium
  ELN

  4  3  0  0  0  0  0  0  0  0999 V2000
    0.0000    0.0000    0.0000 Ga  0  0  0  0  0  0  0  0  0  0  0  0
    1.2990    0.7500    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
   -1.2990    0.7500    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    0.0000   -1.5000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
  1  2  1  0  0  0  0
  1  3  1  0  0  0  0
  1  4  1  0  0  0  0
M  END
"""


def seed_initial_data(storage):
    initial_password = "ereztech"
    storage.save_users([{
        "username": "admin",
        "full_name": "Administrator",
        "chemist_number": "ADMIN",
        "notebook_number": "1",
        "password_hash": generate_password_hash(initial_password),
        "role": "admin",
        "active": True,
    }])
    print("\n*** Ereztech ELN default administrator credentials ***")
    print("Username: admin")
    print("Password: %s" % initial_password)
    print("Change this password under Users after signing in.\n", flush=True)

    materials = [
        dict(slug="trimethylgallium", name="Trimethylgallium (TMGa)", cas="1445-79-0",
             formula="Ga(CH3)3", supplier="Ereztech", air_sensitive=True,
             hazards="Pyrophoric; reacts violently with water",
             storage="Stainless bubbler, N2 glovebox / gas cabinet",
             notes="MOCVD gallium precursor. Handle only under inert atmosphere."),
        dict(slug="trimethylaluminum", name="Trimethylaluminum (TMA)", cas="75-24-1",
             formula="Al2(CH3)6", supplier="Ereztech", air_sensitive=True,
             hazards="Pyrophoric; water-reactive",
             storage="Stainless bubbler, gas cabinet",
             notes="ALD aluminum precursor for Al2O3 deposition."),
        dict(slug="diethylzinc", name="Diethylzinc (DEZ)", cas="557-20-0",
             formula="Zn(C2H5)2", supplier="Ereztech", air_sensitive=True,
             hazards="Pyrophoric; water-reactive",
             storage="Stainless bubbler, N2 glovebox",
             notes="ZnO ALD/MOCVD precursor."),
    ]
    batches = {
        "trimethylgallium": dict(lot="TMG-2606-A", supplier="Ereztech (in-house)",
                                 received="2026-06-02", purity="99.9999% (6N)",
                                 quantity="250 g", container="SS-316 bubbler #14",
                                 location="Gas cabinet 2, slot A", status="Open",
                                 notes="Adduct-purified lot. ICP-MS metals < 50 ppb each."),
        "trimethylaluminum": dict(lot="TMA-2605-C", supplier="Ereztech (in-house)",
                                  received="2026-05-18", purity="99.999% (5N)",
                                  quantity="500 g", container="SS-316 bubbler #7",
                                  location="Gas cabinet 1, slot C", status="In Stock",
                                  notes=""),
        "diethylzinc": dict(lot="DEZ-2604-B", supplier="Ereztech (in-house)",
                            received="2026-04-27", purity="99.9999% (6N)",
                            quantity="100 g", container="SS-316 ampoule",
                            location="N2 glovebox 3", status="Open",
                            notes=""),
    }
    for m in materials:
        slug = m.pop("slug")
        notes = m.pop("notes")
        m["slug"] = slug
        m["created"] = utcnow()
        m["created_by"] = "admin"
        storage.save_material(slug, m, notes)
        b = batches[slug]
        b_notes = b.pop("notes")
        b["material"] = slug
        b["lot_slug"] = b["lot"].lower()
        b["created"] = utcnow()
        b["created_by"] = "admin"
        storage.save_batch(slug, b["lot_slug"], b, b_notes)

    meta = {
        "title": "TMGa adduct purification — distillation trial 12",
        "author": "admin",
        "project": "TMGa 6N purity",
        "experiment_date": "2026-07-10",
        "technique": "N2 glovebox",
        "tags": ["TMGa", "purification", "distillation"],
        "status": "draft",
        "created": utcnow(),
        "materials": [
            {"material": "trimethylgallium", "lot": "TMG-2606-A", "amount": "45.0 g"},
        ],
        "structures": [
            {"file": "structures/struct-01.mol", "svg": "", "smiles": "C[Ga](C)C",
             "caption": "Trimethylgallium"},
        ],
        "attachments": [],
    }
    body = "\n".join([
        "## Objective\n",
        "Evaluate the diphos adduct route for removing residual oxygenated impurities "
        "from crude TMGa lot TMG-2606-A, targeting 6N purity by ICP-MS.\n",
        "## Procedure\n",
        "1. In the N2 glovebox, charge 45.0 g crude TMGa into the 250 mL distillation flask.\n"
        "2. Add 1.05 equiv diphos ligand, stir 30 min at ambient temperature.\n"
        "3. Transfer assembly to Schlenk line; distill at 55 °C / 12 torr through the "
        "10 cm Vigreux column.\n"
        "4. Collect heart cut into the tared SS ampoule; log head temperature every 5 min.\n",
        "## Results & Conclusions\n",
        "Heart cut mass 38.2 g (85% recovery). Head temperature stabilized at 55.8 °C "
        "after 22 min; first 2 mL forecut discarded. Sample submitted for ICP-MS; "
        "results pending.\n",
    ])
    eid = storage.create_entry(meta, body)
    import os
    sdir = os.path.join(storage.entry_dir(eid), "structures")
    os.makedirs(sdir, exist_ok=True)
    with open(os.path.join(sdir, "struct-01.mol"), "w", encoding="utf-8") as f:
        f.write(TMGA_MOL)
    storage.audit(eid, "admin", "created", "seeded example entry")

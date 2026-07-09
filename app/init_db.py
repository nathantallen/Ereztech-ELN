"""Create tables and seed initial data. Run once at container start; safe to re-run."""
import sys
import time
from datetime import date, timedelta

from sqlalchemy.exc import OperationalError

from . import create_app
from .extensions import db
from .models import (
    Deliverable,
    DocumentRoot,
    ProductionRun,
    RDProject,
    Reactor,
    ReactorAttribute,
    Role,
    RunStatus,
    StageLink,
    User,
)


def wait_for_db(app, attempts=30):
    for i in range(attempts):
        try:
            with app.app_context():
                db.session.execute(db.text("SELECT 1"))
            return
        except OperationalError:
            print(f"Waiting for database... ({i + 1}/{attempts})")
            time.sleep(2)
    print("Database never became available.", file=sys.stderr)
    sys.exit(1)


def seed():
    if User.query.count():
        return

    users = {}
    for username, full_name, role in [
        ("admin", "Site Administrator", "Admin"),
        ("pmanager", "Pat Miller", "Production Manager"),
        ("qcmanager", "Quinn Chen", "QC Manager"),
        ("rdirector", "Riya Desai", "R&D Director"),
        ("researcher1", "Sam Ortiz", "Researcher"),
    ]:
        u = User(username=username, full_name=full_name, role=role)
        u.set_password("ereztech")
        db.session.add(u)
        users[username] = u

    reactors = {}
    for name, desc, color, attrs in [
        ("R-101", "Glass-lined batch reactor", "#7a00df",
         [("Capacity", "500 L"), ("Material", "Glass-lined steel"), ("Max Temp", "200 °C")]),
        ("R-102", "Hastelloy C-276 reactor with distillation head", "#F7941E",
         [("Capacity", "1000 L"), ("Material", "Hastelloy C-276"), ("Max Pressure", "6 bar")]),
        ("R-201", "Stainless kilo-lab reactor", "#0693e3",
         [("Capacity", "100 L"), ("Material", "316L SS"), ("Jacket", "-20 to 180 °C")]),
    ]:
        r = Reactor(name=name, description=desc, color=color)
        for aname, aval in attrs:
            r.attributes.append(ReactorAttribute(name=aname, value=aval))
        db.session.add(r)
        reactors[name] = r
    db.session.flush()

    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sample_runs = [
        ("TMA — Trimethylaluminum", "B-2607-01", "R-101", monday - timedelta(days=7), monday - timedelta(days=3), "Complete"),
        ("TDMAT — Tetrakis(dimethylamido)titanium", "B-2607-02", "R-102", monday - timedelta(days=1), monday + timedelta(days=4), "In Progress"),
        ("TEB — Triethylborane", "B-2607-03", "R-201", monday + timedelta(days=2), monday + timedelta(days=5), "Planned"),
        ("DEZ — Diethylzinc", "B-2607-04", "R-101", monday + timedelta(days=7), monday + timedelta(days=12), "Planned"),
    ]
    for product, batch, reactor_name, start, end, status in sample_runs:
        run = ProductionRun(
            product=product,
            batch_number=batch,
            reactor_id=reactors[reactor_name].id,
            start_date=start,
            end_date=end,
            status=status,
        )
        run.ensure_stages()
        db.session.add(run)
    db.session.flush()

    first_run = ProductionRun.query.order_by(ProductionRun.id).first()
    for stage in first_run.stages[:2]:
        stage.links.append(
            StageLink(
                label="Example: SharePoint folder",
                url="https://ereztech.sharepoint.com/sites/Production/Shared%20Documents",
            )
        )

    project = RDProject(
        name="Novel Zr precursor for ALD",
        customer="Acme Semiconductor",
        researcher_id=users["researcher1"].id,
        status="Active",
        description="Route scouting and scale-up of a zirconium amide precursor.",
        start_date=today - timedelta(days=30),
        due_date=today + timedelta(days=60),
        folder_url="https://ereztech.sharepoint.com/sites/RD/Projects/Zr-ALD",
        final_procedure_url="",
        final_qc_url="",
    )
    project.deliverables.append(
        Deliverable(name="Feasibility report", status="Delivered",
                    due_date=today - timedelta(days=10),
                    link_url="https://ereztech.sharepoint.com/sites/RD/Projects/Zr-ALD/feasibility.docx")
    )
    project.deliverables.append(
        Deliverable(name="100 g sample lot", status="In Progress", due_date=today + timedelta(days=20))
    )
    db.session.add(project)

    db.session.commit()
    print("Seeded initial users, reactors, runs, and a sample R&D project.")


def migrate():
    """Additive schema upgrades create_all can't do. Safe to re-run."""
    with db.engine.begin() as conn:
        conn.execute(
            db.text(
                "ALTER TABLE production_runs ADD COLUMN IF NOT EXISTS "
                "intermediate_for_id INTEGER REFERENCES production_runs(id) ON DELETE SET NULL"
            )
        )


def ensure_roles_and_statuses():
    """Runs on every start so upgraded databases pick up the new tables."""
    if not Role.query.count():
        for i, (name, color, flags) in enumerate(
            [
                ("Admin", "#0F0037", ("manage_users", "edit_production", "edit_rd_all")),
                ("Production Manager", "#F7941E", ("edit_production",)),
                ("QC Manager", "#0693e3", ()),
                ("R&D Director", "#7a00df", ("edit_rd_all",)),
                ("Researcher", "#BD6FD5", ("edit_rd_own",)),
                ("Operator", "#8a8797", ()),
            ]
        ):
            role = Role(name=name, color=color, position=i)
            for flag in flags:
                setattr(role, flag, True)
            db.session.add(role)
        db.session.commit()
        print("Seeded default roles.")
    if not RunStatus.query.count():
        for i, (name, color) in enumerate(
            [
                ("Planned", "#7a00df"),
                ("In Progress", "#F7941E"),
                ("Complete", "#0aa574"),
                ("On Hold", "#8a8797"),
                ("Cancelled", "#cf2e2e"),
            ]
        ):
            db.session.add(RunStatus(name=name, color=color, position=i))
        db.session.commit()
        print("Seeded default run statuses.")


def ensure_docroots():
    """Runs on every start (unlike seed) so upgrades pick up the new table."""
    if not DocumentRoot.query.count():
        db.session.add(DocumentRoot(name="Shares", container_path="/shares", link_prefix=""))
        db.session.commit()
        print("Registered default document root at /shares.")


def main():
    app = create_app()
    wait_for_db(app)
    with app.app_context():
        db.create_all()
        migrate()
        ensure_roles_and_statuses()
        seed()
        ensure_docroots()
    print("Database ready.")


if __name__ == "__main__":
    main()

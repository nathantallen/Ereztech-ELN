from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager

PROJECT_STATUSES = ["Active", "On Hold", "Complete", "Cancelled"]
DELIVERABLE_STATUSES = ["Not Started", "In Progress", "Delivered", "Accepted"]

# The five reviewable aspects of every production run, in process order.
STAGE_DEFS = [
    ("raw_materials", "Raw Materials — Ordering & Incoming QC"),
    ("procedure", "Procedure (R&D)"),
    ("process_data", "Process Data & Run Results"),
    ("qc", "QC Results"),
    ("inventory", "Final Material → Inventory"),
]

PROJECT_APPROVAL_ASPECTS = [
    "Project Deliverables",
    "Final Procedure",
    "Final QC Methods",
    "Project Completion",
]

REACTOR_COLORS = ["#7a00df", "#F7941E", "#0693e3", "#00a878", "#BD6FD5", "#04194e"]

# Assigned to researchers on the R&D calendar, cycling in User.id order so each
# person keeps the same color month to month.
RESEARCHER_COLORS = [
    "#7a00df", "#F7941E", "#0693e3", "#00a878",
    "#BD6FD5", "#04194e", "#cf2e2e", "#b8860b",
]
UNASSIGNED_COLOR = "#8a8797"


class Role(db.Model):
    """User types. Users reference roles by name; renames cascade to users.
    Permissions come from the flags, so custom roles work everywhere."""
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), unique=True, nullable=False)
    color = db.Column(db.String(9), default="#7a00df", nullable=False)
    position = db.Column(db.Integer, default=0)
    manage_users = db.Column(db.Boolean, default=False, nullable=False)      # admin: users, roles, doc roots
    edit_production = db.Column(db.Boolean, default=False, nullable=False)   # runs, reactors, statuses
    edit_rd_all = db.Column(db.Boolean, default=False, nullable=False)       # any R&D project
    edit_rd_own = db.Column(db.Boolean, default=False, nullable=False)       # own R&D projects only


class RunStatus(db.Model):
    """Production run statuses. Runs reference statuses by name; renames cascade."""
    __tablename__ = "run_statuses"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), unique=True, nullable=False)
    color = db.Column(db.String(9), default="#7a00df", nullable=False)
    position = db.Column(db.Integer, default=0)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(40), nullable=False, default="Operator")
    password_hash = db.Column(db.String(256), nullable=False)
    is_active_user = db.Column(db.Boolean, default=True, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):
        return self.is_active_user


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class Reactor(db.Model):
    __tablename__ = "reactors"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.Text, default="")
    color = db.Column(db.String(9), default="#7a00df")
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    attributes = db.relationship(
        "ReactorAttribute", backref="reactor", cascade="all, delete-orphan",
        order_by="ReactorAttribute.id",
    )
    runs = db.relationship("ProductionRun", backref="reactor")


class ReactorAttribute(db.Model):
    __tablename__ = "reactor_attributes"
    id = db.Column(db.Integer, primary_key=True)
    reactor_id = db.Column(db.Integer, db.ForeignKey("reactors.id"), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    value = db.Column(db.String(200), nullable=False)


class ProductionRun(db.Model):
    __tablename__ = "production_runs"
    id = db.Column(db.Integer, primary_key=True)
    product = db.Column(db.String(160), nullable=False)
    batch_number = db.Column(db.String(80), default="")
    reactor_id = db.Column(db.Integer, db.ForeignKey("reactors.id"), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(60), default="Planned", nullable=False)
    notes = db.Column(db.Text, default="")
    # Set when this batch is an intermediate consumed by another scheduled run.
    intermediate_for_id = db.Column(
        db.Integer, db.ForeignKey("production_runs.id", ondelete="SET NULL")
    )

    stages = db.relationship(
        "RunStage", backref="run", cascade="all, delete-orphan", order_by="RunStage.position"
    )
    intermediate_for = db.relationship(
        "ProductionRun",
        remote_side="ProductionRun.id",
        backref="feeder_runs",
        foreign_keys=[intermediate_for_id],
    )

    @property
    def duration_days(self):
        return (self.end_date - self.start_date).days + 1

    @property
    def approved_stage_count(self):
        return sum(1 for s in self.stages if s.approval_status == "Approved")

    def ensure_stages(self):
        existing = {s.key for s in self.stages}
        for i, (key, name) in enumerate(STAGE_DEFS):
            if key not in existing:
                self.stages.append(RunStage(key=key, name=name, position=i))


class RunStage(db.Model):
    __tablename__ = "run_stages"
    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey("production_runs.id"), nullable=False)
    key = db.Column(db.String(40), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    position = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text, default="")

    links = db.relationship(
        "StageLink", backref="stage", cascade="all, delete-orphan", order_by="StageLink.id"
    )
    approvals = db.relationship(
        "StageApproval", backref="stage", cascade="all, delete-orphan",
        order_by="StageApproval.created_at",
    )

    @property
    def approval_status(self):
        if any(a.status == "Rejected" for a in self.approvals):
            return "Rejected"
        if any(a.status == "Approved" for a in self.approvals):
            return "Approved"
        return "Pending"


class StageLink(db.Model):
    __tablename__ = "stage_links"
    id = db.Column(db.Integer, primary_key=True)
    stage_id = db.Column(db.Integer, db.ForeignKey("run_stages.id"), nullable=False)
    label = db.Column(db.String(160), nullable=False)
    url = db.Column(db.Text, nullable=False)


class StageApproval(db.Model):
    __tablename__ = "stage_approvals"
    id = db.Column(db.Integer, primary_key=True)
    stage_id = db.Column(db.Integer, db.ForeignKey("run_stages.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    role = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(20), nullable=False)  # Approved / Rejected
    comment = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User")


class RDProject(db.Model):
    __tablename__ = "rd_projects"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    customer = db.Column(db.String(160), default="")
    researcher_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    status = db.Column(db.String(30), default="Active", nullable=False)
    description = db.Column(db.Text, default="")
    start_date = db.Column(db.Date)
    due_date = db.Column(db.Date)
    folder_url = db.Column(db.Text, default="")  # SharePoint / network drive folder
    final_procedure_url = db.Column(db.Text, default="")
    final_qc_url = db.Column(db.Text, default="")

    researcher = db.relationship("User")
    deliverables = db.relationship(
        "Deliverable", backref="project", cascade="all, delete-orphan", order_by="Deliverable.id"
    )
    approvals = db.relationship(
        "ProjectApproval", backref="project", cascade="all, delete-orphan",
        order_by="ProjectApproval.created_at",
    )

    def aspect_status(self, aspect):
        rows = [a for a in self.approvals if a.aspect == aspect]
        if any(a.status == "Rejected" for a in rows):
            return "Rejected"
        if any(a.status == "Approved" for a in rows):
            return "Approved"
        return "Pending"


class DocumentRoot(db.Model):
    r"""A folder mounted into the container that the Browse dialog can walk.
    link_prefix maps container paths back to the address users should open
    (a SharePoint URL or a \\server\share UNC path)."""
    __tablename__ = "document_roots"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    container_path = db.Column(db.Text, nullable=False)
    link_prefix = db.Column(db.Text, default="")


class Deliverable(db.Model):
    __tablename__ = "deliverables"
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("rd_projects.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(30), default="Not Started", nullable=False)
    due_date = db.Column(db.Date)
    link_url = db.Column(db.Text, default="")


class ProjectApproval(db.Model):
    __tablename__ = "project_approvals"
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("rd_projects.id"), nullable=False)
    aspect = db.Column(db.String(60), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    role = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    comment = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User")

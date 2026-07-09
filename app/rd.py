import calendar as cal
from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .calendar_utils import month_lane_grid, month_params
from .extensions import db
from .models import (
    DELIVERABLE_STATUSES,
    PROJECT_APPROVAL_ASPECTS,
    PROJECT_STATUSES,
    RESEARCHER_COLORS,
    UNASSIGNED_COLOR,
    Deliverable,
    ProjectApproval,
    RDProject,
    User,
)
from .permissions import can_edit_rd, is_admin

bp = Blueprint("rd", __name__, url_prefix="/projects")


def parse_date(value):
    value = (value or "").strip()
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


def researchers():
    return User.query.filter_by(is_active_user=True).order_by(User.full_name).all()


@bp.route("/")
@login_required
def list_projects():
    projects = RDProject.query.order_by(RDProject.status, RDProject.due_date).all()
    return render_template("projects.html", projects=projects, can_edit=can_edit_rd())


@bp.route("/calendar")
@login_required
def rd_calendar():
    today, year, month, first, last, prev_m, next_m = month_params()
    projects = RDProject.query.all()
    dated = [p for p in projects if p.start_date or p.due_date]
    undated = [p for p in projects if not (p.start_date or p.due_date)]

    def start_of(p):
        return p.start_date or p.due_date

    def end_of(p):
        return p.due_date or p.start_date

    weeks, grid_start, grid_end = month_lane_grid(dated, year, month, today, start_of, end_of)
    # Mark bar starts/ends so the template can round the right chip corners.
    for week in weeks:
        for day in week:
            day["lanes"] = [
                None if p is None else {
                    "p": p,
                    "is_start": start_of(p) == day["date"],
                    "is_end": end_of(p) == day["date"],
                }
                for p in day["lanes"]
            ]

    deliverables = (
        Deliverable.query.filter(
            Deliverable.due_date.isnot(None),
            Deliverable.due_date >= grid_start,
            Deliverable.due_date <= grid_end,
        )
        .order_by(Deliverable.due_date)
        .all()
    )
    milestones = {}
    for d in deliverables:
        milestones.setdefault(d.due_date, []).append(d)

    # Stable color per researcher (keyed to User.id order, not what's on screen).
    all_users = User.query.order_by(User.id).all()
    color_map = {
        u.id: RESEARCHER_COLORS[i % len(RESEARCHER_COLORS)]
        for i, u in enumerate(all_users)
    }
    shown_ids = {p.researcher_id for p in dated if p.researcher_id}
    legend = [(u.full_name, color_map[u.id]) for u in all_users if u.id in shown_ids]
    if any(p.researcher_id is None for p in dated):
        legend.append(("Unassigned", UNASSIGNED_COLOR))

    return render_template(
        "rd_calendar.html",
        weeks=weeks,
        milestones=milestones,
        undated=undated,
        color_map=color_map,
        unassigned_color=UNASSIGNED_COLOR,
        legend=legend,
        year=year,
        month=month,
        month_name=cal.month_name[month],
        prev_m=prev_m,
        next_m=next_m,
        can_edit=can_edit_rd(),
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_project():
    if not can_edit_rd():
        abort(403)
    if request.method == "POST":
        project = RDProject(
            name=request.form["name"].strip(),
            customer=request.form.get("customer", "").strip(),
            researcher_id=request.form.get("researcher_id", type=int),
            status=request.form.get("status", "Active"),
            description=request.form.get("description", ""),
            start_date=parse_date(request.form.get("start_date")),
            due_date=parse_date(request.form.get("due_date")),
            folder_url=request.form.get("folder_url", "").strip(),
            final_procedure_url=request.form.get("final_procedure_url", "").strip(),
            final_qc_url=request.form.get("final_qc_url", "").strip(),
        )
        db.session.add(project)
        db.session.commit()
        flash("R&D project created.", "ok")
        return redirect(url_for("rd.project_detail", project_id=project.id))
    return render_template(
        "project_form.html", project=None, users=researchers(), statuses=PROJECT_STATUSES
    )


@bp.route("/<int:project_id>")
@login_required
def project_detail(project_id):
    project = db.get_or_404(RDProject, project_id)
    return render_template(
        "project_detail.html",
        project=project,
        aspects=PROJECT_APPROVAL_ASPECTS,
        deliverable_statuses=DELIVERABLE_STATUSES,
        can_edit=can_edit_rd(project),
    )


@bp.route("/<int:project_id>/edit", methods=["GET", "POST"])
@login_required
def edit_project(project_id):
    project = db.get_or_404(RDProject, project_id)
    if not can_edit_rd(project):
        abort(403)
    if request.method == "POST":
        project.name = request.form["name"].strip()
        project.customer = request.form.get("customer", "").strip()
        project.researcher_id = request.form.get("researcher_id", type=int)
        project.status = request.form.get("status", project.status)
        project.description = request.form.get("description", "")
        project.start_date = parse_date(request.form.get("start_date"))
        project.due_date = parse_date(request.form.get("due_date"))
        project.folder_url = request.form.get("folder_url", "").strip()
        project.final_procedure_url = request.form.get("final_procedure_url", "").strip()
        project.final_qc_url = request.form.get("final_qc_url", "").strip()
        db.session.commit()
        flash("Project updated.", "ok")
        return redirect(url_for("rd.project_detail", project_id=project.id))
    return render_template(
        "project_form.html", project=project, users=researchers(), statuses=PROJECT_STATUSES
    )


@bp.route("/<int:project_id>/delete", methods=["POST"])
@login_required
def delete_project(project_id):
    project = db.get_or_404(RDProject, project_id)
    if not can_edit_rd(project):
        abort(403)
    db.session.delete(project)
    db.session.commit()
    flash("Project deleted.", "ok")
    return redirect(url_for("rd.list_projects"))


@bp.route("/<int:project_id>/deliverables", methods=["POST"])
@login_required
def add_deliverable(project_id):
    project = db.get_or_404(RDProject, project_id)
    if not can_edit_rd(project):
        abort(403)
    name = request.form.get("name", "").strip()
    if not name:
        flash("A deliverable name is required.", "error")
    else:
        db.session.add(
            Deliverable(
                project_id=project.id,
                name=name,
                status=request.form.get("status", "Not Started"),
                due_date=parse_date(request.form.get("due_date")),
                link_url=request.form.get("link_url", "").strip(),
            )
        )
        db.session.commit()
        flash("Deliverable added.", "ok")
    return redirect(url_for("rd.project_detail", project_id=project.id))


@bp.route("/deliverables/<int:deliverable_id>/update", methods=["POST"])
@login_required
def update_deliverable(deliverable_id):
    deliverable = db.get_or_404(Deliverable, deliverable_id)
    if not can_edit_rd(deliverable.project):
        abort(403)
    deliverable.status = request.form.get("status", deliverable.status)
    if "link_url" in request.form:
        deliverable.link_url = request.form.get("link_url", "").strip()
    db.session.commit()
    flash("Deliverable updated.", "ok")
    return redirect(url_for("rd.project_detail", project_id=deliverable.project_id))


@bp.route("/deliverables/<int:deliverable_id>/delete", methods=["POST"])
@login_required
def delete_deliverable(deliverable_id):
    deliverable = db.get_or_404(Deliverable, deliverable_id)
    if not can_edit_rd(deliverable.project):
        abort(403)
    project_id = deliverable.project_id
    db.session.delete(deliverable)
    db.session.commit()
    flash("Deliverable removed.", "ok")
    return redirect(url_for("rd.project_detail", project_id=project_id))


@bp.route("/<int:project_id>/approve", methods=["POST"])
@login_required
def approve_project(project_id):
    project = db.get_or_404(RDProject, project_id)
    aspect = request.form.get("aspect")
    status = request.form.get("status")
    if aspect not in PROJECT_APPROVAL_ASPECTS or status not in ("Approved", "Rejected"):
        abort(400)
    db.session.add(
        ProjectApproval(
            project_id=project.id,
            aspect=aspect,
            user_id=current_user.id,
            role=current_user.role,
            status=status,
            comment=request.form.get("comment", "").strip(),
        )
    )
    db.session.commit()
    flash(f"{aspect}: {status.lower()} recorded.", "ok")
    return redirect(url_for("rd.project_detail", project_id=project.id))


@bp.route("/approvals/<int:approval_id>/delete", methods=["POST"])
@login_required
def delete_project_approval(approval_id):
    approval = db.get_or_404(ProjectApproval, approval_id)
    if not (is_admin() or approval.user_id == current_user.id):
        abort(403)
    project_id = approval.project_id
    db.session.delete(approval)
    db.session.commit()
    flash("Approval entry removed.", "ok")
    return redirect(url_for("rd.project_detail", project_id=project_id))

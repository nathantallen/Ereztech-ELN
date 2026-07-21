from datetime import date, datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .extensions import db
from .models import (
    ProductionRun,
    Reactor,
    RunStage,
    RunStatus,
    StageApproval,
    StageLink,
)
from .permissions import can_edit_production, is_admin

bp = Blueprint("runs", __name__, url_prefix="/runs")


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def require_production_editor():
    if not can_edit_production():
        abort(403)


def status_choices():
    return RunStatus.query.order_by(RunStatus.position, RunStatus.id).all()


def parse_intermediate(form, run_id=None):
    target = form.get("intermediate_for_id", type=int)
    if not target or target == run_id:
        return None
    return target if db.session.get(ProductionRun, target) else None


def link_choices(exclude_id=None):
    q = ProductionRun.query.order_by(ProductionRun.start_date.desc())
    return [r for r in q if r.id != exclude_id]


@bp.route("/")
@login_required
def list_runs():
    runs = ProductionRun.query.order_by(ProductionRun.start_date.desc()).all()
    return render_template("runs_list.html", runs=runs, can_edit=can_edit_production())


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_run():
    require_production_editor()
    reactors = Reactor.query.filter_by(is_active=True).order_by(Reactor.name).all()
    if request.method == "POST":
        try:
            start = parse_date(request.form["start_date"])
            end = parse_date(request.form["end_date"])
        except (KeyError, ValueError):
            flash("Valid start and end dates are required.", "error")
            return render_template("run_form.html", run=None, reactors=reactors,
                                   statuses=status_choices(), link_runs=link_choices())
        if end < start:
            flash("End date must be on or after the start date.", "error")
            return render_template("run_form.html", run=None, reactors=reactors,
                                   statuses=status_choices(), link_runs=link_choices())
        run = ProductionRun(
            product=request.form["product"].strip(),
            batch_number=request.form.get("batch_number", "").strip(),
            reactor_id=int(request.form["reactor_id"]),
            start_date=start,
            end_date=end,
            status=request.form.get("status", "Planned"),
            notes=request.form.get("notes", ""),
            intermediate_for_id=parse_intermediate(request.form),
        )
        run.ensure_stages()
        db.session.add(run)
        db.session.commit()
        flash("Production run created.", "ok")
        return redirect(url_for("runs.run_detail", run_id=run.id))
    return render_template("run_form.html", run=None, reactors=reactors,
                                   statuses=status_choices(), link_runs=link_choices())


@bp.route("/<int:run_id>")
@login_required
def run_detail(run_id):
    run = db.get_or_404(ProductionRun, run_id)
    return render_template("run_detail.html", run=run, can_edit=can_edit_production())


@bp.route("/<int:run_id>/edit", methods=["GET", "POST"])
@login_required
def edit_run(run_id):
    require_production_editor()
    run = db.get_or_404(ProductionRun, run_id)
    reactors = Reactor.query.order_by(Reactor.name).all()
    if request.method == "POST":
        try:
            start = parse_date(request.form["start_date"])
            end = parse_date(request.form["end_date"])
        except (KeyError, ValueError):
            flash("Valid start and end dates are required.", "error")
            return render_template("run_form.html", run=run, reactors=reactors,
                                   statuses=status_choices(), link_runs=link_choices(run.id))
        if end < start:
            flash("End date must be on or after the start date.", "error")
            return render_template("run_form.html", run=run, reactors=reactors,
                                   statuses=status_choices(), link_runs=link_choices(run.id))
        run.product = request.form["product"].strip()
        run.batch_number = request.form.get("batch_number", "").strip()
        run.reactor_id = int(request.form["reactor_id"])
        run.start_date = start
        run.end_date = end
        run.status = request.form.get("status", run.status)
        run.notes = request.form.get("notes", "")
        run.intermediate_for_id = parse_intermediate(request.form, run.id)
        db.session.commit()
        flash("Production run updated.", "ok")
        return redirect(url_for("runs.run_detail", run_id=run.id))
    return render_template("run_form.html", run=run, reactors=reactors,
                                   statuses=status_choices(), link_runs=link_choices(run.id))


@bp.route("/<int:run_id>/delete", methods=["POST"])
@login_required
def delete_run(run_id):
    require_production_editor()
    run = db.get_or_404(ProductionRun, run_id)
    db.session.delete(run)
    db.session.commit()
    flash("Production run deleted.", "ok")
    return redirect(url_for("runs.list_runs"))


@bp.route("/stage/<int:stage_id>/notes", methods=["POST"])
@login_required
def stage_notes(stage_id):
    require_production_editor()
    stage = db.get_or_404(RunStage, stage_id)
    stage.notes = request.form.get("notes", "")
    db.session.commit()
    flash(f"Notes saved for {stage.name}.", "ok")
    return redirect(url_for("runs.run_detail", run_id=stage.run_id))


@bp.route("/stage/<int:stage_id>/links", methods=["POST"])
@login_required
def add_stage_link(stage_id):
    require_production_editor()
    stage = db.get_or_404(RunStage, stage_id)
    label = request.form.get("label", "").strip()
    url = request.form.get("url", "").strip()
    if label and url:
        db.session.add(StageLink(stage_id=stage.id, label=label, url=url))
        db.session.commit()
        flash("Link added.", "ok")
    else:
        flash("Both a label and a link/path are required.", "error")
    return redirect(url_for("runs.run_detail", run_id=stage.run_id))


@bp.route("/links/<int:link_id>/delete", methods=["POST"])
@login_required
def delete_stage_link(link_id):
    require_production_editor()
    link = db.get_or_404(StageLink, link_id)
    run_id = link.stage.run_id
    db.session.delete(link)
    db.session.commit()
    flash("Link removed.", "ok")
    return redirect(url_for("runs.run_detail", run_id=run_id))


@bp.route("/stage/<int:stage_id>/approve", methods=["POST"])
@login_required
def approve_stage(stage_id):
    stage = db.get_or_404(RunStage, stage_id)
    status = request.form.get("status")
    if status not in ("Approved", "Rejected"):
        abort(400)
    db.session.add(
        StageApproval(
            stage_id=stage.id,
            user_id=current_user.id,
            role=current_user.role,
            status=status,
            comment=request.form.get("comment", "").strip(),
        )
    )
    db.session.commit()
    flash(f"{stage.name}: {status.lower()} recorded.", "ok")
    return redirect(url_for("runs.run_detail", run_id=stage.run_id))


@bp.route("/approvals/<int:approval_id>/delete", methods=["POST"])
@login_required
def delete_approval(approval_id):
    approval = db.get_or_404(StageApproval, approval_id)
    if not (is_admin() or approval.user_id == current_user.id):
        abort(403)
    run_id = approval.stage.run_id
    db.session.delete(approval)
    db.session.commit()
    flash("Approval entry removed.", "ok")
    return redirect(url_for("runs.run_detail", run_id=run_id))

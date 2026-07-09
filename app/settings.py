from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .extensions import db
from .models import ProductionRun, Role, RunStatus, User
from .permissions import admin_required, can_edit_production

bp = Blueprint("settings", __name__, url_prefix="/settings")

FLAGS = ["manage_users", "edit_production", "edit_rd_all", "edit_rd_own"]


# ---------- Roles (user types) ----------

@bp.route("/roles")
@login_required
@admin_required
def roles():
    rows = Role.query.order_by(Role.position, Role.id).all()
    counts = {
        name: n for name, n in db.session.query(User.role, db.func.count()).group_by(User.role)
    }
    return render_template("roles.html", roles=rows, counts=counts)


@bp.route("/roles/new", methods=["POST"])
@login_required
@admin_required
def new_role():
    name = request.form.get("name", "").strip()
    if not name:
        flash("A role name is required.", "error")
    elif Role.query.filter_by(name=name).first():
        flash("A role with that name already exists.", "error")
    else:
        role = Role(
            name=name,
            color=request.form.get("color", "#7a00df"),
            position=(db.session.query(db.func.max(Role.position)).scalar() or 0) + 1,
        )
        for flag in FLAGS:
            setattr(role, flag, flag in request.form)
        db.session.add(role)
        db.session.commit()
        flash("Role added.", "ok")
    return redirect(url_for("settings.roles"))


@bp.route("/roles/<int:role_id>/update", methods=["POST"])
@login_required
@admin_required
def update_role(role_id):
    role = db.get_or_404(Role, role_id)
    if (
        role.name == current_user.role
        and role.manage_users
        and "manage_users" not in request.form
    ):
        flash("You can't remove admin rights from your own role — that would lock you out.", "error")
        return redirect(url_for("settings.roles"))
    new_name = request.form.get("name", "").strip()
    if new_name and new_name != role.name:
        if Role.query.filter_by(name=new_name).first():
            flash("A role with that name already exists.", "error")
            return redirect(url_for("settings.roles"))
        User.query.filter_by(role=role.name).update({"role": new_name})
        role.name = new_name
    role.color = request.form.get("color", role.color)
    for flag in FLAGS:
        setattr(role, flag, flag in request.form)
    db.session.commit()
    flash("Role updated.", "ok")
    return redirect(url_for("settings.roles"))


@bp.route("/roles/<int:role_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_role(role_id):
    role = db.get_or_404(Role, role_id)
    in_use = User.query.filter_by(role=role.name).count()
    if in_use:
        flash(f"{in_use} user(s) hold the role '{role.name}'. Reassign them first.", "error")
    else:
        db.session.delete(role)
        db.session.commit()
        flash("Role deleted.", "ok")
    return redirect(url_for("settings.roles"))


# ---------- Production run statuses ----------

def require_production_editor():
    if not can_edit_production():
        abort(403)


@bp.route("/statuses")
@login_required
def statuses():
    require_production_editor()
    rows = RunStatus.query.order_by(RunStatus.position, RunStatus.id).all()
    counts = {
        name: n
        for name, n in db.session.query(ProductionRun.status, db.func.count()).group_by(
            ProductionRun.status
        )
    }
    return render_template("statuses.html", statuses=rows, counts=counts)


@bp.route("/statuses/new", methods=["POST"])
@login_required
def new_status():
    require_production_editor()
    name = request.form.get("name", "").strip()
    if not name:
        flash("A status name is required.", "error")
    elif RunStatus.query.filter_by(name=name).first():
        flash("A status with that name already exists.", "error")
    else:
        db.session.add(
            RunStatus(
                name=name,
                color=request.form.get("color", "#7a00df"),
                position=(db.session.query(db.func.max(RunStatus.position)).scalar() or 0) + 1,
            )
        )
        db.session.commit()
        flash("Status added.", "ok")
    return redirect(url_for("settings.statuses"))


@bp.route("/statuses/<int:status_id>/update", methods=["POST"])
@login_required
def update_status(status_id):
    require_production_editor()
    status = db.get_or_404(RunStatus, status_id)
    new_name = request.form.get("name", "").strip()
    if new_name and new_name != status.name:
        if RunStatus.query.filter_by(name=new_name).first():
            flash("A status with that name already exists.", "error")
            return redirect(url_for("settings.statuses"))
        ProductionRun.query.filter_by(status=status.name).update({"status": new_name})
        status.name = new_name
    status.color = request.form.get("color", status.color)
    db.session.commit()
    flash("Status updated.", "ok")
    return redirect(url_for("settings.statuses"))


@bp.route("/statuses/<int:status_id>/delete", methods=["POST"])
@login_required
def delete_status(status_id):
    require_production_editor()
    status = db.get_or_404(RunStatus, status_id)
    in_use = ProductionRun.query.filter_by(status=status.name).count()
    if in_use:
        flash(f"{in_use} run(s) currently use '{status.name}'. Reassign them first.", "error")
    elif RunStatus.query.count() <= 1:
        flash("At least one status must remain.", "error")
    else:
        db.session.delete(status)
        db.session.commit()
        flash("Status deleted.", "ok")
    return redirect(url_for("settings.statuses"))

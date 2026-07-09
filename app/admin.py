from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .extensions import db
from .models import ProjectApproval, RDProject, Role, StageApproval, User
from .permissions import admin_required


def role_choices():
    return Role.query.order_by(Role.position, Role.id).all()

bp = Blueprint("admin", __name__, url_prefix="/users")


@bp.route("/")
@login_required
@admin_required
def list_users():
    users = User.query.order_by(User.full_name).all()
    return render_template("users.html", users=users)


@bp.route("/new", methods=["GET", "POST"])
@login_required
@admin_required
def new_user():
    if request.method == "POST":
        username = request.form["username"].strip()
        if User.query.filter_by(username=username).first():
            flash("That username is already taken.", "error")
        elif not request.form.get("password"):
            flash("A password is required.", "error")
        else:
            user = User(
                username=username,
                full_name=request.form["full_name"].strip(),
                role=request.form.get("role", "Operator"),
                is_active_user="is_active" in request.form,
            )
            user.set_password(request.form["password"])
            db.session.add(user)
            db.session.commit()
            flash("User created.", "ok")
            return redirect(url_for("admin.list_users"))
    return render_template("user_form.html", user=None, roles=role_choices())


@bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_user(user_id):
    user = db.get_or_404(User, user_id)
    if request.method == "POST":
        new_username = request.form.get("username", "").strip()
        if new_username and new_username != user.username:
            if User.query.filter_by(username=new_username).first():
                flash("That username is already taken.", "error")
                return render_template("user_form.html", user=user, roles=role_choices())
            user.username = new_username
        user.full_name = request.form["full_name"].strip()
        user.role = request.form.get("role", user.role)
        if user.id != current_user.id:
            user.is_active_user = "is_active" in request.form
        if request.form.get("password"):
            user.set_password(request.form["password"])
        db.session.commit()
        flash("User updated.", "ok")
        return redirect(url_for("admin.list_users"))
    return render_template("user_form.html", user=user, roles=role_choices())


@bp.route("/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash("You can't delete your own account.", "error")
        return redirect(url_for("admin.list_users"))
    approval_count = (
        StageApproval.query.filter_by(user_id=user.id).count()
        + ProjectApproval.query.filter_by(user_id=user.id).count()
    )
    if approval_count:
        flash(
            f"{user.full_name} has {approval_count} approval record(s), which must be "
            "kept for the audit trail. Disable the account instead (Edit → uncheck "
            "'Account enabled').",
            "error",
        )
        return redirect(url_for("admin.list_users"))
    for project in RDProject.query.filter_by(researcher_id=user.id).all():
        project.researcher_id = None
    db.session.delete(user)
    db.session.commit()
    flash(f"User {user.full_name} deleted.", "ok")
    return redirect(url_for("admin.list_users"))

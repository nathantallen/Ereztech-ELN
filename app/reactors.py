from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required

from .extensions import db
from .models import REACTOR_COLORS, ProductionRun, Reactor, ReactorAttribute
from .permissions import can_edit_production

bp = Blueprint("reactors", __name__, url_prefix="/reactors")


def require_editor():
    if not can_edit_production():
        abort(403)


@bp.route("/")
@login_required
def list_reactors():
    reactors = Reactor.query.order_by(Reactor.name).all()
    return render_template("reactors.html", reactors=reactors, can_edit=can_edit_production())


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_reactor():
    require_editor()
    if request.method == "POST":
        reactor = Reactor(
            name=request.form["name"].strip(),
            description=request.form.get("description", ""),
            color=request.form.get("color", "#7a00df"),
            is_active="is_active" in request.form,
        )
        db.session.add(reactor)
        db.session.commit()
        flash("Reactor added.", "ok")
        return redirect(url_for("reactors.edit_reactor", reactor_id=reactor.id))
    return render_template("reactor_form.html", reactor=None, colors=REACTOR_COLORS)


@bp.route("/<int:reactor_id>/edit", methods=["GET", "POST"])
@login_required
def edit_reactor(reactor_id):
    require_editor()
    reactor = db.get_or_404(Reactor, reactor_id)
    if request.method == "POST":
        reactor.name = request.form["name"].strip()
        reactor.description = request.form.get("description", "")
        reactor.color = request.form.get("color", reactor.color)
        reactor.is_active = "is_active" in request.form
        db.session.commit()
        flash("Reactor updated.", "ok")
        return redirect(url_for("reactors.list_reactors"))
    return render_template("reactor_form.html", reactor=reactor, colors=REACTOR_COLORS)


@bp.route("/<int:reactor_id>/delete", methods=["POST"])
@login_required
def delete_reactor(reactor_id):
    require_editor()
    reactor = db.get_or_404(Reactor, reactor_id)
    if ProductionRun.query.filter_by(reactor_id=reactor.id).count():
        flash("This reactor has scheduled runs. Reassign or delete those runs first, or mark the reactor inactive.", "error")
        return redirect(url_for("reactors.list_reactors"))
    db.session.delete(reactor)
    db.session.commit()
    flash("Reactor deleted.", "ok")
    return redirect(url_for("reactors.list_reactors"))


@bp.route("/<int:reactor_id>/attributes", methods=["POST"])
@login_required
def add_attribute(reactor_id):
    require_editor()
    reactor = db.get_or_404(Reactor, reactor_id)
    name = request.form.get("name", "").strip()
    value = request.form.get("value", "").strip()
    if name and value:
        db.session.add(ReactorAttribute(reactor_id=reactor.id, name=name, value=value))
        db.session.commit()
        flash("Attribute added.", "ok")
    else:
        flash("Both an attribute name and value are required.", "error")
    return redirect(url_for("reactors.edit_reactor", reactor_id=reactor.id))


@bp.route("/attributes/<int:attr_id>/delete", methods=["POST"])
@login_required
def delete_attribute(attr_id):
    require_editor()
    attr = db.get_or_404(ReactorAttribute, attr_id)
    reactor_id = attr.reactor_id
    db.session.delete(attr)
    db.session.commit()
    flash("Attribute removed.", "ok")
    return redirect(url_for("reactors.edit_reactor", reactor_id=reactor_id))

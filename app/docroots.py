import os
from pathlib import Path
from urllib.parse import quote

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required

from .extensions import db
from .models import DocumentRoot
from .permissions import admin_required

bp = Blueprint("docroots", __name__, url_prefix="/docroots")


def build_link(root, rel):
    """Map a path relative to the root back to the link users should open."""
    prefix = (root.link_prefix or "").strip()
    if not rel:
        return prefix or root.container_path
    if prefix.startswith("\\\\"):
        return prefix.rstrip("\\") + "\\" + rel.replace("/", "\\")
    if prefix.startswith(("http://", "https://")):
        return prefix.rstrip("/") + "/" + "/".join(quote(seg) for seg in rel.split("/"))
    if prefix:  # plain filesystem prefix — keep spaces etc. as-is
        return prefix.rstrip("/") + "/" + rel
    return str(Path(root.container_path) / rel)


@bp.route("/browse")
@login_required
def browse():
    roots = DocumentRoot.query.order_by(DocumentRoot.name).all()
    payload_roots = [{"id": r.id, "name": r.name} for r in roots]
    if not roots:
        return jsonify(
            {
                "roots": [],
                "error": "No document roots are configured. An Admin can add one under Doc Roots.",
            }
        )
    root = db.session.get(DocumentRoot, request.args.get("root_id", type=int)) or roots[0]
    rel = request.args.get("path", "").strip("/")
    base = Path(root.container_path).resolve()
    target = (base / rel).resolve() if rel else base
    if base != target and base not in target.parents:
        abort(400)
    if not target.is_dir():
        return jsonify(
            {
                "roots": payload_roots,
                "root_id": root.id,
                "path": "",
                "error": (
                    f"'{root.container_path}' is not available inside the container. "
                    "Check the volume mount in docker-compose.yml and the Doc Roots setup."
                ),
            }
        )
    entries = []
    for p in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if p.name.startswith("."):
            continue
        rel_path = str(p.relative_to(base)).replace(os.sep, "/")
        entries.append(
            {
                "name": p.name,
                "is_dir": p.is_dir(),
                "path": rel_path,
                "link": build_link(root, rel_path),
            }
        )
    return jsonify(
        {
            "roots": payload_roots,
            "root_id": root.id,
            "path": rel,
            "folder_link": build_link(root, rel),
            "entries": entries,
        }
    )


@bp.route("/")
@login_required
@admin_required
def list_roots():
    roots = DocumentRoot.query.order_by(DocumentRoot.name).all()
    for r in roots:
        r.exists = Path(r.container_path).is_dir()
    return render_template("docroots.html", roots=roots)


@bp.route("/new", methods=["POST"])
@login_required
@admin_required
def new_root():
    name = request.form.get("name", "").strip()
    container_path = request.form.get("container_path", "").strip()
    if not name or not container_path:
        flash("A name and a container path are both required.", "error")
    elif DocumentRoot.query.filter_by(name=name).first():
        flash("A document root with that name already exists.", "error")
    else:
        db.session.add(
            DocumentRoot(
                name=name,
                container_path=container_path,
                link_prefix=request.form.get("link_prefix", "").strip(),
            )
        )
        db.session.commit()
        flash("Document root added.", "ok")
    return redirect(url_for("docroots.list_roots"))


@bp.route("/<int:root_id>/update", methods=["POST"])
@login_required
@admin_required
def update_root(root_id):
    root = db.get_or_404(DocumentRoot, root_id)
    root.name = request.form.get("name", root.name).strip() or root.name
    root.container_path = request.form.get("container_path", root.container_path).strip()
    root.link_prefix = request.form.get("link_prefix", "").strip()
    db.session.commit()
    flash("Document root updated.", "ok")
    return redirect(url_for("docroots.list_roots"))


@bp.route("/<int:root_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_root(root_id):
    root = db.get_or_404(DocumentRoot, root_id)
    db.session.delete(root)
    db.session.commit()
    flash("Document root removed.", "ok")
    return redirect(url_for("docroots.list_roots"))

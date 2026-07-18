import os
import re

from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, send_from_directory, url_for)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from .chem import formula_and_mw, pubchem_lookup
from .storage import BATCH_STATUSES, slugify, utcnow
from .svg import namespace_svg as _ns_svg, sanitize_svg

bp = Blueprint("materials", __name__, url_prefix="/materials")

MATERIAL_FIELDS = ("name", "cas", "formula", "supplier", "hazards", "storage")
BATCH_FIELDS = ("lot", "supplier", "received", "expiry", "purity", "quantity",
                "container", "location", "status")


def _storage():
    return current_app.extensions["storage"]


def _require_edit():
    if not current_user.can_edit:
        abort(403)


def _get_material_or_404(slug):
    try:
        meta, notes = _storage().get_material(slug)
    except ValueError:
        abort(404)
    if meta is None:
        abort(404)
    return meta, notes


@bp.route("/")
@login_required
def list_materials():
    q = request.args.get("q", "").strip().lower()
    mats = _storage().list_materials()
    if q:
        mats = [m for m in mats if q in " ".join(
            str(m.get(k, "")) for k in ("name", "cas", "formula", "supplier")).lower()]
    for i, m in enumerate(mats):
        m["_svg"] = _material_svg(m.get("slug", ""), "ml%d" % i)
    return render_template("materials.html", materials=mats, q=request.args.get("q", ""))


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_material():
    _require_edit()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name is required.", "error")
            return redirect(url_for("materials.new_material"))
        slug = slugify(name)
        storage = _storage()
        if storage.get_material(slug)[0] is not None:
            flash("A material with that name already exists.", "error")
            return redirect(url_for("materials.view", slug=slug))
        meta = {k: request.form.get(k, "").strip() for k in MATERIAL_FIELDS}
        meta["slug"] = slug
        meta["air_sensitive"] = bool(request.form.get("air_sensitive"))
        meta["created"] = utcnow()
        meta["created_by"] = current_user.username
        storage.save_material(slug, meta, request.form.get("notes", ""))
        flash("Material created.", "success")
        return redirect(url_for("materials.view", slug=slug))
    return render_template("material_form.html", meta=None, notes="")


def _material_svg(slug, uid):
    # A hand-edited / corrupted material.md may carry a missing or invalid slug;
    # material_dir() would raise (ValueError/TypeError) and 500 the whole catalog.
    if not slug or not re.fullmatch(r"[a-z0-9-]+", slug):
        return ""
    path = os.path.join(_storage().material_dir(slug), "structure.svg")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _ns_svg(f.read(), uid)
    except OSError:
        return ""


@bp.route("/<slug>")
@login_required
def view(slug):
    meta, notes = _get_material_or_404(slug)
    storage = _storage()
    batches = storage.list_batches(slug)
    usage = {b.get("lot"): storage.entries_using_batch(slug, b.get("lot")) for b in batches}
    return render_template("material_view.html", meta=meta, notes=notes,
                           batches=batches, usage=usage,
                           structure_svg=_material_svg(slug, "mat"))


@bp.route("/<slug>/structure/draw")
@login_required
def draw_structure(slug):
    _require_edit()
    meta, _ = _get_material_or_404(slug)
    molfile = ""
    path = os.path.join(_storage().material_dir(slug), "structure.mol")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            molfile = f.read()
    return render_template("structure_edit.html", idx=None,
                           subtitle=meta.get("name", slug),
                           action_url=url_for("materials.save_structure", slug=slug),
                           cancel_url=url_for("materials.view", slug=slug),
                           molfile=molfile, caption=meta.get("name", ""))


@bp.route("/<slug>/structure/save", methods=["POST"])
@login_required
def save_structure(slug):
    _require_edit()
    meta, notes = _get_material_or_404(slug)
    storage = _storage()
    molfile = request.form.get("molfile", "")
    if not molfile.strip():
        flash("Nothing to save — the sketcher was empty.", "error")
        return redirect(url_for("materials.view", slug=slug))
    d = storage.material_dir(slug)
    with open(os.path.join(d, "structure.mol"), "w", encoding="utf-8") as f:
        f.write(molfile)
    svg = sanitize_svg(request.form.get("svg", ""))
    if svg.strip():
        with open(os.path.join(d, "structure.svg"), "w", encoding="utf-8") as f:
            f.write(svg)
    meta["smiles"] = request.form.get("smiles", "").strip()
    formula, mw = formula_and_mw(molfile)
    if formula:
        meta["formula"] = meta.get("formula") or formula
        meta["mw"] = mw
    if not meta.get("cas"):
        prop = storage.properties.lookup(name=meta.get("name"), formula=formula)
        hit = prop or pubchem_lookup(meta["smiles"])
        if hit and hit.get("cas"):
            meta["cas"] = hit["cas"]
    meta["updated"] = utcnow()
    storage.save_material(slug, meta, notes)
    flash("Structure saved%s." % (" — MW %.2f g/mol (%s)" % (mw, formula) if mw else ""),
          "success")
    return redirect(url_for("materials.view", slug=slug))


@bp.route("/<slug>/edit", methods=["GET", "POST"])
@login_required
def edit(slug):
    _require_edit()
    meta, notes = _get_material_or_404(slug)
    if request.method == "POST":
        for k in MATERIAL_FIELDS:
            if k != "name":  # name/slug stays stable; entries reference the slug
                meta[k] = request.form.get(k, "").strip()
        meta["name"] = request.form.get("name", "").strip() or meta["name"]
        meta["air_sensitive"] = bool(request.form.get("air_sensitive"))
        meta["updated"] = utcnow()
        _storage().save_material(slug, meta, request.form.get("notes", ""))
        flash("Material saved.", "success")
        return redirect(url_for("materials.view", slug=slug))
    return render_template("material_form.html", meta=meta, notes=notes)


@bp.route("/<slug>/batches/new", methods=["GET", "POST"])
@bp.route("/<slug>/batches/<lot_slug>/edit", methods=["GET", "POST"])
@login_required
def batch_form(slug, lot_slug=None):
    _require_edit()
    mat_meta, _ = _get_material_or_404(slug)
    storage = _storage()
    meta, notes = ({}, "")
    if lot_slug:
        meta, notes = storage.get_batch(slug, lot_slug)
        if meta is None:
            abort(404)
    if request.method == "POST":
        lot = request.form.get("lot", "").strip()
        if not lot:
            flash("Batch / lot number is required.", "error")
            return redirect(request.url)
        new = {k: request.form.get(k, "").strip() for k in BATCH_FIELDS}
        new["material"] = slug
        new["lot_slug"] = lot_slug or slugify(lot)
        if not lot_slug and storage.get_batch(slug, new["lot_slug"])[0] is not None:
            flash("That lot number already exists for this material.", "error")
            return redirect(request.url)
        new["created"] = meta.get("created", utcnow())
        new["created_by"] = meta.get("created_by", current_user.username)
        if lot_slug:
            new["updated"] = utcnow()
            new["attachments"] = meta.get("attachments", [])
        storage.save_batch(slug, new["lot_slug"], new, request.form.get("notes", ""))
        flash("Batch saved.", "success")
        return redirect(url_for("materials.view", slug=slug))
    return render_template("batch_form.html", material=mat_meta, meta=meta, notes=notes,
                           statuses=BATCH_STATUSES)


@bp.route("/<slug>/batches/<lot_slug>/attach", methods=["POST"])
@login_required
def batch_attach(slug, lot_slug):
    _require_edit()
    _get_material_or_404(slug)
    storage = _storage()
    meta, notes = storage.get_batch(slug, lot_slug)
    if meta is None:
        abort(404)
    f = request.files.get("file")
    if not f or not f.filename:
        flash("No file selected.", "error")
        return redirect(url_for("materials.view", slug=slug))
    att_dir = os.path.join(storage.material_dir(slug), "attachments", lot_slug)
    os.makedirs(att_dir, exist_ok=True)
    name = secure_filename(f.filename)
    f.save(os.path.join(att_dir, name))
    meta.setdefault("attachments", []).append({
        "file": "attachments/%s/%s" % (lot_slug, name),
        "label": request.form.get("label", "").strip() or "Certificate of Analysis",
        "uploaded_by": current_user.username,
        "uploaded_at": utcnow(),
    })
    storage.save_batch(slug, lot_slug, meta, notes)
    flash("Document attached to batch %s." % meta.get("lot", lot_slug), "success")
    return redirect(url_for("materials.view", slug=slug))


@bp.route("/<slug>/files/<path:relpath>")
@login_required
def serve_file(slug, relpath):
    _get_material_or_404(slug)
    return send_from_directory(_storage().material_dir(slug), relpath)

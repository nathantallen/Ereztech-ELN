import os
import re

from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, send_from_directory, url_for)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from .chem import formula_and_mw, pubchem_lookup
from .inventory import (UNITS_BY_FAMILY, batch_quantity, format_base,
                        set_batch_quantity, to_base)
from .organo import available_templates
from .storage import BATCH_STATUSES, slugify, utcnow
from .structure_files import load_preferred, save_bundle
from .svg import namespace_svg as _ns_svg, sanitize_svg

bp = Blueprint("materials", __name__, url_prefix="/materials")

MATERIAL_FIELDS = ("name", "cas", "formula", "supplier", "hazards", "storage")
BATCH_FIELDS = ("lot", "supplier", "received", "expiry", "purity",
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
    for batch in batches:
        batch["_inventory"] = batch_quantity(batch)
    usage = {b.get("lot"): storage.entries_using_batch(slug, b.get("lot")) for b in batches}
    return render_template("material_view.html", meta=meta, notes=notes,
                           batches=batches, usage=usage,
                           inventory_transactions=storage.inventory_transactions(material=slug),
                           structure_svg=_material_svg(slug, "mat"))


@bp.route("/<slug>/structure/draw")
@login_required
def draw_structure(slug):
    _require_edit()
    meta, _ = _get_material_or_404(slug)
    molfile = load_preferred(_storage().material_dir(slug), "structure")
    return render_template("structure_edit.html", idx=None,
                           subtitle=meta.get("name", slug),
                           action_url=url_for("materials.save_structure", slug=slug),
                           cancel_url=url_for("materials.view", slug=slug),
                           molfile=molfile, caption=meta.get("name", ""),
                           structure_templates=available_templates(_storage()))


@bp.route("/<slug>/structure/save", methods=["POST"])
@login_required
def save_structure(slug):
    _require_edit()
    meta, notes = _get_material_or_404(slug)
    storage = _storage()
    molfile = request.form.get("molfile", "")
    molfile_v2000 = request.form.get("molfile_v2000", "")
    ket = request.form.get("ket", "")
    if not molfile.strip():
        flash("Nothing to save — the sketcher was empty.", "error")
        return redirect(url_for("materials.view", slug=slug))
    d = storage.material_dir(slug)
    save_bundle(d, "structure", molfile, molfile_v2000, ket)
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
    quantity = batch_quantity(meta) if meta else {
        "value": "", "unit": "g", "family": "mass", "base_value": 0.0,
        "base_unit": "g", "display": "",
    }
    if request.method == "POST":
        lot = request.form.get("lot", "").strip()
        if not lot:
            flash("Batch / lot number is required.", "error")
            return redirect(request.url)
        try:
            new_base, new_base_unit, new_family = to_base(
                request.form.get("quantity_value", ""), request.form.get("quantity_unit", ""))
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(request.url)
        if lot_slug and new_family != quantity["family"] and quantity["base_value"] > 1e-12:
            flash("A stocked batch cannot be changed from %s units to %s units."
                  % (quantity["family"], new_family), "error")
            return redirect(request.url)
        delta = new_base - (quantity["base_value"] if lot_slug else 0.0)
        reason = request.form.get("adjustment_reason", "").strip()
        if lot_slug and abs(delta) > 1e-9 and not reason:
            flash("Explain the inventory adjustment before changing the batch balance.", "error")
            return redirect(request.url)
        new = {k: request.form.get(k, "").strip() for k in BATCH_FIELDS}
        new["material"] = slug
        new["lot_slug"] = lot_slug or slugify(lot)
        if not lot_slug and storage.get_batch(slug, new["lot_slug"])[0] is not None:
            flash("That lot number already exists for this material.", "error")
            return redirect(request.url)
        new["created"] = meta.get("created", utcnow())
        new["created_by"] = meta.get("created_by", current_user.username)
        set_batch_quantity(new, new_base, new_base_unit,
                           request.form.get("quantity_unit", ""))
        new["inventory_updated"] = utcnow()
        new["inventory_updated_by"] = current_user.username
        if new_base <= 1e-12 and new.get("status") in ("In Stock", "Open"):
            new["status"] = "Depleted"
        if lot_slug:
            new["updated"] = utcnow()
            new["attachments"] = meta.get("attachments", [])
        storage.save_batch(slug, new["lot_slug"], new, request.form.get("notes", ""))
        if not lot_slug or abs(delta) > 1e-9:
            display_unit = new["quantity_unit"]
            sign = "+" if delta > 0 else "−" if delta < 0 else ""
            storage.record_inventory_transaction({
                "material": slug, "lot_slug": new["lot_slug"], "lot": lot,
                "by": current_user.username,
                "action": "opening balance" if not lot_slug else "manual adjustment",
                "delta_base": round(delta, 12), "base_unit": new_base_unit,
                "delta_display": sign + format_base(abs(delta), new_base_unit, display_unit),
                "balance_after_base": round(new_base, 12),
                "balance_display": format_base(new_base, new_base_unit, display_unit),
                "detail": reason or "Batch created.",
            })
        flash("Batch saved.", "success")
        return redirect(url_for("materials.view", slug=slug))
    return render_template("batch_form.html", material=mat_meta, meta=meta, notes=notes,
                           statuses=BATCH_STATUSES, quantity=quantity,
                           inventory_units=UNITS_BY_FAMILY)


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
    if not name:
        flash("That filename contains no usable characters.", "error")
        return redirect(url_for("materials.view", slug=slug))
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

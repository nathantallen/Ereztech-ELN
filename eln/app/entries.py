import csv
import datetime
import io
import json
import os
import uuid

import requests
from flask import (Blueprint, abort, current_app, flash, jsonify, redirect,
                   render_template, request, send_from_directory, url_for)
from flask_login import current_user, login_required
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from . import ha
from .chem import formula_and_mw
from .inventory import (UNITS_BY_FAMILY, batch_quantity, format_base,
                        to_base, unit_family, units_for)
from .organo import available_templates
from .storage import (ENTRY_SECTIONS, attachment_kind, compose_sections,
                      parse_sections, utcnow)
from .structure_files import remove_bundle, save_bundle
from .svg import namespace_svg as _ns_svg, sanitize_svg

COMPONENT_ROLES = ["reactant", "reagent", "catalyst", "solvent", "product"]
# the setup form only asks for what exists before the run; results are written
# on the entry page once the work is done
SETUP_SECTIONS = ["Objective", "Procedure"]
ELN_ID_RE = __import__("re").compile(r"ELN-\d{4}-\d{4}")
COMPONENT_STATES = ["solid", "liquid", "solution", "gas"]
RECORDING_FPS = [1, 2, 5, 10, 15]
RECORDING_RESOLUTIONS = ["original", "1280x720", "960x540", "640x480", "320x240"]


def _elapsed_since(iso):
    try:
        t0 = datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return ""
    secs = int((datetime.datetime.now(datetime.timezone.utc) - t0).total_seconds())
    if secs < 0:
        secs = 0
    return "%02d:%02d:%02d" % (secs // 3600, (secs % 3600) // 60, secs % 60)

bp = Blueprint("entries", __name__, url_prefix="/entries")


def _storage():
    return current_app.extensions["storage"]


def _require_edit():
    if not current_user.can_edit:
        abort(403)


def _get_or_404(eid):
    try:
        meta, body = _storage().get_entry(eid)
    except ValueError:
        abort(404)
    if meta is None:
        abort(404)
    return meta, body


def _require_draft(meta):
    if meta.get("status") != "draft":
        flash("This entry is signed and can no longer be edited.", "error")
        abort(redirect(url_for("entries.view", eid=meta["id"])))


def _check_password(password):
    rec = _storage().find_user(current_user.username)
    return rec and check_password_hash(rec["password_hash"], password or "")


def _technique_from_form(form, storage):
    technique = form.get("technique", "").strip()
    new = form.get("new_technique", "").strip()
    if technique == "__new__" or (new and not technique):
        technique = new
    if technique:
        storage.add_technique(technique)
    return technique


def _sections_from_form(form):
    return {h: form.get("section_%d" % i, "") for i, h in enumerate(SETUP_SECTIONS)}


@bp.route("/")
@login_required
def list_entries():
    q = request.args.get("q", "").strip().lower()
    status = request.args.get("status", "")
    # each user has a personal lab book; default to the viewer's own
    author = request.args.get("author", "") or current_user.username
    storage = _storage()
    all_entries = storage.list_entries()

    counts = {}
    for e in all_entries:
        counts[e.get("author", "")] = counts.get(e.get("author", ""), 0) + 1
    users = storage.get_users()
    names = {u["username"]: u.get("full_name", u["username"]) for u in users}
    # every active user has a lab book (even if still empty); disabled users
    # keep a book only if they authored entries
    books = [{"username": u["username"], "full_name": names[u["username"]],
              "count": counts.get(u["username"], 0)}
             for u in users if u.get("active", True) or counts.get(u["username"])]
    for a in sorted(set(counts) - {b["username"] for b in books}):
        books.append({"username": a, "full_name": a, "count": counts[a]})
    books.sort(key=lambda b: b["full_name"].lower())

    entries = all_entries if author == "all" else \
        [e for e in all_entries if e.get("author") == author]
    if status:
        entries = [e for e in entries if e.get("status") == status]
    if q:
        def match(e):
            # Search all entry metadata too, so reaction names, CAS numbers,
            # equipment, attachment captions, and signatures are discoverable.
            hay = json.dumps(e, ensure_ascii=False, default=str).lower()
            if q in hay:
                return True
            _, body = storage.get_entry(e["id"])
            return q in (body or "").lower()
        entries = [e for e in entries if match(e)]

    if author == "all":
        book_title = "All lab books"
    elif author == current_user.username:
        book_title = "My lab book"
    else:
        book_title = "%s's lab book" % names.get(author, author)
    return render_template("entries.html", entries=entries, q=request.args.get("q", ""),
                           status=status, author=author, books=books,
                           book_title=book_title, total=len(all_entries))


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_entry():
    _require_edit()
    storage = _storage()
    if request.method == "POST":
        meta = {
            "title": request.form.get("title", "").strip() or "Untitled experiment",
            "author": current_user.username,
            "project": request.form.get("project", "").strip(),
            "experiment_date": request.form.get("experiment_date", ""),
            "technique": _technique_from_form(request.form, storage),
            "tags": [t.strip() for t in request.form.get("tags", "").split(",") if t.strip()],
            "status": "draft",
            "created": utcnow(),
            "structures": [],
            "attachments": [],
        }
        body = compose_sections(_sections_from_form(request.form))
        eid = storage.create_entry(meta, body)
        storage.audit(eid, current_user.username, "created", meta["title"])
        flash("Entry %s created." % eid, "success")
        return redirect(url_for("entries.view", eid=eid))
    return render_template("entry_form.html", meta=None, sections={},
                           techniques=storage.get_techniques(),
                           section_names=SETUP_SECTIONS)


@bp.route("/<eid>")
@login_required
def view(eid):
    meta, body = _get_or_404(eid)
    storage = _storage()
    sections = parse_sections(body)
    # preview CSV/data attachments
    previews = {}
    for att in meta.get("attachments") or []:
        if att.get("kind") == "data" and att["file"].lower().endswith((".csv", ".tsv")):
            path = os.path.join(storage.entry_dir(eid), att["file"])
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    sample = f.read(65536)
                delim = "\t" if att["file"].lower().endswith(".tsv") else ","
                rows = list(csv.reader(io.StringIO(sample), delimiter=delim))[:15]
                previews[att["file"]] = rows
            except OSError:
                pass
    # reaction components with inline SVGs (namespaced per placement: the same
    # drawing appears in both the scheme strip and its stoichiometry row)
    reaction = meta.get("reaction") or {}
    components = []
    for i, c in enumerate(reaction.get("components") or []):
        c = dict(c)
        c["idx"] = i
        raw_svg = _read_rel(storage, eid, c.get("svg"))
        c["svg_scheme"] = _ns_svg(raw_svg, "sch%d" % i)
        c["svg_row"] = _ns_svg(raw_svg, "row%d" % i)
        components.append(c)
    legacy_obs = sections.get("Observations & Data", "")
    equipment_cfg = ha.load_config(storage)
    ops = meta.get("operations") or {}
    observations = storage.read_observations(eid)
    # one scan of every lab book, shared by the compound library and the
    # cross-reference lookup below (avoids re-reading every entry 2-3x per view)
    all_entries = storage.list_entries()
    # library of previously used starting materials & products (most recent wins)
    compound_library, seen_compounds = [], set()
    if meta.get("status") == "draft":
        for other in all_entries:
            for c in (other.get("reaction") or {}).get("components") or []:
                if not c.get("name") or not c.get("key"):
                    continue
                dedup = (c["name"].strip().lower(), c.get("cas") or "")
                if dedup in seen_compounds:
                    continue
                seen_compounds.add(dedup)
                label = c["name"]
                if c.get("cas"):
                    label += " · " + c["cas"]
                if c.get("role") == "product":
                    label += " (product of %s)" % other["id"]
                compound_library.append({"label": label,
                                         "value": "%s|%s" % (other["id"], c["key"])})
        compound_library.sort(key=lambda x: x["label"].lower())
    # cross-references: ELN ids mentioned here, entries mentioning this one,
    # and the repeat lineage (repeat_of / repeated-by)
    own_text = (body or "") + "\n" + "\n".join(o["text"] for o in observations)
    mentions, referenced_by, repeats = _crossrefs(storage, eid, own_text, all_entries)
    return render_template("entry_view.html", meta=meta, sections=sections,
                           section_names=ENTRY_SECTIONS,
                           previews=previews,
                           audit=storage.read_audit(eid),
                           reaction=reaction, components=components,
                           legacy_obs=legacy_obs,
                           component_roles=COMPONENT_ROLES,
                           component_states=COMPONENT_STATES,
                           equipment_cfg=equipment_cfg,
                           ha_configured=ha.configured(equipment_cfg)
                                         or bool(equipment_cfg.get("ip_cameras")),
                           ops=ops,
                           observations=observations,
                           mentions=mentions, referenced_by=referenced_by,
                           repeats=repeats,
                           compound_library=compound_library,
                           inventory_allocations=meta.get("inventory_allocations") or [],
                           inventory_batches=_inventory_batch_options(storage),
                           inventory_units=UNITS_BY_FAMILY,
                           inventory_transactions=storage.inventory_transactions(eid=eid),
                           recording=ha.recording_status(eid),
                           recording_fps=RECORDING_FPS,
                           recording_resolutions=RECORDING_RESOLUTIONS)


def _read_rel(storage, eid, rel):
    if not rel:
        return ""
    try:
        with open(os.path.join(storage.entry_dir(eid), rel), "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _crossrefs(storage, eid, own_text, all_entries=None):
    """(mentions, referenced_by, repeats) for an entry: ids it names, entries that
    name it, and drafts created as repeats of it. Pass `all_entries` to reuse a
    list the caller already fetched instead of re-scanning every lab book."""
    mentions = sorted({m for m in ELN_ID_RE.findall(own_text) if m != eid})
    referenced_by, repeats = [], []
    for other in (storage.list_entries() if all_entries is None else all_entries):
        oid = other["id"]
        if oid == eid:
            continue
        if other.get("repeat_of") == eid:
            repeats.append(oid)
        _, obody = storage.get_entry(oid)
        text = (obody or "")
        obs_path = os.path.join(storage.entry_dir(oid), "observations.md")
        if os.path.isfile(obs_path):
            with open(obs_path, "r", encoding="utf-8") as f:
                text += f.read()
        if eid in text:
            referenced_by.append(oid)
    return mentions, referenced_by, repeats


@bp.route("/<eid>/print")
@login_required
def print_view(eid):
    """A clean, self-contained, print-optimized document for one entry — the user
    saves it as a PDF via the browser's print dialog. Renders the full record
    (reaction, ops log, results, sign-off, audit trail) with no app chrome."""
    meta, body = _get_or_404(eid)
    storage = _storage()
    sections = parse_sections(body)
    reaction = meta.get("reaction") or {}
    components = []
    for i, c in enumerate(reaction.get("components") or []):
        c = dict(c)
        c["idx"] = i
        raw_svg = _read_rel(storage, eid, c.get("svg"))
        c["svg_scheme"] = _ns_svg(raw_svg, "psch%d" % i)
        components.append(c)
    observations = storage.read_observations(eid)
    ops = meta.get("operations") or {}
    # per-sensor summary: the live plot can't be printed, so distil each logged
    # sensor to count / min / max / last for the latest operations session.
    sensor_summary = []
    for s in storage.read_sensor_series(eid):
        pts = [p for p in (s.get("points") or [])
               if (not ops.get("started_at") or p[0] >= ops["started_at"])
               and (not ops.get("ended_at") or p[0] <= ops["ended_at"])]
        vals = [v for _, v in pts]
        if not vals:
            continue
        sensor_summary.append({
            "label": s.get("label") or s.get("entity"), "unit": s.get("unit", ""),
            "n": len(vals), "min": min(vals), "max": max(vals), "last": vals[-1],
            "first_at": pts[0][0], "last_at": pts[-1][0],
        })
    own_text = (body or "") + "\n" + "\n".join(o["text"] for o in observations)
    mentions, referenced_by, repeats = _crossrefs(storage, eid, own_text)
    return render_template("entry_print.html", meta=meta, sections=sections,
                           section_names=ENTRY_SECTIONS, reaction=reaction,
                           components=components, observations=observations,
                           sensor_summary=sensor_summary,
                           legacy_obs=sections.get("Observations & Data", ""),
                           equipment=meta.get("equipment") or {},
                           ops=ops,
                           ops_history=meta.get("operations_history") or [],
                           audit=storage.read_audit(eid),
                           mentions=mentions, referenced_by=referenced_by,
                           repeats=repeats, generated_at=utcnow(),
                           generated_by=current_user.full_name)


@bp.route("/<eid>/edit", methods=["GET", "POST"])
@login_required
def edit(eid):
    _require_edit()
    meta, body = _get_or_404(eid)
    _require_draft(meta)
    storage = _storage()
    if request.method == "POST":
        meta["title"] = request.form.get("title", "").strip() or meta["title"]
        meta["project"] = request.form.get("project", "").strip()
        meta["experiment_date"] = request.form.get("experiment_date", "")
        meta["technique"] = _technique_from_form(request.form, storage)
        meta.pop("atmosphere", None)
        meta["tags"] = [t.strip() for t in request.form.get("tags", "").split(",") if t.strip()]
        meta["updated"] = utcnow()
        merged = parse_sections(body)      # keep sections not on the setup form
        merged.update(_sections_from_form(request.form))
        body = compose_sections(merged)
        storage.save_entry(eid, meta, body)
        storage.audit(eid, current_user.username, "edited")
        flash("Entry saved.", "success")
        return redirect(url_for("entries.view", eid=eid))
    return render_template("entry_form.html", meta=meta, sections=parse_sections(body),
                           techniques=storage.get_techniques(),
                           section_names=SETUP_SECTIONS)


@bp.route("/<eid>/results", methods=["POST"])
@login_required
def save_results(eid):
    """Results & Conclusions are written on the entry page after the run."""
    _require_edit()
    meta, body = _get_or_404(eid)
    _require_draft(meta)
    storage = _storage()
    sections = parse_sections(body)
    sections["Results & Conclusions"] = request.form.get("results", "")
    meta["updated"] = utcnow()
    storage.save_entry(eid, meta, compose_sections(sections))
    storage.audit(eid, current_user.username, "updated results")
    flash("Results saved.", "success")
    return redirect(url_for("entries.view", eid=eid) + "#results")


@bp.route("/<eid>/repeat", methods=["POST"])
@login_required
def repeat(eid):
    """Create a fresh draft repeating this entry's reaction: setup sections,
    reaction & stoichiometry (with structures), equipment — no results/ops."""
    _require_edit()
    import copy as _copy
    import shutil
    meta, body = _get_or_404(eid)
    storage = _storage()
    sections = parse_sections(body)
    new_meta = {
        "title": meta.get("title", "Untitled"),
        "author": current_user.username,
        "project": meta.get("project", ""),
        "experiment_date": datetime.date.today().isoformat(),
        "technique": meta.get("technique") or meta.get("atmosphere", ""),
        "tags": list(meta.get("tags") or []),
        "status": "draft",
        "created": utcnow(),
        "structures": _copy.deepcopy(meta.get("structures") or []),
        "attachments": [],
        "repeat_of": eid,
    }
    if meta.get("reaction"):
        new_meta["reaction"] = _copy.deepcopy(meta["reaction"])
    if meta.get("equipment"):
        new_meta["equipment"] = _copy.deepcopy(meta["equipment"])
    new_body = compose_sections({"Objective": sections.get("Objective", ""),
                                 "Procedure": sections.get("Procedure", "")})
    new_id = storage.create_entry(new_meta, new_body)
    src = os.path.join(storage.entry_dir(eid), "structures")
    if os.path.isdir(src):
        shutil.copytree(src, os.path.join(storage.entry_dir(new_id), "structures"),
                        dirs_exist_ok=True)
    storage.audit(new_id, current_user.username, "created", "repeat of " + eid)
    storage.audit(eid, current_user.username, "repeated", "as " + new_id)
    flash("Created %s as a repeat of %s." % (new_id, eid), "success")
    return redirect(url_for("entries.view", eid=new_id))


# ---------- attachments ----------

@bp.route("/<eid>/attach", methods=["POST"])
@login_required
def attach(eid):
    _require_edit()
    meta, body = _get_or_404(eid)
    _require_draft(meta)
    storage = _storage()
    files = request.files.getlist("files")
    caption = request.form.get("caption", "").strip()
    added = 0
    att_dir = os.path.join(storage.entry_dir(eid), "attachments")
    os.makedirs(att_dir, exist_ok=True)
    for f in files:
        if not f or not f.filename:
            continue
        name = secure_filename(f.filename)
        if not name:
            continue
        target = os.path.join(att_dir, name)
        base, ext = os.path.splitext(name)
        n = 1
        while os.path.exists(target):
            name = "%s-%d%s" % (base, n, ext)
            target = os.path.join(att_dir, name)
            n += 1
        f.save(target)
        meta.setdefault("attachments", []).append({
            "file": "attachments/" + name,
            "kind": attachment_kind(name),
            "caption": caption,
            "uploaded_by": current_user.username,
            "uploaded_at": utcnow(),
        })
        storage.audit(eid, current_user.username, "attached file", name)
        added += 1
    if added:
        storage.save_entry(eid, meta, body)
        flash("%d file(s) attached." % added, "success")
    else:
        flash("No files selected.", "error")
    return redirect(url_for("entries.view", eid=eid))


@bp.route("/<eid>/attachments/<int:idx>/delete", methods=["POST"])
@login_required
def delete_attachment(eid, idx):
    _require_edit()
    meta, body = _get_or_404(eid)
    _require_draft(meta)
    storage = _storage()
    atts = meta.get("attachments") or []
    if 0 <= idx < len(atts):
        att = atts.pop(idx)
        path = os.path.join(storage.entry_dir(eid), att["file"])
        if os.path.isfile(path):
            os.remove(path)
        storage.save_entry(eid, meta, body)
        storage.audit(eid, current_user.username, "removed attachment", att["file"])
        flash("Attachment removed.", "success")
    return redirect(url_for("entries.view", eid=eid))


@bp.route("/<eid>/files/<path:relpath>")
@login_required
def serve_file(eid, relpath):
    storage = _storage()
    _get_or_404(eid)
    return send_from_directory(storage.entry_dir(eid), relpath)


# ---------- structures ----------

@bp.route("/<eid>/structures/new")
@bp.route("/<eid>/structures/<int:idx>/edit")
@login_required
def edit_structure(eid, idx=None):
    _require_edit()
    meta, _ = _get_or_404(eid)
    _require_draft(meta)
    molfile, caption = "", ""
    if idx is not None:
        structures = meta.get("structures") or []
        if not (0 <= idx < len(structures)):
            abort(404)
        caption = structures[idx].get("caption", "")
        structure = structures[idx]
        preferred = structure.get("ket") or structure.get("file")
        if preferred:
            molfile = _read_rel(_storage(), eid, preferred)
    return render_template("structure_edit.html", idx=idx,
                           subtitle="%s — %s" % (meta["id"], meta.get("title", "")),
                           action_url=url_for("entries.save_structure", eid=eid),
                           cancel_url=url_for("entries.view", eid=eid),
                           molfile=molfile, caption=caption,
                           structure_templates=available_templates(_storage()))


@bp.route("/<eid>/reaction/<int:cidx>/draw")
@login_required
def draw_component(eid, cidx):
    """Structure editor targeting one reaction component."""
    _require_edit()
    meta, _ = _get_or_404(eid)
    _require_draft(meta)
    components = (meta.get("reaction") or {}).get("components") or []
    if not (0 <= cidx < len(components)):
        abort(404)
    comp = components[cidx]
    molfile = ""
    preferred = comp.get("ket") or comp.get("structure")
    if preferred:
        molfile = _read_rel(_storage(), eid, preferred)
    return render_template("structure_edit.html", idx=None,
                           subtitle="%s — %s" % (meta["id"], meta.get("title", "")),
                           action_url=url_for("entries.save_component_structure",
                                              eid=eid, cidx=cidx),
                           cancel_url=url_for("entries.view", eid=eid) + "#reaction",
                           molfile=molfile, caption=comp.get("name", ""),
                           structure_templates=available_templates(_storage()))


@bp.route("/structure-templates", methods=["POST"])
@login_required
def save_structure_template():
    if not current_user.is_admin:
        abort(403)
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    structure = str(payload.get("structure", "")).strip()
    if not name or len(name) > 80:
        return jsonify({"error": "Enter a template name of 80 characters or fewer."}), 400
    if not structure or len(structure.encode("utf-8")) > 1024 * 1024:
        return jsonify({"error": "The template is empty or too large."}), 400
    record = _storage().save_structure_template(name, structure, current_user.username)
    return jsonify({"ok": True, "template": record})


@bp.route("/<eid>/reaction/<int:cidx>/save-structure", methods=["POST"])
@login_required
def save_component_structure(eid, cidx):
    _require_edit()
    meta, body = _get_or_404(eid)
    _require_draft(meta)
    storage = _storage()
    reaction = meta.setdefault("reaction", {})
    components = reaction.setdefault("components", [])
    if not (0 <= cidx < len(components)):
        abort(404)
    comp = components[cidx]
    molfile = request.form.get("molfile", "")
    molfile_v2000 = request.form.get("molfile_v2000", "")
    ket = request.form.get("ket", "")
    if not molfile.strip():
        flash("Nothing to save — the sketcher was empty.", "error")
        return redirect(url_for("entries.view", eid=eid) + "#reaction")

    key = comp.get("key")
    if not key:
        key = reaction.get("next_key", 1)
        reaction["next_key"] = key + 1
        comp["key"] = key
    sdir = os.path.join(storage.entry_dir(eid), "structures")
    os.makedirs(sdir, exist_ok=True)
    base = "comp-%02d" % key
    saved = save_bundle(sdir, base, molfile, molfile_v2000, ket)
    comp["structure"] = "structures/%s.mol" % base
    comp["v2000"] = "structures/%s.v2000.mol" % base if saved["v2000"] else ""
    comp["ket"] = "structures/%s.ket" % base if saved["ket"] else ""
    svg = sanitize_svg(request.form.get("svg", ""))
    if svg.strip():
        with open(os.path.join(sdir, base + ".svg"), "w", encoding="utf-8") as f:
            f.write(svg)
        comp["svg"] = "structures/%s.svg" % base
    comp["smiles"] = request.form.get("smiles", "").strip()
    caption = request.form.get("caption", "").strip()
    if caption and not comp.get("name"):
        comp["name"] = caption

    # compute MW + formula from the drawing; resolve CAS & physical properties
    old_formula = comp.get("formula", "")
    formula, mw = formula_and_mw(molfile)
    changed = bool(formula and old_formula and formula != old_formula)
    if formula:
        comp["formula"] = formula
    if mw and comp.get("mw_auto", True):
        comp["mw"] = mw
    if changed:
        # the drawing is now a different compound — previous identity is stale
        comp["cas"] = ""
        comp["density"] = None
        comp.pop("properties", None)
    if changed:
        prop = storage.properties.lookup(formula=formula)
    else:
        prop = storage.properties.lookup(cas=comp.get("cas"), name=comp.get("name"),
                                         formula=formula)
    if prop:
        if not comp.get("density") and prop.get("density"):
            comp["density"] = prop["density"]
        if not comp.get("cas") and prop.get("cas"):
            comp["cas"] = prop["cas"]
        if prop.get("name") and (not comp.get("name") or changed):
            comp["name"] = prop["name"]
        comp["properties"] = {k: prop[k] for k in ("bp_c", "mp_c") if prop.get(k) is not None}
    if not comp.get("cas"):
        # CAS autofill from the structure itself (PubChem; skipped when offline)
        from .chem import pubchem_lookup
        hit = pubchem_lookup(comp.get("smiles"))
        if hit.get("cas"):
            comp["cas"] = hit["cas"]
            if hit.get("name") and (not comp.get("name") or changed):
                comp["name"] = hit["name"]
            storage.properties.learn({"name": comp.get("name"), "cas": comp["cas"],
                                      "formula": comp.get("formula"), "mw": comp.get("mw")})
    storage.save_entry(eid, meta, body)
    storage.audit(eid, current_user.username, "drew component structure",
                  comp.get("name") or comp.get("smiles", ""))
    flash("Structure saved%s." % (" — MW %.2f g/mol (%s)" % (mw, formula) if mw else ""),
          "success")
    return redirect(url_for("entries.view", eid=eid) + "#reaction")


@bp.route("/<eid>/structures/save", methods=["POST"])
@login_required
def save_structure(eid):
    _require_edit()
    meta, body = _get_or_404(eid)
    _require_draft(meta)
    storage = _storage()
    molfile = request.form.get("molfile", "")
    molfile_v2000 = request.form.get("molfile_v2000", "")
    ket = request.form.get("ket", "")
    if not molfile.strip():
        flash("Nothing to save — the sketcher was empty.", "error")
        return redirect(url_for("entries.view", eid=eid))
    smiles = request.form.get("smiles", "").strip()
    svg = sanitize_svg(request.form.get("svg", ""))
    caption = request.form.get("caption", "").strip()
    idx = request.form.get("idx", "")
    structures = meta.setdefault("structures", [])

    sdir = os.path.join(storage.entry_dir(eid), "structures")
    os.makedirs(sdir, exist_ok=True)
    if idx != "" and idx.isdigit() and int(idx) < len(structures):
        i = int(idx)
        base = os.path.splitext(os.path.basename(structures[i]["file"]))[0]
        action = "edited structure"
    else:
        i = None
        n = len(structures) + 1
        while os.path.exists(os.path.join(sdir, "struct-%02d.mol" % n)):
            n += 1
        base = "struct-%02d" % n
        action = "added structure"

    saved = save_bundle(sdir, base, molfile, molfile_v2000, ket)
    svg_rel = ""
    if svg.strip():
        with open(os.path.join(sdir, base + ".svg"), "w", encoding="utf-8") as f:
            f.write(svg)
        svg_rel = "structures/%s.svg" % base
    record = {"file": "structures/%s.mol" % base,
              "v2000": "structures/%s.v2000.mol" % base if saved["v2000"] else "",
              "ket": "structures/%s.ket" % base if saved["ket"] else "",
              "svg": svg_rel,
              "smiles": smiles, "caption": caption}
    if i is None:
        structures.append(record)
    else:
        structures[i] = record
    storage.save_entry(eid, meta, body)
    storage.audit(eid, current_user.username, action, caption or smiles or base)
    flash("Structure saved.", "success")
    return redirect(url_for("entries.view", eid=eid))


@bp.route("/<eid>/structures/<int:idx>/delete", methods=["POST"])
@login_required
def delete_structure(eid, idx):
    _require_edit()
    meta, body = _get_or_404(eid)
    _require_draft(meta)
    storage = _storage()
    structures = meta.get("structures") or []
    if 0 <= idx < len(structures):
        s = structures.pop(idx)
        base = os.path.splitext(os.path.basename(s.get("file", "structure.mol")))[0]
        remove_bundle(os.path.join(storage.entry_dir(eid), "structures"), base)
        storage.save_entry(eid, meta, body)
        storage.audit(eid, current_user.username, "removed structure", s.get("caption", ""))
        flash("Structure removed.", "success")
    return redirect(url_for("entries.view", eid=eid))


# ---------- sign & witness ----------

@bp.route("/<eid>/sign", methods=["POST"])
@login_required
def sign(eid):
    _require_edit()
    meta, body = _get_or_404(eid)
    storage = _storage()
    if meta.get("status") != "draft":
        flash("Entry is already signed.", "error")
        return redirect(url_for("entries.view", eid=eid))
    ops = meta.get("operations") or {}
    if ops.get("started_at") and not ops.get("ended_at"):
        flash("End lab work before signing the entry.", "error")
        return redirect(url_for("entries.view", eid=eid))
    if _pending_reconciliation(meta):
        flash("Reconcile all deducted inventory before signing the entry.", "error")
        return redirect(url_for("entries.view", eid=eid) + "#inventory-allocation")
    if not _check_password(request.form.get("password")):
        flash("Password confirmation failed — entry not signed.", "error")
        return redirect(url_for("entries.view", eid=eid))
    meta["status"] = "signed"
    meta["signed"] = {"by": current_user.username, "name": current_user.full_name, "at": utcnow()}
    storage.save_entry(eid, meta, body)
    storage.audit(eid, current_user.username, "signed", "content locked")
    flash("Entry signed and locked.", "success")
    return redirect(url_for("entries.view", eid=eid))


@bp.route("/<eid>/witness", methods=["POST"])
@login_required
def witness(eid):
    _require_edit()
    meta, body = _get_or_404(eid)
    storage = _storage()
    if meta.get("status") != "signed":
        flash("Entry must be signed before it can be witnessed.", "error")
        return redirect(url_for("entries.view", eid=eid))
    if (meta.get("signed") or {}).get("by") == current_user.username:
        flash("The witness must be a different person from the signer.", "error")
        return redirect(url_for("entries.view", eid=eid))
    if not _check_password(request.form.get("password")):
        flash("Password confirmation failed — entry not witnessed.", "error")
        return redirect(url_for("entries.view", eid=eid))
    meta["status"] = "witnessed"
    meta["witnessed"] = {"by": current_user.username, "name": current_user.full_name, "at": utcnow()}
    storage.save_entry(eid, meta, body)
    storage.audit(eid, current_user.username, "witnessed")
    flash("Entry witnessed. It is now a permanent record.", "success")
    return redirect(url_for("entries.view", eid=eid))


# ---------- reaction setup & stoichiometry ----------

def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _inventory_batch_options(storage):
    options = []
    for material in storage.list_materials():
        slug = material.get("slug")
        if not slug:
            continue
        for batch in storage.list_batches(slug):
            quantity = batch_quantity(batch)
            options.append({
                "key": "%s|%s" % (slug, batch.get("lot_slug", "")),
                "material": slug, "material_name": material.get("name", slug),
                "lot_slug": batch.get("lot_slug", ""),
                "lot": batch.get("lot", batch.get("lot_slug", "")),
                "status": batch.get("status", ""), "quantity": quantity,
                "units": units_for(quantity["family"]),
                "selectable": quantity["base_value"] > 1e-12
                              and batch.get("status") not in ("Depleted", "Quarantined"),
            })
    options.sort(key=lambda item: (item["material_name"].lower(), item["lot"].lower()))
    return options


def _pending_reconciliation(meta):
    return [a for a in (meta.get("inventory_allocations") or [])
            if a.get("status") == "deducted"]


@bp.route("/<eid>/reaction", methods=["POST"])
@login_required
def save_reaction(eid):
    _require_edit()
    meta, body = _get_or_404(eid)
    _require_draft(meta)
    active_ops = meta.get("operations") or {}
    if active_ops.get("started_at") and not active_ops.get("ended_at"):
        abort(409, description="Reaction setup is locked while lab work is running.")
    storage = _storage()
    form = request.form
    reaction = meta.get("reaction") or {}
    old_by_key = {c.get("key"): c for c in reaction.get("components") or [] if c.get("key")}
    next_key = reaction.get("next_key", 1)

    n = len(form.getlist("comp_name"))
    limiting = form.get("comp_limiting", "")
    components = []
    for i in range(n):
        def g(field, default=""):
            vals = form.getlist("comp_" + field)
            return vals[i].strip() if i < len(vals) else default
        key = int(g("key") or 0)
        if not key:
            key, next_key = next_key, next_key + 1
        old = old_by_key.get(key, {})
        comp = {
            "key": key,
            "role": g("role") if g("role") in COMPONENT_ROLES else "reactant",
            "name": g("name"),
            "cas": g("cas"),
            "formula": g("formula") or old.get("formula", ""),
            "mw": _f(g("mw")),
            "mw_auto": g("mw_auto") == "1",
            "density": _f(g("density")),
            "state": g("state") if g("state") in COMPONENT_STATES else "liquid",
            "conc": _f(g("conc")),
            "equiv": _f(g("equiv")) or 1.0,
            "limiting": str(i) == limiting,
            # computed snapshot from the client (kept so the file reads standalone)
            "mmol": _f(g("mmol")),
            "mass_g": _f(g("mass_g")),
            "volume_ml": _f(g("volume_ml")),
            "volume_unit": g("volume_unit") if g("volume_unit") in ("µL", "mL", "L") else "mL",
            # structure files survive round-trips
            "structure": old.get("structure", ""),
            "v2000": old.get("v2000", ""),
            "ket": old.get("ket", ""),
            "svg": old.get("svg", ""),
            "smiles": old.get("smiles", ""),
        }
        if old.get("properties"):
            comp["properties"] = old["properties"]
        components.append(comp)
        # learn user-entered densities for next time
        if comp["density"] and (comp["cas"] or comp["name"]):
            storage.properties.learn({"name": comp["name"], "cas": comp["cas"],
                                      "formula": comp["formula"], "mw": comp["mw"],
                                      "density": comp["density"]})

    meta["reaction"] = {
        "scale_amount": _f(form.get("scale_amount")),
        "scale_unit": form.get("scale_unit", "g"),
        "components": components,
        "next_key": next_key,
    }
    component_keys = {c["key"] for c in components}
    meta["inventory_allocations"] = [
        a for a in (meta.get("inventory_allocations") or [])
        if a.get("status") != "planned" or a.get("component_key") in component_keys
    ]
    storage.save_entry(eid, meta, body)
    storage.audit(eid, current_user.username, "updated reaction setup",
                  "%d component(s)" % len(components))
    draw = form.get("draw", "")
    if draw.isdigit() and int(draw) < len(components):
        return redirect(url_for("entries.draw_component", eid=eid, cidx=int(draw)))
    flash("Reaction setup saved.", "success")
    return redirect(url_for("entries.view", eid=eid) + "#reaction")


@bp.route("/<eid>/inventory/allocations", methods=["POST"])
@login_required
def save_inventory_allocations(eid):
    _require_edit()
    meta, body = _get_or_404(eid)
    _require_draft(meta)
    ops = meta.get("operations") or {}
    if (ops.get("started_at") and not ops.get("ended_at")) or _pending_reconciliation(meta):
        flash("Inventory allocations are locked until the active work is reconciled.", "error")
        return redirect(url_for("entries.view", eid=eid) + "#inventory-allocation")

    storage = _storage()
    components = {str(c.get("key")): c for c in
                  (meta.get("reaction") or {}).get("components") or []
                  if c.get("role") != "product"}
    batch_options = {item["key"]: item for item in _inventory_batch_options(storage)}
    old_planned = {a.get("id"): a for a in (meta.get("inventory_allocations") or [])
                   if a.get("status") == "planned"}
    ids = request.form.getlist("allocation_id")
    component_keys = request.form.getlist("allocation_component")
    batch_keys = request.form.getlist("allocation_batch")
    quantities = request.form.getlist("allocation_quantity")
    units = request.form.getlist("allocation_unit")
    planned, errors, used_ids = [], [], set()
    totals = {}
    count = max(len(component_keys), len(batch_keys), len(quantities), len(units))
    for i in range(count):
        component_key = component_keys[i].strip() if i < len(component_keys) else ""
        batch_key = batch_keys[i].strip() if i < len(batch_keys) else ""
        value = quantities[i].strip() if i < len(quantities) else ""
        unit = units[i].strip() if i < len(units) else ""
        if not any((component_key, batch_key, value, unit)):
            continue
        component = components.get(component_key)
        option = batch_options.get(batch_key)
        if not component:
            errors.append("Choose a valid non-product reaction component.")
            continue
        if not option or not option["selectable"]:
            errors.append("Choose an available, non-quarantined inventory batch.")
            continue
        try:
            planned_base, base_unit, family = to_base(value, unit)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if planned_base <= 0:
            errors.append("Allocated quantities must be greater than zero.")
            continue
        if family != option["quantity"]["family"]:
            errors.append("%s is not compatible with batch %s."
                          % (unit, option["lot"]))
            continue
        totals[batch_key] = totals.get(batch_key, 0.0) + planned_base
        old_id = ids[i].strip() if i < len(ids) else ""
        allocation_id = (old_id if old_id in old_planned and old_id not in used_ids
                         else uuid.uuid4().hex[:16])
        used_ids.add(allocation_id)
        planned.append({
            "id": allocation_id, "status": "planned",
            "component_key": component.get("key"),
            "component_name": component.get("name") or "Unnamed component",
            "component_role": component.get("role"),
            "material": option["material"], "material_name": option["material_name"],
            "lot_slug": option["lot_slug"], "lot": option["lot"],
            "planned_quantity": float(value), "planned_unit": unit,
            "planned_base": round(planned_base, 12), "base_unit": base_unit,
            "created_at": old_planned.get(allocation_id, {}).get("created_at", utcnow()),
            "created_by": old_planned.get(allocation_id, {}).get(
                "created_by", current_user.username),
        })
    for batch_key, total in totals.items():
        option = batch_options[batch_key]
        if total > option["quantity"]["base_value"] + 1e-9:
            errors.append("Allocations for %s exceed the available %s."
                          % (option["lot"], option["quantity"]["display"]))
    if errors:
        flash(errors[0], "error")
        return redirect(url_for("entries.view", eid=eid) + "#inventory-allocation")

    history = [a for a in (meta.get("inventory_allocations") or [])
               if a.get("status") != "planned"]
    meta["inventory_allocations"] = history + planned
    storage.save_entry(eid, meta, body)
    storage.audit(eid, current_user.username, "updated inventory allocations",
                  "%d planned allocation(s)" % len(planned))
    flash("Inventory allocations saved.", "success")
    return redirect(url_for("entries.view", eid=eid) + "#inventory-allocation")


@bp.route("/<eid>/components/add-known", methods=["POST"])
@login_required
def add_known_component(eid):
    """Copy a previously used component (with its structure) into this reaction."""
    _require_edit()
    import copy as _copy
    import shutil
    meta, body = _get_or_404(eid)
    _require_draft(meta)
    storage = _storage()
    src_id, _, src_key = request.form.get("source", "").partition("|")
    try:
        src_meta, _ = storage.get_entry(src_id)
    except ValueError:
        src_meta = None
    src_comp = None
    if src_meta:
        for c in (src_meta.get("reaction") or {}).get("components") or []:
            if str(c.get("key")) == src_key:
                src_comp = c
                break
    if not src_comp:
        flash("Could not find that compound.", "error")
        return redirect(url_for("entries.view", eid=eid) + "#reaction")

    reaction = meta.setdefault("reaction", {})
    components = reaction.setdefault("components", [])
    comp = _copy.deepcopy(src_comp)
    new_key = reaction.get("next_key", 1)
    reaction["next_key"] = new_key + 1
    comp["key"] = new_key
    comp["limiting"] = not components   # first component becomes the limiting one
    comp["equiv"] = comp.get("equiv") or 1.0
    for field in ("mmol", "mass_g", "volume_ml"):
        comp[field] = None
    # bring the structure files along under this entry's own naming
    if comp.get("structure"):
        src_dir = storage.entry_dir(src_id)
        dst_dir = os.path.join(storage.entry_dir(eid), "structures")
        os.makedirs(dst_dir, exist_ok=True)
        base = "comp-%02d" % new_key
        for attr, ext in (("structure", ".mol"), ("v2000", ".v2000.mol"),
                          ("ket", ".ket"), ("svg", ".svg")):
            rel = comp.get(attr)
            if rel and os.path.isfile(os.path.join(src_dir, rel)):
                shutil.copyfile(os.path.join(src_dir, rel),
                                os.path.join(dst_dir, base + ext))
                comp[attr] = "structures/" + base + ext
            else:
                comp[attr] = ""
    components.append(comp)
    storage.save_entry(eid, meta, body)
    storage.audit(eid, current_user.username, "added component from library",
                  "%s (from %s)" % (comp.get("name", ""), src_id))
    flash("Added %s from %s." % (comp.get("name", "compound"), src_id), "success")
    return redirect(url_for("entries.view", eid=eid) + "#reaction")


@bp.route("/<eid>/properties-lookup")
@login_required
def properties_lookup(eid):
    prop = _storage().properties.lookup(cas=request.args.get("cas"),
                                        name=request.args.get("name"),
                                        formula=request.args.get("formula"))
    return jsonify(prop or {})


# ---------- equipment selection ----------

@bp.route("/<eid>/equipment", methods=["POST"])
@login_required
def save_equipment(eid):
    _require_edit()
    meta, body = _get_or_404(eid)
    _require_draft(meta)
    storage = _storage()
    cfg = ha.load_config(storage)
    hood_name = request.form.get("hood", "")
    hood = ha.find_hood(cfg, hood_name)
    sensors = []
    if hood:
        chosen = set(request.form.getlist("sensors"))
        sensors = [s for s in hood.get("sensors", []) if s["entity"] in chosen]
    fps = request.form.get("rec_fps", "5")
    res = request.form.get("rec_resolution", "1280x720")
    meta["equipment"] = {
        "hood": hood_name if hood else "",
        "camera": request.form.get("camera", ""),
        "sensors": sensors,
        "recording": {"fps": int(fps) if fps.isdigit() else 5,
                      "resolution": res if res in RECORDING_RESOLUTIONS else "1280x720"},
    }
    storage.save_entry(eid, meta, body)
    storage.audit(eid, current_user.username, "updated equipment",
                  "%s / %s / %d sensor(s)" % (hood_name, meta["equipment"]["camera"] or "no camera",
                                              len(sensors)))
    flash("Equipment saved.", "success")
    return redirect(url_for("entries.view", eid=eid) + "#equipment")


# ---------- lab operations: timer, observations, photos, recording, sensors ----------

def _ops_guard(eid, need_started=True):
    _require_edit()
    meta, body = _get_or_404(eid)
    if meta.get("status") != "draft":
        abort(409)
    ops = meta.get("operations") or {}
    if need_started and (not ops.get("started_at") or ops.get("ended_at")):
        abort(409)
    return meta, body, ops


def _deduct_planned_inventory(storage, meta, eid, session):
    planned = [a for a in (meta.get("inventory_allocations") or [])
               if a.get("status") == "planned"]
    totals = {}
    snapshots = {}
    for allocation in planned:
        key = (allocation.get("material"), allocation.get("lot_slug"))
        batch, _ = storage.get_batch(*key)
        if batch is None:
            raise ValueError("Inventory batch %s no longer exists." % allocation.get("lot", ""))
        quantity = batch_quantity(batch)
        if batch.get("status") == "Quarantined":
            raise ValueError("Batch %s is quarantined." % allocation.get("lot", ""))
        if unit_family(quantity["base_unit"]) != unit_family(allocation.get("base_unit")):
            raise ValueError("Batch %s now uses an incompatible inventory unit."
                             % allocation.get("lot", ""))
        snapshots[key] = quantity
        totals[key] = totals.get(key, 0.0) + float(allocation.get("planned_base") or 0)
    for key, total in totals.items():
        if total > snapshots[key]["base_value"] + 1e-9:
            raise ValueError("Insufficient inventory in batch %s."
                             % next(a.get("lot", "") for a in planned
                                    if (a.get("material"), a.get("lot_slug")) == key))

    audit_rows = []
    for allocation in planned:
        amount = float(allocation.get("planned_base") or 0)
        _, transaction = storage.apply_inventory_delta(
            allocation["material"], allocation["lot_slug"], -amount,
            allocation["base_unit"], current_user.username, "experiment deduction",
            preferred_unit=allocation.get("planned_unit"), entry_id=eid,
            allocation_id=allocation["id"], component_key=allocation.get("component_key"),
            component_name=allocation.get("component_name"), session=session,
            detail="Deducted when Actions and Observations started.")
        allocation.update({
            "status": "deducted", "deducted_at": transaction["at"],
            "deducted_by": current_user.username, "deducted_session": session,
            "deduction_transaction": transaction["id"],
        })
        audit_rows.append((allocation, transaction))
    return audit_rows


@bp.route("/<eid>/ops/start", methods=["POST"])
@login_required
def ops_start(eid):
    meta, body, ops = _ops_guard(eid, need_started=False)
    if ops.get("started_at") and not ops.get("ended_at"):
        return redirect(url_for("entries.view", eid=eid))
    storage = _storage()
    restarting = bool(ops.get("started_at") and ops.get("ended_at"))
    history = list(meta.get("operations_history") or [])
    if restarting:
        history.append(dict(ops))
        meta["operations_history"] = history
    session = len(history) + 1
    try:
        inventory_audits = _deduct_planned_inventory(storage, meta, eid, session)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("entries.view", eid=eid) + "#inventory-allocation")
    meta["operations"] = {"started_at": utcnow(), "started_by": current_user.username,
                          "session": session}
    storage.save_entry(eid, meta, body)
    for allocation, transaction in inventory_audits:
        storage.audit(eid, current_user.username, "inventory deducted",
                      "%s · %s · %s · transaction %s" % (
                          allocation.get("component_name"), allocation.get("lot"),
                          transaction.get("delta_display"), transaction.get("id")))
    storage.append_observation(eid, current_user.username, "system",
                               ("**Lab work restarted — session %d.**" % session
                                if restarting else "**Lab work started.**"), "00:00:00")
    storage.audit(eid, current_user.username,
                  "restarted lab work" if restarting else "started lab work",
                  "session %d" % session)
    cfg = ha.load_config(storage)
    sensors = (meta.get("equipment") or {}).get("sensors") or []
    if sensors and ha.configured(cfg):
        ha.start_sensor_logging(storage, cfg, eid, sensors)
    flash(("Actions and Observations restarted — session %d is now running." % session
           if restarting else "Lab work started — observations are now timestamped."), "success")
    return redirect(url_for("entries.view", eid=eid) + "#operations")


@bp.route("/<eid>/ops/end", methods=["POST"])
@login_required
def ops_end(eid):
    meta, _, _ = _ops_guard(eid)
    if _pending_reconciliation(meta):
        flash("Reconcile consumed, recovered, and returned inventory before ending work.",
              "warning")
        return redirect(url_for("entries.inventory_reconcile", eid=eid))
    storage = _storage()
    rec_file = ha.stop_recording(eid)   # blocks while ffmpeg finalizes
    ha.stop_sensor_logging(eid)
    # exempt from the request-wide mutation lock (the ffmpeg join above can
    # take ~45s); serialize only the read-modify-write, like ops_photo
    with storage.mutation_lock():
        meta, body, ops = _ops_guard(eid)
        elapsed = _finish_operations(storage, meta, body, ops, eid, rec_file)
    flash("Lab work ended after %s." % elapsed, "success")
    return redirect(url_for("entries.view", eid=eid) + "#operations")


def _finish_operations(storage, meta, body, ops, eid, rec_file=None):
    if rec_file:
        _register_recording(storage, meta, eid, rec_file)
    elapsed = _elapsed_since(ops.get("started_at"))
    meta["operations"]["ended_at"] = utcnow()
    meta["operations"]["ended_by"] = current_user.username
    storage.save_entry(eid, meta, body)
    storage.append_observation(eid, current_user.username, "system",
                               "**Lab work ended.**", elapsed)
    storage.audit(eid, current_user.username, "ended lab work", "duration " + elapsed)
    return elapsed


def _parse_reconciliation(form, allocations):
    results = []
    for allocation in allocations:
        aid = allocation["id"]
        unit = form.get("unit_" + aid, allocation.get("planned_unit", "g"))
        if unit_family(unit) != unit_family(allocation.get("base_unit")):
            raise ValueError("Choose a unit compatible with %s." % allocation.get("lot", ""))
        values = {}
        for field in ("consumed", "recovered", "returned"):
            raw = form.get("%s_%s" % (field, aid), "")
            try:
                values[field], _, _ = to_base(raw, unit)
            except ValueError:
                raise ValueError("Report consumed, recovered, and returned quantities for %s."
                                 % allocation.get("component_name", "the allocation"))
        deducted = float(allocation.get("planned_base") or 0)
        total = values["consumed"] + values["recovered"] + values["returned"]
        if abs(total - deducted) > max(1e-8, deducted * 1e-6):
            raise ValueError("The reconciliation for %s must total %s."
                             % (allocation.get("component_name", "the allocation"),
                                format_base(deducted, allocation["base_unit"],
                                            allocation.get("planned_unit"))))
        results.append((allocation, unit, values))
    return results


@bp.route("/<eid>/ops/reconcile", methods=["GET", "POST"])
@login_required
def inventory_reconcile(eid):
    meta, body, ops = _ops_guard(eid)
    pending = _pending_reconciliation(meta)
    if not pending:
        flash("There is no inventory awaiting reconciliation.", "warning")
        return redirect(url_for("entries.view", eid=eid) + "#operations")
    storage = _storage()
    if request.method == "GET":
        rows = []
        for allocation in pending:
            row = dict(allocation)
            batch, _ = storage.get_batch(allocation["material"], allocation["lot_slug"])
            row["batch_balance"] = batch_quantity(batch or {})["display"]
            row["units"] = units_for(allocation.get("base_unit"))
            rows.append(row)
        return render_template("inventory_reconcile.html", meta=meta, allocations=rows)
    try:
        _parse_reconciliation(request.form, pending)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("entries.inventory_reconcile", eid=eid))

    rec_file = ha.stop_recording(eid)
    ha.stop_sensor_logging(eid)
    with storage.mutation_lock():
        meta, body, ops = _ops_guard(eid)
        pending = _pending_reconciliation(meta)
        try:
            reconciliations = _parse_reconciliation(request.form, pending)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("entries.inventory_reconcile", eid=eid))
        for allocation, unit, values in reconciliations:
            returned = values["returned"]
            _, transaction = storage.apply_inventory_delta(
                allocation["material"], allocation["lot_slug"], returned,
                allocation["base_unit"], current_user.username,
                "experiment reconciliation", preferred_unit=unit, entry_id=eid,
                allocation_id=allocation["id"], component_key=allocation.get("component_key"),
                component_name=allocation.get("component_name"),
                session=ops.get("session"), consumed_base=round(values["consumed"], 12),
                recovered_base=round(values["recovered"], 12),
                returned_base=round(returned, 12),
                consumed_display=format_base(values["consumed"], allocation["base_unit"], unit),
                recovered_display=format_base(values["recovered"], allocation["base_unit"], unit),
                returned_display=format_base(returned, allocation["base_unit"], unit),
                detail="Consumed %s; recovered %s; returned %s." % (
                    format_base(values["consumed"], allocation["base_unit"], unit),
                    format_base(values["recovered"], allocation["base_unit"], unit),
                    format_base(returned, allocation["base_unit"], unit)))
            allocation.update({
                "status": "reconciled", "reconciled_at": transaction["at"],
                "reconciled_by": current_user.username,
                "reconciliation_unit": unit,
                "consumed_base": round(values["consumed"], 12),
                "recovered_base": round(values["recovered"], 12),
                "returned_base": round(returned, 12),
                "reconciliation_transaction": transaction["id"],
            })
            storage.audit(eid, current_user.username, "inventory reconciled",
                          "%s · %s · consumed %s · recovered %s · returned %s · transaction %s"
                          % (allocation.get("component_name"), allocation.get("lot"),
                             transaction["consumed_display"], transaction["recovered_display"],
                             transaction["returned_display"], transaction["id"]))
        meta["operations"]["inventory_reconciled_at"] = utcnow()
        meta["operations"]["inventory_reconciled_by"] = current_user.username
        elapsed = _finish_operations(storage, meta, body, ops, eid, rec_file)
    flash("Inventory reconciled and lab work ended after %s." % elapsed, "success")
    return redirect(url_for("entries.view", eid=eid) + "#operations")


@bp.route("/<eid>/ops/observe", methods=["POST"])
@login_required
def ops_observe(eid):
    meta, body, ops = _ops_guard(eid)
    text = request.form.get("text", "").strip()
    if not text:
        return jsonify({"ok": False, "error": "Empty observation."}), 400
    storage = _storage()
    elapsed = _elapsed_since(ops.get("started_at"))
    storage.append_observation(eid, current_user.username, "note", text, elapsed)
    storage.audit(eid, current_user.username, "recorded observation", "t+" + elapsed)
    return jsonify({"ok": True, "elapsed": elapsed})


@bp.route("/<eid>/ops/observations")
@login_required
def ops_observations(eid):
    meta, _ = _get_or_404(eid)
    return render_template("_observations.html",
                           observations=_storage().read_observations(eid), meta=meta)


@bp.route("/<eid>/ops/photo", methods=["POST"])
@login_required
def ops_photo(eid):
    meta, body, ops = _ops_guard(eid)
    storage = _storage()
    cfg = ha.load_config(storage)
    camera = (meta.get("equipment") or {}).get("camera")
    if not ha.camera_usable(cfg, camera):
        return jsonify({"ok": False, "error": "No camera configured for this entry."}), 400
    try:
        data, _ctype = ha.camera_snapshot(cfg, storage, camera)
    except requests.RequestException as e:
        return jsonify({"ok": False, "error": "Camera unreachable: %s" % e}), 502
    # Only the reload + file updates need serialization. Camera I/O above must
    # not block unrelated observations, user changes, or notebook saves.
    with storage.mutation_lock():
        meta, body, ops = _ops_guard(eid)
        elapsed = _elapsed_since(ops.get("started_at"))
        stamp = utcnow().replace(":", "").replace("-", "")
        photo_dir = os.path.join(storage.entry_dir(eid), "photos")
        os.makedirs(photo_dir, exist_ok=True)
        name = "photo-%s-%s.jpg" % (stamp, uuid.uuid4().hex[:10])
        with open(os.path.join(photo_dir, name), "wb") as f:
            f.write(data)
        rel = "photos/" + name
        meta.setdefault("attachments", []).append({
            "file": rel, "kind": "image",
            "caption": "Photo from %s at t+%s" % (camera, elapsed),
            "uploaded_by": current_user.username, "uploaded_at": utcnow(),
        })
        storage.save_entry(eid, meta, body)
        storage.append_observation(eid, current_user.username, "photo",
                                   "Photo captured from `%s`: [%s](%s)" %
                                   (camera, name, url_for("entries.serve_file", eid=eid,
                                                          relpath=rel)), elapsed)
        storage.audit(eid, current_user.username, "captured photo", rel)
    return jsonify({"ok": True, "file": rel, "elapsed": elapsed})


def _register_recording(storage, meta, eid, rel):
    """Attach a finished recording file to the entry (meta already loaded)."""
    if os.path.isfile(os.path.join(storage.entry_dir(eid), rel)):
        meta.setdefault("attachments", []).append({
            "file": rel, "kind": "video",
            "caption": "Camera recording",
            "uploaded_by": current_user.username, "uploaded_at": utcnow(),
        })


@bp.route("/<eid>/ops/record/start", methods=["POST"])
@login_required
def ops_record_start(eid):
    meta, body, ops = _ops_guard(eid)
    storage = _storage()
    cfg = ha.load_config(storage)
    equipment = meta.get("equipment") or {}
    camera = equipment.get("camera")
    if not ha.camera_usable(cfg, camera):
        return jsonify({"ok": False, "error": "No camera configured for this entry."}), 400
    rec = equipment.get("recording") or {}
    rel = ha.start_recording(storage, cfg, eid, camera,
                             rec.get("fps", 5), rec.get("resolution", "1280x720"))
    if not rel:
        return jsonify({"ok": False, "error": "Recording already running."}), 409
    elapsed = _elapsed_since(ops.get("started_at"))
    storage.append_observation(eid, current_user.username, "system",
                               "**Recording started** (%s, %s fps, %s)." %
                               (camera, rec.get("fps", 5), rec.get("resolution", "1280x720")),
                               elapsed)
    storage.audit(eid, current_user.username, "started recording", rel)
    return jsonify({"ok": True, "file": rel})


@bp.route("/<eid>/ops/record/stop", methods=["POST"])
@login_required
def ops_record_stop(eid):
    _ops_guard(eid)
    storage = _storage()
    rel = ha.stop_recording(eid)   # blocks while ffmpeg finalizes
    if not rel:
        return jsonify({"ok": False, "error": "No recording running."}), 409
    # exempt from the request-wide mutation lock (stop_recording joins ffmpeg
    # for up to 45s); serialize only the read-modify-write, like ops_photo
    with storage.mutation_lock():
        meta, body, ops = _ops_guard(eid)
        _register_recording(storage, meta, eid, rel)
        storage.save_entry(eid, meta, body)
        elapsed = _elapsed_since(ops.get("started_at"))
        storage.append_observation(eid, current_user.username, "system",
                                   "**Recording stopped**: [%s](%s)" %
                                   (os.path.basename(rel),
                                    url_for("entries.serve_file", eid=eid, relpath=rel)),
                                   elapsed)
        storage.audit(eid, current_user.username, "stopped recording", rel)
    return jsonify({"ok": True, "file": rel})


@bp.route("/<eid>/ops/sensors.json")
@login_required
def ops_sensors(eid):
    meta, _ = _get_or_404(eid)
    ops = meta.get("operations") or {}
    started = ops.get("started_at", "")
    ended = ops.get("ended_at", "")
    series = _storage().read_sensor_series(eid)
    if started:
        for sensor in series:
            sensor["points"] = [p for p in sensor.get("points", [])
                                if p[0] >= started and (not ended or p[0] <= ended)]
    return jsonify({"started": ops.get("started_at", ""),
                    "ended": ops.get("ended_at", ""),
                    "series": series})


@bp.route("/<eid>/reopen", methods=["POST"])
@login_required
def reopen(eid):
    if not current_user.is_admin:
        abort(403)
    meta, body = _get_or_404(eid)
    storage = _storage()
    if meta.get("status") != "signed":
        flash("Only signed (not yet witnessed) entries can be reopened.", "error")
        return redirect(url_for("entries.view", eid=eid))
    meta["status"] = "draft"
    meta.pop("signed", None)
    storage.save_entry(eid, meta, body)
    storage.audit(eid, current_user.username, "reopened", "signature cleared by admin")
    flash("Entry reopened as draft.", "success")
    return redirect(url_for("entries.view", eid=eid))

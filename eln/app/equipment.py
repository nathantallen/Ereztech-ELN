"""Lab equipment settings and authenticated camera snapshots."""
import requests
from flask import (Blueprint, Response, abort, current_app, flash, jsonify,
                   redirect, render_template, request, url_for)
from flask_login import current_user, login_required

from . import ha
from .storage import slugify

bp = Blueprint("equipment", __name__, url_prefix="/equipment")


def _storage():
    return current_app.extensions["storage"]


@bp.route("/", methods=["GET", "POST"])
@login_required
def config_page():
    if not current_user.is_admin:
        abort(403)
    storage = _storage()
    cfg = ha.load_config(storage)
    if request.method == "POST":
        action = request.form.get("action", "save")
        if action == "connection":
            cfg["url"] = request.form.get("url", "").strip()
            token = request.form.get("token", "").strip()
            if token:
                cfg["token"] = token
                cfg["auth_mode"] = "token"
            try:
                poll = int(float(request.form.get("poll_seconds", "5") or 5))
            except (TypeError, ValueError):
                poll = 5
            cfg["poll_seconds"] = max(2, poll)
            ha.save_config(storage, cfg)
            flash("Connection settings saved.", "success")
        elif action == "login":
            url = request.form.get("url", "").strip() or cfg.get("url", "")
            username = request.form.get("ha_username", "").strip()
            password = request.form.get("ha_password", "")
            client_id = request.url_root
            try:
                tok = ha.password_login(url, username, password, client_id)
            except ValueError as e:
                flash(str(e), "error")
                return redirect(url_for("equipment.config_page"))
            import time as _time
            cfg.update({
                "url": url,
                "auth_mode": "login",
                "client_id": client_id,
                "ha_user": username,
                "refresh_token": tok["refresh_token"],
                "access_token": tok["access_token"],
                "access_expires": _time.time() + tok.get("expires_in", 1800),
            })
            ha.save_config(storage, cfg)
            flash("Signed in to Home Assistant as %s. The password was not stored — "
                  "only the session tokens." % username, "success")
        elif action == "signout":
            for k in ("refresh_token", "access_token", "access_expires", "ha_user",
                      "client_id"):
                cfg.pop(k, None)
            cfg["auth_mode"] = "token" if cfg.get("token") else ""
            ha.save_config(storage, cfg)
            flash("Signed out of Home Assistant.", "success")
        elif action == "add_ipcam":
            label = request.form.get("cam_label", "").strip()
            stream_url = request.form.get("cam_stream_url", "").strip()
            snapshot_url = request.form.get("cam_snapshot_url", "").strip()
            username = request.form.get("cam_username", "").strip()
            password = request.form.get("cam_password", "")
            if not label or not (stream_url or snapshot_url):
                flash("An IP camera needs a name and at least one feed URL.", "error")
            else:
                cam_id = "ipcam." + slugify(label)
                n, base = 1, cam_id
                while ha.find_ip_camera(cfg, cam_id):
                    n += 1
                    cam_id = "%s-%d" % (base, n)
                cfg["ip_cameras"].append({"id": cam_id, "label": label,
                                          "stream_url": stream_url,
                                          "snapshot_url": snapshot_url,
                                          "username": username,
                                          "password": password})
                ha.save_config(storage, cfg)
                flash("IP camera added — assign it to a hood below.", "success")
        elif action == "delete_ipcam":
            cam_id = request.form.get("cam_id", "")
            cfg["ip_cameras"] = [c for c in cfg["ip_cameras"] if c.get("id") != cam_id]
            for hood in cfg["hoods"]:
                hood["cameras"] = [c for c in hood.get("cameras", [])
                                   if c.get("entity") != cam_id]
            ha.save_config(storage, cfg)
            flash("IP camera removed.", "success")
        elif action == "add_hood":
            name = request.form.get("hood_name", "").strip()
            if name and not ha.find_hood(cfg, name):
                cfg["hoods"].append({"name": name, "cameras": [], "sensors": []})
                ha.save_config(storage, cfg)
                flash("Hood added.", "success")
        elif action == "delete_hood":
            name = request.form.get("hood_name", "")
            cfg["hoods"] = [h for h in cfg["hoods"] if h.get("name") != name]
            ha.save_config(storage, cfg)
            flash("Hood removed.", "success")
        elif action == "assign":
            hood = ha.find_hood(cfg, request.form.get("hood_name", ""))
            if hood is not None:
                hood["cameras"] = []
                hood["sensors"] = []
                for cam in request.form.getlist("cameras"):
                    entity, _, label = cam.partition("|")
                    hood["cameras"].append({"entity": entity, "label": label or entity})
                for s in request.form.getlist("sensors"):
                    entity, _, rest = s.partition("|")
                    label, _, unit = rest.partition("|")
                    hood["sensors"].append({"entity": entity, "label": label or entity,
                                            "unit": unit})
                custom = request.form.get("custom_sensor", "").strip()
                if custom:
                    label = request.form.get("custom_label", "").strip() or custom
                    unit = request.form.get("custom_unit", "").strip()
                    hood["sensors"].append({"entity": custom, "label": label,
                                            "unit": unit, "kind": "custom"})
                ha.save_config(storage, cfg)
                flash("Hood '%s' updated." % hood["name"], "success")
        return redirect(url_for("equipment.config_page"))

    # Render immediately — do NOT probe Home Assistant here. A configured-but-
    # unreachable HA (e.g. the lab server seen from an off-site machine) would
    # block the whole page for the connect timeout, twice over (token refresh +
    # /api/states). The connection status and HA camera/sensor lists are fetched
    # asynchronously from /equipment/ha-state.json once the page is on screen.
    ip_cameras = [{"entity": c["id"], "label": c.get("label", c["id"]) + " (IP)"}
                  for c in cfg.get("ip_cameras", [])]
    return render_template("equipment.html", cfg=cfg, ip_cameras=ip_cameras,
                           ha_configured=ha.configured(cfg))


@bp.route("/ha-state.json")
@login_required
def ha_state():
    """Async companion to the equipment page: the (possibly slow) Home Assistant
    reachability check + entity listing, kept off the page-render path so the page
    itself never blocks on a dead HA."""
    if not current_user.is_admin:
        abort(403)
    storage = _storage()
    cfg = ha.load_config(storage)
    if not ha.configured(cfg):
        return jsonify({"configured": False, "connected": False,
                        "cameras": [], "sensors": []})
    try:
        states = ha.HAClient(cfg, storage).states(timeout=(3.05, 8))
    except requests.RequestException as e:
        return jsonify({"configured": True, "connected": False, "error": str(e),
                        "cameras": [], "sensors": []})
    cameras, sensors = [], []
    for st in states:
        eid = st.get("entity_id", "")
        attrs = st.get("attributes", {})
        friendly = attrs.get("friendly_name", eid)
        if eid.startswith("camera."):
            cameras.append({"entity": eid, "label": friendly})
        elif eid.startswith("sensor."):
            sensors.append({"entity": eid, "label": friendly,
                            "unit": attrs.get("unit_of_measurement", ""),
                            "state": st.get("state", "")})
    return jsonify({"configured": True, "connected": True,
                    "cameras": cameras, "sensors": sensors})


@bp.route("/snapshot/<entity>")
@login_required
def snapshot(entity):
    cfg = ha.load_config(_storage())
    if not entity.startswith(("camera.", "ipcam.")) or not ha.camera_usable(cfg, entity):
        abort(404)
    try:
        data, ctype = ha.camera_snapshot(cfg, _storage(), entity)
    except requests.RequestException as e:
        # surface the reason (network / auth) so the UI can show why, not a blank
        # box — with URL userinfo masked and newlines stripped (header safety)
        msg = " ".join(ha.scrub_userinfo(str(e)).split())[:200]
        return Response(msg, status=502, headers={"X-Camera-Error": msg})
    resp = Response(data, content_type=ctype)
    resp.headers["Cache-Control"] = "no-store"     # each poll must be a fresh frame
    return resp


@bp.route("/stream/<entity>")
@login_required
def stream(entity):
    cfg = ha.load_config(_storage())
    if not entity.startswith(("camera.", "ipcam.")) or not ha.camera_usable(cfg, entity):
        abort(404)
    # Never hold a Gunicorn worker thread open as an MJPEG relay. With one
    # eight-thread worker, a handful of browser tabs could otherwise starve the
    # complete ELN. Clients deliberately fall back to bounded snapshot polling.
    return Response("Live relay disabled; use snapshot polling.", status=409)

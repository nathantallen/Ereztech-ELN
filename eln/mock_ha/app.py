"""Mock Home Assistant for ELN demos: fake hood cameras (generated JPEG frames)
and sensors (smooth synthetic signals) behind the same REST endpoints the real
Home Assistant exposes. Any bearer token is accepted."""
import datetime
import hashlib
import io
import math
import os
import secrets
import time

from flask import Flask, Response, abort, jsonify, request
from PIL import Image, ImageDraw

app = Flask(__name__)

# --- mock auth (mimics HA's login flow; demo/demo by default) ---
MOCK_USER = os.environ.get("MOCK_USER", "demo")
MOCK_PASS = os.environ.get("MOCK_PASS", "demo")
_FLOWS, _CODES, _REFRESH = set(), set(), set()


@app.route("/auth/login_flow", methods=["POST"])
def login_flow_start():
    fid = secrets.token_hex(8)
    _FLOWS.add(fid)
    return jsonify({"type": "form", "flow_id": fid, "step_id": "init",
                    "handler": ["homeassistant", None],
                    "data_schema": [{"type": "string", "name": "username", "required": True},
                                    {"type": "string", "name": "password", "required": True}],
                    "errors": {}})


@app.route("/auth/login_flow/<fid>", methods=["POST"])
def login_flow_step(fid):
    if fid not in _FLOWS:
        abort(404)
    data = request.get_json(force=True)
    if data.get("username") == MOCK_USER and data.get("password") == MOCK_PASS:
        _FLOWS.discard(fid)
        code = secrets.token_hex(8)
        _CODES.add(code)
        return jsonify({"type": "create_entry", "result": code, "version": 1})
    return jsonify({"type": "form", "flow_id": fid, "step_id": "init",
                    "errors": {"base": "invalid_auth"}})


@app.route("/auth/token", methods=["POST"])
def auth_token():
    grant = request.form.get("grant_type")
    if grant == "authorization_code" and request.form.get("code") in _CODES:
        _CODES.discard(request.form["code"])
        refresh = "mock-refresh-" + secrets.token_hex(8)
        _REFRESH.add(refresh)
        return jsonify({"access_token": "mock-access-" + secrets.token_hex(8),
                        "token_type": "Bearer", "refresh_token": refresh,
                        "expires_in": 1800})
    if grant == "refresh_token" and request.form.get("refresh_token") in _REFRESH:
        return jsonify({"access_token": "mock-access-" + secrets.token_hex(8),
                        "token_type": "Bearer", "expires_in": 1800})
    return jsonify({"error": "invalid_grant"}), 400

SENSORS = {
    "sensor.hood1_temp": {"friendly_name": "Hood 1 bath temperature",
                          "unit_of_measurement": "°C", "device_class": "temperature",
                          "base": 55.0, "amp": 6.0, "period": 480},
    "sensor.hood1_pressure": {"friendly_name": "Hood 1 line pressure",
                              "unit_of_measurement": "torr", "device_class": "pressure",
                              "base": 12.0, "amp": 0.8, "period": 300},
    "sensor.hood2_temp": {"friendly_name": "Hood 2 bath temperature",
                          "unit_of_measurement": "°C", "device_class": "temperature",
                          "base": 24.0, "amp": 3.0, "period": 600},
    "sensor.hood2_o2": {"friendly_name": "Hood 2 glovebox O2",
                        "unit_of_measurement": "ppm", "device_class": None,
                        "base": 0.5, "amp": 0.15, "period": 240},
}
CAMERAS = {
    "camera.hood1_overhead": "Hood 1 overhead",
    "camera.hood2_overhead": "Hood 2 overhead",
}


def _auth():
    if not request.headers.get("Authorization", "").startswith("Bearer "):
        abort(401)


def _sensor_value(entity):
    s = SENSORS[entity]
    t = time.time()
    return round(s["base"] + s["amp"] * math.sin(2 * math.pi * t / s["period"])
                 + 0.15 * s["amp"] * math.sin(t / 7.3), 3)


def _frame(entity):
    img = Image.new("RGB", (640, 480), (15, 0, 55))
    d = ImageDraw.Draw(img)
    label = CAMERAS.get(entity, entity)
    now = datetime.datetime.now().strftime("%H:%M:%S")
    d.rectangle([0, 0, 640, 46], fill=(4, 25, 78))
    d.text((14, 14), "%s   %s" % (label, now), fill=(247, 148, 30))
    # crude animated "flask": stirring vortex circle
    t = time.time()
    cx = 320 + int(90 * math.sin(t / 2.0))
    cy = 300 + int(30 * math.cos(t / 1.3))
    d.ellipse([200, 180, 440, 420], outline=(218, 208, 236), width=4)
    d.ellipse([cx - 26, cy - 26, cx + 26, cy + 26], fill=(247, 148, 30))
    d.text((14, 452), "MOCK CAMERA FEED", fill=(218, 208, 236))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


@app.route("/api/")
def api_root():
    _auth()
    return jsonify({"message": "API running."})


@app.route("/api/states")
def states():
    _auth()
    out = []
    for entity, s in SENSORS.items():
        out.append({"entity_id": entity, "state": str(_sensor_value(entity)),
                    "attributes": {k: s[k] for k in
                                   ("friendly_name", "unit_of_measurement", "device_class")}})
    for entity, name in CAMERAS.items():
        out.append({"entity_id": entity, "state": "streaming",
                    "attributes": {"friendly_name": name}})
    return jsonify(out)


@app.route("/api/states/<entity>")
def state(entity):
    _auth()
    if entity in SENSORS:
        s = SENSORS[entity]
        return jsonify({"entity_id": entity, "state": str(_sensor_value(entity)),
                        "attributes": {"friendly_name": s["friendly_name"],
                                       "unit_of_measurement": s["unit_of_measurement"]}})
    if entity in CAMERAS:
        return jsonify({"entity_id": entity, "state": "streaming",
                        "attributes": {"friendly_name": CAMERAS[entity]}})
    abort(404)


@app.route("/api/camera_proxy/<entity>")
def camera_proxy(entity):
    _auth()
    if entity not in CAMERAS:
        abort(404)
    return Response(_frame(entity), content_type="image/jpeg")


@app.route("/api/camera_proxy_stream/<entity>")
def camera_stream(entity):
    _auth()
    if entity not in CAMERAS:
        abort(404)

    def gen():
        while True:
            frame = _frame(entity)
            yield (b"--frameboundary\r\nContent-Type: image/jpeg\r\n"
                   b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n" +
                   frame + b"\r\n")
            time.sleep(0.5)

    return Response(gen(), content_type="multipart/x-mixed-replace; boundary=frameboundary")


# --- plain IP-camera style endpoints (no auth), for testing direct feeds ---

@app.route("/ipcam/snapshot.jpg")
def ipcam_snapshot():
    return Response(_frame("camera.hood2_overhead"), content_type="image/jpeg")


@app.route("/ipcam/stream")
def ipcam_stream():
    def gen():
        while True:
            frame = _frame("camera.hood2_overhead")
            yield (b"--frameboundary\r\nContent-Type: image/jpeg\r\n"
                   b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n" +
                   frame + b"\r\n")
            time.sleep(0.5)
    return Response(gen(), content_type="multipart/x-mixed-replace; boundary=frameboundary")


# --- Amcrest-style camera with HTTP DIGEST auth (mimics a real IP camera) ---
CAM_USER = os.environ.get("MOCK_CAM_USER", "cam_user")
CAM_PASS = os.environ.get("MOCK_CAM_PASS", "cam_pass")
_REALM = "Login to CAMERA"
_NONCE = secrets.token_hex(16)


def _digest_ok():
    """Validate an RFC-2617 Digest (qop=auth, MD5) Authorization header the way
    a real Amcrest/Dahua camera does. Returns True on a correct response."""
    hdr = request.headers.get("Authorization", "")
    if not hdr.startswith("Digest "):
        return False
    parts = {}
    for item in hdr[len("Digest "):].split(","):
        if "=" in item:
            k, v = item.strip().split("=", 1)
            parts[k] = v.strip().strip('"')
    if parts.get("username") != CAM_USER:
        return False
    ha1 = hashlib.md5(("%s:%s:%s" % (CAM_USER, _REALM, CAM_PASS)).encode()).hexdigest()
    ha2 = hashlib.md5(("%s:%s" % (request.method, parts.get("uri", ""))).encode()).hexdigest()
    if parts.get("qop"):
        expect = hashlib.md5(":".join([ha1, parts.get("nonce", ""), parts.get("nc", ""),
                                       parts.get("cnonce", ""), parts["qop"], ha2]).encode()).hexdigest()
    else:
        expect = hashlib.md5(("%s:%s:%s" % (ha1, parts.get("nonce", ""), ha2)).encode()).hexdigest()
    return parts.get("response") == expect


def _digest_challenge():
    chal = 'Digest realm="%s", qop="auth", nonce="%s", opaque="0"' % (_REALM, _NONCE)
    return Response("401 Unauthorized", status=401,
                    headers={"WWW-Authenticate": chal})


@app.route("/cgi-bin/snapshot.cgi")
def amcrest_snapshot():
    if not _digest_ok():
        return _digest_challenge()
    return Response(_frame("camera.amcrest"), content_type="image/jpeg")


@app.route("/cgi-bin/mjpg/video.cgi")
def amcrest_mjpeg():
    if not _digest_ok():
        return _digest_challenge()

    def gen():
        for _ in range(600):        # ~5 min at 2 fps, then the client reconnects
            frame = _frame("camera.amcrest")
            yield (b"--myboundary\r\nContent-Type: image/jpeg\r\n"
                   b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n" +
                   frame + b"\r\n")
            time.sleep(0.5)
    return Response(gen(), content_type="multipart/x-mixed-replace; boundary=myboundary")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8123, threaded=True)

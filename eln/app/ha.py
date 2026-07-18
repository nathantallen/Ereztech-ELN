"""Home Assistant integration: equipment config (cameras & sensors grouped by
lab hood), REST client, per-entry background sensor loggers, and a camera
recorder that polls snapshots and pipes them to ffmpeg.

Config lives in <data>/equipment.json so it travels with the notebook:
{
  "url": "http://homeassistant.local:8123",
  "token": "<long-lived access token>",
  "poll_seconds": 5,
  "hoods": [
    {"name": "Hood 1",
     "cameras": [{"entity": "camera.hood1_overhead", "label": "Overhead"}],
     "sensors": [{"entity": "sensor.hood1_temp", "label": "Bath temperature",
                  "unit": "°C", "kind": "temperature"}]}
  ]
}
"""
import datetime
import json
import os
import subprocess
import threading
import time
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth


def load_config(storage):
    path = os.path.join(storage.root, "equipment.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = {}
    cfg.setdefault("url", os.environ.get("ELN_HA_URL", ""))
    cfg.setdefault("token", os.environ.get("ELN_HA_TOKEN", ""))
    cfg.setdefault("poll_seconds", 5)
    cfg.setdefault("hoods", [])
    cfg.setdefault("ip_cameras", [])
    return cfg


# serialises writers of equipment.json (admin edits + the background token
# refresh) so one never clobbers another's just-written copy
_config_lock = threading.RLock()


def save_config(storage, cfg):
    path = os.path.join(storage.root, "equipment.json")
    with _config_lock:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)


def configured(cfg):
    if not cfg.get("url"):
        return False
    if cfg.get("auth_mode") == "login":
        return bool(cfg.get("refresh_token"))
    return bool(cfg.get("token"))


# ---------- username/password auth (Home Assistant login flow) ----------
# The password is exchanged once for refresh + access tokens and never stored.

_token_lock = threading.Lock()


def password_login(url, username, password, client_id):
    """Run HA's login flow; returns the /auth/token response dict.
    Raises ValueError with a human-readable message on failure."""
    url = url.rstrip("/")
    try:
        r = requests.post(url + "/auth/login_flow", json={
            "client_id": client_id,
            "handler": ["homeassistant", None],
            "redirect_uri": client_id.rstrip("/") + "/?auth_callback=1",
        }, timeout=10)
        r.raise_for_status()
        flow = r.json()
        r = requests.post(url + "/auth/login_flow/" + flow["flow_id"], json={
            "username": username, "password": password, "client_id": client_id,
        }, timeout=10)
        r.raise_for_status()
        step = r.json()
    except requests.RequestException as e:
        raise ValueError("Could not reach Home Assistant: %s" % e)
    if step.get("type") != "create_entry":
        if (step.get("errors") or {}).get("base") == "invalid_auth":
            raise ValueError("Home Assistant rejected the username or password.")
        raise ValueError("Login needs an unsupported step (multi-factor auth?). "
                         "Use a long-lived token instead.")
    try:
        r = requests.post(url + "/auth/token", data={
            "grant_type": "authorization_code",
            "code": step["result"],
            "client_id": client_id,
        }, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise ValueError("Token exchange failed: %s" % e)


def access_token(storage):
    """Current bearer token. In login mode, refreshes the short-lived access
    token via the stored refresh token when it is about to expire."""
    cfg = load_config(storage)
    if cfg.get("auth_mode") != "login":
        return cfg.get("token", "")
    with _token_lock:
        cfg = load_config(storage)
        if cfg.get("access_token") and cfg.get("access_expires", 0) > time.time() + 60:
            return cfg["access_token"]
        try:
            r = requests.post(cfg["url"].rstrip("/") + "/auth/token", data={
                "grant_type": "refresh_token",
                "refresh_token": cfg.get("refresh_token", ""),
                "client_id": cfg.get("client_id", ""),
            }, timeout=(3.05, 8))   # short connect: never hang the caller on a dead HA
            r.raise_for_status()
            tok = r.json()
        except requests.RequestException:
            return cfg.get("access_token", "")   # let the API call fail loudly
        new_access = tok.get("access_token")
        if not new_access:
            # a 2xx with no token (misconfigured proxy?) — keep the old one and
            # let the actual API call surface the failure rather than KeyError here
            return cfg.get("access_token", "")
        expires = time.time() + tok.get("expires_in", 1800)
        # merge the new token onto the FRESHEST config (re-read under the lock) so
        # an admin edit that landed during the refresh isn't overwritten
        with _config_lock:
            latest = load_config(storage)
            latest["access_token"] = new_access
            latest["access_expires"] = expires
            save_config(storage, latest)
        return new_access


def find_hood(cfg, name):
    for h in cfg.get("hoods", []):
        if h.get("name") == name:
            return h
    return None


# ---------- IP cameras (direct MJPEG/JPEG feeds, no Home Assistant needed) ----------

def find_ip_camera(cfg, entity):
    for c in cfg.get("ip_cameras", []):
        if c.get("id") == entity:
            return c
    return None


def camera_usable(cfg, entity):
    """A camera works if it's a configured IP feed, or HA is connected."""
    if not entity:
        return False
    if entity.startswith("ipcam."):
        return find_ip_camera(cfg, entity) is not None
    return configured(cfg)


def _split_creds(url):
    """Pull userinfo out of a URL. Returns (clean_url, (user, pass)|None). IP
    cameras (Amcrest etc.) embed credentials as http://user:pass@host/... but
    need proper Digest/Basic auth, not just the raw URL."""
    p = urlsplit(url)
    if p.username:
        netloc = p.hostname + (":%d" % p.port if p.port else "")
        clean = urlunsplit((p.scheme, netloc, p.path, p.query, p.fragment))
        return clean, (unquote(p.username), unquote(p.password or ""))
    return url, None


def _cam_http_get(url, stream=False, timeout=15, username="", password=""):
    """GET an http(s) camera URL. If it carries credentials, try Digest first
    (Amcrest, Dahua, Hikvision, Axis all use Digest), then fall back to Basic."""
    clean, creds = _split_creds(url)
    if username:
        creds = (username, password or "")
    if not creds:
        return requests.get(clean, stream=stream, timeout=timeout)
    r = requests.get(clean, auth=HTTPDigestAuth(*creds), stream=stream, timeout=timeout)
    if r.status_code in (401, 403):
        r.close()
        r = requests.get(clean, auth=HTTPBasicAuth(*creds), stream=stream, timeout=timeout)
    return r


def _mjpeg_first_frame(url, timeout=10, username="", password=""):
    """Pull a single JPEG frame out of an MJPEG (multipart) HTTP stream."""
    r = _cam_http_get(url, stream=True, timeout=timeout,
                      username=username, password=password)
    r.raise_for_status()
    buf = b""
    try:
        for chunk in r.iter_content(8192):
            buf += chunk
            start = buf.find(b"\xff\xd8")
            if start >= 0:
                end = buf.find(b"\xff\xd9", start + 2)
                if end >= 0:
                    return buf[start:end + 2]
            if len(buf) > 5_000_000:
                break
    finally:
        r.close()
    raise requests.RequestException("no JPEG frame found in stream")


def _ffmpeg_grab(url, timeout=20):
    """Grab a single JPEG frame from an RTSP (or any ffmpeg-readable) URL."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp",
           "-i", url, "-frames:v", "1", "-f", "image2", "-"]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise requests.RequestException("camera did not respond (rtsp timeout)")
    if out.returncode != 0 or not out.stdout:
        raise requests.RequestException(
            "ffmpeg could not read the camera: " + (out.stderr[-200:].decode("utf-8", "replace")))
    return out.stdout


def _url_with_creds(url, username="", password=""):
    """Add separately stored credentials to a URL for tools such as ffmpeg.
    Existing userinfo URLs remain supported for older camera records."""
    if not username or not url:
        return url
    p = urlsplit(url)
    host = p.hostname or ""
    if p.port:
        host += ":%d" % p.port
    userinfo = "%s:%s@" % (quote(username, safe=""), quote(password or "", safe=""))
    return urlunsplit((p.scheme, userinfo + host, p.path, p.query, p.fragment))


def _is_http(url):
    return bool(url) and url.lower().startswith(("http://", "https://"))


def _is_rtsp(url):
    return bool(url) and url.lower().startswith("rtsp://")


def camera_snapshot(cfg, storage, entity):
    """One still frame from either an IP camera or an HA camera."""
    cam = find_ip_camera(cfg, entity)
    if cam:
        username = cam.get("username", "")
        password = cam.get("password", "")
        snap = cam.get("snapshot_url", "")
        if _is_http(snap):                        # Amcrest CGI snapshot (Digest)
            r = _cam_http_get(snap, timeout=15, username=username, password=password)
            r.raise_for_status()
            return r.content, r.headers.get("Content-Type", "image/jpeg")
        stream = cam.get("stream_url", "")
        if _is_rtsp(stream):                      # grab a frame off the RTSP feed
            return _ffmpeg_grab(_url_with_creds(stream, username, password)), "image/jpeg"
        if _is_http(stream):                      # pull one frame from HTTP MJPEG
            return _mjpeg_first_frame(stream, username=username, password=password), "image/jpeg"
        raise requests.RequestException("camera has no usable snapshot source")
    return HAClient(cfg, storage).snapshot(entity)


def camera_stream(cfg, storage, entity):
    """Live MJPEG stream for the browser. Returns a requests streaming Response
    for HTTP(S) sources, or None when there is no browser-displayable stream
    (e.g. RTSP) — callers fall back to polling snapshots."""
    cam = find_ip_camera(cfg, entity)
    if cam:
        stream = cam.get("stream_url", "")
        if _is_http(stream):
            return _cam_http_get(stream, stream=True, timeout=15,
                                 username=cam.get("username", ""),
                                 password=cam.get("password", ""))
        return None                               # RTSP / snapshot-only → poll snapshots
    return HAClient(cfg, storage).stream(entity)


class HAClient:
    def __init__(self, cfg, storage=None):
        self.url = cfg.get("url", "").rstrip("/")
        self.cfg = cfg
        self.storage = storage

    @property
    def headers(self):
        if self.cfg.get("auth_mode") == "login" and self.storage is not None:
            return {"Authorization": "Bearer " + access_token(self.storage)}
        return {"Authorization": "Bearer " + self.cfg.get("token", "")}

    def ping(self):
        try:
            r = requests.get(self.url + "/api/", headers=self.headers, timeout=5)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def states(self, timeout=10):
        r = requests.get(self.url + "/api/states", headers=self.headers, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def state(self, entity):
        r = requests.get(self.url + "/api/states/" + entity, headers=self.headers, timeout=10)
        r.raise_for_status()
        return r.json()

    def snapshot(self, entity):
        r = requests.get(self.url + "/api/camera_proxy/" + entity,
                         headers=self.headers, timeout=15)
        r.raise_for_status()
        return r.content, r.headers.get("Content-Type", "image/jpeg")

    def stream(self, entity):
        return requests.get(self.url + "/api/camera_proxy_stream/" + entity,
                            headers=self.headers, stream=True, timeout=15)


# ---------- background sensor loggers (one thread per running entry) ----------

_pollers = {}   # eid -> {"stop": Event, "thread": Thread}
_pollers_lock = threading.Lock()


def _poll_loop(storage, cfg, eid, sensors, stop):
    client = HAClient(cfg, storage)
    interval = max(2, int(cfg.get("poll_seconds", 5)))
    while not stop.wait(interval):
        for s in sensors:
            try:
                state = client.state(s["entity"])
                value = state.get("state")
                float(value)  # skip 'unavailable' / non-numeric states
            except (requests.RequestException, TypeError, ValueError):
                continue
            try:
                storage.append_sensor_point(eid, s["entity"], s.get("label", s["entity"]),
                                            s.get("unit", ""), value)
            except OSError:
                pass


def start_sensor_logging(storage, cfg, eid, sensors):
    if not configured(cfg) or not sensors:
        return False
    with _pollers_lock:
        if eid in _pollers:
            return True
        stop = threading.Event()
        t = threading.Thread(target=_poll_loop, args=(storage, cfg, eid, sensors, stop),
                             daemon=True, name="sensorlog-" + eid)
        _pollers[eid] = {"stop": stop, "thread": t}
        t.start()
    return True


def stop_sensor_logging(eid):
    with _pollers_lock:
        entry = _pollers.pop(eid, None)
    if entry:
        entry["stop"].set()


def resume_pollers(storage):
    """Restart loggers for entries that were mid-run when the container stopped."""
    cfg = load_config(storage)
    if not configured(cfg):
        return
    for meta in storage.list_entries():
        ops = meta.get("operations") or {}
        if ops.get("started_at") and not ops.get("ended_at"):
            sensors = (meta.get("equipment") or {}).get("sensors") or []
            if sensors:
                start_sensor_logging(storage, cfg, meta["id"], sensors)


def background_active():
    """True if any sensor poller or camera recording is currently running."""
    with _pollers_lock:
        pollers = bool(_pollers)
    with _rec_lock:
        recs = bool(_recordings)
    return pollers or recs


def stop_all():
    """Stop every background poller and recording — used when the data store is
    being re-pointed so nothing keeps writing to the old location. Threads are
    JOINED (not just signalled) so no in-flight write lands after the caller
    proceeds to copy/rebind."""
    with _pollers_lock:
        entries = list(_pollers.values())
        _pollers.clear()
    for e in entries:
        e["stop"].set()
    for e in entries:
        e["thread"].join(timeout=15)
    with _rec_lock:
        recs = list(_recordings.values())
        _recordings.clear()
    for rec in recs:
        rec["stop"].set()
        rec["thread"].join(timeout=45)


# ---------- camera recording (snapshot poll -> ffmpeg image2pipe) ----------

_recordings = {}   # eid -> {'stop': Event, 'thread': Thread, 'file': relpath, 'started': iso}
_rec_lock = threading.Lock()


def _scale_args(resolution):
    if resolution and resolution != "original":
        w, h = resolution.split("x")
        return ["-vf", "scale=%s:%s" % (w, h)]
    return []


def _record_rtsp(url, fps, resolution, outfile, stop):
    """Record an RTSP feed straight to mp4 with ffmpeg (efficient, no polling)."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-rtsp_transport", "tcp", "-i", url, "-r", str(fps)] + _scale_args(resolution) + \
          ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
           "-movflags", "+faststart", outfile]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    stop.wait()                       # block until asked to stop
    try:
        proc.communicate(b"q", timeout=10)   # 'q' → ffmpeg finalises the moov atom
    except (subprocess.TimeoutExpired, OSError, ValueError):
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _record_snapshots(storage, cfg, eid, camera, fps, resolution, outfile, stop):
    """Record by polling still frames and piping them to ffmpeg — used for
    snapshot-only / HTTP cameras and HA camera entities."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "image2pipe", "-framerate", str(fps), "-i", "-"] + _scale_args(resolution) + \
          ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
           "-movflags", "+faststart", outfile]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    interval = 1.0 / max(0.2, float(fps))
    try:
        while not stop.is_set():
            t0 = time.monotonic()
            try:
                frame, _ = camera_snapshot(cfg, storage, camera)
                proc.stdin.write(frame)
            except (requests.RequestException, BrokenPipeError, OSError):
                pass
            delay = interval - (time.monotonic() - t0)
            if delay > 0:
                stop.wait(delay)
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()


def _record_loop(storage, cfg, eid, camera, fps, resolution, outfile, stop):
    cam = find_ip_camera(cfg, camera)
    if cam and _is_rtsp(cam.get("stream_url", "")):
        stream_url = _url_with_creds(cam["stream_url"], cam.get("username", ""),
                                     cam.get("password", ""))
        _record_rtsp(stream_url, fps, resolution, outfile, stop)
    else:
        _record_snapshots(storage, cfg, eid, camera, fps, resolution, outfile, stop)


def start_recording(storage, cfg, eid, camera, fps, resolution):
    with _rec_lock:
        if eid in _recordings:
            return None
        rec_dir = os.path.join(storage.entry_dir(eid), "recordings")
        os.makedirs(rec_dir, exist_ok=True)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
        rel = "recordings/rec-%s.mp4" % stamp
        stop = threading.Event()
        t = threading.Thread(target=_record_loop,
                             args=(storage, cfg, eid, camera, fps, resolution,
                                   os.path.join(storage.entry_dir(eid), rel), stop),
                             daemon=True, name="record-" + eid)
        _recordings[eid] = {"stop": stop, "thread": t, "file": rel,
                            "camera": camera}
        t.start()
        return rel


def stop_recording(eid):
    with _rec_lock:
        rec = _recordings.pop(eid, None)
    if not rec:
        return None
    rec["stop"].set()
    rec["thread"].join(timeout=45)
    return rec["file"]


def recording_status(eid):
    with _rec_lock:
        rec = _recordings.get(eid)
        return {"active": bool(rec), "file": rec["file"] if rec else None}

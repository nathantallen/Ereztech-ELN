// Equipment config page: load the Home Assistant connection status and the
// available HA cameras/sensors ASYNCHRONOUSLY, so the page itself never blocks
// on a slow/unreachable HA. Already-assigned equipment is rendered server-side
// (checked) — this only adds the not-yet-assigned HA entities as options.
(function () {
  "use strict";

  var statusEl = document.getElementById("ha-status");
  var errorEl = document.getElementById("ha-error");

  function initCameraPresets() {
    var preset = document.getElementById("cam-preset");
    var host = document.getElementById("cam-host");
    var channel = document.getElementById("cam-channel");
    var subtype = document.getElementById("cam-subtype");
    var stream = document.getElementById("cam-stream-url");
    var snapshot = document.getElementById("cam-snapshot-url");
    var apply = document.getElementById("apply-camera-preset");
    var hint = document.getElementById("camera-preset-hint");
    if (!preset || !host || !channel || !subtype || !stream || !snapshot || !apply) return;

    function cleanHost(value) {
      return (value || "").trim()
        .replace(/^[a-z]+:\/\//i, "")
        .replace(/\/.*$/, "")
        .replace(/\/$/, "");
    }

    function applyPreset() {
      var cameraHost = cleanHost(host.value);
      var cameraChannel = Math.max(1, parseInt(channel.value, 10) || 1);
      var cameraSubtype = subtype.value === "0" ? "0" : "1";
      if (preset.value === "manual") {
        hint.textContent = "Enter the stream and snapshot URLs manually below.";
        stream.focus();
        return;
      }
      if (!cameraHost) {
        hint.textContent = "Enter the camera IP address or hostname first.";
        host.focus();
        return;
      }

      var streamUrl = "", snapshotUrl = "";
      if (preset.value === "amcrest-http") {
        streamUrl = "http://" + cameraHost + "/cgi-bin/mjpg/video.cgi?channel=" +
          cameraChannel + "&subtype=" + cameraSubtype;
        snapshotUrl = "http://" + cameraHost + "/cgi-bin/snapshot.cgi?channel=" + cameraChannel;
      } else if (preset.value === "amcrest-rtsp") {
        streamUrl = "rtsp://" + cameraHost + ":554/cam/realmonitor?channel=" +
          cameraChannel + "&subtype=" + cameraSubtype;
        snapshotUrl = "http://" + cameraHost + "/cgi-bin/snapshot.cgi?channel=" + cameraChannel;
      } else if (preset.value === "hikvision-rtsp") {
        var hikChannel = String(cameraChannel) + (cameraSubtype === "0" ? "01" : "02");
        streamUrl = "rtsp://" + cameraHost + ":554/Streaming/Channels/" + hikChannel;
        snapshotUrl = "http://" + cameraHost + "/ISAPI/Streaming/channels/" + hikChannel + "/picture";
      } else if (preset.value === "axis-http") {
        streamUrl = "http://" + cameraHost + "/axis-cgi/mjpg/video.cgi?resolution=1280x720";
        snapshotUrl = "http://" + cameraHost + "/axis-cgi/jpg/image.cgi";
      } else if (preset.value === "generic-http") {
        streamUrl = "http://" + cameraHost + "/mjpeg";
        snapshotUrl = "http://" + cameraHost + "/snapshot.jpg";
      } else if (preset.value === "generic-rtsp") {
        streamUrl = "rtsp://" + cameraHost + ":554/stream1";
      }
      stream.value = streamUrl;
      snapshot.value = snapshotUrl;
      hint.textContent = "Preset applied. You can edit either URL before adding the camera.";
    }

    apply.addEventListener("click", applyPreset);
    preset.addEventListener("change", function () {
      hint.textContent = preset.value === "manual"
        ? "Enter the stream and snapshot URLs manually below."
        : "Enter the camera address, then apply the preset URLs.";
    });
    host.addEventListener("keydown", function (event) {
      if (event.key === "Enter") { event.preventDefault(); applyPreset(); }
    });
  }

  initCameraPresets();

  function setStatus(text, color) {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.style.background = color;
  }

  if (!window.ELN_HA_CONFIGURED) {
    setStatus("not connected", "var(--hold)");
    return;
  }

  function makeCheck(name, value, label, meta) {
    var l = document.createElement("label");
    l.className = "check-label";
    l.style.marginTop = "6px";
    var cb = document.createElement("input");
    cb.type = "checkbox";
    cb.name = name;
    cb.value = value;
    l.appendChild(cb);
    l.appendChild(document.createTextNode(" " + label + " "));
    var span = document.createElement("span");
    span.className = "mono muted small";
    span.textContent = meta;
    l.appendChild(span);
    return l;
  }

  function csv(el, attr) {
    return (el.getAttribute(attr) || "").split(",").filter(Boolean);
  }

  fetch("/equipment/ha-state.json", {headers: {"Accept": "application/json"}})
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.connected) {
        setStatus("not reachable", "#cf2e2e");
        if (errorEl && d.error) { errorEl.textContent = d.error; errorEl.hidden = false; }
        return;
      }
      setStatus("connected", "#0aa574");
      var cameras = d.cameras || [], sensors = d.sensors || [];
      document.querySelectorAll(".hood-assign").forEach(function (form) {
        var haveCams = csv(form, "data-assigned-cameras");
        var haveSensors = csv(form, "data-assigned-sensors");
        var camWrap = form.querySelector(".cam-options");
        var senWrap = form.querySelector(".sensor-options");
        cameras.forEach(function (c) {
          if (haveCams.indexOf(c.entity) !== -1) return;   // already shown (assigned)
          camWrap.appendChild(makeCheck("cameras", c.entity + "|" + c.label,
                                        c.label, c.entity));
        });
        sensors.forEach(function (s) {
          if (haveSensors.indexOf(s.entity) !== -1) return;
          var meta = s.entity + (s.state ? " · " + s.state : "") + (s.unit ? " " + s.unit : "");
          senWrap.appendChild(makeCheck("sensors",
                                        s.entity + "|" + s.label + "|" + (s.unit || ""),
                                        s.label, meta));
        });
      });
    })
    .catch(function () {
      setStatus("not reachable", "#cf2e2e");
      if (errorEl) { errorEl.textContent = "Could not query Home Assistant."; errorEl.hidden = false; }
    });
})();

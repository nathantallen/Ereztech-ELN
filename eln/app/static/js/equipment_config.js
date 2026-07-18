// Equipment config page: load the Home Assistant connection status and the
// available HA cameras/sensors ASYNCHRONOUSLY, so the page itself never blocks
// on a slow/unreachable HA. Already-assigned equipment is rendered server-side
// (checked) — this only adds the not-yet-assigned HA entities as options.
(function () {
  "use strict";

  var statusEl = document.getElementById("ha-status");
  var errorEl = document.getElementById("ha-error");

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

// Stoichiometry calculator + equipment picker for the entry view.
(function () {
  "use strict";

  // ---------- stoichiometry ----------
  function rows(table) {
    return Array.from(table.querySelectorAll("tbody tr.stoich-row"));
  }
  function num(el) {
    var v = parseFloat(el && el.value);
    return isFinite(v) && v > 0 ? v : null;
  }
  function fmtMass(g) {
    if (g == null) return "";
    if (g >= 1000) return (g / 1000).toFixed(3) + " kg";
    if (g < 0.1) return (g * 1000).toFixed(1) + " mg";
    return g.toFixed(3) + " g";
  }
  function fmtVol(ml) {
    if (ml == null) return "";
    if (ml >= 1000) return (ml / 1000).toFixed(3) + " L";
    return ml.toFixed(2) + " mL";
  }

  function recalc(form) {
    var table = form.querySelector("#stoich-table");
    var all = rows(table);
    var scaleAmount = num(form.querySelector("#scale-amount"));
    var scaleUnit = form.querySelector("#scale-unit").value;
    var limiting = null;
    all.forEach(function (r, i) {
      r.querySelector(".f-limiting").value = String(i);
      var drawBtn = r.querySelector("button[name=draw]");
      if (drawBtn) drawBtn.value = String(i);
      if (r.querySelector(".f-limiting").checked) limiting = r;
    });
    if (!limiting && all.length) {
      limiting = all[0];
      limiting.querySelector(".f-limiting").checked = true;
    }
    var limMw = limiting ? num(limiting.querySelector(".f-mw")) : null;
    var limEquiv = limiting ? (num(limiting.querySelector(".f-equiv")) || 1) : 1;
    var limMmol = null;
    if (scaleAmount != null && limiting) {
      if (scaleUnit === "mmol") limMmol = scaleAmount;
      else if (scaleUnit === "mol") limMmol = scaleAmount * 1000;
      else if (limMw) {
        var grams = scaleUnit === "kg" ? scaleAmount * 1000 :
                    scaleUnit === "mg" ? scaleAmount / 1000 : scaleAmount;
        limMmol = grams / limMw * 1000;
      }
    }
    all.forEach(function (r) {
      var mw = num(r.querySelector(".f-mw"));
      var equiv = num(r.querySelector(".f-equiv")) || 1;
      var density = num(r.querySelector(".f-density"));
      var conc = num(r.querySelector(".f-conc"));
      var state = r.querySelector(".f-state").value;
      var role = r.querySelector(".f-role").value;
      var mmol = null, mass = null, vol = null;
      if (limMmol != null && role !== "solvent") {
        mmol = limMmol * equiv / limEquiv;
        if (mw) mass = mmol * mw / 1000;
        if (state === "solution" && conc) vol = mmol / conc;
        else if (state === "liquid" && density && mass != null) vol = mass / density;
      }
      r.querySelector(".c-mmol").textContent = mmol != null ? mmol.toFixed(2) : "";
      r.querySelector(".c-mass").textContent =
        role === "product" && mass != null ? fmtMass(mass) + " (theor.)" : fmtMass(mass);
      r.querySelector(".c-volume").textContent = fmtVol(vol);
      r.querySelector(".f-mmol").value = mmol != null ? mmol.toFixed(3) : "";
      r.querySelector(".f-mass").value = mass != null ? mass.toFixed(4) : "";
      r.querySelector(".f-volume").value = vol != null ? vol.toFixed(3) : "";
    });
  }

  function wireStoichRow(form, r) {
    r.addEventListener("input", function (ev) {
      if (ev.target.classList.contains("f-mw")) {
        r.querySelector(".f-mw-auto").value = "0";   // manual override
        ev.target.classList.remove("mw-auto");
      }
      recalc(form);
    });
    r.addEventListener("change", function () { recalc(form); });
    r.querySelector(".row-del").addEventListener("click", function () {
      r.remove();
      recalc(form);
    });
    // fill MW/density from the local properties DB when name or CAS is entered
    ["f-name", "f-cas"].forEach(function (cls) {
      r.querySelector("." + cls).addEventListener("blur", function () {
        var name = r.querySelector(".f-name").value.trim();
        var cas = r.querySelector(".f-cas").value.trim();
        if (!name && !cas) return;
        var eid = document.getElementById("reaction-form").dataset.eid;
        fetch("/entries/" + eid + "/properties-lookup?name=" + encodeURIComponent(name) +
              "&cas=" + encodeURIComponent(cas))
          .then(function (resp) { return resp.json(); })
          .then(function (p) {
            if (!p || !p.name) return;
            var mwEl = r.querySelector(".f-mw");
            var dEl = r.querySelector(".f-density");
            if (!mwEl.value && p.mw) mwEl.value = p.mw;
            if (!dEl.value && p.density) dEl.value = p.density;
            if (!r.querySelector(".f-cas").value && p.cas) r.querySelector(".f-cas").value = p.cas;
            recalc(form);
          }).catch(function () {});
      });
    });
  }

  function initStoich() {
    var form = document.getElementById("reaction-form");
    if (!form) return;
    form.dataset.eid = (window.location.pathname.match(/ELN-\d{4}-\d{4}/) || [""])[0];
    var table = form.querySelector("#stoich-table");
    rows(table).forEach(function (r) { wireStoichRow(form, r); });
    form.querySelector("#scale-amount").addEventListener("input", function () { recalc(form); });
    form.querySelector("#scale-unit").addEventListener("change", function () { recalc(form); });
    document.getElementById("add-component").addEventListener("click", function () {
      var tpl = document.getElementById("stoich-row-template");
      var node = tpl.content.firstElementChild.cloneNode(true);
      table.querySelector("tbody").appendChild(node);
      wireStoichRow(form, node);
      recalc(form);
    });
    recalc(form);
  }

  // ---------- equipment picker ----------
  function initEquipment() {
    var form = document.getElementById("equipment-form");
    if (!form || !window.EQUIPMENT_CFG) return;
    var hoodSel = document.getElementById("eq-hood");
    var camSel = document.getElementById("eq-camera");
    var sensorBox = document.getElementById("eq-sensors");

    function hood() {
      return (window.EQUIPMENT_CFG.hoods || []).find(function (h) {
        return h.name === hoodSel.value;
      });
    }
    function refresh(keepCurrent) {
      var h = hood();
      var currentCam = keepCurrent ? camSel.getAttribute("data-current") : "";
      var currentSensors = keepCurrent ? (sensorBox.getAttribute("data-current") || "").split(",") : [];
      camSel.innerHTML = '<option value="">— none —</option>';
      sensorBox.innerHTML = "";
      if (!h) return;
      (h.cameras || []).forEach(function (c) {
        var opt = document.createElement("option");
        opt.value = c.entity;
        opt.textContent = c.label + " (" + c.entity + ")";
        if (c.entity === currentCam) opt.selected = true;
        camSel.appendChild(opt);
      });
      (h.sensors || []).forEach(function (s) {
        var label = document.createElement("label");
        label.className = "check-label";
        var cb = document.createElement("input");
        cb.type = "checkbox";
        cb.name = "sensors";
        cb.value = s.entity;
        if (currentSensors.indexOf(s.entity) >= 0) cb.checked = true;
        label.appendChild(cb);
        label.appendChild(document.createTextNode(
          " " + s.label + (s.unit ? " (" + s.unit + ")" : "")));
        sensorBox.appendChild(label);
      });
    }
    hoodSel.addEventListener("change", function () { refresh(false); });
    refresh(true);

    var previewBtn = document.getElementById("eq-preview-btn");
    var pollTimer = null;
    var previewWrap = document.getElementById("eq-preview");
    var resizeHandle = previewWrap && previewWrap.querySelector(".camera-resize-handle");
    if (resizeHandle) {
      function beginResize(startX, startY) {
        var startRect = previewWrap.getBoundingClientRect();
        return function resize(clientX, clientY) {
          var maxWidth = previewWrap.parentElement.clientWidth;
          var minWidth = Math.min(280, maxWidth);
          var width = Math.max(minWidth,
            Math.min(maxWidth, startRect.width + clientX - startX));
          var height = Math.max(180,
            Math.min(window.innerHeight * 0.75,
              startRect.height + clientY - startY));
          previewWrap.style.width = Math.round(width) + "px";
          previewWrap.style.height = Math.round(height) + "px";
        };
      }

      resizeHandle.addEventListener("mousedown", function (event) {
        event.preventDefault();
        var resize = beginResize(event.clientX, event.clientY);
        function move(moveEvent) { resize(moveEvent.clientX, moveEvent.clientY); }
        function finish() {
          window.removeEventListener("mousemove", move);
          window.removeEventListener("mouseup", finish);
        }
        window.addEventListener("mousemove", move);
        window.addEventListener("mouseup", finish);
      });

      resizeHandle.addEventListener("touchstart", function (event) {
        if (!event.touches.length) return;
        event.preventDefault();
        var resize = beginResize(event.touches[0].clientX, event.touches[0].clientY);
        function move(moveEvent) {
          if (!moveEvent.touches.length) return;
          moveEvent.preventDefault();
          resize(moveEvent.touches[0].clientX, moveEvent.touches[0].clientY);
        }
        function finish() {
          window.removeEventListener("touchmove", move);
          window.removeEventListener("touchend", finish);
          window.removeEventListener("touchcancel", finish);
        }
        window.addEventListener("touchmove", move, { passive: false });
        window.addEventListener("touchend", finish);
        window.addEventListener("touchcancel", finish);
      });
    }
    function stopPreview(img, wrap, msg) {
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
      img.src = "";
      wrap.hidden = true;
      previewBtn.textContent = "Live camera preview";
      if (msg) alert(msg);
    }
    function snapshotPolling(img, entity) {
      // fall back to refreshing a still frame (works for RTSP / snapshot-only cams)
      function tick() { img.src = "/equipment/snapshot/" + entity + "?t=" + Date.now(); }
      tick();
      pollTimer = setInterval(tick, 1000);
    }
    previewBtn.addEventListener("click", function () {
      var wrap = document.getElementById("eq-preview");
      var img = document.getElementById("eq-preview-img");
      if (!wrap.hidden) { stopPreview(img, wrap); return; }
      if (!camSel.value) { alert("Pick a camera first."); return; }
      var entity = camSel.value;
      wrap.hidden = false;
      previewBtn.textContent = "Hide preview";
      // try a live MJPEG stream; if it isn't available (RTSP/snapshot-only) or
      // fails to load, fall back to polling snapshots
      var streamOk = false;
      img.onload = function () { streamOk = true; };
      img.onerror = function () {
        if (pollTimer) return;                 // already polling
        fetch("/equipment/snapshot/" + entity + "?t=" + Date.now())
          .then(function (r) {
            if (r.ok) { img.onerror = null; snapshotPolling(img, entity); }
            else { return r.text().then(function (t) {
              stopPreview(img, wrap, "Camera unreachable: " + (t || r.status)); }); }
          })
          .catch(function () { stopPreview(img, wrap, "Camera unreachable."); });
      };
      img.src = "/equipment/stream/" + entity;
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initStoich();
    initEquipment();
  });
})();

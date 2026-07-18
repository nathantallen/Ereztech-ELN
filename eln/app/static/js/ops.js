// Lab operations: elapsed timer, observation composer, photo capture,
// recording control, and the live multi-series sensor plot.
(function () {
  "use strict";

  var COLORS = ["#F7941E", "#7a00df", "#0aa574", "#04194e", "#cf2e2e"];

  function post(url, data) {
    var csrf = document.querySelector('meta[name="csrf-token"]');
    return fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-CSRF-Token": csrf ? csrf.content : "",
      },
      body: data ? new URLSearchParams(data).toString() : "",
    }).then(function (resp) {
      return resp.json().catch(function () { return { ok: false, error: "HTTP " + resp.status }; });
    });
  }

  function eid() {
    return (window.location.pathname.match(/ELN-\d{4}-\d{4}/) || [""])[0];
  }

  function msg(text, isError) {
    var el = document.getElementById("ops-msg");
    if (!el) return;
    el.textContent = text || "";
    el.style.color = isError ? "#ff9d9d" : "";
    if (text) setTimeout(function () { if (el.textContent === text) el.textContent = ""; }, 6000);
  }

  // ---------- timer ----------
  function initTimer(bar) {
    var started = Date.parse(bar.dataset.started);
    var out = document.getElementById("ops-timer");
    if (!out || !isFinite(started)) return;
    function tick() {
      var s = Math.max(0, Math.floor((Date.now() - started) / 1000));
      out.textContent =
        String(Math.floor(s / 3600)).padStart(2, "0") + ":" +
        String(Math.floor((s % 3600) / 60)).padStart(2, "0") + ":" +
        String(s % 60).padStart(2, "0");
    }
    tick();
    setInterval(tick, 1000);
  }

  // ---------- sensor plot ----------
  function drawPlot(canvas, legend, data) {
    var ctx = canvas.getContext("2d");
    var W = canvas.width = canvas.clientWidth * (window.devicePixelRatio || 1);
    var H = canvas.height = canvas.clientHeight * (window.devicePixelRatio || 1);
    ctx.clearRect(0, 0, W, H);
    var series = (data.series || []).filter(function (s) { return s.points.length > 1; });
    if (!series.length) {
      ctx.fillStyle = "#8a8797";
      ctx.font = (12 * (window.devicePixelRatio || 1)) + "px Poppins, sans-serif";
      ctx.fillText("Waiting for sensor data…", 10, H / 2);
      return;
    }
    var t0 = Date.parse(data.started) || Date.parse(series[0].points[0][0]);
    var tEnd = data.ended ? Date.parse(data.ended) : Date.now();
    var pad = { l: 44, r: 8, t: 8, b: 18 };
    var dpr = window.devicePixelRatio || 1;
    pad.l *= dpr; pad.r *= dpr; pad.t *= dpr; pad.b *= dpr;

    legend.innerHTML = "";
    series.forEach(function (s, si) {
      var vals = s.points.map(function (p) { return p[1]; });
      var vmin = Math.min.apply(null, vals), vmax = Math.max.apply(null, vals);
      if (vmax - vmin < 1e-9) { vmax += 1; vmin -= 1; }
      var span = (vmax - vmin) * 0.1;
      vmin -= span; vmax += span;
      ctx.strokeStyle = COLORS[si % COLORS.length];
      ctx.lineWidth = 1.5 * dpr;
      ctx.beginPath();
      s.points.forEach(function (p, i) {
        var x = pad.l + (Date.parse(p[0]) - t0) / Math.max(1, tEnd - t0) * (W - pad.l - pad.r);
        var y = H - pad.b - (p[1] - vmin) / (vmax - vmin) * (H - pad.t - pad.b);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
      var last = s.points[s.points.length - 1][1];
      var chip = document.createElement("span");
      chip.className = "plot-chip";
      chip.style.borderColor = COLORS[si % COLORS.length];
      chip.innerHTML = "<i style='background:" + COLORS[si % COLORS.length] + "'></i>" +
        s.label + ": <strong>" + last.toFixed(2) + (s.unit ? " " + s.unit : "") + "</strong>";
      legend.appendChild(chip);
    });
    // x axis: elapsed minutes
    ctx.fillStyle = "#8a8797";
    ctx.font = (10 * dpr) + "px Poppins, sans-serif";
    var totalMin = (tEnd - t0) / 60000;
    [0, 0.25, 0.5, 0.75, 1].forEach(function (f) {
      var x = pad.l + f * (W - pad.l - pad.r);
      ctx.fillText("+" + (totalMin * f).toFixed(0) + "m", x - 8, H - 4 * dpr);
    });
  }

  function initPlot() {
    var wrap = document.getElementById("ops-plot-wrap");
    if (!wrap) return;
    var canvas = document.getElementById("ops-plot");
    var legend = document.getElementById("ops-plot-legend");
    var id = eid();
    var live = !wrap.classList.contains("ops-plot-static");

    function refresh() {
      fetch("/entries/" + id + "/ops/sensors.json")
        .then(function (r) { return r.json(); })
        .then(function (data) { drawPlot(canvas, legend, data); })
        .catch(function () {});
    }
    refresh();
    if (live) setInterval(refresh, 5000);

    var fsBtn = document.getElementById("ops-fullscreen");
    if (fsBtn) fsBtn.addEventListener("click", function () {
      wrap.classList.toggle("ops-plot-full");
      refresh();
    });
    window.addEventListener("resize", refresh);
  }

  // ---------- observations ----------
  function refreshObservations() {
    var list = document.getElementById("observations-list");
    if (!list) return;
    fetch("/entries/" + eid() + "/ops/observations")
      .then(function (r) { return r.text(); })
      .then(function (html) {
        list.innerHTML = html;
        if (window.localizeTimes) window.localizeTimes(list);  // localize new stamps
        list.scrollTop = list.scrollHeight;
      }).catch(function () {});
  }

  function initComposer() {
    var btn = document.getElementById("obs-save");
    if (!btn) return;
    var text = document.getElementById("obs-text");
    btn.addEventListener("click", function () {
      var value = text.value.trim();
      if (!value) return;
      btn.disabled = true;
      post("/entries/" + eid() + "/ops/observe", { text: value }).then(function (res) {
        btn.disabled = false;
        if (res.ok) {
          text.value = "";
          msg("Observation saved at t+" + res.elapsed + ".");
          refreshObservations();
        } else {
          msg(res.error || "Could not save observation.", true);
        }
      });
    });
    text.addEventListener("keydown", function (ev) {
      if (!ev.isComposing && (ev.metaKey || ev.ctrlKey) && ev.key === "Enter") btn.click();
    });
  }

  // ---------- photo & recording ----------
  function initCameraButtons(bar) {
    var photoBtn = document.getElementById("ops-photo");
    if (photoBtn) photoBtn.addEventListener("click", function () {
      photoBtn.disabled = true;
      post("/entries/" + eid() + "/ops/photo").then(function (res) {
        photoBtn.disabled = false;
        if (res.ok) {
          msg("Photo saved at t+" + res.elapsed + ".");
          refreshObservations();
        } else {
          msg(res.error || "Photo failed.", true);
        }
      });
    });
    var recBtn = document.getElementById("ops-record");
    if (recBtn) recBtn.addEventListener("click", function () {
      var recording = bar.dataset.recording === "1";
      recBtn.disabled = true;
      post("/entries/" + eid() + "/ops/record/" + (recording ? "stop" : "start"))
        .then(function (res) {
          recBtn.disabled = false;
          if (res.ok) {
            bar.dataset.recording = recording ? "" : "1";
            recBtn.textContent = recording ? "⏺ Record" : "⏹ Stop recording";
            recBtn.classList.toggle("btn-danger-solid", !recording);
            msg(recording ? "Recording saved: " + res.file : "Recording started.");
            refreshObservations();
          } else {
            msg(res.error || "Recording control failed.", true);
          }
        });
    });
  }

  function initLiveCamera(bar) {
    var wrap = document.getElementById("ops-camera");
    var img = document.getElementById("ops-camera-img");
    if (!wrap || !img) return;
    var pollTimer = null;

    function pollSnapshots() {
      if (pollTimer) return;
      function tick() { img.src = img.dataset.snapshot + "?t=" + Date.now(); }
      tick();
      pollTimer = setInterval(tick, 1500);
    }

    img.onerror = function () {
      img.onerror = null;
      pollSnapshots();
    };
    img.src = img.dataset.stream;

    var toggle = document.getElementById("ops-camera-toggle");
    if (toggle) toggle.addEventListener("click", function () {
      var collapsed = wrap.classList.toggle("collapsed");
      toggle.textContent = collapsed ? "+" : "−";
      toggle.title = collapsed ? "Show camera" : "Hide camera";
      toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    });

    var handle = wrap.querySelector(".ops-camera-resize");
    if (handle) handle.addEventListener("pointerdown", function (event) {
      event.preventDefault();
      var startX = event.clientX, startY = event.clientY;
      var startWidth = wrap.offsetWidth, startHeight = wrap.offsetHeight;
      handle.setPointerCapture(event.pointerId);
      function move(moveEvent) {
        var maxWidth = Math.max(180, window.innerWidth - 32);
        wrap.style.width = Math.min(maxWidth, Math.max(160, startWidth + moveEvent.clientX - startX)) + "px";
        wrap.style.height = Math.min(420, Math.max(100, startHeight + moveEvent.clientY - startY)) + "px";
      }
      function finish() {
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", finish);
        handle.removeEventListener("pointercancel", finish);
      }
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", finish);
      handle.addEventListener("pointercancel", finish);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var bar = document.getElementById("ops-bar");
    if (bar) {
      initTimer(bar);
      initCameraButtons(bar);
      initLiveCamera(bar);
    }
    initPlot();
    initComposer();
    var list = document.getElementById("observations-list");
    if (list) list.scrollTop = list.scrollHeight;
  });
})();

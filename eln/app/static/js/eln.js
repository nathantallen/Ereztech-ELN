// Ereztech ELN client-side glue: entry-form material rows + Ketcher sketcher bridge.
(function () {
  "use strict";

  // ---------- mobile keyboard and dictation hints ----------
  function initDictationFields() {
    var literalNames = /(?:^|_)(?:cas|formula|username|url|host|entity|lot|unit|token|password)(?:$|_)/i;
    document.querySelectorAll('input[type="text"], input[type="search"], input[type="url"], textarea')
      .forEach(function (field) {
        if (field.readOnly || field.disabled || field.dataset.dictation === "off") return;
        var literal = field.type === "url" || literalNames.test(field.name || field.id || "");
        field.setAttribute("inputmode", field.type === "url" ? "url" : "text");
        field.setAttribute("autocapitalize", literal ? "none" : "sentences");
        field.setAttribute("spellcheck", literal ? "false" : "true");
        // autocorrect is understood by iOS/iPadOS even though it is not yet a
        // universal HTML attribute. Disable it for chemical IDs and formulas.
        field.setAttribute("autocorrect", literal ? "off" : "on");
        field.setAttribute("enterkeyhint",
          field.type === "search" ? "search" : (field.tagName === "TEXTAREA" ? "enter" : "next"));
      });
  }

  // Add the per-session CSRF token to every server-rendered POST form. This
  // keeps older templates protected without duplicating hidden markup.
  document.addEventListener("DOMContentLoaded", function () {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (!meta) return;
    document.querySelectorAll('form[method="post"], form[method="POST"]').forEach(function (form) {
      if (form.querySelector('input[name="_csrf_token"]')) return;
      var input = document.createElement("input");
      input.type = "hidden";
      input.name = "_csrf_token";
      input.value = meta.content;
      form.appendChild(input);
    });
  });

  // ---------- entry form: dynamic raw-material rows ----------
  function fillLots(matSelect, lotSelect, keep) {
    var map = window.MATERIALS_MAP || {};
    var info = map[matSelect.value];
    lotSelect.innerHTML = "";
    var opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = "— batch —";
    lotSelect.appendChild(opt0);
    (info ? info.batches : []).forEach(function (lot) {
      var opt = document.createElement("option");
      opt.value = lot;
      opt.textContent = lot;
      if (keep && lot === keep) opt.selected = true;
      lotSelect.appendChild(opt);
    });
  }

  function wireRow(row) {
    var matSelect = row.querySelector(".mat-select");
    var lotSelect = row.querySelector(".lot-select");
    matSelect.addEventListener("change", function () {
      fillLots(matSelect, lotSelect);
    });
    row.querySelector(".remove-row").addEventListener("click", function () {
      row.remove();
    });
    var current = lotSelect.getAttribute("data-current");
    if (current && matSelect.value) fillLots(matSelect, lotSelect, current);
  }

  function initEntryForm() {
    var rows = document.getElementById("material-rows");
    var addBtn = document.getElementById("add-material-row");
    var tpl = document.getElementById("material-row-template");
    if (!rows || !addBtn || !tpl) return;
    rows.querySelectorAll(".material-row").forEach(wireRow);
    addBtn.addEventListener("click", function () {
      var node = tpl.content.firstElementChild.cloneNode(true);
      rows.appendChild(node);
      wireRow(node);
    });
    if (!rows.children.length) addBtn.click();
  }

  // ---------- experiment inventory allocation ----------
  function initInventoryAllocations() {
    var form = document.getElementById("inventory-allocation-form");
    var rows = document.getElementById("inventory-allocation-rows");
    var add = document.getElementById("add-inventory-allocation");
    var template = document.getElementById("inventory-allocation-template");
    if (!form || !rows || !add || !template) return;

    function refreshUnits(row) {
      var batch = row.querySelector(".inventory-batch-select");
      var unit = row.querySelector(".inventory-unit-select");
      var selected = batch.options[batch.selectedIndex];
      var choices = selected ? (selected.dataset.units || "").split(",").filter(Boolean) : [];
      var keep = unit.dataset.current || unit.value || (selected && selected.dataset.defaultUnit);
      unit.replaceChildren();
      if (!choices.length) {
        var placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = "unit";
        unit.appendChild(placeholder);
      } else {
        choices.forEach(function (choice) {
          var option = document.createElement("option");
          option.value = choice;
          option.textContent = choice;
          if (choice === keep) option.selected = true;
          unit.appendChild(option);
        });
      }
      unit.dataset.current = "";
    }

    function wire(row) {
      row.querySelector(".inventory-batch-select").addEventListener("change", function () {
        refreshUnits(row);
      });
      row.querySelector(".inventory-allocation-remove").addEventListener("click", function () {
        row.remove();
      });
      refreshUnits(row);
    }

    rows.querySelectorAll(".inventory-allocation-row").forEach(wire);
    add.addEventListener("click", function () {
      var row = template.content.firstElementChild.cloneNode(true);
      rows.appendChild(row);
      wire(row);
      row.querySelector('select[name="allocation_component"]').focus();
    });
  }

  // ---------- structure editor: Ketcher bridge ----------
  function initSketcher() {
    var frame = document.getElementById("ketcher-frame");
    var form = document.getElementById("structure-form");
    if (!frame || !form) return;
    var shell = document.getElementById("sketcher-shell");
    var saveBtn = document.getElementById("save-structure-btn");
    var status = document.getElementById("sketcher-status");
    var touchBtn = document.getElementById("touch-mode-btn");
    var fullscreenBtn = document.getElementById("sketcher-fullscreen-btn");
    var recovery = document.getElementById("sketcher-recovery");
    var draftKey = "ereztech:ketcher-draft:" + window.location.pathname;
    var ketcher = null;
    var initialized = false;
    var autosaveTimer = null;
    var touchModeOverride = null;
    var touchResizeTimer = null;

    function setStatus(message) { status.textContent = message; }

    function injectTouchStyles() {
      try {
        var doc = frame.contentDocument;
        if (!doc || doc.getElementById("ereztech-ketcher-touch")) return;
        var style = doc.createElement("style");
        style.id = "ereztech-ketcher-touch";
        style.textContent = [
          "@media (pointer:coarse), (max-width:1024px){",
          "button,[role=button]{min-width:46px!important;min-height:46px!important;}",
          "input,select{min-height:44px!important;font-size:16px!important;}",
          "canvas,svg{touch-action:none!important;}",
          "[class*=toolbar],[class*=Toolbar]{gap:3px!important;}",
          "}"
        ].join("");
        doc.head.appendChild(style);
      } catch (e) { /* same-origin iframe may still be starting */ }
    }

    function setTouchMode(enabled) {
      shell.classList.toggle("touch-mode", enabled);
      touchBtn.setAttribute("aria-pressed", enabled ? "true" : "false");
      touchBtn.textContent = enabled ? "✓ Touch mode" : "☝ Touch mode";
      injectTouchStyles();
    }

    function syncAutomaticTouchMode() {
      if (touchModeOverride !== null) return;
      setTouchMode(window.matchMedia("(pointer: coarse)").matches || window.innerWidth <= 1024);
    }

    function setFullscreen(enabled) {
      shell.classList.toggle("editor-fullscreen", enabled);
      document.body.classList.toggle("sketcher-fullscreen-active", enabled);
      fullscreenBtn.setAttribute("aria-pressed", enabled ? "true" : "false");
      fullscreenBtn.textContent = enabled ? "✕ Exit full screen" : "⛶ Full screen";
    }

    touchBtn.addEventListener("click", function () {
      touchModeOverride = !shell.classList.contains("touch-mode");
      setTouchMode(touchModeOverride);
    });
    window.addEventListener("resize", function () {
      window.clearTimeout(touchResizeTimer);
      touchResizeTimer = window.setTimeout(syncAutomaticTouchMode, 100);
    });
    fullscreenBtn.addEventListener("click", function () {
      setFullscreen(!shell.classList.contains("editor-fullscreen"));
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && shell.classList.contains("editor-fullscreen")) {
        setFullscreen(false);
      }
    });

    function exportFormats() {
      // Standalone Ketcher/Indigo can cross-wire concurrent export responses.
      // Run each conversion in sequence so every result keeps its own format.
      var formats = {v3000: "", v2000: "", ket: "", smiles: ""};
      return ketcher.getMolfile("v3000").then(function (value) {
        formats.v3000 = value || "";
        return ketcher.getMolfile("v2000").catch(function () { return ""; });
      }).then(function (value) {
        formats.v2000 = value || "";
        if (typeof ketcher.getKet !== "function") return "";
        return ketcher.getKet().catch(function () { return ""; });
      }).then(function (value) {
        formats.ket = value || "";
        return ketcher.getSmiles().catch(function () { return ""; });
      }).then(function (value) {
        formats.smiles = value || "";
        return formats;
      });
    }

    function readDraft() {
      try { return JSON.parse(localStorage.getItem(draftKey) || "null"); }
      catch (e) { return null; }
    }

    function saveDraft() {
      if (!ketcher) return;
      ketcher.getSmiles().then(function (smiles) {
        if (!smiles || !smiles.trim()) return;
        var structurePromise = typeof ketcher.getKet === "function" ?
          ketcher.getKet().catch(function () { return ketcher.getMolfile("v3000"); }) :
          ketcher.getMolfile("v3000");
        return structurePromise.then(function (structure) {
          try {
            localStorage.setItem(draftKey, JSON.stringify({
              savedAt: new Date().toISOString(), structure: structure
            }));
          } catch (e) { /* private browsing or storage quota */ }
        });
      }).catch(function () {});
    }

    function showRecoveryIfAvailable() {
      var draft = readDraft();
      if (draft && draft.structure) recovery.hidden = false;
    }

    document.getElementById("recover-sketch").addEventListener("click", function () {
      var draft = readDraft();
      if (!draft || !ketcher) return;
      ketcher.setMolecule(draft.structure).then(function () {
        recovery.hidden = true;
        setStatus("Recovered the unsaved drawing from this device.");
      }).catch(function () { setStatus("The saved draft could not be recovered."); });
    });
    document.getElementById("discard-sketch").addEventListener("click", function () {
      try { localStorage.removeItem(draftKey); } catch (e) {}
      recovery.hidden = true;
    });

    function poll() {
      if (initialized) return;
      try {
        ketcher = frame.contentWindow && frame.contentWindow.ketcher;
      } catch (e) { ketcher = null; }
      if (ketcher) {
        initialized = true;
        setStatus("Sketcher ready — KET and V3000 preservation enabled.");
        saveBtn.disabled = false;
        injectTouchStyles();
        var initial = window.INITIAL_MOLFILE;
        if (initial && initial.trim()) {
          ketcher.setMolecule(initial).catch(function () {
            setStatus("Could not load the existing structure.");
          });
        }
        showRecoveryIfAvailable();
        autosaveTimer = window.setInterval(saveDraft, 5000);
      } else {
        setTimeout(poll, 300);
      }
    }
    frame.addEventListener("load", function () { setTimeout(poll, 300); });
    setTimeout(poll, 1500); // in case load already fired
    syncAutomaticTouchMode();
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) saveDraft();
    });

    form.addEventListener("submit", function (ev) {
      if (form.dataset.ready === "1") return; // second pass: really submit
      ev.preventDefault();
      if (!ketcher) return;
      saveBtn.disabled = true;
      setStatus("Exporting KET, V3000 and compatibility formats…");
      exportFormats().then(function (formats) {
        document.getElementById("f-molfile").value = formats.v3000;
        document.getElementById("f-molfile-v2000").value = formats.v2000;
        document.getElementById("f-ket").value = formats.ket;
        document.getElementById("f-smiles").value = formats.smiles;
        return ketcher.generateImage(formats.v3000, { outputFormat: "svg" })
          .then(function (blob) { return blob.text(); })
          .catch(function () { return ""; });
      }).then(function (svg) {
        document.getElementById("f-svg").value = svg || "";
        try { localStorage.removeItem(draftKey); } catch (e) {}
        if (autosaveTimer) window.clearInterval(autosaveTimer);
        form.dataset.ready = "1";
        form.submit();
      }).catch(function (err) {
        setStatus("Export failed: " + err);
        saveBtn.disabled = false;
      });
    });
  }

  // ---------- create form: embedded structure sketcher + MW/formula calc ----------
  function initCreateSketcher() {
    var frame = document.getElementById("create-ketcher-frame");
    var form = document.getElementById("entry-form");
    if (!frame || !form) return;
    var calcBtn = document.getElementById("struct-calc-btn");
    var result = document.getElementById("struct-calc-result");
    var ketcher = null;

    (function poll() {
      try { ketcher = frame.contentWindow && frame.contentWindow.ketcher; }
      catch (e) { ketcher = null; }
      if (!ketcher) setTimeout(poll, 300);
    })();

    function exportFormats() {
      var formats = {v3000: "", v2000: "", ket: "", smiles: ""};
      return ketcher.getMolfile("v3000").then(function (v) {
        formats.v3000 = v || "";
        return ketcher.getMolfile("v2000").catch(function () { return ""; });
      }).then(function (v) {
        formats.v2000 = v || "";
        return (typeof ketcher.getKet === "function"
          ? ketcher.getKet().catch(function () { return ""; }) : "");
      }).then(function (v) {
        formats.ket = v || "";
        return ketcher.getSmiles().catch(function () { return ""; });
      }).then(function (v) {
        formats.smiles = v || "";
        return formats;
      });
    }

    if (calcBtn) calcBtn.addEventListener("click", function () {
      if (!ketcher) { result.textContent = "Sketcher still loading…"; return; }
      result.textContent = "Calculating…";
      exportFormats().then(function (formats) {
        if (!formats.smiles.trim()) { result.textContent = "Draw a structure first."; return; }
        var csrf = document.querySelector('meta[name="csrf-token"]').content;
        return fetch("/entries/structure-calc", {
          method: "POST", credentials: "same-origin",
          headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf},
          body: JSON.stringify({molfile: formats.v3000})
        }).then(function (r) {
          return r.json().then(function (b) {
            if (!r.ok) throw new Error(b.error || "Could not calculate.");
            result.innerHTML = "<strong>" + b.formula + "</strong> · " +
              (b.mw != null ? Number(b.mw).toFixed(2) + " g/mol" : "MW n/a");
          });
        });
      }).catch(function (e) { result.textContent = e.message || "Calculation failed."; });
    });

    form.addEventListener("submit", function (ev) {
      if (form.dataset.structReady === "1") return;   // second pass: really submit
      if (!ketcher) return;                            // sketcher not up: submit as-is
      ev.preventDefault();
      exportFormats().then(function (formats) {
        if (formats.smiles.trim()) {                   // a structure was drawn
          document.getElementById("struct-molfile").value = formats.v3000;
          document.getElementById("struct-molfile-v2000").value = formats.v2000;
          document.getElementById("struct-ket").value = formats.ket;
          document.getElementById("struct-smiles").value = formats.smiles;
          return ketcher.generateImage(formats.v3000, { outputFormat: "svg" })
            .then(function (blob) { return blob.text(); })
            .catch(function () { return ""; })
            .then(function (svg) { document.getElementById("struct-svg").value = svg || ""; });
        }
      }).catch(function () { /* fall through and submit anyway */ })
        .then(function () {
          form.dataset.structReady = "1";
          form.submit();
        });
    });
  }

  // ---------- technique select: "+ New technique…" reveals a text input ----------
  function initTechnique() {
    var sel = document.getElementById("technique-select");
    var input = document.getElementById("new-technique");
    if (!sel || !input) return;
    function toggle() {
      var isNew = sel.value === "__new__";
      input.hidden = !isNew;
      input.required = isNew;
      if (isNew) input.focus();
    }
    sel.addEventListener("change", toggle);
    toggle();
  }

  // ---------- pressing Enter in a login field submits the form ----------
  function initEnterSubmit() {
    document.querySelectorAll("form input[type=password], form input[autocomplete=username]")
      .forEach(function (el) {
        el.addEventListener("keydown", function (ev) {
          if (ev.key === "Enter" && !ev.isComposing && el.form) {
            ev.preventDefault();
            el.form.requestSubmit();
          }
        });
      });
  }

  // ---------- compact navigation for phones and tablets ----------
  function initNavigation() {
    var header = document.querySelector(".topbar");
    var toggle = document.querySelector(".nav-toggle");
    if (!header || !toggle) return;

    function setOpen(open) {
      header.classList.toggle("nav-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      var label = toggle.querySelector(".sr-only");
      if (label) label.textContent = open ? "Close navigation" : "Open navigation";
    }

    toggle.addEventListener("click", function () {
      setOpen(!header.classList.contains("nav-open"));
    });
    header.querySelectorAll("nav a").forEach(function (link) {
      link.addEventListener("click", function () { setOpen(false); });
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") setOpen(false);
    });
    window.addEventListener("resize", function () {
      if (window.innerWidth > 1100) setOpen(false);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initDictationFields();
    initEntryForm();
    initInventoryAllocations();
    initSketcher();
    initCreateSketcher();
    initTechnique();
    initEnterSubmit();
    initNavigation();
  });
})();

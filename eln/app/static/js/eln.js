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

  // ---------- structure editor: Ketcher bridge ----------
  function initSketcher() {
    var frame = document.getElementById("ketcher-frame");
    var form = document.getElementById("structure-form");
    if (!frame || !form) return;
    var saveBtn = document.getElementById("save-structure-btn");
    var status = document.getElementById("sketcher-status");
    var ketcher = null;

    function poll() {
      try {
        ketcher = frame.contentWindow && frame.contentWindow.ketcher;
      } catch (e) { ketcher = null; }
      if (ketcher) {
        status.textContent = "Sketcher ready.";
        saveBtn.disabled = false;
        var initial = window.INITIAL_MOLFILE;
        if (initial && initial.trim()) {
          ketcher.setMolecule(initial).catch(function () {
            status.textContent = "Could not load the existing structure.";
          });
        }
      } else {
        setTimeout(poll, 300);
      }
    }
    frame.addEventListener("load", function () { setTimeout(poll, 300); });
    setTimeout(poll, 1500); // in case load already fired

    form.addEventListener("submit", function (ev) {
      if (form.dataset.ready === "1") return; // second pass: really submit
      ev.preventDefault();
      if (!ketcher) return;
      saveBtn.disabled = true;
      status.textContent = "Exporting structure…";
      var molfileP = ketcher.getMolfile("v2000");
      molfileP.then(function (molfile) {
        document.getElementById("f-molfile").value = molfile || "";
        return ketcher.getSmiles().catch(function () { return ""; });
      }).then(function (smiles) {
        document.getElementById("f-smiles").value = smiles || "";
        var molfile = document.getElementById("f-molfile").value;
        return ketcher.generateImage(molfile, { outputFormat: "svg" })
          .then(function (blob) { return blob.text(); })
          .catch(function () { return ""; });
      }).then(function (svg) {
        document.getElementById("f-svg").value = svg || "";
        form.dataset.ready = "1";
        form.submit();
      }).catch(function (err) {
        status.textContent = "Export failed: " + err;
        saveBtn.disabled = false;
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
    initSketcher();
    initTechnique();
    initEnterSubmit();
    initNavigation();
  });
})();

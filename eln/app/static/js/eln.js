// EreZtech ELN client-side glue: entry-form material rows + Ketcher sketcher bridge.
(function () {
  "use strict";

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
          if (ev.key === "Enter" && el.form) {
            ev.preventDefault();
            el.form.requestSubmit();
          }
        });
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initEntryForm();
    initSketcher();
    initTechnique();
    initEnterSubmit();
  });
})();

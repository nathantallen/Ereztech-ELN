// Storage-location picker styled as a system "Choose folder" dialog. Browses
// the CONTAINER's mounted shares (server-side) — the only paths the app can
// actually write to — with navigate-and-Choose semantics like the macOS picker:
// double-click / Enter opens a folder, Choose selects the folder you're in.
(function () {
  "use strict";

  var modal = document.getElementById("browse-modal");
  if (!modal) return;
  var dlg = modal.querySelector(".dlg");
  var listEl = document.getElementById("browse-list");
  var sidebarEl = document.getElementById("browse-sidebar");
  var crumbsEl = document.getElementById("browse-crumbs");
  var pathInput = document.getElementById("browse-path");
  var chooseBtn = document.getElementById("browse-choose");
  var upBtn = document.getElementById("browse-up");
  var statusEl = document.getElementById("browse-status");
  var newFolderBtn = document.getElementById("browse-newfolder-btn");

  var cur = null;        // current listing {path, parent, dirs, is_eln_store, has_content, writable}
  var roots = [];
  var highlight = -1;    // index into cur.dirs for keyboard navigation

  function open() {
    modal.hidden = false;
    load("");
    dlg.focus();
  }
  function close() { modal.hidden = true; }

  function setChoosable() {
    // Choose picks the folder currently shown (like a real folder dialog).
    if (!cur || !cur.path) {                 // roots view — nothing to choose yet
      pathInput.value = "";
      chooseBtn.disabled = true;
      statusEl.textContent = "Open a folder to choose it.";
      return;
    }
    pathInput.value = cur.path;
    if (!cur.writable) {
      chooseBtn.disabled = true;
      statusEl.textContent = cur.path + " — not writable by the app.";
    } else if (cur.is_eln_store) {
      chooseBtn.disabled = false;
      statusEl.textContent = cur.path + " — existing notebook, will be adopted.";
    } else if (cur.has_content) {
      chooseBtn.disabled = true;
      statusEl.textContent = cur.path + " — not empty. Use New Folder or pick an empty folder.";
    } else {
      chooseBtn.disabled = false;
      statusEl.textContent = cur.path + " — empty, the current notebook will be copied here.";
    }
  }

  function renderCrumbs() {
    crumbsEl.innerHTML = "";
    if (!cur || !cur.path) {
      var span = document.createElement("span");
      span.className = "dlg-crumb-cur";
      span.textContent = "Locations";
      crumbsEl.appendChild(span);
      return;
    }
    var parts = cur.path.split("/").filter(Boolean);
    var acc = "";
    var rootCrumb = document.createElement("button");
    rootCrumb.type = "button";
    rootCrumb.className = "dlg-crumb";
    rootCrumb.textContent = "▸";
    rootCrumb.title = "Locations";
    rootCrumb.addEventListener("click", function () { load(""); });
    crumbsEl.appendChild(rootCrumb);
    parts.forEach(function (p, i) {
      acc += "/" + p;
      var target = acc;
      var last = i === parts.length - 1;
      var el = document.createElement(last ? "span" : "button");
      el.className = last ? "dlg-crumb-cur" : "dlg-crumb";
      el.textContent = p;
      if (!last) {
        el.type = "button";
        el.addEventListener("click", function () { load(target); });
      }
      crumbsEl.appendChild(el);
    });
  }

  function renderSidebar() {
    sidebarEl.innerHTML = "";
    roots.forEach(function (r) {
      var li = document.createElement("li");
      var b = document.createElement("button");
      b.type = "button";
      b.className = "dlg-side-item" + (cur && cur.path && (cur.path === r || cur.path.indexOf(r + "/") === 0) ? " active" : "");
      b.innerHTML = "<span class='dlg-ico'>💾</span>" + r;
      b.addEventListener("click", function () { load(r); });
      li.appendChild(b);
      sidebarEl.appendChild(li);
    });
  }

  function setHighlight(i) {
    var rows = listEl.querySelectorAll(".dlg-row");
    if (!rows.length) return;
    highlight = Math.max(0, Math.min(rows.length - 1, i));
    rows.forEach(function (r, idx) { r.classList.toggle("sel", idx === highlight); });
    rows[highlight].scrollIntoView({ block: "nearest" });
  }

  function renderList() {
    listEl.innerHTML = "";
    highlight = -1;
    var dirs = (cur && cur.dirs) || [];
    if (!dirs.length) {
      var empty = document.createElement("li");
      empty.className = "dlg-empty";
      empty.textContent = cur && cur.path ? "This folder has no sub-folders." : "No locations available.";
      listEl.appendChild(empty);
      return;
    }
    dirs.forEach(function (d, idx) {
      var li = document.createElement("li");
      li.className = "dlg-row";
      li.innerHTML = "<span class='dlg-ico'>📁</span><span class='dlg-name'></span>";
      li.querySelector(".dlg-name").textContent = d.name;
      if (d.is_eln) {
        var badge = document.createElement("span");
        badge.className = "dlg-badge";
        badge.textContent = "notebook";
        li.appendChild(badge);
      }
      li.addEventListener("click", function () { setHighlight(idx); });
      li.addEventListener("dblclick", function () { load(d.path); });
      listEl.appendChild(li);
    });
  }

  function load(path) {
    statusEl.textContent = "Loading…";
    chooseBtn.disabled = true;
    fetch("/settings/browse?path=" + encodeURIComponent(path || ""))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) { statusEl.textContent = data.error; return; }
        roots = data.roots || roots;
        cur = data.path ? data : { path: "", dirs: data.dirs || [], parent: null };
        upBtn.disabled = !cur.path || !cur.parent;
        renderSidebar();
        renderCrumbs();
        renderList();
        setChoosable();
      })
      .catch(function () { statusEl.textContent = "Could not list that folder."; });
  }

  function goUp() { if (cur && cur.parent) load(cur.parent); }

  // ---------- New Folder ----------
  function newFolder() {
    if (!cur || !cur.path) { statusEl.textContent = "Open a location first."; return; }
    var name = window.prompt("New folder name in\n" + cur.path + ":", "lab-notebook");
    if (!name) return;
    fetch("/settings/mkdir", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content,
      },
      body: JSON.stringify({ parent: cur.path, name: name }),
    }).then(function (r) { return r.json(); })
      .then(function (res) {
        if (res.path) load(res.path); else statusEl.textContent = res.error || "Could not create folder.";
      }).catch(function () { statusEl.textContent = "Could not create folder."; });
  }

  // ---------- keyboard ----------
  function onKey(ev) {
    if (modal.hidden) return;
    if (ev.key === "Escape") { ev.preventDefault(); close(); }
    else if (ev.key === "ArrowDown") { ev.preventDefault(); setHighlight(highlight + 1); }
    else if (ev.key === "ArrowUp") { ev.preventDefault(); setHighlight(highlight - 1); }
    else if (ev.key === "Backspace") { ev.preventDefault(); goUp(); }
    else if (ev.key === "ArrowRight" || (ev.key === "Enter" && highlight >= 0 && !ev.shiftKey && document.activeElement === listEl)) {
      // open the highlighted folder
      var dirs = (cur && cur.dirs) || [];
      if (highlight >= 0 && dirs[highlight]) { ev.preventDefault(); load(dirs[highlight].path); }
    } else if (ev.key === "Enter") {
      if (!chooseBtn.disabled) { ev.preventDefault(); document.getElementById("browse-form").requestSubmit(); }
    }
  }

  document.getElementById("change-location-btn").addEventListener("click", open);
  document.getElementById("browse-close").addEventListener("click", close);
  document.getElementById("browse-cancel").addEventListener("click", close);
  upBtn.addEventListener("click", goUp);
  newFolderBtn.addEventListener("click", newFolder);
  modal.addEventListener("click", function (ev) { if (ev.target === modal) close(); });
  modal.addEventListener("keydown", onKey);
  document.getElementById("browse-form").addEventListener("submit", function (ev) {
    if (chooseBtn.disabled || !pathInput.value) { ev.preventDefault(); return; }
    if (!window.confirm("Assign the notebook's storage to:\n" + pathInput.value + "\n\nContinue?")) {
      ev.preventDefault();
    }
  });
})();

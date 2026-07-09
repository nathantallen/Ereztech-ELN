/* Server-side file/folder browser. Any <button class="browse-btn" data-target="#input-id">
   opens the dialog; picking a file (or "Link current folder") writes the mapped
   link into the target input. */
(function () {
  let targetInput = null;
  let current = { rootId: null, path: "", folderLink: "" };

  const overlay = document.createElement("div");
  overlay.className = "fb-overlay";
  overlay.hidden = true;
  overlay.innerHTML = `
    <div class="fb-dialog" role="dialog" aria-label="Select a file or folder">
      <div class="fb-head">
        <h3>Select a file or folder</h3>
        <button type="button" class="fb-x" title="Close">&times;</button>
      </div>
      <div class="fb-bar">
        <select class="fb-root" title="Document root"></select>
        <div class="fb-crumbs"></div>
      </div>
      <ul class="fb-list"></ul>
      <div class="fb-foot">
        <span class="fb-hint">Click a file to link it, or open a folder and use:</span>
        <button type="button" class="btn btn-sm fb-usefolder">Link current folder</button>
        <button type="button" class="btn btn-outline btn-sm fb-cancel">Cancel</button>
      </div>
    </div>`;
  document.addEventListener("DOMContentLoaded", () => document.body.appendChild(overlay));

  const $ = (sel) => overlay.querySelector(sel);

  function close() {
    overlay.hidden = true;
    targetInput = null;
  }

  function choose(link) {
    if (targetInput) {
      targetInput.value = link;
      targetInput.dispatchEvent(new Event("change", { bubbles: true }));
      targetInput.focus();
    }
    close();
  }

  async function load(rootId, path) {
    const params = new URLSearchParams();
    if (rootId) params.set("root_id", rootId);
    params.set("path", path || "");
    let data;
    try {
      const res = await fetch("/docroots/browse?" + params.toString(), {
        headers: { Accept: "application/json" },
      });
      data = await res.json();
    } catch (e) {
      data = { roots: [], error: "Could not reach the server." };
    }
    render(data);
  }

  function render(data) {
    current = {
      rootId: data.root_id || null,
      path: data.path || "",
      folderLink: data.folder_link || "",
    };

    const rootSel = $(".fb-root");
    rootSel.innerHTML = "";
    (data.roots || []).forEach((r) => {
      const opt = document.createElement("option");
      opt.value = r.id;
      opt.textContent = r.name;
      if (r.id === data.root_id) opt.selected = true;
      rootSel.appendChild(opt);
    });
    rootSel.style.display = (data.roots || []).length ? "" : "none";

    const crumbs = $(".fb-crumbs");
    crumbs.innerHTML = "";
    const home = document.createElement("a");
    home.href = "#";
    home.textContent = "⌂";
    home.dataset.path = "";
    crumbs.appendChild(home);
    let acc = [];
    (current.path ? current.path.split("/") : []).forEach((seg) => {
      acc.push(seg);
      crumbs.appendChild(document.createTextNode(" / "));
      const a = document.createElement("a");
      a.href = "#";
      a.textContent = seg;
      a.dataset.path = acc.join("/");
      crumbs.appendChild(a);
    });

    const list = $(".fb-list");
    list.innerHTML = "";
    if (data.error) {
      const li = document.createElement("li");
      li.className = "fb-error";
      li.textContent = data.error;
      list.appendChild(li);
      $(".fb-usefolder").disabled = true;
      return;
    }
    $(".fb-usefolder").disabled = false;
    if (!data.entries.length) {
      const li = document.createElement("li");
      li.className = "fb-empty";
      li.textContent = "This folder is empty.";
      list.appendChild(li);
    }
    data.entries.forEach((e) => {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = "#";
      a.className = e.is_dir ? "fb-dir" : "fb-file";
      a.textContent = (e.is_dir ? "📁 " : "📄 ") + e.name;
      a.dataset.path = e.path;
      a.dataset.link = e.link;
      a.dataset.isdir = e.is_dir ? "1" : "";
      li.appendChild(a);
      list.appendChild(li);
    });
  }

  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".browse-btn");
    if (btn) {
      ev.preventDefault();
      targetInput = document.querySelector(btn.dataset.target);
      overlay.hidden = false;
      load(null, "");
      return;
    }
    if (overlay.hidden) return;

    if (ev.target === overlay || ev.target.closest(".fb-x") || ev.target.closest(".fb-cancel")) {
      ev.preventDefault();
      close();
      return;
    }
    if (ev.target.closest(".fb-usefolder")) {
      ev.preventDefault();
      choose(current.folderLink);
      return;
    }
    const crumb = ev.target.closest(".fb-crumbs a");
    if (crumb) {
      ev.preventDefault();
      load(current.rootId, crumb.dataset.path);
      return;
    }
    const entry = ev.target.closest(".fb-list a");
    if (entry) {
      ev.preventDefault();
      if (entry.dataset.isdir) load(current.rootId, entry.dataset.path);
      else choose(entry.dataset.link);
    }
  });

  document.addEventListener("change", (ev) => {
    if (ev.target.matches(".fb-root")) load(ev.target.value, "");
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !overlay.hidden) close();
  });
})();

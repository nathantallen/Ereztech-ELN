/* Container-filesystem folder picker. Any
   <button class="path-btn" data-target="#input-id"> opens a dialog that browses
   the app container's own filesystem; picking a folder writes its ABSOLUTE
   container path into the target input. Unlike filebrowser.js (which navigates
   within an already-registered Doc Root and returns a mapped link), this picks
   the container_path for a *new* root, so it must browse raw container paths. */
(function () {
  let targetInput = null;
  let current = { path: "/", parent: null };

  const overlay = document.createElement("div");
  overlay.className = "fb-overlay pp-overlay";
  overlay.hidden = true;
  overlay.innerHTML = `
    <div class="fb-dialog" role="dialog" aria-label="Select a folder inside the container">
      <div class="fb-head">
        <h3>Select a folder (inside the app container)</h3>
        <button type="button" class="fb-x" title="Close">&times;</button>
      </div>
      <div class="fb-bar">
        <span class="fb-crumbs pp-path"></span>
      </div>
      <ul class="fb-list pp-list"></ul>
      <div class="fb-foot">
        <span class="fb-hint">Open a folder to browse into it, then use:</span>
        <button type="button" class="btn btn-sm pp-use">Use this folder</button>
        <button type="button" class="btn btn-outline btn-sm pp-cancel">Cancel</button>
      </div>
    </div>`;
  document.addEventListener("DOMContentLoaded", () => document.body.appendChild(overlay));

  const $ = (sel) => overlay.querySelector(sel);

  function close() {
    overlay.hidden = true;
    targetInput = null;
  }

  function choose(path) {
    if (targetInput) {
      targetInput.value = path;
      targetInput.dispatchEvent(new Event("change", { bubbles: true }));
      targetInput.focus();
    }
    close();
  }

  async function load(path) {
    const params = new URLSearchParams({ path: path || "/" });
    let data;
    try {
      const res = await fetch("/docroots/fsbrowse?" + params.toString(), {
        headers: { Accept: "application/json" },
      });
      data = await res.json();
    } catch (e) {
      data = { path: path || "/", parent: null, error: "Could not reach the server.", dirs: [] };
    }
    render(data);
  }

  function render(data) {
    current = { path: data.path || "/", parent: data.parent || null };
    $(".pp-path").textContent = current.path;

    const list = $(".pp-list");
    list.innerHTML = "";

    if (current.parent) {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = "#";
      a.className = "fb-dir pp-up";
      a.textContent = "⬆ .. (parent folder)";
      a.dataset.path = current.parent;
      li.appendChild(a);
      list.appendChild(li);
    }

    if (data.error) {
      const li = document.createElement("li");
      li.className = "fb-error";
      li.textContent = data.error;
      list.appendChild(li);
    } else if (!data.dirs.length) {
      const li = document.createElement("li");
      li.className = "fb-empty";
      li.textContent = "No sub-folders here. Use this folder, or go back up.";
      list.appendChild(li);
    } else {
      data.dirs.forEach((d) => {
        const li = document.createElement("li");
        const a = document.createElement("a");
        a.href = "#";
        a.className = "fb-dir";
        a.textContent = "📁 " + d.name;
        a.dataset.path = d.path;
        li.appendChild(a);
        list.appendChild(li);
      });
    }
  }

  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".path-btn");
    if (btn) {
      ev.preventDefault();
      targetInput = document.querySelector(btn.dataset.target);
      const start = (targetInput && targetInput.value.trim()) || "/";
      overlay.hidden = false;
      load(start);
      return;
    }
    if (overlay.hidden) return;

    if (ev.target === overlay || ev.target.closest(".fb-x") || ev.target.closest(".pp-cancel")) {
      ev.preventDefault();
      close();
      return;
    }
    if (ev.target.closest(".pp-use")) {
      ev.preventDefault();
      choose(current.path);
      return;
    }
    const dir = ev.target.closest(".pp-list a");
    if (dir) {
      ev.preventDefault();
      load(dir.dataset.path);
    }
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !overlay.hidden) close();
  });
})();

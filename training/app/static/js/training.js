// Ereztech Safety Training — small progressive enhancements. Every page works
// without JavaScript; this only adds the phone nav toggle and the quiz counter.
(function () {
  "use strict";

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

  // ---------- quiz: answered counter, jump to the first unanswered ----------
  function initQuiz() {
    var form = document.getElementById("quiz-form");
    if (!form) return;
    var total = parseInt(form.dataset.total, 10) || 0;
    var count = document.getElementById("quiz-answered");
    var bar = document.getElementById("quiz-bar");

    function answered() {
      var names = {};
      form.querySelectorAll("input[type=radio]:checked").forEach(function (el) { names[el.name] = 1; });
      return Object.keys(names).length;
    }
    function update() {
      var n = answered();
      if (count) count.textContent = n;
      if (bar && total) bar.style.width = Math.round(100 * n / total) + "%";
    }
    form.addEventListener("change", function (event) {
      var fs = event.target.closest(".q-card");
      if (fs) fs.classList.remove("q-missing");
      update();
    });
    form.addEventListener("submit", function (event) {
      var first = null;
      form.querySelectorAll(".q-card").forEach(function (fs) {
        var picked = fs.querySelector("input[type=radio]:checked");
        fs.classList.toggle("q-missing", !picked);
        if (!picked && !first) first = fs;
      });
      if (first) {
        event.preventDefault();
        first.scrollIntoView({ block: "center" });
        var radio = first.querySelector("input[type=radio]");
        if (radio) radio.focus({ preventScroll: true });
      }
    });
    if (form.dataset.firstMissing) {
      var target = document.getElementById("q" + form.dataset.firstMissing);
      if (target) target.scrollIntoView({ block: "center" });
    }
    update();
  }

  document.addEventListener("DOMContentLoaded", function () {
    initNavigation();
    initQuiz();
  });
})();

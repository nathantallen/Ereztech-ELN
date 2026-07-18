// Rewrite UTC <time class="lt"> stamps to the viewer's LOCAL timezone, formatted
// for easy reading (e.g. "Jul 16, 2026, 3:58:02 PM CDT"). Timestamps are stored
// and served in UTC; only the display is localized. Exposed as window.localizeTimes
// so content loaded later (live Actions and Observations) can be localized too.
(function () {
  "use strict";

  function fmtOpts() {
    var o = {
      year: "numeric", month: "short", day: "numeric",
      hour: "numeric", minute: "2-digit", second: "2-digit",
      timeZoneName: "short",
    };
    // window.ELN_TZ pins all viewers to the configured lab timezone; when it is
    // empty each viewer sees their own browser-local time.
    if (window.ELN_TZ) o.timeZone = window.ELN_TZ;
    return o;
  }

  function localize(root) {
    var opts = fmtOpts();
    (root || document).querySelectorAll("time.lt[datetime]").forEach(function (el) {
      if (el.dataset.localized) return;
      var d = new Date(el.getAttribute("datetime"));
      if (isNaN(d.getTime())) return;
      try {
        el.textContent = d.toLocaleString(undefined, opts);
      } catch (e) {
        el.textContent = d.toLocaleString();   // invalid tz name → browser local
      }
      el.title = d.toISOString().replace("T", " ").replace(".000Z", " UTC");
      el.dataset.localized = "1";
    });
  }

  window.localizeTimes = localize;
  document.addEventListener("DOMContentLoaded", function () { localize(document); });
})();

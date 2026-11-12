(function () {
  var d = document.documentElement, KEY = "md-bilingual-page-view", BAR = 60;
  var CODE = { zh: "zh-Hans", en: "en", both: "zh-Hans" };
  function known(v) { return v === "zh" || v === "en" || v === "both"; }
  function buttons(v) {
    var b = document.querySelectorAll("[data-set]");
    for (var i = 0; i < b.length; i++) b[i].setAttribute("aria-pressed", b[i].getAttribute("data-set") === v ? "true" : "false");
  }
  function set(v) {
    d.setAttribute("data-lang", v);
    d.lang = CODE[v];
    document.title = d.getAttribute("data-title-" + v);
    buttons(v);
  }
  // The reader's last choice stands. A link straight to a heading in one language opens that language, unless both are showing.
  var saved = null, hash = /^#(zh|en)-\d+$/.exec(location.hash);
  try { saved = localStorage.getItem(KEY); } catch (e) {}
  if (known(saved)) set(saved);
  var now = d.getAttribute("data-lang");
  if (hash && now !== "both" && now !== hash[1]) set(hash[1]);
  document.addEventListener("DOMContentLoaded", function () { buttons(d.getAttribute("data-lang")); });

  // Which section the reader is in, and how far through it. Sections are shared by all three views.
  function place() {
    var secs = document.querySelectorAll("[data-sec]"), cur = null;
    for (var i = 0; i < secs.length; i++) if (secs[i].getBoundingClientRect().top <= BAR) cur = secs[i];
    if (!cur) return null;
    var r = cur.getBoundingClientRect();
    return { n: cur.getAttribute("data-sec"), f: (BAR - r.top) / Math.max(r.height, 1) };
  }
  function go(p) {
    var t = p && document.querySelector('[data-sec="' + p.n + '"]');
    if (!t) return;
    var r = t.getBoundingClientRect();
    window.scrollBy(0, r.top + p.f * r.height - BAR);
  }

  document.addEventListener("click", function (e) {
    if (!e.target.closest) return;
    var menu = document.querySelector(".menu");
    if (menu && menu.open && (e.target.closest(".menu a") || !e.target.closest(".menu"))) menu.open = false;
    var b = e.target.closest("[data-set]");
    if (!b) return;
    var v = b.getAttribute("data-set");
    if (v === d.getAttribute("data-lang")) return;
    var p = place();
    set(v);
    go(p);
    try { localStorage.setItem(KEY, v); } catch (e2) {}
  });
})();

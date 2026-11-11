/* Shared by every page of zono.be: the bar at the top, the language menu and the footer, in four languages.
   A page calls Site.start(function (lang) { ...draw the page in that language... }). */
var Site = (function () {
  var TEXT = {
    nl: { navDevices: "Toestellen", navTogether: "Verder kijken", navTour: "Wat zit erin", navFaq: "Vragen",
      footTv: "Zono op je tv", footPrivacy: "Privacy", footSmall: "© 2026 Zono TV · Zono is alleen de app. Zenders en films zitten er niet bij." },
    fr: { navDevices: "Appareils", navTogether: "Reprendre partout", navTour: "Visite", navFaq: "Questions",
      footTv: "Zono sur la télé", footPrivacy: "Confidentialité", footSmall: "© 2026 Zono TV · Zono est uniquement le lecteur : aucun flux ni chaîne inclus." },
    en: { navDevices: "Devices", navTogether: "Watch anywhere", navTour: "Tour", navFaq: "Questions",
      footTv: "Zono on your TV", footPrivacy: "Privacy", footSmall: "© 2026 Zono TV · Zono is just the player: no streams or channels included." },
    de: { navDevices: "Geräte", navTogether: "Überall schauen", navTour: "Rundgang", navFaq: "Fragen",
      footTv: "Zono auf dem Fernseher", footPrivacy: "Datenschutz", footSmall: "© 2026 Zono TV · Zono ist nur der Player: keine Streams oder Sender enthalten." }
  };
  var NAMES = { nl: "Nederlands", fr: "Français", en: "English", de: "Deutsch" };
  var lang = "nl", changed = function () {};

  function pick() {
    var chosen = new URLSearchParams(location.search).get("lang");
    try { chosen = chosen || localStorage.getItem("zono-language"); } catch (e) {}
    if (!TEXT[chosen]) { var b = (navigator.language || "nl").slice(0, 2); chosen = TEXT[b] ? b : "nl"; }
    return chosen;
  }
  function apply() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-s]").forEach(function (el) { el.innerHTML = TEXT[lang][el.getAttribute("data-s")]; });
    var toggle = document.getElementById("lang-toggle");
    if (toggle) toggle.textContent = NAMES[lang];
    document.querySelectorAll("[data-lang]").forEach(function (b) { b.setAttribute("aria-current", String(b.getAttribute("data-lang") === lang)); });
    document.querySelectorAll("a[data-keep-lang]").forEach(function (a) { a.href = a.getAttribute("data-keep-lang") + "?lang=" + lang + (a.getAttribute("data-hash") || ""); });
  }
  function set(next) {
    lang = TEXT[next] ? next : "nl";
    try { localStorage.setItem("zono-language", lang); } catch (e) {}
    try { var u = new URL(location.href); u.searchParams.set("lang", lang); history.replaceState(null, "", u); } catch (e) {}
    apply(); changed(lang);
  }
  function start(onChange) {
    changed = onChange || changed;
    var toggle = document.getElementById("lang-toggle"), menu = document.getElementById("lang-menu");
    function close() { if (menu) { menu.hidden = true; toggle.setAttribute("aria-expanded", "false"); } }
    if (toggle && menu) {
      toggle.onclick = function () { menu.hidden = !menu.hidden; toggle.setAttribute("aria-expanded", String(!menu.hidden)); };
      menu.querySelectorAll("[data-lang]").forEach(function (b) { b.onclick = function () { set(b.getAttribute("data-lang")); close(); toggle.focus(); }; });
      document.addEventListener("click", function (e) { if (!e.target.closest(".langs")) close(); });
      document.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });
    }
    lang = pick();
    apply(); changed(lang);
  }
  return { start: start, lang: function () { return lang; } };
})();

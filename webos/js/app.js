// Zono for LG TV (webOS). Works with the remote's arrows / OK / Back / numbers and with the Magic Remote pointer.
// Written for the browser inside webOS 4 and newer (no async/await, no optional chaining).
(function () {
  "use strict";
  var VERSION = "2.3.5";
  var KEY = { LEFT: 37, UP: 38, RIGHT: 39, DOWN: 40, OK: 13, BACK: 461, BACKSPACE: 8, ESC: 27, CH_UP: 33, CH_DOWN: 34,
    PLAY: 415, PAUSE: 19, PLAY_PAUSE: 10252, STOP: 413, FF: 417, RW: 412 };
  var API = window.ZONO_API || "https://zono.be/api";
  var SUBS_API = window.ZONO_SUBS_API || "https://api.opensubtitles.com/api/v1";

  // ------------------------------------------------------------------ error log (sent only with "Report a problem")
  var LOG = [];
  function log(text) {
    var line = new Date().toISOString().slice(0, 19) + " " + String(text);
    line = line.replace(/(\/(?:live|movie|series|timeshift)\/)[^\/\s]+\/[^\/\s]+\//gi, "$1***/***/")
      .replace(/((?:username|password)=)[^&\s'"]+/gi, "$1***");
    LOG.push(line.slice(0, 500));
    if (LOG.length > 200) LOG.shift();
  }
  window.addEventListener("error", function (e) { log("error: " + e.message + " @" + (e.filename || "").split("/").pop() + ":" + e.lineno); });
  window.addEventListener("unhandledrejection", function (e) { log("promise: " + (e.reason && (e.reason.message || e.reason.code) || e.reason)); });
  var STARTED = Date.now();
  // moments the screen was stuck (> 150 ms), with the page: this is what makes a TV feel slow
  try {
    new PerformanceObserver(function (list) {
      list.getEntries().forEach(function (e) { if (e.duration > 150) log("stuck " + Math.round(e.duration) + " ms on " + where()); });
    }).observe({ entryTypes: ["longtask"] });
  } catch (e) { /* older TVs */ }
  function where() {
    if (typeof S === "undefined" || !player || !P) return "start";
    if (!player.hidden && !P.mini) return "player";
    return S.guideFor ? "channel guide" : S.detail ? "film page" : S.series ? "series page" : S.page + (P.mini ? " (+small picture)" : "");
  }

  // ------------------------------------------------------------------ storage (only on this TV)
  function load(key, fallback) {
    try { var v = localStorage.getItem("zono." + key); return v === null ? fallback : JSON.parse(v); } catch (e) { return fallback; }
  }
  function save(key, value) {
    try { if (value === null) localStorage.removeItem("zono." + key); else localStorage.setItem("zono." + key, JSON.stringify(value)); } catch (e) { /* full */ }
  }
  // per profile: favourites, progress, recent channels, reminders, hidden groups (the first profile uses the plain keys)
  var profileId = load("profile", "main");
  function pkey(k) { return profileId === "main" ? k : "p." + profileId + "." + k; }
  function pload(k, fallback) { return load(pkey(k), fallback); }
  function psave(k, value) { save(pkey(k), value); }

  var db = {
    open: function () {
      return new Promise(function (resolve, reject) {
        if (!window.indexedDB) return reject(new Error("no idb"));
        var r = indexedDB.open("zono", 1);
        r.onupgradeneeded = function () { r.result.createObjectStore("kv"); };
        r.onsuccess = function () { resolve(r.result); };
        r.onerror = function () { reject(r.error); };
      });
    },
    get: function (key) {
      return db.open().then(function (d) {
        return new Promise(function (resolve) {
          var r = d.transaction("kv").objectStore("kv").get(key);
          r.onsuccess = function () { resolve(r.result); };
          r.onerror = function () { resolve(undefined); };
        });
      }).catch(function () { return undefined; });
    },
    put: function (key, value) {
      return db.open().then(function (d) {
        return new Promise(function (resolve) {
          var t = d.transaction("kv", "readwrite");
          if (value === undefined) t.objectStore("kv").delete(key); else t.objectStore("kv").put(value, key);
          t.oncomplete = t.onerror = function () { resolve(); };
        });
      }).catch(function () {});
    },
  };

  // ------------------------------------------------------------------ language
  var lang = "en";
  function pickLanguage() {
    var chosen = load("language", "");
    var device = String(navigator.language || "en").slice(0, 2).toLowerCase();
    lang = chosen || (STRINGS[device] ? device : "en");
    document.documentElement.lang = lang;
  }
  function T(key) {
    var text = (STRINGS[lang] && STRINGS[lang][key]) || STRINGS.en[key] || key;
    for (var i = 1; i < arguments.length; i++) text = text.replace("{" + (i - 1) + "}", arguments[i]);
    return text;
  }
  var LANGS = [["", null], ["nl", "Nederlands"], ["fr", "Français"], ["en", "English"], ["de", "Deutsch"]];

  // ------------------------------------------------------------------ network
  var PROXY = location.host === "appassets.androidplatform.net" ? location.origin + "/proxy?u=" : "";
  function via(url) {
    return PROXY && /^https?:\/\//i.test(url) && url.indexOf(location.origin) !== 0 && !/^https:\/\/(zono\.be|api\.opensubtitles\.com)\//i.test(url) ? PROXY + encodeURIComponent(url) : url;
  }
  function request(method, url, body, headers, timeout, maxBytes) {
    return new Promise(function (resolve, reject) {
      var x = new XMLHttpRequest();
      x.open(method, via(url), true);
      x.timeout = timeout || 60000;
      Object.keys(headers || {}).forEach(function (k) { x.setRequestHeader(k, headers[k]); });
      if (maxBytes) x.onprogress = function (e) { if (e.loaded > maxBytes) { x.abort(); reject(new Error("too big")); } };
      x.onload = function () {
        if (x.status === 401 || x.status === 403) { var e = new Error("HTTP " + x.status); e.status = x.status; e.login = /player_api/.test(url); reject(e); }
        else if (x.status >= 200 && x.status < 300) resolve(x.responseText);
        else { var err = new Error("HTTP " + x.status); err.status = x.status; reject(err); }
      };
      x.onerror = function () { reject(new Error("network")); };
      x.ontimeout = function () { reject(new Error("timeout")); };
      x.send(body === undefined ? null : body);
    });
  }
  function get(url, timeout) { return request("GET", url, undefined, null, timeout); }
  function parse(t) { return JSON.parse(String(t).replace(/^﻿/, "")); }
  function json(url) { return get(url).then(parse); }
  function post(url, body, headers) {
    // text/plain: a "simple" request, so the TV does not have to ask the server for permission first (zono.be reads it as JSON)
    var all = { "Content-Type": "text/plain;charset=UTF-8" }; for (var k in headers || {}) all[k] = headers[k];
    return request("POST", url, JSON.stringify(body), all, 20000).then(function (t) { return t ? parse(t) : {}; });
  }
  function loginError() { var e = new Error(T("error_login")); e.login = true; return e; }

  // ---- heavy work runs in a worker (js/worker.js), so the screen never freezes
  var worker = null, jobs = {}, jobId = 0;
  function work(message, onStep, onPartial) {
    if (!worker) {
      worker = new Worker("js/worker.js");
      worker.onmessage = function (e) {
        var m = e.data, job = jobs[m.id];
        if (!job) return;
        if (m.type === "step") { if (job.step) job.step(m.kind); return; }
        if (m.type === "chunk") { Array.prototype.push.apply(job.items, m.items); return; }
        if (m.type === "partial") { var first = job.items; job.items = []; if (job.partial) job.partial(first); return; }
        delete jobs[m.id];
        m.items = job.items;
        if (m.type === "done") job.resolve(m); else job.reject(m);
      };
    }
    return new Promise(function (resolve, reject) {
      var id = ++jobId;
      jobs[id] = { resolve: resolve, reject: reject, step: onStep, partial: onPartial, items: [] };
      message.id = id;
      worker.postMessage(message);
    });
  }
  /** The whole library from the provider (read and stored by the worker). */
  function fetchLibrary(source, step, onPartial) {
    return work({ type: "load", source: source }, step, onPartial).then(function (m) {
      if (source.type !== "xtream") save("guideUrl", m.guideUrl || "");
      save("refreshedAt", Date.now());
      return m.items;
    }, function (m) {
      if (m.code === "login") throw loginError();
      if (m.code === "empty") throw new Error(T("error_empty"));
      throw new Error(m.message || m.code);
    });
  }

  // ------------------------------------------------------------------ profiles
  var PROFILE_COLORS = ["#5558f5", "#db2777", "#0ea5e9", "#f59e0b", "#10b981", "#8b5cf6"];
  function profiles() {
    var list = load("profiles", null);
    return Array.isArray(list) && list.length ? list : [{ id: "main", name: "", color: 0 }];
  }
  function currentProfile() {
    var list = profiles();
    return list.filter(function (p) { return p.id === profileId; })[0] || list[0];
  }
  function saveProfiles(list) { save("profiles", list); }
  function hashPin(pin, id) {
    var bytes = new TextEncoderLite(String(pin) + "|" + id);
    var digest = nacl.hash(bytes), hex = "";
    for (var i = 0; i < 16; i++) hex += (digest[i] < 16 ? "0" : "") + digest[i].toString(16);
    return hex;
  }
  function TextEncoderLite(text) {
    var s = unescape(encodeURIComponent(text)), out = new Uint8Array(s.length);
    for (var i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
    return out;
  }

  // ------------------------------------------------------------------ state
  var S = {
    source: load("source", null),
    items: [],
    shelves: Catalog.shelves([], true),
    uhd: load("uhd", true),
    loading: false, step: "", error: "",
    page: "discover", series: null, detail: null, guideFor: null,
    choosing: false, // the "who's watching?" screen
    byId: null, numbers: {}, pos: {},
  };
  function loadProfileData() {
    profileId = load("profile", "main");
    profileId = currentProfile().id;
    var sid = Catalog.shortId;
    S.progress = pload("progress", []).map(function (p) { p.item.id = sid(p.item.id); return p; });
    S.favorites = pload("favorites", []).map(sid);
    S.recent = pload("recent", []).map(sid);
    S.reminders = pload("reminders", []).map(function (r) { r.channel = sid(r.channel); return r; });
    S.hidden = pload("hidden", []);
    S.countries = pload("countries", []);
  }
  loadProfileData();

  /** What this profile may see: no hidden groups; in a kids profile no adult groups or titles. */
  function buildShelves() {
    var kids = !!currentProfile().kids, hidden = {};
    S.hidden.forEach(function (h) { hidden[h] = 1; });
    var anyHidden = S.hidden.length > 0;
    S.hiddenSet = hidden; S.kids = kids;
    var visible = !kids && !anyHidden ? S.items : S.items.filter(function (i) {
      if (anyHidden && hidden[(i.kind === "episode" ? "series" : i.kind) + "|" + i.group]) return false;
      return !(kids && (i.adult || (i.q === undefined && (Guide.adult(i.group) || Guide.adult(i.title)))));
    });
    S.shelves = Catalog.shelves(visible, S.uhd, S.countries);
    S.byId = null; // built when first needed (see find)
    // channel numbers: the provider's own (num / tvg-chno) or the position in the list
    S.numbers = {};
    var numbered = S.shelves.live.some(function (c) { return c.num > 0; });
    S.pos = {};
    S.shelves.live.forEach(function (c, i) { var n = numbered ? c.num : i + 1; S.pos[c.id] = n; if (n && !S.numbers[n]) S.numbers[n] = c; });
  }

  function refresh(source, quiet) {
    var began = Date.now();
    S.loading = !quiet; S.error = ""; S.step = "";
    if (!quiet) render();
    var shownEarly = false;
    // the channels come first: show them at once (films and series follow a little later)
    function early(live) {
      if (quiet || !live.length) return;
      shownEarly = true;
      S.items = live; buildShelves(); S.loading = false;
      if (!S.source) { S.source = source; save("source", source); stopPairing(); S.choosing = needsChoice(); }
      log("channels shown after " + Math.round((Date.now() - began) / 1000) + " s");
      render();
    }
    return fetchLibrary(source, function (kind) { S.step = kind; if (!quiet && !shownEarly) render(); }, early).then(function (items) {
      S.loading = false;
      var same = quiet && S.items.length === items.length && S.items.length && S.items[0].id === items[0].id && S.items[S.items.length - 1].id === items[items.length - 1].id;
      S.items = items;
      buildShelves();
      log("library " + (quiet ? "refreshed" : "loaded") + " in " + Math.round((Date.now() - began) / 1000) + " s: " + S.shelves.live.length + " channels, " + S.shelves.movies.length + " films, " + S.shelves.series.length + " series");
      if (same) return true; // nothing new: no redraw while you are browsing
      if (!S.source) { S.source = source; save("source", source); stopPairing(); S.choosing = needsChoice(); }
      render();
      return true;
    }, function (problem) {
      S.loading = false;
      log("library: " + (problem.message || problem));
      if (!quiet) S.error = problem.login ? T("error_login") : String(problem.message || problem).indexOf(T("error_empty")) === 0
        ? T("error_empty") : T("error_connect", problem.message || "?");
      render();
      return false;
    });
  }

  /** An item by id (a Map, built once: fast even with 100,000 titles). */
  function find(id) {
    if (!id) return null;
    if (!S.byId) { S.byId = new Map(); for (var i = 0; i < S.items.length; i++) S.byId.set(S.items[i].id, S.items[i]); }
    return S.byId.get(id) || null;
  }
  /** Shown in this profile? (not in a hidden group, not adult in a kids profile) */
  function visible(i) {
    if (!i) return false;
    if (S.hiddenSet && S.hiddenSet[(i.kind === "episode" ? "series" : i.kind) + "|" + i.group]) return false;
    return !(S.kids && (i.adult || Guide.adult(i.group) || Guide.adult(i.title)));
  }

  function needsChoice() { var list = profiles(); return list.length > 1 || !!list[0].pin; }

  function start() {
    S.choosing = !!S.source && needsChoice();
    if (!S.source) return render();
    S.loading = true; render();
    var cacheOld = false;
    work({ type: "cache" }).then(function (m) { cacheOld = m.old; return m.items; }, function () { return []; }).then(function (items) {
      if (items && items.length) {
        S.items = items;
        setTimeout(function () {
          buildShelves();
          S.loading = false;
          setTimeout(render, 0);
        }, 0);
        var old = cacheOld, due = Date.now() - load("refreshedAt", 0) > 6 * 3600000;
        if (old || due) setTimeout(function () { refresh(S.source, true); }, old ? 500 : 15000);
      } else refresh(S.source, false);
    });
  }

  function saveProgress(item, pos, dur) {
    if (item.kind === "catchup") return;
    var list = S.progress.filter(function (p) { return p.item.id !== item.id; });
    if (!(dur > 0 && pos > dur * 0.94) && pos > 60) {
      list.unshift({ item: { id: item.id, kind: item.kind, title: item.title, image: item.image || "", url: item.url || "", sid: item.sid || "", ext: item.ext || "", group: item.group || "",
        number: item.number || 0 }, pos: pos, dur: dur, t: Date.now() });
    }
    S.progress = list.slice(0, 40);
    psave("progress", S.progress);
  }
  function progressOf(id) { for (var i = 0; i < S.progress.length; i++) if (S.progress[i].item.id === id) return S.progress[i]; return null; }
  function isFavorite(id) { return S.favorites.indexOf(id) >= 0; }
  function toggleFavorite(item) {
    var i = S.favorites.indexOf(item.id);
    if (i >= 0) S.favorites.splice(i, 1); else S.favorites.unshift(item.id);
    psave("favorites", S.favorites);
    toast(isFavorite(item.id) ? T("favorite_added", item.title) : T("favorite_removed", item.title));
  }
  function addRecent(id) {
    S.recent = [id].concat(S.recent.filter(function (x) { return x !== id; })).slice(0, 15);
    psave("recent", S.recent);
  }

  // ------------------------------------------------------------------ tv guide
  var epgCache = {}; // channel id -> {at, full, rows}
  var xmltv = { state: "off", guide: null, url: "" };

  /** Programmes of a channel: Xtream asks the provider (short = now and next, full = also the past for catch-up);
   *  M3U uses the playlist's XMLTV guide. */
  function programsFor(item, full) {
    var cached = epgCache[item.id];
    if (cached && Date.now() - cached.at < 10 * 60000 && (cached.full || !full)) return Promise.resolve(cached.rows);
    if (S.source.type === "xtream" && item.sid) {
      var url = Catalog.apiUrl(S.source, full ? "get_simple_data_table" : "get_short_epg", full ? { stream_id: item.sid } : { stream_id: item.sid, limit: "8" });
      return work({ type: "epg", url: url }).then(function (m) {
        var rows = m.rows || [];
        if (!rows.length && full) return programsFor(item, false);
        epgCache[item.id] = { at: Date.now(), full: full, rows: rows };
        var keys = Object.keys(epgCache);
        if (keys.length > 400) keys.slice(0, keys.length - 300).forEach(function (k) { delete epgCache[k]; });
        return rows;
      }, function () { return xmltvRows(item); });
    }
    return xmltvRows(item);
  }
  function xmltvRows(item) {
    return loadXmltv(false).then(function (url) {
      if (!url) return [];
      return work({ type: "gchan", url: url, item: { epg: item.epg, tvgName: item.tvgName, title: item.title } }).then(function (m) { return m.rows || []; });
    });
  }
  /** The XMLTV guide (the playlist's own for M3U, or for searching the provider's whole guide). It is kept in the
   *  worker; this returns its link once it is ready there, or "" when there is none. */
  function loadXmltv(forSearch) {
    var url = S.source.type === "xtream" ? (forSearch ? Catalog.xmltvUrl(S.source) : "") : load("guideUrl", "");
    if (!url) return Promise.resolve("");
    if (xmltv.url === url && xmltv.state === "ready") return Promise.resolve(url);
    if (xmltv.url === url && xmltv.promise) return xmltv.promise;
    if (/\.gz(\?|$)/i.test(url)) { xmltv.state = "failed"; return Promise.resolve(""); }
    xmltv.url = url; xmltv.state = "loading";
    var channels = S.shelves.live.map(function (c) { return { id: c.id, epg: c.epg, tvgName: c.tvgName, title: c.title }; });
    xmltv.promise = work({ type: "xmltv", url: url, channels: channels }).then(function () {
      xmltv.state = "ready"; return url;
    }, function (m) {
      log("guide: " + (m.message || m.code));
      xmltv.state = m.code === "big" ? "big" : "failed"; xmltv.promise = null;
      return "";
    });
    return xmltv.promise;
  }

  function hm(t) { var d = new Date(t * 1000); return (d.getHours() < 10 ? "0" : "") + d.getHours() + ":" + (d.getMinutes() < 10 ? "0" : "") + d.getMinutes(); }
  function dayName(t) {
    var d = new Date(t * 1000), today = new Date(); today.setHours(0, 0, 0, 0);
    var diff = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()) - today) / 86400000);
    if (diff === 0) return T("today");
    if (diff === 1) return T("tomorrow");
    if (diff === -1) return T("yesterday");
    try { return d.toLocaleDateString(lang, { weekday: "long", day: "numeric", month: "long" }); } catch (e) { return d.toDateString(); }
  }
  function nowSeconds() { return Date.now() / 1000; }
  function numberOf(channel) { return (S.pos && S.pos[channel.id]) || channel.num || 0; }

  // ------------------------------------------------------------------ reminders
  function reminderFor(item, program) {
    for (var i = 0; i < S.reminders.length; i++) if (S.reminders[i].channel === item.id && S.reminders[i].start === program.start) return S.reminders[i];
    return null;
  }
  function toggleReminder(item, program) {
    var found = reminderFor(item, program);
    if (found) S.reminders.splice(S.reminders.indexOf(found), 1);
    else S.reminders.push({ channel: item.id, channelTitle: item.title, title: program.title, start: program.start, end: program.end });
    S.reminders.sort(function (a, b) { return a.start - b.start; });
    psave("reminders", S.reminders);
    toast(found ? T("reminder_removed") : T("reminder_set") + " · " + hm(program.start) + " " + program.title);
  }
  function checkReminders() {
    var now = nowSeconds(), changed = false;
    S.reminders = S.reminders.filter(function (r) { if (r.end < now) { changed = true; return false; } return true; });
    S.reminders.forEach(function (r) {
      if (!r.shown && r.start - now <= 60) {
        r.shown = true; changed = true;
        var channel = find(r.channel);
        sheet({ title: T("reminder_title", r.title), text: T("reminder_on", r.channelTitle) + " · " + hm(r.start), items: [
          channel ? { label: T("watch_now"), go: function () { closeSheet(); playChannel(channel); } } : null,
          { label: T("close"), go: closeSheet }] });
      }
    });
    if (changed) psave("reminders", S.reminders);
  }

  // ------------------------------------------------------------------ icons (drawn, so they look the same on every TV:
  // LG's own font has no arrows, hearts or bells)
  var S2 = 'fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"';
  var ICONS = {
    play: '<path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/>',
    pause: '<path d="M8 5v14M16 5v14" ' + S2 + ' stroke-width="3.2"/>',
    info: '<circle cx="12" cy="12" r="9" ' + S2 + '/><path d="M12 11v6" ' + S2 + '/><circle cx="12" cy="7.6" r="1.4" fill="currentColor"/>',
    heart: '<path d="M12 20s-7.5-4.6-7.5-10.2A4.2 4.2 0 0 1 12 7.2a4.2 4.2 0 0 1 7.5 2.6C19.5 15.4 12 20 12 20z" ' + S2 + '/>',
    heartFill: '<path d="M12 20s-7.5-4.6-7.5-10.2A4.2 4.2 0 0 1 12 7.2a4.2 4.2 0 0 1 7.5 2.6C19.5 15.4 12 20 12 20z" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>',
    replay: '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3" ' + S2 + '/><path d="M4.5 3.8v4.6h4.6" ' + S2 + '/>',
    bell: '<path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 1.5h-15z" ' + S2 + '/><path d="M10 20.5a2 2 0 0 0 4 0" ' + S2 + '/>',
    clock: '<circle cx="12" cy="12" r="8.5" ' + S2 + '/><path d="M12 7.5V12l3 2" ' + S2 + '/>',
    left: '<path d="M14.5 5.5L8 12l6.5 6.5" ' + S2 + ' stroke-width="2.6"/>',
    right: '<path d="M9.5 5.5L16 12l-6.5 6.5" ' + S2 + ' stroke-width="2.6"/>',
    up: '<path d="M5.5 14.5L12 8l6.5 6.5" ' + S2 + ' stroke-width="2.6"/>',
    down: '<path d="M5.5 9.5L12 16l6.5-6.5" ' + S2 + ' stroke-width="2.6"/>',
    dot: '<circle cx="12" cy="12" r="5" fill="currentColor"/>',
    star: '<path d="M12 3.6l2.5 5.3 5.8.8-4.2 4 1 5.7L12 16.7l-5.1 2.7 1-5.7-4.2-4 5.8-.8z" fill="currentColor"/>',
    lock: '<rect x="5.5" y="10.5" width="13" height="9.5" rx="2" ' + S2 + '/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" ' + S2 + '/>',
    smile: '<circle cx="12" cy="12" r="8.5" ' + S2 + '/><path d="M8.5 14a4.5 4.5 0 0 0 7 0" ' + S2 + '/><circle cx="9" cy="10" r="1.3" fill="currentColor"/><circle cx="15" cy="10" r="1.3" fill="currentColor"/>',
    erase: '<path d="M9 6h11v12H9l-6-6z" ' + S2 + '/><path d="M12.5 9.5l5 5M17.5 9.5l-5 5" ' + S2 + '/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5" ' + S2 + ' stroke-width="2.8"/>',
    close: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11" ' + S2 + ' stroke-width="2.6"/>',
    list: '<path d="M8.5 7h11M8.5 12h11M8.5 17h11" ' + S2 + '/><circle cx="4.5" cy="7" r="1.3" fill="currentColor"/><circle cx="4.5" cy="12" r="1.3" fill="currentColor"/><circle cx="4.5" cy="17" r="1.3" fill="currentColor"/>',
    grid: '<rect x="3.5" y="5" width="17" height="14" rx="2" ' + S2 + '/><path d="M3.5 10h17M9 10v9" ' + S2 + '/>',
    cc: '<rect x="3" y="5.5" width="18" height="13" rx="2.5" ' + S2 + '/><path d="M10.5 10.3a2.3 2.3 0 1 0 0 3.4M17 10.3a2.3 2.3 0 1 0 0 3.4" ' + S2 + ' stroke-width="1.9"/>',
    download: '<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19.5h14" ' + S2 + '/>',
  };
  function icon(name, cls) {
    var span = document.createElement("span");
    span.className = "ic" + (cls ? " " + cls : "");
    span.innerHTML = '<svg viewBox="0 0 24 24" width="1em" height="1em" aria-hidden="true">' + (ICONS[name] || "") + "</svg>";
    return span;
  }
  function withIcon(name, text, cls) { return h("span", { cls: "wi" + (cls ? " " + cls : "") }, [icon(name), text ? h("span", { text: text }) : null]); }
  /** A remote key as a little key cap: "OK", "0", or an arrow. */
  function keycap(k) { return h("span", { cls: "keycap" }, [ICONS[k] ? icon(k) : k]); }
  function keyHint(keys, text) { return h("span", { cls: "keyhint" }, keys.map(keycap).concat([h("span", { text: text })])); }

  // ------------------------------------------------------------------ building blocks
  function h(tag, attrs, kids) {
    var el = document.createElement(tag);
    for (var k in attrs || {}) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) continue;
      if (k === "cls") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k === "go") { el._go = v; el.classList.add("f"); el.tabIndex = -1; }
      else if (k === "long") el._long = v;
      else if (k === "onfocus") el.addEventListener("focus", v);
      else if (k === "style") el.setAttribute("style", v);
      else el.setAttribute(k, v);
    }
    (kids || []).forEach(function (c) { if (c) el.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return el;
  }

  var PAIRS = [["#4c1d95", "#db2777"], ["#1e3a8a", "#06b6d4"], ["#7c2d12", "#f59e0b"], ["#064e3b", "#34d399"], ["#312e81", "#a78bfa"], ["#831843", "#fb7185"]];
  function hash(s) { var x = 0; for (var i = 0; i < s.length; i++) x = (x * 31 + s.charCodeAt(i)) | 0; return Math.abs(x); }
  function placeholder(title) {
    var p = PAIRS[hash(title) % PAIRS.length];
    return h("div", { cls: "ph", style: "background:linear-gradient(135deg," + p[0] + "," + p[1] + ")", text: Catalog.initials(title) });
  }
  /** Pictures load when they come into view (a page can hold hundreds), in a TV-friendly size. */
  var seen = window.IntersectionObserver ? new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (!e.isIntersecting) return;
      var img = e.target; seen.unobserve(img);
      if (img._src) { img.src = img._src; img._src = null; }
    });
  }, { rootMargin: "300px" }) : null;
  function picture(src, cls) {
    if (!src) return null;
    var img = h("img", { alt: "", cls: cls, decoding: "async" });
    img.onerror = function () { img.remove(); };
    src = posterSize(src, cls);
    if (seen) { img._src = src; seen.observe(img); } else img.src = src;
    return img;
  }
  /** TMDB pictures in the size the TV shows them (originals can be thousands of pixels wide). */
  function posterSize(src, cls) {
    return String(src).replace(/\/t\/p\/(?:original|w1280|w1920|w780|w500)\//, cls === "poster-bg" ? "/t/p/w780/" : "/t/p/w342/");
  }
  function bar(fraction) { return h("div", { cls: "progress" }, [h("div", { style: "width:" + Math.max(2, Math.min(1, fraction) * 100) + "%" })]); }

  function poster(item, go, opts) {
    opts = opts || {};
    var pic = h("div", { cls: "pic" }, [placeholder(item.title), picture(item.image),
      item.rating > 0 ? h("div", { cls: "corner", text: item.rating.toFixed(1) }) : null,
      isFavorite(item.id) ? h("div", { cls: "corner heart" }, [icon("heartFill")]) : null,
      opts.progress ? bar(opts.progress) : null]);
    return h("div", { cls: "card poster", go: go, long: opts.long || function () { toggleFavorite(item); render(); }, "data-key": "i-" + item.id },
      [pic, h("div", { cls: "title", text: item.title })]);
  }

  function wide(item, go, opts) {
    opts = opts || {};
    var isLive = item.kind === "live";
    var pic = h("div", { cls: "pic" }, [item.image ? null : placeholder(item.title), picture(item.image),
      isLive && Catalog.itemUhd(item) ? h("div", { cls: "corner k", text: "4K" }) : null,
      opts.progress ? bar(opts.progress) : null]);
    return h("div", { cls: "card wide" + (isLive ? " logo" : ""), go: go, long: opts.long, "data-key": "w-" + item.id },
      [pic, h("div", { cls: "title", text: item.title }), opts.sub ? h("div", { cls: "sub", text: opts.sub }) : null]);
  }

  function rowItem(title, go, opts) {
    opts = opts || {};
    var kids = [];
    if (opts.image !== undefined) kids.push(h("div", { cls: "logo-box" }, [opts.image ? picture(opts.image) : h("span", { text: Catalog.initials(title) })]));
    if (opts.time) kids.push(h("span", { cls: "time", text: opts.time }));
    kids.push(h("div", { cls: "name" }, [h("div", { cls: "line" }, [opts.lead || null, title]), opts.sub ? h("div", { cls: "sub", text: opts.sub }) : null]));
    if (opts.badge) kids.push(h("span", { cls: "badge", text: opts.badge }));
    if (opts.trail) kids.push(typeof opts.trail === "string" ? h("span", { cls: "trail", text: opts.trail }) : h("span", { cls: "trail" }, [opts.trail]));
    return h("div", { cls: "row-item" + (opts.sel ? " sel" : "") + (opts.cls ? " " + opts.cls : ""), go: go, long: opts.long,
      "data-key": opts.key, onfocus: opts.onfocus }, kids);
  }

  function pill(text, sel, go, key, long) { return h("div", { cls: "pill" + (sel ? " sel" : ""), go: go, long: long, "data-key": key, text: text }); }
  function button(text, go, opts) {
    opts = opts || {};
    return h("div", { cls: "btn" + (opts.primary ? " primary" : "") + (opts.round ? " round" : ""), go: go, "data-key": opts.key },
      [opts.icon ? icon(opts.icon, "icon") : null, opts.round ? null : h("span", { text: text }),
        opts.round ? h("span", { cls: "under", text: text }) : null]);
  }
  function shelf(title, cards, hint) {
    return h("div", { cls: "shelf" }, [h("h2", null, [title, hint ? h("span", { cls: "hint", text: hint }) : null]), h("div", { cls: "scroll-x" }, cards)]);
  }
  function groupName(g) { return g || T("other"); }
  function stepText() {
    return S.step === "live" ? T("loading_live") : S.step === "movie" ? T("loading_movies") : S.step === "series" ? T("loading_series") : T("loading");
  }
  function lazyList(container, items, make, batch) {
    batch = batch || 60;
    var drawn = 0;
    function more() {
      var end = Math.min(items.length, drawn + batch);
      for (var i = drawn; i < end; i++) {
        var el = make(items[i], i);
        if (i >= end - 10 && end < items.length) el._near = more;
        container.appendChild(el);
      }
      drawn = end;
    }
    more();
    container._more = function () { if (drawn < items.length) more(); };
  }
  function input(value, placeholderText, onChange, opts) {
    opts = opts || {};
    var el = h("input", { cls: "f", type: opts.type || "text", placeholder: placeholderText, value: value || "", "data-key": opts.key,
      autocomplete: "off", autocapitalize: "off", spellcheck: "false", style: opts.style });
    el.tabIndex = -1;
    el.oninput = function () { onChange(el.value); };
    el._go = function () { el.blur(); el.focus(); };
    return el;
  }

  // ------------------------------------------------------------------ sheets (small windows on top: menus, questions, PIN)
  var sheetEl = document.getElementById("sheet");
  function sheetOpen() { return !sheetEl.hidden; }
  var sheetReturn = null, sheetOnClose = null;
  function sheet(opts) {
    var hadSheet = sheetOpen();
    if (!hadSheet) sheetReturn = document.activeElement;
    sheetOnClose = opts.onClose || null;
    var body = [h("h2", { text: opts.title })];
    if (opts.text) body.push(h("div", { cls: "sheet-text", text: opts.text }));
    (opts.content || []).forEach(function (c) { if (c) body.push(c); });
    var list = h("div", { cls: "sheet-list scroll-y" });
    (opts.items || []).forEach(function (it) {
      if (!it) return;
      if (it.heading) list.appendChild(h("div", { cls: "sheet-heading", text: it.heading }));
      else list.appendChild(rowItem(it.label, it.go, { sel: it.sel, trail: it.trail, sub: it.sub, key: it.key, image: it.image, onfocus: it.onfocus }));
    });
    if (list.children.length) body.push(list);
    sheetEl.innerHTML = "";
    sheetEl.className = "sheet" + (opts.side ? " side" : "");
    sheetEl._digit = null;
    sheetEl.appendChild(h("div", { cls: "sheet-box" + (opts.wide ? " wide" : "") }, body));
    sheetEl.hidden = false;
    var first = sheetEl.querySelector(".f.sel") || focusables(sheetEl)[0];
    if (first) focus(first);
  }
  function closeSheet() {
    if (!sheetOpen()) return;
    sheetEl.hidden = true; sheetEl.innerHTML = "";
    var after = sheetOnClose; sheetOnClose = null;
    if (after) after();
    if (sheetReturn && document.body.contains(sheetReturn)) focus(sheetReturn);
    else if (!playerOpen()) restoreFocus(null);
  }

  /** Four-digit PIN with the number keys (or the on-screen digits). */
  function pinSheet(title, done) {
    var digits = "";
    var dots = h("div", { cls: "pin-dots" });
    function draw() { dots.innerHTML = ""; for (var i = 0; i < 4; i++) dots.appendChild(h("span", { cls: i < digits.length ? "on" : "" })); }
    function add(d) {
      if (d === "del") digits = digits.slice(0, -1); else if (digits.length < 4) digits += d;
      draw();
      if (digits.length === 4) { var pin = digits; digits = ""; setTimeout(function () { draw(); done(pin); }, 150); }
    }
    draw();
    var pad = h("div", { cls: "pin-pad" }, "123456789".split("").concat(["", "0", "del"]).map(function (d) {
      return d ? h("div", { cls: "pin-key", go: function () { add(d); } }, [d === "del" ? icon("erase") : d]) : h("div", { cls: "pin-key empty" });
    }));
    sheet({ title: title, content: [dots, pad] });
    sheetEl._digit = add;
  }

  // ------------------------------------------------------------------ screens
  var app = document.getElementById("app");

  function render() {
    var keep = currentKey();
    app.innerHTML = "";
    if (!S.source) app.appendChild(loginScreen());
    else if (S.choosing) app.appendChild(profilesScreen());
    else app.appendChild(homeScreen());
    if (P.mini && !app.querySelector(".mini-slot")) stopMini();
    if (!sheetOpen()) restoreFocus(keep);
  }

  var login = { xtream: true, server: "", user: "", password: "", m3u: "", problem: "" };
  // ---- the phone sends settings (login, OpenSubtitles key) locked with a key only this TV has
  var PAIR_API = window.ZONO_PAIR_API || API + "/pair.php";
  var PAIR_PAGE = window.ZONO_PAIR_PAGE || "https://zono.be/tv/";
  var pair = { state: "off", url: "", code: "", key: null, poll: null, round: 0, mode: "login", onChange: null };

  function b64url(bytes) {
    var t = ""; for (var i = 0; i < bytes.length; i++) t += String.fromCharCode(bytes[i]);
    return btoa(t).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function fromB64(text) {
    var raw = atob(text), out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }
  function utf8(bytes) { var t = ""; for (var i = 0; i < bytes.length; i++) t += String.fromCharCode(bytes[i]); return decodeURIComponent(escape(t)); }
  function hexId(n) { var b = nacl.randomBytes(n), s = ""; for (var i = 0; i < n; i++) s += (b[i] < 16 ? "0" : "") + b[i].toString(16); return s; }

  function stopPairing() { clearTimeout(pair.poll); pair.state = "off"; pair.round++; }
  function startPairing(mode, onChange) {
    if (mode) { pair.mode = mode; pair.onChange = onChange || null; }
    if (!window.nacl || !window.qrcode) { pair.state = "failed"; return; }
    var round = ++pair.round;
    pair.state = "loading";
    post(PAIR_API, { action: "new" }).then(function (answer) {
      if (round !== pair.round) return;
      pair.code = answer.code;
      pair.key = nacl.randomBytes(32);
      pair.url = PAIR_PAGE + "#" + pair.code + "." + b64url(pair.key) + "." + lang + (pair.mode === "subs" ? ".subs" : "");
      pair.state = "ready";
      pairChanged();
      waitForPhone(round);
    }, function () {
      if (round !== pair.round) return;
      pair.state = "failed";
      pairChanged();
    });
  }
  function pairChanged() { if (pair.onChange) pair.onChange(); else if (!S.source) render(); }
  function waitForPhone(round) {
    pair.poll = setTimeout(function () {
      if (round !== pair.round || (pair.mode === "login" && S.source)) return;
      json(PAIR_API + "?code=" + pair.code).then(function (answer) {
        if (round !== pair.round) return;
        if (!answer.data) return waitForPhone(round);
        var all = fromB64(answer.data);
        var opened = nacl.secretbox.open(all.subarray(24), all.subarray(0, 24), pair.key);
        var got = opened && JSON.parse(utf8(opened));
        if (got && got.type === "settings" && pair.mode === "subs") {
          stopPairing();
          if (got.opensubtitles) { save("opensubtitles", String(got.opensubtitles).trim()); toast(T("sub_key_set")); }
          closeSheet();
          return;
        }
        if (!got || (got.type !== "xtream" && got.type !== "m3u") || pair.mode !== "login") return startPairing();
        stopPairing();
        if (got.language && STRINGS[got.language]) { save("language", got.language); pickLanguage(); }
        if (got.name) { var list = profiles(); list[0].name = String(got.name).slice(0, 20); saveProfiles(list); }
        if (Array.isArray(got.countries)) { save(pkey("countries"), got.countries.filter(function (c) { return /^[A-Z]{2,4}$/.test(c); }).slice(0, 10)); loadProfileData(); }
        login.xtream = got.type === "xtream";
        login.server = got.server || ""; login.user = got.user || ""; login.password = got.password || ""; login.m3u = got.m3u || "";
        toast(T("phone_received"));
        refresh(login.xtream ? { type: "xtream", server: login.server, user: login.user, password: login.password } : { type: "m3u", m3u: login.m3u }, false)
          .then(function (ok) { if (!ok) startPairing("login"); });
      }, function (problem) {
        if (round !== pair.round) return;
        if (/404/.test(problem.message)) startPairing(); // the code ran out (10 minutes): a new one
        else waitForPhone(round);
      });
    }, 2500);
  }
  function qrBox() {
    if (pair.state === "ready") {
      var qr = qrcode(0, "M"); qr.addData(pair.url); qr.make();
      return h("img", { cls: "qr", src: qr.createDataURL(8, 3), alt: "QR" });
    }
    if (pair.state === "failed") return h("div", { cls: "qr-off", text: T("phone_unavailable") });
    return h("div", { cls: "qr-off" }, [h("div", { cls: "spinner" })]);
  }
  function phonePanel() {
    if (pair.mode !== "login") { pair.mode = "login"; pair.onChange = null; pair.state = "off"; }
    if (pair.state === "off" && !S.loading) startPairing("login");
    return h("div", { cls: "phone" }, [qrBox(), h("div", { cls: "phone-text" }, [h("h2", { text: T("phone_title") }), h("div", { text: T("phone_steps") }),
      pair.state === "ready" ? h("div", { cls: "phone-wait" }, [h("div", { cls: "dot" }), h("span", { text: T("phone_waiting") })]) : null])]);
  }

  function loginScreen() {
    function connect() {
      login.problem = "";
      var source = login.xtream ? { type: "xtream", server: login.server.trim(), user: login.user.trim(), password: login.password }
        : { type: "m3u", m3u: login.m3u.trim() };
      var ready = login.xtream ? source.server && source.user && source.password : /^https?:\/\//i.test(source.m3u);
      if (!ready) { login.problem = T("error_fields"); render(); return; }
      refresh(source, false);
    }
    function field(key, text, type) { return input(login[key], text, function (v) { login[key] = v; }, { type: type, key: "in-" + key }); }
    var form = [h("div", null, [pill(T("tab_xtream"), login.xtream, function () { login.xtream = true; render(); }, "tab-x"),
      pill(T("tab_m3u"), !login.xtream, function () { login.xtream = false; render(); }, "tab-m")])];
    if (login.xtream) form.push(field("server", T("field_server"), "url"), field("user", T("field_user")), field("password", T("field_password"), "password"));
    else form.push(field("m3u", T("field_m3u"), "url"));
    var message = login.problem || S.error;
    if (message) form.push(h("div", { cls: "error", text: message }));
    form.push(S.loading ? h("div", { cls: "busy" }, [h("div", { cls: "spinner" }), h("span", { text: stepText() })])
      : h("div", null, [pill(T("connect"), true, connect, "connect")]));
    return h("div", { cls: "login" }, [
      h("div", { cls: "intro" }, [h("img", { src: "img/logo.png", alt: "Zono" }), h("h1", { text: T("login_title") }),
        h("p", { text: T("login_intro") }), phonePanel()]),
      h("div", { cls: "form" }, [h("div", { cls: "or", text: T("or_remote") })].concat(form))]);
  }

  // ---- who's watching?
  function avatar(p, big) {
    var color = PROFILE_COLORS[(p.color || 0) % PROFILE_COLORS.length];
    return h("div", { cls: "avatar" + (big ? " big" : ""), style: "background:" + color }, [p.kids ? icon("smile") : (p.name || T("profile_default")).slice(0, 1).toUpperCase()]);
  }
  function enterProfile(p, verified) {
    if (p.pin && !verified) {
      return pinSheet(T("enter_pin", p.name || T("profile_default")), function (pin) {
        if (hashPin(pin, p.id) === p.pin) { closeSheet(); enterProfile(p, true); }
        else toast(T("pin_wrong"));
      });
    }
    save("profile", p.id);
    loadProfileData();
    buildShelves();
    S.choosing = false; S.page = "discover"; S.series = S.detail = S.guideFor = null;
    render();
    focusFirst(".main");
  }
  function profilesScreen() {
    return h("div", { cls: "who" }, [h("img", { cls: "who-logo", src: "img/logo.png", alt: "Zono" }), h("h1", { text: T("who_watching") }),
      h("div", { cls: "who-list" }, profiles().map(function (p) {
        return h("div", { cls: "who-card", go: function () { enterProfile(p); }, "data-key": "who-" + p.id },
          [avatar(p, true), h("div", { cls: "who-name" }, [p.name || T("profile_default"), p.pin ? icon("lock", "after") : null])]);
      }))]);
  }

  var PAGES = [["discover", "nav_discover"], ["search", "nav_search"], ["live", "nav_live"], ["guide", "nav_guide"], ["movies", "nav_movies"], ["series", "nav_series"], ["settings", "nav_settings"]];
  function homeScreen() {
    var me = currentProfile();
    var menu = h("div", { cls: "menu" }, [h("img", { cls: "logo", src: "img/logo.png", alt: "Zono" })].concat(PAGES.map(function (p) {
      return rowItem(T(p[1]), function () { log("page " + p[0]); S.page = p[0]; S.series = S.detail = S.guideFor = null; render(); focusFirst(".main"); if (p[0] === "guide") setTimeout(function () { focusFirst(".tvg-box.now"); }, 600); },
        { sel: S.page === p[0] && !S.series && !S.detail && !S.guideFor, key: "menu-" + p[0] });
    })));
    if (profiles().length > 1) {
      menu.appendChild(h("div", { cls: "menu-space" }));
      menu.appendChild(h("div", { cls: "row-item me", go: function () { S.choosing = true; render(); }, "data-key": "menu-me" },
        [avatar(me), h("div", { cls: "name", text: me.name || T("profile_default") })]));
    }
    var main = h("div", { cls: "main" });
    if (S.guideFor) main.appendChild(channelGuideScreen(S.guideFor));
    else if (S.detail) main.appendChild(detailScreen(S.detail));
    else if (S.series) main.appendChild(seriesScreen(S.series));
    else if (!S.shelves.all.length && S.page !== "settings") main.appendChild(loadingScreen());
    else main.appendChild(({ discover: discoverScreen, search: searchScreen, live: liveScreen, guide: tvGuideScreen, movies: moviesScreen, series: seriesListScreen, settings: settingsScreen })[S.page]());
    return h("div", { cls: "home" }, [menu, main]);
  }

  function loadingScreen() {
    if (S.error) return h("div", { cls: "center" }, [h("div", { text: S.error }), pill(T("retry"), true, function () { refresh(S.source, false); }, "retry")]);
    if (!S.loading && !S.items.length) return h("div", { cls: "center" }, [h("div", { text: T("nothing_yet") })]);
    return h("div", { cls: "center" }, [h("div", { cls: "spinner" }), h("div", { text: stepText() })]);
  }

  // ---- open things
  function open(item, list, index) {
    if (item.kind === "series") return openSeries(item);
    if (item.kind === "movie") return openDetail(item);
    if (item.kind === "live") return playChannel(item, list);
    play(list || [item], list ? index : 0);
  }
  function openSeries(item) { S.series = item; S.detail = null; render(); focusFirst(".eps"); }
  function openDetail(item) { S.detail = item; render(); focusFirst(".detail .btn"); }
  function openGuide(item) { S.guideFor = item; render(); focusFirst(".guide-list"); }
  function playChannel(item, list) {
    list = list && list.length ? list : S.shelves.live;
    var index = list.indexOf(item);
    if (index < 0) { list = S.shelves.live; index = list.indexOf(item); }
    if (index < 0) { list = [item]; index = 0; }
    play(list, index);
  }

  // ---- discover: big banner with the top films, greeting, "continue with" channel, rows
  var hero = { index: 0, timer: null, info: {} };
  function heroItems() {
    var sh = S.shelves, seen = {}, out = [];
    sh.topMovies.concat(sh.newMovies).forEach(function (m) { if (!seen[m.id] && out.length < 8) { seen[m.id] = 1; out.push(m); } });
    return out;
  }
  function vodInfo(item) {
    if (hero.info[item.id]) return Promise.resolve(hero.info[item.id]);
    if (!S.source || S.source.type !== "xtream" || !item.sid) return Promise.resolve({});
    var action = item.kind === "series" ? "get_series_info" : "get_vod_info";
    var extra = item.kind === "series" ? { series_id: item.sid } : { vod_id: item.sid };
    return json(Catalog.apiUrl(S.source, action, extra)).then(function (data) {
      var i = (data && data.info) || {};
      var backdrop = i.backdrop_path; if (Array.isArray(backdrop)) backdrop = backdrop[0];
      var year = String(i.releasedate || i.releaseDate || i.release_date || i.year || "").slice(0, 4);
      var info = { plot: i.plot || i.description || "", genre: String(i.genre || "").split(/[,/]/)[0].trim(), year: /^\d{4}$/.test(year) ? year : "",
        duration: i.duration || (i.episode_run_time ? i.episode_run_time + " min" : ""), backdrop: typeof backdrop === "string" ? backdrop : "",
        cast: i.cast || i.actors || "", director: i.director || "", rating: parseFloat(i.rating) || 0, cover: i.movie_image || i.cover || "" };
      hero.info[item.id] = info;
      return info;
    }, function () { hero.info[item.id] = {}; return {}; });
  }
  function metaLine(item, info) {
    var parts = [];
    if (info.year) parts.push(info.year);
    if (info.genre) parts.push(info.genre);
    if (info.duration) parts.push(info.duration);
    var rating = info.rating || item.rating;
    var line = h("span", { text: parts.join("  ·  ") });
    if (rating) { if (parts.length) line.appendChild(document.createTextNode("  ·  ")); line.appendChild(withIcon("star", String(Math.round(rating * 10) / 10), "gold")); }
    return line;
  }
  /** Film pictures from TMDB in a TV-friendly size (the original can be 4000 pixels wide). */
  function smaller(src) { return String(src || "").replace(/\/t\/p\/(?:original|w1280|w1920)\//, "/t/p/w780/"); }
  function preload(src, done) {
    if (!src) return done();
    var img = new Image(), called = false;
    function once() { if (!called) { called = true; done(); } }
    img.onload = img.onerror = once; setTimeout(once, 4000); img.src = src;
  }
  function heroBlock() {
    var list = heroItems();
    if (!list.length) return null;
    if (hero.index >= list.length) hero.index = 0;
    var box = h("div", { cls: "hero" });
    var layers = [h("div", { cls: "hero-bg on" }), h("div", { cls: "hero-bg" })], front = 0;
    var text = h("div", { cls: "hero-text" }), dots = h("div", { cls: "hero-dots" });
    box.appendChild(layers[0]); box.appendChild(layers[1]); box.appendChild(h("div", { cls: "hero-shade" })); box.appendChild(text); box.appendChild(dots);
    function background(layer, item, info) {
      layer.innerHTML = "";
      var bg = smaller(info.backdrop || item.backdrop);
      layer.appendChild(bg ? picture(bg, "poster-bg") : item.image ? picture(item.image, "poster-bg") : placeholder(item.title));
    }
    function words(item, info) {
      var had = box.contains(document.activeElement) ? currentKey() : null;
      text.innerHTML = "";
      var rank = S.shelves.topMovies.indexOf(item);
      text.appendChild(h("div", { cls: "hero-rank" }, rank >= 0 && rank < 10 ? [h("span", { cls: "badge", text: "TOP 10" }), h("span", { text: T("hero_rank", rank + 1) })] : []));
      text.appendChild(h("h1", { text: item.title }));
      text.appendChild(h("div", { cls: "hero-meta" }, [metaLine(item, info)]));
      text.appendChild(h("div", { cls: "hero-plot", text: info.plot || item.plot || "" }));
      text.appendChild(h("div", { cls: "hero-buttons" }, [
        button(T("play"), function () { play([item], 0); }, { primary: true, icon: "play", key: "hero-play" }),
        button(T("more_info"), function () { openDetail(item); }, { round: true, icon: "info", key: "hero-info" }),
        button(T("favorite"), function () { toggleFavorite(item); words(item, info); }, { round: true, icon: isFavorite(item.id) ? "heartFill" : "heart", key: "hero-fav" })]));
      dots.innerHTML = "";
      list.forEach(function (_, n) { dots.appendChild(h("span", { cls: n === hero.index ? "on" : "" })); });
      if (had) focus(box.querySelector('[data-key="' + had + '"]'));
    }
    var first = list[hero.index];
    background(layers[0], first, hero.info[first.id] || {});
    words(first, hero.info[first.id] || {});
    vodInfo(first).then(function (info) {
      if (list[hero.index] !== first) return;
      if ((info.backdrop || "") !== "") preload(smaller(info.backdrop), function () { background(layers[front], first, info); });
      words(first, info);
    });
    // the next film fades in every 9 seconds (not while you are on the banner's buttons); its picture is loaded first
    clearInterval(hero.timer);
    hero.timer = setInterval(function () {
      if (!box.parentNode) return clearInterval(hero.timer);
      if (box.contains(document.activeElement) || playerOpen() || sheetOpen() || box.getBoundingClientRect().bottom < 100) return;
      var next = (hero.index + 1) % list.length, item = list[next];
      vodInfo(item).then(function (info) {
        preload(smaller(info.backdrop || item.backdrop) || item.image, function () {
          if (!box.parentNode || box.contains(document.activeElement)) return;
          hero.index = next;
          var back = layers[1 - front];
          background(back, item, info);
          back.classList.add("on"); layers[front].classList.remove("on"); front = 1 - front;
          words(item, info);
        });
      });
    }, 20000);
    return box;
  }
  function greeting() {
    var hour = new Date().getHours(), name = currentProfile().name;
    var hi = T(hour < 12 ? "greet_morning" : hour < 18 ? "greet_afternoon" : "greet_evening");
    return name ? hi + ", " + name : hi;
  }
  function lastChannelCard() {
    var channel = find(S.recent[0] || load(pkey("last"), ""));
    if (!channel || channel.kind !== "live") return null;
    var now = h("div", { cls: "cont-now" });
    programsFor(channel, false).then(function (rows) {
      var nn = Guide.nowNext(rows);
      if (nn.now) now.textContent = T("now_on", nn.now.title);
    }, function () {});
    return h("div", { cls: "cont" }, [h("div", { cls: "logo-box big" }, [channel.image ? picture(channel.image) : h("span", { text: Catalog.initials(channel.title) })]),
      h("div", { cls: "cont-text" }, [h("div", { cls: "cont-label", text: T("continue_channel") }), h("div", { cls: "cont-title", text: channel.title }), now]),
      button(T("continue_btn"), function () { playChannel(channel); }, { primary: true, icon: "play", key: "cont-play" })]);
  }
  function discoverScreen() {
    var sh = S.shelves, rows = [];
    rows.push(h("div", { cls: "greet" }, [h("h1", { text: greeting() }), h("div", { cls: "hint", text: T("favorites_hint") })]));
    var cont = lastChannelCard(); if (cont) rows.push(cont);
    if (S.progress.length) {
      var items = S.progress.map(function (p) { return p.item; });
      rows.push(shelf(T("continue_watching"), S.progress.map(function (p, i) {
        var sub = p.item.kind === "episode" ? T("season", p.item.group) : "";
        return wide(p.item, function () { play(items, i); }, { progress: p.dur ? p.pos / p.dur : 0, sub: sub });
      })));
    }
    var favs = S.favorites.map(find).filter(visible);
    if (favs.length) {
      var favLive = favs.filter(function (x) { return x.kind === "live"; });
      rows.push(shelf(T("favorites"), favs.map(function (x) {
        return x.kind === "live" ? wide(x, function () { playChannel(x, favLive); }, { long: function () { toggleFavorite(x); render(); } })
          : poster(x, function () { open(x); });
      })));
    }
    var recent = S.recent.map(find).filter(function (x) { return visible(x) && x.kind === "live"; });
    if (recent.length > 1) rows.push(shelf(T("recent_channels"), recent.map(function (c) { return wide(c, function () { playChannel(c, recent); }); })));
    if (sh.uhdChannels.length) rows.push(shelf(T("uhd_channels"), sh.uhdChannels.map(function (c) { return wide(c, function () { playChannel(c, sh.uhdChannels); }); })));
    [["new_movies", sh.newMovies], ["top_movies", sh.topMovies]].forEach(function (pair) {
      if (pair[1].length) rows.push(shelf(T(pair[0]), pair[1].map(function (m) { return poster(m, function () { openDetail(m); }); })));
    });
    if (sh.newSeries.length) rows.push(shelf(T("new_series"), sh.newSeries.map(function (s) { return poster(s, function () { openSeries(s); }); })));
    if (!sh.movies.length && sh.live.length && !sh.uhdChannels.length) {
      var first = sh.live.slice(0, 30);
      rows.push(shelf(T("nav_live"), first.map(function (c) { return wide(c, function () { playChannel(c, first); }); })));
    }
    return h("div", { cls: "scroll-y" }, [heroBlock(), h("div", { cls: "page" }, rows)]);
  }

  // ---- live tv: groups, channels, what's on
  var liveGroup = null, infoTimer = null;
  function askHide(kind, group) {
    sheet({ title: T("hide_group_q", groupName(group)), text: T("hide_group_text"), items: [
      { label: T("hide_group"), go: function () {
        S.hidden.push(kind + "|" + group); psave("hidden", S.hidden); buildShelves(); closeSheet();
        if (kind === "live") liveGroup = null; else gridGroup[kind === "movie" ? "movies" : "series"] = "\u0000all";
        render(); toast(T("hidden_toast", groupName(group)));
      } },
      { label: T("cancel"), go: closeSheet }] });
  }
  /** Now / next of a channel in a card (Live TV page). */
  function nowCard(card, channel) {
    card.innerHTML = "";
    card.appendChild(h("div", { cls: "nc-head" }, [h("span", { cls: "lb-num", text: String(numberOf(channel) || "") }), h("span", { cls: "nc-name", text: channel.title }),
      Catalog.itemUhd(channel) ? h("span", { cls: "badge", text: "4K" }) : null, channel.archive ? withIcon("replay", T("catchup"), "lb-tag") : null]));
    var body = h("div", { cls: "nc-body" });
    card.appendChild(body);
    programsFor(channel, false).then(function (rows) {
      if (card._channel !== channel) return;
      var nn = Guide.nowNext(rows, nowSeconds(), 3);
      if (!nn.now && !nn.next.length) { body.appendChild(h("div", { cls: "empty", text: T("no_guide") })); return; }
      if (nn.now) {
        var p = nn.now;
        body.appendChild(h("div", { cls: "lb-now" }, [h("span", { cls: "lb-time", text: hm(p.start) + " – " + hm(p.end) }), h("span", { cls: "lb-title", text: p.title })]));
        body.appendChild(h("div", { cls: "lb-bar" }, [h("div", { style: "width:" + Math.round((nowSeconds() - p.start) / (p.end - p.start) * 100) + "%" })]));
        if (p.desc) body.appendChild(h("div", { cls: "nc-desc", text: p.desc }));
      }
      nn.next.forEach(function (n) { body.appendChild(h("div", { cls: "info-next" }, [h("span", { cls: "time", text: hm(n.start) }), h("span", { text: n.title })])); });
    });
  }
  function liveScreen() {
    var sh = S.shelves, FAV = "\u0000fav";
    var favLive = sh.live.filter(function (c) { return isFavorite(c.id); });
    var groups = (favLive.length ? [FAV] : []).concat(sh.liveGroups);
    if (liveGroup === null || groups.indexOf(liveGroup) < 0) {
      var found = find(S.recent[0]);
      liveGroup = found && sh.liveGroups.indexOf(found.group) >= 0 ? found.group : (sh.liveGroups[0] || "");
    }
    var channels = liveGroup === FAV ? favLive : sh.live.filter(function (c) { return c.group === liveGroup; });
    var groupList = h("div", { cls: "scroll-y" });
    lazyList(groupList, groups, function (g) {
      var name = g === FAV ? T("favorites") : groupName(g);
      return rowItem(name, function () { liveGroup = g; render(); focusFirst(".channels"); }, { lead: g === FAV ? icon("heartFill", "lead") : null, sel: g === liveGroup,
        badge: g !== FAV && Catalog.isUhd(g) ? "4K" : "", key: "g-" + g, long: g === FAV ? null : function () { askHide("live", g); } });
    }, 60);
    var slot = h("div", { cls: "mini-slot" }), card = h("div", { cls: "now-card" });
    var channelList = h("div", { cls: "scroll-y" });
    if (!channels.length) channelList.appendChild(h("div", { cls: "empty", text: T("empty_group") }));
    function pick(c, now) {
      card._channel = c;
      clearTimeout(infoTimer);
      infoTimer = setTimeout(function () {
        if (card._channel !== c) return;
        nowCard(card, c);
        // the small picture shows your channel (opening a stream for every channel you pass makes the TV slow)
        if (now) { clearTimeout(mini.follow); mini.follow = setTimeout(function () { if (slot.parentNode) miniPlay(c, slot); }, 1200); }
      }, now ? 0 : 250);
    }
    lazyList(channelList, channels, function (c) {
      var cached = epgCache[c.id], nn = cached && Guide.nowNext(cached.rows, nowSeconds(), 0);
      return rowItem(c.title, function () { if (mini.channel === c) miniToFull(); else playChannel(c, channels); }, {
        image: c.image || "", lead: h("span", { cls: "zap-num", text: String(numberOf(c) || "") }), sub: nn && nn.now ? nn.now.title : " ",
        badge: Catalog.itemUhd(c) ? "4K" : "", trail: isFavorite(c.id) ? icon("heartFill") : "", key: "c-" + c.id,
        long: function () { toggleFavorite(c); render(); },
        onfocus: function () { pick(c, false); },
      });
    });
    var last = find(S.recent[0]);
    var start = (mini.channel && channels.indexOf(mini.channel) >= 0) ? mini.channel : last && channels.indexOf(last) >= 0 ? last : channels[0];
    if (start) setTimeout(function () { if (slot.parentNode) pick(start, true); }, 30);
    return h("div", { cls: "live" }, [
      h("div", { cls: "groups" }, [h("h2", { text: T("groups"), style: "padding-left:24px" }), groupList]),
      h("div", { cls: "channels" }, [h("h2", { style: "padding-left:24px" }, [liveGroup === FAV ? T("favorites") : groupName(liveGroup),
        h("span", { cls: "hint", text: T("hold_ok_favorite") })]), channelList]),
      h("div", { cls: "info-col" }, [slot, card])]);
  }

  // ---- the guide of one channel, with catch-up and reminders
  function channelGuideScreen(channel) {
    var list = h("div", { cls: "guide-list scroll-y" }, [h("div", { cls: "spinner" })]);
    var desc = h("div", { cls: "guide-desc" });
    programsFor(channel, true).then(function (rows) {
      if (S.guideFor !== channel) return;
      list.innerHTML = "";
      var now = nowSeconds();
      if (!rows.length) { list.appendChild(h("div", { cls: "empty", text: T("no_guide") })); return; }
      var lastDay = "", current = null;
      rows.forEach(function (p) {
        var day = dayName(p.start);
        if (day !== lastDay) { list.appendChild(h("div", { cls: "day", text: day })); lastDay = day; }
        var live = p.start <= now && p.end > now, past = p.end <= now, back = past && Guide.canCatchUp(channel, p, now);
        var trail = live ? withIcon("dot", T("now"), "red") : back ? withIcon("replay", T("catchup")) : !past && reminderFor(channel, p) ? icon("bell") : "";
        var el = rowItem(p.title || "—", function () {
          if (live) playChannel(channel);
          else if (back) playCatchup(channel, p);
          else if (!past) { toggleReminder(channel, p); render(); }
        }, { time: hm(p.start), trail: trail, cls: (past && !back ? "past" : "") + (live ? " live-now" : ""), key: "p-" + p.start,
          onfocus: function () {
            desc.innerHTML = "";
            desc.appendChild(h("div", { cls: "info-label", text: dayName(p.start) + " · " + hm(p.start) + " – " + hm(p.end) }));
            desc.appendChild(h("div", { cls: "info-now", text: p.title }));
            if (p.desc) desc.appendChild(h("div", { cls: "info-desc", text: p.desc }));
            desc.appendChild(h("div", { cls: "info-hint", text: live ? T("ok_watch") : back ? T("ok_catchup") : past ? "" : T("ok_remind") }));
          } });
        list.appendChild(el);
        if (live) current = el;
      });
      if (!sheetOpen() && !playerOpen()) focus(current || focusables(list)[0]);
    });
    return h("div", { cls: "guide" }, [
      h("div", { cls: "guide-head" }, [h("div", { cls: "logo-box big" }, [channel.image ? picture(channel.image) : h("span", { text: Catalog.initials(channel.title) })]),
        h("h1", { text: channel.title }), button(T("watch_live"), function () { playChannel(channel); }, { primary: true, icon: "play", key: "guide-live" })]),
      h("div", { cls: "guide-body" }, [list, desc])]);
  }
  function playCatchup(channel, p) {
    var base = Catalog.base(S.source.server);
    play([{ id: channel.id + "|" + p.start, kind: "catchup", title: channel.title + " · " + p.title, image: channel.image,
      url: Guide.timeshiftUrl(base, S.source.user, S.source.password, channel.sid, p) }], 0);
  }

  // ---- tv guide: a time grid like Zono for Windows (channels down, time across)
  var TVG = { group: "\u0000all", day: 0, offset: null, ppm: 8 }; // ppm: pixels per minute
  var tvgRunning = 0, tvgWaiting = [];
  function limited(task) { // at most 4 guide requests at the same time
    return new Promise(function (resolve) {
      function go() { tvgRunning++; task().then(done, done); }
      function done(v) { tvgRunning--; resolve(v); var next = tvgWaiting.shift(); if (next) next(); }
      if (tvgRunning < 4) go(); else tvgWaiting.push(go);
    });
  }
  function dayStart(day) { var d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() + day); return d.getTime() / 1000; }
  function tvGuideScreen() {
    var sh = S.shelves, ppm = TVG.ppm, channels = sh.live;
    var start = dayStart(TVG.day), full = 24 * 60 * ppm, view = 1060;
    var nowX = (nowSeconds() - start) / 60 * ppm;
    if (TVG.offset === null) TVG.offset = TVG.day === 0 ? nowX - 30 * ppm : (new Date().getHours() * 60 - 30) * ppm;
    TVG.offset = Math.max(0, Math.min(full - view, TVG.offset));
    var lanes = [];
    function apply() { lanes.forEach(function (l) { l.style.transform = "translateX(" + (-TVG.offset) + "px)"; }); }
    var info = h("div", { cls: "tvg-info" }, [h("div", { cls: "hint", text: T("guide_intro") })]);
    function show(channel, p) {
      var live = p.start <= nowSeconds() && p.end > nowSeconds(), past = p.end <= nowSeconds(), back = past && Guide.canCatchUp(channel, p);
      info.innerHTML = "";
      info.appendChild(h("div", { cls: "info-label", text: numberOf(channel) + " " + channel.title + " · " + dayName(p.start) + " " + hm(p.start) + " – " + hm(p.end) }));
      info.appendChild(h("div", { cls: "info-now", text: p.title }));
      if (p.desc) info.appendChild(h("div", { cls: "info-desc", text: p.desc }));
      info.appendChild(h("div", { cls: "info-hint", text: live ? (mini.channel === channel ? T("ok_full") : T("ok_preview")) : back ? T("ok_catchup") : past ? "" : T("ok_remind") }));
    }
    var slot = h("div", { cls: "mini-slot guide-mini" });
    var days = [[-2, "day_before"], [-1, "yesterday"], [0, "today"], [1, "tomorrow"]].map(function (d) {
      return h("div", { cls: "pill small" + (TVG.day === d[0] ? " sel" : ""), go: function () { TVG.day = d[0]; TVG.offset = null; render(); }, "data-key": "td" + d[0] },
        [d[0] < 0 ? icon("replay", "lead") : null, T(d[1])]);
    });
    var tools = h("div", { cls: "tvg-tools" }, days.concat([
      h("div", { cls: "pill small", go: function () { TVG.day = 0; TVG.offset = null; render(); focusFirst(".tvg-box.now"); }, "data-key": "t-now" }, [icon("clock", "lead"), T("now")]),
      h("div", { cls: "tvg-space" }), keyHint(["1", "2"], T("channel_number_jump"))]));
    var ruler = h("div", { cls: "tvg-lane ruler", style: "width:" + full + "px" });
    for (var m = 0; m < 24 * 60; m += 30) ruler.appendChild(h("div", { cls: "tick", style: "left:" + (m * ppm) + "px", text: (m / 60 < 10 ? "0" : "") + Math.floor(m / 60) + ":" + (m % 60 ? "30" : "00") }));
    if (TVG.day === 0) ruler.appendChild(h("div", { cls: "now-label", style: "left:" + nowX + "px", text: hm(nowSeconds()) }));
    lanes.push(ruler);
    var body = h("div", { cls: "tvg-body scroll-y" });
    if (!channels.length) body.appendChild(h("div", { cls: "empty", text: T("empty_group") }));
    /** OK on what is on now: first in the small picture, a second OK: full screen. */
    function watch(channel) { if (mini.channel === channel) miniToFull(); else miniPlay(channel, slot); }
    lazyList(body, channels, function (channel) {
      var lane = h("div", { cls: "tvg-lane", style: "width:" + full + "px" });
      if (TVG.day === 0) lane.appendChild(h("div", { cls: "now-line", style: "left:" + nowX + "px" }));
      lanes.push(lane);
      lane.style.transform = "translateX(" + (-TVG.offset) + "px)";
      var cell = h("div", { cls: "tvg-channel", go: function () { watch(channel); }, "data-key": "tc-" + channel.id }, [
        h("span", { cls: "num", text: String(numberOf(channel)) }), h("div", { cls: "logo-box" }, [channel.image ? picture(channel.image) : h("span", { text: Catalog.initials(channel.title) })]),
        h("span", { cls: "cname", text: channel.title })]);
      var shownStarts = {}, any = false;
      function addBox(p) {
        var end = start + 86400, now = nowSeconds();
        if (p.end <= start || p.start >= end || shownStarts[p.start]) return;
        shownStarts[p.start] = 1; any = true;
        var left = Math.max(0, (p.start - start) / 60 * ppm), right = Math.min(full, (p.end - start) / 60 * ppm);
        var live = p.start <= now && p.end > now, past = p.end <= now, back = past && Guide.canCatchUp(channel, p, now);
        var bell = icon("bell", "lead"); bell.hidden = !reminderFor(channel, p);
        var box = h("div", { cls: "tvg-box" + (live ? " now" : "") + (past && !back ? " past" : ""), style: "left:" + left + "px;width:" + Math.max(24, right - left - 6) + "px",
          "data-key": "tb-" + channel.id + "-" + p.start,
          go: function () {
            if (live) { watch(channel); show(channel, p); }
            else if (back) { stopMini(); playCatchup(channel, p); }
            else if (!past) { toggleReminder(channel, p); bell.hidden = !reminderFor(channel, p); }
          },
          long: function () { openGuide(channel); },
          onfocus: function () {
            if (left < TVG.offset + 20 && right < TVG.offset + 260 || left > TVG.offset + view - 160) { TVG.offset = Math.max(0, Math.min(full - view, left - 60)); apply(); }
            show(channel, p);
            // today first shows now and next (quick); the earlier programmes come in when you are on the row
            if (!lane._full) { lane._full = true; limited(function () { return programsFor(channel, true); }).then(function (all) { (all || []).forEach(addBox); }); }
          } });
        box.appendChild(h("div", { cls: "t" }, [bell, back ? icon("replay", "lead") : null, live ? icon("dot", "lead red") : null, p.title || "—"]));
        box.appendChild(h("div", { cls: "s", text: hm(p.start) + " – " + hm(p.end) }));
        lane.appendChild(box);
      }
      lane._full = true;
      limited(function () { return programsFor(channel, true); }).then(function (rows) {
        (rows || []).forEach(addBox);
        if (!any) lane.appendChild(h("div", { cls: "tvg-none", style: "left:" + TVG.offset + "px", text: T("no_guide") }));
        if (TVG.jump === channel) { TVG.jump = null; focus(lane.querySelector(".tvg-box.now") || cell); }
      });
      return h("div", { cls: "tvg-row", "data-channel": channel.id }, [cell, h("div", { cls: "tvg-track" }, [lane])]);
    }, 25);
    var first = (mini.channel && channels.indexOf(mini.channel) >= 0) ? mini.channel : find(S.recent[0]) || channels[0];
    if (first) setTimeout(function () { if (slot.parentNode) miniPlay(first, slot); }, 400);
    TVG.body = body;
    return h("div", { cls: "tvg" }, [
      h("div", { cls: "tvg-head" }, [h("div", { cls: "tvg-left" }, [h("h1", { text: T("nav_guide") }), info]), slot]),
      tools,
      h("div", { cls: "tvg-row ruler-row" }, [h("div", { cls: "tvg-channel blank" }), h("div", { cls: "tvg-track" }, [ruler])]),
      body]);
  }
  /** A channel number typed on the TV guide: the grid goes to that channel and the small picture shows it. */
  function guideJump(channel) {
    var body = TVG.body;
    if (!body || !body.parentNode) return;
    var tries = 0, row;
    while (!(row = body.querySelector('[data-channel="' + (window.CSS && CSS.escape ? CSS.escape(channel.id) : channel.id) + '"]')) && body._more && tries++ < 2000) {
      var before = body.children.length; body._more(); if (body.children.length === before) break;
    }
    if (!row) return toast(T("no_channel", numberOf(channel)));
    TVG.jump = channel;
    var box = row.querySelector(".tvg-box.now");
    focus(box || row.querySelector(".tvg-channel"));
    if (box) TVG.jump = null;
    var slot = app.querySelector(".guide-mini");
    if (slot) miniPlay(channel, slot);
  }

  // ---- movies and series
  var gridGroup = { movies: "\u0000all", series: "\u0000all" };
  function gridScreen(kind, items, groups, openOne) {
    var ALL = "\u0000all", current = gridGroup[kind];
    if (current !== ALL && groups.indexOf(current) < 0) current = gridGroup[kind] = ALL;
    var cache = S.shelves._sorted || (S.shelves._sorted = {});
    var chosen = S.countries, rank = function (i) { var k = chosen.indexOf(i.cc || ""); return k < 0 ? chosen.length : k; };
    var shown = current === ALL ? (cache[kind] || (cache[kind] = items.slice().sort(function (a, b) { return (chosen.length ? rank(a) - rank(b) : 0) || (b.added || 0) - (a.added || 0); })))
      : items.filter(function (i) { return i.group === current; });
    var hideKind = kind === "movies" ? "movie" : "series";
    var pills = h("div", { cls: "scroll-x", style: "padding:12px 8px" }, [pill(T("all"), current === ALL, function () { gridGroup[kind] = ALL; render(); }, "p-all")]
      .concat(groups.map(function (g) {
        return pill(groupName(g), g === current, function () { gridGroup[kind] = g; render(); }, "p-" + g, function () { askHide(hideKind, g); });
      })));
    var grid = h("div", { cls: "grid" });
    if (!shown.length) grid.appendChild(h("div", { cls: "empty", text: T("empty_group") }));
    lazyList(grid, shown, function (item) { return poster(item, function () { openOne(item); }); }, 50);
    return h("div", { cls: "scroll-y" }, [h("div", { cls: "page", style: "padding-top:44px" }, [h("div", { cls: "hint", style: "margin:0 0 8px 12px", text: T("hold_hint") }), pills, grid])]);
  }
  function moviesScreen() { return gridScreen("movies", S.shelves.movies, S.shelves.movieGroups, openDetail); }
  function seriesListScreen() { return gridScreen("series", S.shelves.series, S.shelves.seriesGroups, openSeries); }

  function detailScreen(item) {
    var box = h("div", { cls: "detail" });
    function draw(info) {
      var p = progressOf(item.id);
      box.innerHTML = "";
      var bg = smaller(info.backdrop || item.backdrop);
      box.appendChild(h("div", { cls: "hero-bg" }, [bg ? picture(bg) : (item.image ? picture(item.image, "blur") : null)]));
      box.appendChild(h("div", { cls: "hero-shade full" }));
      var buttons = [];
      if (p && p.dur) {
        buttons.push(button(T("continue_at", Math.round(p.pos / p.dur * 100) + "%"), function () { play([item], 0); }, { primary: true, icon: "play", key: "d-play" }));
        buttons.push(button(T("from_start"), function () { saveProgress(item, 0, p.dur); play([item], 0); }, { icon: "replay", key: "d-start" }));
      } else buttons.push(button(T("play"), function () { play([item], 0); }, { primary: true, icon: "play", key: "d-play" }));
      buttons.push(button(isFavorite(item.id) ? T("favorited") : T("favorite"), function () { toggleFavorite(item); draw(info); focus(box.querySelector('[data-key="d-fav"]')); },
        { icon: isFavorite(item.id) ? "heartFill" : "heart", key: "d-fav" }));
      box.appendChild(h("div", { cls: "detail-body" }, [
        h("div", { cls: "cover" }, [placeholder(item.title), picture(info.cover || item.image)]),
        h("div", { cls: "detail-text" }, [h("h1", { text: item.title }), h("div", { cls: "hero-meta" }, [metaLine(item, info)]),
          info.plot || item.plot ? h("div", { cls: "detail-plot", text: info.plot || item.plot }) : null,
          info.director ? h("div", { cls: "detail-small" }, [h("b", { text: T("director") + ": " }), info.director]) : null,
          info.cast ? h("div", { cls: "detail-small" }, [h("b", { text: T("cast") + ": " }), String(info.cast).slice(0, 220)]) : null,
          p && p.dur ? h("div", { cls: "detail-progress" }, [bar(p.pos / p.dur)]) : null,
          h("div", { cls: "hero-buttons" }, buttons)])]));
    }
    draw(hero.info[item.id] || {});
    vodInfo(item).then(function (info) {
      if (S.detail !== item) return;
      var had = currentKey(); draw(info);
      var el = had && box.querySelector('[data-key="' + had + '"]'); focus(el || box.querySelector(".btn"));
    });
    return box;
  }

  var episodeCache = {}, season = {};
  function forPlayer(ep, series) {
    var name = ep.title ? ep.number + ". " + ep.title : "E" + ep.number;
    var copy = {}; for (var k in ep) copy[k] = ep[k];
    copy.title = series.title + " · " + name;
    copy.image = ep.image || series.image;
    copy.series = series.title;
    return copy;
  }
  function seriesScreen(series) {
    var eps = h("div", { cls: "eps" });
    var list = episodeCache[series.id];
    if (list === undefined) {
      eps.appendChild(h("div", { cls: "spinner" }));
      episodeCache[series.id] = null;
      json(Catalog.apiUrl(S.source, "get_series_info", { series_id: series.sid })).then(function (data) {
        episodeCache[series.id] = Catalog.episodes(data, S.source);
      }, function () { episodeCache[series.id] = "failed"; }).then(function () {
        if (S.series === series) { render(); focusFirst(".eps"); }
      });
    } else if (list === null) {
      eps.appendChild(h("div", { cls: "spinner" }));
    } else if (list === "failed" || !list.length) {
      eps.appendChild(h("div", { cls: "empty", text: T(list === "failed" ? "playback_error" : "no_episodes") }));
    } else {
      var seasons = []; list.forEach(function (e) { if (seasons.indexOf(e.group) < 0) seasons.push(e.group); });
      var now = season[series.id] && seasons.indexOf(season[series.id]) >= 0 ? season[series.id] : seasons[0];
      var inSeason = list.filter(function (e) { return e.group === now; });
      var queue = inSeason.map(function (e) { return forPlayer(e, series); });
      eps.appendChild(h("div", { cls: "scroll-x" }, seasons.map(function (s) {
        return pill(T("season", s), s === now, function () { season[series.id] = s; render(); }, "s-" + s);
      })));
      var rows = h("div", { cls: "scroll-y" });
      lazyList(rows, inSeason, function (e, i) {
        var p = progressOf(e.id);
        return rowItem(e.title ? e.number + ". " + e.title : T("episode", e.number), function () { play(queue, i); },
          { trail: p && p.dur ? Math.round(p.pos / p.dur * 100) + "%" : "", key: "e-" + e.id });
      });
      eps.appendChild(rows);
    }
    var info = hero.info[series.id];
    if (!info) vodInfo(series);
    return h("div", { cls: "series" }, [
      h("div", { cls: "info" }, [h("div", { cls: "cover" }, [placeholder(series.title), picture(series.image)]), h("h1", { text: series.title }),
        series.rating > 0 ? h("div", { cls: "gold" }, [withIcon("star", String(series.rating))]) : null, series.plot ? h("div", { cls: "plot", text: series.plot }) : null,
        h("div", { style: "margin-top:24px" }, [button(isFavorite(series.id) ? T("favorited") : T("favorite"), function () { toggleFavorite(series); render(); },
          { icon: isFavorite(series.id) ? "heartFill" : "heart", key: "s-fav" })])]),
      eps]);
  }

  // ---- search: titles and the tv guide
  var query = "", searchTimer = null;
  function searchScreen() {
    var field = input(query, T("search_hint"), function (v) { query = v; clearTimeout(searchTimer); searchTimer = setTimeout(fill, 300); }, { key: "search", style: "width:1000px" });
    var results = h("div");
    var round = 0;
    function fill() {
      // the titles are searched in pieces of 8,000, so typing stays smooth with a huge library
      var mine = ++round, w = Catalog.words(query), found = [], all = S.shelves.all, at = 0;
      if (!w.length) return show(found);
      (function piece() {
        if (mine !== round) return;
        var end = Math.min(all.length, at + 8000);
        for (; at < end && found.length < 60; at++) if (Catalog.matches(all[at], w)) found.push(all[at]);
        if (at < all.length && found.length < 60) setTimeout(piece, 0); else show(found);
      })();
    }
    function show(found) {
      results.innerHTML = "";
      var live = found.filter(function (i) { return i.kind === "live"; });
      if (found.length) {
        var grid = h("div", { cls: "grid" });
        found.forEach(function (item) { grid.appendChild(poster(item, function () { open(item, live, live.indexOf(item)); })); });
        results.appendChild(grid);
      }
      if (query.trim().length >= 3) {
        var tv = h("div", { cls: "search-tv" }, [h("h2", { text: T("on_tv") })]);
        results.appendChild(tv);
        var status = h("div", { cls: "empty", text: T("guide_loading") });
        tv.appendChild(status);
        var asked = query;
        loadXmltv(true).then(function (url) {
          if (!url) return { ok: false, hits: [] };
          return work({ type: "gsearch", url: url, query: asked });
        }).then(function (answer) {
          if (asked !== query) return;
          var hits = (answer.hits || []).map(function (h) { return { channel: find(h.channel), program: h.program }; }).filter(function (h) { return h.channel; });
          status.textContent = !answer.ok ? T(xmltv.state === "big" ? "guide_too_big" : "no_guide_search") : hits.length ? "" : T("no_results");
          hits.forEach(function (hit) {
            var p = hit.program, c = hit.channel, live = p.start <= nowSeconds();
            tv.appendChild(rowItem(p.title, function () { if (live) playChannel(c); else { toggleReminder(c, p); fill(); } },
              { image: c.image || "", time: dayName(p.start) + " " + hm(p.start), sub: c.title, trail: live ? withIcon("dot", T("now"), "red") : reminderFor(c, p) ? icon("bell") : "", key: "t-" + c.id + p.start }));
          });
        });
      } else if (query.trim() && !found.length) results.appendChild(h("div", { cls: "empty", text: T("no_results") }));
    }
    fill();
    return h("div", { cls: "scroll-y" }, [h("div", { cls: "page" }, [field, results])]);
  }

  // ---- settings
  function settingsScreen() {
    var source = S.source, chosen = load("language", ""), me = currentProfile(), kids = !!me.kids;
    var where = source.type === "xtream" ? source.user + " @ " + Catalog.base(source.server).replace(/^https?:\/\//, "")
      : source.m3u.replace(/^https?:\/\//, "").split("/")[0];
    var parts = [
      h("h2", { text: T("language") }),
      h("div", { cls: "scroll-x", style: "padding:8px;margin-bottom:44px" }, LANGS.map(function (l) {
        return pill(l[1] || T("language_system"), l[0] === chosen, function () { save("language", l[0]); pickLanguage(); render(); }, "lang-" + l[0]);
      })),
      h("h2", { text: T("nav_live") }),
      rowItem(T("uhd_first"), function () { S.uhd = !S.uhd; save("uhd", S.uhd); buildShelves(); render(); }, { trail: T(S.uhd ? "on" : "off"), key: "uhd" }),
      rowItem(T("reminders"), remindersSheet, { trail: String(S.reminders.length), key: "reminders" }),
      rowItem(T("countries_first"), countriesSheet, { trail: S.countries.length ? S.countries.join(", ") : T("all"), key: "countries" }),
      h("h2", { text: T("subtitles"), style: "margin-top:44px" }),
      rowItem(T("sub_language"), function () {
        sheet({ title: T("sub_language"), items: [["nl", "Nederlands"], ["fr", "Français"], ["en", "English"], ["de", "Deutsch"]].map(function (l) {
          return { label: l[1], sel: subLanguage() === l[0], go: function () { save("subLang", l[0]); closeSheet(); render(); } };
        }) });
      }, { trail: subLanguage().toUpperCase(), key: "sublang" }),
      rowItem(T("sub_key"), subsKeySheet, { trail: load("opensubtitles", "") ? icon("check") : T("off"), key: "subkey" }),
    ];
    if (!kids) {
      parts.push(h("h2", { text: T("profiles"), style: "margin-top:44px" }));
      profiles().forEach(function (p) {
        parts.push(h("div", { cls: "row-item", go: function () { profileSheet(p); }, "data-key": "prof-" + p.id },
          [avatar(p), h("div", { cls: "name" }, [(p.name || T("profile_default")) + (p.kids ? " · " + T("kids_profile") : ""), p.pin ? icon("lock", "after") : null]),
            p.id === me.id ? h("span", { cls: "trail" }, [icon("check")]) : null]));
      });
      parts.push(rowItem("+ " + T("add_profile"), function () { nameSheet(T("add_profile"), "", function (name) {
        var list = profiles(); list.push({ id: hexId(6), name: name, color: list.length % PROFILE_COLORS.length }); saveProfiles(list); render();
      }); }, { key: "prof-add" }));
      parts.push(rowItem(T("hidden_groups"), hiddenSheet, { trail: String(S.hidden.length), key: "hidden" }));
      parts.push(h("h2", { text: T("account"), style: "margin-top:44px" }));
      parts.push(h("div", { cls: "empty", text: where }));
      parts.push(rowItem(T("refresh"), function () {
        toast(T("loading"));
        refresh(S.source, true).then(function (ok) { toast(ok ? T("library_updated") : T("error_connect", "")); });
      }, { key: "refresh" }));
      parts.push(rowItem(T("logout"), function () {
        sheet({ title: T("logout") + "?", items: [{ label: T("logout"), go: function () {
          closeSheet();
          S.source = null; save("source", null); save("guideUrl", null);
          S.items = []; buildShelves(); S.page = "discover"; db.put("library", undefined); db.put("xmltv", undefined); epgCache = {}; xmltv = { state: "off" };
          render();
        } }, { label: T("cancel"), go: closeSheet }] });
      }, { key: "logout" }));
    }
    parts.push(h("h2", { text: T("privacy"), style: "margin-top:44px" }));
    parts.push(rowItem(T("stats"), function () { save("share", !sharing()); render(); }, { trail: T(sharing() ? "on" : "off"), sub: T("stats_text"), key: "share" }));
    parts.push(rowItem(T("report"), reportSheet, { key: "report" }));
    parts.push(h("div", { cls: "empty", style: "margin-top:44px;color:var(--dim)", text: T("version", VERSION) + " · zono.be/privacy.html" }));
    return h("div", { cls: "scroll-y" }, [h("div", { cls: "page", style: "max-width:1300px" }, parts)]);
  }
  /** Which countries first: the ones in this library, most channels and films first. */
  function countriesSheet() {
    var count = {};
    S.items.forEach(function (i) { if (i.cc) count[i.cc] = (count[i.cc] || 0) + 1; });
    var codes = Object.keys(count).sort(function (a, b) { return count[b] - count[a]; }).slice(0, 24);
    S.countries.forEach(function (c) { if (codes.indexOf(c) < 0) codes.unshift(c); });
    function toggle(code) {
      var at = S.countries.indexOf(code);
      if (at >= 0) S.countries.splice(at, 1); else S.countries.push(code);
      psave("countries", S.countries); countriesSheet();
    }
    sheet({ title: T("countries_first"), text: T("countries_text"), wide: true, onClose: function () { buildShelves(); render(); }, items: [
      { label: T("all"), sel: !S.countries.length, trail: !S.countries.length ? icon("check") : "", go: function () { S.countries = []; psave("countries", []); countriesSheet(); } }]
      .concat(codes.map(function (c) {
        var n = S.countries.indexOf(c);
        return { label: Countries.name(c, lang), sub: (count[c] || 0).toLocaleString(lang) + " · " + c, sel: n >= 0, trail: n >= 0 ? String(n + 1) : "", key: "cc-" + c, go: function () { toggle(c); } };
      })).concat([{ label: T("done"), go: closeSheet }]) });
    var keep = sheetEl.querySelector(".row-item.sel"); if (keep) focus(keep);
  }
  function remindersSheet() {
    var items = S.reminders.map(function (r) {
      return { label: r.title, sub: r.channelTitle + " · " + dayName(r.start) + " " + hm(r.start), trail: icon("close"), go: function () {
        S.reminders.splice(S.reminders.indexOf(r), 1); psave("reminders", S.reminders); closeSheet(); remindersSheet(); render();
      } };
    });
    sheet({ title: T("reminders"), text: items.length ? T("reminders_text") : T("no_reminders"), items: items.concat([{ label: T("close"), go: closeSheet }]), onClose: render });
  }
  function hiddenSheet() {
    var items = S.hidden.map(function (key) {
      var parts = key.split("|"), kind = parts.shift(), group = parts.join("|");
      return { label: groupName(group), sub: T(kind === "live" ? "nav_live" : kind === "movie" ? "nav_movies" : "nav_series"), trail: T("show_again"), go: function () {
        S.hidden.splice(S.hidden.indexOf(key), 1); psave("hidden", S.hidden); buildShelves(); closeSheet(); hiddenSheet();
      } };
    });
    sheet({ title: T("hidden_groups"), text: items.length ? T("hold_hint") : T("hidden_none"), items: items.concat([{ label: T("close"), go: closeSheet }]), onClose: render });
  }
  function nameSheet(title, value, done) {
    var name = value;
    var field = input(value, T("profile_name"), function (v) { name = v; }, { key: "name" });
    sheet({ title: title, content: [field], items: [{ label: T("save"), go: function () { if (name.trim()) { closeSheet(); done(name.trim().slice(0, 20)); } } },
      { label: T("cancel"), go: closeSheet }] });
  }
  function profileSheet(p) {
    function update(change) { var list = profiles().map(function (x) { if (x.id === p.id) change(x); return x; }); saveProfiles(list); closeSheet(); render(); }
    var items = [];
    if (p.id !== currentProfile().id) items.push({ label: T("switch_profile"), go: function () { closeSheet(); enterProfile(p); } });
    items.push({ label: T("rename"), go: function () { closeSheet(); nameSheet(T("rename"), p.name, function (n) { p.name = n; update(function (x) { x.name = n; }); }); } });
    items.push({ label: T("kids_profile"), trail: T(p.kids ? "on" : "off"), go: function () { update(function (x) { x.kids = !x.kids; }); if (p.id === profileId) { p.kids = !p.kids; buildShelves(); render(); } } });
    items.push({ label: p.pin ? T("pin_change") : T("pin_set"), go: function () {
      closeSheet();
      pinSheet(T("new_pin"), function (pin) { closeSheet(); update(function (x) { x.pin = hashPin(pin, x.id); }); toast(T("pin_saved")); });
    } });
    if (p.pin) items.push({ label: T("pin_remove"), go: function () { update(function (x) { delete x.pin; }); } });
    if (profiles().length > 1 && p.id !== "main") items.push({ label: T("delete"), go: function () {
      saveProfiles(profiles().filter(function (x) { return x.id !== p.id; }));
      ["progress", "favorites", "recent", "reminders", "hidden"].forEach(function (k) { save("p." + p.id + "." + k, null); });
      if (p.id === profileId) { save("profile", "main"); loadProfileData(); buildShelves(); }
      closeSheet(); render();
    } });
    items.push({ label: T("close"), go: closeSheet });
    sheet({ title: p.name || T("profile_default"), items: items });
  }
  function subsKeySheet() {
    var key = load("opensubtitles", "");
    var box = h("div", { cls: "phone small" });
    function draw() { box.innerHTML = ""; box.appendChild(qrBox()); box.appendChild(h("div", { cls: "phone-text", text: T("sub_key_steps") })); }
    draw();
    startPairing("subs", function () { if (sheetOpen()) { var keep = currentKey(); draw(); if (keep) focus(sheetEl.querySelector('[data-key="' + keep + '"]')); } });
    sheet({ title: T("sub_key"), text: T("sub_key_missing"), wide: true, content: [box], items: [
      key ? { label: T("sub_key_remove"), go: function () { save("opensubtitles", null); closeSheet(); render(); } } : null,
      { label: T("close"), go: closeSheet }], onClose: function () { stopPairing(); pair.mode = "login"; pair.onChange = null; render(); } });
  }

  // ---- report a problem, anonymous statistics
  function platform() {
    var ua = navigator.userAgent || "", chrome = /Chrome\/(\d+)/.exec(ua);
    return ((/Web0S|webOS/i.test(ua) ? "LG webOS" : "TV browser") + (chrome ? " (Chrome " + chrome[1] + ")" : "")).slice(0, 40);
  }
  /** A technical overview for "Report a problem": no logins, nothing about what is watched. */
  function diagnostics() {
    var mem = performance.memory, sh = S.shelves, lines = [
      "Zono for LG TV " + VERSION + " · " + platform(),
      "browser: " + navigator.userAgent,
      "screen: " + window.innerWidth + "x" + window.innerHeight + " · zoom " + (document.documentElement.style.zoom || "1"),
      "running: " + Math.round((Date.now() - STARTED) / 60000) + " min · page: " + where(),
      mem ? "memory: " + Math.round(mem.usedJSHeapSize / 1048576) + " MB used of " + Math.round(mem.jsHeapSizeLimit / 1048576) + " MB" : "memory: (unknown)",
      "provider: " + (S.source ? S.source.type : "none") + " · library: " + S.items.length + " items, " + sh.live.length + " channels, " + sh.movies.length + " films, " + sh.series.length + " series, " + sh.liveGroups.length + " channel groups",
      "last refresh: " + (load("refreshedAt", 0) ? Math.round((Date.now() - load("refreshedAt", 0)) / 60000) + " min ago" : "never"),
      "settings: language " + lang + ", 4K first " + S.uhd + ", countries " + (S.countries.join(",") || "all") + ", profiles " + profiles().length + (currentProfile().kids ? " (kids)" : "") + ", hidden groups " + S.hidden.length,
      "guide cache: " + Object.keys(epgCache).length + " channels · xmltv: " + xmltv.state + " · worker: " + (worker ? "on" : "off"),
    ];
    return lines.join("\n");
  }
  function sharing() { return load("share", true) !== false; }
  function installId() { var id = load("installId", ""); if (!/^[0-9a-f]{32}$/.test(id)) { id = hexId(16); save("installId", id); } return id; }
  function ping() {
    if (!sharing() || !window.nacl) return;
    var day = new Date().toISOString().slice(0, 10);
    if (load("pinged", "") === day) return;
    post(API + "/ping.php", { id: installId(), version: VERSION, language: lang, windows: platform() }).then(function () { save("pinged", day); }, function () {});
  }
  function reportSheet() {
    var message = "";
    var field = input("", T("message"), function (v) { message = v; }, { key: "report-msg" });
    sheet({ title: T("report"), text: T("report_text"), content: [field], items: [{ label: T("send"), go: function () {
      closeSheet(); toast(T("loading"));
      post(API + "/report.php", { version: VERSION, language: lang, windows: platform(), message: message || "(LG TV)", log: diagnostics() + "\n\n--- log ---\n" + LOG.join("\n") })
        .then(function (a) { toast(T("report_sent", a.number || "?")); }, function (problem) {
          log("report: " + (problem && problem.message));
          toast(problem && problem.status === 429 ? T("report_limit") : T("report_failed") + " (" + ((problem && problem.message) || "?") + ")");
        });
    } }, { label: T("cancel"), go: closeSheet }] });
  }

  // ------------------------------------------------------------------ focus and remote control
  function focusables(scope) {
    var list = (scope || document).querySelectorAll(".f");
    var out = [];
    for (var i = 0; i < list.length; i++) if (list[i].offsetParent !== null) out.push(list[i]);
    return out;
  }
  function focus(el) {
    if (!el) return;
    try { el.focus({ preventScroll: true }); } catch (e) { el.focus(); }
    reveal(el);
    if (el._near) { var more = el._near; el._near = null; more(); }
  }
  function currentKey() { var a = document.activeElement; return a && a.getAttribute ? a.getAttribute("data-key") : null; }
  function restoreFocus(key) {
    if (!playerOpen() && key) {
      var el = app.querySelector('[data-key="' + (window.CSS && CSS.escape ? CSS.escape(key) : key) + '"]');
      if (el) return focus(el);
    }
    if (!app.contains(document.activeElement) || document.activeElement === document.body) {
      var sel = app.querySelector(".menu .row-item.sel") || focusables(app)[0];
      focus(sel);
    }
  }
  function focusFirst(selector) {
    var scope = app.querySelector(selector);
    var first = scope && (scope.classList.contains("f") ? scope : scope.querySelector(".f.sel") || focusables(scope)[0]);
    if (first) focus(first);
  }

  /** Keeps the focused element visible in its scrolling boxes. */
  function reveal(el) {
    var node = el.parentElement;
    while (node && node !== document.body) {
      if (node.classList.contains("scroll-y") || node.classList.contains("scroll-x")) {
        var box = node.getBoundingClientRect(), r = el.getBoundingClientRect(), margin = 60;
        if (node.classList.contains("scroll-y")) {
          if (r.top < box.top + margin) node.scrollTop -= box.top + margin - r.top;
          else if (r.bottom > box.bottom - margin) node.scrollTop += r.bottom - box.bottom + margin;
          if (node.scrollTop < 400 && node.querySelector(".hero") && node.firstChild.contains(el)) node.scrollTop = 0;
        } else {
          if (r.left < box.left + margin) node.scrollLeft -= box.left + margin - r.left;
          else if (r.right > box.right - margin) node.scrollLeft += r.right - box.right + margin;
        }
      }
      node = node.parentElement;
    }
  }

  /** The nearest element in the pressed direction (what TVs call spatial navigation). */
  function move(dir, scope) {
    var cur = document.activeElement;
    if ((!cur || cur === document.body) && lastInput && scope.contains(lastInput)) cur = lastInput;
    var all = focusables(scope);
    if (!cur || all.indexOf(cur) < 0) return focus(scope.querySelector(".menu .row-item.sel") || all[0]);
    var a = cur.getBoundingClientRect(), best = null, bestScore = Infinity;
    var horizontal = dir === "left" || dir === "right";
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      if (el === cur) continue;
      var b = el.getBoundingClientRect(), gap;
      if (dir === "left") gap = a.left - b.right;
      else if (dir === "right") gap = b.left - a.right;
      else if (dir === "up") gap = a.top - b.bottom;
      else gap = b.top - a.bottom;
      if (gap < -4) continue;
      var side = horizontal ? Math.max(0, Math.max(a.top, b.top) - Math.min(a.bottom, b.bottom))
        : Math.max(0, Math.max(a.left, b.left) - Math.min(a.right, b.right));
      var score = Math.max(0, gap) + side * 4 + (side > 0 ? 400 : 0);
      if (score < bestScore) { bestScore = score; best = el; }
    }
    if (best) focus(best);
  }

  var okTarget = null, okTimer = null, lastBack = 0, lastInput = null, lastMove = 0;
  function back() {
    var a = document.activeElement;
    if (a && a.tagName === "INPUT") { lastInput = a; a.blur(); return; } // closes the TV keyboard; arrows go on from the field
    if (S.guideFor) { S.guideFor = null; render(); return; }
    if (S.detail) { S.detail = null; render(); return; }
    if (S.series) { S.series = null; render(); return; }
    if (S.source && !S.choosing && S.page !== "discover") { S.page = "discover"; render(); focusFirst(".menu .sel"); return; }
    if (Date.now() - lastBack < 2500) {
      if (window.ZonoAndroid) ZonoAndroid.exit();
      else if (window.PalmSystem && PalmSystem.platformBack) PalmSystem.platformBack(); else window.close();
    } else { lastBack = Date.now(); toast(T("exit_hint")); }
  }

  function uiKey(k, e, scope) {
    var a = document.activeElement, typing = a && a.tagName === "INPUT";
    if (k === KEY.BACK || k === KEY.ESC || (k === KEY.BACKSPACE && !typing)) { e.preventDefault(); return scope === sheetEl ? closeSheet() : back(); }
    if (typing && (k === KEY.LEFT || k === KEY.RIGHT)) {
      var atStart = a.selectionStart === 0 && a.selectionEnd === 0, atEnd = a.selectionStart === a.value.length;
      if ((k === KEY.LEFT && !atStart) || (k === KEY.RIGHT && !atEnd)) return;
    }
    var dir = { 37: "left", 38: "up", 39: "right", 40: "down" }[k];
    if (dir) {
      e.preventDefault();
      if (e.repeat && Date.now() - lastMove < 80) return; // the TV keeps up instead of lagging behind
      lastMove = Date.now();
      move(dir, scope); return;
    }
    if (k === KEY.OK && a && a._go) {
      e.preventDefault();
      if (typing) { a.blur(); a.focus(); return; } // opens the TV keyboard
      if (okTarget) return; // the key repeats while it is held
      okTarget = a;
      // OK chooses when you let go; held for 0.7 s it does the "hold" action
      clearTimeout(okTimer);
      if (a._long) okTimer = setTimeout(function () { if (okTarget === a) { okTarget = "used"; a._long(); } }, 700);
    }
  }

  function digitOf(e) {
    var k = e.keyCode;
    if (k >= 48 && k <= 57) return String(k - 48);
    if (k >= 96 && k <= 105) return String(k - 96);
    return null;
  }

  document.addEventListener("keydown", onKey);
  function onKey(e) {
    var k = e.keyCode, d = digitOf(e), a = document.activeElement;
    if (d !== null && !(a && a.tagName === "INPUT")) {
      e.preventDefault();
      if (sheetOpen()) { if (sheetEl._digit) return sheetEl._digit(d); if (!sheetEl.classList.contains("side")) return; closeSheet(); }
      if (S.source && !S.choosing && S.shelves.live.length) numberKey(d);
      return;
    }
    if (sheetOpen()) return uiKey(k, e, sheetEl);
    if (playerOpen()) { if (playerKey(k, e)) e.preventDefault(); return; }
    uiKey(k, e, app);
  }
  /** Keys the Android app passes on (Back, channel up/down, play/pause): handled like the LG remote's. */
  function pressKey(code) {
    var fake = { keyCode: code, repeat: false, preventDefault: function () {} };
    onKey(fake);
    if (code === KEY.OK) document.dispatchEvent(new KeyboardEvent("keyup", { key: "Enter" }));
  }
  document.addEventListener("keyup", function (e) {
    if (e.keyCode !== KEY.OK || (playerOpen() && !sheetOpen())) return;
    clearTimeout(okTimer);
    var a = document.activeElement;
    if (a && a === okTarget && a._go && a.tagName !== "INPUT") { okTarget = null; a._go(); }
    okTarget = null;
  });
  document.addEventListener("mouseover", function (e) {
    var el = e.target.closest && e.target.closest(".f");
    if (el && el !== document.activeElement && (!playerOpen() || sheetOpen())) { try { el.focus({ preventScroll: true }); } catch (x) { el.focus(); } }
  });
  document.addEventListener("click", function (e) {
    var el = e.target.closest && e.target.closest(".f");
    if (el && el._go && (!playerOpen() || sheetEl.contains(el)) && el.tagName !== "INPUT") el._go();
  });
  document.addEventListener("wheel", function (e) {
    var node = e.target.closest && e.target.closest(".scroll-y, .scroll-x");
    if (!node) return;
    if (node.classList.contains("scroll-y")) node.scrollTop += e.deltaY; else node.scrollLeft += e.deltaY;
    if (node._more && node.scrollTop + node.clientHeight > node.scrollHeight - 400) node._more();
  });

  var toastTimer = null;
  function toast(text) {
    var t = document.getElementById("toast");
    t.textContent = text; t.classList.add("on");
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.classList.remove("on"); }, 2600);
  }

  // ---- channel numbers: type 1-2-3, after a moment Zono switches; 0 alone goes back to the previous channel
  var number = { typed: "", timer: null };
  var numbox = document.getElementById("numbox");
  function numberKey(d) {
    if (d === "0" && !number.typed) {
      if (playerOpen() && P.previous) return previousChannel();
      if (!playerOpen() && find(S.recent[1])) return playChannel(find(S.recent[1]));
      return;
    }
    number.typed = (number.typed + d).slice(0, 4);
    numbox.textContent = number.typed; numbox.classList.add("on");
    clearTimeout(number.timer);
    number.timer = setTimeout(function () {
      var n = parseInt(number.typed, 10), channel = S.numbers[n];
      number.typed = ""; numbox.classList.remove("on");
      if (!channel) return toast(T("no_channel", n));
      if (!playerOpen() && S.page === "guide" && !S.guideFor && !S.detail && !S.series) return guideJump(channel);
      playChannel(channel, S.shelves.live);
    }, 1500);
  }

  // ------------------------------------------------------------------ player
  var P = { queue: [], index: 0, retried: false, saveTimer: null, hideTimer: null, returnFocus: null, previous: null, programs: null, subs: null };
  // on Android TV the picture comes from Android's own player (js/native.js); on LG from the <video> element
  var player = document.getElementById("player"), video = window.ZonoNativeVideo || document.getElementById("video");
  /** Android: tell the native player where the picture goes (hidden, small picture, full screen). */
  function syncVideo() {
    if (!video.setRect) return;
    var full = !player.hidden && !P.mini;
    document.documentElement.classList.toggle("native-full", full);
    if (player.hidden) video.setRect(0);
    else if (P.mini) video.setRect(1, parseFloat(player.style.left), parseFloat(player.style.top), parseFloat(player.style.width), parseFloat(player.style.height));
    else video.setRect(2);
  }
  function playerOpen() { return !player.hidden && !P.mini; }
  var mini = { channel: null, slot: null, follow: null };
  /** Position of an element in page pixels (the page is laid out at 1920x1080 and zoomed as a whole). */
  function pagePos(el) { var x = 0, y = 0; for (var n = el; n && n !== document.body; n = n.offsetParent) { x += n.offsetLeft - (n.scrollLeft || 0); y += n.offsetTop - (n.scrollTop || 0); } return { x: x, y: y }; }
  function miniPlay(channel, slot) {
    // only on the page that asked for it, and never over something playing full screen
    if (!channel || !slot || !document.body.contains(slot) || sheetOpen() || playerOpen()) return;
    var at = pagePos(slot);
    player.style.left = at.x + "px"; player.style.top = at.y + "px";
    player.style.width = slot.offsetWidth + "px"; player.style.height = slot.offsetHeight + "px";
    mini.slot = slot;
    if (P.mini && mini.channel === channel && player.classList.contains("mini")) return syncVideo();
    P.mini = true; mini.channel = channel;
    player.classList.add("mini"); player.hidden = false;
    var list = S.shelves.live, index = list.indexOf(channel);
    P.queue = index >= 0 ? list : [channel]; P.index = Math.max(0, index);
    syncVideo();
    startItem(false);
  }
  function stopMini() {
    clearTimeout(mini.follow);
    if (!P.mini) return;
    P.mini = false; mini.channel = null;
    player.classList.remove("mini"); player.removeAttribute("style");
    clearInterval(P.saveTimer);
    video.pause(); video.removeAttribute("src"); video.load();
    player.hidden = true;
    syncVideo();
  }
  /** From the small picture to full screen, without starting the stream again. */
  function miniToFull() {
    if (!P.mini) return;
    P.mini = false; mini.channel = null;
    player.classList.remove("mini"); player.removeAttribute("style");
    syncVideo();
    P.returnFocus = currentKey();
    var item = current();
    save(pkey("last"), item.id); addRecent(item.id);
    liveBar(item, epgCache[item.id] && epgCache[item.id].rows);
  }
  function current() { return P.queue[P.index]; }
  function isLive() { var it = current(); return it && it.kind === "live"; }

  function play(queue, index) {
    if (!queue.length) return;
    if (P.mini) { P.mini = false; mini.channel = null; player.classList.remove("mini"); player.removeAttribute("style"); player.hidden = true; }
    if (playerOpen() && isLive() && queue[index] && queue[index].kind === "live") P.previous = { queue: P.queue, index: P.index };
    P.queue = queue.slice(); P.index = Math.max(0, Math.min(index, queue.length - 1));
    if (!playerOpen()) P.returnFocus = currentKey();
    player.hidden = false;
    syncVideo();
    startItem(true);
  }

  var subline = document.getElementById("subline");
  function clearSubtitles() { P.subs = null; P.cues = null; subline.textContent = ""; subline.hidden = true; }
  function drawSubtitle() {
    if (!P.cues) return;
    var cue = Guide.cueAt(P.cues, video.currentTime);
    var text = cue ? cue.text : "";
    if (subline.textContent !== text) { subline.textContent = text; subline.hidden = !text; }
    subline.classList.toggle("high", document.getElementById("bar").classList.contains("on"));
  }

  function startItem(resume) {
    var item = current();
    P.retried = false; P.programs = null;
    clearSubtitles();
    video.pause();
    video.removeAttribute("src"); video.load();
    var link = Catalog.urlOf(item, S.source);
    video.src = link;
    log("play " + item.kind + " " + link);
    var info = "", saved = null;
    if (!isLive() && resume) saved = progressOf(item.id);
    if (saved && saved.pos > 0) {
      info = T("resume");
      video.addEventListener("loadedmetadata", function seek() { video.removeEventListener("loadedmetadata", seek); try { video.currentTime = saved.pos; } catch (e) { /* not seekable */ } });
    }
    if (isLive()) { var seekBar = document.getElementById("bar"); seekBar.classList.remove("on"); seekBar.hidden = true; }
    else hideLiveBar();
    if (P.mini) { hideLiveBar(); hideBanner(); loadNowNext(item); }
    else if (isLive()) { save(pkey("last"), item.id); addRecent(item.id); hideBanner(); liveBar(item, epgCache[item.id] && epgCache[item.id].rows); loadNowNext(item); }
    spinner(true);
    var p = video.play(); if (p && p.catch) p.catch(function () {});
    if (!isLive()) banner(item.title, info);
    clearInterval(P.saveTimer);
    P.saveTimer = setInterval(remember, 15000);
  }
  function titleOf(item) { var num = item.kind === "live" ? numberOf(item) : 0; return (num > 0 ? num + "  " : "") + item.title + (item.kind === "live" && Catalog.itemUhd(item) ? "  ·  4K" : ""); }
  // ---- live: a bar at the bottom with what's on now and next (5 seconds), OK opens the channel list
  var livebar = document.getElementById("livebar"), liveTimer = null;
  function liveBar(channel, programs, preview) {
    var nn = Guide.nowNext(programs || [], nowSeconds(), 1), now = nn.now, next = nn.next[0];
    livebar.innerHTML = "";
    livebar.appendChild(h("div", { cls: "logo-box big" }, [channel.image ? picture(channel.image) : h("span", { text: Catalog.initials(channel.title) })]));
    var main = h("div", { cls: "lb-main" }, [
      h("div", { cls: "lb-head" }, [h("span", { cls: "lb-num", text: String(numberOf(channel) || "") }), h("span", { cls: "lb-name", text: channel.title }),
        Catalog.itemUhd(channel) ? h("span", { cls: "badge", text: "4K" }) : null, channel.archive ? withIcon("replay", T("catchup"), "lb-tag") : null]),
      now ? h("div", { cls: "lb-now" }, [h("span", { cls: "lb-time", text: hm(now.start) + " – " + hm(now.end) }), h("span", { cls: "lb-title", text: now.title })])
        : h("div", { cls: "lb-now lb-empty", text: programs ? T("no_guide") : T("loading") }),
      now ? h("div", { cls: "lb-bar" }, [h("div", { style: "width:" + Math.round((nowSeconds() - now.start) / (now.end - now.start) * 100) + "%" })]) : null,
      next ? h("div", { cls: "lb-next" }, [h("span", { cls: "lb-label", text: T("later") }), h("span", { cls: "lb-time", text: hm(next.start) }), h("span", { text: next.title })]) : null]);
    livebar.appendChild(main);
    if (!preview) livebar.appendChild(h("div", { cls: "lb-keys" }, [keyHint(["up", "down"], T("zap_hint")), keyHint(["OK"], T("menu_hint_live")),
      P.previous ? keyHint(["0"], T("previous_channel")) : keyHint(["1", "2"], T("channel_numbers"))]));
    livebar.classList.toggle("beside", !!preview);
    livebar.classList.add("on");
    clearTimeout(liveTimer);
    if (!preview) liveTimer = setTimeout(function () { if (!(sheetOpen() && sheetEl.classList.contains("side"))) livebar.classList.remove("on"); }, 5000);
  }
  function hideLiveBar() { clearTimeout(liveTimer); livebar.classList.remove("on"); }
  function hideBanner() { document.getElementById("banner").classList.remove("on"); }
  function loadNowNext(item) {
    programsFor(item, false).then(function (rows) {
      P.programs = rows;
      if (!P.mini && current() === item && livebar.classList.contains("on") && !livebar.classList.contains("beside")) liveBar(item, rows);
    }, function () {});
  }
  /** The channel list over the picture: the TV keeps playing; moving through it previews what's on. */
  function zapPanel() {
    var item = current(), queue = P.queue, at = P.index;
    var from = Math.max(0, at - 60), to = Math.min(queue.length, at + 200);
    var list = h("div", { cls: "sheet-list scroll-y zap-list" });
    var rows = [];
    for (var n = from; n < to; n++) (function (channel, index) {
      var row = rowItem(channel.title, function () {
        closeSheet();
        if (index !== P.index) { P.previous = { queue: P.queue, index: P.index }; P.index = index; startItem(false); } else liveBar(channel, P.programs);
      }, { image: channel.image || "", lead: h("span", { cls: "zap-num", text: String(numberOf(channel) || "") }), sel: index === at, key: "z-" + channel.id,
        trail: isFavorite(channel.id) ? icon("heartFill") : "", sub: " ",
        onfocus: function () {
          var cached = epgCache[channel.id];
          liveBar(channel, cached && cached.rows, true);
          // what's on, for this row and the ones around it
          rows.slice(Math.max(0, index - from - 3), index - from + 6).forEach(function (r) {
            if (r._asked) return; r._asked = true;
            limited(function () { return programsFor(r._channel, false); }).then(function (progs) {
              var nn = Guide.nowNext(progs || [], nowSeconds(), 0);
              var sub = r.querySelector(".sub"); if (sub) sub.textContent = nn.now ? nn.now.title : "";
              if (r._channel === channel && document.activeElement === r) liveBar(channel, progs, true);
            });
          });
        } });
      row._channel = channel;
      rows.push(row); list.appendChild(row);
    })(queue[n], n);
    var actions = h("div", { cls: "zap-actions" }, [
      button(T("nav_guide"), function () { closeSheet(); closePlayer(); openGuide(item); }, { icon: "grid", key: "za-guide" }),
      button(T("subtitles"), function () { closeSheet(); playerMenu(); }, { icon: "cc", key: "za-subs" }),
      button(isFavorite(item.id) ? T("favorited") : T("favorite"), function () { toggleFavorite(item); closeSheet(); }, { icon: isFavorite(item.id) ? "heartFill" : "heart", key: "za-fav" })]);
    sheet({ title: item.group ? groupName(item.group) : T("nav_live"), side: true, content: [actions, list],
      onClose: function () { var c = current(); if (c && c.kind === "live") liveBar(c, P.programs); } });
    var sel = list.querySelector(".row-item.sel");
    if (sel) { focus(sel); list.scrollTop = Math.max(0, sel.offsetTop - 300); }
  }

  function spinner(on) { document.getElementById("spinner").hidden = !on; }
  function bannerOn() { return document.getElementById("banner").classList.contains("on"); }
  function banner(title, info) {
    document.getElementById("banner-title").textContent = title;
    var i = document.getElementById("banner-info"); i.textContent = info || ""; i.hidden = !info;
    showOverlay();
  }
  function showOverlay() {
    document.getElementById("banner").classList.add("on");
    var barEl = document.getElementById("bar");
    barEl.hidden = isLive();
    if (!isLive()) { updateBar(); barEl.classList.add("on"); }
    clearTimeout(P.hideTimer);
    P.hideTimer = setTimeout(function () {
      if (video.paused && !isLive()) return;
      document.getElementById("banner").classList.remove("on"); barEl.classList.remove("on");
    }, 5000);
  }
  function clock(s) {
    s = Math.max(0, Math.floor(s || 0));
    var hh = Math.floor(s / 3600), mm = Math.floor(s / 60) % 60, ss = s % 60;
    return (hh ? hh + ":" + (mm < 10 ? "0" : "") : "") + mm + ":" + (ss < 10 ? "0" : "") + ss;
  }
  function updateBar() {
    var d = video.duration, t = video.currentTime;
    document.getElementById("bar-now").textContent = clock(t);
    document.getElementById("bar-end").textContent = isFinite(d) ? clock(d) : "";
    var hint = document.getElementById("bar-hint"), paused = video.paused;
    if (hint._paused !== paused) {
      hint._paused = paused; hint.innerHTML = "";
      if (paused) hint.appendChild(withIcon("pause", T("paused")));
      else { hint.appendChild(keyHint(["left", "right"], T("seek_hint"))); hint.appendChild(keyHint(["down"], T("menu_hint_vod"))); }
    }
    document.getElementById("bar-fill").style.width = isFinite(d) && d > 0 ? (t / d * 100) + "%" : "0";
  }
  video.addEventListener("timeupdate", function () { if (document.getElementById("bar").classList.contains("on")) updateBar(); drawSubtitle(); });
  video.addEventListener("playing", function () { spinner(false); P.retried = false; });
  video.addEventListener("waiting", function () { spinner(true); });
  video.addEventListener("pause", function () { if (playerOpen() && !isLive()) showOverlay(); });
  video.addEventListener("error", function () {
    if (!playerOpen() || !video.getAttribute("src")) return;
    var item = current();
    var link = Catalog.urlOf(item, S.source);
    log("playback error " + (video.error && video.error.code) + " " + link);
    if (!P.retried) {
      P.retried = true;
      setTimeout(function () { video.load(); var p = video.play(); if (p && p.catch) p.catch(function () {}); }, 1500);
      return;
    }
    if (isLive() && /\.m3u8$/.test(link)) {
      var copy = {}; for (var key in item) copy[key] = item[key];
      copy.url = link.replace(/\.m3u8$/, ".ts");
      P.queue[P.index] = copy;
      return startItem(false);
    }
    spinner(false);
    if (!P.mini) banner(item.title, T("playback_error"));
  });
  video.addEventListener("ended", function () {
    var item = current();
    if (isLive()) return;
    saveProgress(item, video.duration, video.duration);
    if (item.kind === "episode" && P.index + 1 < P.queue.length) {
      P.index += 1; startItem(false); banner(current().title, T("next_episode"));
    } else closePlayer();
  });

  function remember() {
    var item = current();
    if (item && !isLive() && isFinite(video.duration) && video.duration > 0) saveProgress(item, video.currentTime, video.duration);
  }

  function closePlayer() {
    remember();
    clearInterval(P.saveTimer); clearTimeout(P.hideTimer);
    clearSubtitles();
    video.pause(); video.removeAttribute("src"); video.load();
    player.hidden = true;
    P.previous = null;
    hideLiveBar();
    syncVideo();
    render();
    restoreFocus(P.returnFocus);
  }

  function zap(step) {
    if (P.queue.length < 2) return;
    P.previous = { queue: P.queue, index: P.index };
    P.index = (P.index + step + P.queue.length) % P.queue.length;
    startItem(false);
  }
  function previousChannel() {
    var prev = P.previous;
    if (!prev) return;
    P.previous = { queue: P.queue, index: P.index };
    P.queue = prev.queue; P.index = prev.index;
    startItem(false);
  }
  function seek(seconds) {
    if (!isFinite(video.duration)) return;
    video.currentTime = Math.max(0, Math.min(video.duration - 1, video.currentTime + seconds));
    showOverlay();
  }
  function togglePause() {
    if (video.paused) { var p = video.play(); if (p && p.catch) p.catch(function () {}); } else video.pause();
    showOverlay(); updateBar();
  }

  // ---- the player menu: subtitles, audio, guide
  function trackName(t, i) { return t.label || (t.language ? t.language.toUpperCase() : T("track", i + 1)); }
  function playerMenu() {
    var items = [], live = isLive(), item = current();
    var texts = video.textTracks || [], audio = video.audioTracks;
    items.push({ heading: T("subtitles") });
    var anyOn = false;
    for (var i = 0; i < texts.length; i++) if (texts[i].mode === "showing") anyOn = true;
    if (P.cues) items.push({ label: "OpenSubtitles", sub: P.subs && P.subs.name, sel: true, go: closeSheet });
    items.push({ label: T("off"), sel: !anyOn && !P.cues, go: function () { for (var j = 0; j < texts.length; j++) texts[j].mode = "disabled"; clearSubtitles(); closeSheet(); } });
    for (var t = 0; t < texts.length; t++) (function (track, n) {
      if (track.kind !== "subtitles" && track.kind !== "captions") return;
      items.push({ label: trackName(track, n), sel: track.mode === "showing", go: function () {
        for (var j = 0; j < texts.length; j++) texts[j].mode = texts[j] === track ? "showing" : "disabled";
        clearSubtitles(); closeSheet();
      } });
    })(texts[t], t);
    if (!live) items.push({ label: T("sub_search"), sub: T("sub_language") + ": " + subLanguage().toUpperCase(), go: function () { closeSheet(); searchSubtitles(); } });
    if (audio && audio.length > 1) {
      items.push({ heading: T("audio") });
      for (var a = 0; a < audio.length; a++) (function (track, n) {
        items.push({ label: trackName(track, n), sel: track.enabled, go: function () {
          for (var j = 0; j < audio.length; j++) audio[j].enabled = audio[j] === track;
          closeSheet();
        } });
      })(audio[a], a);
    }
    sheet({ title: item.title, items: items, wide: true });
  }

  function subLanguage() {
    var chosen = load("subLang", "");
    return chosen || (["nl", "fr", "en", "de"].indexOf(lang) >= 0 ? lang : "en");
  }
  function subsHeaders() {
    return { "Api-Key": load("opensubtitles", ""), "X-User-Agent": "Zono TV v" + VERSION, "Accept": "application/json" };
  }
  function searchSubtitles() {
    var item = current(), key = load("opensubtitles", "");
    if (!key) return subsKeySheet();
    var numbers = Guide.episodeNumbers(item.title), q = { languages: subLanguage(), order_by: "download_count", order_direction: "desc" };
    var name = item.kind === "episode" ? (item.series || item.title.split(" · ")[0]) : item.title;
    q.query = Guide.cleanQuery(name);
    if (item.kind === "episode") { q.season_number = parseInt(item.group, 10) || numbers[0] || 1; q.episode_number = item.number || numbers[1] || 1; }
    var url = SUBS_API + "/subtitles?" + Object.keys(q).sort().map(function (k) { return k + "=" + encodeURIComponent(q[k]); }).join("&");
    toast(T("loading"));
    request("GET", url, undefined, subsHeaders(), 20000).then(parse).then(function (answer) {
      var found = [];
      (answer.data || []).forEach(function (row) {
        var at = row.attributes || {}, files = at.files || [];
        if (files[0] && files[0].file_id) found.push({ id: files[0].file_id, name: at.release || files[0].file_name || "", downloads: at.download_count || 0 });
      });
      if (!found.length) return toast(T("sub_none"));
      sheet({ title: T("subtitles"), wide: true, items: found.slice(0, 10).map(function (f) {
        return { label: f.name, trail: withIcon("download", String(f.downloads)), go: function () { closeSheet(); downloadSubtitle(f); } };
      }).concat([{ label: T("close"), go: closeSheet }]) });
    }, function (problem) { log("subtitles: " + problem.message); toast(problem.status === 429 || problem.status === 406 ? T("sub_limit") : T("sub_none")); });
  }
  function downloadSubtitle(f) {
    toast(T("loading"));
    var headers = subsHeaders(); headers["Content-Type"] = "application/json";
    request("POST", SUBS_API + "/download", JSON.stringify({ file_id: f.id, sub_format: "srt" }), headers, 20000).then(parse).then(function (answer) {
      if (!answer.link) throw new Error(answer.message || "no link");
      return get(answer.link, 30000);
    }).then(function (srt) {
      clearSubtitles();
      var texts = video.textTracks; for (var j = 0; j < texts.length; j++) texts[j].mode = "disabled";
      // drawn by Zono itself (above the progress bar, same size on every TV)
      P.cues = Guide.parseSubtitles(srt);
      if (!P.cues.length) throw new Error("empty");
      P.subs = f;
      toast(T("sub_loaded"));
    }, function (problem) { log("subtitle download: " + problem.message); toast(problem.status === 429 || problem.status === 406 ? T("sub_limit") : T("sub_none")); });
  }

  function playerKey(k, e) {
    var live = isLive(), item = current();
    switch (k) {
      case KEY.BACK: case KEY.ESC: case KEY.BACKSPACE: case KEY.STOP: closePlayer(); return true;
      case KEY.CH_UP: if (live) zap(-1); return true;
      case KEY.CH_DOWN: if (live) zap(1); return true;
      case KEY.UP: if (live) zap(-1); else showOverlay(); return true;
      case KEY.DOWN: if (live) zap(1); else playerMenu(); return true;
      case KEY.LEFT: if (!live) seek(e.repeat ? -30 : -10); else liveBar(item, P.programs); return true;
      case KEY.RIGHT: if (!live) seek(e.repeat ? 30 : 10); else liveBar(item, P.programs); return true;
      case KEY.RW: if (!live) seek(-30); return true;
      case KEY.FF: if (!live) seek(30); return true;
      case KEY.OK:
        if (e.repeat) return true;
        if (live) zapPanel(); else togglePause();
        return true;
      case KEY.PLAY: case KEY.PAUSE: case KEY.PLAY_PAUSE:
        if (!live) togglePause();
        return true;
    }
    if (live) liveBar(item, P.programs); else showOverlay();
    return false;
  }
  player.addEventListener("click", function (e) { if (sheetEl.contains(e.target)) return; if (isLive()) zapPanel(); else togglePause(); });

  document.addEventListener("visibilitychange", function () {
    if (document.hidden && playerOpen()) { remember(); video.pause(); }
    if (document.hidden && P.mini) stopMini();
  });

  // ------------------------------------------------------------------ go
  function fit() {
    var scale = window.innerWidth / 1920;
    document.documentElement.style.zoom = scale === 1 ? "" : String(scale);
  }
  window.addEventListener("resize", fit);
  fit();
  pickLanguage();
  start();
  setInterval(checkReminders, 15000);
  setTimeout(ping, 20000);
  window.Zono = { key: pressKey, state: S, render: render, buildShelves: buildShelves, mini: mini, P: P, version: VERSION, pair: pair, checkReminders: checkReminders, ping: ping, log: LOG }; // for tests
})();

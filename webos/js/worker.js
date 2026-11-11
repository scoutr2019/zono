// Heavy work away from the screen, so the TV never freezes: downloading and reading the provider's library
// (tens of thousands of channels and films), storing it, and reading big XMLTV guides.
// Messages in:  {id, type: "load", source}  {id, type: "epg", url} (a channel's guide, read here)  {id, type: "xmltv", url, keep: [ids], names: [titles]}
// Messages out: {id, type: "step", kind}  {id, type: "done", items, guideUrl}  {id, type: "error", code, message}
importScripts("catalog.js", "guide.js", "countries.js");

// in the Android app the provider is reached through the app itself (see MainActivity: /proxy)
var PROXY = self.location && self.location.host === "appassets.androidplatform.net" ? self.location.origin + "/proxy?u=" : "";
function get(url, timeout, maxBytes) {
  return new Promise(function (resolve, reject) {
    var x = new XMLHttpRequest();
    x.open("GET", PROXY && /^https?:\/\//i.test(url) ? PROXY + encodeURIComponent(url) : url, true);
    x.timeout = timeout || 120000;
    if (maxBytes) x.onprogress = function (e) { if (e.loaded > maxBytes) { x.abort(); reject({ code: "big" }); } };
    x.onload = function () {
      if (x.status === 401 || x.status === 403) reject({ code: "login" });
      else if (x.status >= 200 && x.status < 300) resolve(x.responseText);
      else reject({ code: "http", message: "HTTP " + x.status });
    };
    x.onerror = function () { reject({ code: "network", message: "network" }); };
    x.ontimeout = function () { reject({ code: "network", message: "timeout" }); };
    x.send();
  });
}
function json(url) { return get(url).then(function (t) { return JSON.parse(t.replace(/^﻿/, "")); }); }

/** Sends a big list in pieces: one huge message would freeze the screen while it is unpacked. */
function send(id, items, extra, kind) {
  for (var i = 0; i < items.length; i += 2000) postMessage({ id: id, type: "chunk", items: items.slice(i, i + 2000) });
  var done = { id: id, type: kind || "done" };
  for (var k in extra || {}) done[k] = extra[k];
  postMessage(done);
}
function read(key) {
  return new Promise(function (resolve) {
    try {
      var r = indexedDB.open("zono", 1);
      r.onupgradeneeded = function () { r.result.createObjectStore("kv"); };
      r.onsuccess = function () {
        var g = r.result.transaction("kv").objectStore("kv").get(key);
        g.onsuccess = function () { resolve(g.result); };
        g.onerror = function () { resolve(undefined); };
      };
      r.onerror = function () { resolve(undefined); };
    } catch (e) { resolve(undefined); }
  });
}

function store(key, value) {
  return new Promise(function (resolve) {
    try {
      var r = indexedDB.open("zono", 1);
      r.onupgradeneeded = function () { r.result.createObjectStore("kv"); };
      r.onsuccess = function () {
        var t = r.result.transaction("kv", "readwrite");
        t.objectStore("kv").put(value, key);
        t.oncomplete = t.onerror = function () { resolve(); };
      };
      r.onerror = function () { resolve(); };
    } catch (e) { resolve(); }
  });
}

/** Search text: the clean title and the provider's own name, lower case, made once. */
function searchKeys(items) {
  items.forEach(function (i) {
    if (Guide.adult(i.group) || Guide.adult(i.title)) i.adult = 1; // for kids profiles
    if (i.kind === "live") i.k4 = Catalog.itemUhd(i) ? 1 : 0; // 4K, worked out once
    i.cc = Countries.detect(i); // country, for "your countries first"
  });
  return items;
}

function load(id, source) {
  var step = function (kind) { postMessage({ id: id, type: "step", kind: kind }); };
  var done = function (items, guideUrl, marked) {
    if (!marked) searchKeys(items); else searchKeys(items.filter(function (i) { return i.kind !== "live"; }));
    // to the screen first, then stored: storing 100,000+ titles can take a while on a TV
    send(id, items, { guideUrl: guideUrl || "" });
    return store("library", items).then(function () { return store("libraryVersion", 7); });
  };
  if (source.type !== "xtream") {
    step("live");
    return get(source.m3u, 180000).then(function (raw) {
      var items = Catalog.parseM3u(raw);
      if (!items.length) throw { code: "empty" };
      return done(items, Catalog.m3uGuideUrl(raw));
    });
  }
  // everything is asked at the same time (one after the other took much longer); the channels go to the
  // screen as soon as they are in, so you can start watching while films and series still come in
  var kinds = [["live", "live", "get_live_streams"], ["movie", "vod", "get_vod_streams"], ["series", "series", "get_series"]];
  var account = json(Catalog.apiUrl(source)).then(function (answer) {
    var info = answer && answer.user_info;
    if (!info || String(info.auth) === "0") throw { code: "login" };
  });
  step("live");
  var parts = kinds.map(function (k) {
    var cats = json(Catalog.apiUrl(source, "get_" + k[1] + "_categories")).catch(function () { return []; });
    var rows = json(Catalog.apiUrl(source, k[2]));
    return Promise.all([cats, rows]).then(function (got) { return Catalog.streams(got[1], k[0], source, Catalog.categories(got[0])); });
  });
  parts[0].catch(function () {});
  parts[1].catch(function () {});
  parts[2].catch(function () {});
  return account.then(function () {
    return parts[0].then(function (live) {
      if (live.length) { searchKeys(live); send(id, live, null, "partial"); }
      step("movie");
      return Promise.all(parts).then(function (lists) {
        var all = lists[0].concat(lists[1], lists[2]);
        if (!all.length) throw { code: "empty" };
        return done(all, "", true);
      });
    });
  });
}

// big XMLTV guides stay here: the screen only gets search results and one channel's programmes
var guides = {}, guideChannels = {};
function xmltv(id, url, channels) {
  function ready() { postMessage({ id: id, type: "done", ok: true }); }
  if (guides[url]) return Promise.resolve(ready());
  return read("xmltv").then(function (cached) {
    if (cached && cached.url === url && Date.now() - cached.at < 6 * 3600000) return cached.guide;
    return get(url, 240000, 120 * 1024 * 1024).then(function (text) {
      var guide = Guide.parseXmltv(text, null);
      text = null;
      var wanted = {};
      channels.forEach(function (c) { var g = Guide.channelFor(guide, c); if (g) wanted[g] = 1; });
      Object.keys(guide.programs).forEach(function (c) { if (!wanted[c]) delete guide.programs[c]; });
      return store("xmltv", { url: url, at: Date.now(), guide: guide }).then(function () { return guide; });
    });
  }).then(function (guide) {
    guides = {}; guides[url] = guide; guideChannels[url] = channels;
    ready();
  });
}
function guideSearch(id, url, query) {
  var guide = guides[url];
  var hits = guide ? Guide.search(guide, guideChannels[url] || [], query) : [];
  postMessage({ id: id, type: "done", ok: !!guide, hits: hits.map(function (h) { return { channel: h.channel.id, program: h.program }; }) });
}
function guideChannel(id, url, item) {
  var guide = guides[url], c = guide && Guide.channelFor(guide, item);
  postMessage({ id: id, type: "done", rows: c ? guide.programs[c] : [] });
}

onmessage = function (e) {
  var m = e.data;
  var job = m.type === "load" ? load(m.id, m.source)
    : m.type === "epg" ? json(m.url).then(function (data) { postMessage({ id: m.id, type: "done", rows: Guide.xtreamPrograms(data) }); })
    : m.type === "cache" ? read("libraryVersion").then(function (version) {
      return read("library").then(function (items) { send(m.id, items || [], { old: version !== 7 }); });
    })
    : m.type === "gsearch" ? Promise.resolve(guideSearch(m.id, m.url, m.query))
    : m.type === "gchan" ? Promise.resolve(guideChannel(m.id, m.url, m.item))
    : xmltv(m.id, m.url, m.channels || []);
  job.catch(function (problem) {
    postMessage({ id: m.id, type: "error", code: (problem && problem.code) || "error", message: (problem && (problem.message || problem.code)) || String(problem) });
  });
};

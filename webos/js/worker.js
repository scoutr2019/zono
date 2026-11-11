// Heavy work away from the screen, so the TV never freezes: downloading and reading the provider's library
// (tens of thousands of channels and films), storing it, and reading big XMLTV guides.
// Messages in:  {id, type: "load", source}  {id, type: "xmltv", url, keep: [ids], names: [titles]}
// Messages out: {id, type: "step", kind}  {id, type: "done", items, guideUrl}  {id, type: "error", code, message}
importScripts("catalog.js", "guide.js");

function get(url, timeout, maxBytes) {
  return new Promise(function (resolve, reject) {
    var x = new XMLHttpRequest();
    x.open("GET", url, true);
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
function send(id, items, extra) {
  for (var i = 0; i < items.length; i += 4000) postMessage({ id: id, type: "chunk", items: items.slice(i, i + 4000) });
  var done = { id: id, type: "done" };
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
    i.q = (i.title + " " + (i.raw || "")).toLowerCase();
    if (Guide.adult(i.group) || Guide.adult(i.title)) i.adult = 1; // for kids profiles
    if (i.kind === "live") i.k4 = Catalog.itemUhd(i) ? 1 : 0; // 4K, worked out once
  });
  return items;
}

function load(id, source) {
  var step = function (kind) { postMessage({ id: id, type: "step", kind: kind }); };
  var done = function (items, guideUrl) {
    searchKeys(items);
    return store("library", items).then(function () { send(id, items, { guideUrl: guideUrl || "" }); });
  };
  if (source.type !== "xtream") {
    step("live");
    return get(source.m3u, 180000).then(function (raw) {
      var items = Catalog.parseM3u(raw);
      if (!items.length) throw { code: "empty" };
      return done(items, Catalog.m3uGuideUrl(raw));
    });
  }
  var all = [];
  var kinds = [["live", "live", "get_live_streams"], ["movie", "vod", "get_vod_streams"], ["series", "series", "get_series"]];
  return json(Catalog.apiUrl(source)).then(function (account) {
    var info = account && account.user_info;
    if (!info || String(info.auth) === "0") throw { code: "login" };
    return kinds.reduce(function (chain, k) {
      return chain.then(function () {
        step(k[0]);
        return json(Catalog.apiUrl(source, "get_" + k[1] + "_categories")).catch(function () { return []; }).then(function (cats) {
          var groups = Catalog.categories(cats);
          return json(Catalog.apiUrl(source, k[2])).then(function (rows) {
            all = all.concat(Catalog.streams(rows, k[0], source, groups));
          });
        });
      });
    }, Promise.resolve());
  }).then(function () {
    if (!all.length) throw { code: "empty" };
    return done(all);
  });
}

function xmltv(id, url, keep, names) {
  return get(url, 240000, 120 * 1024 * 1024).then(function (text) {
    var guide = Guide.parseXmltv(text, null);
    text = null;
    var wanted = {};
    keep.forEach(function (k) { if (guide.programs[k]) wanted[k] = 1; });
    names.forEach(function (n) { var c = Guide.channelFor(guide, { title: n }); if (c) wanted[c] = 1; });
    Object.keys(guide.programs).forEach(function (c) { if (!wanted[c]) delete guide.programs[c]; });
    return store("xmltv", { url: url, at: Date.now(), guide: guide }).then(function () {
      postMessage({ id: id, type: "done", guide: guide });
    });
  });
}

onmessage = function (e) {
  var m = e.data;
  var job = m.type === "load" ? load(m.id, m.source)
    : m.type === "cache" ? read("library").then(function (items) { send(m.id, items || [], { old: !!(items && items[0] && !items[0].q) }); })
    : xmltv(m.id, m.url, m.keep || [], m.names || []);
  job.catch(function (problem) {
    postMessage({ id: m.id, type: "error", code: (problem && problem.code) || "error", message: (problem && (problem.message || problem.code)) || String(problem) });
  });
};

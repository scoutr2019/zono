// Linking Zono apps: "continue watching", favourites and the last channel, shared between Windows, LG and Android TV.
// The same format and locking as src/sync.py in Zono for Windows (keep both the same!):
// - id and key come from the subscription (or a link code) on the device; zono.be only sees the id and a locked
//   package (NaCl secretbox) it cannot open;
// - per profile name: progress, favourites, last channel, each with the time it changed; the newest change wins;
// - titles are matched by kind + the provider's id ("m123", "e456", "l7", "s9"), playlists by a hash of the link.
var Sync = (function () {
  "use strict";
  var VERSION = 1, MAX_PROGRESS = 300, MAX_FAVORITES = 600;

  function utf8(text) {
    var s = unescape(encodeURIComponent(text)), out = new Uint8Array(s.length);
    for (var i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
    return out;
  }
  function fromUtf8(bytes) { var s = ""; for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]); return decodeURIComponent(escape(s)); }
  function join(a, b) { var out = new Uint8Array(a.length + b.length); out.set(a, 0); out.set(b, a.length); return out; }
  function hex(bytes) { var s = ""; for (var i = 0; i < bytes.length; i++) s += (bytes[i] < 16 ? "0" : "") + bytes[i].toString(16); return s; }
  function b64(bytes) { var s = ""; for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]); return btoa(s); }
  function unb64(text) { var s = atob(text), out = new Uint8Array(s.length); for (var i = 0; i < s.length; i++) out[i] = s.charCodeAt(i); return out; }

  /** What links devices: the subscription itself (server without http/https or path, user, password). */
  function secretFor(source) {
    if (!source) return "";
    if (source.type === "m3u") return source.m3u ? "m3u\n" + String(source.m3u).trim() : "";
    var server = String(source.server || "").trim().replace(/^[a-z][a-z0-9+.-]*:\/\//i, "");
    var host = server.split(/[\/?#]/)[0].toLowerCase(), user = String(source.user || "").trim(), password = String(source.password || "");
    return host && user && password ? "xtream\n" + host + "\n" + user + "\n" + password : "";
  }
  function linkSecret(code) { return "code\n" + String(code || "").toUpperCase().replace(/[^A-Z0-9]/g, ""); }
  function newLinkCode() {
    var alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789", raw = nacl.randomBytes(16), out = "";
    for (var i = 0; i < 16; i++) out += (i && i % 4 === 0 ? "-" : "") + alphabet[raw[i] % alphabet.length];
    return out;
  }
  var derived = {};
  /** {id, key}. Slow on purpose (1000 rounds), so the id does not give the login away. */
  function derive(secret) {
    if (derived[secret]) return derived[secret];
    var raw = utf8(secret), digest = raw;
    for (var i = 0; i < 1000; i++) digest = nacl.hash(join(digest, raw));
    var result = { id: hex(nacl.hash(join(utf8("zono-sync-id"), digest)).subarray(0, 32)), key: nacl.hash(join(utf8("zono-sync-key"), digest)).subarray(0, 32) };
    derived = {}; derived[secret] = result;
    return result;
  }

  /** The same title in every Zono app. TV ids are already "m123" and so on; playlist items: a hash of the link. */
  function itemKey(item) {
    if (!item) return "";
    if (/^[lmse]\S+$/.test(item.id || "") && item.sid) return item.id;
    return item.url ? "u" + hex(nacl.hash(utf8(String(item.url)))).slice(0, 16) : "";
  }
  function profileName(name) { return String(name || "").toLowerCase().replace(/\s+/g, " ").trim() || "main"; }
  function empty() { return { v: VERSION, profiles: {} }; }

  function merge(a, b) {
    var out = empty();
    [a, b].forEach(function (pack) {
      if (!pack || typeof pack !== "object") return;
      var profiles = pack.profiles || {};
      Object.keys(profiles).forEach(function (name) {
        var part = profiles[name];
        if (!part || typeof part !== "object") return;
        var mine = out.profiles[name] || (out.profiles[name] = { progress: {}, fav: {}, last: null });
        ["progress", "fav"].forEach(function (field) {
          var list = part[field] || {};
          Object.keys(list).forEach(function (key) {
            var entry = list[key];
            if (entry && typeof entry === "object" && (!mine[field][key] || (entry.t || 0) > (mine[field][key].t || 0))) mine[field][key] = entry;
          });
        });
        if (part.last && typeof part.last === "object" && (!mine.last || (part.last.t || 0) > (mine.last.t || 0))) mine.last = part.last;
      });
    });
    Object.keys(out.profiles).forEach(function (name) {
      var part = out.profiles[name];
      [["progress", MAX_PROGRESS], ["fav", MAX_FAVORITES]].forEach(function (pair) {
        var keys = Object.keys(part[pair[0]]);
        if (keys.length <= pair[1]) return;
        keys.sort(function (x, y) { return (part[pair[0]][y].t || 0) - (part[pair[0]][x].t || 0); });
        var kept = {};
        keys.slice(0, pair[1]).forEach(function (k) { kept[k] = part[pair[0]][k]; });
        part[pair[0]] = kept;
      });
    });
    return out;
  }
  /** The same content, whatever the order (to see whether anything changed). */
  function same(a, b) {
    function sorted(v) {
      if (Array.isArray(v)) return v.map(sorted);
      if (!v || typeof v !== "object") return v;
      var out = {};
      Object.keys(v).sort().forEach(function (k) { out[k] = sorted(v[k]); });
      return out;
    }
    return JSON.stringify(sorted(a)) === JSON.stringify(sorted(b));
  }

  function lock(pack, key) {
    var nonce = nacl.randomBytes(24);
    return b64(join(nonce, nacl.secretbox(utf8(JSON.stringify(pack)), nonce, key)));
  }
  function open(data, key) {
    if (!data) return empty();
    try {
      var all = unb64(data), opened = nacl.secretbox.open(all.subarray(24), all.subarray(0, 24), key);
      var pack = opened && JSON.parse(fromUtf8(opened));
      return pack && pack.v === VERSION ? pack : null;
    } catch (e) { return null; }
  }

  /** Merge `local` with zono.be, store the result there; resolves with the merged package. `http(method, url, body)`
   *  is the app's own request function: resolves {status, body}. */
  function exchange(api, secret, local, http) {
    var d = derive(secret);
    function round(current, tries) {
      var theirs = open(current.data, d.key);
      var merged = merge(theirs || empty(), local);
      if (theirs && same(merged, merge(theirs, empty()))) return Promise.resolve(merged); // nothing new from here
      return http("POST", api, { id: d.id, rev: current.rev || 0, data: lock(merged, d.key) }).then(function (answer) {
        if (answer.status === 200) return merged;
        if (answer.status === 409 && tries < 4) return round(answer.body || {}, tries + 1);
        throw new Error("sync " + answer.status);
      });
    }
    return http("GET", api + "?id=" + d.id).then(function (answer) {
      if (answer.status !== 200) throw new Error("sync " + answer.status);
      return round(answer.body || {}, 0);
    });
  }

  return { secretFor: secretFor, linkSecret: linkSecret, newLinkCode: newLinkCode, derive: derive, itemKey: itemKey,
    profileName: profileName, empty: empty, merge: merge, same: same, lock: lock, open: open, exchange: exchange };
})();
if (typeof module !== "undefined") module.exports = Sync;

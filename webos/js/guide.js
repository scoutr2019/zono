// TV guide: Xtream Codes guide data and XMLTV files (for M3U playlists and for searching), catch-up links,
// the "hide adult groups" rule. Plain ES5, no screen code (tested with node).
(function (root) {
  "use strict";

  function text64(value) {
    // Xtream sends titles and descriptions base64-encoded (UTF-8)
    var s = String(value || "");
    if (!s || !/^[A-Za-z0-9+\/=\s]+$/.test(s) || s.replace(/\s/g, "").length % 4) return s;
    try { return decodeURIComponent(escape(atob(s.replace(/\s/g, "")))); } catch (e) { return s; }
  }

  /** Xtream get_short_epg / get_simple_data_table -> [{title, desc, start, end, label, archive}] sorted by start. */
  function xtreamPrograms(data) {
    var rows = data && Array.isArray(data.epg_listings) ? data.epg_listings : [];
    var out = [];
    rows.forEach(function (r) {
      if (!r || typeof r !== "object") return;
      var start = parseInt(r.start_timestamp, 10) || 0, end = parseInt(r.stop_timestamp, 10) || 0;
      if (!start || !end || end <= start) return;
      out.push({ title: text64(r.title), desc: text64(r.description).slice(0, 400), start: start, end: end,
        label: String(r.start || ""), archive: "has_archive" in r ? ["0", "", "None", "False", "false"].indexOf(String(r.has_archive)) < 0 : null });
    });
    out.sort(function (a, b) { return a.start - b.start; });
    return out;
  }

  var STAMP = /^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})?\s*([+-]\d{4})?/;
  /** "20261109150000 +0100" -> unix seconds (UTC). */
  function parseTime(value) {
    var m = STAMP.exec(String(value || "").trim());
    if (!m) return null;
    var t = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0)) / 1000;
    if (m[7]) t -= (m[7][0] === "-" ? -1 : 1) * (+m[7].slice(1, 3) * 3600 + +m[7].slice(3, 5) * 60);
    return t;
  }

  function keyName(name) {
    return String(name || "").toLowerCase().replace(/\b(hd|fhd|uhd|4k|sd|hevc|backup)\b/g, "").replace(/[^a-z0-9À-ɏ]/g, "");
  }

  function unescapeXml(s) {
    return String(s || "").replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"')
      .replace(/&apos;/g, "'").replace(/&#(\d+);/g, function (_, n) { return String.fromCharCode(+n); }).replace(/&amp;/g, "&").trim();
  }
  function attr(tag, name) {
    var m = new RegExp("\\s" + name + "=\"([^\"]*)\"").exec(tag) || new RegExp("\\s" + name + "='([^']*)'").exec(tag);
    return m ? unescapeXml(m[1]) : "";
  }
  function inner(block, name) {
    var m = new RegExp("<" + name + "(?:\\s[^>]*)?>([\\s\\S]*?)</" + name + ">").exec(block);
    return m ? unescapeXml(m[1]) : "";
  }

  /** An XMLTV file -> {programs: {channel id: [{title, desc, start, end}]}, names: {keyName: channel id}}.
   *  keep(id): only those channels; only programmes from `before` seconds ago to `after` seconds ahead. */
  function parseXmltv(xml, keep, now, before, after, limit) {
    now = now || Date.now() / 1000; before = before || 2 * 86400; after = after || 4 * 86400; limit = limit || 300000;
    var guide = { programs: {}, names: {} }, count = 0, m;
    var channels = /<channel\s[^>]*>[\s\S]*?<\/channel>/g;
    while ((m = channels.exec(xml))) {
      var id = attr(m[0].slice(0, m[0].indexOf(">") + 1), "id");
      if (!id) continue;
      guide.names[keyName(id)] = guide.names[keyName(id)] || id;
      var names = /<display-name[^>]*>([\s\S]*?)<\/display-name>/g, d;
      while ((d = names.exec(m[0]))) { var k = keyName(unescapeXml(d[1])); if (k && !guide.names[k]) guide.names[k] = id; }
    }
    var programmes = /<programme\s([^>]*)>([\s\S]*?)<\/programme>/g;
    while ((m = programmes.exec(xml)) && count < limit) {
      var head = " " + m[1], channel = attr(head, "channel");
      if (!channel || (keep && !keep(channel))) continue;
      var start = parseTime(attr(head, "start")), end = parseTime(attr(head, "stop"));
      if (!start || !end || end < now - before || start > now + after) continue;
      (guide.programs[channel] = guide.programs[channel] || []).push({ title: inner(m[2], "title"), desc: inner(m[2], "desc").slice(0, 400), start: start, end: end });
      count++;
    }
    Object.keys(guide.programs).forEach(function (c) { guide.programs[c].sort(function (a, b) { return a.start - b.start; }); });
    return guide;
  }

  /** The guide's channel id for a library channel: its tvg-id / epg id, else by (loose) name. */
  function channelFor(guide, item) {
    if (!guide || !item) return null;
    if (item.epg && guide.programs[item.epg]) return item.epg;
    var tries = [item.epg, item.tvgName, item.title];
    for (var i = 0; i < tries.length; i++) {
      var id = tries[i] && guide.names[keyName(tries[i])];
      if (id && guide.programs[id]) return id;
    }
    return null;
  }

  /** What is on now and next: {now, next: [...]}. */
  function nowNext(programs, now, count) {
    now = now || Date.now() / 1000;
    var current = null, next = [];
    (programs || []).forEach(function (p) {
      if (p.start <= now && p.end > now) current = p;
      else if (p.start > now && next.length < (count || 4)) next.push(p);
    });
    return { now: current, next: next };
  }

  /** Programmes whose title has all the words, on the given library channels, from now up to `ahead`. */
  function search(guide, channels, query, now, ahead, limit) {
    now = now || Date.now() / 1000; ahead = ahead || 2 * 86400; limit = limit || 60;
    var words = String(query || "").toLowerCase().split(/\s+/).filter(Boolean), found = [], seen = {};
    if (!words.length || !guide) return found;
    channels.forEach(function (item) {
      var id = channelFor(guide, item);
      if (!id || seen[id]) return;
      seen[id] = 1;
      guide.programs[id].forEach(function (p) {
        if (p.end <= now || p.start > now + ahead) return;
        var t = p.title.toLowerCase();
        if (words.every(function (w) { return t.indexOf(w) >= 0; })) found.push({ channel: item, program: p });
      });
    });
    found.sort(function (a, b) { return a.program.start - b.program.start; });
    return found.slice(0, limit);
  }

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  /** Xtream catch-up link. `label` is the programme start in the server's own time ("YYYY-MM-DD HH:MM:SS"). */
  function timeshiftUrl(base, user, password, sid, program) {
    var label = String(program.label || "").replace("T", " ");
    if (!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(label)) {
      var d = new Date(program.start * 1000);
      label = d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
    }
    var minutes = Math.max(1, Math.round((program.end - program.start) / 60));
    var stamp = label.slice(0, 10) + ":" + label.slice(11, 16).replace(":", "-");
    var q = function (v) { return encodeURIComponent(String(v)); };
    return base + "/timeshift/" + q(user) + "/" + q(password) + "/" + minutes + "/" + stamp + "/" + q(sid) + ".ts";
  }

  /** Can this programme be watched again? */
  function canCatchUp(item, program, now) {
    now = now || Date.now() / 1000;
    if (!item || !item.archive || program.start >= now) return false;
    if (program.archive === false) return false;
    var days = item.archiveDays || 0;
    return !days || program.start > now - days * 86400;
  }

  var ADULT = ["adult", "xxx", "18+", "+18", "porn", "erotic", "erotik", "sex", "playboy", "hustler", "nsfw", "brazzers",
    "redlight", "for adults", "volwassen", "hot girls"];
  function adult(text) {
    var t = String(text || "").toLowerCase();
    return ADULT.some(function (w) { return t.indexOf(w) >= 0; });
  }

  /** SubRip (.srt) -> WebVTT for the <track> element. */
  function srtToVtt(srt) {
    return "WEBVTT\n\n" + String(srt || "").replace(/^﻿/, "").replace(/\r/g, "")
      .replace(/(\d{2}:\d{2}:\d{2}),(\d{3})/g, "$1.$2").replace(/^\d+\n(?=\d{2}:\d{2})/gm, "")
      .replace(/<\/?font[^>]*>/gi, "");
  }

  /** SubRip (.srt) or WebVTT -> [{start, end, text}] in seconds, sorted. */
  function parseSubtitles(raw) {
    var cues = [], blocks = String(raw || "").replace(/^\uFEFF/, "").replace(/\r/g, "").split(/\n{2,}/);
    var time = /(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})/;
    blocks.forEach(function (block) {
      var lines = block.split("\n"), at = -1;
      for (var i = 0; i < lines.length; i++) if (time.test(lines[i])) { at = i; break; }
      if (at < 0) return;
      var m = time.exec(lines[at]);
      var text = lines.slice(at + 1).join("\n").replace(/<[^>]+>/g, "").replace(/\{\\[^}]*\}/g, "").trim();
      if (!text) return;
      cues.push({ start: +m[1] * 3600 + +m[2] * 60 + +m[3] + +m[4] / 1000, end: +m[5] * 3600 + +m[6] * 60 + +m[7] + +m[8] / 1000, text: text });
    });
    cues.sort(function (a, b) { return a.start - b.start; });
    return cues;
  }
  function cueAt(cues, t) {
    var lo = 0, hi = cues.length - 1, found = null;
    while (lo <= hi) { var mid = (lo + hi) >> 1; if (cues[mid].start <= t) { found = mid; lo = mid + 1; } else hi = mid - 1; }
    for (var i = found; i !== null && i >= 0 && i > found - 3; i--) if (cues[i].start <= t && cues[i].end > t) return cues[i];
    return null;
  }

  /** "Show - S02E05 - Name" -> [2, 5]. */
  function episodeNumbers(title) {
    var m = /\bS(\d{1,2})\s*[ .x]?\s*E(\d{1,3})\b/i.exec(String(title || ""));
    return m ? [+m[1], +m[2]] : [null, null];
  }
  function cleanQuery(title) {
    return String(title || "").replace(/^\s*(?:\[[^\]]{1,8}\]\s*)?(?:[A-Z]{2,3}\s*[-|:]\s*)?/, "").replace(/[\(\[][^\)\]]*[\)\]]/g, " ")
      .replace(/\b(4K|UHD|FHD|HD|SD|MULTI|SUB|HEVC|x26[45])\b/gi, " ").replace(/\s+/g, " ").replace(/^[\s\-|:]+|[\s\-|:]+$/g, "");
  }

  var api = { text64: text64, xtreamPrograms: xtreamPrograms, parseTime: parseTime, keyName: keyName, parseXmltv: parseXmltv,
    channelFor: channelFor, nowNext: nowNext, search: search, timeshiftUrl: timeshiftUrl, canCatchUp: canCatchUp, adult: adult,
    srtToVtt: srtToVtt, parseSubtitles: parseSubtitles, cueAt: cueAt, episodeNumbers: episodeNumbers, cleanQuery: cleanQuery };
  if (typeof module !== "undefined") module.exports = api; else root.Guide = api;
})(this);

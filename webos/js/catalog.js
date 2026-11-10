// Plain ES5 so it also runs on older LG TVs (webOS 3+).
// Reading Xtream Codes and M3U, the same rules as Zono for Windows and Android. No screen code here (tested with node).
(function (root) {
  "use strict";

  var UHD = /(^|[^A-Z0-9])(4K|8K|16K|UHD|2160P?)(?![A-Z0-9])|ᵁᴴᴰ/i;

  /** A 4K (or better) channel, from the provider's own name or group: "4K | VRT 1", "NPO 1 UHD", "NPO 2ᵁᴴᴰ". */
  function isUhd(text) { return UHD.test(String(text || "")); }
  function itemUhd(item) { return isUhd(item.title + " " + (item.group || "")); }

  /** 4K first, otherwise the provider's order. */
  function uhdFirst(items) {
    var a = [], b = [];
    items.forEach(function (it) { (itemUhd(it) ? a : b).push(it); });
    return a.concat(b);
  }

  function groupsOf(items, uhd) {
    var seen = {}, list = [];
    items.forEach(function (it) { if (!(it.group in seen)) { seen[it.group] = 1; list.push(it.group); } });
    if (!uhd) return list;
    return list.filter(isUhd).concat(list.filter(function (g) { return !isUhd(g); }));
  }

  function base(server) {
    var text = String(server || "").trim();
    if (!/^https?:\/\//i.test(text)) text = "http://" + text;
    text = text.split("#")[0].split("?")[0];
    text = text.replace(/\/(?:player_api|get|panel_api)\.php\/?$/i, "");
    return text.replace(/\/+$/, "");
  }

  function quote(value) {
    return encodeURIComponent(String(value)).replace(/[!'()*]/g, function (c) { return "%" + c.charCodeAt(0).toString(16).toUpperCase(); });
  }

  function streamUrl(source, kind, id, ext) {
    return base(source.server) + "/" + kind + "/" + quote(source.user) + "/" + quote(source.password) + "/" + quote(id) + (ext ? "." + ext : "");
  }

  function apiUrl(source, action, extra) {
    var q = "username=" + quote(source.user) + "&password=" + quote(source.password);
    if (action) q += "&action=" + action;
    Object.keys(extra || {}).forEach(function (k) { q += "&" + k + "=" + quote(extra[k]); });
    return base(source.server) + "/player_api.php?" + q;
  }

  function num(value) {
    var n = parseFloat(value);
    return isFinite(n) && n > 0 ? n : 0;
  }

  function str(value) {
    if (value === null || value === undefined) return "";
    if (Array.isArray(value)) return value.length && typeof value[0] !== "object" ? String(value[0]) : "";
    return typeof value === "object" ? "" : String(value);
  }

  function categories(data) {
    var groups = {};
    (Array.isArray(data) ? data : []).forEach(function (c) {
      if (c && typeof c === "object" && c.category_id !== undefined && c.category_name !== undefined) groups[String(c.category_id)] = String(c.category_name);
    });
    return groups;
  }

  /** kind: live, movie or series. Compact items: {id, kind, title, group, image, url, sid, rating, added, plot}. */
  function streams(data, kind, source, groups) {
    if (!Array.isArray(data)) throw new Error("no list");
    var server = base(source.server), key = kind === "series" ? "series_id" : "stream_id", items = [];
    for (var i = 0; i < data.length; i++) {
      var row = data[i];
      if (!row || typeof row !== "object" || row[key] === undefined || row[key] === null) continue;
      var sid = String(row[key]);
      var url = kind === "series" ? "" : kind === "live" ? streamUrl(source, "live", sid, "m3u8")
        : streamUrl(source, "movie", sid, str(row.container_extension) || "mp4");
      var item = { id: server + "|" + kind + "|" + sid, kind: kind, sid: sid, title: str(row.name) || sid,
        group: groups[str(row.category_id)] || "", image: str(row.cover) || str(row.stream_icon), url: url };
      if (kind !== "live") {
        var rating = num(row.rating) || num(row.rating_5based) * 2;
        item.rating = Math.round(Math.min(rating, 10) * 10) / 10;
        item.added = Math.floor(num(row.added || row.last_modified));
        if (row.plot) item.plot = str(row.plot);
      }
      items.push(item);
    }
    return items;
  }

  function cleanEpisode(raw) {
    var text = String(raw || "").trim();
    var m = /S\d{1,2}\s*[ .x]?\s*E\d{1,3}\s*[-:|]?\s*(.*)$/i.exec(text);
    return m ? m[1].trim() : text;
  }

  /** Episodes of a series (get_series_info), sorted by season and number. */
  function episodes(data, source) {
    var server = base(source.server), seasons = data && data.episodes, pairs = [], rows = [];
    if (!seasons) return [];
    if (Array.isArray(seasons)) seasons.forEach(function (v, i) { pairs.push([i + 1, v]); });
    else Object.keys(seasons).forEach(function (k) { pairs.push([parseInt(k, 10) || 0, seasons[k]]); });
    pairs.forEach(function (pair) {
      (Array.isArray(pair[1]) ? pair[1] : []).forEach(function (ep) {
        if (!ep || ep.id === undefined) return;
        var info = ep.info && typeof ep.info === "object" ? ep.info : {};
        var season = parseInt(ep.season, 10) || pair[0], number = Math.floor(num(ep.episode_num));
        rows.push({ id: server + "|episode|" + ep.id, kind: "episode", sid: String(ep.id), title: cleanEpisode(str(ep.title)),
          group: String(season), number: number, image: str(info.movie_image), plot: str(info.plot),
          url: streamUrl(source, "series", String(ep.id), str(ep.container_extension) || "mp4") });
      });
    });
    rows.sort(function (a, b) { return (+a.group - +b.group) || (a.number - b.number); });
    return rows;
  }

  function splitTitle(line) {
    var quoted = false;
    for (var i = 0; i < line.length; i++) {
      if (line[i] === '"') quoted = !quoted;
      if (line[i] === "," && !quoted) return line.slice(i + 1).trim();
    }
    return "";
  }

  function parseM3u(raw) {
    var items = [], info = null, title = "";
    String(raw || "").replace(/^﻿/, "").split(/\r?\n/).forEach(function (line) {
      line = line.trim();
      if (line.indexOf("#EXTINF:") === 0) {
        info = {};
        line.replace(/([\w-]+)="([^"]*)"/g, function (_, k, v) { info[k] = v; return ""; });
        title = splitTitle(line);
      } else if (info && line && line[0] !== "#") {
        if (/^https?:\/\//i.test(line)) {
          var path = line.split("?")[0].toLowerCase();
          var kind = /\/movie\//.test(path) || /\.(mp4|mkv|avi)$/.test(path) ? "movie" : "live";
          items.push({ id: line, kind: kind, title: title || info["tvg-name"] || line, group: info["group-title"] || "",
            image: info["tvg-logo"] || "", url: line });
        }
        info = null;
      }
    });
    return items;
  }

  function words(query) { return String(query || "").toLowerCase().split(/\s+/).filter(Boolean); }
  function matches(item, w) {
    if (!w.length) return false;
    var t = item.title.toLowerCase();
    return w.every(function (x) { return t.indexOf(x) >= 0; });
  }

  function initials(title) {
    var parts = String(title || "").replace(/^[A-Z]{2,3}\s*[-|:]\s*/, "").split(/[\s\-|:.,;!?'"()\[\]\/]+/).filter(Boolean);
    return parts.slice(0, 2).map(function (p) { return p[0].toUpperCase(); }).join("") || "Z";
  }

  /** The shelves the screens show. */
  function shelves(all, uhd) {
    var providerLive = all.filter(function (i) { return i.kind === "live"; });
    var live = uhd ? uhdFirst(providerLive) : providerLive;
    var movies = all.filter(function (i) { return i.kind === "movie"; });
    var series = all.filter(function (i) { return i.kind === "series"; });
    function newest(list) { return list.filter(function (i) { return i.added > 0; }).sort(function (a, b) { return b.added - a.added; }).slice(0, 30); }
    return {
      all: all, live: live, movies: movies, series: series,
      liveGroups: groupsOf(providerLive, uhd), movieGroups: groupsOf(movies), seriesGroups: groupsOf(series),
      newMovies: newest(movies), newSeries: newest(series),
      topMovies: movies.filter(function (i) { return i.rating >= 7; }).sort(function (a, b) { return b.rating - a.rating; }).slice(0, 30),
      uhdChannels: live.filter(itemUhd).slice(0, 30),
    };
  }

  var api = { isUhd: isUhd, itemUhd: itemUhd, uhdFirst: uhdFirst, groupsOf: groupsOf, base: base, quote: quote,
    streamUrl: streamUrl, apiUrl: apiUrl, categories: categories, streams: streams, episodes: episodes,
    cleanEpisode: cleanEpisode, parseM3u: parseM3u, words: words, matches: matches, initials: initials, shelves: shelves };
  if (typeof module !== "undefined") module.exports = api; else root.Catalog = api;
})(this);

// Zono for LG TV (webOS). Works with the remote's arrows / OK / Back and with the Magic Remote pointer.
// Written for the browser inside webOS 4 and newer (no async/await, no optional chaining).
(function () {
  "use strict";
  var VERSION = "0.1.0";
  var KEY = { LEFT: 37, UP: 38, RIGHT: 39, DOWN: 40, OK: 13, BACK: 461, BACKSPACE: 8, ESC: 27, CH_UP: 33, CH_DOWN: 34,
    PLAY: 415, PAUSE: 19, PLAY_PAUSE: 10252, STOP: 413, FF: 417, RW: 412 };

  // ------------------------------------------------------------------ storage (only on this TV)
  function load(key, fallback) {
    try { var v = localStorage.getItem("zono." + key); return v === null ? fallback : JSON.parse(v); } catch (e) { return fallback; }
  }
  function save(key, value) {
    try { if (value === null) localStorage.removeItem("zono." + key); else localStorage.setItem("zono." + key, JSON.stringify(value)); } catch (e) { /* full */ }
  }

  // The library is kept in IndexedDB (too big for localStorage), so Zono starts at once next time.
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
  function get(url, timeout) {
    return new Promise(function (resolve, reject) {
      var x = new XMLHttpRequest();
      x.open("GET", url, true);
      x.timeout = timeout || 60000;
      x.onload = function () {
        if (x.status === 401 || x.status === 403) reject(loginError());
        else if (x.status >= 200 && x.status < 300) resolve(x.responseText);
        else reject(new Error("HTTP " + x.status));
      };
      x.onerror = function () { reject(new Error("network")); };
      x.ontimeout = function () { reject(new Error("timeout")); };
      x.send();
    });
  }
  function loginError() { var e = new Error(T("error_login")); e.login = true; return e; }
  function json(url) { return get(url).then(function (t) { return JSON.parse(t.replace(/^﻿/, "")); }); }

  /** The whole library from the provider. */
  function fetchLibrary(source, step) {
    if (source.type !== "xtream") {
      step("live");
      return get(source.m3u, 90000).then(function (raw) {
        var items = Catalog.parseM3u(raw);
        if (!items.length) throw new Error(T("error_empty"));
        return items;
      });
    }
    var all = [];
    return json(Catalog.apiUrl(source)).then(function (account) {
      var info = account && account.user_info;
      if (!info || String(info.auth) === "0") throw loginError();
      var kinds = [["live", "live", "get_live_streams"], ["movie", "vod", "get_vod_streams"], ["series", "series", "get_series"]];
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
      if (!all.length) throw new Error(T("error_empty"));
      return all;
    });
  }

  // ------------------------------------------------------------------ state
  var S = {
    source: load("source", null),
    shelves: Catalog.shelves([], true),
    progress: load("progress", []), // [{item, pos, dur, t}]
    favorites: load("favorites", []),
    uhd: load("uhd", true),
    loading: false, step: "", error: "",
    page: "discover", series: null,
  };

  function refresh(source, quiet) {
    S.loading = !quiet; S.error = ""; S.step = "";
    render();
    return fetchLibrary(source, function (kind) { S.step = kind; if (!quiet) render(); }).then(function (items) {
      S.loading = false;
      S.shelves = Catalog.shelves(items, S.uhd);
      db.put("library", items);
      if (!S.source) { S.source = source; save("source", source); }
      render();
      return true;
    }, function (problem) {
      S.loading = false;
      if (!quiet) S.error = problem.login ? T("error_login") : String(problem.message || problem).indexOf(T("error_empty")) === 0
        ? T("error_empty") : T("error_connect", problem.message || "?");
      render();
      return false;
    });
  }

  function start() {
    if (!S.source) return render();
    S.loading = true; render();
    db.get("library").then(function (items) {
      if (items && items.length) {
        S.shelves = Catalog.shelves(items, S.uhd);
        S.loading = false;
        render();
        refresh(S.source, true);
      } else refresh(S.source, false);
    });
  }

  function saveProgress(item, pos, dur) {
    var list = S.progress.filter(function (p) { return p.item.id !== item.id; });
    if (!(dur > 0 && pos > dur * 0.94) && pos > 60) {
      list.unshift({ item: { id: item.id, kind: item.kind, title: item.title, image: item.image || "", url: item.url, group: item.group || "",
        number: item.number || 0 }, pos: pos, dur: dur, t: Date.now() });
    }
    S.progress = list.slice(0, 40);
    save("progress", S.progress);
  }

  function toggleFavorite(id) {
    var i = S.favorites.indexOf(id);
    if (i >= 0) S.favorites.splice(i, 1); else S.favorites.push(id);
    save("favorites", S.favorites);
  }

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
  function picture(src) {
    if (!src) return null;
    var img = h("img", { src: src, alt: "" });
    img.onerror = function () { img.remove(); };
    return img;
  }

  function poster(item, go, opts) {
    opts = opts || {};
    var pic = h("div", { cls: "pic" }, [placeholder(item.title), picture(item.image),
      item.rating > 0 ? h("div", { cls: "corner", text: item.rating.toFixed(1) }) : null,
      opts.progress ? h("div", { cls: "progress" }, [h("div", { style: "width:" + Math.max(2, opts.progress * 100) + "%" })]) : null]);
    return h("div", { cls: "card poster", go: go }, [pic, h("div", { cls: "title", text: item.title })]);
  }

  function wide(item, go, opts) {
    opts = opts || {};
    var isLive = item.kind === "live";
    var pic = h("div", { cls: "pic" }, [item.image ? null : placeholder(item.title), picture(item.image),
      isLive && Catalog.itemUhd(item) ? h("div", { cls: "corner k", text: "4K" }) : null,
      opts.progress ? h("div", { cls: "progress" }, [h("div", { style: "width:" + Math.max(2, opts.progress * 100) + "%" })]) : null]);
    return h("div", { cls: "card wide" + (isLive ? " logo" : ""), go: go }, [pic, h("div", { cls: "title", text: item.title }),
      opts.sub ? h("div", { cls: "sub", text: opts.sub }) : null]);
  }

  function rowItem(title, go, opts) {
    opts = opts || {};
    var kids = [];
    if (opts.image !== undefined) kids.push(h("div", { cls: "logo-box" }, [opts.image ? picture(opts.image) : h("span", { text: Catalog.initials(title) })]));
    kids.push(h("div", { cls: "name", text: title }));
    if (opts.badge) kids.push(h("span", { cls: "badge", text: opts.badge }));
    if (opts.trail) kids.push(h("span", { cls: "trail", text: opts.trail }));
    return h("div", { cls: "row-item" + (opts.sel ? " sel" : ""), go: go, long: opts.long, "data-key": opts.key }, kids);
  }

  function pill(text, sel, go, key) { return h("div", { cls: "pill" + (sel ? " sel" : ""), go: go, "data-key": key, text: text }); }
  function shelf(title, cards) { return h("div", { cls: "shelf" }, [h("h2", { text: title }), h("div", { cls: "scroll-x" }, cards)]); }
  function groupName(g) { return g || T("other"); }
  function stepText() {
    return S.step === "live" ? T("loading_live") : S.step === "movie" ? T("loading_movies") : S.step === "series" ? T("loading_series") : T("loading");
  }

  /** Long lists are drawn in batches: the next batch when the focus comes near the end. */
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

  // ------------------------------------------------------------------ screens
  var app = document.getElementById("app");
  var memory = {}; // focused element key per screen, to come back to the same place

  function render() {
    var keep = currentKey();
    app.innerHTML = "";
    if (!S.source) app.appendChild(loginScreen());
    else app.appendChild(homeScreen());
    restoreFocus(keep);
  }

  var login = { xtream: true, server: "", user: "", password: "", m3u: "", problem: "" };
  function loginScreen() {
    function input(key, placeholderText, type) {
      var el = h("input", { cls: "f", type: type || "text", placeholder: placeholderText, value: login[key], "data-key": "in-" + key,
        autocomplete: "off", autocapitalize: "off", spellcheck: "false" });
      el.tabIndex = -1;
      el.oninput = function () { login[key] = el.value; };
      el._go = function () { el.blur(); el.focus(); };
      return el;
    }
    function connect() {
      login.problem = "";
      var source = login.xtream ? { type: "xtream", server: login.server.trim(), user: login.user.trim(), password: login.password }
        : { type: "m3u", m3u: login.m3u.trim() };
      var ready = login.xtream ? source.server && source.user && source.password : /^https?:\/\//i.test(source.m3u);
      if (!ready) { login.problem = T("error_fields"); render(); return; }
      refresh(source, false);
    }
    var form = [h("div", null, [pill(T("tab_xtream"), login.xtream, function () { login.xtream = true; render(); }, "tab-x"),
      pill(T("tab_m3u"), !login.xtream, function () { login.xtream = false; render(); }, "tab-m")])];
    if (login.xtream) form.push(input("server", T("field_server"), "url"), input("user", T("field_user")), input("password", T("field_password"), "password"));
    else form.push(input("m3u", T("field_m3u"), "url"));
    var message = login.problem || S.error;
    if (message) form.push(h("div", { cls: "error", text: message }));
    form.push(S.loading ? h("div", { cls: "busy" }, [h("div", { cls: "spinner" }), h("span", { text: stepText() })])
      : h("div", null, [pill(T("connect"), true, connect, "connect")]));
    return h("div", { cls: "login" }, [
      h("div", { cls: "intro" }, [h("img", { src: "img/logo.png", alt: "Zono" }), h("h1", { text: T("login_title") }),
        h("p", { text: T("login_intro") }), h("div", { cls: "note", text: T("test_build") })]),
      h("div", { cls: "form" }, form)]);
  }

  var PAGES = [["discover", "nav_discover"], ["search", "nav_search"], ["live", "nav_live"], ["movies", "nav_movies"], ["series", "nav_series"], ["settings", "nav_settings"]];
  function homeScreen() {
    var menu = h("div", { cls: "menu" }, [h("img", { cls: "logo", src: "img/logo.png", alt: "Zono" })].concat(PAGES.map(function (p) {
      return rowItem(T(p[1]), function () { S.page = p[0]; S.series = null; render(); focusFirst(".main"); }, { sel: S.page === p[0] && !S.series, key: "menu-" + p[0] });
    })));
    var main = h("div", { cls: "main" });
    if (S.series) main.appendChild(seriesScreen(S.series));
    else if (!S.shelves.all.length) main.appendChild(loadingScreen());
    else main.appendChild(({ discover: discoverScreen, search: searchScreen, live: liveScreen, movies: moviesScreen, series: seriesListScreen, settings: settingsScreen })[S.page]());
    return h("div", { cls: "home" }, [menu, main]);
  }

  function loadingScreen() {
    if (S.error) return h("div", { cls: "center" }, [h("div", { text: S.error }), pill(T("retry"), true, function () { refresh(S.source, false); }, "retry")]);
    return h("div", { cls: "center" }, [h("div", { cls: "spinner" }), h("div", { text: stepText() })]);
  }

  function discoverScreen() {
    var sh = S.shelves, rows = [];
    if (S.progress.length) {
      var items = S.progress.map(function (p) { return p.item; });
      rows.push(shelf(T("continue_watching"), S.progress.map(function (p, i) {
        var sub = p.item.kind === "episode" ? T("season", p.item.group) : "";
        return wide(p.item, function () { play(items, i); }, { progress: p.dur ? p.pos / p.dur : 0, sub: sub });
      })));
    }
    var favs = sh.live.filter(function (c) { return S.favorites.indexOf(c.id) >= 0; });
    if (favs.length) rows.push(shelf(T("favorites"), favs.map(function (c, i) { return wide(c, function () { play(favs, i); }); })));
    if (sh.uhdChannels.length) rows.push(shelf(T("uhd_channels"), sh.uhdChannels.map(function (c, i) { return wide(c, function () { play(sh.uhdChannels, i); }); })));
    [["new_movies", sh.newMovies], ["top_movies", sh.topMovies]].forEach(function (pair) {
      if (pair[1].length) rows.push(shelf(T(pair[0]), pair[1].map(function (m, i) { return poster(m, function () { play(pair[1], i); }); })));
    });
    if (sh.newSeries.length) rows.push(shelf(T("new_series"), sh.newSeries.map(function (s) { return poster(s, function () { openSeries(s); }); })));
    if (!rows.length && sh.live.length) {
      var first = sh.live.slice(0, 30);
      rows.push(shelf(T("nav_live"), first.map(function (c, i) { return wide(c, function () { play(first, i); }); })));
    }
    return h("div", { cls: "scroll-y" }, [h("div", { cls: "page" }, rows)]);
  }

  var liveGroup = null;
  function liveScreen() {
    var sh = S.shelves, FAV = "\u0000fav";
    var groups = (S.favorites.length ? [FAV] : []).concat(sh.liveGroups);
    if (liveGroup === null || groups.indexOf(liveGroup) < 0) {
      var last = load("last", "");
      var found = sh.live.filter(function (c) { return c.id === last; })[0];
      liveGroup = found ? found.group : (sh.liveGroups[0] || "");
    }
    var channels = liveGroup === FAV ? sh.live.filter(function (c) { return S.favorites.indexOf(c.id) >= 0; })
      : sh.live.filter(function (c) { return c.group === liveGroup; });
    var groupList = h("div", { cls: "scroll-y" });
    lazyList(groupList, groups, function (g) {
      var name = g === FAV ? "♥ " + T("favorites") : groupName(g);
      return rowItem(name, function () { liveGroup = g; render(); }, { sel: g === liveGroup, badge: g !== FAV && Catalog.isUhd(g) ? "4K" : "", key: "g-" + g });
    }, 200);
    var channelList = h("div", { cls: "scroll-y" });
    if (!channels.length) channelList.appendChild(h("div", { cls: "empty", text: T("empty_group") }));
    lazyList(channelList, channels, function (c, i) {
      return rowItem(c.title, function () { save("last", c.id); play(channels, i); }, {
        image: c.image || "", badge: Catalog.itemUhd(c) ? "4K" : "", trail: S.favorites.indexOf(c.id) >= 0 ? "♥" : "", key: "c-" + c.id,
        long: function () { toggleFavorite(c.id); render(); toast(S.favorites.indexOf(c.id) >= 0 ? "♥ " + c.title : c.title); },
      });
    });
    return h("div", { cls: "live" }, [
      h("div", { cls: "groups" }, [h("h2", { text: T("groups"), style: "padding-left:24px" }), groupList]),
      h("div", { cls: "channels" }, [h("h2", { style: "padding-left:24px" }, [liveGroup === FAV ? T("favorites") : groupName(liveGroup),
        h("span", { cls: "hint", text: T("hold_ok_favorite") })]), channelList])]);
  }

  var gridGroup = { movies: "\u0000all", series: "\u0000all" };
  function gridScreen(kind, items, groups, open) {
    var ALL = "\u0000all", current = gridGroup[kind];
    var shown = current === ALL ? items.slice().sort(function (a, b) { return (b.added || 0) - (a.added || 0); })
      : items.filter(function (i) { return i.group === current; });
    var pills = h("div", { cls: "scroll-x", style: "padding:12px 8px" }, [pill(T("all"), current === ALL, function () { gridGroup[kind] = ALL; render(); }, "p-all")]
      .concat(groups.map(function (g) { return pill(groupName(g), g === current, function () { gridGroup[kind] = g; render(); }, "p-" + g); })));
    var grid = h("div", { cls: "grid" });
    if (!shown.length) grid.appendChild(h("div", { cls: "empty", text: T("empty_group") }));
    lazyList(grid, shown, function (item, i) { var el = poster(item, function () { open(shown, i); }); el.setAttribute("data-key", "i-" + item.id); return el; }, 50);
    return h("div", { cls: "scroll-y" }, [h("div", { cls: "page", style: "padding-top:44px" }, [pills, grid])]);
  }
  function moviesScreen() { return gridScreen("movies", S.shelves.movies, S.shelves.movieGroups, function (list, i) { play(list, i); }); }
  function seriesListScreen() { return gridScreen("series", S.shelves.series, S.shelves.seriesGroups, function (list, i) { openSeries(list[i]); }); }

  var episodeCache = {}, season = {};
  function openSeries(item) { S.series = item; render(); focusFirst(".eps"); }
  function forPlayer(ep, series) {
    var name = ep.title ? ep.number + ". " + ep.title : "E" + ep.number;
    var copy = {}; for (var k in ep) copy[k] = ep[k];
    copy.title = series.title + " · " + name;
    copy.image = ep.image || series.image;
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
      var seen = {}; S.progress.forEach(function (p) { seen[p.item.id] = p; });
      eps.appendChild(h("div", { cls: "scroll-x" }, seasons.map(function (s) {
        return pill(T("season", s), s === now, function () { season[series.id] = s; render(); }, "s-" + s);
      })));
      var rows = h("div", { cls: "scroll-y" });
      lazyList(rows, inSeason, function (e, i) {
        var p = seen[e.id];
        return rowItem(e.title ? e.number + ". " + e.title : T("episode", e.number), function () { play(queue, i); },
          { trail: p && p.dur ? Math.round(p.pos / p.dur * 100) + "%" : "", key: "e-" + e.id });
      });
      eps.appendChild(rows);
    }
    return h("div", { cls: "series" }, [
      h("div", { cls: "info" }, [h("div", { cls: "cover" }, [placeholder(series.title), picture(series.image)]), h("h1", { text: series.title }),
        series.rating > 0 ? h("div", { cls: "gold", text: "★ " + series.rating }) : null, series.plot ? h("div", { cls: "plot", text: series.plot }) : null]),
      eps]);
  }

  var query = "", searchTimer = null;
  function searchScreen() {
    var field = h("input", { cls: "f", type: "text", placeholder: T("search_hint"), value: query, "data-key": "search", style: "width:1000px" });
    field.tabIndex = -1;
    field._go = function () { field.blur(); field.focus(); };
    var grid = h("div", { cls: "grid" });
    function fill() {
      grid.innerHTML = "";
      var w = Catalog.words(query), found = [];
      if (w.length) {
        var all = S.shelves.all;
        for (var i = 0; i < all.length && found.length < 120; i++) if (Catalog.matches(all[i], w)) found.push(all[i]);
      }
      if (query.trim() && !found.length) grid.appendChild(h("div", { cls: "empty", text: T("no_results") }));
      var live = found.filter(function (i) { return i.kind === "live"; });
      found.forEach(function (item) {
        grid.appendChild(poster(item, function () {
          if (item.kind === "series") openSeries(item);
          else if (item.kind === "live") play(live, live.indexOf(item));
          else play([item], 0);
        }));
      });
    }
    field.oninput = function () { query = field.value; clearTimeout(searchTimer); searchTimer = setTimeout(fill, 300); };
    fill();
    return h("div", { cls: "scroll-y" }, [h("div", { cls: "page" }, [field, grid])]);
  }

  function settingsScreen() {
    var source = S.source, chosen = load("language", "");
    var where = source.type === "xtream" ? source.user + " @ " + Catalog.base(source.server).replace(/^https?:\/\//, "")
      : source.m3u.replace(/^https?:\/\//, "").split("/")[0];
    return h("div", { cls: "scroll-y" }, [h("div", { cls: "page", style: "max-width:1300px" }, [
      h("h2", { text: T("language") }),
      h("div", { cls: "scroll-x", style: "padding:8px;margin-bottom:44px" }, LANGS.map(function (l) {
        return pill(l[1] || T("language_system"), l[0] === chosen, function () { save("language", l[0]); pickLanguage(); render(); }, "lang-" + l[0]);
      })),
      h("h2", { text: T("nav_live") }),
      rowItem(T("uhd_first"), function () { S.uhd = !S.uhd; save("uhd", S.uhd); S.shelves = Catalog.shelves(S.shelves.all, S.uhd); render(); },
        { trail: T(S.uhd ? "on" : "off"), key: "uhd" }),
      h("h2", { text: T("account"), style: "margin-top:44px" }),
      h("div", { cls: "empty", text: where }),
      rowItem(T("refresh"), function () {
        toast(T("loading"));
        refresh(S.source, true).then(function (ok) { toast(ok ? "✓" : T("error_connect", "")); });
      }, { key: "refresh" }),
      rowItem(T("logout"), function () {
        S.source = null; save("source", null); save("progress", []); save("favorites", []); save("last", null);
        S.progress = []; S.favorites = []; S.shelves = Catalog.shelves([], S.uhd); S.page = "discover"; db.put("library", undefined);
        render();
      }, { key: "logout" }),
      h("div", { cls: "empty", style: "margin-top:44px;color:var(--dim)", text: T("version", VERSION) + " · " + T("test_build") }),
    ])]);
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
    var first = scope && (scope.querySelector(".f.sel") || focusables(scope)[0]);
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
        } else {
          if (r.left < box.left + margin) node.scrollLeft -= box.left + margin - r.left;
          else if (r.right > box.right - margin) node.scrollLeft += r.right - box.right + margin;
        }
      }
      node = node.parentElement;
    }
  }

  /** The nearest element in the pressed direction (what TVs call spatial navigation). */
  function move(dir) {
    var cur = document.activeElement;
    var all = focusables(app);
    if (!cur || all.indexOf(cur) < 0) return focus(app.querySelector(".menu .row-item.sel") || all[0]);
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
      if (gap < -4) continue; // not in that direction
      // how far it is off to the side (0 when they line up)
      var side = horizontal ? Math.max(0, Math.max(a.top, b.top) - Math.min(a.bottom, b.bottom))
        : Math.max(0, Math.max(a.left, b.left) - Math.min(a.right, b.right));
      var score = Math.max(0, gap) + side * 4 + (side > 0 ? 400 : 0);
      if (score < bestScore) { bestScore = score; best = el; }
    }
    if (best) focus(best);
  }

  var okTarget = null, okTimer = null, lastBack = 0;
  function back() {
    if (playerOpen()) return closePlayer();
    var a = document.activeElement;
    if (S.series) { S.series = null; render(); return; }
    if (S.source && S.page !== "discover") { S.page = "discover"; render(); focusFirst(".menu"); return; }
    if (a && a.tagName === "INPUT") { a.blur(); return; }
    if (Date.now() - lastBack < 2500) {
      if (window.PalmSystem && PalmSystem.platformBack) PalmSystem.platformBack(); else window.close();
    } else { lastBack = Date.now(); toast(T("exit_hint")); }
  }

  document.addEventListener("keydown", function (e) {
    var k = e.keyCode;
    if (playerOpen()) { if (playerKey(k, e)) e.preventDefault(); return; }
    var a = document.activeElement, typing = a && a.tagName === "INPUT";
    if (k === KEY.BACK || k === KEY.ESC || (k === KEY.BACKSPACE && !typing)) { e.preventDefault(); return back(); }
    if (typing && (k === KEY.LEFT || k === KEY.RIGHT)) {
      var atStart = a.selectionStart === 0 && a.selectionEnd === 0, atEnd = a.selectionStart === a.value.length;
      if ((k === KEY.LEFT && !atStart) || (k === KEY.RIGHT && !atEnd)) return; // move the text cursor
    }
    var dir = { 37: "left", 38: "up", 39: "right", 40: "down" }[k];
    if (dir) { e.preventDefault(); move(dir); return; }
    if (k === KEY.OK && a && a._go) {
      e.preventDefault();
      if (typing) { a.blur(); a.focus(); return; } // opens the TV keyboard
      if (okTarget) return; // the key repeats while it is held
      okTarget = a;
      // OK chooses when you let go; held for 0.7 s it does the "hold" action (favourite)
      clearTimeout(okTimer);
      if (a._long) okTimer = setTimeout(function () { if (okTarget === a) { okTarget = "used"; a._long(); } }, 700);
    }
  });
  document.addEventListener("keyup", function (e) {
    if (e.keyCode !== KEY.OK || playerOpen()) return;
    clearTimeout(okTimer);
    var a = document.activeElement;
    if (a && a === okTarget && a._go && a.tagName !== "INPUT") { okTarget = null; a._go(); }
    okTarget = null;
  });
  // Magic Remote / mouse: point to focus, click to choose
  document.addEventListener("mouseover", function (e) {
    var el = e.target.closest && e.target.closest(".f");
    if (el && el !== document.activeElement && !playerOpen()) { try { el.focus({ preventScroll: true }); } catch (x) { el.focus(); } }
  });
  document.addEventListener("click", function (e) {
    var el = e.target.closest && e.target.closest(".f");
    if (el && el._go && !playerOpen() && el.tagName !== "INPUT") el._go();
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
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.classList.remove("on"); }, 2500);
  }

  // ------------------------------------------------------------------ player
  var P = { queue: [], index: 0, retried: false, timer: null, saveTimer: null, hideTimer: null, returnFocus: null };
  var player = document.getElementById("player"), video = document.getElementById("video");
  function playerOpen() { return !player.hidden; }
  function isLive() { var it = P.queue[P.index]; return it && it.kind === "live"; }

  function play(queue, index) {
    if (!queue.length) return;
    P.queue = queue.slice(); P.index = Math.max(0, Math.min(index, queue.length - 1));
    P.returnFocus = currentKey();
    player.hidden = false;
    startItem(true);
  }

  function startItem(resume) {
    var item = P.queue[P.index];
    P.retried = false;
    video.pause();
    video.removeAttribute("src"); video.load();
    video.src = item.url;
    var info = "";
    var saved = null;
    if (!isLive() && resume) S.progress.forEach(function (p) { if (p.item.id === item.id) saved = p; });
    if (saved && saved.pos > 0) {
      info = T("resume");
      video.addEventListener("loadedmetadata", function seek() { video.removeEventListener("loadedmetadata", seek); try { video.currentTime = saved.pos; } catch (e) { /* not seekable */ } });
    }
    if (isLive()) { save("last", item.id); info = liveInfo(); }
    spinner(true);
    var p = video.play(); if (p && p.catch) p.catch(function () {});
    banner(item.title + (isLive() && Catalog.itemUhd(item) ? "  ·  4K" : ""), info);
    clearInterval(P.saveTimer);
    P.saveTimer = setInterval(remember, 15000);
  }

  function liveInfo() { return (P.index + 1) + " / " + P.queue.length + (P.queue.length > 1 ? "   ·   " + T("zap_hint") : ""); }
  function spinner(on) { document.getElementById("spinner").hidden = !on; }

  function banner(title, info) {
    document.getElementById("banner-title").textContent = title;
    var i = document.getElementById("banner-info"); i.textContent = info || ""; i.hidden = !info;
    showOverlay();
  }
  function showOverlay() {
    document.getElementById("banner").classList.add("on");
    var bar = document.getElementById("bar");
    bar.hidden = isLive();
    if (!isLive()) { updateBar(); bar.classList.add("on"); }
    clearTimeout(P.hideTimer);
    P.hideTimer = setTimeout(function () {
      if (video.paused && !isLive()) return;
      document.getElementById("banner").classList.remove("on"); bar.classList.remove("on");
    }, 4000);
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
    document.getElementById("bar-hint").textContent = video.paused ? "❚❚ " + T("paused") : T("seek_hint");
    document.getElementById("bar-fill").style.width = isFinite(d) && d > 0 ? (t / d * 100) + "%" : "0";
  }
  video.addEventListener("timeupdate", function () { if (document.getElementById("bar").classList.contains("on")) updateBar(); });
  video.addEventListener("playing", function () { spinner(false); P.retried = false; });
  video.addEventListener("waiting", function () { spinner(true); });
  video.addEventListener("pause", function () { if (playerOpen() && !isLive()) showOverlay(); });
  video.addEventListener("error", function () {
    if (!playerOpen() || !video.getAttribute("src")) return;
    var item = P.queue[P.index];
    if (!P.retried) {
      P.retried = true;
      setTimeout(function () { video.load(); var p = video.play(); if (p && p.catch) p.catch(function () {}); }, 1500);
      return;
    }
    if (isLive() && /\.m3u8$/.test(item.url)) {
      // some providers only send live TV as a plain .ts stream
      var copy = {}; for (var key in item) copy[key] = item[key];
      copy.url = item.url.replace(/\.m3u8$/, ".ts");
      P.queue[P.index] = copy;
      return startItem(false);
    }
    spinner(false);
    banner(item.title, T("playback_error"));
  });
  video.addEventListener("ended", function () {
    var item = P.queue[P.index];
    if (isLive()) return;
    saveProgress(item, video.duration, video.duration);
    if (item.kind === "episode" && P.index + 1 < P.queue.length) {
      P.index += 1; startItem(false); banner(P.queue[P.index].title, T("next_episode"));
    } else closePlayer();
  });

  function remember() {
    var item = P.queue[P.index];
    if (item && !isLive() && isFinite(video.duration) && video.duration > 0) saveProgress(item, video.currentTime, video.duration);
  }

  function closePlayer() {
    remember();
    clearInterval(P.saveTimer); clearTimeout(P.hideTimer);
    video.pause(); video.removeAttribute("src"); video.load();
    player.hidden = true;
    render();
    restoreFocus(P.returnFocus);
  }

  function zap(step) {
    if (P.queue.length < 2) return;
    P.index = (P.index + step + P.queue.length) % P.queue.length;
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

  function playerKey(k, e) {
    var live = isLive(), item = P.queue[P.index];
    switch (k) {
      case KEY.BACK: case KEY.ESC: case KEY.BACKSPACE: case KEY.STOP: closePlayer(); return true;
      case KEY.CH_UP: zap(-1); return true;
      case KEY.CH_DOWN: zap(1); return true;
      case KEY.UP: if (live) zap(-1); else showOverlay(); return true;
      case KEY.DOWN: if (live) zap(1); else showOverlay(); return true;
      case KEY.LEFT: if (!live) seek(e.repeat ? -30 : -10); return true;
      case KEY.RIGHT: if (!live) seek(e.repeat ? 30 : 10); return true;
      case KEY.RW: if (!live) seek(-30); return true;
      case KEY.FF: if (!live) seek(30); return true;
      case KEY.OK: case KEY.PLAY: case KEY.PAUSE: case KEY.PLAY_PAUSE:
        if (live) banner(item.title + (Catalog.itemUhd(item) ? "  ·  4K" : ""), liveInfo()); else togglePause();
        return true;
    }
    showOverlay();
    return false;
  }
  player.addEventListener("click", function () { if (isLive()) showOverlay(); else togglePause(); });

  // webOS pauses apps in the background: save the position and stop the stream
  document.addEventListener("visibilitychange", function () {
    if (document.hidden && playerOpen()) { remember(); video.pause(); }
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
  window.Zono = { state: S, render: render, version: VERSION }; // for tests
})();

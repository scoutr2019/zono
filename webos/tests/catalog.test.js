// node --test tests/
const test = require("node:test");
const assert = require("node:assert");
const C = require("../js/catalog.js");
const STRINGS = require("../js/strings.js");

const source = { type: "xtream", server: "example.com:8080/player_api.php", user: "jan peeters", password: "p@ss/1" };

test("server address", () => {
  assert.equal(C.base("example.com:8080/player_api.php"), "http://example.com:8080");
  assert.equal(C.base(" https://tv.example.com/ "), "https://tv.example.com");
  assert.equal(C.base("http://x.org/sub/get.php?username=a"), "http://x.org/sub");
});

test("links quote the login", () => {
  assert.equal(C.streamUrl(source, "live", "12", "m3u8"), "http://example.com:8080/live/jan%20peeters/p%40ss%2F1/12.m3u8");
  assert.equal(C.apiUrl(source, "get_series_info", { series_id: "7" }),
    "http://example.com:8080/player_api.php?username=jan%20peeters&password=p%40ss%2F1&action=get_series_info&series_id=7");
});

test("4K detection and order", () => {
  ["4K | VRT 1", "NPO 1 UHD", "NPO 2ᵁᴴᴰ", "Sky 2160p"].forEach((t) => assert.ok(C.isUhd(t), t));
  ["SKY4KIDS", "BBC One HD"].forEach((t) => assert.ok(!C.isUhd(t), t));
  const items = ["A HD", "B 4K", "C", "D UHD"].map((t) => ({ id: t, kind: "live", title: t, group: "" }));
  assert.deepEqual(C.uhdFirst(items).map((i) => i.title), ["B 4K", "D UHD", "A HD", "C"]);
  const g = [{ group: "NL" }, { group: "NL 4K" }, { group: "BE" }].map((x) => Object.assign({ title: "x" }, x));
  assert.deepEqual(C.groupsOf(g, true), ["NL 4K", "NL", "BE"]);
});

test("xtream streams", () => {
  const groups = C.categories([{ category_id: "1", category_name: "Belgie" }, { category_id: 2, category_name: "4K" }, "junk"]);
  assert.deepEqual(groups, { 1: "Belgie", 2: "4K" });
  const live = C.streams([{ name: "VRT 1 HD", stream_id: 101, stream_icon: "http://logo", category_id: "1" },
    { name: "VTM 4K", stream_id: "102", stream_icon: null, category_id: "2" }, { name: "no id" }], "live", source, groups);
  assert.equal(live.length, 2);
  assert.equal(live[0].id, "l101");
  assert.equal(live[0].url, undefined, "links are made when playing");
  assert.equal(C.urlOf(live[0], source), "http://example.com:8080/live/jan%20peeters/p%40ss%2F1/101.m3u8");
  assert.equal(live[1].image, "");
  const movies = C.streams([{ name: "Film", stream_id: 5, container_extension: "mkv", rating: "7.84", added: "1700000000" },
    { name: "Old", stream_id: 6, rating_5based: 4.5, container_extension: "" }], "movie", source, {});
  assert.equal(movies[0].rating, 7.8);
  assert.equal(movies[0].added, 1700000000);
  assert.ok(C.urlOf(movies[0], source).endsWith("/5.mkv"));
  assert.equal(movies[1].rating, 9);
  assert.ok(C.urlOf(movies[1], source).endsWith("/6.mp4"));
  assert.equal(C.shortId("http://x:1|movie|5"), "m5");
  assert.equal(C.shortId("http://x/list.m3u8"), "http://x/list.m3u8");
  assert.throws(() => C.streams({ user_info: { auth: 0 } }, "live", source, {}));
});

test("episodes", () => {
  const eps = C.episodes({ episodes: {
    2: [{ id: "902", episode_num: 1, title: "NL - Thuis - S02E01 - Terug", container_extension: "mkv", season: 2 }],
    1: [{ id: "802", episode_num: 2, title: "Thuis S01E02", info: { movie_image: "http://e2.jpg" } }, { id: "801", episode_num: "1", title: "De start" }] } }, source);
  assert.deepEqual(eps.map((e) => e.sid), ["801", "802", "902"]);
  assert.deepEqual(eps.map((e) => e.title), ["De start", "", "Terug"]);
  assert.equal(eps[1].image, "http://e2.jpg");
  assert.ok(eps[2].url.endsWith("/series/jan%20peeters/p%40ss%2F1/902.mkv"));
  assert.deepEqual(C.episodes({ episodes: [[{ id: "1" }], [{ id: "2" }]] }, source).map((e) => e.group), ["1", "2"]);
});

test("m3u", () => {
  const items = C.parseM3u('﻿#EXTM3U url-tvg="http://g.xml"\n#EXTINF:-1 tvg-id="een.be" tvg-logo="http://l.png" group-title="Vlaanderen",Eén HD\r\nhttp://s/live/1.ts\n' +
    '#EXTINF:-1 group-title="Films, nieuw",De film, deel 2\nhttp://s/movie/u/p/2.mkv\n#EXTINF:-1,Zonder link\n#EXTVLCOPT:x\n#EXTINF:-1,Rare\nrtmp://x\n');
  assert.deepEqual(items.map((i) => [i.title, i.group, i.kind]), [["Eén", "Vlaanderen", "live"], ["De film, deel 2", "Films, nieuw", "movie"]]);
});

test("search, initials, shelves", () => {
  assert.ok(C.matches({ title: "The Lord of the Rings" }, C.words("lord RINGS")));
  assert.ok(!C.matches({ title: "x" }, C.words("  ")));
  assert.equal(C.initials("BE - VRT Een"), "VE");
  assert.equal(C.initials("!!"), "Z");
  const sh = C.shelves([{ kind: "live", title: "A", group: "" }, { kind: "live", title: "B 4K", group: "" },
    { kind: "movie", title: "M", group: "", rating: 8, added: 5 }], true);
  assert.equal(sh.live[0].title, "B 4K");
  assert.equal(sh.topMovies.length, 1);
  const order = C.shelves([{ kind: "live", title: "a", group: "BE" }, { kind: "live", title: "b", group: "NL" }, { kind: "live", title: "c 4K", group: "NL" }], true);
  assert.deepEqual(order.liveGroups, ["BE", "NL"]);
});

test("all four languages have every text", () => {
  const keys = Object.keys(STRINGS.en).sort();
  for (const l of ["nl", "fr", "de"]) assert.deepEqual(Object.keys(STRINGS[l]).sort(), keys, l);
});

test("display names like Zono for Windows", () => {
  assert.deepEqual(C.cleanTitle("[ALL] NL: The Matrix (1999)"), { title: "The Matrix", year: "1999" });
  assert.equal(C.cleanTitle("NL - Breaking Bad").title, "Breaking Bad");
  assert.equal(C.cleanTitle("[TR] Uzak Şehir").title, "Uzak Şehir");
  assert.equal(C.cleanTitle("(ALL) De Zaak Alzheimer").title, "De Zaak Alzheimer");
  assert.ok(!C.cleanTitle("NPO 2ᵁᴴᴰ").title.includes("ᵁᴴᴰ"));
  assert.equal(C.cleanTitle("(2020)").title, "(2020)");
  assert.equal(C.cleanName("4K | VRT 1 HD"), "VRT 1");
  assert.equal(C.cleanName("16K NPO 2ᵁᴴᴰ"), "NPO 2");
  assert.equal(C.cleanName("BE: VTM 2 FHD"), "VTM 2");
  assert.equal(C.cleanName("|BE| Eén (BE)"), "Eén");
  ["HD", "4K", "|", "x"].forEach((t) => assert.ok(C.cleanName(t)));
  assert.ok(C.isSeparator("##### NL #####"));
  assert.ok(C.isSeparator("♦♦♦ WELCOME ♦♦♦"));
  ["NPO 1", "VRT 1 HD", "4K | VRT 1 HD", "RTL 4"].forEach((t) => assert.ok(!C.isSeparator(t), t));
  const live = C.streams([{ name: "4K | VRT 1 HD", stream_id: 1 }, { name: "##### BE #####", stream_id: 2 }], "live", source, {});
  assert.equal(live.length, 1);
  assert.equal(live[0].title, "VRT 1");
  assert.ok(C.itemUhd(live[0]), "4K comes from the provider's own name");
  assert.ok(C.matches(live[0], C.words("4k vrt")));
  const films = C.streams([{ name: "[ALL] BE: Loft (2008)", stream_id: 5 }], "movie", source, {});
  assert.deepEqual([films[0].title, films[0].year], ["Loft", "2008"]);
});

test("chosen countries first", () => {
  const items = [
    { id: "1", kind: "live", title: "TF1", group: "FR", cc: "FR" }, { id: "2", kind: "live", title: "VRT 1", group: "BE", cc: "BE" },
    { id: "3", kind: "live", title: "NPO 1", group: "NL", cc: "NL" }, { id: "4", kind: "live", title: "Canvas", group: "BE", cc: "BE" },
    { id: "5", kind: "movie", title: "A", group: "FR films", cc: "FR", added: 9 }, { id: "6", kind: "movie", title: "B", group: "NL films", cc: "NL", added: 1 },
  ];
  const sh = C.shelves(items, false, ["NL", "BE"]);
  assert.deepEqual(sh.live.map((i) => i.title), ["NPO 1", "VRT 1", "Canvas", "TF1"]);
  assert.deepEqual(sh.liveGroups, ["NL", "BE", "FR"]);
  assert.deepEqual(sh.movieGroups, ["NL films", "FR films"]);
  assert.deepEqual(sh.newMovies.map((i) => i.title), ["B", "A"], "own countries first, then the rest");
  assert.deepEqual(C.shelves(items, false, []).live.map((i) => i.title), ["TF1", "VRT 1", "NPO 1", "Canvas"], "no choice: provider order");
});

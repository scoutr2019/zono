// node --test tests/guide.test.js
const test = require("node:test");
const assert = require("node:assert");
const G = require("../js/guide.js");
const C = require("../js/catalog.js");
const b64 = (s) => Buffer.from(s, "utf8").toString("base64");

test("xtream guide rows", () => {
  const rows = G.xtreamPrograms({ epg_listings: [
    { title: b64("Het Journaal"), description: b64("Nieuws · één"), start: "2026-11-11 19:00:00", start_timestamp: "1794420000", stop_timestamp: "1794421800", has_archive: 1 },
    { title: b64("Thuis"), start_timestamp: 1794416400, stop_timestamp: 1794418200, has_archive: "0" },
    { title: "x", start_timestamp: 0, stop_timestamp: 5 }] });
  assert.deepEqual(rows.map((r) => r.title), ["Thuis", "Het Journaal"]);
  assert.equal(rows[1].desc, "Nieuws · één");
  assert.equal(rows[1].archive, true);
  assert.equal(rows[0].archive, false);
  assert.equal(G.text64("Sport"), "Sport"); // not base64 (length) -> as is
});

test("xmltv", () => {
  const xml = `<?xml version="1.0"?><tv>
  <channel id="een.be"><display-name lang="nl">Eén HD</display-name><display-name>VRT 1</display-name></channel>
  <channel id='npo1.nl'><display-name>NPO 1</display-name></channel>
  <programme start="20261111190000 +0100" stop="20261111194000 +0100" channel="een.be"><title lang="nl">Het Journaal</title><desc>Tom &amp; Jerry</desc></programme>
  <programme start="20261111180000 +0100" stop="20261111190000 +0100" channel="een.be"><title><![CDATA[Thuis]]></title></programme>
  <programme start="20261111180000 +0100" stop="20261111190000 +0100" channel="npo1.nl"><title>NOS</title></programme>
  <programme start="20251111180000 +0100" stop="20251111190000 +0100" channel="een.be"><title>Oud</title></programme>
  </tv>`;
  const now = Date.UTC(2026, 10, 11, 17, 30) / 1000;
  const g = G.parseXmltv(xml, (id) => id !== "npo1.nl", now);
  assert.deepEqual(g.programs["een.be"].map((p) => p.title), ["Thuis", "Het Journaal"]);
  assert.equal(g.programs["een.be"][1].desc, "Tom & Jerry");
  assert.equal(g.programs["npo1.nl"], undefined);
  assert.equal(g.programs["een.be"][0].start, Date.UTC(2026, 10, 11, 17, 0) / 1000);
  assert.equal(G.channelFor(g, { epg: "een.be" }), "een.be");
  assert.equal(G.channelFor(g, { title: "VRT 1 HD" }), "een.be");
  assert.equal(G.channelFor(g, { title: "Eén" }), "een.be");
  const nn = G.nowNext(g.programs["een.be"], now);
  assert.equal(nn.now.title, "Thuis");
  assert.equal(nn.next[0].title, "Het Journaal");
  const found = G.search(g, [{ title: "Eén", id: "c1" }], "journaal", now);
  assert.equal(found.length, 1);
  assert.equal(found[0].channel.id, "c1");
});

test("catch-up", () => {
  const p = { start: 1794416400, end: 1794418200, label: "2026-11-11 18:00:00" };
  assert.equal(G.timeshiftUrl("http://s:8080", "jan peeters", "p@ss", "12", p), "http://s:8080/timeshift/jan%20peeters/p%40ss/30/2026-11-11:18-00/12.ts");
  assert.ok(G.canCatchUp({ archive: 1, archiveDays: 7 }, p, p.end + 3600));
  assert.ok(!G.canCatchUp({ archive: 1, archiveDays: 1 }, p, p.end + 3 * 86400));
  assert.ok(!G.canCatchUp({ archive: 0 }, p, p.end + 60));
  assert.ok(!G.canCatchUp({ archive: 1 }, Object.assign({}, p, { archive: false }), p.end + 60));
});

test("catalogue keeps channel numbers, guide ids and archive", () => {
  const live = C.streams([{ name: "VRT 1", stream_id: 1, num: 7, epg_channel_id: "een.be", tv_archive: 1, tv_archive_duration: "7" },
    { name: "X", stream_id: 2, tv_archive: 0 }], "live", { server: "s", user: "u", password: "p" }, {});
  assert.deepEqual([live[0].num, live[0].epg, live[0].archive, live[0].archiveDays], [7, "een.be", 1, 7]);
  assert.equal(live[1].archive, undefined);
  const m3u = '#EXTM3U x-tvg-url="http://g/a.xml.gz,http://b"\n#EXTINF:-1 tvg-id="een.be" tvg-name="Een" tvg-chno="3",Eén\nhttp://x/1.ts\n';
  assert.equal(C.m3uGuideUrl(m3u), "http://g/a.xml.gz");
  assert.deepEqual([C.parseM3u(m3u)[0].epg, C.parseM3u(m3u)[0].tvgName, C.parseM3u(m3u)[0].num], ["een.be", "Een", 3]);
  assert.equal(C.xmltvUrl({ server: "http://s:1/", user: "a b", password: "c" }), "http://s:1/xmltv.php?username=a%20b&password=c");
});

test("subtitles and kids", () => {
  assert.equal(G.srtToVtt("1\r\n00:00:01,500 --> 00:00:03,000\r\n<font color=red>Hallo</font>\r\n"), "WEBVTT\n\n00:00:01.500 --> 00:00:03.000\nHallo\n");
  assert.deepEqual(G.episodeNumbers("Thuis - S02E05 - x"), [2, 5]);
  assert.equal(G.cleanQuery("NL - The Matrix (1999) 4K"), "The Matrix");
  assert.ok(G.adult("XXX Adults only"));
  assert.ok(!G.adult("Sport"));
});

test("subtitle cues", () => {
  const cues = G.parseSubtitles("1\r\n00:00:01,500 --> 00:00:03,000\r\n<i>Hallo</i>\r\n\r\n2\r\n00:01:00,000 --> 00:01:02,500\r\nTwee\nregels\r\n");
  assert.deepEqual(cues, [{ start: 1.5, end: 3, text: "Hallo" }, { start: 60, end: 62.5, text: "Twee\nregels" }]);
  assert.equal(G.cueAt(cues, 2).text, "Hallo");
  assert.equal(G.cueAt(cues, 10), null);
  assert.equal(G.cueAt(cues, 61).text, "Twee\nregels");
  assert.equal(G.parseSubtitles("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nVTT").length, 1);
});

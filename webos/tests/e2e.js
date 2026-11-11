// The whole app in a browser at TV size, driven with the remote's keys, against a fake Xtream provider,
// a fake OpenSubtitles and a fake zono.be.
//   node tests/e2e.js <test video .webm> <screenshot folder>
//   ZONO_ROOT=<unpacked ipk app folder> node tests/e2e.js ...   (the packaged app)
const http = require("http");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = process.env.ZONO_ROOT || path.join(__dirname, "..");
const VIDEO = fs.readFileSync(process.argv[2]);
const OUT = process.argv[3];
fs.mkdirSync(OUT, { recursive: true });
const b64 = (s) => Buffer.from(s, "utf8").toString("base64");
const NOW = Math.floor(Date.now() / 1000);
const received = { ping: [], report: [], subs: [] };

function sendVideo(req, res) {
  res.setHeader("Content-Type", "video/webm"); res.setHeader("Accept-Ranges", "bytes");
  const m = /bytes=(\d+)-(\d*)/.exec(req.headers.range || "");
  if (!m) return res.end(VIDEO);
  const start = +m[1], end = m[2] ? +m[2] : VIDEO.length - 1;
  res.statusCode = 206; res.setHeader("Content-Range", `bytes ${start}-${end}/${VIDEO.length}`);
  res.end(VIDEO.subarray(start, end + 1));
}
function listings(sid, full) {
  const rows = [];
  for (let i = full ? -6 : 0; i < 6; i++) {
    const start = NOW - 1800 + i * 3600, d = new Date(start * 1000);
    const label = d.toISOString().slice(0, 10) + " " + d.toTimeString().slice(0, 8);
    rows.push({ title: b64(i === 0 ? "Het Journaal" : i < 0 ? "Thuis " + -i : "Programma " + i), description: b64("Over vandaag · " + sid),
      start: label, start_timestamp: String(start), stop_timestamp: String(start + 3600), has_archive: i < 0 ? 1 : 0 });
  }
  return { epg_listings: rows };
}

function provider(req, res) {
  const url = new URL(req.url, "http://x");
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Api-Key, X-User-Agent");
  if (req.method === "OPTIONS") { res.statusCode = 204; return res.end(); }
  if (/^\/(live|movie|series|timeshift)\//.test(url.pathname)) return sendVideo(req, res);
  let body = "";
  req.on("data", (c) => (body += c));
  req.on("end", () => {
    // fake zono.be
    if (url.pathname === "/api/ping.php") { received.ping.push(JSON.parse(body)); return res.end('{"ok":true}'); }
    if (url.pathname === "/api/report.php") { received.report.push(JSON.parse(body)); return res.end('{"ok":true,"number":42}'); }
    // fake OpenSubtitles
    if (url.pathname === "/subs/subtitles") {
      received.subs.push({ query: url.search, key: req.headers["api-key"] });
      return res.end(JSON.stringify({ data: [{ attributes: { release: "Loft.2008.NL", download_count: 900, files: [{ file_id: 77 }] } }] }));
    }
    if (url.pathname === "/subs/download") return res.end(JSON.stringify({ link: "http://" + req.headers.host + "/subs/file.srt" }));
    if (url.pathname === "/subs/file.srt") return res.end("1\r\n00:00:00,500 --> 00:00:30,000\r\nHallo ondertitel\r\n");
    // fake provider
    const q = url.searchParams, good = q.get("username") === "demo" && q.get("password") === "geheim", action = q.get("action");
    const groups = ["4K | Belgie", "Belgie", "Nederland", "Sport", "XXX Adults"];
    let out;
    if (!good) out = { user_info: { auth: 0 } };
    else if (!action) out = { user_info: { auth: 1, status: "Active" } };
    else if (action.endsWith("_categories")) out = groups.map((n, i) => ({ category_id: String(i), category_name: n }));
    else if (action === "get_live_streams") out = Array.from({ length: 40 }, (_, i) => ({ num: i + 1, name: ["VRT 1", "VTM", "NPO 1", "Play Sports 1", "Canvas"][i % 5] + (i % 7 === 0 ? " 4K" : " HD") + " " + (i + 1), stream_id: i + 1, category_id: String(i % 4), tv_archive: i % 3 === 0 ? 1 : 0, tv_archive_duration: 7 }));
    else if (action === "get_vod_streams") out = Array.from({ length: 120 }, (_, i) => ({ name: ["De Zaak Alzheimer", "Loft", "Dune Part Two", "Oppenheimer", "Ad Astra"][i % 5] + " " + i, stream_id: 1000 + i, container_extension: "webm", rating: 5 + (i % 5), added: 1700000000 + i, category_id: i === 0 ? "4" : String(i % 3) }));
    else if (action === "get_series") out = Array.from({ length: 12 }, (_, i) => ({ name: ["Thuis", "De Mol", "Undercover", "Familie"][i % 4] + " " + i, series_id: 5000 + i, rating: 8.1, last_modified: 1700000000 + i, category_id: "1", plot: "Een Vlaamse reeks." }));
    else if (action === "get_series_info") out = { info: { plot: "Een Vlaamse reeks." }, episodes: { 1: [1, 2].map((n) => ({ id: "9" + n, episode_num: n, title: "S01E0" + n + " - Deel " + n, container_extension: "webm" })) } };
    else if (action === "get_vod_info") out = { info: { plot: "Een film over " + q.get("vod_id") + ".", genre: "Drama, Thriller", releasedate: "2026-03-01", duration: "01:44:00", director: "Jan", cast: "An, Bert", rating: "8.4" } };
    else if (action === "get_short_epg") out = listings(q.get("stream_id"), false);
    else if (action === "get_simple_data_table") out = listings(q.get("stream_id"), true);
    else out = [];
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(out));
  });
}

function files(req, res) {
  const file = path.join(ROOT, decodeURIComponent(new URL(req.url, "http://x").pathname));
  if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.statusCode = 404; return res.end(); }
  const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".png": "image/png" };
  res.setHeader("Content-Type", types[path.extname(file)] || "application/octet-stream");
  res.end(fs.readFileSync(file));
}
const listen = (handler) => new Promise((resolve) => { const s = http.createServer(handler).listen(0, "127.0.0.1", () => resolve(s)); });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failures = 0;
function check(ok, what) { console.log((ok ? "ok   " : "FAIL ") + what); if (!ok) failures++; }

(async () => {
  const api = await listen(provider), site = await listen(files);
  const server = "127.0.0.1:" + api.address().port, base = "http://" + server;
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.addInitScript((b) => {
    Object.defineProperty(navigator, "language", { get: () => "nl-BE" });
    window.ZONO_API = b + "/api"; window.ZONO_SUBS_API = b + "/subs"; window.ZONO_PAIR_API = b + "/nopair";
  }, base);
  await page.goto("http://127.0.0.1:" + site.address().port + "/index.html");
  const key = async (name, times = 1) => { for (let i = 0; i < times; i++) { await page.keyboard.press(name); await sleep(70); } };
  const focused = () => page.evaluate(() => (document.activeElement.textContent || document.activeElement.getAttribute("data-key") || "").trim());
  const focusKey = (k) => page.evaluate((k) => { const el = document.querySelector('[data-key="' + k + '"]'); el.focus(); return !!el; }, k);
  const shot = (name) => page.screenshot({ path: path.join(OUT, name + ".png") });
  const hold = async () => { await page.keyboard.down("Enter"); await sleep(900); await page.keyboard.up("Enter"); await sleep(200); };
  const video = () => page.evaluate(() => { const v = document.getElementById("video"); return { t: v.currentTime, src: v.src, paused: v.paused }; });

  // ---- login (wrong password first)
  await sleep(300);
  check((await focused()) === "Xtream Codes", "start on the Xtream tab");
  await key("ArrowDown"); await page.keyboard.type(server);
  await key("ArrowDown"); await page.keyboard.type("demo");
  await key("ArrowDown"); await page.keyboard.type("fout");
  await key("ArrowDown"); await key("Enter");
  await page.waitForSelector(".error");
  check((await page.textContent(".error")).includes("klopt niet"), "wrong password is explained in Dutch");
  await page.fill('[data-key="in-password"]', "geheim");
  await focusKey("connect"); await key("Enter");
  await page.waitForSelector(".hero h1", { timeout: 10000 });

  // ---- discover like the Windows app
  await page.waitForFunction(() => /Drama/.test((document.querySelector(".hero-meta") || {}).textContent || ""), null, { timeout: 5000 }).catch(() => {});
  check(/2026 {2}· {2}Drama {2}· {2}01:44:00 {2}· {2}★ 8.4/.test(await page.textContent(".hero-meta")), "banner: year, genre, duration, rating from the provider");
  check(!!(await page.$(".hero-rank .badge")), "banner: TOP 10 badge");
  check((await page.textContent(".greet h1")).startsWith("Goede"), "greeting");
  await focusKey("hero-play"); await key("ArrowRight");
  check((await focused()).includes("Meer info"), "banner buttons: Play → More info");
  await shot("01-discover");
  await key("Enter"); await page.waitForSelector(".detail .detail-plot");
  check((await page.textContent(".detail-plot")).startsWith("Een film over"), "More info opens the film page with the plot");
  await shot("02-detail");
  await key("Escape"); await sleep(150);
  check(!(await page.$(".detail")), "Back leaves the film page");

  // ---- live tv: what's on, guide, catch-up, reminder
  await focusKey("menu-live"); await key("Enter");
  await page.waitForFunction(() => /Het Journaal/.test((document.querySelector(".live-info") || {}).textContent || ""), null, { timeout: 5000 }).catch(() => {});
  check((await page.textContent(".live-info")).includes("Het Journaal"), "Live TV shows what's on now");
  check((await page.$eval(".channels h2", (h) => h.firstChild.textContent)) === "4K | Belgie", "4K group first");
  await key("ArrowRight"); await sleep(400);
  await shot("03-live");
  await focusKey("live-guide"); await key("Enter");
  await page.waitForSelector(".guide-list .row-item");
  check((await page.$$eval(".guide .day", (d) => d.map((x) => x.textContent))).includes("Vandaag"), "guide: days");
  check((await focused()).includes("Het Journaal"), "guide: focus on what's on now");
  await shot("04-guide");
  await key("ArrowUp"); await sleep(100);
  check((await focused()).includes("Terugkijken"), "guide: earlier programme can be watched again");
  await key("Enter"); await sleep(800);
  check((await video()).src.includes("/timeshift/demo/geheim/60/"), "catch-up plays the timeshift link");
  await key("Escape"); await sleep(200);
  await page.evaluate(() => { const rows = [...document.querySelectorAll(".guide-list .row-item")]; rows[rows.length - 1].focus(); });
  await key("Enter"); await sleep(200);
  check((await page.evaluate(() => Zono.state.reminders.length)) === 1, "OK on a later programme sets a reminder");
  check((await page.textContent(".guide-list")).includes("🔔"), "the reminder bell shows in the guide");
  await page.evaluate(() => { Zono.state.reminders[0].start = Date.now() / 1000 + 30; Zono.checkReminders(); });
  check((await page.textContent("#sheet")).includes("begint zo"), "the reminder pops up just before the start");
  await shot("05-reminder");
  await key("ArrowDown"); await key("Enter"); await sleep(150);
  check(!(await page.isVisible("#sheet")), "the reminder can be closed");
  await key("Escape"); await sleep(150);

  // ---- the tv guide tab (grid like Zono for Windows)
  await focusKey("menu-guide"); await key("Enter");
  await page.waitForSelector(".tvg-box.now", { timeout: 5000 });
  await sleep(800);
  check((await focused()).startsWith("Het Journaal"), "TV guide opens on what's on now");
  const chips = await page.$$eval(".tvg-groups .pill", (p) => p.map((x) => x.textContent));
  check(chips[0] === "Alles40" && chips.includes("Belgie10"), "guide: groups with counts " + chips.slice(0, 3));
  check(!!(await page.$(".now-line")) && !!(await page.$(".now-label")), "guide: red line at the current time");
  await key("ArrowRight"); await sleep(150);
  check((await focused()).startsWith("Programma 1"), "→ goes to the next programme");
  const before = await page.evaluate(() => Zono.state.reminders.length);
  await key("Enter"); await sleep(150);
  check((await page.evaluate(() => Zono.state.reminders.length)) === before + 1 && (await focused()).startsWith("🔔"), "OK on a later programme: reminder with a bell");
  await key("ArrowDown"); await sleep(150);
  check((await focused()).startsWith("Programma 1"), "↓ goes to the same time on the next channel");
  await key("ArrowLeft", 2); await sleep(200);
  const offsetBefore = await page.evaluate(() => document.querySelector(".tvg-lane:not(.ruler)").style.transform);
  await key("ArrowLeft", 2); await sleep(200);
  check((await focused()).startsWith("Thuis"), "← goes back in time");
  check((await page.evaluate(() => document.querySelector(".tvg-lane:not(.ruler)").style.transform)) !== offsetBefore, "the grid scrolls along");
  await shot("04b-tvguide");
  await focusKey("td-1"); await key("Enter"); await sleep(600);
  check((await page.$eval(".pill.sel[data-key='td-1']", (p) => p.textContent)).includes("Gisteren"), "guide: yesterday");
  await focusKey("menu-live");

  // ---- channel numbers, previous channel, player menu
  await key("7"); await sleep(1700);
  check(await page.isVisible("#player"), "typing 7 opens channel 7");
  check((await page.textContent("#banner-title")).startsWith("7  "), "banner shows channel number 7");
  await page.waitForFunction(() => /Nu: Het Journaal/.test(document.getElementById("banner-info").textContent), null, { timeout: 4000 }).catch(() => {});
  check((await page.textContent("#banner-info")).includes("Nu: Het Journaal"), "banner shows now and next");
  await key("1"); await key("2"); await sleep(1700);
  check((await page.textContent("#banner-title")).startsWith("12  "), "1-2 switches to channel 12");
  await key("0"); await sleep(300);
  check((await page.textContent("#banner-title")).startsWith("7  "), "0 goes back to the previous channel");
  await key("Enter"); await sleep(100);
  if (!(await page.isVisible("#sheet"))) { await key("Enter"); await sleep(150); }
  check((await page.textContent("#sheet")).includes("Gids en terugkijken"), "OK twice in live TV opens the menu");
  await shot("06-live-menu");
  await key("Escape"); await sleep(100);
  check(!(await page.isVisible("#sheet")) && (await page.isVisible("#player")), "Back closes only the menu");
  await key("Escape"); await sleep(200);

  // ---- films: subtitles from OpenSubtitles
  await focusKey("menu-movies"); await key("Enter"); await sleep(200);
  await key("ArrowRight"); await key("ArrowDown", 2);
  await key("Enter"); await page.waitForSelector(".detail .btn");
  await focusKey("d-play"); await key("Enter"); await sleep(1500);
  check((await video()).t > 0.3, "the film plays");
  await key("ArrowDown"); await sleep(150);
  check((await page.textContent("#sheet")).includes("Ondertitels zoeken"), "▼ opens subtitles and audio");
  await page.evaluate(() => localStorage.setItem("zono.opensubtitles", JSON.stringify("testkey1234567")));
  await page.evaluate(() => [...document.querySelectorAll("#sheet .row-item")].find((r) => /zoeken/.test(r.textContent)).focus());
  await key("Enter"); await page.waitForFunction(() => /Loft.2008.NL/.test(document.getElementById("sheet").textContent), null, { timeout: 4000 }).catch(() => {});
  check(received.subs.length === 1 && received.subs[0].key === "testkey1234567" && /languages=nl/.test(received.subs[0].query), "OpenSubtitles search with key and language");
  await key("Enter"); await sleep(1200);
  check((await page.textContent("#subline")) === "Hallo ondertitel" && await page.isVisible("#subline"), "the subtitles are shown");
  await shot("07-subtitles");
  await page.evaluate(() => { document.getElementById("video").currentTime = 80; });
  await sleep(300);
  await key("Escape"); await sleep(200);
  check(!!(await page.$(".detail .detail-progress")), "back on the film page, with the progress bar");
  await key("Escape"); await sleep(200);

  // ---- hide a group
  await page.evaluate(() => [...document.querySelectorAll(".pill")].find((p) => p.textContent === "Belgie").focus());
  await hold();
  check((await page.textContent("#sheet")).includes("Belgie verbergen?"), "hold OK on a group: hide?");
  await key("Enter"); await sleep(200);
  check(!(await page.$$eval(".pill", (p) => p.map((x) => x.textContent))).includes("Belgie"), "the group is hidden");

  // ---- profiles: a kids profile with a PIN
  await focusKey("menu-settings"); await key("Enter"); await sleep(150);
  await focusKey("prof-add"); await key("Enter"); await sleep(100);
  await page.fill('#sheet [data-key="name"]', "Kids");
  await page.evaluate(() => [...document.querySelectorAll("#sheet .row-item")][0].focus()); await key("Enter"); await sleep(150);
  const kidsId = await page.evaluate(() => JSON.parse(localStorage.getItem("zono.profiles")).find((p) => p.name === "Kids").id);
  await focusKey("prof-" + kidsId); await key("Enter"); await sleep(100);
  await page.evaluate(() => [...document.querySelectorAll("#sheet .row-item")].find((r) => /Kinderprofiel/.test(r.textContent)).focus()); await key("Enter"); await sleep(150);
  await focusKey("prof-" + kidsId); await key("Enter"); await sleep(100);
  await page.evaluate(() => [...document.querySelectorAll("#sheet .row-item")].find((r) => /Pincode instellen/.test(r.textContent)).focus()); await key("Enter"); await sleep(100);
  await key("1"); await key("2"); await key("3"); await key("4"); await sleep(400);
  const kids = await page.evaluate((id) => JSON.parse(localStorage.getItem("zono.profiles")).find((p) => p.id === id), kidsId);
  check(kids.kids === true && /^[0-9a-f]{32}$/.test(kids.pin), "kids profile with a hashed PIN");
  await shot("08-settings");
  await focusKey("menu-me"); await key("Enter"); await sleep(150);
  check((await page.textContent(".who h1")) === "Wie kijkt er?", "who's watching?");
  await shot("09-who");
  await focusKey("who-" + kidsId); await key("Enter"); await sleep(100);
  await key("9"); await key("9"); await key("9"); await key("9"); await sleep(400);
  check(await page.isVisible("#sheet"), "a wrong PIN keeps the profile closed");
  await key("1"); await key("2"); await key("3"); await key("4"); await sleep(400);
  check((await page.evaluate(() => Zono.state.shelves.movies.length)) === 119, "kids profile: the adult film is gone");
  check((await page.evaluate(() => Zono.state.progress.length)) === 0, "every profile has its own 'continue watching'");
  check((await page.textContent(".menu .me")).includes("Kids"), "the menu shows the profile");

  // ---- report a problem, statistics
  await focusKey("menu-settings"); await key("Enter"); await sleep(100);
  await focusKey("report"); await key("Enter"); await sleep(100);
  await page.fill('#sheet [data-key="report-msg"]', "Zender 12 hapert");
  await page.evaluate(() => [...document.querySelectorAll("#sheet .row-item")][0].focus()); await key("Enter"); await sleep(600);
  check(received.report.length === 1 && received.report[0].message === "Zender 12 hapert", "a problem report reaches zono.be");
  check(!received.report[0].log.includes("geheim") && received.report[0].log.includes("/live/***/***/"), "the log has no login details");
  check((await page.textContent("#toast")).includes("#42"), "the report number is shown");
  await page.evaluate(() => Zono.ping()); await sleep(400);
  check(received.ping.length === 1 && /^[0-9a-f]{32}$/.test(received.ping[0].id) && received.ping[0].version === "0.3.0", "anonymous daily ping");

  // ---- restart: first profile again, film progress kept
  await page.evaluate(() => localStorage.setItem("zono.profile", JSON.stringify("main")));
  await page.reload(); await page.waitForSelector(".who");
  await focusKey("who-main"); await key("Enter"); await page.waitForSelector(".shelf");
  check((await page.$$eval(".shelf h2", (h) => h.map((x) => x.textContent))).some((t) => t.startsWith("Verder kijken")), "after a restart: continue watching");
  check(!!(await page.$(".cont")), "after a restart: 'continue with' the last channel");
  await shot("10-restart");
  check(errors.length === 0, "no script errors " + errors.join(" "));
  await browser.close(); api.close(); site.close();
  console.log(failures ? failures + " failed" : "all passed");
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });

// The whole app in a browser at TV size, driven with the remote's keys, against a fake Xtream provider.
//   node tests/e2e.js <test video .webm> <screenshot folder>
const http = require("http");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = process.env.ZONO_ROOT || path.join(__dirname, ".."); // ZONO_ROOT: test an unpacked .ipk
const VIDEO = fs.readFileSync(process.argv[2]);
const OUT = process.argv[3];
fs.mkdirSync(OUT, { recursive: true });

function provider(req, res) {
  const url = new URL(req.url, "http://x");
  res.setHeader("Access-Control-Allow-Origin", "*");
  if (/^\/(live|movie|series)\//.test(url.pathname)) {
    // like real providers: byte ranges, so you can seek
    res.setHeader("Content-Type", "video/webm"); res.setHeader("Accept-Ranges", "bytes");
    const m = /bytes=(\d+)-(\d*)/.exec(req.headers.range || "");
    if (!m) return res.end(VIDEO);
    const start = +m[1], end = m[2] ? +m[2] : VIDEO.length - 1;
    res.statusCode = 206; res.setHeader("Content-Range", `bytes ${start}-${end}/${VIDEO.length}`);
    return res.end(VIDEO.subarray(start, end + 1));
  }
  const q = url.searchParams, good = q.get("username") === "demo" && q.get("password") === "geheim", action = q.get("action");
  const groups = ["4K | Belgie", "Belgie", "Nederland", "Sport"];
  let body;
  if (!good) body = { user_info: { auth: 0 } };
  else if (!action) body = { user_info: { auth: 1, status: "Active" } };
  else if (action.endsWith("_categories")) body = groups.map((n, i) => ({ category_id: String(i), category_name: n }));
  else if (action === "get_live_streams") body = Array.from({ length: 90 }, (_, i) => ({ name: ["VRT 1", "VTM", "NPO 1", "Play Sports 1", "Canvas"][i % 5] + (i % 7 === 0 ? " 4K" : " HD"), stream_id: i + 1, category_id: String(i % 4) }));
  else if (action === "get_vod_streams") body = Array.from({ length: 300 }, (_, i) => ({ name: ["De Zaak Alzheimer", "Loft", "Dune Part Two", "Oppenheimer", "Ad Astra"][i % 5] + " " + i, stream_id: 1000 + i, container_extension: "webm", rating: 5 + (i % 5), added: 1700000000 + i, category_id: String(i % 3) }));
  else if (action === "get_series") body = Array.from({ length: 40 }, (_, i) => ({ name: ["Thuis", "De Mol", "Undercover", "Familie"][i % 4] + " " + i, series_id: 5000 + i, rating: 8.1, last_modified: 1700000000 + i, category_id: "1", plot: "Een Vlaamse reeks." }));
  else if (action === "get_series_info") body = { episodes: { 1: [1, 2, 3].map((n) => ({ id: "9" + n, episode_num: n, title: "S01E0" + n + " - Deel " + n, container_extension: "mkv" })), 2: [{ id: "99", episode_num: 1, title: "Nieuw seizoen" }] } };
  else body = [];
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify(body));
}

function files(req, res) {
  const file = path.join(ROOT, decodeURIComponent(new URL(req.url, "http://x").pathname));
  if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.statusCode = 404; return res.end(); }
  const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".png": "image/png" };
  res.setHeader("Content-Type", types[path.extname(file)] || "application/octet-stream");
  res.end(fs.readFileSync(file));
}

function listen(handler) {
  return new Promise((resolve) => { const s = http.createServer(handler).listen(0, "127.0.0.1", () => resolve(s)); });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failures = 0;
function check(ok, what) { console.log((ok ? "ok   " : "FAIL ") + what); if (!ok) failures++; }

(async () => {
  const api = await listen(provider), site = await listen(files);
  const server = "127.0.0.1:" + api.address().port;
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.addInitScript(() => Object.defineProperty(navigator, "language", { get: () => "nl-BE" }));
  await page.goto("http://127.0.0.1:" + site.address().port + "/index.html");
  const key = async (name, times = 1) => { for (let i = 0; i < times; i++) { await page.keyboard.press(name); await sleep(60); } };
  const focused = () => page.evaluate(() => (document.activeElement.textContent || document.activeElement.getAttribute("data-key") || "").trim());
  const shot = (name) => page.screenshot({ path: path.join(OUT, name + ".png") });

  // login with the remote: type in the fields, wrong password first
  await sleep(300);
  check((await focused()) === "Xtream Codes", "start on the Xtream tab");
  await shot("1-login");
  await key("ArrowDown"); await page.keyboard.type(server);
  await key("ArrowDown"); await page.keyboard.type("demo");
  await key("ArrowDown"); await page.keyboard.type("fout");
  await key("ArrowDown"); await key("Enter");
  await page.waitForSelector(".error");
  check((await page.textContent(".error")).includes("klopt niet"), "wrong password is explained in Dutch");
  await page.click('[data-key="in-password"]'); await page.fill('[data-key="in-password"]', "geheim");
  await page.focus('[data-key="connect"]'); await key("Enter");
  await page.waitForSelector(".menu", { timeout: 10000 });
  await page.waitForSelector(".shelf");
  check((await page.$$eval(".shelf h2", (h) => h.map((x) => x.textContent))).join("|") === "4K-zenders|Nieuwe films|Best beoordeeld|Nieuwe series", "Discover shelves");
  await shot("2-discover");

  // Live TV: 4K first, zap, favourite
  await page.evaluate(() => document.querySelector('[data-key="menu-discover"]').focus());
  await key("ArrowDown", 2); await key("Enter");
  await sleep(200);
  check((await page.$eval(".channels h2", (h) => h.firstChild.textContent)) === "4K | Belgie", "4K group first");
  await key("ArrowRight"); await key("ArrowRight");
  const first = await focused();
  check(first.includes("4K") || first.includes("HD"), "a channel has focus: " + first);
  await shot("3-live");
  await page.keyboard.down("Enter"); await sleep(900); await page.keyboard.up("Enter");
  await sleep(200);
  check((await page.evaluate(() => Zono.state.favorites.length)) === 1, "hold OK makes a favourite");
  await key("Enter");
  await sleep(150);
  check(await page.isVisible("#player"), "player opens");
  // desktop Chromium has no HLS (the TV has): the player must try the .ts link next
  check((await page.evaluate(() => document.getElementById("video").src)).endsWith(".m3u8"), "live channels start as HLS");
  await page.waitForFunction(() => document.getElementById("video").src.endsWith(".ts"), null, { timeout: 8000 }).then(() => check(true, "HLS fails -> tries .ts"), () => check(false, "HLS fails -> tries .ts"));
  const before = await page.textContent("#banner-title");
  await key("ArrowDown"); await sleep(800);
  check((await page.textContent("#banner-title")) !== before, "▼ zaps to the next channel");
  await shot("4-player");
  await key("Escape");
  check(!(await page.isVisible("#player")), "Back closes the player");

  // Movies: grid, play, resume list
  await page.evaluate(() => document.querySelector('[data-key="menu-movies"]').focus()); await key("Enter");
  await sleep(200);
  await key("ArrowRight"); await key("ArrowDown"); await key("ArrowRight", 2); await key("ArrowDown", 8);
  const movie = await focused();
  check(/\d/.test(movie), "moving in the movie grid: " + movie);
  check((await page.$$(".grid .card")).length > 50, "more posters are drawn when you scroll");
  await shot("5-movies");
  await key("Enter"); await sleep(1500);
  check((await page.evaluate(() => document.getElementById("video").currentTime)) > 0.3, "movie plays");
  await page.evaluate(() => { const v = document.getElementById("video"); v.currentTime = 80; });
  await sleep(400);
  await key("ArrowLeft"); await sleep(300);
  check(Math.abs((await page.evaluate(() => document.getElementById("video").currentTime)) - 70) < 1.5, "◀ seeks back 10 s");
  await key("Enter"); await sleep(200);
  check(await page.evaluate(() => document.getElementById("video").paused), "OK pauses");
  await shot("6-paused");
  await key("Escape");

  // Series: seasons and episodes
  await page.evaluate(() => document.querySelector('[data-key="menu-series"]').focus()); await key("Enter");
  await sleep(200); await key("ArrowRight"); await key("ArrowDown"); await key("Enter");
  await page.waitForSelector(".eps .row-item");
  check((await page.$$eval(".eps .pill", (p) => p.map((x) => x.textContent))).join() === "Seizoen 1,Seizoen 2", "seasons");
  check((await focused()) === "Seizoen 1", "focus on the first season");
  await key("ArrowDown"); check((await focused()) === "1. Deel 1", "clean episode titles");
  await shot("7-series");
  await key("Escape"); await sleep(100);
  check(!(await page.$(".eps")), "Back leaves the series");

  // Search and settings
  await page.evaluate(() => document.querySelector('[data-key="menu-search"]').focus()); await key("Enter");
  await page.focus('[data-key="search"]'); await page.keyboard.type("oppen"); await sleep(500);
  check((await page.$$(".grid .card")).length === 60, "search finds the films");
  await page.evaluate(() => document.querySelector('[data-key="menu-settings"]').focus()); await key("Enter");
  await page.evaluate(() => document.querySelector('[data-key="lang-fr"]').focus()); await key("Enter");
  check((await page.textContent('[data-key="menu-movies"]')).trim() === "Films" && (await page.textContent('[data-key="menu-settings"]')).trim() === "Paramètres", "switch to French");
  await shot("8-settings-fr");
  await page.evaluate(() => document.querySelector('[data-key="lang-nl"]').focus()); await key("Enter");

  // restart: the library comes from the cache
  await page.reload(); await page.waitForSelector(".shelf", { timeout: 5000 });
  check((await page.$$eval(".shelf h2", (h) => h[0].textContent)) === "Verder kijken", "after a restart: continue watching + cached library");
  check(errors.length === 0, "no script errors " + errors.join(" "));
  await browser.close(); api.close(); site.close();
  console.log(failures ? failures + " failed" : "all passed");
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });

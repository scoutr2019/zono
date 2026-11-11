// How smooth is Zono with a big provider (29,000 channels, 60,000 films, 12,000 series) on a slow CPU (like a TV)?
//   node tests/stress.js            (ZONO_ROOT=<unpacked ipk> for the packaged app)
// Reports the longest freezes (main thread busy) for start, refresh, browsing, the TV guide and search.
const http = require("http");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");
const ROOT = process.env.ZONO_ROOT || path.join(__dirname, "..");
const SLOW = +(process.env.SLOW || 6);
const NOW = Math.floor(Date.now() / 1000);
const b64 = (s) => Buffer.from(s).toString("base64");
const groups = Array.from({ length: 300 }, (_, i) => ({ category_id: String(i), category_name: ["BE", "NL", "UK", "FR", "DE", "US"][i % 6] + " | Groep " + i }));
const json = {
  live: JSON.stringify(Array.from({ length: 29000 }, (_, i) => ({ num: i + 1, name: (i % 9 === 0 ? "4K | " : "BE: ") + "Zender " + i + " HD", stream_id: i + 1, stream_icon: "", epg_channel_id: "c" + i, category_id: String(i % 300), tv_archive: i % 4 === 0 ? 1 : 0, tv_archive_duration: 7 }))),
  vod: JSON.stringify(Array.from({ length: 60000 }, (_, i) => ({ name: "[ALL] NL: Film nummer " + i + " (20" + (10 + (i % 15)) + ")", stream_id: 100000 + i, stream_icon: "", rating: (i % 10) + "", added: String(1700000000 + i), category_id: String(i % 300), container_extension: "mkv", plot: "" }))),
  series: JSON.stringify(Array.from({ length: 12000 }, (_, i) => ({ name: "BE - Serie " + i, series_id: 300000 + i, cover: "", rating: "7", last_modified: String(1700000000 + i), category_id: String(i % 300) }))),
};
function epg(full) {
  const rows = [];
  for (let i = full ? -48 : 0; i < (full ? 48 : 8); i++) {
    const start = NOW - 1800 + i * 3600;
    rows.push({ title: b64("Programma " + i), description: b64("Beschrijving van het programma, een paar zinnen lang. ".repeat(3)), start: "2026-01-01 00:00:00", start_timestamp: String(start), stop_timestamp: String(start + 3600), has_archive: i < 0 ? 1 : 0 });
  }
  return JSON.stringify({ epg_listings: rows });
}
const server = http.createServer((req, res) => {
  const q = new URL(req.url, "http://x").searchParams, action = q.get("action");
  res.setHeader("Access-Control-Allow-Origin", "*");
  let body = "[]";
  if (!action) body = JSON.stringify({ user_info: { auth: 1 } });
  else if (action.endsWith("_categories")) body = JSON.stringify(groups);
  else if (action === "get_live_streams") body = json.live;
  else if (action === "get_vod_streams") body = json.vod;
  else if (action === "get_series") body = json.series;
  else if (action === "get_short_epg") body = epg(false);
  else if (action === "get_simple_data_table") body = epg(true);
  else if (action === "get_vod_info") body = JSON.stringify({ info: { plot: "x", genre: "Drama" } });
  res.end(body);
}).listen(8801);
const files = http.createServer((req, res) => {
  const file = path.join(ROOT, decodeURIComponent(new URL(req.url, "http://x").pathname));
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.statusCode = 404; return res.end(); }
  res.setHeader("Content-Type", { ".html": "text/html", ".js": "text/javascript", ".css": "text/css" }[path.extname(file)] || "image/png");
  res.end(fs.readFileSync(file));
}).listen(8802);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  const cdp = await page.context().newCDPSession(page);
  await page.addInitScript(() => {
    window.__long = [];
    new PerformanceObserver((l) => l.getEntries().forEach((e) => window.__long.push(e.duration))).observe({ entryTypes: ["longtask"] });
    localStorage.setItem("zono.source", JSON.stringify({ type: "xtream", server: "http://127.0.0.1:8801", user: "u", password: "p" }));
    window.ZONO_PAIR_API = "http://127.0.0.1:1/x"; window.ZONO_API = "http://127.0.0.1:1";
  });
  const errors = []; page.on("pageerror", (e) => errors.push(String(e)));
  async function phase(name, run) {
    await page.evaluate(() => (window.__long = []));
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: SLOW });
    const t = Date.now();
    await run();
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 1 });
    const long = await page.evaluate(() => window.__long);
    const worst = Math.round(Math.max(0, ...long)), total = Math.round(long.reduce((a, b) => a + b, 0));
    console.log(`${name.padEnd(34)} took ${String(Date.now() - t).padStart(6)} ms   longest freeze ${String(worst).padStart(6)} ms   frozen in total ${String(total).padStart(6)} ms`);
  }
  const key = async (k, n = 1) => { for (let i = 0; i < n; i++) { await page.keyboard.press(k); await sleep(120); } };
  await phase("first start (load everything)", async () => {
    await page.goto("http://127.0.0.1:8802/index.html");
    await page.waitForSelector(".shelf", { timeout: 300000 });
    await sleep(1500);
  });
  await phase("browse discover (10 keys)", async () => { await key("ArrowDown", 5); await key("ArrowRight", 5); });
  await phase("second start (from cache + refresh)", async () => {
    await page.reload(); await page.waitForSelector(".shelf", { timeout: 300000 }); await sleep(8000);
  });
  await phase("live tv: open + 20 channels down", async () => {
    await page.evaluate(() => document.querySelector('[data-key="menu-live"]').focus()); await key("Enter"); await sleep(500);
    await key("ArrowRight"); await key("ArrowDown", 20); await sleep(1000);
  });
  await phase("tv guide: open + browse", async () => {
    await page.evaluate(() => document.querySelector('[data-key="menu-guide"]').focus()); await key("Enter"); await sleep(4000);
    await key("ArrowDown", 10); await key("ArrowRight", 5); await sleep(2000);
  });
  await phase("films: open grid + 10 rows down", async () => {
    await page.evaluate(() => document.querySelector('[data-key="menu-movies"]').focus()); await key("Enter"); await sleep(500);
    await key("ArrowRight"); await key("ArrowDown", 10);
  });
  await phase("search: type 'film 12'", async () => {
    await page.evaluate(() => document.querySelector('[data-key="menu-search"]').focus()); await key("Enter"); await sleep(300);
    await page.focus('[data-key="search"]'); await page.keyboard.type("film 12", { delay: 150 }); await sleep(2500);
  });
  console.log(errors.length ? "errors: " + errors.join(" | ") : "no script errors");
  await browser.close(); server.close(); files.close();
})().catch((e) => { console.error(e); process.exit(1); });

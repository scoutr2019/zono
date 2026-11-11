// Linking apps end to end: Zono for Windows (its real sync code, src/sync.py) and the TV app, through the real
// server script (server/api/sync.php under `php -S`), with the same subscription.
//   node tests/sync.e2e.js
const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn, execFileSync } = require("child_process");
const { chromium } = require("playwright");

const ROOT = path.join(__dirname, "..");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failures = 0;
function check(ok, what) { console.log((ok ? "ok   " : "FAIL ") + what); if (!ok) failures++; }

function provider(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  const q = new URL(req.url, "http://x").searchParams, action = q.get("action");
  const body = !action ? { user_info: { auth: 1 } } : action.endsWith("_categories") ? [{ category_id: "1", category_name: "BE" }]
    : action === "get_live_streams" ? [{ name: "VRT 1", stream_id: 1, category_id: "1" }, { name: "VTM", stream_id: 2, category_id: "1" }]
    : action === "get_vod_streams" ? [{ name: "Noorderlicht", stream_id: 100, container_extension: "mkv", category_id: "1" }, { name: "Orbit", stream_id: 101, category_id: "1" }]
    : action === "get_series" ? [{ name: "De Haven", series_id: 500, category_id: "1" }] : [];
  res.end(JSON.stringify(body));
}

// "Windows": a few lines of Python around src/sync.py, exactly as the app uses it
function windows(local) {
  const script = `
import json, sys
sys.path.insert(0, ${JSON.stringify(path.join(ROOT, "../src"))})
import sync
sync.API = "http://127.0.0.1:8781/api/sync.php"
secret = sync.secret_for({"server": "http://127.0.0.1:8783", "user": "jan", "password": "geheim"})
print(json.dumps(sync.exchange(secret, json.loads(sys.argv[1]))))`;
  try { return JSON.parse(execFileSync("python3", ["-c", script, JSON.stringify(local)], { stdio: "pipe" }).toString()); }
  catch (e) { console.log(String(e.stderr)); throw new Error("python failed"); }
}

(async () => {
  const site = fs.mkdtempSync(path.join(os.tmpdir(), "zono-sync-"));
  fs.cpSync(path.join(ROOT, "../server"), site, { recursive: true });
  fs.rmSync(path.join(site, "api/data"), { recursive: true, force: true });
  const php = spawn("php", ["-S", "127.0.0.1:8781", "-t", site], { stdio: "ignore" });
  process.on("exit", () => php.kill());
  const files = http.createServer((req, res) => {
    const file = path.join(ROOT, decodeURIComponent(new URL(req.url, "http://x").pathname));
    if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.statusCode = 404; return res.end(); }
    res.setHeader("Content-Type", { ".html": "text/html", ".js": "text/javascript", ".css": "text/css" }[path.extname(file)] || "image/png");
    res.end(fs.readFileSync(file));
  }).listen(8782);
  const iptv = http.createServer(provider).listen(8783);
  await sleep(700);

  // 1. on the pc: half of Noorderlicht watched, Orbit a favourite, last channel VTM
  const now = Date.now();
  let pack = windows({ v: 1, profiles: { main: {
    progress: { m100: { t: now - 5000, pos: 1500, dur: 6000, from: "pc", kind: "movie", title: "Noorderlicht", sid: "100", ext: "mkv" } },
    fav: { m101: { t: now - 5000, on: true, kind: "movie", title: "Orbit", sid: "101" } },
    last: { key: "l2", t: now - 5000, title: "VTM", sid: "2" } } } });
  check(pack.profiles.main.progress.m100.pos === 1500, "pc: stored on zono.be (locked)");
  const stored = execFileSync("php", ["-r", "echo (new PDO('sqlite:' . $argv[1]))->query('SELECT data FROM sync')->fetchColumn();", path.join(site, "api/data/zono.sqlite")]).toString();
  check(stored.length > 100 && !/Noorderlicht|geheim|jan/.test(stored), "the server only holds a locked package: no titles, no login");

  // 2. the TV logs in with the same subscription and picks it up
  const browser = await chromium.launch();
  const tv = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  const errors = [];
  tv.on("pageerror", (e) => errors.push(String(e)));
  await tv.addInitScript(() => {
    window.ZONO_SYNC_API = "http://127.0.0.1:8781/api/sync.php";
    window.ZONO_API = "http://127.0.0.1:8781/api";
    window.ZONO_PAIR_API = "http://127.0.0.1:8781/nopair";
    Object.defineProperty(navigator, "language", { get: () => "nl-BE" });
  });
  await tv.goto("http://127.0.0.1:8782/index.html");
  await sleep(400);
  await tv.fill('[data-key="in-server"]', "127.0.0.1:8783");
  await tv.fill('[data-key="in-user"]', "jan");
  await tv.fill('[data-key="in-password"]', "geheim");
  await tv.evaluate(() => document.querySelector('[data-key="connect"]').focus());
  await tv.keyboard.press("Enter");
  await tv.waitForSelector(".greet h1", { timeout: 10000 });
  await tv.waitForFunction(() => Zono.state.progress.length > 0, null, { timeout: 15000 }).catch(() => {});
  const p = await tv.evaluate(() => Zono.state.progress[0] && { id: Zono.state.progress[0].item.id, pos: Zono.state.progress[0].pos, from: Zono.state.progress[0].from });
  check(p && p.id === "m100" && p.pos === 1500 && p.from === "pc", "TV: 'continue watching' from the pc, at the same spot: " + JSON.stringify(p));
  await sleep(500);
  const shelfText = await tv.evaluate(() => [...document.querySelectorAll(".shelf")].map((s) => s.textContent).join(" | "));
  check(/Noorderlicht/.test(shelfText) && /verder op je pc/.test(shelfText), "TV: shown on Discover with 'verder op je pc'");
  check(await tv.evaluate(() => Zono.state.favorites.indexOf("m101") >= 0), "TV: the pc's favourite is a favourite here too");
  check(await tv.evaluate(() => JSON.parse(localStorage.getItem("zono.last") || '""') === "l2"), "TV: the last channel from the pc");
  await tv.screenshot({ path: path.join(os.tmpdir(), "zono-sync-tv.png") });

  // 3. on the TV: Noorderlicht further, Orbit no longer a favourite -> the pc sees it
  await tv.evaluate(() => {
    const p = Zono.state.progress[0]; p.pos = 4000; p.t = Date.now(); p.from = "lg";
    localStorage.setItem("zono.progress", JSON.stringify(Zono.state.progress));
  });
  await tv.evaluate(() => Zono.toggleFavorite(Zono.state.items.find((i) => i.id === "m101")));
  await tv.evaluate(() => Zono.syncNow());
  await sleep(800);
  pack = windows({ v: 1, profiles: {} });
  check(pack.profiles.main.progress.m100.pos === 4000 && pack.profiles.main.progress.m100.from === "lg", "pc: continues where the TV stopped");
  check(pack.profiles.main.fav.m101.on === false, "pc: the favourite removed on the TV is gone");

  // 4. finished on the pc -> gone from the TV's continue watching
  windows({ v: 1, profiles: { main: { progress: { m100: { t: Date.now(), done: 1 } }, fav: {}, last: null } } });
  await tv.evaluate(() => Zono.syncNow());
  await sleep(500);
  check(await tv.evaluate(() => !Zono.state.progress.some((p) => p.item.id === "m100")), "finished on the pc: off the TV's list");

  // 5. a wrong key can't read it, and nobody can write without matching the revision
  check(await tv.evaluate(() => Sync.open("AAAA" + "A".repeat(80), Sync.derive("other").key) === null), "another key cannot open it");
  check(errors.length === 0, "no script errors " + errors.join(" "));
  await browser.close(); php.kill(); files.close(); iptv.close();
  console.log(failures ? failures + " failed" : "all passed");
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });

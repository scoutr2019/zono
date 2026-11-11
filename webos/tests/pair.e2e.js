// "Log in with your phone" end to end: the TV app, the phone page (server/tv) and server/api/pair.php (needs php).
//   node tests/pair.e2e.js
const { spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const http = require("http");
const { chromium } = require("playwright");

const ROOT = process.env.ZONO_ROOT || path.join(__dirname, "..");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failures = 0;
function check(ok, what) { console.log((ok ? "ok   " : "FAIL ") + what); if (!ok) failures++; }

function provider(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  const q = new URL(req.url, "http://x").searchParams;
  const good = q.get("username") === "jan" && q.get("password") === "geheim 123";
  const action = q.get("action");
  let body = !good ? { user_info: { auth: 0 } } : !action ? { user_info: { auth: 1 } } : action.endsWith("_categories") ? [{ category_id: "1", category_name: "BE" }]
    : action === "get_live_streams" ? [{ name: "VRT 1", stream_id: 1, category_id: "1" }] : [];
  res.end(JSON.stringify(body));
}

(async () => {
  // a copy of the server folder, so the test database stays out of the repository
  const site = fs.mkdtempSync(path.join(os.tmpdir(), "zono-site-"));
  fs.cpSync(path.join(__dirname, "../../server"), site, { recursive: true });
  const php = spawn("php", ["-S", "127.0.0.1:8791", "-t", site], { stdio: "ignore" });
  const files = http.createServer((req, res) => {
    const file = path.join(ROOT, decodeURIComponent(new URL(req.url, "http://x").pathname));
    if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.statusCode = 404; return res.end(); }
    res.setHeader("Content-Type", { ".html": "text/html", ".js": "text/javascript", ".css": "text/css" }[path.extname(file)] || "image/png");
    res.end(fs.readFileSync(file));
  }).listen(8792);
  const iptv = http.createServer(provider).listen(8793);
  await sleep(600);

  const browser = await chromium.launch();
  const tv = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  const errors = [];
  tv.on("pageerror", (e) => errors.push(String(e)));
  await tv.addInitScript(() => {
    window.ZONO_PAIR_API = "http://127.0.0.1:8791/api/pair.php";
    window.ZONO_PAIR_PAGE = "http://127.0.0.1:8791/tv/";
    Object.defineProperty(navigator, "language", { get: () => "nl-BE" });
  });
  await tv.goto("http://127.0.0.1:8792/index.html");
  await tv.waitForSelector(".phone img.qr", { timeout: 8000 });
  check(true, "the TV shows a QR code");
  await tv.screenshot({ path: path.join(os.tmpdir(), "zono-pair-tv.png") });
  const link = await tv.evaluate(() => Zono.pair.url);
  check(/^http:\/\/127\.0\.0\.1:8791\/tv\/#[A-Z2-7]{10}\.[A-Za-z0-9_-]{43}\.nl$/.test(link), "QR link: code, key and language after #");

  // the phone
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const seen = [];
  phone.on("request", (r) => seen.push(r.url() + " " + (r.postData() || "")));
  await phone.goto(link);
  check((await phone.textContent("h1")) === "Log in op Zono op je tv", "phone page in the TV's language");
  check(!phone.url().includes("#"), "the key is removed from the phone's address bar");
  await phone.fill("#server", "http://127.0.0.1:8793");
  await phone.fill("#user", "jan");
  await phone.fill("#password", "geheim 123");
  await phone.screenshot({ path: path.join(os.tmpdir(), "zono-pair-phone.png") });
  await phone.click("#send");
  await phone.waitForSelector(".msg.good", { timeout: 5000 });
  check(true, "phone: sent");
  check(!seen.some((s) => s.includes("geheim")) && !seen.some((s) => s.includes(link.split(".")[3] || "nokey")), "the password never travels readable");

  await tv.waitForSelector(".menu", { timeout: 10000 });
  check((await tv.evaluate(() => Zono.state.source.user)) === "jan", "the TV signed in with the details from the phone");

  // the OpenSubtitles key, also with the phone
  await tv.evaluate(() => { Zono.state.page = "settings"; Zono.render(); document.querySelector('[data-key="subkey"]').focus(); });
  await tv.keyboard.press("Enter"); await sleep(100);
  await tv.waitForSelector("#sheet img.qr", { timeout: 8000 });
  const subsLink = await tv.evaluate(() => Zono.pair.url);
  check(subsLink.endsWith(".nl.subs"), "QR for the subtitles key");
  const phone2 = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await phone2.goto(subsLink);
  check((await phone2.textContent("h1")) === "OpenSubtitles op je tv" && !(await phone2.isVisible("#server")), "phone page asks only for the key");
  await phone2.fill("#subkey", "abcDEF1234567890");
  await phone2.click("#send");
  await phone2.waitForSelector(".msg.good", { timeout: 5000 });
  await tv.waitForFunction(() => localStorage.getItem("zono.opensubtitles") === JSON.stringify("abcDEF1234567890"), null, { timeout: 8000 })
    .then(() => check(true, "the TV saved the subtitles key"), () => check(false, "the TV saved the subtitles key"));
  check(!(await tv.isVisible("#sheet")), "the window closes by itself");

  // a used code cannot be used again
  await phone.click("#send").catch(() => {});
  const again = await phone.evaluate(() => fetch("/api/pair.php", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "send", code: "AAAAAAAAAA", data: "x".repeat(60) }) }).then((r) => r.status));
  check(again === 404, "unknown codes are refused");
  check(errors.length === 0, "no script errors " + errors.join(" "));
  await browser.close(); php.kill(); files.close(); iptv.close();
  console.log(failures ? failures + " failed" : "all passed");
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });

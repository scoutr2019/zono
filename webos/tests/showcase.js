// Pictures of the TV app for zono.be and GitHub: the real app at TV size, against a made-up provider
// with invented channels, films and series (artwork drawn here, no real posters or logos).
//   node tests/showcase.js <output folder> [nl|fr|en|de]
// The "TV picture" is a drawn landscape that slowly moves (made here with ffmpeg).
const http = require("http");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = path.join(__dirname, "..");
const { execFileSync } = require("child_process");
const OUT = process.argv[2];
const LANG = process.argv[3] || "nl";
let VIDEO;
fs.mkdirSync(OUT, { recursive: true });
const b64 = (s) => Buffer.from(s, "utf8").toString("base64");
const NOW = Math.floor(Date.now() / 1000);

// ---- made-up library
const CHANNELS = [
  ["Nieuws 24", "België", ["Ochtendnieuws", "Het Weer", "Debat Vandaag", "Middagnieuws", "Reportage", "Avondnieuws", "Laat Nieuws"]],
  ["Sport 1", "Sport", ["Voetbal Live", "Studio Sport", "Wielerflash", "Tennis Open", "Doelpunten", "Sportcafé", "Voetbal Live"]],
  ["Cinema Max", "Films", ["Noorderlicht", "Stad van Glas", "Zoutwater", "De Vuurtoren", "Orbit", "Koud Spoor", "Nachtfilm"]],
  ["Natuur & Reizen", "Documentaire", ["Wilde Kusten", "Ijsland van Boven", "De Grote Trek", "Bergen", "Oceaan", "Savanne", "Regenwoud"]],
  ["Kids Club", "Kids", ["Tekenfilms", "Raket Rik", "Bosvrienden", "Knutseluur", "Raket Rik", "Slaapliedjes", "Tekenfilms"]],
  ["Muziek Hits", "Muziek", ["Top 40", "Ochtendhits", "Live Sessie", "Classics", "Dance Uur", "Unplugged", "Nachtmix"]],
  ["Koken & Wonen", "België", ["Snel Koken", "Ons Huis", "Tuinieren", "Bakwedstrijd", "Klussen", "Streekkeuken", "Het Diner"]],
  ["Docu Plus", "Documentaire", ["Ruimtevaart", "Oude Steden", "De Tweede Wereldoorlog", "Wetenschap", "Uitvinders", "Het Brein", "Diepzee"]],
  ["Lach TV", "België", ["Sketches", "Stand-up", "Quiz Avond", "De Sitcom", "Sketches", "Panelshow", "Stand-up"]],
  ["Sport 2", "Sport", ["Basketbal", "Formule Snel", "Darts", "Hockey", "Golf", "Zwemmen", "Basketbal"]],
  ["Wereld Nieuws", "Nederland", ["World Report", "Economie", "Interview", "Het Weer", "Wereldnieuws", "Achtergrond", "Nachtjournaal"]],
  ["Retro Films", "Films", ["De Jaren 80", "Klassieker", "Western", "Zwart-Wit", "Musical", "Avontuur", "Nachtfilm"]],
];
const FILMS = [
  ["Noorderlicht", "Drama, Avontuur", 8.4, "Een poolonderzoeker raakt verdwaald in de winternacht en vindt de weg terug dankzij het noorderlicht."],
  ["Stad van Glas", "Thriller", 7.9, "In een stad vol spiegels ontdekt een rechercheur dat niemand is wie hij lijkt."],
  ["Zoutwater", "Drama", 7.6, "Twee zussen erven een vissersboot en moeten kiezen tussen de zee en de stad."],
  ["Orbit", "Sciencefiction", 8.1, "Een kleine bemanning moet een kapot ruimtestation repareren voor het de aarde nadert."],
  ["De Vuurtoren", "Mysterie", 7.3, "Een nieuwe vuurtorenwachter hoort elke nacht een stem over de radio."],
  ["Koud Spoor", "Misdaad", 7.8, "Een oude zaak komt terug als een postkaart van twintig jaar geleden aankomt."],
  ["Middernacht in Gent", "Romantiek", 7.1, "Twee vreemden missen de laatste trein en ontdekken de stad bij nacht."],
  ["Wolkenkrabber", "Actie", 7.4, "Een glazenwasser zit vast op de vijftigste verdieping tijdens een storm."],
  ["Het Stille Dorp", "Drama", 7.7, "Een dorp waar niemand meer praat, tot een kind een vraag stelt."],
  ["Neon Nachten", "Thriller", 7.2, "Een taxichauffeur ziet in één nacht drie keer dezelfde klant."],
  ["De Erfenis", "Komedie", 6.9, "Vijf neven en nichten, één testament en een huis vol geheimen."],
  ["Woestijnwind", "Avontuur", 7.5, "Een expeditie door de woestijn op zoek naar een verloren oase."],
  ["Diepblauw", "Documentaire", 8.2, "De onbekende wereld onder de golven, in prachtige beelden."],
  ["Laatste Ronde", "Sport, Drama", 7.0, "Een bokser op leeftijd krijgt nog één kans."],
  ["Papieren Vogels", "Familie", 7.3, "Een meisje vouwt duizend vogels om haar opa beter te maken."],
  ["Schaduwspel", "Mysterie", 7.6, "Een poppenspeler ontdekt dat zijn schaduwen een eigen wil hebben."],
];
const SERIES = ["De Haven", "Kustwacht", "Familie Peeters", "Het Kantoor", "Spoorloos", "Bloed & Bier", "De Brug", "Achter de Dijk"];

// ---- drawn artwork: a landscape in the colours of the title
function rand(seed) { let s = 0; for (const c of seed) s = (s * 31 + c.charCodeAt(0)) >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }
const PALETTES = [["#0f1b4d", "#6a3bd6", "#ff8f6b"], ["#081c2e", "#11698e", "#5ad1c8"], ["#2a0f3d", "#c2185b", "#ffb74d"], ["#0b1d14", "#2e7d5b", "#c5e1a5"],
  ["#1a1033", "#3949ab", "#90caf9"], ["#2b1608", "#b4532a", "#ffd180"], ["#0d0d1f", "#5e35b1", "#f48fb1"], ["#06262e", "#00838f", "#ffe082"]];
function art(name, w, h, title) {
  const r = rand(name), p = PALETTES[Math.floor(r() * PALETTES.length)];
  let svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><defs>
    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${p[0]}"/><stop offset=".65" stop-color="${p[1]}"/><stop offset="1" stop-color="${p[2]}"/></linearGradient>
    <radialGradient id="sun"><stop offset="0" stop-color="#fff8e1"/><stop offset=".5" stop-color="${p[2]}"/><stop offset="1" stop-color="${p[2]}" stop-opacity="0"/></radialGradient>
    <linearGradient id="fade" x1="0" y1="0" x2="0" y2="1"><stop offset=".55" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".75"/></linearGradient></defs>
    <rect width="${w}" height="${h}" fill="url(#sky)"/>`;
  for (let i = 0; i < 40; i++) svg += `<circle cx="${r() * w}" cy="${r() * h * 0.45}" r="${r() * 1.6 + 0.4}" fill="#fff" opacity="${r() * 0.7}"/>`;
  const sx = w * (0.25 + r() * 0.5), sy = h * (0.42 + r() * 0.12), sr = Math.min(w, h) * (0.12 + r() * 0.08);
  svg += `<circle cx="${sx}" cy="${sy}" r="${sr * 2.2}" fill="url(#sun)" opacity=".55"/><circle cx="${sx}" cy="${sy}" r="${sr * 0.55}" fill="#fff3e0" opacity=".9"/>`;
  for (let layer = 0; layer < 4; layer++) {
    const base = h * (0.55 + layer * 0.11), amp = h * (0.16 - layer * 0.03);
    let d = `M0 ${h} L0 ${base}`;
    const steps = 6 + layer * 2;
    for (let i = 0; i <= steps; i++) d += ` L${(i / steps) * w} ${base - r() * amp}`;
    d += ` L${w} ${h} Z`;
    svg += `<path d="${d}" fill="${p[0]}" opacity="${0.45 + layer * 0.18}"/>`;
  }
  svg += `<rect width="${w}" height="${h}" fill="url(#fade)"/>`;
  if (title) {
    const words = title.toUpperCase().split(" "), lines = [];
    words.forEach((word) => { const last = lines[lines.length - 1]; if (last && (last + " " + word).length <= 11) lines[lines.length - 1] = last + " " + word; else lines.push(word); });
    const longest = Math.max.apply(null, lines.map((l) => l.length));
    const size = Math.min(w * 0.13, (w * 0.86) / (longest * 0.68));
    lines.forEach((line, i) => {
      svg += `<text x="${w / 2}" y="${h * 0.9 - (lines.length - 1 - i) * size * 1.1}" text-anchor="middle" font-family="Georgia, serif" font-weight="700" font-size="${size.toFixed(1)}" fill="#fff">${line.replace(/&/g, "&amp;")}</text>`;
    });
  }
  return svg + "</svg>";
}

function sendVideo(req, res) {
  res.setHeader("Content-Type", "video/webm"); res.setHeader("Accept-Ranges", "bytes");
  const m = /bytes=(\d+)-(\d*)/.exec(req.headers.range || "");
  if (!m) return res.end(VIDEO);
  const start = +m[1], end = m[2] ? +m[2] : VIDEO.length - 1;
  res.statusCode = 206; res.setHeader("Content-Range", `bytes ${start}-${end}/${VIDEO.length}`);
  res.end(VIDEO.subarray(start, end + 1));
}
function listings(sid, full) {
  const ch = CHANNELS[(sid - 1) % CHANNELS.length], rows = [];
  for (let i = full ? -3 : 0; i < 6; i++) {
    const start = NOW - 1500 + i * 3600, d = new Date(start * 1000);
    const label = d.toISOString().slice(0, 10) + " " + d.toTimeString().slice(0, 8);
    rows.push({ title: b64(ch[2][(i + 3 + sid) % ch[2].length]), description: b64("Vandaag op " + ch[0] + "."),
      start: label, start_timestamp: String(start), stop_timestamp: String(start + 3600), has_archive: i < 0 ? 1 : 0 });
  }
  return { epg_listings: rows };
}
function provider(req, res) {
  const url = new URL(req.url, "http://x"), host = "http://" + req.headers.host;
  res.setHeader("Access-Control-Allow-Origin", "*");
  if (/^\/(live|movie|series|timeshift)\//.test(url.pathname)) return sendVideo(req, res);
  const pic = /^\/art\/(poster|wide)\/(.+)\.svg$/.exec(url.pathname);
  if (pic) {
    const name = decodeURIComponent(pic[2]);
    res.setHeader("Content-Type", "image/svg+xml");
    return res.end(pic[1] === "poster" ? art(name, 342, 513, name) : art(name + " wide", 1280, 720));
  }
  if (url.pathname.startsWith("/api/")) return res.end('{"ok":true}');
  const action = url.searchParams.get("action"), groups = ["België", "Nederland", "Sport", "Films", "Documentaire", "Kids", "Muziek"];
  let out;
  if (!action) out = { user_info: { auth: 1, status: "Active" } };
  else if (action === "get_live_categories") out = groups.map((n, i) => ({ category_id: String(i), category_name: n }));
  else if (action === "get_vod_categories") out = [{ category_id: "0", category_name: "Nieuw" }, { category_id: "1", category_name: "Drama" }, { category_id: "2", category_name: "Spanning" }];
  else if (action === "get_series_categories") out = [{ category_id: "0", category_name: "Vlaams" }, { category_id: "1", category_name: "Misdaad" }];
  else if (action === "get_live_streams") out = CHANNELS.map((c, i) => ({ num: i + 1, name: c[0] + (i === 2 || i === 3 ? " 4K" : " HD"), stream_id: i + 1, category_id: String(groups.indexOf(c[1])), tv_archive: 1, tv_archive_duration: 7 }));
  else if (action === "get_vod_streams") out = FILMS.map((f, i) => ({ name: f[0], stream_id: 1000 + i, container_extension: "webm", rating: f[2], added: NOW - i * 86400, category_id: String(i % 3), stream_icon: host + "/art/poster/" + encodeURIComponent(f[0]) + ".svg" }));
  else if (action === "get_series") out = SERIES.map((s, i) => ({ name: s, series_id: 5000 + i, rating: 7.5 + (i % 4) * 0.3, last_modified: NOW - i * 86400, category_id: String(i % 2), plot: "Een nieuwe Vlaamse reeks.", cover: host + "/art/poster/" + encodeURIComponent(s) + ".svg" }));
  else if (action === "get_series_info") out = { info: { plot: "Een nieuwe Vlaamse reeks." }, episodes: { 1: [1, 2, 3, 4].map((n) => ({ id: "9" + n, episode_num: n, title: "Aflevering " + n, container_extension: "webm" })) } };
  else if (action === "get_vod_info") {
    const f = FILMS[+url.searchParams.get("vod_id") - 1000] || FILMS[0];
    out = { info: { plot: f[3], genre: f[1], releasedate: "2026-03-01", duration: "01:52:00", director: "Lien Claes", cast: "Ruben Maes, Nora Wouters, Jonas De Smet", rating: String(f[2]),
      backdrop_path: [host + "/art/wide/" + encodeURIComponent(f[0]) + ".svg"], movie_image: host + "/art/poster/" + encodeURIComponent(f[0]) + ".svg" } };
  }
  else if (action === "get_short_epg") out = listings(+url.searchParams.get("stream_id"), false);
  else if (action === "get_simple_data_table") out = listings(+url.searchParams.get("stream_id"), true);
  else out = [];
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify(out));
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

(async () => {
  const api = await listen(provider), site = await listen(files);
  const server = "127.0.0.1:" + api.address().port;
  const browser = await chromium.launch();
  // the TV picture: a wide drawn landscape, slowly panned
  const still = path.join(OUT, "_picture.png"), movie = path.join(OUT, "_picture.webm");
  const painter = await browser.newPage({ viewport: { width: 2400, height: 1080 } });
  await painter.setContent('<body style="margin:0">' + art("Zono avond", 2400, 1080) + "</body>");
  await painter.screenshot({ path: still }); await painter.close();
  execFileSync("ffmpeg", ["-v", "error", "-y", "-loop", "1", "-i", still, "-vf", "crop=1920:1080:'min(480,t*16)':0,scale=1280:720", "-t", "30", "-r", "25",
    "-c:v", "libvpx-vp9", "-b:v", "1500k", "-deadline", "realtime", "-cpu-used", "8", movie]);
  VIDEO = fs.readFileSync(movie);
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  page.on("pageerror", (e) => console.log("page error:", String(e)));
  await page.addInitScript((a) => {
    Object.defineProperty(navigator, "language", { get: () => a.lang });
    window.ZONO_API = a.base + "/api"; window.ZONO_PAIR_API = a.base + "/nopair";
  }, { base: "http://" + server, lang: LANG });
  await page.goto("http://127.0.0.1:" + site.address().port + "/index.html");
  const key = async (name, times = 1) => { for (let i = 0; i < times; i++) { await page.keyboard.press(name); await sleep(90); } };
  const focusKey = (k) => page.evaluate((k) => { const el = document.querySelector('[data-key="' + k + '"]'); if (el) el.focus(); return !!el; }, k);
  const shot = async (name) => { await sleep(600); await page.screenshot({ path: path.join(OUT, name + ".png") }); console.log("picture", name); };

  await shot("00-login");
  await sleep(300);
  await key("ArrowDown"); await page.keyboard.type(server);
  await key("ArrowDown"); await page.keyboard.type("demo");
  await key("ArrowDown"); await page.keyboard.type("demo");
  await focusKey("connect"); await key("Enter");
  await page.waitForSelector(".hero h1", { timeout: 15000 });
  await page.evaluate(() => Zono.state.items.forEach((i) => { if (i.kind === "live") i.url = Catalog.urlOf(i, Zono.state.source).replace(/\.m3u8$/, ".webm"); }));
  await sleep(3500); // banner picture and posters
  await focusKey("hero-play");
  await shot("01-discover");

  await key("ArrowRight"); await key("Enter");
  await page.waitForSelector(".detail .detail-plot"); await sleep(1500);
  await shot("02-film");
  await key("Escape"); await sleep(400);

  await focusKey("menu-live"); await key("Enter");
  await sleep(2500);
  await key("ArrowRight"); await key("ArrowDown", 2); await sleep(2500);
  await shot("03-live");

  await key("Enter"); await sleep(2500);
  await shot("04-fullscreen");
  await key("Escape"); await sleep(1500);

  await focusKey("menu-guide"); await key("Enter");
  await page.waitForSelector(".tvg-box.now", { timeout: 8000 }); await sleep(3000);
  await shot("05-guide");
  await key("Escape"); await sleep(300);

  await focusKey("menu-series"); await key("Enter"); await sleep(2500);
  await shot("06-series");
  await browser.close(); api.close(); site.close();
  fs.unlinkSync(still); fs.unlinkSync(movie);
})().catch((e) => { console.error(e); process.exit(1); });

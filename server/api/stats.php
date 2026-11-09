<?php
// Zono statistics, behind a password (STATS_PASSWORD in config.php): active installs, versions, languages,
// Windows versions, downloads per release (from GitHub) and the latest problem reports.
require __DIR__ . '/lib.php';
session_start();
header('Cache-Control: no-store');
header('X-Robots-Tag: noindex');
if (isset($_POST['password'])) {
    if (STATS_PASSWORD !== 'VERANDER-DIT-WACHTWOORD' && hash_equals(STATS_PASSWORD, (string)$_POST['password'])) {
        session_regenerate_id(true);
        $_SESSION['zono'] = true;
    } else {
        sleep(2);
    }
}
if (isset($_GET['logout'])) { $_SESSION = []; session_destroy(); header('Location: stats.php'); exit; }
function h($text) { return htmlspecialchars((string)$text, ENT_QUOTES, 'UTF-8'); }
?><!doctype html><html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Zono statistieken</title>
<style>
:root{--ink:#10101b;--violet:#514eff;--paper:#f7f6ff;--line:rgba(19,17,42,.12);--muted:#6b6880}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
header{background:linear-gradient(135deg,#504def,#7542eb);color:#fff;padding:28px clamp(16px,5vw,60px)}
header h1{margin:0;font-size:26px}header a{color:#fff;opacity:.8;font-size:13px}
main{padding:28px clamp(16px,5vw,60px);display:grid;gap:22px;max-width:1200px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px}
.card{background:#fff;border:1px solid var(--line);border-radius:20px;padding:18px 20px}
.card b{display:block;font-size:30px;line-height:1.1}.card span{color:var(--muted);font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
table{width:100%;border-collapse:collapse}td,th{padding:7px 4px;border-bottom:1px solid var(--line);text-align:left;font-size:14px}
th{color:var(--muted);font-weight:600}td.n{text-align:right;font-variant-numeric:tabular-nums}
.bar{height:8px;border-radius:4px;background:var(--violet);opacity:.75}
form{max-width:340px;margin:12vh auto;background:#fff;border:1px solid var(--line);border-radius:22px;padding:28px}
input{width:100%;padding:11px 13px;border:1px solid var(--line);border-radius:12px;font:inherit;margin:12px 0}
button{background:var(--violet);color:#fff;border:0;border-radius:999px;padding:11px 20px;font:600 15px system-ui;cursor:pointer}
pre{white-space:pre-wrap;font-size:12px;background:#f2f1fb;border-radius:12px;padding:10px;max-height:200px;overflow:auto}
details{border-bottom:1px solid var(--line);padding:8px 0}summary{cursor:pointer}
</style></head><body>
<?php if (empty($_SESSION['zono'])): ?>
<form method="post"><h2 style="margin:0">Zono statistieken</h2>
<?php if (STATS_PASSWORD === 'VERANDER-DIT-WACHTWOORD'): ?><p style="color:#c0392b">Stel eerst een wachtwoord in, in config.php.</p><?php endif; ?>
<input type="password" name="password" placeholder="Wachtwoord" autofocus><button>Inloggen</button></form>
<?php else:
$pdo = db();
$today = gmdate('Y-m-d');
$count = function (string $sql, array $args = []) use ($pdo) { $q = $pdo->prepare($sql); $q->execute($args); return (int)$q->fetchColumn(); };
$active = function (int $days) use ($count) { return $count('SELECT COUNT(DISTINCT id) FROM activity WHERE day > ?', [gmdate('Y-m-d', time() - $days * 86400)]); };
$group = function (string $column) use ($pdo) {
    $q = $pdo->prepare("SELECT COALESCE(NULLIF($column, ''), '?') AS k, COUNT(*) AS n FROM installs WHERE last_day > ? GROUP BY k ORDER BY n DESC LIMIT 12");
    $q->execute([gmdate('Y-m-d', time() - 30 * 86400)]); return $q->fetchAll(PDO::FETCH_ASSOC); };
$days = $pdo->prepare('SELECT day, COUNT(*) AS n FROM activity WHERE day > ? GROUP BY day ORDER BY day');
$days->execute([gmdate('Y-m-d', time() - 30 * 86400)]); $days = $days->fetchAll(PDO::FETCH_ASSOC);
$peak = max(array_merge([1], array_column($days, 'n')));
// downloads from GitHub, cached for an hour
$cache = DATA_DIR . '/github.json';
if (!is_file($cache) || filemtime($cache) < time() - 3600) {
    $context = stream_context_create(['http' => ['header' => "User-Agent: Zono-stats\r\nAccept: application/vnd.github+json\r\n", 'timeout' => 8]]);
    $json = @file_get_contents('https://api.github.com/repos/' . GITHUB_REPO . '/releases?per_page=30', false, $context);
    if ($json) file_put_contents($cache, $json);
}
$releases = is_file($cache) ? (json_decode(file_get_contents($cache), true) ?: []) : [];
$downloads = 0; foreach ($releases as $r) foreach (($r['assets'] ?? []) as $a) $downloads += (int)($a['download_count'] ?? 0);
$reports = $pdo->query('SELECT * FROM reports ORDER BY id DESC LIMIT 20')->fetchAll(PDO::FETCH_ASSOC);
?>
<header><h1>Zono statistieken</h1><a href="?logout">Uitloggen</a></header>
<main>
<div class="cards">
  <div class="card"><b><?= $active(1) ?></b><span>Actief vandaag</span></div>
  <div class="card"><b><?= $active(7) ?></b><span>Actief deze week</span></div>
  <div class="card"><b><?= $active(30) ?></b><span>Actief deze maand</span></div>
  <div class="card"><b><?= $count('SELECT COUNT(*) FROM installs') ?></b><span>Installaties ooit</span></div>
  <div class="card"><b><?= $downloads ?></b><span>Downloads (GitHub)</span></div>
  <div class="card"><b><?= $count('SELECT COUNT(*) FROM reports') ?></b><span>Probleemmeldingen (90 d.)</span></div>
</div>
<div class="card"><h3 style="margin-top:0">Actieve installaties per dag (30 dagen)</h3>
<table><?php foreach ($days as $d): ?><tr><td style="width:110px"><?= h($d['day']) ?></td>
<td><div class="bar" style="width:<?= round($d['n'] / $peak * 100) ?>%"></div></td><td class="n" style="width:60px"><?= (int)$d['n'] ?></td></tr><?php endforeach; ?></table></div>
<div class="grid">
<?php foreach (['version' => 'Versies', 'language' => 'Talen', 'windows' => 'Windows'] as $column => $title): ?>
  <div class="card"><h3 style="margin-top:0"><?= $title ?> <span>(actief, 30 d.)</span></h3><table>
  <?php foreach ($group($column) as $row): ?><tr><td><?= h($row['k']) ?></td><td class="n"><?= (int)$row['n'] ?></td></tr><?php endforeach; ?>
  </table></div>
<?php endforeach; ?>
  <div class="card"><h3 style="margin-top:0">Downloads per release</h3><table>
  <?php foreach ($releases as $r): $n = 0; foreach (($r['assets'] ?? []) as $a) $n += (int)($a['download_count'] ?? 0); ?>
  <tr><td><?= h($r['tag_name'] ?? '') ?></td><td class="n"><?= $n ?></td></tr><?php endforeach; ?></table></div>
</div>
<div class="card"><h3 style="margin-top:0">Laatste probleemmeldingen</h3>
<?php foreach ($reports as $r): ?><details><summary>#<?= (int)$r['id'] ?> · <?= h(substr($r['at'], 0, 16)) ?> · Zono <?= h($r['version']) ?> · <?= h(mb_substr($r['message'] ?: '(geen bericht)', 0, 80)) ?></summary>
<p><?= nl2br(h($r['message'])) ?></p><p>Contact: <?= h($r['contact'] ?: '-') ?> · Taal: <?= h($r['language']) ?> · <?= h($r['windows']) ?></p>
<?php if ($r['log']): ?><pre><?= h($r['log']) ?></pre><?php endif; ?></details><?php endforeach; ?>
<?php if (!$reports): ?><p>Nog geen meldingen.</p><?php endif; ?></div>
</main>
<?php endif; ?>
</body></html>

<?php
// Linking Zono apps: "continue watching", favourites and the last channel, shared between Windows, LG and Android TV.
//   GET  ?id=<64 hex>                       -> {"rev": n, "data": "<locked>"}   (rev 0 and no data: nothing yet)
//   POST {"id", "rev", "data"}              -> {"rev": n+1}, or 409 {"rev", "data"} when another device was first
// The id and the key come from the subscription (or a link code) on the device itself; the key never reaches this
// server. The server only holds one locked package (NaCl secretbox) per id, which it cannot open.
require __DIR__ . '/lib.php';

const SYNC_MAX = 400000;   // bytes of locked data (base64): far more than a few hundred titles need
const SYNC_KEEP_DAYS = 180;
if (!defined('SYNC_WRITES_PER_HOUR')) define('SYNC_WRITES_PER_HOUR', 240);

$pdo = db();
$pdo->exec('CREATE TABLE IF NOT EXISTS sync (id TEXT PRIMARY KEY, rev INTEGER, data TEXT, updated INTEGER)');

function sync_id(string $id): string {
    if (!preg_match('/^[0-9a-f]{64}$/', $id)) answer(400, ['error' => 'bad id']);
    return $id;
}
function sync_row(PDO $pdo, string $id): array {
    $row = $pdo->prepare('SELECT rev, data FROM sync WHERE id = ?');
    $row->execute([$id]);
    $found = $row->fetch(PDO::FETCH_ASSOC);
    return $found ? ['rev' => (int)$found['rev'], 'data' => (string)$found['data']] : ['rev' => 0, 'data' => ''];
}

if (($_SERVER['REQUEST_METHOD'] ?? '') === 'GET') {
    $id = sync_id((string)($_GET['id'] ?? ''));
    if (random_int(1, 200) === 1) {
        $pdo->prepare('DELETE FROM sync WHERE updated < ?')->execute([time() - SYNC_KEEP_DAYS * 86400]);
    }
    answer(200, sync_row($pdo, $id));
}

$body = read_json(SYNC_MAX + 1000);
$id = sync_id((string)($body['id'] ?? ''));
$data = (string)($body['data'] ?? '');
$rev = (int)($body['rev'] ?? -1);
if ($rev < 0 || strlen($data) < 40 || strlen($data) > SYNC_MAX || !preg_match('/^[A-Za-z0-9+\/=]+$/', $data)) answer(400, ['error' => 'bad input']);
if (limited('sync', SYNC_WRITES_PER_HOUR)) answer(429, ['error' => 'too many']);

$pdo->beginTransaction();
$now = sync_row($pdo, $id);
if ($now['rev'] !== $rev) {
    $pdo->rollBack();
    answer(409, $now); // another device saved first: merge with this and try again
}
if ($rev === 0) {
    $pdo->prepare('INSERT OR IGNORE INTO sync (id, rev, data, updated) VALUES (?, 1, ?, ?)')->execute([$id, $data, time()]);
} else {
    $pdo->prepare('UPDATE sync SET rev = rev + 1, data = ?, updated = ? WHERE id = ? AND rev = ?')->execute([$data, time(), $id, $rev]);
}
$pdo->commit();
$after = sync_row($pdo, $id);
if ($after['rev'] !== $rev + 1 || $after['data'] !== $data) answer(409, $after);
answer(200, ['rev' => $after['rev']]);

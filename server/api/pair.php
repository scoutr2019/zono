<?php
// "Log in with your phone" for Zono on a TV.
//  1. The TV asks for a code:            POST {"action":"new"}                      -> {"code": "..."}
//  2. The TV shows a QR code: https://zono.be/tv/#<code>.<key>. The key never reaches this server (it is after #).
//  3. The phone sends the login, locked with that key (NaCl secretbox): POST {"action":"send","code","data"}
//  4. The TV asks every few seconds:     GET ?code=...  -> {"wait":true} or {"data":"..."} (then it is deleted)
// The server only ever holds locked data it cannot open, for at most 10 minutes.
require __DIR__ . '/lib.php';

const PAIR_SECONDS = 600;
if (!defined('PAIRS_PER_HOUR')) define('PAIRS_PER_HOUR', 30); // codes per TV address per hour, against abuse
$pdo = db();
$pdo->exec('CREATE TABLE IF NOT EXISTS pairs (code TEXT PRIMARY KEY, created INTEGER, data TEXT)');
$pdo->prepare('DELETE FROM pairs WHERE created < ?')->execute([time() - PAIR_SECONDS]);

function valid_code(string $code): bool { return (bool)preg_match('/^[A-Z2-7]{10}$/', $code); }

if (($_SERVER['REQUEST_METHOD'] ?? '') === 'GET') {
    $code = (string)($_GET['code'] ?? '');
    if (!valid_code($code)) answer(400, ['error' => 'bad code']);
    $row = $pdo->prepare('SELECT data FROM pairs WHERE code = ?');
    $row->execute([$code]);
    $found = $row->fetch(PDO::FETCH_ASSOC);
    if (!$found) answer(404, ['error' => 'expired']);
    if ($found['data'] === null) answer(200, ['wait' => true]);
    $pdo->prepare('DELETE FROM pairs WHERE code = ?')->execute([$code]);
    answer(200, ['data' => $found['data']]);
}

$body = read_json(8192);
$action = (string)($body['action'] ?? '');
if ($action === 'new') {
    if (limited('pair', PAIRS_PER_HOUR)) answer(429, ['error' => 'too many']);
    $alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
    $code = '';
    foreach (str_split(random_bytes(10)) as $byte) $code .= $alphabet[ord($byte) % 32];
    $pdo->prepare('INSERT INTO pairs (code, created, data) VALUES (?, ?, NULL)')->execute([$code, time()]);
    answer(200, ['code' => $code, 'seconds' => PAIR_SECONDS]);
}
if ($action === 'send') {
    if (limited('pair-send', PAIRS_PER_HOUR)) answer(429, ['error' => 'too many']);
    $code = (string)($body['code'] ?? '');
    $data = (string)($body['data'] ?? '');
    if (!valid_code($code) || !preg_match('/^[A-Za-z0-9+\/=]{40,6000}$/', $data)) answer(400, ['error' => 'bad input']);
    $update = $pdo->prepare('UPDATE pairs SET data = ? WHERE code = ? AND data IS NULL');
    $update->execute([$data, $code]);
    if ($update->rowCount() !== 1) answer(404, ['error' => 'expired']);
    answer(200, ['ok' => true]);
}
answer(400, ['error' => 'unknown action']);

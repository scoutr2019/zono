<?php
// Anonymous usage statistics: once a day an installed Zono says "I'm here" with a random number (not linked to a
// person), its version, language and Windows version. Nothing about what is watched, no provider, no IP address.
require __DIR__ . '/lib.php';
$data = read_json(2048);
$id = (string)($data['id'] ?? '');
if (!preg_match('/^[0-9a-f]{32}$/', $id)) answer(400, ['error' => 'bad id']);
$version = text($data, 'version', 20, '/^[0-9.]*$/');
$language = text($data, 'language', 5, '/^[a-z]*$/');
$windows = text($data, 'windows', 40);
$day = gmdate('Y-m-d');
$pdo = db();
$pdo->prepare('INSERT INTO installs (id, first_day, last_day, version, language, windows) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET last_day = excluded.last_day, version = excluded.version,
               language = excluded.language, windows = excluded.windows')
    ->execute([$id, $day, $day, $version, $language, $windows]);
$pdo->prepare('INSERT OR IGNORE INTO activity (day, id, version) VALUES (?, ?, ?)')->execute([$day, $id, $version]);
answer(200, ['ok' => true]);

<?php
// Shared code for the Zono API: database, JSON answers, rate limits. No IP addresses are stored: for the rate limit
// only a salted hash of the address is kept, and only for one day.
require __DIR__ . '/config.php';

function db(): PDO {
    static $pdo = null;
    if ($pdo) return $pdo;
    if (!is_dir(DATA_DIR)) mkdir(DATA_DIR, 0750, true);
    $pdo = new PDO('sqlite:' . DATA_DIR . '/zono.sqlite');
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $pdo->exec('PRAGMA journal_mode=WAL');
    $pdo->exec('CREATE TABLE IF NOT EXISTS installs (id TEXT PRIMARY KEY, first_day TEXT, last_day TEXT,
                version TEXT, language TEXT, windows TEXT)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS activity (day TEXT, id TEXT, version TEXT, PRIMARY KEY (day, id))');
    $pdo->exec('CREATE TABLE IF NOT EXISTS limits (key TEXT, at INTEGER)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY, at TEXT, version TEXT, language TEXT,
                windows TEXT, message TEXT, contact TEXT, log TEXT)');
    return $pdo;
}

function answer(int $status, array $body): void {
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($body, JSON_UNESCAPED_UNICODE);
    exit;
}

function read_json(int $max_bytes): array {
    if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') answer(405, ['error' => 'POST only']);
    $raw = file_get_contents('php://input', false, null, 0, $max_bytes + 1);
    if ($raw === false || strlen($raw) > $max_bytes) answer(413, ['error' => 'too large']);
    $data = json_decode($raw, true);
    if (!is_array($data)) answer(400, ['error' => 'bad json']);
    return $data;
}

function text(array $data, string $key, int $max, string $pattern = '/^[\p{L}\p{N} ._:\/()\-+,]*$/u'): string {
    $value = trim((string)($data[$key] ?? ''));
    $value = mb_substr($value, 0, $max);
    return preg_match($pattern, $value) ? $value : '';
}

function salt(): string {
    $file = DATA_DIR . '/salt.txt';
    if (!is_file($file)) file_put_contents($file, bin2hex(random_bytes(16)));
    return trim(file_get_contents($file));
}

function limited(string $kind, int $per_hour): bool {
    // a salted hash of the sender's address, kept for one day at most
    $who = hash('sha256', salt() . ($_SERVER['REMOTE_ADDR'] ?? '') . date('Y-m-d'));
    $key = $kind . ':' . $who;
    $pdo = db();
    $pdo->prepare('DELETE FROM limits WHERE at < ?')->execute([time() - 86400]);
    $count = $pdo->prepare('SELECT COUNT(*) FROM limits WHERE key = ? AND at > ?');
    $count->execute([$key, time() - 3600]);
    if ((int)$count->fetchColumn() >= $per_hour) return true;
    $pdo->prepare('INSERT INTO limits (key, at) VALUES (?, ?)')->execute([$key, time()]);
    return false;
}

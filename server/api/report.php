<?php
// "Probleem melden" in the app: the user's message, the app version and (if the user agreed) the error log,
// mailed to support. Kept on the server too, so nothing is lost when mail fails.
require __DIR__ . '/lib.php';
$data = read_json(300 * 1024);
if (limited('report', REPORTS_PER_HOUR)) answer(429, ['error' => 'too many reports']);
$version = text($data, 'version', 20, '/^[0-9.]*$/');
$language = text($data, 'language', 5, '/^[a-z]*$/');
$windows = text($data, 'windows', 60);
$message = mb_substr(trim((string)($data['message'] ?? '')), 0, 4000);
$contact = mb_substr(trim((string)($data['contact'] ?? '')), 0, 200);
if ($contact !== '' && !filter_var($contact, FILTER_VALIDATE_EMAIL)) $contact = '';
$log = mb_substr((string)($data['log'] ?? ''), 0, 250 * 1024);
if ($message === '' && $log === '') answer(400, ['error' => 'empty']);
$pdo = db();
$pdo->prepare('DELETE FROM reports WHERE at < ?')->execute([gmdate('c', time() - 90 * 86400)]);  // kept 90 days
$pdo->prepare('INSERT INTO reports (at, version, language, windows, message, contact, log) VALUES (?, ?, ?, ?, ?, ?, ?)')
    ->execute([gmdate('c'), $version, $language, $windows, $message, $contact, $log]);
$number = (int)$pdo->lastInsertId();

$subject = "Zono probleem #$number" . ($version ? " (Zono $version)" : '');
$body = "Melding #$number\nVersie: $version\nTaal: $language\nWindows: $windows\n"
      . "Contact: " . ($contact ?: '(niet opgegeven)') . "\n\nBericht:\n" . ($message ?: '(geen)') . "\n";
$boundary = 'zono' . bin2hex(random_bytes(8));
$headers = "From: Zono <" . MAIL_FROM . ">\r\nMIME-Version: 1.0\r\n"
         . "Content-Type: multipart/mixed; boundary=\"$boundary\"\r\n";
if ($contact) $headers .= "Reply-To: $contact\r\n";
$mail = "--$boundary\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n$body\r\n";
if ($log !== '') {
    $mail .= "--$boundary\r\nContent-Type: text/plain; charset=utf-8; name=\"zono-log-$number.txt\"\r\n"
           . "Content-Disposition: attachment; filename=\"zono-log-$number.txt\"\r\n"
           . "Content-Transfer-Encoding: base64\r\n\r\n" . chunk_split(base64_encode($log)) . "\r\n";
}
$mail .= "--$boundary--\r\n";
$sent = function_exists('mail') && @mail(SUPPORT_EMAIL, '=?UTF-8?B?' . base64_encode($subject) . '?=', $mail, $headers);
answer(200, ['ok' => true, 'number' => $number, 'mailed' => (bool)$sent]);

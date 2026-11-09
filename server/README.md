# Zono op zono.be: probleem melden en statistieken

Kleine PHP-scripts voor cPanel (PHP 7.4+ met PDO SQLite, standaard bij de meeste hosts).

## Installeren (eenmalig)

1. Open `api/config.php` en zet bij `STATS_PASSWORD` een eigen, sterk wachtwoord.
2. Upload de hele map `api` naar `public_html` op zono.be, zodat je `https://zono.be/api/ping.php` krijgt.
3. Controleer dat `https://zono.be/api/data/` een **403 Forbidden** geeft (de database is afgeschermd).
4. Open `https://zono.be/api/stats.php` en log in met je wachtwoord.

## Wat elk bestand doet

| Bestand | Doel |
|---|---|
| `ping.php` | Anonieme dagelijkse statistiek van de app: willekeurig nummer, versie, taal, Windows-versie. Geen IP-adres. |
| `report.php` | "Probleem melden" in de app: bericht, optioneel e-mailadres en het (opgeschoonde) logboek. Mailt naar `SUPPORT_EMAIL` en bewaart de melding 90 dagen. Maximaal 5 meldingen per uur per afzender. |
| `stats.php` | De statistiekenpagina achter een wachtwoord: actieve gebruikers per dag/week/maand, versies, talen, Windows-versies, downloads per release (GitHub) en de laatste meldingen. |
| `config.php`, `lib.php` | Instellingen en gedeelde code; niet bereikbaar via de browser (`.htaccess`). |
| `data/` | De SQLite-database; afgeschermd met `data/.htaccess`. |

Komt de e-mail niet aan, vraag dan aan Junda of PHP `mail()` toegestaan is en of `MAIL_FROM` (`noreply@zono.be`) mag versturen. De meldingen staan hoe dan ook op `stats.php`.

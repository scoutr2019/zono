# Wijzigingen

## 2.3.0
- Automatische updates: Zono zoekt bij het starten naar een nieuwe release op GitHub, haalt `Zono.exe` op de achtergrond binnen (gecontroleerd met de SHA-256 van GitHub) en vraagt om te herstarten. Niets verwijderen of opnieuw installeren.
- Zono komt in het Startmenu; oude uitgepakte versies worden opgeruimd.
- Instellingen › Updates: aan/uit en "Nu zoeken naar updates".

## 2.2.2
- Fout opgelost: Escape in volledig scherm, nadat de bedieningsbalk vanzelf verdwenen was, gaf "window isn't packed". Met een test die precies dat nadoet.

## 2.2.1
- Posters als de beeldserver van de provider niet bestaat of geblokkeerd is: Zono gebruikt de foto's uit de filminfo van de provider (vaak TMDB) of, met een TMDB-sleutel, TMDB zelf, en onthoudt per titel wat werkte (art.json).
- Servernamen die de DNS van je internetprovider blokkeert, worden opgezocht via beveiligde DNS (Cloudflare/Google).
- Een server die niet bestaat wordt 10 minuten overgeslagen in plaats van bij elke poster opnieuw te wachten.
- Eén ontbrekende poster (404) komt niet meer als melding in het logboek.

## 2.2.0
- Zono in vier talen: Nederlands, Français, English, Deutsch (Instellingen › Algemeen › Taal; volgt standaard Windows).
- Posters en achtergronden laden betrouwbaarder: andere route bij een systeemproxy, http/https-terugval, browser-herkenning; een melding in het logboek als een beeldserver niet antwoordt.
- De app gaat als gecompileerde code in de exe.
- Licentie: PolyForm Strict 1.0.0.

## 2.1.2
- Zoeken: elke extra letter zoekt alleen nog in de vorige treffers (veel sneller bij grote bibliotheken).
- Live TV opent sneller: de eerste zenders verschijnen meteen, de rest wordt erbij geladen.
- Ontdekken: landen- en genrerijen worden één keer berekend en onthouden.
- Posters: het hover-beeld wordt pas gemaakt als je erover gaat; binnenkomende posters worden in kleine porties verwerkt (vloeiender scrollen tijdens het laden).
- Testsuite (45 tests) en GitHub-bestanden toegevoegd.

## 2.1.1
- Afleveringstitels opgeschoond ([ALL], S01E01), soepeler scrollen en wisselen van pagina, bibliotheek één keer per opstart vernieuwd.

## 2.1
- Oorzaak van vastlopende pc's opgelost: een timer werd steeds opnieuw ingepland.

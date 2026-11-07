# Hoe Zono in elkaar zit

Zono is één Tkinter-programma (Python 3.12) met de VLC 3-videomotor via `ctypes`. Er zijn geen externe Python-pakketten nodig behalve Pillow.

## Bestanden

| Bestand | Rol |
|---|---|
| `src/app.py` | De app: venster, navigatie, alle pagina's, speler-bediening, profielen, instellingen. Klasse `Zono`. |
| `src/ui.py` | Kleuren, lettertypes, schaal (DPI), knoppen (`Pill`), schuifbalk (`Slider`), iconen en alle getekende beelden (kaarten, banners, logo). |
| `src/catalogue.py` | Provider en opslag: Xtream Codes-API, M3U, EPG, profielen, JSON-bestanden in `%LOCALAPPDATA%\Zono`, versleuteling (DPAPI), downloads, logboek. |
| `src/player.py` | VLC: `Player` (zichtbare speler in een venster), `Headless` (zonder beeld), `LiveBuffer` (pauzeren/terugspoelen bij live), `BufferTap`, `Recorder`, `Transcoder` (H.264 voor telefoons). |
| `src/remote.py` | Webserver voor "Op je telefoon": webpagina, bibliotheek, doorsturen van streams (`/s/…`), omzetten (`/t/…`), foutuitleg (`/api/check`). |
| `src/cast.py` | Tv's in huis vinden (SSDP/DLNA) en er een stream naartoe sturen. |
| `src/webview.py` | Trailers in de app: Edge in app-modus, als kindvenster in Zono. |
| `src/countries.py` | Landen herkennen en namen/titels opschonen. |
| `src/tmdb.py` | Optionele extra info van The Movie Database (eigen gratis sleutel). |
| `src/qr.py` | QR-codes zonder externe bibliotheek. |

## Draaiende delen

- **Eén schermthread.** Alles wat het scherm aanraakt gebeurt in de Tk-thread. Netwerk en beeldbewerking lopen in twee threadpools (`workers`, `art_workers`); hun resultaat gaat via een wachtrij naar `poll()`, dat elke 40 ms (bij drukte 15 ms) maximaal ~12 ms aan resultaten verwerkt. Zo blijft scrollen vloeiend terwijl posters binnenkomen.
- **Gefaseerd tekenen.** Een pagina tekent eerst wat je ziet; de rest komt via `defer()` in kleine stukjes. Een paginawissel verhoogt `generation`, waardoor oud werk vanzelf vervalt.
- **Timers.** `poll`, `session_tick` (speler, elke 0,4-1 s) en `recording_tick` (elke 5 s) plannen zichzelf in een `finally`, zodat een fout ze nooit stopt. Fouten gaan naar `report_error` → logboek (`zono.log`). De UI-test controleert dat het aantal wachtende timers niet oploopt.
- **Veilige modus.** Bij het starten wordt `running.flag` geschreven en bij netjes afsluiten verwijderd. Bleef het staan (vastgelopen start), dan start Zono de volgende keer zonder automatisch afspelen. `start.log` houdt de eerste minuut bij.

## Gegevens

Per profiel (`%LOCALAPPDATA%\Zono` of `…\profiles\<map>`): `library.json` (bibliotheek + provider), `activity.json` (favorieten, voortgang), `watched.json`, `downloads.json`, `recordings.json`, `genres.json`. Links in deze bestanden bevatten nooit je inloggegevens: die worden vervangen door `{zono-auth}` (`catalogue.seal`).

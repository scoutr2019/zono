# Onderdelen van derden en releasecontrole

Deze inventaris is gebaseerd op de aangeleverde broncode en Zono-2_2_1.exe. Zij is geen volledige juridische goedkeuring van de build.

| Onderdeel | Bevinding |
| --- | --- |
| Python-runtime | Eigen PSF-licentie en aanvullende kennisgevingen in runtime/LICENSE.txt. |
| Pillow | Eigen licentie aanwezig onder runtime/Lib/site-packages/pillow-12.3.0.dist-info/licenses/LICENSE. |
| Tcl/Tk | Eigen license.terms-bestanden aanwezig in de runtime. |
| libVLC / libvlccore | Versiestring 3.0.24, build 3.0.24-rc1-0-g6de05adcba; libVLC kent LGPL-voorwaarden. |
| VLC-pluginbundel | 362 bestanden onder video/plugins; bevat o.a. libx264_plugin.dll, libx26410b_plugin.dll, libx265_plugin.dll, libqt_plugin.dll en libstream_out_transcode_plugin.dll. Niet behandelen als uitsluitend LGPL. |
| video/COPYING.txt | Bevat GPL versie 2; de broncode-README mocht de hele bundel daarom niet zonder verdere controle als LGPL beschrijven. |

PolyForm Strict mag de rechten op deze onderdelen niet beperken. Een copyrightbericht van Zono verandert hun licenties niet.

## Nog nodig vóór publicatie van de exe

1. Stel de herkomst, exacte versies, licenties en eventuele wijzigingen vast van alle gebundelde native bibliotheken en plugins, inclusief onderliggende codec-bibliotheken.
2. Kies een aantoonbaar compatibele runtime voor Zono onder PolyForm Strict. Alleen de VLC-licentietekst wijzigen of plugins blind verwijderen lost dit niet op.
3. Voeg de vereiste licentieteksten, kennisgevingen en bijbehorende broncode of een distributiemethode die aan de betreffende licentie voldoet toe.
4. Controleer of vervanging van LGPL-bibliotheken mogelijk blijft en toepasselijke rechten op debugging van wijzigingen niet worden beperkt.
5. Test afspelen, opnemen, casten en telefoontranscodering na wijzigingen aan de runtime.

De aangeleverde exe is nog niet goedgekeurd voor publicatie. Er wordt geen v2.2.1-release getagd op basis van alleen deze documentatiecontrole.

## Bronnen

- https://docs.videolan.me/vlc-user/en/support/faq/legalconcerns.html
- https://github.com/videolan/vlc/blob/master/doc/standalone/libvlc.md
- https://polyformproject.org/licenses/strict/1.0.0

VideoLAN waarschuwt dat sommige modules GPL gebruiken en dat die combinatie vóór herdistributie moet worden gecontroleerd.

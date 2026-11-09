; Zono-Setup.exe: installs Zono for the current user (no administrator rights needed).
; Built by tools/build_installer.py:  makensis -DVERSION=2.3.2 -DAPP_EXE=<Zono.exe> -DOUT=<Zono-Setup.exe> zono.nsi
;
; Zono.exe goes to %LOCALAPPDATA%\Zono - the same place the automatic updater uses - with shortcuts "Zono"
; in the Start menu and on the desktop and an entry in Settings > Apps with a normal uninstall button.

Unicode true
ManifestDPIAware true
RequestExecutionLevel user
SetCompressor /SOLID lzma

!ifndef VERSION
  !error "VERSION ontbreekt (bv. -DVERSION=2.3.2)"
!endif
!ifndef APP_EXE
  !error "APP_EXE ontbreekt (pad naar Zono.exe)"
!endif
!ifndef OUT
  !define OUT "Zono-Setup.exe"
!endif

!define NAME "Zono"
!define PUBLISHER "Zono TV"
!define WEBSITE "https://zono.be"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\Zono"

Name "${NAME}"
OutFile "${OUT}"
InstallDir "$LOCALAPPDATA\Zono"
BrandingText "Zono ${VERSION}"
ShowInstDetails nevershow
ShowUninstDetails nevershow

VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=0 "ProductName" "Zono"
VIAddVersionKey /LANG=0 "FileDescription" "Zono installatie"
VIAddVersionKey /LANG=0 "CompanyName" "${PUBLISHER}"
VIAddVersionKey /LANG=0 "LegalCopyright" "© 2026 Zono TV"
VIAddVersionKey /LANG=0 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=0 "ProductVersion" "${VERSION}"

!include "MUI2.nsh"
!include "FileFunc.nsh"

!define MUI_ICON "..\src\Zono.ico"
!define MUI_UNICON "..\src\Zono.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "welcome.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "welcome.bmp"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_RIGHT
!define MUI_HEADERIMAGE_BITMAP "header.bmp"
!define MUI_ABORTWARNING

!define MUI_WELCOMEPAGE_TITLE "$(WelcomeTitle)"
!define MUI_WELCOMEPAGE_TEXT "$(WelcomeText)"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TITLE "$(FinishTitle)"
!define MUI_FINISHPAGE_TEXT "$(FinishText)"
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "$(RunZono)"
!define MUI_FINISHPAGE_RUN_FUNCTION StartZono
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Dutch"
!insertmacro MUI_LANGUAGE "French"
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "German"

LangString WelcomeTitle ${LANG_DUTCH} "Welkom bij Zono"
LangString WelcomeTitle ${LANG_FRENCH} "Bienvenue dans Zono"
LangString WelcomeTitle ${LANG_ENGLISH} "Welcome to Zono"
LangString WelcomeTitle ${LANG_GERMAN} "Willkommen bei Zono"
LangString WelcomeText ${LANG_DUTCH} "Zono ${VERSION} wordt op deze pc geïnstalleerd. Je hebt geen beheerdersrechten nodig.$\r$\n$\r$\nZono levert zelf geen zenders, films of series: je koppelt je eigen abonnement of afspeellijst.$\r$\n$\r$\nKlik op Installeren om te beginnen."
LangString WelcomeText ${LANG_FRENCH} "Zono ${VERSION} va être installé sur ce PC. Aucun droit administrateur n'est nécessaire.$\r$\n$\r$\nZono ne fournit ni chaînes, ni films, ni séries : vous connectez votre propre abonnement ou playlist.$\r$\n$\r$\nCliquez sur Installer pour commencer."
LangString WelcomeText ${LANG_ENGLISH} "Zono ${VERSION} will be installed on this PC. No administrator rights are needed.$\r$\n$\r$\nZono does not provide channels, movies or series: you connect your own subscription or playlist.$\r$\n$\r$\nClick Install to start."
LangString WelcomeText ${LANG_GERMAN} "Zono ${VERSION} wird auf diesem PC installiert. Administratorrechte sind nicht nötig.$\r$\n$\r$\nZono liefert keine Sender, Filme oder Serien: Du verbindest dein eigenes Abo oder deine Playlist.$\r$\n$\r$\nKlicke auf Installieren, um zu beginnen."
LangString FinishTitle ${LANG_DUTCH} "Zono is geïnstalleerd"
LangString FinishTitle ${LANG_FRENCH} "Zono est installé"
LangString FinishTitle ${LANG_ENGLISH} "Zono is installed"
LangString FinishTitle ${LANG_GERMAN} "Zono ist installiert"
LangString FinishText ${LANG_DUTCH} "Je vindt Zono in het Startmenu en op je bureaublad. Nieuwe versies komen voortaan vanzelf binnen."
LangString FinishText ${LANG_FRENCH} "Zono se trouve dans le menu Démarrer et sur votre bureau. Les nouvelles versions arrivent désormais automatiquement."
LangString FinishText ${LANG_ENGLISH} "You'll find Zono in the Start menu and on your desktop. New versions now arrive automatically."
LangString FinishText ${LANG_GERMAN} "Du findest Zono im Startmenü und auf dem Desktop. Neue Versionen kommen ab jetzt automatisch."
LangString RunZono ${LANG_DUTCH} "Zono nu starten"
LangString RunZono ${LANG_FRENCH} "Lancer Zono maintenant"
LangString RunZono ${LANG_ENGLISH} "Start Zono now"
LangString RunZono ${LANG_GERMAN} "Zono jetzt starten"
LangString KeepData ${LANG_DUTCH} "Wil je ook je instellingen, favorieten, kijkvoortgang, downloads en providergegevens verwijderen?$\r$\n$\r$\nKies Nee om ze te bewaren voor als je Zono later opnieuw installeert."
LangString KeepData ${LANG_FRENCH} "Voulez-vous aussi supprimer vos paramètres, favoris, progression, téléchargements et identifiants du fournisseur ?$\r$\n$\r$\nChoisissez Non pour les conserver si vous réinstallez Zono plus tard."
LangString KeepData ${LANG_ENGLISH} "Do you also want to remove your settings, favourites, watch progress, downloads and provider details?$\r$\n$\r$\nChoose No to keep them in case you reinstall Zono later."
LangString KeepData ${LANG_GERMAN} "Möchtest du auch deine Einstellungen, Favoriten, deinen Fortschritt, Downloads und Anbieterdaten löschen?$\r$\n$\r$\nWähle Nein, um sie für eine spätere Neuinstallation zu behalten."
LangString StillRunning ${LANG_DUTCH} "Sluit Zono eerst en klik dan op Opnieuw."
LangString StillRunning ${LANG_FRENCH} "Fermez d'abord Zono, puis cliquez sur Réessayer."
LangString StillRunning ${LANG_ENGLISH} "Please close Zono first, then click Retry."
LangString StillRunning ${LANG_GERMAN} "Schließe zuerst Zono und klicke dann auf Wiederholen."

; No language question: NSIS picks Dutch, French, English or German from the Windows display language itself.

Function StartZono
  ; start without the installer's rights and without waiting for it
  Exec '"$INSTDIR\Zono.exe"'
FunctionEnd

Section "Zono" Main
  SetOutPath "$INSTDIR"
  ; A running Zono.exe cannot be overwritten, but it can be renamed: move it aside, Zono removes it later.
  IfFileExists "$INSTDIR\Zono.exe" 0 copy
    Delete "$INSTDIR\Zono.old.exe"
    Rename "$INSTDIR\Zono.exe" "$INSTDIR\Zono.old.exe"
  copy:
  ClearErrors
  File "/oname=Zono.exe" "${APP_EXE}"
  IfErrors 0 +3
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "$(StillRunning)" IDRETRY copy
    Abort

  ; tell the automatic updater which version is installed here
  FileOpen $0 "$INSTDIR\update.json" w
  FileWrite $0 '{"installed": "${VERSION}"}'
  FileClose $0

  WriteUninstaller "$INSTDIR\Zono verwijderen.exe"
  CreateShortcut "$SMPROGRAMS\Zono.lnk" "$INSTDIR\Zono.exe" "" "$INSTDIR\Zono.exe" 0 SW_SHOWNORMAL "" "Zono"
  CreateShortcut "$DESKTOP\Zono.lnk" "$INSTDIR\Zono.exe" "" "$INSTDIR\Zono.exe" 0 SW_SHOWNORMAL "" "Zono"

  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "Zono"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "${PUBLISHER}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "URLInfoAbout" "${WEBSITE}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "HelpLink" "mailto:support@zono.be"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\Zono.exe,0"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '"$INSTDIR\Zono verwijderen.exe"'
  WriteRegStr HKCU "${UNINSTALL_KEY}" "QuietUninstallString" '"$INSTDIR\Zono verwijderen.exe" /S'
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/M=Zono.exe /S=0K" $0 $1 $2
  IntOp $0 $0 + 250000  ; the unpacked app takes about this much on first start
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "EstimatedSize" $0
SectionEnd

Section "Uninstall"
  Delete "$SMPROGRAMS\Zono.lnk"
  Delete "$DESKTOP\Zono.lnk"
  DeleteRegKey HKCU "${UNINSTALL_KEY}"
  Delete "$INSTDIR\Zono.exe"
  Delete "$INSTDIR\Zono.old*.exe"
  Delete "$INSTDIR\Zono.exe.part"
  Delete "$INSTDIR\update.json"
  RMDir /r "$INSTDIR\app"
  IfSilent keep
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 "$(KeepData)" IDNO keep
    RMDir /r "$INSTDIR"
    Goto done
  keep:
  Delete "$INSTDIR\Zono verwijderen.exe"
  done:
SectionEnd

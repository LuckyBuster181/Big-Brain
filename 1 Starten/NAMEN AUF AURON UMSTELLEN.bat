@echo off
rem ======================================================================
rem  NAMEN AUF AURON UMSTELLEN.bat (P20 Teil C, 16.10.2026, Claude Code) - Ungetestet am PC.
rem  Benennt im Vault Dateien und Ordner mit "Jarvis" im Namen auf "Auron" um und passt die Links an.
rem  Fliesstext bleibt, wie er ist. Nichts wird geloescht. Gibt es den neuen Namen schon, bleibt die Datei.
rem  Ablauf: 1. Probelauf (zeigt alles, aendert nichts)  2. Frage J/N  3. erst bei J umstellen.
rem  Vorher: Git-Commit im Vault (falls Git da ist) und Sicherung der geaenderten Notizen.
rem  Rueckweg: diese Datei noch einmal starten und R waehlen (letzte Umstellung zurueck).
rem  Bericht: data\namen_auron_bericht.txt. Vorher Obsidian schliessen.
rem ======================================================================
setlocal EnableExtensions
chcp 65001 >nul
title Namen auf Auron umstellen
for %%I in ("%~dp0..") do set "J=%%~fI"
set "BERICHT=%J%\data\namen_auron_bericht.txt"
set "WERKZEUG=%J%\backend\tools\namen_auron.py"
if not exist "%J%\data" mkdir "%J%\data"
if not exist "%WERKZEUG%" (
  echo  FEHLER: %WERKZEUG% fehlt. Erst REPO HOLEN.bat starten.
  goto ende
)
set "PY="
if exist "%J%\backend\venv\Scripts\python.exe" set "PY=%J%\backend\venv\Scripts\python.exe"
if not defined PY (
  py -3 --version >nul 2>&1
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  python --version >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo  FEHLER: Kein Python gefunden. Bitte Claude Bescheid geben.
  goto ende
)

echo.
echo  Bitte Obsidian vorher schliessen.
echo  Moeglich: J = umstellen (nach dem Probelauf), R = letzte Umstellung zurueck, N = nichts tun.
choice /c PRN /m " Erst Probelauf (P), Rueckweg (R) oder Ende (N)"
if errorlevel 3 goto ende
if errorlevel 2 goto rueckweg

set "VAULTARG="
:probelauf
echo.
echo  ===== Probelauf (es wird nichts geaendert) =====
%PY% "%WERKZEUG%" --jarvis-ordner "%J%" %VAULTARG% --bericht "%BERICHT%"
if errorlevel 2 (
  echo.
  set /p "VAULT= Pfad zum Vault eingeben (z.B. C:\Users\maxi1\Documents\Brain): "
  call set "VAULTARG=--vault "%%VAULT%%""
  goto probelauf
)
echo.
choice /c JN /m " Jetzt so umstellen"
if errorlevel 2 (
  echo  Abgebrochen, nichts geaendert.
  goto ende
)
echo.
echo  ===== Umstellen =====
%PY% "%WERKZEUG%" --jarvis-ordner "%J%" %VAULTARG% --ausfuehren --bericht "%BERICHT%"
echo.
echo  Fertig. Syncthing bringt die Aenderung zum Mini-PC, Auron findet die neuen Namen selbst.
echo  Bericht: %BERICHT%
goto ende

:rueckweg
set "LETZTE="
for /f "delims=" %%D in ('dir /b /ad /o-n "%J%\data\namen_auron" 2^>nul') do if not defined LETZTE set "LETZTE=%%D"
if not defined LETZTE (
  echo  Keine fruehere Umstellung gefunden.
  goto ende
)
echo  Letzte Umstellung: %LETZTE%
choice /c JN /m " Diese Umstellung zuruecknehmen"
if errorlevel 2 goto ende
%PY% "%WERKZEUG%" --rueckweg "%J%\data\namen_auron\%LETZTE%\rueckweg.json" --bericht "%BERICHT%"

:ende
echo.
pause

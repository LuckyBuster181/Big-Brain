@echo off
rem REPO HOLEN.bat (10.10.2026, Claude Code): Gegenstueck zu REPO HOCHLADEN.bat.
rem Holt den neuesten Stand aus GitHub (main) in den Arbeitsordner Big-Brain-Repo
rem und kopiert den Code von dort in den Jarvis-Ordner.
rem - Kopiert nur Code: backend, dashboard, werkstatt, 1 Starten.
rem - Nie: Vault, data, .env, Modelle, Datenbanken, Logs. Loescht im Jarvis-Ordner nichts.
rem - Sichert vorher den alten Code nach KI\Jarvis-Sicherungen\<Datum_Uhrzeit>.
rem - Sich selbst und REPO HOCHLADEN.bat kopiert sie nicht (eine laufende .bat darf nicht ueberschrieben werden).
rem Danach: Python geaendert = Jarvis neu starten. Nur HTML oder JS = Strg+F5.
setlocal
title Auron: Code aus dem GitHub-Repo holen

set "REPOORDNER=C:\Users\maxi1\Documents\KI\Big-Brain-Repo"
set "JARVIS=C:\Users\maxi1\Documents\KI\Jarvis"
set "SICHERUNGEN=C:\Users\maxi1\Documents\KI\Jarvis-Sicherungen"
set "REPO=https://github.com/LuckyBuster181/Big-Brain.git"
set "XD=__pycache__ venv .venv models data node_modules .git .pytest_cache"
set "XF=.env *.env *.pyc *.db *.sqlite *.sqlite3 *.log *.bin *.onnx *.pth *.gguf *.safetensors"

if not exist "%JARVIS%\backend" goto KEINJARVIS
where git >nul 2>&1
if errorlevel 1 goto KEINGIT

echo.
echo  Achtung: Haben Sie am PC Code geaendert, der noch NICHT mit REPO HOCHLADEN.bat
echo  hochgeladen ist? Dann jetzt mit N abbrechen. Der alte Stand wird zwar gesichert,
echo  im Jarvis-Ordner aber durch den Stand aus GitHub ersetzt.
echo.
choice /c JN /m "Weiter"
if errorlevel 2 goto ABBRUCH

echo.
echo [1/4] Neuesten Stand aus GitHub holen
if exist "%REPOORDNER%\.git" goto HOLEN
git clone "%REPO%" "%REPOORDNER%"
if errorlevel 1 goto FEHLER
goto SICHERN

:HOLEN
for /f "delims=" %%A in ('git -C "%REPOORDNER%" status --porcelain --untracked-files=no') do goto UNSAUBER
git -C "%REPOORDNER%" checkout -q main
if errorlevel 1 goto FEHLER
git -C "%REPOORDNER%" pull --ff-only origin main
if errorlevel 1 goto FEHLER

:SICHERN
echo.
echo [2/4] Alten Code sichern
set "STEMPEL="
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set "STEMPEL=%%i"
if not defined STEMPEL set "STEMPEL=letzte"
set "SICHERUNG=%SICHERUNGEN%\%STEMPEL%"
for %%O in (backend dashboard werkstatt "1 Starten") do (
  if exist "%JARVIS%\%%~O\" (
    robocopy "%JARVIS%\%%~O" "%SICHERUNG%\%%~O" /E /XD %XD% /XF %XF% /MAX:5000000 /NFL /NDL /NJH /NJS /NP >nul
    if errorlevel 8 goto FEHLER
  )
)
echo  Gesichert in: %SICHERUNG%

echo.
echo [3/4] Code in den Jarvis-Ordner kopieren
for %%O in (backend dashboard werkstatt "1 Starten") do (
  if exist "%REPOORDNER%\%%~O\" (
    robocopy "%REPOORDNER%\%%~O" "%JARVIS%\%%~O" /E /XD %XD% /XF %XF% "REPO HOLEN.bat" "REPO HOCHLADEN.bat" /NFL /NDL /NJH /NJS /NP
    if errorlevel 8 goto FEHLER
  )
)

echo.
echo [4/4] Fertig. Letzte Aenderungen im Repo:
git -C "%REPOORDNER%" log --oneline -5
echo.
echo  Python geaendert = Auron NEU STARTEN. Nur HTML oder JS = Strg+F5.
echo  Alte Sicherungen in %SICHERUNGEN% duerfen Sie loeschen.
echo.
pause
exit /b 0

:KEINJARVIS
echo.
echo  FEHLER: Jarvis-Ordner nicht gefunden: %JARVIS%
goto ENDE_FEHLER

:KEINGIT
echo.
echo  FEHLER: Git ist nicht installiert oder nicht im PATH.
goto ENDE_FEHLER

:UNSAUBER
echo.
echo  STOPP: Im Ordner %REPOORDNER% gibt es Aenderungen, die noch nicht hochgeladen sind.
echo  Erst REPO HOCHLADEN.bat laufen lassen oder Claude Bescheid geben. Im Jarvis-Ordner wurde nichts geaendert.
goto ENDE_FEHLER

:ABBRUCH
echo.
echo  Abgebrochen. Es wurde nichts geaendert.
echo.
pause
exit /b 1

:FEHLER
echo.
echo  FEHLER beim Holen oder Kopieren. Bitte die Meldung oben Claude zeigen.
goto ENDE_FEHLER

:ENDE_FEHLER
echo.
pause
exit /b 1

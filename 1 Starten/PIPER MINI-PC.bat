@echo off
rem ======================================================================
rem  PIPER MINI-PC.bat (P05, 16.10.2026, Claude Code) - Ungetestet am PC.
rem  Richtet die Piper-Stimme auf dem Mini-PC ein (Ubuntu): Python-Paket piper-tts
rem  in die venv, Stimmen thorsten high und medium bereitstellen, Probesatz erzeugen.
rem    1 = Einrichten    2 = Messen (Fish Audio / Piper high / Piper medium)    3 = Stand zeigen
rem  Ergebnis: data\piper_mini_bericht.txt (bitte an Claude geben), Hoerproben data\piper_probe_*.wav,
rem  Messung data\stimme_messung.txt.
rem  Vorher: REPO HOLEN.bat und JARVIS STARTEN.bat (bringt den neuen Code auf den Mini-PC).
rem  Aendert nichts am Dienst jarvis und nichts an der .env.
rem ======================================================================
setlocal EnableExtensions
chcp 65001 >nul
title Piper auf dem Mini-PC
for %%I in ("%~dp0..") do set "J=%%~fI"
set "IP=192.168.68.139"
set "ZIEL=max1@%IP%"
set "SSHO=-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o BatchMode=yes"
set "BERICHT=%J%\data\piper_mini_bericht.txt"
if not exist "%J%\data" mkdir "%J%\data"

echo.
echo  Piper-Stimme auf dem Mini-PC
echo    1 = Einrichten (Paket, Stimmen, Probesatz)
echo    2 = Messen (dauert einige Minuten)
echo    3 = Stand zeigen
choice /c 123 /m " Was soll passieren"
set "WAHL=%errorlevel%"
set "AKTION=einrichten"
if "%WAHL%"=="2" set "AKTION=messen"
if "%WAHL%"=="3" set "AKTION=status"

> "%BERICHT%" echo ===== Piper Mini-PC %AKTION% %date% %time% =====
ping -n 2 -w 2000 %IP% >nul
if errorlevel 1 (
  echo  FEHLER: Mini-PC %IP% antwortet nicht. Ist er an?
  >> "%BERICHT%" echo FEHLER: Mini-PC %IP% antwortet nicht.
  goto ende
)
ssh %SSHO% %ZIEL% "mkdir -p ~/jarvis-umzug" >nul 2>&1
if errorlevel 1 (
  echo  FEHLER: SSH zum Mini-PC geht nicht. JARVIS STARTEN.bat einmal laufen lassen.
  >> "%BERICHT%" echo FEHLER: SSH zum Mini-PC geht nicht.
  goto ende
)
scp %SSHO% "%~dp0piper_mini_einrichten.sh" %ZIEL%:jarvis-umzug/piper_mini_einrichten.sh >nul 2>&1
if errorlevel 1 (
  echo  FEHLER: Skript konnte nicht auf den Mini-PC kopiert werden.
  >> "%BERICHT%" echo FEHLER: scp des Skripts fehlgeschlagen.
  goto ende
)
echo.
echo  Laeuft auf dem Mini-PC (%AKTION%) ... Ausgabe auch in %BERICHT%
ssh %SSHO% %ZIEL% "tr -d '\r' < ~/jarvis-umzug/piper_mini_einrichten.sh > ~/jarvis-umzug/piper_mini_einrichten.lf.sh; bash ~/jarvis-umzug/piper_mini_einrichten.lf.sh %AKTION%" >> "%BERICHT%" 2>&1
set "RC=%errorlevel%"
rem Hoerproben und Messung zurueck auf diesen PC holen (Projektordner steht im Bericht)
for /f "tokens=2,*" %%A in ('findstr /b /c:"Projektordner:" "%BERICHT%"') do set "REMOTE=%%A %%B"
if defined REMOTE (
  for %%D in (piper_probe_high.wav piper_probe_medium.wav stimme_messung.txt) do scp %SSHO% "%ZIEL%:%REMOTE%/data/%%D" "%J%\data\%%D" >nul 2>&1
)
type "%BERICHT%"
echo.
if "%RC%"=="0" (echo  Fertig.) else (echo  Mit Meldungen beendet [Code %RC%]. Bitte data\piper_mini_bericht.txt an Claude geben.)

:ende
echo.
pause

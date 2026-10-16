@echo off
rem ======================================================================
rem  WHISPER MINI-PC.bat (P04, 16.10.2026, Claude Code) - Ungetestet am PC.
rem  Lokale Spracherkennung (faster-whisper) auf dem Mini-PC (Ubuntu), alles per ssh:
rem    1 = Einrichten mit Modell base (Standard, schneller)
rem    2 = Einrichten mit Modell small (versteht besser, langsamer)
rem    3 = Messen: Dauer fuer 5 und 10 Sekunden Sprache (base und small)
rem    4 = Spracherkennung auf lokal stellen      5 = zurueck auf Browser      6 = Stand zeigen
rem  Einrichten installiert faster-whisper in die venv, laedt das Modell und startet den Dienst jarvis neu.
rem  Logdatei (an Claude geben): data\whisper_mini_bericht.txt. Messung auch in data\whisper_messung.txt.
rem  Vorher: REPO HOLEN.bat und JARVIS STARTEN.bat. Fuer die Messung vorher PIPER MINI-PC.bat (macht die Sprachproben).
rem  Aendert nichts an der .env. Kosten 0 EUR.
rem ======================================================================
setlocal EnableExtensions
chcp 65001 >nul
title Whisper auf dem Mini-PC
for %%I in ("%~dp0..") do set "J=%%~fI"
set "IP=192.168.68.139"
set "ZIEL=max1@%IP%"
set "SSHO=-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o BatchMode=yes"
set "BERICHT=%J%\data\whisper_mini_bericht.txt"
if not exist "%J%\data" mkdir "%J%\data"

echo.
echo  Lokale Spracherkennung (Whisper) auf dem Mini-PC
echo    1 = Einrichten mit Modell base (Standard)
echo    2 = Einrichten mit Modell small
echo    3 = Messen (base und small, einige Minuten)
echo    4 = Spracherkennung auf lokal stellen
echo    5 = Spracherkennung zurueck auf Browser
echo    6 = Stand zeigen
choice /c 123456 /m " Was soll passieren"
set "WAHL=%errorlevel%"
set "AKTION=einrichten base"
if "%WAHL%"=="2" set "AKTION=einrichten small"
if "%WAHL%"=="3" set "AKTION=messen base small"
if "%WAHL%"=="4" set "AKTION=lokal"
if "%WAHL%"=="5" set "AKTION=browser"
if "%WAHL%"=="6" set "AKTION=status"

>> "%BERICHT%" echo.
>> "%BERICHT%" echo ===== Whisper Mini-PC: %AKTION% %date% %time% =====
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
scp %SSHO% "%~dp0whisper_mini_einrichten.sh" %ZIEL%:jarvis-umzug/whisper_mini_einrichten.sh >nul 2>&1
if errorlevel 1 (
  echo  FEHLER: Skript konnte nicht auf den Mini-PC kopiert werden.
  >> "%BERICHT%" echo FEHLER: scp des Skripts fehlgeschlagen.
  goto ende
)
echo.
echo  Laeuft auf dem Mini-PC (%AKTION%) ... Ausgabe auch in %BERICHT%
ssh %SSHO% %ZIEL% "tr -d '\r' < ~/jarvis-umzug/whisper_mini_einrichten.sh > ~/jarvis-umzug/whisper_mini_einrichten.lf.sh; bash ~/jarvis-umzug/whisper_mini_einrichten.lf.sh %AKTION%" > "%TEMP%\whisper_mini.txt" 2>&1
set "RC=%errorlevel%"
type "%TEMP%\whisper_mini.txt" >> "%BERICHT%"
type "%TEMP%\whisper_mini.txt"
if "%WAHL%"=="3" (
  for /f "tokens=2,*" %%A in ('findstr /b /c:"Projektordner:" "%TEMP%\whisper_mini.txt"') do set "REMOTE=%%A %%B"
)
if defined REMOTE scp %SSHO% "%ZIEL%:%REMOTE%/data/whisper_messung.txt" "%J%\data\whisper_messung.txt" >nul 2>&1
echo.
if "%RC%"=="0" (echo  Fertig.) else (echo  Mit Meldungen beendet [Code %RC%]. Bitte data\whisper_mini_bericht.txt an Claude geben.)

:ende
echo.
pause

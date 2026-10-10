@echo off
rem AURON_APP_EINRICHTEN.bat (04.10.2026, Claude): legt das Symbol "Auron" auf dem Desktop und im Startmenue an.
rem Einmal starten. Danach genuegt ein Doppelklick auf das Symbol "Auron" (kein JARVIS STARTEN mehr noetig,
rem solange Jarvis auf dem Mini-PC laeuft; sonst fragt das Symbol, ob JARVIS STARTEN.bat laufen soll).
setlocal
chcp 65001 >nul
title Auron einrichten
cd /d "%~dp0"
for %%I in ("%~dp0..") do set "J=%%~fI"
set "BERICHT=%J%\data\auron_app_einrichten_bericht.txt"
> "%BERICHT%" echo ===== Auron App einrichten %date% %time% =====
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0auron_verknuepfung.ps1" >> "%BERICHT%" 2>&1
type "%BERICHT%"
echo.
findstr /b /c:"OK " "%BERICHT%" >nul
if errorlevel 1 (echo  FEHLER - bitte Claude Bescheid geben.) else (echo  Fertig. Auf dem Desktop liegt jetzt "Auron". Bitte Claude Bescheid geben.)
echo.
pause

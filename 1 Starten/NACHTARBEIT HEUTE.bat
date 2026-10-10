@echo off
rem NACHTARBEIT HEUTE.bat (04.10.2026, Claude): legt den Nachtauftrag Nr. 5 (Quellen/Lizenzen fuer Texturen) an
rem und zeigt, wann die Nachtarbeit laeuft (Timer auf dem Mini-PC: taeglich 03:00, Aufgaben nur lokal, 0 Euro).
rem Auf Wunsch startet sie zusaetzlich SOFORT. Ergebnis: data\nachtarbeit_heute_bericht.txt
setlocal
chcp 65001 >nul
title Nachtarbeit heute
cd /d "%~dp0"
for %%I in ("%~dp0..") do set "J=%%~fI"
set "BERICHT=%J%\data\nachtarbeit_heute_bericht.txt"
> "%BERICHT%" echo ===== Nachtarbeit heute %date% %time% =====
echo.
choice /c JN /t 20 /d N /m " Nachtarbeit zusaetzlich JETZT starten (J) oder nur um 03:00 (N)? (N nach 20 s)"
if errorlevel 2 (set "SOFORT=") else (set "SOFORT=-Sofort")
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0nachtarbeit_heute.ps1" %SOFORT% >> "%BERICHT%" 2>&1
type "%BERICHT%"
echo.
echo  Fertig. Bitte Claude Bescheid geben.
pause

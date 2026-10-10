@echo off
rem FEHLERBERICHT SENDEN.bat (10.10.2026, Claude Code): schickt Claude den Fehlerbericht von Auron.
rem Holt den Bericht vom laufenden Jarvis (Mini-PC ueber den Tunnel), haengt die Start-Protokolle dieses PCs an
rem und legt alles als berichte\fehlerbericht.md ins GitHub-Repo. Danach Claude sagen: "Lies den Fehlerbericht".
rem Schluessel, Tokens und Mailadressen werden vorher unkenntlich gemacht. Chat-Inhalte sind nicht dabei.
setlocal
title Auron: Fehlerbericht an Claude senden
for %%I in ("%~dp0..") do set "J=%%~fI"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fehlerbericht_senden.ps1" -J "%J%"
echo.
pause

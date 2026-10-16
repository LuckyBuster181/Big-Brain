@echo off
rem JARVIS STARTEN.bat - alter Name (bis 16.10.2026). Leitet nur weiter, damit Verknuepfungen und
rem Gewohnheit weiter gehen. Die eigentliche Startdatei ist "AURON STARTEN.bat" (P20). LF-Zeilenenden.
call "%~dp0AURON STARTEN.bat" %*
exit /b %errorlevel%

@echo off
rem Vault-Pflegebericht: prueft den Obsidian-Vault (liest nur) und schreibt den Bericht nach
rem Wissen\06 - Quellen und Pflege\Vault-Pflegebericht.md (wird jedes Mal ueberschrieben).
rem Dauer: wenige Sekunden, keine Last, kein Claude-Aufruf.
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
call venv\Scripts\activate.bat
python -m tools.vault_pflege
echo.
pause

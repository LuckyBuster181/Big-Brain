@echo off
rem Stufe-1-Befehl fuer den PC-Agenten (P22). Nicht interaktiv: es wird auf keine Eingabe gewartet.
rem Pfade relativ zum Jarvis-Ordner (diese Datei liegt in Jarvis\pc_befehle).
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set EMBEDDING_THREADS=2
set OMP_NUM_THREADS=2
set HF_HUB_DISABLE_PROGRESS_BARS=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set "JARVIS=%~dp0.."
cd /d "%JARVIS%\backend" || exit /b 2
if not exist venv\Scripts\activate.bat (
  echo FEHLER: venv fehlt in %JARVIS%\backend
  exit /b 2
)
call venv\Scripts\activate.bat
echo ==== Backup %DATE% %TIME% ====
rem Vault-Pfad aus .env (nur lesen, wird nicht ausgegeben)
set "VAULT="
for /f "usebackq delims=" %%V in (`python -c "from dotenv import load_dotenv; import os; load_dotenv(); print(os.getenv('VAULT_PATH') or '')"`) do set "VAULT=%%V"
if not defined VAULT (
  echo FEHLER: VAULT_PATH nicht gefunden
  exit /b 3
)
echo.
echo --- 1. Vault per Git sichern (nur wenn es Aenderungen gibt) ---
if not exist "%VAULT%\.git" (
  echo Kein Git-Repo im Vault - bitte einmal GIT_INIT_VAULT.bat starten. Uebersprungen.
) else (
  git -C "%VAULT%" add -A
  git -C "%VAULT%" diff --cached --quiet
  if errorlevel 1 (
    git -C "%VAULT%" commit -q -m "Auron Backup %DATE% %TIME%"
    echo Vault gesichert.
  ) else (
    echo Keine Aenderungen im Vault.
  )
)
echo.
echo --- 2. data\*.json kopieren ---
for /f %%D in ('python -c "import datetime; print(datetime.date.today().isoformat())"') do set "TAG=%%D"
set "ZIEL=%JARVIS%\data\sicherung\%TAG%"
if not exist "%ZIEL%" mkdir "%ZIEL%"
copy /Y "%JARVIS%\data\*.json" "%ZIEL%\" >nul
echo Kopiert nach %ZIEL% (nichts geloescht).
exit /b 0

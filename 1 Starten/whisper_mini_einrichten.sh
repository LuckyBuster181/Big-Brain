#!/usr/bin/env bash
# whisper_mini_einrichten.sh - P04 lokale Spracherkennung (faster-whisper) auf dem Mini-PC (16.10.2026, Claude Code)
#
# Wird von "1 Starten/WHISPER MINI-PC.bat" per ssh auf dem Mini-PC gestartet (nicht von Hand noetig):
#     bash whisper_mini_einrichten.sh einrichten [base|small]  Paket in die venv, Modell laden, Dienst neu starten
#     bash whisper_mini_einrichten.sh messen [base|small ...]   Dauer fuer 5 und 10 s Sprache
#     bash whisper_mini_einrichten.sh lokal | browser           Spracherkennung umstellen (Einstellung im Backend)
#     bash whisper_mini_einrichten.sh status
#
# Projektordner und venv findet es selbst (Dienst "jarvis", sonst bekannte Ordner); anders: JARVIS_DIR=/pfad.
# Aendert nichts an der .env. Kosten: 0 EUR (Download Modell base ca. 150 MB, small ca. 480 MB).
# Ungetestet auf dem Mini-PC (in der Cloud mit echtem faster-whisper und Piper-Sprachproben geprueft).

set -u

AKTION="${1:-einrichten}"
shift || true
PORT="${JARVIS_PORT:-8000}"
export WHISPER_THREADS="${WHISPER_THREADS:-2}"

suche_ordner() {
    local kandidat
    if [ -n "${JARVIS_DIR:-}" ] && [ -d "$JARVIS_DIR/backend" ]; then echo "$JARVIS_DIR"; return; fi
    for modus in "" "--user"; do
        kandidat="$(systemctl $modus show jarvis -p WorkingDirectory --value 2>/dev/null || true)"
        kandidat="${kandidat%/backend}"
        if [ -n "$kandidat" ] && [ -d "$kandidat/backend" ]; then echo "$kandidat"; return; fi
    done
    for kandidat in "$HOME/KI/Jarvis" "$HOME/Jarvis" "$HOME/jarvis" "$HOME/Brain" "$HOME/big-brain"; do
        if [ -d "$kandidat/backend" ]; then echo "$kandidat"; return; fi
    done
}

suche_python() {
    local ordner="$1" ausfuehren pfad
    for modus in "" "--user"; do
        ausfuehren="$(systemctl $modus show jarvis -p ExecStart --value 2>/dev/null || true)"
        pfad="$(printf '%s' "$ausfuehren" | grep -o 'path=[^ ;]*' | head -1 | cut -d= -f2)"
        case "$pfad" in */python*) if [ -x "$pfad" ]; then echo "$pfad"; return; fi;; esac
    done
    for pfad in "$HOME/.jarvis-venv/bin/python" "$ordner/venv/bin/python" "$ordner/.venv/bin/python" \
                "$ordner/backend/venv/bin/python" "$ordner/backend/.venv/bin/python"; do
        if [ -x "$pfad" ]; then echo "$pfad"; return; fi
    done
}

installieren() {
    # pip, sonst uv (die venv des Mini-PCs hat kein pip, Befund 16.10.2026), sonst ensurepip
    local uv kandidat
    uv="$(command -v uv 2>/dev/null || true)"
    for kandidat in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" "/usr/local/bin/uv"; do
        if [ -z "$uv" ] && [ -x "$kandidat" ]; then uv="$kandidat"; fi
    done
    if "$PY" -m pip --version >/dev/null 2>&1; then
        echo "  Weg: pip"; "$PY" -m pip install --upgrade "$@" 2>&1 | tail -4
    elif [ -n "$uv" ]; then
        echo "  Weg: uv ($uv)"; "$uv" pip install --python "$PY" --upgrade "$@" 2>&1 | tail -6
    elif "$PY" -m ensurepip --upgrade >/dev/null 2>&1; then
        echo "  Weg: ensurepip, danach pip"; "$PY" -m pip install --upgrade "$@" 2>&1 | tail -4
    else
        echo "FEHLER: die venv hat weder pip noch ensurepip, und uv wurde nicht gefunden."; return 1
    fi
}

einstellung() {
    # Einstellung im laufenden Backend setzen (gilt sofort, steht danach in data/einstellungen.json)
    local json="$1" i
    for i in $(seq 1 30); do
        if curl -s -m 3 -o /dev/null "http://127.0.0.1:$PORT/api/sprache/erkennen/status"; then break; fi
        sleep 2
    done
    if curl -s -m 10 -X PUT -H "Content-Type: application/json" -d "$json" "http://127.0.0.1:$PORT/api/einstellungen" -o /dev/null -w "%{http_code}" | grep -q 200; then
        echo "  Einstellung gesetzt: $json"
    else
        echo "  FEHLER: Backend auf Port $PORT nicht erreichbar, Einstellung $json NICHT gesetzt. Spaeter im HUD einstellen."
        return 1
    fi
}

stand_zeigen() {
    local antwort
    antwort="$(curl -s -m 5 "http://127.0.0.1:$PORT/api/sprache/erkennen/status" || true)"
    echo "  Backend meldet: ${antwort:-keine Antwort auf Port $PORT}"
}

neu_starten() {
    if [ -f "$HOME/jarvis-umzug/jarvis_mini.sh" ]; then
        bash "$HOME/jarvis-umzug/jarvis_mini.sh" neustart; local rc=$?
        if [ "$rc" -eq 0 ]; then echo "  Dienst jarvis neu gestartet."; return 0; fi
        echo "  Neustart ueber jarvis_mini.sh ging nicht (Code $rc). Bitte JARVIS STARTEN.bat starten."; return 1
    fi
    if systemctl --user restart jarvis 2>/dev/null || sudo -n systemctl restart jarvis 2>/dev/null; then
        echo "  Dienst jarvis neu gestartet."; return 0
    fi
    echo "  Dienst konnte nicht neu gestartet werden (kein Recht). Bitte JARVIS STARTEN.bat starten."; return 1
}

echo "===== Whisper auf dem Mini-PC: $AKTION $*, $(date '+%d.%m.%Y %H:%M:%S') ====="
ORDNER="$(suche_ordner)"
if [ -z "$ORDNER" ]; then echo "FEHLER: Projektordner nicht gefunden. JARVIS_DIR=/pfad angeben oder an Claude melden."; exit 2; fi
PY="$(suche_python "$ORDNER")"
if [ -z "$PY" ]; then echo "FEHLER: keine venv gefunden."; exit 2; fi
echo "Projektordner: $ORDNER"
echo "Python:        $PY ($("$PY" --version 2>&1))"
if ! grep -q "def vorladen" "$ORDNER/backend/app/stt.py" 2>/dev/null; then
    echo "FEHLER: Auf dem Mini-PC liegt noch der alte Code (stt.py ohne vorladen). Erst REPO HOLEN.bat und JARVIS STARTEN.bat."
    exit 3
fi
cd "$ORDNER/backend" || exit 2

case "$AKTION" in
einrichten)
    MODELL="${1:-base}"
    case "$MODELL" in base|small) ;; *) echo "FEHLER: Modell $MODELL (erlaubt: base, small)"; exit 1;; esac
    echo
    echo "1/4 faster-whisper in die venv installieren (av<19: faster-whisper 1.2.1 laeuft nicht mit av 19) ..."
    installieren faster-whisper "av<19" || exit 4
    if ! "$PY" -c "import faster_whisper, av" 2>/dev/null; then
        echo "FEHLER: faster-whisper laesst sich nicht importieren:"; "$PY" -c "import faster_whisper" 2>&1 | tail -3; exit 4
    fi
    "$PY" -c "import importlib.metadata as m; print('  faster-whisper', m.version('faster-whisper'), '| av', m.version('av'), '| ctranslate2', m.version('ctranslate2'))"
    echo
    echo "2/4 Modell $MODELL laden (beim ersten Mal Download) ..."
    WHISPER_MODELL="$MODELL" "$PY" -c "from app import stt; print('  geladen in', stt.vorladen(), 's')" 2>&1 | grep -v HF_TOKEN | tail -3
    echo
    echo "3/4 Dienst jarvis neu starten ..."
    neu_starten
    echo
    echo "4/4 Modell im Backend einstellen ..."
    einstellung "{\"whisper_modell\": \"$MODELL\"}"
    stand_zeigen
    echo
    echo "Fertig. Lokal einschalten: im .bat Taste 4 (oder HUD, Einstellungen, Spracherkennung: lokal)."
    ;;
messen)
    [ $# -gt 0 ] || set -- base
    echo "Messung laeuft (Modelle: $*, je 3 Laeufe fuer 5 und 10 s Sprache) ..."
    "$PY" whisper_messung.py --modelle "$@" --ausgabe "$ORDNER/data/whisper_messung.txt" 2>&1 | grep -v HF_TOKEN
    ;;
lokal)
    einstellung '{"spracherkennung": "lokal"}'; stand_zeigen ;;
browser)
    einstellung '{"spracherkennung": "browser"}'; stand_zeigen ;;
status)
    "$PY" -c "import importlib.metadata as m; print('faster-whisper', m.version('faster-whisper'), '| av', m.version('av'))" 2>&1 | tail -1
    stand_zeigen ;;
*)
    echo "Unbekannte Aktion: $AKTION (einrichten, messen, lokal, browser, status)"; exit 1 ;;
esac

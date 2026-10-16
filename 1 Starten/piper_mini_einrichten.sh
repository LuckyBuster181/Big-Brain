#!/usr/bin/env bash
# piper_mini_einrichten.sh - P05 Piper-Stimme auf dem Mini-PC (16.10.2026, Claude Code)
#
# Wird von "1 Starten/PIPER MINI-PC.bat" per ssh auf dem Mini-PC gestartet (nicht von Hand noetig):
#     bash piper_mini_einrichten.sh einrichten   Paket piper-tts in die venv, Stimmen bereitstellen, Probesatz
#     bash piper_mini_einrichten.sh messen       Messung Fish Audio / Piper high / Piper medium
#     bash piper_mini_einrichten.sh status       nur anzeigen, was da ist
#
# Es findet den Projektordner und die venv selbst: Dienst "jarvis" (systemd), sonst bekannte Ordner.
# Anderer Ordner: JARVIS_DIR=/pfad bash piper_mini_einrichten.sh einrichten
# Aendert nichts am Dienst und nichts an der .env. Kosten: 0 EUR (Download der Stimmen ca. 190 MB).
# Ungetestet auf dem Mini-PC (in der Cloud ist nur der Python-Teil mit einer echten Stimme geprueft).

set -u

AKTION="${1:-einrichten}"
HF="https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten"

suche_ordner() {
    local kandidat
    if [ -n "${JARVIS_DIR:-}" ] && [ -d "$JARVIS_DIR/backend" ]; then echo "$JARVIS_DIR"; return; fi
    for modus in "" "--user"; do
        kandidat="$(systemctl $modus show jarvis -p WorkingDirectory --value 2>/dev/null || true)"
        kandidat="${kandidat%/backend}"
        if [ -n "$kandidat" ] && [ -d "$kandidat/backend" ]; then echo "$kandidat"; return; fi
    done
    for kandidat in "$HOME/Jarvis" "$HOME/jarvis" "$HOME/Brain" "$HOME/big-brain" "$HOME/Documents/KI/Jarvis"; do
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
    for pfad in "$ordner/venv/bin/python" "$ordner/.venv/bin/python" "$ordner/backend/venv/bin/python" "$ordner/backend/.venv/bin/python"; do
        if [ -x "$pfad" ]; then echo "$pfad"; return; fi
    done
}

echo "===== Piper auf dem Mini-PC: $AKTION, $(date '+%d.%m.%Y %H:%M:%S') ====="
ORDNER="$(suche_ordner)"
if [ -z "$ORDNER" ]; then
    echo "FEHLER: Projektordner nicht gefunden (gesucht: Dienst jarvis, ~/Jarvis, ~/jarvis, ~/Brain, ~/big-brain)."
    echo "        Dann mit JARVIS_DIR=/pfad/zum/Projekt starten oder den Ordner an Claude melden."
    exit 2
fi
PY="$(suche_python "$ORDNER")"
if [ -z "$PY" ]; then
    echo "FEHLER: keine venv in $ORDNER gefunden (venv/bin/python, .venv/bin/python)."
    exit 2
fi
echo "Projektordner: $ORDNER"
echo "Python:        $PY ($("$PY" --version 2>&1))"

if [ ! -f "$ORDNER/backend/app/piper_tts.py" ] || ! grep -q "def paket_da" "$ORDNER/backend/app/piper_tts.py"; then
    echo "FEHLER: Auf dem Mini-PC liegt noch der alte Code (piper_tts.py ohne Linux-Weg)."
    echo "        Erst REPO HOLEN.bat, dann JARVIS STARTEN.bat (bringt den neuen Code hin), dann dies noch einmal."
    exit 3
fi

STIMMEN="$ORDNER/tools/piper"
DATEN="$ORDNER/data"
mkdir -p "$STIMMEN" "$DATEN"

stimme_holen() {
    local q="$1" name="de_DE-thorsten-$1"
    for ende in ".onnx" ".onnx.json"; do
        if [ -s "$STIMMEN/$name$ende" ]; then
            echo "  $name$ende: schon da ($(du -h "$STIMMEN/$name$ende" | cut -f1))"
        else
            echo "  $name$ende: lade herunter ..."
            if curl -fL --retry 2 --connect-timeout 20 -o "$STIMMEN/$name$ende.teil" "$HF/$q/$name$ende"; then
                mv "$STIMMEN/$name$ende.teil" "$STIMMEN/$name$ende"
                echo "  $name$ende: fertig ($(du -h "$STIMMEN/$name$ende" | cut -f1))"
            else
                rm -f "$STIMMEN/$name$ende.teil"
                echo "  FEHLER: $name$ende konnte nicht geladen werden (Internet am Mini-PC?)."
                return 1
            fi
        fi
    done
}

case "$AKTION" in
einrichten)
    echo
    echo "1/3 Python-Paket piper-tts in die venv installieren ..."
    # Die venv des Mini-PCs hat evtl. kein pip (Befund 16.10.2026: "No module named pip"). Dann uv, sonst ensurepip.
    UV="$(command -v uv 2>/dev/null || true)"
    for kandidat in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" "/usr/local/bin/uv"; do
        if [ -z "$UV" ] && [ -x "$kandidat" ]; then UV="$kandidat"; fi
    done
    if "$PY" -m pip --version >/dev/null 2>&1; then
        echo "  Weg: pip"
        "$PY" -m pip install --upgrade piper-tts 2>&1 | tail -4
    elif [ -n "$UV" ]; then
        echo "  Weg: uv ($UV), die venv hat kein pip"
        "$UV" pip install --python "$PY" --upgrade piper-tts 2>&1 | tail -6
    elif "$PY" -m ensurepip --upgrade >/dev/null 2>&1; then
        echo "  Weg: ensurepip, danach pip"
        "$PY" -m pip install --upgrade piper-tts 2>&1 | tail -4
    else
        echo "FEHLER: die venv hat weder pip noch ensurepip, und uv wurde nicht gefunden."
        echo "        Meldung an Claude geben."
        exit 4
    fi
    if ! "$PY" -c "import piper" 2>/dev/null; then
        echo "FEHLER: piper-tts laesst sich nicht importieren. Meldung oben an Claude geben."
        "$PY" -c "import piper" 2>&1 | tail -3
        exit 4
    fi
    echo "  piper-tts: $("$PY" -c "import importlib.metadata as m; print(m.version('piper-tts'))" 2>&1)"
    echo "  onnxruntime: $("$PY" -c "import importlib.metadata as m; print(m.version('onnxruntime'))" 2>&1)"

    echo
    echo "2/3 Stimmen bereitstellen ($STIMMEN) ..."
    FEHLT=0
    stimme_holen high || FEHLT=1
    stimme_holen medium || FEHLT=1

    echo
    echo "3/3 Probesatz erzeugen ..."
    cd "$ORDNER/backend" || exit 2
    PIPER_THREADS="${PIPER_THREADS:-2}" "$PY" - <<PYEOF
import os, time
from pathlib import Path
from app import piper_tts
daten = Path(r"$DATEN")
satz = "Guten Abend, Sir. Hier spricht Auron mit der Stimme Piper."
for q in piper_tts.QUALITAETEN:
    os.environ["PIPER_QUALITAET"] = q
    os.environ.pop("PIPER_STIMME", None)
    piper_tts.vergessen()
    problem = piper_tts.problem()
    if problem:
        print(f"  Piper {q}: NICHT BEREIT - {problem}")
        continue
    try:
        start = time.perf_counter()
        wav = piper_tts.sprechen(satz)
        erst = time.perf_counter() - start
        start = time.perf_counter()
        piper_tts.sprechen(satz)
        zweit = time.perf_counter() - start
        ziel = daten / f"piper_probe_{q}.wav"
        ziel.write_bytes(wav)
        print(f"  Piper {q}: OK, {len(wav)//1024} KB, erster Satz {erst:.2f} s (mit Laden), zweiter {zweit:.2f} s -> {ziel.name}")
    except Exception as exc:
        print(f"  Piper {q}: FEHLER - {exc}")
PYEOF
    echo
    echo "Fertig. Hoerproben: data/piper_probe_high.wav und piper_probe_medium.wav (kommen auch auf den PC)."
    echo "Danach JARVIS STARTEN.bat, damit das Backend die Stimme vorlaedt. Dann in den Einstellungen 'Vorlesen ueber' waehlen."
    exit $FEHLT
    ;;
messen)
    cd "$ORDNER/backend" || exit 2
    if [ ! -f stimme_messung.py ]; then echo "FEHLER: backend/stimme_messung.py fehlt - erst REPO HOLEN und JARVIS STARTEN."; exit 3; fi
    echo "Messung laeuft (Fish Audio, Piper high, Piper medium: je 5 Laeufe und 20 Saetze), dauert einige Minuten ..."
    PIPER_THREADS="${PIPER_THREADS:-2}" "$PY" stimme_messung.py --ausgabe "$DATEN/stimme_messung.txt"
    ;;
status)
    "$PY" -c "import piper, importlib.metadata as m; print('piper-tts:', m.version('piper-tts'))" 2>&1 | tail -1
    ls -la "$STIMMEN"/*.onnx "$STIMMEN"/*.onnx.json 2>/dev/null || echo "Keine Stimmen in $STIMMEN"
    ;;
*)
    echo "Unbekannte Aktion: $AKTION (einrichten, messen, status)"
    exit 1
    ;;
esac

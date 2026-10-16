#!/usr/bin/env bash
# gpu_waechter_einrichten.sh - P24 GPU-Miete, Waechter gegen vergessene RunPod-Pods (16.10.2026, Claude Code)
#
# NUR auf dem Mini-PC (Ubuntu) starten, von Sir selbst:
#     sudo bash "1 Starten/gpu_waechter_einrichten.sh"             einrichten
#     sudo bash "1 Starten/gpu_waechter_einrichten.sh" --entfernen wieder abbauen
#
# Was es tut:
#   Ein systemd-Timer startet alle 10 Minuten backend/gpu_waechter.py. Das Programm listet alle Pods
#   im RunPod-Konto und loescht jeden, der zu lange laeuft, nur gestoppt ist oder nicht von Auron stammt.
#   Es braucht RUNPOD_API_KEY in der .env (Jarvis-Ordner). Ohne Schluessel tut es nichts.
# Python: nimmt $JARVIS/venv/bin/python, sonst $JARVIS/.venv/bin/python, sonst python3.
#   Anderes Python: PYTHON=/pfad/zu/python sudo -E bash "1 Starten/gpu_waechter_einrichten.sh"
# Kosten: 0 EUR. Ungetestet auf dem Mini-PC (in der Cloud gibt es kein systemd).

set -euo pipefail

DIENST="auron-gpu-waechter"
UNIT_DIR="/etc/systemd/system"
HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JARVIS="$(dirname "$HIER")"
BACKEND="$JARVIS/backend"

if [ "$(id -u)" -ne 0 ]; then
    echo "Bitte mit sudo starten: sudo bash \"$0\""
    exit 1
fi

if [ "${1:-}" = "--entfernen" ]; then
    systemctl disable --now "$DIENST.timer" 2>/dev/null || true
    rm -f "$UNIT_DIR/$DIENST.service" "$UNIT_DIR/$DIENST.timer"
    systemctl daemon-reload
    echo "Fertig. Der Waechter ist abgebaut."
    exit 0
fi

if [ ! -f "$BACKEND/gpu_waechter.py" ]; then
    echo "FEHLER: $BACKEND/gpu_waechter.py nicht gefunden. Erst REPO HOLEN, dann nochmal starten."
    exit 1
fi

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
    for kandidat in "$JARVIS/venv/bin/python" "$JARVIS/.venv/bin/python" "$(command -v python3 || true)"; do
        if [ -n "$kandidat" ] && [ -x "$kandidat" ]; then PY="$kandidat"; break; fi
    done
fi
if [ -z "$PY" ]; then
    echo "FEHLER: kein Python gefunden. PYTHON=/pfad/zu/python angeben."
    exit 1
fi
# Wem gehoert der Jarvis-Ordner? Als dieser Benutzer laeuft der Waechter (nicht als root).
BENUTZER="$(stat -c '%U' "$JARVIS")"

echo "1/3 Dienst $DIENST anlegen (Python: $PY, Benutzer: $BENUTZER) ..."
cat > "$UNIT_DIR/$DIENST.service" <<UNIT
[Unit]
Description=Auron GPU-Waechter: vergessene RunPod-Pods loeschen (P24)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$BENUTZER
WorkingDirectory=$BACKEND
ExecStart=$PY gpu_waechter.py
TimeoutStartSec=300
UNIT

echo "2/3 Timer anlegen (alle 10 Minuten, erster Lauf 2 Minuten nach dem Start) ..."
cat > "$UNIT_DIR/$DIENST.timer" <<UNIT
[Unit]
Description=Auron GPU-Waechter alle 10 Minuten

[Timer]
OnBootSec=2min
OnUnitActiveSec=10min
AccuracySec=30s

[Install]
WantedBy=timers.target
UNIT

echo "3/3 Timer aktivieren ..."
systemctl daemon-reload
systemctl enable --now "$DIENST.timer"
echo
echo "Fertig. Pruefen:"
echo "  systemctl list-timers $DIENST.timer"
echo "  sudo systemctl start $DIENST.service && journalctl -u $DIENST.service -n 20 --no-pager"

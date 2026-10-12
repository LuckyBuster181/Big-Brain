#!/usr/bin/env bash
# alexa_tunnel_einrichten.sh - P19 Alexa-Skill "frag Auron" (12.10.2026, Claude Code)
#
# NUR auf dem Mini-PC (Ubuntu) starten, von Sir selbst:
#     sudo bash "1 Starten/alexa_tunnel_einrichten.sh"            einrichten
#     sudo bash "1 Starten/alexa_tunnel_einrichten.sh" --entfernen wieder abbauen
#
# Was es tut:
#   Ein ZWEITER Tailscale-Knoten "auron-alexa" (eigener Dienst tailscaled-alexa, eigener
#   Zustand, userspace-networking). Nur dieser Knoten bekommt Funnel (oeffentlich, Port 443)
#   und reicht nur den Pfad /api/alexa an Auron (127.0.0.1:8000) weiter.
#   Der bestehende Knoten "auron" (Handy-Zugang, nur Tailnet) wird NICHT angefasst.
# Kosten: 0 EUR. Ungetestet auf dem Mini-PC (in der Cloud gibt es kein Tailscale).

set -euo pipefail

NAME="auron-alexa"
DIENST="tailscaled-alexa"
ZUSTAND="/var/lib/tailscale-alexa"
SOCKET="/run/tailscale-alexa/tailscaled.sock"
UDP_PORT="41642"
PFAD="/api/alexa"
ZIEL="http://127.0.0.1:8000/api/alexa"
UNIT="/etc/systemd/system/${DIENST}.service"

if [ "$(id -u)" -ne 0 ]; then
    echo "Bitte mit sudo starten: sudo bash \"$0\""
    exit 1
fi

TSD="$(command -v tailscaled || true)"
TS="$(command -v tailscale || true)"
if [ -z "$TSD" ] || [ -z "$TS" ]; then
    echo "FEHLER: tailscale/tailscaled nicht gefunden. Ist Tailscale auf dem Mini-PC installiert?"
    exit 1
fi
ts() { "$TS" --socket="$SOCKET" "$@"; }

if [ "${1:-}" = "--entfernen" ]; then
    echo "Baue den Alexa-Knoten ab ..."
    ts funnel reset 2>/dev/null || true
    ts logout 2>/dev/null || true
    systemctl disable --now "$DIENST" 2>/dev/null || true
    rm -f "$UNIT"
    systemctl daemon-reload
    echo "Fertig. Den Knoten \"$NAME\" bitte zusaetzlich im Tailscale-Adminbereich entfernen (Machines)."
    exit 0
fi

echo "1/4 Dienst $DIENST anlegen ..."
cat > "$UNIT" <<EOF
[Unit]
Description=Tailscale-Knoten ${NAME} (nur Alexa-Skill, P19)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=${TSD} --tun=userspace-networking --statedir=${ZUSTAND} --socket=${SOCKET} --port=${UDP_PORT}
RuntimeDirectory=tailscale-alexa
StateDirectory=tailscale-alexa
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now "$DIENST"
for i in $(seq 1 20); do
    [ -S "$SOCKET" ] && break
    sleep 1
done
if [ ! -S "$SOCKET" ]; then
    echo "FEHLER: Dienst startet nicht. Pruefen mit: journalctl -u $DIENST -n 50"
    exit 1
fi

echo "2/4 Knoten $NAME anmelden (falls ein Link erscheint: im Browser oeffnen, mit Sirs Tailscale-Konto bestaetigen) ..."
ts up --hostname="$NAME"

echo "3/4 Funnel nur fuer $PFAD einschalten ..."
echo "    (Falls Tailscale nach einer Freigabe fragt: Link oeffnen und Funnel fuer den Knoten erlauben.)"
ts funnel --bg --set-path="$PFAD" "$ZIEL"

echo "4/4 Stand:"
ts funnel status || true
ADRESSE="$(ts status --json 2>/dev/null | grep -o '"DNSName": *"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/' | sed 's/\.$//')"
echo
echo "Fertig. Endpunkt fuer die Developer Console:"
echo "    https://${ADRESSE:-auron-alexa.<tailnet>.ts.net}${PFAD}"
echo
echo "Pruefen (Handy im Mobilfunk, Tailscale AUS):"
echo "  - https://${ADRESSE:-auron-alexa...}/          -> darf nichts von Auron zeigen"
echo "  - https://${ADRESSE:-auron-alexa...}/auron     -> darf nichts von Auron zeigen"
echo "Pruefen hier auf dem Mini-PC (ALEXA_AKTIV=1 muss in der .env stehen, Auron neu gestartet):"
echo "    curl -s -X POST https://${ADRESSE:-auron-alexa...}${PFAD}"
echo "  - {\"detail\":\"Bad Request\"}  = richtig (Auron erreicht, Anfrage ohne Amazon-Signatur abgelehnt)"
echo "  - {\"detail\":\"Not Found\"}    = ALEXA_AKTIV fehlt oder der Pfad kommt falsch an -> Claude melden"

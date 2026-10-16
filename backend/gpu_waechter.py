"""
GPU-Wächter (P24, 16.10.2026): Sicherheitsnetz gegen vergessene RunPod-Pods, unabhängig vom Backend.

Aufruf auf dem Mini-PC alle 10 Minuten (systemd-Timer, eingerichtet mit "1 Starten/gpu_waechter_einrichten.sh"):
    python gpu_waechter.py            (im Ordner backend)

Listet ALLE Pods des RunPod-Kontos und löscht jeden, der länger als GPU_MIETE_MAX_STUNDEN (Standard 3) existiert,
nur gestoppt ist oder nicht von Auron gestartet wurde. Der Schlüssel kommt aus der Umgebung/.env (RUNPOD_API_KEY),
wird nie ausgegeben. Ohne Schlüssel tut das Programm nichts.

Rückgabewert: 0 = alles in Ordnung (auch ohne Schlüssel), 1 = Pod konnte nicht gelöscht oder RunPod nicht abgefragt
werden (Alarm ist gesetzt, Auron zeigt Ampel rot). Ungetestet auf dem Mini-PC.
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    from app import gpu_miete

    if not gpu_miete.schluessel_da():
        print("GPU-Wächter: kein RUNPOD_API_KEY, nichts zu tun.")
        return 0
    erg = gpu_miete.waechter_lauf()
    print(f"GPU-Wächter: {erg['geprueft']} Pod(s) geprüft, {len(erg['geloescht'])} gelöscht"
          + (f", Fehler: {'; '.join(erg['fehler'])}" if erg["fehler"] else "."))
    for g in erg["geloescht"]:
        print(f"  gelöscht: {g['name'] or g['id']} ({g['grund']})")
    return 0 if erg["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

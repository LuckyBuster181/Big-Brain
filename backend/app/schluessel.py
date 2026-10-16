"""
API-Schlüssel im HUD (Ausbauplan Phase A, 23.09.2026).

Sicherheitsregeln (Lehre 11 in claude/jarvis-stand.md):
- Ein Schlüssel wird NIE an den Browser zurückgegeben. Das HUD sieht nur
  "gesetzt/fehlt", die Länge und bei langen Geheimnissen die letzten 4 Zeichen.
- Schreiben nur für eine feste Liste bekannter Namen (keine beliebigen
  Variablen wie VAULT_PATH, die Jarvis lahmlegen könnten).
- Schreibweise wie die .bat-Dateien seit dem .env-Fehler vom 22.09.2026: Zeilen
  einlesen, die alte Zeile ersetzen oder sauber anhängen, alles neu schreiben -
  nie blind anhängen. Vorher Sicherung nach data/env_sicherung_hud.txt.
- Die .env behält BOM und Windows-Zeilenenden (CRLF), wie sie sind.
- Nach dem Schreiben gilt der neue Wert sofort für Module, die ihn bei jedem
  Aufruf lesen (z.B. ANTHROPIC_API_KEY). Werte, die beim Start gelesen werden
  (z.B. ANTHROPIC_TOOL_MODEL), brauchen NEUSTART.bat - das Ergebnis sagt es.

Das Backend lauscht nur auf 127.0.0.1 (lokal) - wer den Rechner bedienen kann,
kann auch die .env direkt öffnen, das Schreiben über das HUD ist also kein
zusätzliches Einfallstor von außen.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import namen

# Name -> (Beschreibung, geheim?, Neustart nötig?)
BEKANNTE: dict[str, tuple[str, bool, bool]] = {
    "ANTHROPIC_API_KEY": ("Claude (Anthropic) - Pflicht für alle Antworten", True, False),
    "ANTHROPIC_TOOL_MODEL": ("Günstiges Modell für Sucher/Themen-Zerlegung (z.B. Haiku)", False, True),
    "FISH_API_KEY": ("Fish Audio - Sprachausgabe", True, False),
    "KALENDER_ICS_URL": ("Google-Kalender lesen (geheime iCal-Adresse)", True, False),
    "SPOTIFY_CLIENT_ID": ("Spotify - App-Kennung", False, False),
    "SPOTIFY_CLIENT_SECRET": ("Spotify - App-Geheimnis", True, False),
    "SPOTIFY_REFRESH_TOKEN": ("Spotify - Anmeldung", True, False),
    "GOOGLE_CLIENT_ID": ("Google-Kalender schreiben - App-Kennung", False, False),
    "GOOGLE_CLIENT_SECRET": ("Google-Kalender schreiben - App-Geheimnis", True, False),
    "GOOGLE_CALENDAR_REFRESH_TOKEN": ("Google-Kalender schreiben - Anmeldung", True, False),
}
MAX_LAENGE = 1000


class SchluesselFehler(ValueError):
    pass


def env_pfad() -> Path:
    return Path(namen.env("ENV_PATH") or Path(__file__).resolve().parents[2] / ".env")   # P20: AURON_ENV_PATH vor JARVIS_ENV_PATH


def _sicherung_pfad() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "env_sicherung_hud.txt"


def _anzeige(name: str, wert: str) -> dict:
    beschreibung, geheim, neustart = BEKANNTE[name]
    wert = wert.strip().strip('"').strip("'")
    eintrag = {
        "name": name,
        "beschreibung": beschreibung,
        "gesetzt": bool(wert),
        "laenge": len(wert),
        "geheim": geheim,
        "neustart_noetig": neustart,
        "ende": None,
    }
    if wert and not geheim:
        eintrag["ende"] = wert  # z.B. Modellname - kein Geheimnis
    elif wert and len(wert) >= 20:
        eintrag["ende"] = "…" + wert[-4:]
    return eintrag


def status() -> list[dict]:
    """Stand aller bekannten Schlüssel - ohne Geheimnisse preiszugeben."""
    return [_anzeige(name, os.getenv(name, "")) for name in BEKANNTE]


def setzen(name: str, wert: str) -> dict:
    """Schreibt einen bekannten Schlüssel sicher in die .env und in os.environ."""
    name = (name or "").strip()
    if name not in BEKANNTE:
        raise SchluesselFehler(f"Unbekannter Schlüssel \"{name}\" - erlaubt: {', '.join(BEKANNTE)}")
    wert = (wert or "").strip()
    if not wert:
        raise SchluesselFehler("Leerer Wert - zum Entfernen bitte die .env von Hand bearbeiten.")
    if "\n" in wert or "\r" in wert:
        raise SchluesselFehler("Der Wert darf keinen Zeilenumbruch enthalten.")
    if len(wert) > MAX_LAENGE:
        raise SchluesselFehler(f"Wert zu lang (höchstens {MAX_LAENGE} Zeichen).")
    if wert.startswith(f"{name}="):
        wert = wert[len(name) + 1:].strip()  # ganze Zeile eingefügt

    pfad = env_pfad()
    roh = pfad.read_bytes() if pfad.exists() else b""
    bom = roh.startswith(b"\xef\xbb\xbf")
    text = roh.decode("utf-8-sig") if roh else ""
    zeilenende = "\r\n" if "\r\n" in text or not text else "\n"

    if pfad.exists():
        sicherung = _sicherung_pfad()
        sicherung.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pfad, sicherung)

    zeilen = text.splitlines()
    neue_zeile = f"{name}={wert}"
    ersetzt = False
    ergebnis = []
    for zeile in zeilen:
        if zeile.split("=", 1)[0].strip() == name and not zeile.lstrip().startswith("#"):
            if not ersetzt:
                ergebnis.append(neue_zeile)
                ersetzt = True
            continue  # doppelte alte Zeilen fallen weg
        ergebnis.append(zeile)
    if not ersetzt:
        ergebnis.append(neue_zeile)

    inhalt = zeilenende.join(ergebnis) + zeilenende
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes((b"\xef\xbb\xbf" if bom else b"") + inhalt.encode("utf-8"))
    os.environ[name] = wert
    return _anzeige(name, wert)

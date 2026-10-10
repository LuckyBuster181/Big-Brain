"""
Sicherheitscheck für Jarvis (03.10.2026, Idee aus OZ CORE "Security Audit", für unser System umgesetzt).

Prüft NUR LESEND, ob Zugangsdaten offen herumliegen. Es wird nichts verändert, nichts
gesendet und kein Geheimnis im Bericht angezeigt: der Bericht nennt Datei, Zeile und
Namen der Einstellung, nie den Wert.

Prüfungen:
1. .gitignore schützt .env und data/ (sonst landen Schlüssel im Git).
2. Klartext-Zugangsdaten außerhalb der .env (Skripte, Notizen, Textdateien im Projektordner).
3. Zugangs-Sicherungen im Klartext (env_sicherung*, laptop_daten ...).
4. Kurze Schlüssel in der .env (unter 16 Zeichen: leicht zu erraten, z. B. VNC-Kennwörter).
5. Dienste, die auf allen Netzwerkkarten lauschen (0.0.0.0).
6. Linux: .env für andere Benutzer lesbar.

Start:  python -m app.sicherheitscheck          (Bericht: data/sicherheitscheck_bericht.txt)
Auf dem Haupt-PC: 2 Testen und Pruefen\\SICHERHEIT_PRUEFEN.bat
"""

from __future__ import annotations

import datetime
import os
import re
import sys
from pathlib import Path
from typing import Any

PROJEKT = Path(__file__).resolve().parents[2]
TEXT_ENDUNGEN = {".py", ".bat", ".ps1", ".sh", ".md", ".txt", ".json", ".html", ".service", ".cfg", ".ini", ".yml", ".yaml"}
AUSGELASSEN = {".git", "venv", ".venv", "node_modules", "__pycache__", "vector_db", "tiktok", "novnc", ".stfolder",
               "ablage", "pc_agent_windows_build", "tiktok_test"}
MAX_DATEI = 1_000_000
MAX_FUNDE = 40
KURZ_UNTER = 16

# Name der Einstellung, die nach einem Geheimnis aussieht
_NAME = r"[A-Za-z0-9_]*(?:API[_-]?KEY|TOKEN|PASSWORT|PASSWORD|SECRET|ZUGANG|VNC|APP_PASSWORT)[A-Za-z0-9_]*"
_ZUWEISUNG_RE = re.compile(rf"(?P<name>{_NAME})\s*[=:]\s*[\"']?(?P<wert>[A-Za-z0-9_\-./+]{{12,}})", re.IGNORECASE)
_SCHLUESSEL_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}")
_PLATZHALTER = ("xxx", "dein", "beispiel", "example", "your", "changeme", "platzhalter", "hier", "<", "...", "none", "null")
_KEIN_WERT_PRAEFIX = ("os.", "getenv", "environ", "%", "$", "{", "str(", "get_", "env.", "self.")
_KEIN_GEHEIMNIS_NAME = ("tokens", "tokenizer", "bereit", "max_token")
SICHERUNGS_NAMEN = ("env_sicherung", "laptop_daten", "agent.env", "passwoerter", "passwords")


def alle_dateien(wurzel: Path):
    """Alle Dateien unter wurzel, ohne die großen/irrelevanten Ordner (werden gar nicht betreten)."""
    for ordner, unterordner, namen in os.walk(wurzel):
        unterordner[:] = [d for d in unterordner if d not in AUSGELASSEN]
        for name in namen:
            yield Path(ordner) / name


def _ist_platzhalter(wert: str) -> bool:
    w = wert.lower()
    return any(p in w for p in _PLATZHALTER) or w.startswith(_KEIN_WERT_PRAEFIX)


def _sieht_nach_geheimnis_aus(name: str, wert: str) -> bool:
    """Zählernamen (max_tokens ...) und Wörter ohne Ziffer (Variablennamen, Beispieltext) sind kein Geheimnis."""
    if any(k in name.lower() for k in _KEIN_GEHEIMNIS_NAME):
        return False
    return any(c.isdigit() for c in wert) and any(c.isalpha() for c in wert)


def dateien(wurzel: Path) -> list[Path]:
    ergebnis = []
    for pfad in alle_dateien(wurzel):
        try:
            if pfad.name == ".env" or pfad.suffix.lower() in TEXT_ENDUNGEN:
                if pfad.stat().st_size <= MAX_DATEI:
                    ergebnis.append(pfad)
        except OSError:
            continue
    return ergebnis


def pruefen_gitignore(wurzel: Path) -> list[dict]:
    funde = []
    pfad = wurzel / ".gitignore"
    try:
        zeilen = {z.strip() for z in pfad.read_text(encoding="utf-8", errors="replace").splitlines()}
    except OSError:
        return [{"stufe": "rot", "text": ".gitignore fehlt: .env könnte ins Git geraten."}]
    for muss in (".env", "data/"):
        if muss not in zeilen:
            funde.append({"stufe": "rot", "text": f".gitignore enthält '{muss}' nicht."})
    return funde


def pruefen_klartext(wurzel: Path) -> list[dict]:
    funde: list[dict] = []
    for pfad in dateien(wurzel):
        if pfad.name == ".env":
            continue
        rel = pfad.relative_to(wurzel)
        try:
            zeilen = pfad.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for nr, zeile in enumerate(zeilen, 1):
            if _SCHLUESSEL_RE.search(zeile):
                funde.append({"stufe": "rot", "text": f"{rel}, Zeile {nr}: Anthropic-Schlüssel im Klartext."})
            else:
                m = _ZUWEISUNG_RE.search(zeile)
                if m and not _ist_platzhalter(m.group("wert")) and _sieht_nach_geheimnis_aus(m.group("name"), m.group("wert")):
                    funde.append({"stufe": "gelb", "text": f"{rel}, Zeile {nr}: Wert für {m.group('name')} im Klartext."})
            if len(funde) >= MAX_FUNDE:
                funde.append({"stufe": "gelb", "text": f"Weitere Funde nicht aufgelistet (Grenze {MAX_FUNDE})."})
                return funde
    return funde


def pruefen_sicherungen(wurzel: Path) -> list[dict]:
    funde = []
    for pfad in alle_dateien(wurzel):
        if any(n in pfad.name.lower() for n in SICHERUNGS_NAMEN):
            funde.append({"stufe": "gelb", "text": f"{pfad.relative_to(wurzel)}: Sicherung von Zugangsdaten im Klartext. "
                                                   "Auf Geräten außerhalb Ihres Netzes nicht zulassen."})
    return funde


def env_werte(wurzel: Path) -> dict[str, str]:
    werte: dict[str, str] = {}
    try:
        for zeile in (wurzel / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in zeile and not zeile.lstrip().startswith("#"):
                name, wert = zeile.split("=", 1)
                werte[name.strip()] = wert.strip().strip("\"'")
    except OSError:
        pass
    return werte


def pruefen_kurze_schluessel(wurzel: Path) -> list[dict]:
    funde = []
    for name, wert in env_werte(wurzel).items():
        if re.search(r"TOKEN|KEY|PASSW|SECRET|ZUGANG|VNC", name, re.IGNORECASE) and 0 < len(wert) < KURZ_UNTER:
            if name.upper().endswith(("_URL", "_PORT", "_ID")):
                continue
            funde.append({"stufe": "gelb", "text": f".env: {name} ist nur {len(wert)} Zeichen lang. Länger und zufällig wählen."})
    return funde


def pruefen_lauschen(wurzel: Path) -> list[dict]:
    funde = []
    for pfad in dateien(wurzel):
        if pfad.suffix.lower() not in {".bat", ".sh", ".service", ".ps1", ".py"}:
            continue
        try:
            for nr, zeile in enumerate(pfad.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if re.search(r"--host\s+0\.0\.0\.0|OLLAMA_HOST\s*=\s*0\.0\.0\.0|host\s*=\s*[\"']0\.0\.0\.0", zeile):
                    funde.append({"stufe": "info", "text": f"{pfad.relative_to(wurzel)}, Zeile {nr}: lauscht auf allen Netzwerkkarten. "
                                                           "Nur im Heimnetz ok, Router darf den Port nicht freigeben."})
        except OSError:
            continue
    return funde


def pruefen_rechte(wurzel: Path) -> list[dict]:
    env = wurzel / ".env"
    if os.name == "nt" or not env.exists():
        return []
    if env.stat().st_mode & 0o077:
        return [{"stufe": "rot", "text": ".env ist für andere Benutzer lesbar. Mit chmod 600 beschränken."}]
    return []


def pruefen(wurzel: Path | None = None) -> dict[str, Any]:
    wurzel = Path(wurzel) if wurzel else PROJEKT
    funde = [
        *pruefen_gitignore(wurzel),
        *pruefen_klartext(wurzel),
        *pruefen_sicherungen(wurzel),
        *pruefen_kurze_schluessel(wurzel),
        *pruefen_lauschen(wurzel),
        *pruefen_rechte(wurzel),
    ]
    rang = {"rot": 0, "gelb": 1, "info": 2}
    funde.sort(key=lambda f: rang.get(f["stufe"], 3))
    ampel = "rot" if any(f["stufe"] == "rot" for f in funde) else ("gelb" if any(f["stufe"] == "gelb" for f in funde) else "gruen")
    return {"zeit": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "ampel": ampel, "funde": funde,
            "geprueft": len(dateien(wurzel))}


def bericht_text(ergebnis: dict[str, Any]) -> str:
    zeilen = [f"Sicherheitscheck {ergebnis['zeit']}", f"Ampel: {ergebnis['ampel'].upper()} ({ergebnis['geprueft']} Dateien geprüft, nur lesend)", ""]
    if not ergebnis["funde"]:
        zeilen.append("Keine Auffälligkeiten.")
    for f in ergebnis["funde"]:
        zeilen.append(f"[{f['stufe'].upper()}] {f['text']}")
    zeilen += ["", "Der Bericht zeigt nie den Wert eines Schlüssels, nur Datei, Zeile und Name."]
    return "\n".join(zeilen) + "\n"


def main() -> int:
    ergebnis = pruefen()
    text = bericht_text(ergebnis)
    ziel = Path(os.getenv("SICHERHEITSCHECK_PATH") or PROJEKT / "data" / "sicherheitscheck_bericht.txt")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

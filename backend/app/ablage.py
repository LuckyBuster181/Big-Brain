"""
Datei-Ablage (Ausbauplan Phase A, 23.09.2026): ein fester Ordner, in den Sir
über das HUD Dateien legen kann (Standard: Jarvis/data/ablage, per .env
ABLAGE_PATH änderbar).

Bewusst einfach und ohne Zusatzpaket: der Upload kommt als roher Inhalt im
Anfrage-Körper, der Dateiname als Parameter. (FastAPIs UploadFile bräuchte
python-multipart - das ist nicht installiert.)

Schutzregeln:
- Nur ein reiner Dateiname, keine Pfade ("..\\" usw. werden entfernt).
- Keine ausführbaren Dateien (.exe, .bat, .ps1 ...) - die Ablage soll kein
  Umweg sein, um Programme auf den Rechner zu bringen.
- Größengrenze (Standard 50 MB).
- Nichts wird überschrieben: gleicher Name bekommt " (2)", " (3)" ...
- Löschen gibt es hier nicht (wie im ganzen Projekt: nichts ungefragt löschen).

Noch NICHT gebaut: Dateien aus der Ablage automatisch in den Vault oder die
Suche übernehmen - das ist ein eigener Schritt (erst sehen, was Sir ablegt).
"""

from __future__ import annotations

import datetime
import os
import re
from pathlib import Path

MAX_BYTES = int(float(os.getenv("ABLAGE_MAX_MB", "50")) * 1024 * 1024)
GESPERRT = {
    ".exe", ".bat", ".cmd", ".com", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf",
    ".msi", ".scr", ".dll", ".lnk", ".reg", ".hta", ".jar", ".sh",
}
_UNERLAUBT_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class AblageFehler(ValueError):
    pass


def ordner() -> Path:
    pfad = Path(os.getenv("ABLAGE_PATH") or Path(__file__).resolve().parents[2] / "data" / "ablage")
    pfad.mkdir(parents=True, exist_ok=True)
    return pfad


def sicherer_name(name: str) -> str:
    """Nur der letzte Teil eines Pfads, ohne Windows-verbotene Zeichen."""
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = _UNERLAUBT_RE.sub("_", name).strip().strip(".")
    if not name:
        raise AblageFehler("Kein gültiger Dateiname.")
    if Path(name).suffix.lower() in GESPERRT:
        raise AblageFehler(f"Dateityp {Path(name).suffix} ist in der Ablage gesperrt (ausführbar).")
    return name[:150]


def speichern(name: str, inhalt: bytes) -> dict:
    name = sicherer_name(name)
    if not inhalt:
        raise AblageFehler("Die Datei ist leer.")
    if len(inhalt) > MAX_BYTES:
        raise AblageFehler(f"Datei zu groß (höchstens {MAX_BYTES // (1024 * 1024)} MB).")
    ziel = ordner() / name
    zaehler = 2
    while ziel.exists():
        ziel = ordner() / f"{Path(name).stem} ({zaehler}){Path(name).suffix}"
        zaehler += 1
    ziel.write_bytes(inhalt)
    return _info(ziel)


def _info(pfad: Path) -> dict:
    st = pfad.stat()
    return {
        "name": pfad.name,
        "bytes": st.st_size,
        "geaendert": datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        "typ": pfad.suffix.lower().lstrip(".") or "datei",
    }


def liste() -> list[dict]:
    dateien = [p for p in ordner().iterdir() if p.is_file()]
    return sorted((_info(p) for p in dateien), key=lambda d: d["geaendert"], reverse=True)


def pfad_fuer(name: str) -> Path:
    """Pfad einer vorhandenen Datei in der Ablage (für den Download)."""
    ziel = ordner() / sicherer_name(name)
    if not ziel.is_file():
        raise FileNotFoundError(name)
    return ziel

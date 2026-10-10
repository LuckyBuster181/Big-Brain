"""
Offline-Stimme mit Piper (Phase 3.2, 23.09.2026) - OPTIONAL.

Warum: Fish Audio ist nur bis 30.11.2026 kostenlos und schickt den Text an
fremde Server. Die Windows-Stimmen klingen blechern. Piper läuft komplett auf
dem PC, braucht wenig Rechenleistung und hat gute deutsche Stimmen
(Standard: "thorsten", Qualität "high").

Einrichten: PIPER_EINRICHTEN.bat (lädt piper.exe und die Stimme nach
Jarvis\\tools\\piper, ca. 130 MB). Danach im HUD "Vorlesen über: Piper".
Ungetestet am PC (in der Cloud gibt es kein Windows-Piper).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[2]
STANDARD_ORDNER = WURZEL / "tools" / "piper"
MAX_ZEICHEN = 2000


class PiperFehler(RuntimeError):
    pass


def exe() -> Path:
    roh = os.getenv("PIPER_PFAD")
    if roh:
        return Path(roh)
    for kandidat in (STANDARD_ORDNER / "piper" / "piper.exe", STANDARD_ORDNER / "piper.exe", STANDARD_ORDNER / "piper" / "piper"):
        if kandidat.is_file():
            return kandidat
    return STANDARD_ORDNER / "piper" / "piper.exe"


def stimme() -> Path:
    roh = os.getenv("PIPER_STIMME")
    if roh:
        return Path(roh)
    treffer = sorted(STANDARD_ORDNER.glob("*.onnx"))
    return treffer[0] if treffer else STANDARD_ORDNER / "de_DE-thorsten-high.onnx"


def verfuegbar() -> bool:
    return exe().is_file() and stimme().is_file()


def stand() -> dict:
    return {"verfuegbar": verfuegbar(), "stimme": stimme().stem,
            "hinweis": "Piper bereit - nichts verlässt den PC." if verfuegbar()
            else "Piper nicht eingerichtet - PIPER_EINRICHTEN.bat starten."}


def sprechen(text: str, tempo: float = 1.0, ausfuehren=subprocess.run) -> bytes:
    """Text -> WAV-Bytes."""
    text = (text or "").strip()[:MAX_ZEICHEN]
    if not text:
        raise PiperFehler("Kein Text.")
    if not verfuegbar():
        raise PiperFehler("Piper ist nicht eingerichtet (PIPER_EINRICHTEN.bat).")
    laenge = max(0.5, min(2.0, 1 / max(0.5, float(tempo or 1))))
    with tempfile.TemporaryDirectory() as tmp:
        ziel = Path(tmp) / "sprache.wav"
        extra = {"creationflags": 0x08000000} if os.name == "nt" else {}  # CREATE_NO_WINDOW
        ergebnis = ausfuehren(
            [str(exe()), "--model", str(stimme()), "--output_file", str(ziel), "--length_scale", f"{laenge:.2f}"],
            input=text.encode("utf-8"), capture_output=True, timeout=60, **extra,
        )
        if getattr(ergebnis, "returncode", 1) != 0 or not ziel.is_file():
            fehler = (getattr(ergebnis, "stderr", b"") or b"").decode("utf-8", errors="replace")[-300:]
            raise PiperFehler(f"Piper-Fehler: {fehler or 'keine Ausgabe'}")
        return ziel.read_bytes()

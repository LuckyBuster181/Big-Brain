"""
Spracherkennung lokal mit Whisper (Phase 3.3, 23.09.2026) - OPTIONAL.

Bisher erkennt der Browser (Chrome/Edge) die Sprache - das Audio geht dabei
an Google bzw. Microsoft. Mit dieser Option bleibt das Audio auf dem PC:
Das HUD nimmt die Frage auf (bis ca. 15 Sekunden) und schickt sie an
/api/sprache/erkennen; faster-whisper macht daraus Text.

Einschalten (Wunsch von Sir, 23.09.2026: "ja, als Option"):
1. Windows: WHISPER_EINRICHTEN.bat. Mini-PC (Ubuntu, P04 16.10.2026):
   1 Starten\\WHISPER MINI-PC.bat (installiert faster-whisper per ssh in die
   venv, lädt das Modell, startet den Dienst neu, schreibt eine Logdatei).
2. Im HUD unter Einstellungen > Sprache "Spracherkennung: lokal (Whisper)"
   oder im .bat "lokal einschalten". Auron (auron.html) nimmt dann für den
   Mikrofon-Knopf Whisper; das Weckwort bleibt beim Browser.
Standard bleibt der Browser.

Linux (P04): läuft unverändert - Aufnahme in einen Temp-Ordner, Threads über
WHISPER_THREADS, das Modell lädt faster-whisper beim ersten Mal von
HuggingFace in den Cache des Benutzers (~/.cache/huggingface) oder nach
WHISPER_MODELLORDNER. Standardmodell seit P04 "base" (der Mini-PC, i5 der
4. Generation, ist langsam); "small" ist wählbar (WHISPER_MODELL).

PC-Last: gedrosselt auf WHISPER_THREADS (Standard 2) und nie zwei Erkennungen
gleichzeitig (Sperre). "small" versteht Deutsch besser, "base" ist etwa
doppelt so schnell. Messung: backend/whisper_messung.py (über das .bat).

Das Weckwort ("Immer ansprechbar") bleibt beim Browser - dauerhaftes Mithören
mit Whisper wäre für den PC zu viel Last.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

MAX_BYTES = 10_000_000
ENDUNGEN = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/wav": ".wav", "audio/x-wav": ".wav",
            "audio/mpeg": ".mp3", "audio/mp4": ".m4a"}
_modell_lock = threading.Lock()
_lauf_lock = threading.Lock()
_modell: Any = None
_modell_name: str | None = None


class SttFehler(RuntimeError):
    pass


def modus() -> str:
    m = (os.getenv("STT_MODUS") or "browser").strip().lower()
    return m if m in ("browser", "lokal") else "browser"


STANDARD_MODELL = "base"  # P04 (16.10.2026): vorher "small"; der Mini-PC ist für "small" zu langsam


def modell_name() -> str:
    return (os.getenv("WHISPER_MODELL") or STANDARD_MODELL).strip() or STANDARD_MODELL


def modell_ordner() -> str | None:
    """Eigener Ordner für die Modelle (sonst der HuggingFace-Cache des Benutzers)."""
    return (os.getenv("WHISPER_MODELLORDNER") or "").strip() or None


def einrichtung() -> str:
    return "WHISPER_EINRICHTEN.bat" if os.name == "nt" else "1 Starten\\WHISPER MINI-PC.bat"


def threads() -> int:
    try:
        return max(1, min(8, int(os.getenv("WHISPER_THREADS") or os.getenv("EMBEDDING_THREADS") or "2")))
    except ValueError:
        return 2


def installiert() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 - ImportError oder kaputte Installation
        return False


def stand() -> dict:
    ok = installiert()
    return {
        "modus": modus(), "installiert": ok, "modell": modell_name(), "threads": threads(),
        "geladen": _modell is not None, "bereit": ok and modus() == "lokal",
        "hinweis": ("Lokale Erkennung bereit - das Audio verlässt den PC nicht." if ok else
                    f"faster-whisper ist nicht installiert - {einrichtung()} starten. "
                    "Bis dahin erkennt der Browser die Sprache."),
    }


def _laden(lader: Any = None):
    global _modell, _modell_name
    with _modell_lock:
        if _modell is not None and _modell_name == modell_name():
            return _modell
        if lader is None:
            try:
                from faster_whisper import WhisperModel
            except Exception as exc:  # noqa: BLE001
                raise SttFehler(f"faster-whisper ist nicht installiert ({einrichtung()}).") from exc
            lader = WhisperModel
        extra = {"download_root": modell_ordner()} if modell_ordner() else {}
        _modell = lader(modell_name(), device="cpu", compute_type="int8", cpu_threads=threads(), **extra)
        _modell_name = modell_name()
        return _modell


def vorladen(lader: Any = None) -> float:
    """Modell laden (beim ersten Mal auch herunterladen). Gibt die Sekunden zurück."""
    start = time.time()
    _laden(lader)
    return round(time.time() - start, 2)


def erkennen(audio: bytes, typ: str = "audio/webm", lader: Any = None) -> dict:
    """Audio (webm/ogg/wav) -> Text. Blockiert; läuft in der Route im Thread-Pool."""
    if not audio:
        raise SttFehler("Keine Aufnahme erhalten.")
    if len(audio) > MAX_BYTES:
        raise SttFehler("Aufnahme zu groß (höchstens ca. 1 Minute).")
    endung = ENDUNGEN.get((typ or "").split(";")[0].strip().lower(), ".webm")
    if not _lauf_lock.acquire(timeout=30):
        raise SttFehler("Die Spracherkennung ist gerade beschäftigt - bitte gleich noch einmal.")
    try:
        modell = _laden(lader)
        start = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / f"aufnahme{endung}"
            pfad.write_bytes(audio)
            try:
                segmente, info = modell.transcribe(str(pfad), language="de", beam_size=1, vad_filter=True)
                text = " ".join(s.text.strip() for s in segmente).strip()
            except TypeError as exc:
                if "metadata_errors" in str(exc):   # Befund 16.10.2026: faster-whisper 1.2.1 läuft nicht mit av 19
                    raise SttFehler(f"Das Paket av ist zu neu für faster-whisper (braucht av<19) - {einrichtung()} erneut starten.") from exc
                raise
        return {"text": text, "dauer_s": round(time.time() - start, 2), "modell": modell_name(),
                "audio_s": round(getattr(info, "duration", 0) or 0, 1)}
    finally:
        _lauf_lock.release()

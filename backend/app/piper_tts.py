"""
Offline-Stimme mit Piper (Phase 3.2, 23.09.2026; Linux-Weg P05, 16.10.2026).

Warum: Fish Audio ist nur bis 30.11.2026 kostenlos und schickt den Text an
fremde Server. Die Windows-Stimmen klingen blechern. Piper läuft komplett auf
dem eigenen Rechner, braucht wenig Rechenleistung und hat gute deutsche
Stimmen (thorsten, Qualität "high" oder "medium").

Zwei Wege, je nach Betriebssystem:
- Windows: bisheriger Weg, piper.exe wird je Satz gestartet
  (PIPER_EINRICHTEN.bat lädt piper.exe und die Stimme nach Jarvis\\tools\\piper).
- Linux (Mini-PC): Python-Paket piper-tts in der venv. Die Stimme wird EINMAL
  geladen und bleibt im Speicher (kein Programmstart je Satz). Grund: die
  piper.exe aus tools/piper kommt per Syncthing vom Windows-PC und läuft auf
  Linux nicht ("Exec format error", Messung 10.10.2026).
  Einrichten: 1 Starten\\PIPER MINI-PC.bat.

Stimmen (.onnx + .onnx.json) liegen in tools/piper und gelten für beide Wege.
Einstellungen: PIPER_QUALITAET (high oder medium, Standard high), PIPER_STIMME
(voller Pfad zu einer .onnx, schlägt alles andere), PIPER_THREADS (Linux,
Standard 2, damit der Mini-PC nicht ausgelastet wird).
"""

from __future__ import annotations

import importlib
import importlib.util
import io
import os
import subprocess
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any, Callable

WURZEL = Path(__file__).resolve().parents[2]
STANDARD_ORDNER = WURZEL / "tools" / "piper"
MAX_ZEICHEN = 2000
QUALITAETEN = ("high", "medium")

_stimmen: dict[str, Any] = {}      # geladene Stimmen, Schlüssel = Pfad der .onnx
_lade_lock = threading.Lock()      # Stimme wird nur einmal geladen
_sprech_lock = threading.Lock()    # eine Synthese zur Zeit (Mini-PC schonen, espeak ist nicht thread-fest)


class PiperFehler(RuntimeError):
    pass


def _windows() -> bool:
    return os.name == "nt"


def weg() -> str:
    """"exe" (Windows) oder "paket" (Linux, Python-Paket piper-tts)."""
    return "exe" if _windows() else "paket"


def paket_da() -> bool:
    try:
        importlib.invalidate_caches()   # Paket kann nach dem Start der App nachinstalliert worden sein
        return importlib.util.find_spec("piper") is not None
    except (ImportError, ValueError):
        return False


def threads() -> int:
    try:
        return max(1, min(8, int(os.getenv("PIPER_THREADS") or os.getenv("EMBEDDING_THREADS") or "2")))
    except ValueError:
        return 2


def exe() -> Path:
    roh = os.getenv("PIPER_PFAD")
    if roh:
        return Path(roh)
    for kandidat in (STANDARD_ORDNER / "piper" / "piper.exe", STANDARD_ORDNER / "piper.exe", STANDARD_ORDNER / "piper" / "piper"):
        if kandidat.is_file():
            return kandidat
    return STANDARD_ORDNER / "piper" / "piper.exe"


def qualitaet() -> str:
    q = (os.getenv("PIPER_QUALITAET") or "high").strip().lower()
    return q if q in QUALITAETEN else "high"


def stimme() -> Path:
    """Stimmendatei (.onnx): PIPER_STIMME, sonst thorsten in der gewählten Qualität,
    sonst die erste .onnx in tools/piper."""
    roh = os.getenv("PIPER_STIMME")
    if roh:
        return Path(roh)
    gewuenscht = STANDARD_ORDNER / f"de_DE-thorsten-{qualitaet()}.onnx"
    if gewuenscht.is_file():
        return gewuenscht
    treffer = sorted(STANDARD_ORDNER.glob("*.onnx"))
    return treffer[0] if treffer else gewuenscht


def stimme_config(modell: Path | None = None) -> Path:
    modell = modell or stimme()
    return modell.with_name(modell.name + ".json")


def problem() -> str | None:
    """None, wenn alles bereit ist, sonst ein Satz für Sir, was fehlt."""
    modell = stimme()
    if _windows():
        if not exe().is_file():
            return "piper.exe nicht gefunden - PIPER_EINRICHTEN.bat starten."
    elif not paket_da():
        return "Das Python-Paket piper-tts fehlt in der venv des Mini-PCs - 1 Starten\\PIPER MINI-PC.bat starten."
    if not modell.is_file():
        return f"Keine Piper-Stimme gefunden ({modell.name}) - {'PIPER_EINRICHTEN.bat' if _windows() else 'PIPER MINI-PC.bat'} starten."
    if not stimme_config(modell).is_file():
        return (f"Zur Stimme {modell.name} fehlt die Datei {modell.name}.json. "
                "Beide Dateien gehören zusammen und müssen im selben Ordner liegen.")
    return None


def verfuegbar() -> bool:
    return problem() is None


def geladen() -> bool:
    return str(stimme()) in _stimmen


def stand() -> dict:
    fehler = problem()
    return {"verfuegbar": fehler is None, "weg": weg(), "stimme": stimme().stem, "qualitaet": qualitaet(),
            "geladen": geladen(),
            "hinweis": "Piper bereit - nichts verlässt den Rechner." if fehler is None else fehler}


# ------------------------------------------------------------------ Linux: Python-Paket


def _paket_laden(modell: Path, config: Path) -> Any:
    """Stimme laden. Eigene Sitzung mit begrenzten Threads; klappt das nicht (anderes
    piper-tts), der normale Weg PiperVoice.load."""
    from piper import PiperVoice

    try:
        import json

        import onnxruntime
        from piper.config import PiperConfig
        from piper.voice import ESPEAK_DATA_DIR

        optionen = onnxruntime.SessionOptions()
        optionen.intra_op_num_threads = threads()
        optionen.inter_op_num_threads = 1
        sitzung = onnxruntime.InferenceSession(str(modell), sess_options=optionen, providers=["CPUExecutionProvider"])
        config_dict = json.loads(config.read_text(encoding="utf-8"))
        return PiperVoice(config=PiperConfig.from_dict(config_dict), session=sitzung,
                          espeak_data_dir=Path(ESPEAK_DATA_DIR), download_dir=Path.cwd())
    except Exception:  # noqa: BLE001 - Rückfall auf den offiziellen Weg
        return PiperVoice.load(str(modell), config_path=str(config))


def stimme_laden(modell: Path | None = None, lader: Callable[[Path, Path], Any] | None = None) -> Any:
    """Die Stimme aus dem Speicher; geladen wird nur beim ersten Mal."""
    modell = modell or stimme()
    schluessel = str(modell)
    if schluessel in _stimmen:
        return _stimmen[schluessel]
    with _lade_lock:
        if schluessel not in _stimmen:
            _stimmen[schluessel] = (lader or _paket_laden)(modell, stimme_config(modell))
    return _stimmen[schluessel]


def vergessen() -> None:
    """Geladene Stimmen aus dem Speicher nehmen (Tests, Stimmenwechsel)."""
    with _lade_lock:
        _stimmen.clear()


def vorwaermen() -> bool:
    """Stimme schon vor dem ersten Satz laden (dauert auf dem Mini-PC einige Sekunden).
    Gibt zurück, ob sie jetzt geladen ist."""
    if _windows() or problem():
        return False
    try:
        stimme_laden()
    except Exception:  # noqa: BLE001 - der erste echte Satz meldet den Fehler
        return False
    return True


def vorwaermen_starten() -> None:
    threading.Thread(target=vorwaermen, name="piper-vorwaermen", daemon=True).start()


def _syn_config(laenge: float) -> Any:
    try:
        from piper.config import SynthesisConfig
    except ImportError:
        return None
    return SynthesisConfig(length_scale=laenge)


def _sprechen_paket(text: str, laenge: float, lader: Callable[[Path, Path], Any] | None = None) -> bytes:
    try:
        voice = stimme_laden(lader=lader)
        puffer = io.BytesIO()
        with _sprech_lock, wave.open(puffer, "wb") as wav:
            if hasattr(voice, "synthesize_wav"):
                voice.synthesize_wav(text, wav, syn_config=_syn_config(laenge))
            else:  # ältere piper-tts-Pakete
                voice.synthesize(text, wav, length_scale=laenge)
        daten = puffer.getvalue()
    except PiperFehler:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PiperFehler(f"Piper-Fehler: {exc}"[:300]) from exc
    if len(daten) < 100:
        raise PiperFehler("Piper-Fehler: keine Ausgabe")
    return daten


# ------------------------------------------------------------------ Windows: piper.exe


def _sprechen_exe(text: str, laenge: float, ausfuehren=subprocess.run) -> bytes:
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


def sprechen(text: str, tempo: float = 1.0, ausfuehren=subprocess.run, lader: Callable[[Path, Path], Any] | None = None) -> bytes:
    """Text -> WAV-Bytes. Windows: piper.exe, Linux: Python-Paket (Stimme bleibt geladen)."""
    text = (text or "").strip()[:MAX_ZEICHEN]
    if not text:
        raise PiperFehler("Kein Text.")
    fehler = problem()
    if fehler:
        raise PiperFehler(fehler)
    laenge = max(0.5, min(2.0, 1 / max(0.5, float(tempo or 1))))
    if _windows():
        return _sprechen_exe(text, laenge, ausfuehren)
    return _sprechen_paket(text, laenge, lader)

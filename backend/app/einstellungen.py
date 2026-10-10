"""
Einstellungen, die sich im HUD ändern lassen (data/einstellungen.json).

Die .env bleibt unangetastet - dort steht der API-Schlüssel. Werte aus dieser
Datei überschreiben beim Start die Umgebungsvariablen, solange sie gesetzt sind.
So lassen sich Vault-Ordner, Antwortmodus und Modell aus der Oberfläche ändern,
ohne eine Datei von Hand zu bearbeiten.

Änderungen wirken erst nach einem Neustart des Backends - außer dem Modus, der
bei jeder Anfrage neu gelesen wird.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "einstellungen.json"

# Erlaubte Schlüssel: Name in der Datei -> Umgebungsvariable
FELDER: dict[str, str] = {
    "vault_pfad": "VAULT_PATH",
    "chat_modus": "CHAT_MODE",
    # 03.10.2026: "ollama" = Chat und Alltagsfunktionen lokal, "claude" = wie bisher
    "ki_anbieter": "LLM_PROVIDER",
    "embedding_modell": "EMBEDDING_MODEL",
    "antwort_modell": "ANTHROPIC_MODEL",
    "einlesen_beim_start": "AUTO_REINDEX_ON_START",
    "vault_ueberwachen": "AUTO_REINDEX_WATCH",
    "wissensluecken_merken": "WISSENSLUECKEN_LOG",
    "fish_modell": "FISH_MODEL",
    "fish_stimme": "FISH_VOICE_ID",
    # Phase 3 (23.09.2026): Spracherkennung "browser" oder "lokal" (Whisper)
    "spracherkennung": "STT_MODUS",
    "whisper_modell": "WHISPER_MODELL",
}

# Werte, die nur angezeigt, aber nicht über die Oberfläche gesetzt werden
NUR_LESEN = ("ANTHROPIC_API_KEY", "FISH_API_KEY")

_lock = threading.Lock()


def _path() -> Path:
    return Path(os.getenv("EINSTELLUNGEN_PATH") or DEFAULT_PATH)


def laden() -> dict[str, Any]:
    """Gespeicherte Einstellungen, leeres Dict wenn es noch keine gibt."""
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: v for k, v in data.items() if k in FELDER} if isinstance(data, dict) else {}


def anwenden() -> dict[str, Any]:
    """Gespeicherte Werte in die Umgebung übernehmen (beim Start aufrufen)."""
    gespeichert = laden()
    for name, env in FELDER.items():
        wert = gespeichert.get(name)
        if wert in (None, ""):
            continue
        if name == "vault_pfad" and not Path(str(wert)).is_dir():
            # z.B. Windows-Pfad auf dem Linux-Mini-PC (24.09.2026): dann gilt VAULT_PATH aus .env/Dienst
            print(f"[Einstellungen] Vault-Ordner {wert!r} gibt es hier nicht - nehme VAULT_PATH.", flush=True)
            continue
        os.environ[env] = str(wert)
    return gespeichert


def speichern(neu: dict[str, Any]) -> dict[str, Any]:
    """Werte prüfen, speichern und sofort in die Umgebung übernehmen."""
    unbekannt = [k for k in neu if k not in FELDER]
    if unbekannt:
        raise ValueError("Unbekannte Einstellung: " + ", ".join(sorted(unbekannt)))

    pfad = neu.get("vault_pfad")
    if pfad not in (None, "") and not Path(str(pfad)).is_dir():
        raise ValueError(f"Ordner gibt es nicht: {pfad}")
    if neu.get("ki_anbieter") not in (None, "", "claude", "ollama"):
        raise ValueError("KI-Anbieter muss 'claude' oder 'ollama' sein")
    stt_modus = neu.get("spracherkennung")
    if stt_modus not in (None, "", "browser", "lokal"):
        raise ValueError("Spracherkennung muss 'browser' oder 'lokal' sein")
    wm = neu.get("whisper_modell")
    if wm not in (None, "", "tiny", "base", "small", "medium"):
        raise ValueError("Whisper-Modell: tiny, base, small oder medium")
    modus = neu.get("chat_modus")
    if modus not in (None, "", "klassisch", "werkzeug"):
        raise ValueError("Modus muss 'klassisch' oder 'werkzeug' sein")

    with _lock:
        aktuell = laden()
        aktuell.update({k: v for k, v in neu.items()})
        ziel = _path()
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(json.dumps(aktuell, ensure_ascii=False, indent=1), encoding="utf-8")
    anwenden()
    return aktuell


def aktueller_stand() -> dict[str, Any]:
    """Was gerade gilt: gespeicherte Werte plus die tatsächlich aktive Umgebung."""
    gespeichert = laden()
    aktiv = {name: os.getenv(env) or None for name, env in FELDER.items()}
    return {
        "gespeichert": gespeichert,
        "aktiv": aktiv,
        "api_schluessel_gesetzt": bool(os.getenv("ANTHROPIC_API_KEY")),
        "fish_schluessel_gesetzt": bool(os.getenv("FISH_API_KEY")),
        "datei": str(_path()),
    }

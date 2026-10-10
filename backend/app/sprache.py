"""
Sprachausgabe über Fish Audio (https://fish.audio).

Warum: Die Windows-Stimmen im Browser klingen blechern. Fish Audio liefert
deutlich natürlichere deutsche Stimmen und stellt das Modell `s2.1-pro-free`
bis zum 30.11.2026 kostenlos zur Verfügung (kein Konto mit Zahlungsmittel
nötig, kein Zeichenlimit, nur "Fair Use").

Datenschutz - bewusst hier notiert, weil es der einzige Teil von Jarvis ist,
der Inhalte aus dem Vault nach außen gibt: Der vorgelesene Text geht an die
Server von Fish Audio und kann laut deren Datenschutzerklärung zur
Verbesserung der Modelle genutzt werden. Wer das nicht will, stellt die
Sprachausgabe im HUD auf "Windows-Stimmen" zurück - dann verlässt nichts
den PC.

Einstellungen (.env oder data/einstellungen.json):
    FISH_API_KEY    Schlüssel von fish.audio/app/api-keys (Pflicht)
    FISH_MODEL      Standard: s2.1-pro-free
    FISH_VOICE_ID   Stimme aus der Fish-Bibliothek (optional, sonst Standardstimme)
    FISH_TIMEOUT    Sekunden, Standard 30
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

URL = "https://api.fish.audio/v1/tts"
STANDARD_MODELL = "s2.1-pro-free"
# Mehr als das liest ohnehin niemand am Stück - schützt vor Ausrutschern
# (versehentlich eine ganze Notiz vorlesen lassen).
MAX_ZEICHEN = 2000


class SpracheFehler(RuntimeError):
    """Sprachausgabe nicht möglich - Text ist für die Oberfläche gedacht."""


def schluessel() -> str:
    return (os.getenv("FISH_API_KEY") or "").strip()


def modell() -> str:
    return (os.getenv("FISH_MODEL") or STANDARD_MODELL).strip() or STANDARD_MODELL


def stimme() -> str:
    return (os.getenv("FISH_VOICE_ID") or "").strip()


def verfuegbar() -> bool:
    return bool(schluessel())


def stand() -> dict:
    """Was das HUD wissen muss, ohne den Schlüssel preiszugeben."""
    return {
        "verfuegbar": verfuegbar(),
        "modell": modell(),
        "stimme": stimme() or None,
        "hinweis": (
            "Der vorgelesene Text wird an Fish Audio gesendet."
            if verfuegbar()
            else "Kein FISH_API_KEY gesetzt - Sprachausgabe läuft über die Windows-Stimmen."
        ),
    }


def _nutzlast(text: str, tempo: float) -> dict:
    körper: dict = {
        "text": text,
        "format": "mp3",
        "mp3_bitrate": 128,
        "normalize": True,      # Zahlen und Daten werden ausgeschrieben
        "latency": "balanced",
    }
    if stimme():
        körper["reference_id"] = stimme()
    if abs(tempo - 1.0) > 0.01:
        körper["prosody"] = {"speed": max(0.5, min(2.0, float(tempo)))}
    return körper


def aufbereiten(text: str) -> str:
    """Quellenmarken [1] entfernen und auf eine sinnvolle Länge kürzen."""
    sauber = re.sub(r"\[\d+\]", "", str(text or ""))
    sauber = " ".join(sauber.split())
    # sonst bliebe nach "im Vault [2]." ein Leerzeichen vor dem Punkt stehen,
    # was manche Stimmen als Pause vorlesen
    sauber = re.sub(r"\s+([.,;:!?])", r"\1", sauber)
    return sauber[:MAX_ZEICHEN]


def sprich(text: str, tempo: float = 1.0) -> bytes:
    """Text an Fish Audio schicken und die MP3-Daten zurückgeben."""
    inhalt = aufbereiten(text)
    if not inhalt:
        raise SpracheFehler("Kein Text zum Vorlesen.")
    key = schluessel()
    if not key:
        raise SpracheFehler("FISH_API_KEY fehlt - Schlüssel in die .env eintragen und Backend neu starten.")

    anfrage = urllib.request.Request(
        URL,
        data=json.dumps(_nutzlast(inhalt, tempo)).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "model": modell(),
        },
        method="POST",
    )
    zeit = float(os.getenv("FISH_TIMEOUT") or 30)
    try:
        with urllib.request.urlopen(anfrage, timeout=zeit) as antwort:
            daten = antwort.read()
    except urllib.error.HTTPError as exc:
        details = ""
        try:
            details = exc.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001 - Fehlertext ist nur Beiwerk
            pass
        if exc.code in (401, 403):
            raise SpracheFehler("Fish Audio lehnt den Schlüssel ab (401/403). Schlüssel prüfen.") from exc
        if exc.code == 429:
            raise SpracheFehler("Fish Audio bremst gerade (429). Später nochmal.") from exc
        raise SpracheFehler(f"Fish Audio antwortet mit Fehler {exc.code}. {details}".strip()) from exc
    except urllib.error.URLError as exc:
        raise SpracheFehler(f"Fish Audio nicht erreichbar: {exc.reason}") from exc

    if not daten:
        raise SpracheFehler("Fish Audio hat nichts zurückgegeben.")
    return daten

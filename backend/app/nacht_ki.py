"""
Nacht-KI (04.10.2026, Claude Cowork): EIN Ort, an dem die Nachtarbeit ihre KI bekommt.

Entscheidung Sir 04.10.2026: Die Nachtarbeit darf NICHT mit der Claude-API verbunden sein.
Befund am selben Tag: `nachtauftraege.py` und `nachtarbeit.py` riefen Claude (Sonnet, Opus,
Haiku) fest über `aufgaben_loop._anthropic_client()` auf und wurden bei der Umstellung auf
lokale KI am 03.10. nicht angepasst. Die Nacht zum 04.10. kostete deshalb ca. 0,29 $.

Jetzt gilt: Nachtarbeit nutzt NUR die lokalen Ollama-Rechner aus data/ki_lokal.json
(Reihenfolge "reihenfolge": Test-PC, Haupt-PC, Mini-PC). Ist keiner erreichbar, wartet die
Arbeit bis zur nächsten Nacht. Es gibt keinen Rückfall auf Claude und keine Websuche.
Der Schalter `ki_anbieter` in den Einstellungen gilt hier nicht.
"""

from __future__ import annotations

from typing import Any

import requests

from llm import provider


class NachtKiFehler(RuntimeError):
    """Kein lokaler KI-Rechner erreichbar - die Arbeit bleibt liegen, nichts geht an Claude."""


def ist_lokal(client: Any) -> bool:
    return isinstance(client, provider.OllamaClient)


def modell_label() -> str:
    """Modell des ersten Rechners der Nacht-Reihenfolge (für Protokoll und Anzeige)."""
    z = provider.ziele(False)
    return z[0]["modell"] if z else "lokal"


def erreichbar() -> tuple[bool, str]:
    """Antwortet mindestens ein Rechner der Nacht-Reihenfolge? Rückgabe: (ja/nein, Name oder Liste)."""
    alle = provider.ziele(False)
    for z in alle:
        try:
            r = requests.get(f"{z['url']}/api/tags", timeout=(provider.OLLAMA_CONNECT_TIMEOUT, 5))
            r.raise_for_status()
            return True, z["name"]
        except requests.exceptions.RequestException:
            continue
    return False, ", ".join(f"{z['name']} ({z['url']})" for z in alle) or "kein Rechner eingetragen"


def client() -> provider.OllamaClient:
    """Lokaler Client für die Nacht (tag=False: große Kontextlänge, lange Zeitgrenze).
    Wirft NachtKiFehler, wenn kein Rechner antwortet. Gibt NIE einen Claude-Client zurück."""
    ok, wer = erreichbar()
    if not ok:
        raise NachtKiFehler(f"Kein lokaler KI-Rechner erreichbar: {wer}. Die Arbeit wartet auf die nächste Nacht.")
    return provider.OllamaClient(tag=False)


def abgeschnitten(usage: Any, max_tokens: int) -> bool:
    """Lokale Antworten melden keinen stop_reason: Erreichte Ausgabe-Token = Grenze erreicht."""
    return (getattr(usage, "output_tokens", 0) or 0) >= max_tokens - 5

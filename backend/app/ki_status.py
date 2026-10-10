"""
Zustand der lokalen KI für Auron (05.10.2026, Claude Cowork).

Wozu: Auron zeigt eine klare Fehleranzeige, sobald die lokale KI nicht erreichbar ist
(Wunsch Sir, Punkt 6), statt still auf Claude zurückzufallen. Dafür fragt diese Seite
die Rechner aus "reihenfolge_tag" (data/ki_lokal.json) direkt bei Ollama ab:
    GET <url>/api/tags  -> Rechner an? Modell installiert?
    GET <url>/api/ps    -> Modell gerade im Speicher geladen (erste Antwort schnell)?
Kostet nichts (keine KI-Anfrage), dauert höchstens ca. 3 s (alle Rechner gleichzeitig) und
wird 20 s zwischengespeichert, damit mehrere offene Fenster die PCs nicht dauernd fragen.

Antwort von /api/ki/status:
    {"anbieter": "ollama"|"claude", "lokal_bereit": bool, "rueckfall": "claude"|None,
     "rechner": [{"name", "url", "modell", "erreichbar", "installiert", "geladen", "fehler"}],
     "zeit": "..."}
"""

from __future__ import annotations

import datetime
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

from llm import provider

ZWISCHENSPEICHER_S = 20
_lock = threading.Lock()
_letzter: dict[str, Any] = {"zeit": 0.0, "daten": None}


def _namen(antwort: requests.Response, feld: str = "models") -> list[str]:
    try:
        return [str(m.get("name") or m.get("model") or "") for m in (antwort.json() or {}).get(feld) or []]
    except ValueError:
        return []


def _passt(modell: str, namen: list[str]) -> bool:
    """qwen3.5:9b passt auf "qwen3.5:9b"; ohne Tag auch auf "<name>:latest"."""
    m = modell.strip().lower()
    return any(n.lower() == m or n.lower() == f"{m}:latest" for n in namen)


def _rechner_pruefen(z: dict[str, str]) -> dict[str, Any]:
    eintrag: dict[str, Any] = {"name": z["name"], "url": z["url"], "modell": z["modell"],
                               "erreichbar": False, "installiert": False, "geladen": False, "fehler": ""}
    zeit = (provider.OLLAMA_CONNECT_TIMEOUT, 3)
    try:
        r = requests.get(f"{z['url']}/api/tags", timeout=zeit)
        r.raise_for_status()
        eintrag["erreichbar"] = True
        eintrag["installiert"] = _passt(z["modell"], _namen(r))
        if not eintrag["installiert"]:
            eintrag["fehler"] = f"Modell {z['modell']} ist dort nicht installiert"
    except requests.exceptions.RequestException as exc:
        eintrag["fehler"] = "aus oder nicht im Netz" if isinstance(exc, requests.exceptions.ConnectionError) \
            else f"antwortet nicht ({exc.__class__.__name__})"
        return eintrag
    try:
        r = requests.get(f"{z['url']}/api/ps", timeout=zeit)
        r.raise_for_status()
        eintrag["geladen"] = _passt(z["modell"], _namen(r))
    except requests.exceptions.RequestException:
        pass  # ältere Ollama-Version ohne /api/ps: "geladen" bleibt unbekannt (False)
    return eintrag


def status(neu: bool = False) -> dict[str, Any]:
    """Zustand aller Tag-Rechner (zwischengespeichert, neu=True fragt sofort)."""
    with _lock:
        if not neu and _letzter["daten"] and time.time() - _letzter["zeit"] < ZWISCHENSPEICHER_S:
            return _letzter["daten"]
    anbieter = provider.provider_name()
    rechner: list[dict[str, Any]] = []
    if anbieter == "ollama":
        ziele = provider.ziele(tag=True)
        with ThreadPoolExecutor(max_workers=max(1, len(ziele))) as pool:
            rechner = list(pool.map(_rechner_pruefen, ziele))
    daten = {
        "anbieter": anbieter,
        "lokal_bereit": any(r["erreichbar"] and r["installiert"] for r in rechner),
        "rueckfall": provider.tag_rueckfall() if anbieter == "ollama" else None,
        "rechner": rechner,
        "zeit": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    with _lock:
        _letzter.update({"zeit": time.time(), "daten": daten})
    return daten


# ------------------------------------------------------------------ Vorwärmen (05.10.2026)
# Wunsch Sir: Auron soll beim Sprechen viel schneller antworten. Größte Bremse: Nach einer Pause muss
# Ollama das Modell erst in den Grafikspeicher laden (ca. 20 s bei der ersten Frage). Der Ladebildschirm
# von Auron ruft deshalb /api/ki/aufwaermen: Ollama lädt das Modell, ohne etwas zu erzeugen (POST /api/generate
# ohne Prompt), und hält es OLLAMA_KEEP_ALIVE (60 Min.) im Speicher. Kostet nichts.

def aufwaermen(zeitgrenze: float = 45.0) -> dict[str, Any]:
    """Lädt das Modell auf dem ersten erreichbaren Tag-Rechner. Rückgabe:
    {"ok": bool, "rechner": name, "modell": m, "schon_geladen": bool, "sekunden": s, "fehler": ""}"""
    if provider.provider_name() != "ollama":
        return {"ok": True, "rechner": "Claude", "modell": "", "schon_geladen": True, "sekunden": 0.0, "fehler": ""}
    s = status(neu=True)
    for r in s["rechner"]:
        if not (r["erreichbar"] and r["installiert"]):
            continue
        if r["geladen"]:
            return {"ok": True, "rechner": r["name"], "modell": r["modell"], "schon_geladen": True, "sekunden": 0.0, "fehler": ""}
        start = time.time()
        try:
            antwort = requests.post(f"{r['url']}/api/generate", json={"model": r["modell"], "keep_alive": provider.OLLAMA_KEEP_ALIVE},
                                    timeout=(provider.OLLAMA_CONNECT_TIMEOUT, zeitgrenze))
            antwort.raise_for_status()
        except requests.exceptions.RequestException as exc:
            return {"ok": False, "rechner": r["name"], "modell": r["modell"], "schon_geladen": False,
                    "sekunden": round(time.time() - start, 1), "fehler": exc.__class__.__name__}
        with _lock:
            _letzter["daten"] = None   # Status neu abfragen lassen ("geladen" hat sich geändert)
        return {"ok": True, "rechner": r["name"], "modell": r["modell"], "schon_geladen": False,
                "sekunden": round(time.time() - start, 1), "fehler": ""}
    return {"ok": False, "rechner": "", "modell": "", "schon_geladen": False, "sekunden": 0.0,
            "fehler": "kein lokaler Rechner mit Modell erreichbar"}

"""
Alarme (P24b, 16.10.2026, Claude Code): Auron meldet sich, wenn im ganzen System etwas nicht geht.

Quelle ist die Ampel (app/ampel.py): Jeder Bereich, der ROT wird, löst genau eine Meldung aus (Vault einlesen,
Aufgaben-Loop, Studium, Nachtarbeit, Kosten, GPU-Miete ...). Bleibt er rot, kommt nach ALARM_WIEDERHOLUNG_STUNDEN (6)
eine Erinnerung; wird er wieder grün/grau, ist der Zustand vergessen und der nächste Fehler meldet sich neu.

Wege (Kanäle), in dieser Reihenfolge, jeder optional:
  1. Alexa-Benachrichtigung (app/alexa_alarm.py): gelber Ring am Echo, Details über "frag Agent Auron nach dem Status".
  2. Fehlerbericht und Konsole: immer (die Fehler stehen ohnehin im Bericht).
  3. Banner in Auron: braucht keinen Kanal, liest die Ampel direkt (dashboard/auron.html).
Ist kein Kanal eingerichtet, merkt Auron sich NICHT als gemeldet und versucht es beim nächsten Prüflauf erneut.

Wo es läuft: im Backend alle ALARM_INTERVALL_MIN (5) Minuten (start_hintergrund, aus main.py) und für die GPU-Miete
zusätzlich im Wächter auf dem Mini-PC (backend/gpu_waechter.py), der unabhängig vom Backend läuft.
Grenze: Ist das Backend selbst aus, meldet es nichts. Das erkennt dann nur der Banner am PC ("Keine Verbindung zum Mini-PC").
"""

from __future__ import annotations

import datetime
import json
import os
import threading
from pathlib import Path
from typing import Any

from . import fehlerbericht

_lock = threading.Lock()
_stop = threading.Event()


def _intervall_s() -> float:
    try:
        return max(60.0, float(os.getenv("ALARM_INTERVALL_MIN", "5")) * 60)
    except ValueError:
        return 300.0


def _wiederholung_s() -> float:
    try:
        return max(600.0, float(os.getenv("ALARM_WIEDERHOLUNG_STUNDEN", "6")) * 3600)
    except ValueError:
        return 6 * 3600.0


def _pfad() -> Path:
    return Path(os.getenv("ALARM_PATH") or Path(__file__).resolve().parents[2] / "data" / "alarm_zustand.json")


def _lesen() -> dict[str, dict]:
    try:
        d = json.loads(_pfad().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _schreiben(d: dict) -> None:
    try:
        p = _pfad()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def rote_bereiche() -> list[dict]:
    """Alle Bereiche, die in der Ampel rot sind: [{"name", "text"}]."""
    from . import ampel

    return [{"name": j["name"], "text": j.get("text", "")} for j in ampel.uebersicht()["jobs"] if j.get("farbe") == "rot"]


def _kanaele(namen: list[str]) -> list[tuple[str, bool, str]]:
    """Versucht alle eingerichteten Wege. Rückgabe: [(Weg, geklappt, Text)]."""
    ergebnis = []
    from . import alexa_alarm

    if alexa_alarm.eingerichtet():
        ok, text = alexa_alarm.senden(namen)
        ergebnis.append(("alexa", ok, text))
    return ergebnis


def pruefen(rote: list[dict] | None = None, bereich: list[str] | None = None,
            jetzt: datetime.datetime | None = None) -> dict[str, Any]:
    """Meldet neu rote Bereiche (und erinnert an lange rote). rote=None: aus der Ampel lesen.
    bereich: nur diese Bereichsnamen betrachten (der GPU-Wächter prüft nur "GPU-Miete", ohne den übrigen Zustand
    anzufassen). Wirft nie."""
    jetzt = jetzt or datetime.datetime.now().astimezone()
    try:
        rote = rote_bereiche() if rote is None else rote
    except Exception as exc:  # noqa: BLE001
        fehlerbericht.merken("fehler", f"Alarm-Prüfung: Ampel nicht lesbar ({type(exc).__name__}: {exc})", "alarm")
        return {"gemeldet": [], "kanaele": [], "fehler": str(exc)}
    if bereich is not None:
        rote = [r for r in rote if r["name"] in bereich]
    with _lock:
        zustand = _lesen()
        aktuell = {r["name"]: r for r in rote}
        # Entwarnung: nicht mehr rot -> vergessen (nur im betrachteten Bereich)
        for name in list(zustand):
            if (bereich is None or name in bereich) and name not in aktuell:
                del zustand[name]
        faellig = []
        for name, r in aktuell.items():
            e = zustand.get(name)
            gemeldet = None
            if e and e.get("gemeldet"):
                try:
                    gemeldet = datetime.datetime.fromisoformat(e["gemeldet"])
                except ValueError:
                    gemeldet = None
            if gemeldet is None or (jetzt - gemeldet).total_seconds() >= _wiederholung_s():
                faellig.append(r)
            zustand.setdefault(name, {"seit": jetzt.isoformat(timespec="seconds"), "gemeldet": None})
            zustand[name]["text"] = str(r.get("text", ""))[:200]
        kanaele: list[tuple[str, bool, str]] = []
        if faellig:
            namen = [r["name"] for r in faellig]
            fehlerbericht.merken("alarm", "ALARM Auron: " + "; ".join(f"{r['name']}: {r.get('text', '')}" for r in faellig), "alarm")
            kanaele = _kanaele(namen)
            if any(ok for _, ok, _ in kanaele):
                for r in faellig:
                    zustand[r["name"]]["gemeldet"] = jetzt.isoformat(timespec="seconds")
            for weg, ok, text in kanaele:
                if not ok:
                    fehlerbericht.merken("fehler", f"Alarm über {weg} nicht zugestellt: {text}", "alarm")
        _schreiben(zustand)
    return {"gemeldet": [r["name"] for r in faellig], "kanaele": kanaele, "rot": list(aktuell)}


def pruefen_gpu() -> dict[str, Any]:
    """Nur der GPU-Alarm (für den Wächter auf dem Mini-PC, unabhängig vom Backend)."""
    from . import gpu_miete

    a = gpu_miete.alarm_lesen()
    rote = [{"name": "GPU-Miete", "text": str(a.get("text", ""))}] if a else []
    return pruefen(rote, bereich=["GPU-Miete"])


def status() -> dict[str, Any]:
    from . import alexa_alarm

    return {"alexa_eingerichtet": alexa_alarm.eingerichtet(), "alexa_fehlt": alexa_alarm.fehlt(),
            "gemeldet": _lesen(), "intervall_min": _intervall_s() / 60}


def start_hintergrund() -> None:
    """Einmal beim Backend-Start: alle paar Minuten die Ampel prüfen. Ausschalten: ALARM_AUS=1."""
    if (os.getenv("ALARM_AUS") or "").strip().lower() in ("1", "ja", "true"):
        return
    _stop.clear()

    def _lauf() -> None:
        if _stop.wait(120):          # die Dienste erst zur Ruhe kommen lassen
            return
        while not _stop.is_set():
            try:
                pruefen()
            except Exception as exc:  # noqa: BLE001
                print(f"WARNUNG: Alarm-Prüfung fehlgeschlagen: {exc}", flush=True)
            if _stop.wait(_intervall_s()):
                return

    threading.Thread(target=_lauf, name="auron-alarm", daemon=True).start()


def stoppen() -> None:
    _stop.set()

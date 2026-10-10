"""
Fehlerbericht (10.10.2026, Claude Code).

Wunsch Sir: Er soll nicht selbst suchen müssen, wo Auron Probleme macht. Deshalb sammelt das Backend seine
Fehler selbst, und "1 Starten/FEHLERBERICHT SENDEN.bat" legt den Bericht ins Repo (berichte/fehlerbericht.md),
wo Claude ihn liest.

Gesammelt wird (einrichten(), aufgerufen in main.py):
- alles, was das Backend auf die Konsole schreibt und nach Fehler aussieht: Tracebacks, "WARNUNG", "Fehler",
  "fehlgeschlagen", "antwortet nicht" usw. (Jarvis meldet Probleme fast immer per print)
- Log-Meldungen ab WARNING (z.B. "Exception in ASGI application" von uvicorn mit Traceback)
Gleiche Meldungen werden zusammengefasst (Anzahl, erstes und letztes Mal). Gespeichert in data/fehler_log.jsonl
(FEHLER_LOG_PATH), höchstens ca. 2 MB, dann fallen die ältesten Einträge weg.

Datenschutz: Schlüssel, Tokens, Mailadressen und lange Kennungen werden vor dem Speichern unkenntlich gemacht
(saeubern()). Chat-Inhalte werden nicht gesammelt - nur Fehlermeldungen. Ganz ausschließen lässt sich nicht,
dass eine Fehlermeldung ein Stück Text enthält; jeder Eintrag ist deshalb auf 800 Zeichen begrenzt.

bericht() baut daraus Markdown: Zustand der Hintergrund-Läufe (Ampel), KI-Rechner, Monatsrahmen und die
Fehler der letzten Tage. GET /api/fehlerbericht liefert ihn. 0 Kosten, keine KI-Aufrufe.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import platform
import re
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

MAX_ZEICHEN = 800
MAX_DATEI_BYTES = 2_000_000
GLEICHE_MELDUNG_S = 600   # gleiche Meldung höchstens alle 10 Minuten neu in die Datei (Zähler läuft weiter)
START = time.time()

# Zeilen, die nach Problem aussehen (Groß-/Kleinschreibung wie in Jarvis üblich)
_MARKER = re.compile(r"Traceback \(most recent call last\)|\bWARNUNG\b|\bFEHLER\b|\bFehler\b|fehlgeschlagen|"
                     r"nicht erreichbar|antwortet nicht|\bException\b|\w+Error\b")

_GEHEIM = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]+"), "sk-ant-***"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=\-]+"), r"\1***"),
    (re.compile(r"(?i)((?:api[_-]?key|token|secret|passwor[dt]|passwd|client_secret)\s*[=:]\s*)[^\s,;&\"']+"), r"\1***"),
    (re.compile(r"(?i)([?&](?:token|key|access_token|refresh_token|code|sig|signature)=)[^&\s\"']+"), r"\1***"),
    (re.compile(r"/calendar/ical/[^\s\"']+"), "/calendar/ical/***"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "<mail>"),
    (re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"), "***"),
]

_lock = threading.Lock()
_zuletzt_geschrieben: dict[str, float] = {}
_zaehler: dict[str, int] = {}
_eingerichtet = [False]


def pfad() -> Path:
    return Path(os.getenv("FEHLER_LOG_PATH") or Path(__file__).resolve().parents[2] / "data" / "fehler_log.jsonl")


def saeubern(text: str) -> str:
    """Schlüssel, Tokens, Mailadressen und lange Kennungen unkenntlich machen, Länge begrenzen."""
    t = str(text or "")
    for muster, ersatz in _GEHEIM:
        t = muster.sub(ersatz, t)
    return t[:MAX_ZEICHEN]


def _schluessel(text: str) -> str:
    """Gleiche Meldung trotz anderer Zahlen (Uhrzeit, Ports, Dauer) erkennen."""
    return re.sub(r"\d+", "#", text.strip().splitlines()[-1] if text.strip() else "")[:200]


def merken(art: str, text: str, quelle: str = "") -> None:
    """Einen Fund eintragen. Wirft nie (darf die eigentliche Arbeit nicht stören)."""
    try:
        text = saeubern(text).rstrip()
        if not text:
            return
        key = f"{art}|{_schluessel(text)}"
        jetzt = time.time()
        with _lock:
            _zaehler[key] = _zaehler.get(key, 0) + 1
            if jetzt - _zuletzt_geschrieben.get(key, 0) < GLEICHE_MELDUNG_S:
                return
            _zuletzt_geschrieben[key] = jetzt
            anzahl = _zaehler[key]
            _zaehler[key] = 0
            p = pfad()
            p.parent.mkdir(parents=True, exist_ok=True)
            eintrag = {"zeit": _dt.datetime.now().astimezone().isoformat(timespec="seconds"), "art": art,
                       "quelle": quelle, "key": key, "anzahl": anzahl, "text": text}
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
            if p.stat().st_size > MAX_DATEI_BYTES:
                zeilen = p.read_text(encoding="utf-8", errors="replace").splitlines()
                p.write_text("\n".join(zeilen[len(zeilen) // 2:]) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


class Mitschreiber:
    """Hängt sich zwischen sys.stdout/sys.stderr und die Konsole: alles geht unverändert weiter,
    Zeilen, die nach Fehler aussehen, und ganze Tracebacks werden zusätzlich gemerkt."""

    def __init__(self, strom: Any, quelle: str) -> None:
        self._strom = strom
        self._quelle = quelle
        self._rest = ""
        self._tb: list[str] | None = None

    def write(self, text: str) -> int:
        n = self._strom.write(text)
        try:
            self._lesen(text)
        except Exception:  # noqa: BLE001
            pass
        return n

    def flush(self) -> None:
        self._strom.flush()

    def __getattr__(self, name: str) -> Any:   # reconfigure, encoding, isatty ... vom echten Strom
        return getattr(self._strom, name)

    def _lesen(self, text: str) -> None:
        self._rest += text
        if "\n" not in self._rest:
            if len(self._rest) > 20000:
                self._rest = self._rest[-20000:]
            return
        *zeilen, self._rest = self._rest.split("\n")
        for z in zeilen:
            self._zeile(z.rstrip("\r"))

    def _zeile(self, z: str) -> None:
        if self._tb is not None:
            self._tb.append(z)
            weiter = (not z or z[0] in " \t" or z.startswith(("Traceback", "During handling", "The above exception"))
                      or z.startswith("^"))
            if not weiter:   # erste Zeile ohne Einrückung = die eigentliche Fehlermeldung
                merken("traceback", "\n".join(self._tb[-14:]), self._quelle)
                self._tb = None
            elif len(self._tb) > 400:
                self._tb = self._tb[-40:]
            return
        if z.startswith("Traceback (most recent call last)"):
            self._tb = [z]
        elif _MARKER.search(z):
            merken("meldung", z, self._quelle)


class _LogSammler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = record.getMessage()
            if record.exc_info:
                import traceback  # noqa: PLC0415

                text += "\n" + "".join(traceback.format_exception(*record.exc_info)[-14:])
            merken("log", f"{record.levelname} {record.name}: {text}", "logging")
        except Exception:  # noqa: BLE001
            pass


def einrichten() -> None:
    """Einmal beim Start (main.py). Ohne Wirkung, wenn FEHLERBERICHT=aus in der .env steht."""
    if _eingerichtet[0] or os.getenv("FEHLERBERICHT", "").strip().lower() in ("aus", "0", "false", "nein"):
        return
    _eingerichtet[0] = True
    sys.stdout = Mitschreiber(sys.stdout, "konsole")
    sys.stderr = Mitschreiber(sys.stderr, "konsole")
    sammler = _LogSammler(level=logging.WARNING)
    for name in ("", "uvicorn", "uvicorn.error"):
        logging.getLogger(name).addHandler(sammler)


# ------------------------------------------------------------------ Bericht

def eintraege(tage: int = 7) -> list[dict]:
    """Gespeicherte Funde der letzten Tage, gleiche Meldungen zusammengefasst (häufigste zuerst)."""
    grenze = (_dt.datetime.now().astimezone() - _dt.timedelta(days=tage)).isoformat(timespec="seconds")
    gruppen: dict[str, dict] = {}
    try:
        zeilen = pfad().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        zeilen = []
    for z in zeilen:
        try:
            e = json.loads(z)
        except json.JSONDecodeError:
            continue
        if str(e.get("zeit", "")) < grenze:
            continue
        g = gruppen.setdefault(e.get("key", ""), {"art": e.get("art"), "anzahl": 0, "erstes": e.get("zeit"),
                                                   "letztes": e.get("zeit"), "text": e.get("text", "")})
        g["anzahl"] += int(e.get("anzahl") or 1)
        g["letztes"] = e.get("zeit")
        g["text"] = e.get("text", g["text"])
    with _lock:   # noch nicht geschriebene Wiederholungen mitzählen
        offen = dict(_zaehler)
    for key, n in offen.items():
        if key in gruppen:
            gruppen[key]["anzahl"] += n
    return sorted(gruppen.values(), key=lambda g: (g["art"] != "traceback", -g["anzahl"], g["letztes"] or ""))


def _abschnitt(titel: str, funktion) -> list[str]:
    try:
        return [f"## {titel}", "", *funktion(), ""]
    except Exception as exc:  # noqa: BLE001 - ein kaputter Teil darf den Bericht nie verhindern
        return [f"## {titel}", "", f"(nicht lesbar: {saeubern(f'{type(exc).__name__}: {exc}')})", ""]


def _ampel() -> list[str]:
    from . import ampel  # noqa: PLC0415

    u = ampel.uebersicht()
    return [f"- **{j.get('name')}**: {j.get('farbe')} - {saeubern(j.get('text', ''))}" for j in u.get("jobs", [])]


def _ki() -> list[str]:
    from . import ki_status  # noqa: PLC0415

    st = ki_status.status(neu=True)
    zeilen = [f"- Anbieter: {st.get('anbieter')}"]
    for r in st.get("rechner", []):
        zeilen.append(f"- {r.get('name')}: {'erreichbar' if r.get('erreichbar') else 'NICHT erreichbar'}, "
                      f"Modell {r.get('modell')}, {'geladen' if r.get('geladen') else 'nicht geladen'}"
                      + (f", Fehler: {saeubern(r.get('fehler'))}" if r.get("fehler") else ""))
    return zeilen


def _kosten() -> list[str]:
    from . import kosten  # noqa: PLC0415

    u = kosten.uebersicht()
    return [f"- Rest im Monatsrahmen: {u.get('rest_usd', '?')} $"]


def _funde(tage: int) -> list[str]:
    liste = eintraege(tage)
    if not liste:
        return ["Keine Fehler gesammelt."]
    zeilen = []
    for g in liste[:60]:
        zeilen += [f"### {g['art']} · {g['anzahl']}x · zuletzt {g['letztes']} (erstes Mal {g['erstes']})", "",
                   "```", g["text"], "```", ""]
    return zeilen


def bericht(tage: int = 7) -> str:
    laufzeit = int(time.time() - START)
    kopf = [f"# Fehlerbericht Auron - {_dt.datetime.now().astimezone().strftime('%d.%m.%Y %H:%M')}", "",
            f"- Rechner: {socket.gethostname()} ({platform.system()} {platform.release()}), Python {platform.python_version()}",
            f"- Backend läuft seit {laufzeit // 3600} h {laufzeit % 3600 // 60} min, Fehlersammlung "
            f"{'an' if _eingerichtet[0] else 'AUS'}",
            f"- KI-Anbieter: {os.getenv('LLM_PROVIDER') or 'claude'}", ""]
    return "\n".join(kopf + _abschnitt("Hintergrund-Läufe (Ampel)", _ampel) + _abschnitt("KI-Rechner", _ki)
                     + _abschnitt("Kosten", _kosten) + _abschnitt(f"Fehler der letzten {tage} Tage", lambda: _funde(tage)))

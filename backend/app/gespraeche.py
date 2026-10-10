"""
Gedächtnis über Gespräche (Phase 2.6, 23.09.2026).

Jede Frage an Jarvis und seine Antwort werden lokal gespeichert:
data/gespraeche/JJJJ-MM-TT.jsonl, eine Zeile pro Austausch. Nichts davon
verlässt den PC, nichts geht automatisch an Claude.

Wozu:
- Verlauf im HUD: frühere Gespräche wieder öffnen und durchsuchen.
- Werkzeug "gespraeche_suchen": Jarvis findet frühere Entscheidungen
  ("Was hatten wir zu Opus gesagt?") - nur im Werkzeug-Modus, auf Nachfrage.
- Bewertung (gut/schlecht): schlechte Antworten landen zusätzlich in
  data/testfragen_kandidaten.jsonl - daraus werden neue Testfragen.
- Tagesnotiz per Knopf: die Gespräche eines Tages zusammenfassen und als
  Vorschlag in die Tagesnotiz im Vault eintragen (app/routes.py).

Datenschutz: Die Dateien liegen nur im Jarvis-Ordner (data/ ist nicht im Git).
Abschalten mit GESPRAECHE_MERKEN=false in der .env.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any

DEFAULT_ORDNER = Path(__file__).resolve().parents[2] / "data" / "gespraeche"
MAX_ANTWORT_ZEICHEN = 20_000
MAX_TREFFER = 30
_TAG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_lock = threading.Lock()


def ordner() -> Path:
    pfad = Path(os.getenv("GESPRAECHE_PATH") or DEFAULT_ORDNER)
    pfad.mkdir(parents=True, exist_ok=True)
    return pfad


def aktiv() -> bool:
    return os.getenv("GESPRAECHE_MERKEN", "true").strip().lower() not in ("0", "false", "nein", "aus", "no")


def _jetzt() -> datetime.datetime:
    return datetime.datetime.now().astimezone()


def _datei(tag: str) -> Path:
    if not _TAG_RE.match(tag or ""):
        raise ValueError(f"Ungültiger Tag: {tag!r} (erwartet JJJJ-MM-TT)")
    return ordner() / f"{tag}.jsonl"


def _lesen(pfad: Path) -> list[dict]:
    eintraege = []
    try:
        for zeile in pfad.read_text(encoding="utf-8").splitlines():
            if not zeile.strip():
                continue
            try:
                eintraege.append(json.loads(zeile))
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return eintraege


def speichern(
    frage: str,
    antwort: str,
    quellen: list[dict] | None = None,
    modus: str | None = None,
    modell: str | None = None,
    extra: dict[str, Any] | None = None,
) -> str | None:
    """Speichert einen Austausch und gibt seine ID zurück (None, wenn abgeschaltet)."""
    if not aktiv() or not (frage or "").strip():
        return None
    zeit = _jetzt()
    tag = zeit.date().isoformat()
    eintrag = {
        "id": f"{tag}-{uuid.uuid4().hex[:8]}",
        "zeit": zeit.isoformat(timespec="seconds"),
        "frage": frage.strip()[:5000],
        "antwort": (antwort or "").strip()[:MAX_ANTWORT_ZEICHEN],
        "quellen": [
            {"file_path": q.get("file_path", ""), "heading_path": q.get("heading_path", "")}
            for q in (quellen or []) if isinstance(q, dict)
        ][:20],
        "modus": modus,
        "modell": modell,
    }
    if extra:
        eintrag.update({k: v for k, v in extra.items() if k not in eintrag})
    with _lock:
        with _datei(tag).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
    return eintrag["id"]


def tage() -> list[dict]:
    """Alle Tage mit Gesprächen, neueste zuerst."""
    ergebnis = []
    for pfad in sorted(ordner().glob("*.jsonl"), reverse=True):
        if _TAG_RE.match(pfad.stem):
            ergebnis.append({"tag": pfad.stem, "anzahl": len(_lesen(pfad))})
    return ergebnis


def tag_laden(tag: str) -> list[dict]:
    return _lesen(_datei(tag))


def eintrag(eid: str) -> dict | None:
    tag = (eid or "")[:10]
    if not _TAG_RE.match(tag):
        return None
    return next((e for e in _lesen(_datei(tag)) if e.get("id") == eid), None)


def _aktualisieren(eid: str, felder: dict[str, Any]) -> dict:
    tag = (eid or "")[:10]
    with _lock:
        pfad = _datei(tag)
        eintraege = _lesen(pfad)
        treffer = next((e for e in eintraege if e.get("id") == eid), None)
        if treffer is None:
            raise KeyError(f"Gespräch {eid} nicht gefunden.")
        treffer.update(felder)
        tmp = pfad.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in eintraege), encoding="utf-8")
        tmp.replace(pfad)
    return treffer


def bewerten(eid: str, wert: int, kommentar: str = "") -> dict:
    """wert: +1 (gut) oder -1 (schlecht). Schlechte Antworten werden Testfrage-Kandidaten."""
    if wert not in (1, -1):
        raise ValueError("Bewertung muss +1 oder -1 sein.")
    kommentar = (kommentar or "").strip()[:1000]
    e = _aktualisieren(eid, {"bewertung": wert, "bewertung_kommentar": kommentar,
                             "bewertet": _jetzt().isoformat(timespec="seconds")})
    if wert < 0:
        kandidaten = Path(os.getenv("TESTFRAGEN_KANDIDATEN_PATH") or ordner().parent / "testfragen_kandidaten.jsonl")
        with _lock, kandidaten.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "zeit": _jetzt().isoformat(timespec="seconds"), "gespraech": eid, "frage": e.get("frage"),
                "antwort": (e.get("antwort") or "")[:3000], "quellen": e.get("quellen", []), "kommentar": kommentar,
            }, ensure_ascii=False) + "\n")
    return e


def pruefung_merken(eid: str, pruefung: dict) -> dict:
    return _aktualisieren(eid, {"pruefung": pruefung})


def _woerter(text: str) -> list[str]:
    return [w for w in re.findall(r"[\wäöüß]+", (text or "").casefold()) if len(w) >= 3]


def suchen(suchbegriff: str, limit: int = 10) -> list[dict]:
    """Einfache Stichwortsuche über alle Gespräche, neueste zuerst. Treffer
    müssen alle Wörter (ab 3 Buchstaben) enthalten; Wortanfänge reichen."""
    woerter = _woerter(suchbegriff)
    if not woerter:
        return []
    limit = max(1, min(int(limit or 10), MAX_TREFFER))
    treffer = []
    for pfad in sorted(ordner().glob("*.jsonl"), reverse=True):
        for e in reversed(_lesen(pfad)):
            text = f"{e.get('frage', '')}\n{e.get('antwort', '')}".casefold()
            if all(w in text for w in woerter):
                treffer.append(e)
                if len(treffer) >= limit:
                    return treffer
    return treffer


def kurzfassung(e: dict, zeichen: int = 300) -> str:
    antwort = re.sub(r"\s+", " ", e.get("antwort") or "").strip()
    if len(antwort) > zeichen:
        antwort = antwort[:zeichen].rsplit(" ", 1)[0] + " …"
    return f"{str(e.get('zeit', ''))[:16].replace('T', ' ')} | Frage: {e.get('frage', '')} | Antwort: {antwort}"

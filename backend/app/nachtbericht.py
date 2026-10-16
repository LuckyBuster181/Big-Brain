"""
Kurzfassung der letzten Nacht für Auron (05.10.2026, Claude Cowork, Wunsch Sir Punkt 7).

Beim ersten Öffnen von Auron am Tag erscheint eine kurze Mitteilung: Was hat die Nachtarbeit
erledigt oder gefunden? Diese Seite baut die Daten dafür aus dem, was ohnehin gespeichert wird
(keine KI-Anfrage, 0 Kosten):
- data/nachtarbeit_log.jsonl (nachtarbeit.letzte_nacht): lief sie, was hat sie gekostet, Fehler?
- data/nachtauftraege.json: Aufträge, die in dieser Nacht fertig wurden, scheiterten oder eine
  Rückfrage haben (mit Urteil der Prüfung und Vault-Notiz).
- data/vorschlaege.json: der Vorschlag "Nachtbericht <Datum>" (Abschnitt "Arbeiten für 0 €").

Antwort von /api/nachtarbeit/kurz:
    {"datum": "2026-10-05", "gelaufen": bool, "status", "kosten_usd", "fehler",
     "punkte": ["...", ...],   - höchstens 6 kurze Sätze für die Mitteilung
     "auftraege": [{"nr", "titel", "status", "urteil", "notiz", "fehler"}],
     "bericht_id": "..." | None}  - ID des Vorschlags mit dem ganzen Bericht
"""

from __future__ import annotations

import datetime
import re
from typing import Any

from . import nachtarbeit, nachtauftraege, vorschlaege

MAX_PUNKTE = 6
_FREI_KOPF = "**Arbeiten für 0 €:**"
STATUS_TEXT = {"fertig": "fertig", "fehler": "gescheitert", "rueckfrage": "wartet auf Ihre Antwort",
               "vorschlag": "neuer Vorschlag"}


def _heute() -> datetime.date:
    return datetime.datetime.now().astimezone().date()


def _ergebnis(a: dict) -> dict:
    e = a.get("ergebnis")
    return e if isinstance(e, dict) else {}


def _auftraege_der_nacht(datum: str) -> list[dict]:
    """Aufträge, die in der Nacht zu `datum` bearbeitet wurden (geändert zwischen 00:00 und 09:00)."""
    treffer = []
    for a in nachtauftraege.liste():
        geaendert = str(a.get("geaendert") or "")
        if not geaendert.startswith(datum) or geaendert[11:13] > "08":
            continue
        if a.get("status") not in STATUS_TEXT:
            continue
        e = _ergebnis(a)
        notiz = str(e.get("notiz") or "")
        treffer.append({
            "nr": a.get("id"), "titel": a.get("titel") or "", "status": a.get("status"),
            "urteil": e.get("urteil") or "", "notiz": notiz.rsplit("/", 1)[-1].removesuffix(".md") if notiz else "",
            "fehler": a.get("fehler") or "",
        })
    return treffer


def _frei_zeilen(text: str) -> list[str]:
    """Die Zeilen unter "Arbeiten für 0 €:" aus dem Nachtbericht."""
    if _FREI_KOPF not in text:
        return []
    teil = text.split(_FREI_KOPF, 1)[1]
    zeilen = []
    for z in teil.splitlines():
        z = z.strip()
        if not z:
            if zeilen:
                break
            continue
        if not z.startswith("- "):
            break
        zeilen.append(z[2:].strip())
    return zeilen


def _bericht(datum: str) -> dict | None:
    for v in vorschlaege.liste(None):  # neueste zuerst
        if v.get("quelle") == "nachtarbeit" and str(v.get("titel") or "") == f"Nachtbericht {datum}":
            return v
    return None


def _kurz(text: str, zeichen: int = 110) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= zeichen else text[:zeichen].rsplit(" ", 1)[0] + " …"


def kurz(heute: datetime.date | None = None) -> dict[str, Any]:
    datum = (heute or _heute()).isoformat()
    try:
        dieser = [e for e in nachtarbeit._eintraege() if e.get("datum") == datum]  # noqa: SLF001
    except Exception:  # noqa: BLE001 - Protokoll unlesbar: wie "nicht gelaufen" behandeln
        dieser = []
    letzte = dieser[-1] if dieser else (nachtarbeit.letzte_nacht() or {})
    gelaufen = letzte.get("datum") == datum
    auftraege = _auftraege_der_nacht(datum)
    bericht = _bericht(datum)
    frei = _frei_zeilen(str(bericht.get("text") or "")) if bericht else []

    punkte: list[str] = []
    if not gelaufen:
        punkte.append("Die Nachtarbeit ist heute Nacht nicht gelaufen." + (
            f" Letzter Lauf: {letzte['datum']}." if letzte.get("datum") else ""))
    elif letzte.get("status") not in (None, "durchgefuehrt"):
        grund = letzte.get("grund") or letzte.get("fehler") or letzte.get("status")
        punkte.append(f"Die Nachtarbeit wurde übersprungen: {_kurz(str(grund))}")
    elif letzte.get("fehler"):
        punkte.append(f"Die Nachtarbeit meldet einen Fehler: {_kurz(str(letzte['fehler']))}")
    try:   # P24: Alarm der GPU-Miete steht ganz oben
        from . import gpu_miete

        alarm = gpu_miete.alarm_lesen()
    except Exception:  # noqa: BLE001
        alarm = None
    if alarm:
        punkte.insert(0, f"ACHTUNG GPU-Miete: {_kurz(str(alarm.get('text', '')), 140)} Bitte in der RunPod-Konsole nachsehen.")
    for a in auftraege:
        satz = f"Auftrag Nr. {a['nr']} „{_kurz(a['titel'], 70)}“: {STATUS_TEXT.get(a['status'], a['status'])}"
        if a["urteil"]:
            satz += f", Prüfung: {a['urteil']}"
        if a["status"] == "fehler" and a["fehler"]:
            satz += f" ({_kurz(a['fehler'], 60).rstrip('.')})"
        punkte.append(satz + ".")
    for z in frei:
        punkte.append(_kurz(z))
    if gelaufen and not auftraege and not frei and len(punkte) == 0:
        punkte.append("Die Nachtarbeit lief, es gab aber nichts Neues zu tun.")
    kosten = letzte.get("kosten_usd") if gelaufen else None
    return {
        "datum": datum, "gelaufen": gelaufen, "status": letzte.get("status"), "kosten_usd": kosten,
        "fehler": letzte.get("fehler"), "punkte": punkte[:MAX_PUNKTE], "auftraege": auftraege,
        "bericht_id": bericht.get("id") if bericht else None,
    }

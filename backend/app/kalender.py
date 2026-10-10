"""Termine aus dem Google-Kalender holen (iCal/ICS).

Die geheime iCal-Adresse steht in der .env als KALENDER_ICS_URL
(Google Kalender -> Einstellungen -> Kalender integrieren -> "Geheime Adresse
im iCal-Format"). Wer diese Adresse hat, kann den Kalender lesen - sie wird
deshalb nirgends ausgegeben, auch nicht in Fehlermeldungen.

Absichtlich ohne Zusatzpakete: `requests` und `python-dateutil` sind im venv
bereits vorhanden, `icalendar` und `recurring-ical-events` wären zwei weitere
Abhängigkeiten für eine Aufgabe, die hier in rund 150 Zeilen erledigt ist.

Das Ergebnis wird zwischengespeichert (CACHE_S, Standard 15 Minuten), damit
nicht jeder Aufruf des HUD bei Google landet.
"""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import date, datetime, timedelta

import requests
from dateutil import rrule as _rrule
from dateutil import tz

CACHE_S = 15 * 60
# Öffentlicher Feiertagskalender von Google (keine geheime Adresse nötig).
# Abschaltbar mit FEIERTAGE_ICS_URL=aus in der .env, ersetzbar durch eine
# andere Adresse (z.B. ein anderes Bundesland oder Land).
FEIERTAGE_STD = (
    "https://calendar.google.com/calendar/ical/"
    "de.german%23holiday%40group.v.calendar.google.com/public/basic.ics"
)
TAGE_VORAUS = 90
TAGE_ZURUECK = 7
ZEITZONE = tz.gettz("Europe/Berlin")

_sperre = threading.Lock()
_cache: dict | None = None
_cache_zeit = 0.0


class KalenderFehler(RuntimeError):
    """Abruf oder Auswertung fehlgeschlagen (ohne die Adresse zu nennen)."""


def ics_url() -> str:
    return (os.getenv("KALENDER_ICS_URL") or "").strip().strip('"').strip("'")


def feiertage_url() -> str:
    wert = (os.getenv("FEIERTAGE_ICS_URL") or FEIERTAGE_STD).strip().strip('"').strip("'")
    return "" if wert.lower() in ("aus", "nein", "false", "off", "0") else wert


def ist_eingerichtet() -> bool:
    return bool(ics_url())


# ---------------------------------------------------------------- ICS lesen

def _zeilen_entfalten(text: str) -> list[str]:
    """Fortsetzungszeilen (beginnen mit Leerzeichen oder Tab) anhaengen."""
    zeilen: list[str] = []
    for roh in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if roh[:1] in (" ", "\t") and zeilen:
            zeilen[-1] += roh[1:]
        else:
            zeilen.append(roh)
    return zeilen


def _wert_entschaerfen(w: str) -> str:
    return (w.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",")
             .replace("\;", ";").replace("\\\\", "\\").strip())


def _zeit_lesen(wert: str, params: dict[str, str]):
    """Gibt datetime (zeitzonenbehaftet) oder date (ganztaegig) zurueck."""
    wert = wert.strip()
    if params.get("VALUE") == "DATE" or (len(wert) == 8 and wert.isdigit()):
        return datetime.strptime(wert[:8], "%Y%m%d").date()
    if wert.endswith("Z"):
        roh = datetime.strptime(wert, "%Y%m%dT%H%M%SZ").replace(tzinfo=tz.UTC)
        return roh.astimezone(ZEITZONE)
    zone = tz.gettz(params["TZID"]) if params.get("TZID") else ZEITZONE
    return datetime.strptime(wert[:15], "%Y%m%dT%H%M%S").replace(tzinfo=zone or ZEITZONE)


def _params(teil: str) -> tuple[str, dict[str, str]]:
    name, *rest = teil.split(";")
    werte = {}
    for p in rest:
        if "=" in p:
            k, v = p.split("=", 1)
            werte[k.upper()] = v.strip('"')
    return name.upper(), werte


def ics_zerlegen(text: str) -> list[dict]:
    """VEVENT-Bloecke in einfache Dicts umwandeln (VTIMEZONE wird uebersprungen)."""
    termine: list[dict] = []
    aktuell: dict | None = None
    tiefe_fremd = 0
    for zeile in _zeilen_entfalten(text):
        if zeile.startswith("BEGIN:VEVENT"):
            aktuell = {"exdate": []}
            continue
        if zeile.startswith("END:VEVENT"):
            if aktuell and aktuell.get("start") is not None:
                termine.append(aktuell)
            aktuell = None
            continue
        if zeile.startswith("BEGIN:") and aktuell is None:
            if not zeile.startswith("BEGIN:VCALENDAR"):
                tiefe_fremd += 1
            continue
        if zeile.startswith("END:") and aktuell is None:
            if tiefe_fremd:
                tiefe_fremd -= 1
            continue
        if aktuell is None or tiefe_fremd or ":" not in zeile:
            continue

        kopf, wert = zeile.split(":", 1)
        name, par = _params(kopf)
        if name == "SUMMARY":
            aktuell["titel"] = _wert_entschaerfen(wert)
        elif name == "LOCATION":
            aktuell["ort"] = _wert_entschaerfen(wert)
        elif name == "DTSTART":
            aktuell["start"] = _zeit_lesen(wert, par)
        elif name == "DTEND":
            aktuell["ende"] = _zeit_lesen(wert, par)
        elif name == "RRULE":
            aktuell["rrule"] = wert.strip()
        elif name == "EXDATE":
            for einzel in wert.split(","):
                aktuell["exdate"].append(_zeit_lesen(einzel, par))
        elif name == "RECURRENCE-ID":
            aktuell["recurrence_id"] = _zeit_lesen(wert, par)
        elif name == "UID":
            aktuell["uid"] = wert.strip()
        elif name == "STATUS":
            aktuell["status"] = wert.strip().upper()
    return termine


# ------------------------------------------------------- Wiederholungen

def _als_datetime(w):
    if isinstance(w, datetime):
        return w
    return datetime(w.year, w.month, w.day, tzinfo=ZEITZONE)


def _termine_ausrollen(roh: list[dict], von: datetime, bis: datetime) -> list[dict]:
    """Serien wie "Arbeit" in einzelne Termine aufloesen.

    Einzeln geaenderte Termine einer Serie (RECURRENCE-ID) ersetzen den
    berechneten Termin an dieser Stelle - sonst stuende er doppelt im HUD."""
    ausnahmen: dict[tuple, dict] = {}
    for t in roh:
        if t.get("recurrence_id") is not None and t.get("uid"):
            ausnahmen[(t["uid"], _als_datetime(t["recurrence_id"]).strftime("%Y%m%dT%H%M"))] = t

    ergebnis: list[dict] = []
    for t in roh:
        if t.get("status") == "CANCELLED":
            continue
        if t.get("recurrence_id") is not None:
            if von <= _als_datetime(t["start"]) <= bis:
                ergebnis.append(t)
            continue

        if not t.get("rrule"):
            if von <= _als_datetime(t["start"]) <= bis:
                ergebnis.append(t)
            continue

        start = t["start"]
        ganztags = not isinstance(start, datetime)
        dauer = None
        if t.get("ende") is not None:
            dauer = _als_datetime(t["ende"]) - _als_datetime(start)

        try:
            regel = _rrule.rrulestr(t["rrule"], dtstart=_als_datetime(start))
        except Exception:  # noqa: BLE001 - eine kaputte Regel darf den Rest nicht kippen
            continue

        raus = {_als_datetime(x).strftime("%Y%m%dT%H%M") for x in t.get("exdate", [])}
        for zeitpunkt in regel.between(von, bis, inc=True):
            schluessel = zeitpunkt.strftime("%Y%m%dT%H%M")
            if schluessel in raus:
                continue
            if t.get("uid") and (t["uid"], schluessel) in ausnahmen:
                continue  # dieser Termin wurde einzeln geaendert, siehe oben
            neu = dict(t)
            neu.pop("rrule", None)
            neu["start"] = zeitpunkt.date() if ganztags else zeitpunkt
            neu["ende"] = (zeitpunkt + dauer) if dauer is not None else None
            if ganztags and neu["ende"] is not None:
                neu["ende"] = (zeitpunkt + dauer).date()
            ergebnis.append(neu)
    return ergebnis


def _formatieren(t: dict) -> dict:
    def txt(w):
        if w is None:
            return ""
        if isinstance(w, datetime):
            return w.strftime("%Y-%m-%dT%H:%M")
        return w.strftime("%Y-%m-%d")
    return {
        "titel": t.get("titel", "(ohne Titel)"),
        "start": txt(t.get("start")),
        "ende": txt(t.get("ende")),
        "ort": t.get("ort", ""),
        "kategorie": t.get("kategorie", "termin"),
    }


# ------------------------------------------------------------- Abruf

def _laden(url: str) -> str:
    try:
        antwort = requests.get(url, timeout=30)
        antwort.raise_for_status()
        antwort.encoding = antwort.encoding or "utf-8"
        return antwort.text
    except requests.RequestException as exc:
        # Die Adresse selbst darf nicht in der Meldung landen
        grund = type(exc).__name__
        status = getattr(getattr(exc, "response", None), "status_code", None)
        raise KalenderFehler(f"Kalender nicht abrufbar ({grund}{f', HTTP {status}' if status else ''})") from exc


def abrufen(text: str | None = None) -> dict:
    """Termine aufbereiten. Mit `text` wird dieser ICS-Inhalt genommen (Tests),
    sonst der eigene Kalender plus - wenn eingeschaltet - die Feiertage."""
    jetzt = datetime.now(ZEITZONE)
    von = jetzt - timedelta(days=TAGE_ZURUECK)
    bis = jetzt + timedelta(days=TAGE_VORAUS)

    quellen: list[tuple[str, str]] = []
    if text is not None:
        quellen.append((text, "termin"))
    else:
        url = ics_url()
        if not url:
            raise KalenderFehler("KALENDER_ICS_URL ist nicht gesetzt (.env)")
        quellen.append((_laden(url), "termin"))
        feiertage = feiertage_url()
        if feiertage:
            try:
                quellen.append((_laden(feiertage), "feiertag"))
            except KalenderFehler:
                pass  # Feiertage sind Beiwerk - der eigene Kalender zählt

    termine: list[dict] = []
    for inhalt, kategorie in quellen:
        for eintrag in _termine_ausrollen(ics_zerlegen(inhalt), von, bis):
            eintrag["kategorie"] = kategorie
            termine.append(eintrag)

    termine.sort(key=lambda t: _als_datetime(t["start"]))
    return {
        "stand": jetzt.strftime("%d.%m.%Y %H:%M"),
        "quelle": "Google Kalender (iCal), automatisch abgerufen",
        "feiertage": bool(text is None and feiertage_url()),
        "termine": [_formatieren(t) for t in termine],
    }


def hole(erzwingen: bool = False) -> dict:
    """Zwischengespeicherte Fassung, hoechstens alle CACHE_S Sekunden neu."""
    global _cache, _cache_zeit
    with _sperre:
        frisch = _cache is not None and (time.time() - _cache_zeit) < CACHE_S
        if frisch and not erzwingen:
            return _cache
        daten = abrufen()
        _cache, _cache_zeit = daten, time.time()
        return daten

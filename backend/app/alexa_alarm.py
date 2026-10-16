"""
Alexa-Benachrichtigung für Alarme (P24b, 16.10.2026, Claude Code). UNGETESTET gegen echtes Alexa.

Was Amazon erlaubt (Stand Dokumentation, nachgelesen 16.10.2026) und was nicht:
- Eine ECHTE Erinnerung wie bei einem Termin (Reminders API) kann ein Skill nur INNERHALB einer Sitzung anlegen
  (mit dem Zugriffstoken aus der Anfrage). Außerhalb einer Sitzung geht nur Ändern/Löschen. Auron kann also nachts
  keine neue Erinnerung anlegen. Deshalb wird sie hier NICHT benutzt.
- Möglich ist die Benachrichtigung (Proactive Events API, Ereignis AMAZON.MessageAlert.Activated): Das Echo zeigt den
  gelben Ring und sagt auf Nachfrage ("Alexa, was gibt es Neues?" / "Benachrichtigungen"): "Du hast 1 neue ungelesene
  Nachricht von <Name>". Frei wählbar ist nur der Absendername (<Name>). Einen Satz Text gibt es nicht; die Einzelheiten
  nennt dann "Computer, frag Agent Auron nach dem Status". Ob das Ereignis für de-DE angeboten wird, ist aus der
  Dokumentation nicht eindeutig. Das muss der erste Versuch zeigen.

Voraussetzungen (einmalig, von Sir; Schritte in projekt-aufgaben/UEBERGABE P24b.md):
  - Skill-Manifest: Berechtigung alexa::devices:all:notifications:write und events.publications mit
    AMAZON.MessageAlert.Activated; in der Alexa-App für den Skill "Benachrichtigungen" erlauben.
  - ALEXA_ALARM_CLIENT_ID und ALEXA_ALARM_CLIENT_SECRET in der .env (Zugangsdaten des Skills, Login with Amazon).
  - Die userId von Sir: ALEXA_NUTZER_ID aus der .env, sonst lernt Auron sie aus der ersten Alexa-Anfrage selbst
    (data/alexa_nutzer.json, nur die Kennung).
Region: ALEXA_ALARM_REGION=EU (Standard), NA oder FE. Stufe: ALEXA_ALARM_STUFE=development (Standard, solange der Skill im
Entwicklungsmodus ist) oder live. Aus: ALEXA_ALARM_AUS=1.

Geheimnisse: Client-Secret und Token werden nie geloggt und nie in Fehlertexte geschrieben.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests

from . import fehlerbericht, geraeteschutz

TOKEN_URL = "https://api.amazon.com/auth/o2/token"
HOSTS = {"NA": "api.amazonalexa.com", "EU": "api.eu.amazonalexa.com", "FE": "api.fe.amazonalexa.com"}
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
ABSENDER_MAX = 40
_USER_ID = re.compile(r"^amzn1\.ask\.account\.[A-Za-z0-9._-]{10,}$")

_lock = threading.Lock()
_token: dict = {"wert": None, "bis": 0.0}


def _nutzer_pfad() -> Path:
    return Path(os.getenv("ALEXA_NUTZER_PATH") or Path(__file__).resolve().parents[2] / "data" / "alexa_nutzer.json")


def nutzer_merken(user_id: str) -> None:
    """Die Alexa-Kennung von Sir aus einer geprüften Anfrage merken (nur die Kennung, keine Inhalte). Wirft nie."""
    try:
        if not _USER_ID.match(user_id or "") or nutzer() == user_id:
            return
        p = _nutzer_pfad()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"user_id": user_id}), encoding="utf-8")
    except OSError:
        pass


def nutzer() -> str | None:
    """Alexa-Kennung von Sir: ALEXA_NUTZER_ID aus der .env (falls dort eingetragen), sonst die gelernte."""
    fest = (os.getenv("ALEXA_NUTZER_ID") or "").strip()
    if _USER_ID.match(fest):
        return fest
    try:
        d = json.loads(_nutzer_pfad().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    uid = d.get("user_id") if isinstance(d, dict) else None
    return uid if isinstance(uid, str) and _USER_ID.match(uid) else None


def _zugang() -> tuple[str, str]:
    return (os.getenv("ALEXA_ALARM_CLIENT_ID") or "").strip(), (os.getenv("ALEXA_ALARM_CLIENT_SECRET") or "").strip()


def eingerichtet() -> bool:
    cid, secret = _zugang()
    aus = (os.getenv("ALEXA_ALARM_AUS") or "").strip().lower() in ("1", "ja", "true")
    return bool(cid and secret and nutzer()) and not aus


def fehlt() -> str:
    """Was zur Einrichtung noch fehlt, in einfachen Worten (für Status und Doku)."""
    cid, secret = _zugang()
    fehlend = []
    if not (cid and secret):
        fehlend.append("ALEXA_ALARM_CLIENT_ID und ALEXA_ALARM_CLIENT_SECRET in der .env")
    if not nutzer():
        fehlend.append("eine erste Anfrage an den Alexa-Skill (damit Auron Ihre Alexa-Kennung lernt)")
    return ", ".join(fehlend)


def _loopback_oder(wunsch: str, standard: str) -> str:
    """Eine andere Adresse als die von Amazon gilt nur für 127.0.0.1 (Test-Stub)."""
    w = (wunsch or "").strip()
    return w if w and (urlparse(w).hostname or "").lower() in LOOPBACK else standard


def _sauber(text: object) -> str:
    t = str(text or "")
    for geheim in _zugang():
        if geheim:
            t = t.replace(geheim, "***")
    if _token["wert"]:
        t = t.replace(_token["wert"], "***")
    return fehlerbericht.saeubern(t)[:200]


def _event_url() -> str:
    region = (os.getenv("ALEXA_ALARM_REGION") or "EU").strip().upper()
    host = HOSTS.get(region, HOSTS["EU"])
    live = (os.getenv("ALEXA_ALARM_STUFE") or "development").strip().lower() == "live"
    standard = f"https://{host}/v1/proactiveEvents/" + ("" if live else "stages/development")
    return _loopback_oder(os.getenv("ALEXA_ALARM_EVENT_URL", ""), standard)


def _zugriffstoken() -> str:
    """LWA-Token mit dem Bereich alexa::proactive_events (wird bis kurz vor Ablauf wiederverwendet)."""
    with _lock:
        if _token["wert"] and time.time() < _token["bis"] - 60:
            return _token["wert"]
    cid, secret = _zugang()
    url = _loopback_oder(os.getenv("ALEXA_ALARM_TOKEN_URL", ""), TOKEN_URL)
    geraeteschutz.netz_pruefen(url, "Alexa-Anmeldung (Login with Amazon)")
    try:
        r = requests.post(url, data={"grant_type": "client_credentials", "client_id": cid, "client_secret": secret,
                                     "scope": "alexa::proactive_events"}, timeout=(5, 15))
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Anmeldung bei Amazon nicht möglich: {type(exc).__name__}") from None
    if r.status_code != 200:
        raise RuntimeError(f"Amazon hat die Anmeldung abgelehnt (HTTP {r.status_code}): Client-ID und Secret prüfen.")
    try:
        d = r.json()
        wert, dauer = str(d["access_token"]), float(d.get("expires_in") or 3600)
    except (ValueError, KeyError, TypeError):
        raise RuntimeError("Amazon-Antwort bei der Anmeldung nicht lesbar.") from None
    with _lock:
        _token.update(wert=wert, bis=time.time() + dauer)
    return wert


def absender_name(namen: list[str]) -> str:
    """Der frei wählbare Name in "Du hast 1 neue ungelesene Nachricht von <Name>"."""
    if len(namen) == 1:
        basis = f"Auron Alarm {namen[0]}"
    else:
        basis = "Auron Alarm"
    return basis[:ABSENDER_MAX].strip()


def senden(namen: list[str], jetzt: datetime.datetime | None = None) -> tuple[bool, str]:
    """Eine Benachrichtigung an Sirs Echo schicken. Rückgabe (gesendet, Text). Wirft nie."""
    if not eingerichtet():
        return False, "Alexa-Alarm nicht eingerichtet: " + (fehlt() or "ausgeschaltet")
    jetzt = (jetzt or datetime.datetime.now(datetime.timezone.utc)).astimezone(datetime.timezone.utc)
    body = {
        "timestamp": jetzt.strftime("%Y-%m-%dT%H:%M:%S.00Z"),
        "referenceId": f"auron-{uuid.uuid4().hex[:16]}",
        "expiryTime": (jetzt + datetime.timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%S.00Z"),
        "event": {"name": "AMAZON.MessageAlert.Activated", "payload": {
            "state": {"status": "UNREAD", "freshness": "NEW"},
            "messageGroup": {"creator": {"name": absender_name(namen)}, "count": max(1, len(namen))}}},
        "relevantAudience": {"type": "Unicast", "payload": {"user": nutzer()}},
    }
    url = _event_url()
    try:
        token = _zugriffstoken()
        geraeteschutz.netz_pruefen(url, "Alexa-Benachrichtigung")
        r = requests.post(url, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=(5, 15))
    except RuntimeError as exc:
        return False, _sauber(exc)
    except requests.exceptions.RequestException as exc:
        return False, f"Alexa-Benachrichtigung nicht gesendet: {type(exc).__name__}"
    if r.status_code == 202:
        return True, "Alexa-Benachrichtigung gesendet."
    if r.status_code == 401:
        with _lock:
            _token.update(wert=None, bis=0.0)   # nächster Versuch holt ein neues Token
    hinweis = {400: "Amazon lehnt die Angaben ab (Ereignis oder Region für diese Sprache nicht erlaubt?)",
               401: "Anmeldung abgelaufen oder ungültig", 403: "Amazon verbietet das Senden (Berechtigung im Manifest fehlt?)",
               429: "zu viele Anfragen", 432: "Benachrichtigungslimit des Kunden erreicht"}.get(r.status_code, "Fehler bei Amazon")
    return False, f"Alexa-Benachrichtigung nicht gesendet (HTTP {r.status_code}): {hinweis}. {_sauber(r.text)}".strip()

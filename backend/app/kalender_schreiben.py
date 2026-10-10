"""Termine im Google-Kalender ANLEGEN (Schreibzugriff, 22.09.2026).

Getrennt von kalender.py (das liest nur über die geheime iCal-Adresse, ohne
Anmeldung). Hier braucht es echten Schreibzugriff über die Google Calendar
API mit OAuth - andere Technik, anderes Risiko: ein Bug hier kann echte
Termine im Kalender von Sir anlegen. Deshalb bewusst eng gehalten:
- Scope nur "calendar.events" (Termine lesen/anlegen/ändern), NICHT der volle
  "calendar"-Scope - Jarvis darf keine Kalender selbst anlegen oder löschen.
- Diese Datei kann nur ANLEGEN (termin_anlegen), kein Löschen und kein Ändern
  bestehender Termine. Das kommt erst, wenn Sir es ausdrücklich will.
- Eine Chat-Anbindung ("Jarvis legt per Sprache einen Termin an") ist bewusst
  NICHT Teil dieser Datei - das ist ein späterer Schritt mit eigener
  Bestätigungslogik. Hier steht nur der Baustein plus ein Testweg über die API.

Einrichtung (einmalig, Sir in der Google Cloud Console):
1. console.cloud.google.com -> neues Projekt anlegen (z.B. "Jarvis")
2. APIs & Dienste -> Bibliothek -> "Google Calendar API" suchen, aktivieren
3. APIs & Dienste -> OAuth-Zustimmungsbildschirm: Nutzertyp "Extern", Status
   "Testing" reicht (keine Google-Prüfung nötig), Sir selbst als Testnutzer
   eintragen
4. APIs & Dienste -> Anmeldedaten -> Anmeldedaten erstellen -> OAuth-Client-ID
   -> Anwendungstyp "Desktop-App"
5. Client-ID und Client-Secret über GOOGLE_KALENDER_ZUGANG_SETZEN.bat in die
   .env eintragen, Backend neu starten
6. http://127.0.0.1:8000/api/kalender-schreiben/login im Browser öffnen,
   Google-Konto wählen, bestätigen - die Rückleitungsseite zeigt den
   Refresh-Token zum Eintragen über GOOGLE_KALENDER_TOKEN_SETZEN.bat

Zugangsdaten in der .env:
    GOOGLE_CLIENT_ID=...
    GOOGLE_CLIENT_SECRET=...
    GOOGLE_CALENDAR_REFRESH_TOKEN=...   (kommt aus /api/kalender-schreiben/login)
    GOOGLE_CALENDAR_ID=...              (optional, Standard "primary" = Hauptkalender)

Absichtlich ohne Zusatzpaket (kein google-api-python-client): requests ist
im venv schon da und reicht für die Handvoll REST-Aufrufe - gleiches Muster
wie app/spotify.py.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"
TIMEOUT = 8
# Bewusst eng: nur Termine, nicht die Kalenderverwaltung selbst.
SCOPE = "https://www.googleapis.com/auth/calendar.events"
ZEITZONE = "Europe/Berlin"
STANDARD_DAUER = timedelta(hours=1)


class KalenderSchreibenFehler(RuntimeError):
    """Abruf oder Schreibbefehl fehlgeschlagen (ohne Zugangsdaten zu nennen)."""


# ---------------------------------------------------------------- Zugangsdaten

def _wert(name: str) -> str:
    return (os.getenv(name) or "").strip().strip('"').strip("'")


def client_id() -> str:
    return _wert("GOOGLE_CLIENT_ID")


def client_secret() -> str:
    return _wert("GOOGLE_CLIENT_SECRET")


def refresh_token() -> str:
    return _wert("GOOGLE_CALENDAR_REFRESH_TOKEN")


def redirect_uri() -> str:
    return _wert("GOOGLE_CALENDAR_REDIRECT_URI") or "http://127.0.0.1:8000/api/kalender-schreiben/callback"


def kalender_id() -> str:
    return _wert("GOOGLE_CALENDAR_ID") or "primary"


def ist_eingerichtet() -> bool:
    return bool(client_id() and client_secret() and refresh_token())


# ------------------------------------------------------- Einmalige Anmeldung

def login_url() -> str:
    """Adresse, die Sir einmal im Browser öffnet, um Jarvis freizugeben.

    access_type=offline + prompt=consent, damit Google WIRKLICH einen
    refresh_token liefert (ohne prompt=consent bekommt man beim zweiten
    Versuch mit demselben Konto oft keinen neuen mehr)."""
    if not client_id():
        raise KalenderSchreibenFehler("GOOGLE_CLIENT_ID fehlt in der .env.")
    return AUTH + "?" + urlencode(
        {
            "client_id": client_id(),
            "response_type": "code",
            "redirect_uri": redirect_uri(),
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        }
    )


def code_einloesen(code: str) -> str:
    """Tauscht den Code aus der Rückleitung gegen den Erneuerungs-Schlüssel."""
    antwort = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id(),
            "client_secret": client_secret(),
            "redirect_uri": redirect_uri(),
        },
        timeout=TIMEOUT,
    )
    if antwort.status_code != 200:
        raise KalenderSchreibenFehler(f"Google lehnte den Code ab (HTTP {antwort.status_code}).")
    daten = antwort.json()
    neuer = daten.get("refresh_token")
    if not neuer:
        raise KalenderSchreibenFehler(
            "Google lieferte keinen refresh_token. Vermutlich wurde der Zugriff schon einmal "
            "freigegeben - unter myaccount.google.com/permissions den Zugriff für diese App "
            "entziehen und /api/kalender-schreiben/login erneut öffnen."
        )
    return neuer


# ------------------------------------------------------------------- Aufrufe

def _access_token() -> str:
    """Kurzlebiges Zugangsticket über den Refresh-Token - wird nicht gecacht,
    weil termin_anlegen() selten genug aufgerufen wird, dass es nicht auffällt."""
    if not ist_eingerichtet():
        raise KalenderSchreibenFehler(
            "Kalender-Schreibzugriff ist nicht eingerichtet. GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET "
            "und GOOGLE_CALENDAR_REFRESH_TOKEN in die .env eintragen."
        )
    antwort = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token(),
            "client_id": client_id(),
            "client_secret": client_secret(),
        },
        timeout=TIMEOUT,
    )
    if antwort.status_code != 200:
        raise KalenderSchreibenFehler(
            f"Google-Anmeldung fehlgeschlagen (HTTP {antwort.status_code}). Vermutlich ist der "
            "Refresh-Token ungültig - neu anmelden über /api/kalender-schreiben/login."
        )
    token = antwort.json().get("access_token")
    if not token:
        raise KalenderSchreibenFehler("Google lieferte kein access_token.")
    return token


def _iso(zeitpunkt: datetime) -> str:
    return zeitpunkt.strftime("%Y-%m-%dT%H:%M:%S")


def termin_anlegen(
    titel: str,
    start: datetime,
    ende: datetime | None = None,
    ort: str = "",
    beschreibung: str = "",
) -> dict:
    """Legt einen Termin im Google-Kalender an. Ohne Ende: eine Stunde Dauer.

    Gibt u.a. 'id' und 'link' (htmlLink) zurück - der Link zeigt den Termin
    direkt in Google Kalender, nützlich zum Gegenprüfen ohne Rätselraten.
    KEIN Löschen, KEIN Ändern bestehender Termine - nur Anlegen."""
    titel = (titel or "").strip()
    if not titel:
        raise KalenderSchreibenFehler("Kein Titel angegeben.")
    if start.tzinfo is not None:
        start = start.replace(tzinfo=None)
    if ende is None:
        ende = start + STANDARD_DAUER
    elif ende.tzinfo is not None:
        ende = ende.replace(tzinfo=None)
    if ende <= start:
        raise KalenderSchreibenFehler("Das Ende muss nach dem Start liegen.")

    koerper: dict = {
        "summary": titel,
        "start": {"dateTime": _iso(start), "timeZone": ZEITZONE},
        "end": {"dateTime": _iso(ende), "timeZone": ZEITZONE},
    }
    if ort:
        koerper["location"] = ort
    if beschreibung:
        koerper["description"] = beschreibung

    antwort = requests.post(
        f"{API}/calendars/{kalender_id()}/events",
        headers={"Authorization": f"Bearer {_access_token()}"},
        json=koerper,
        timeout=TIMEOUT,
    )
    if antwort.status_code not in (200, 201):
        raise KalenderSchreibenFehler(
            f"Google lehnte den Termin ab (HTTP {antwort.status_code}): {antwort.text[:200]}"
        )
    daten = antwort.json()
    return {
        "id": daten.get("id", ""),
        "titel": daten.get("summary", titel),
        "start": start.strftime("%d.%m.%Y %H:%M"),
        "ende": ende.strftime("%d.%m.%Y %H:%M"),
        "link": daten.get("htmlLink", ""),
    }


def stand() -> dict:
    """Für das HUD: ist der Schreibzugriff eingerichtet."""
    if not ist_eingerichtet():
        return {
            "eingerichtet": False,
            "hinweis": "GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET und GOOGLE_CALENDAR_REFRESH_TOKEN fehlen in der .env.",
        }
    return {"eingerichtet": True, "kalender_id": kalender_id()}

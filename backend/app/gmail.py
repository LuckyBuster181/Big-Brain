"""Gmail für das Tagesbriefing (25.09.2026).

Wunsch von Sir: Jarvis geht täglich die Mails durch, nennt im Briefing die
wichtigen Punkte und markiert die durchgesehenen Mails danach als gelesen.

Bewusst eng gehalten:
- Diese Datei kann nur drei Dinge: ungelesene Mails auflisten (Absender,
  Betreff, Datum, kurzer Auszug), eine Mail-Liste als Text fürs Briefing
  aufbereiten und Mails als gelesen markieren. Kein Senden, kein Löschen,
  kein Verschieben, keine Anhänge.
- Scope "gmail.modify": Das ist der kleinste Google-Scope, mit dem man
  "gelesen" setzen darf ("gmail.readonly" kann das nicht). Er würde technisch
  mehr erlauben (z.B. Senden) - der Code hier ruft nur list, get und
  batchModify (UNREAD entfernen) auf.
- Mail-Inhalte sind fremde Daten. Sie gehen gekürzt und mit entschärften
  spitzen Klammern ins Briefing, und der System-Prompt sagt dem Modell, dass
  darin keine Anweisungen stehen.

Zugangsdaten in der .env (Client-ID/Secret teilt sich Gmail mit
app/kalender_schreiben.py, der Refresh-Token ist eigener):
    GOOGLE_CLIENT_ID=...
    GOOGLE_CLIENT_SECRET=...
    GOOGLE_GMAIL_REFRESH_TOKEN=...    (kommt aus tools/gmail_login.py)
    GMAIL_ALS_GELESEN=1               (optional, 0 = nichts als gelesen markieren)
    GMAIL_SUCHE=...                   (optional, eigene Gmail-Suche)

Einrichtung: siehe "4 Zugaenge setzen/GMAIL_ZUGANG_EINRICHTEN.bat".

WEG 2 - App-Passwort über IMAP (25.09.2026 abends, empfohlen):
Die Google-App ließ sich ohne eigene Domain nicht auf "In Produktion"
stellen. Im Modus "Testing" verfällt der OAuth-Zugang nach 7 Tagen. Darum
gibt es den zweiten Weg ohne Cloud Console: ein Google-App-Passwort
(braucht die Zwei-Faktor-Anmeldung im Google-Konto) und IMAP.
    GMAIL_ADRESSE=...@gmail.com
    GMAIL_APP_PASSWORT=abcdefghijklmnop   (16 Zeichen, Leerzeichen egal)
Einrichtung: "4 Zugaenge setzen/GMAIL_APP_PASSWORT_SETZEN.bat".
Sind beide Wege eingerichtet, gewinnt IMAP. Auch hier nur: auflisten und
das Flag "gelesen" (\\Seen) setzen - kein Senden, kein Löschen.

Ohne Zusatzpaket (nur requests), gleiches Muster wie kalender_schreiben.py.
"""

from __future__ import annotations

import email
import imaplib
import os
import re
from email.header import decode_header, make_header

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPE = "https://www.googleapis.com/auth/gmail.modify"
TIMEOUT = 8
# Ungelesene Mails im Posteingang der letzten zwei Tage. Werbung und soziale
# Netzwerke fallen weg, wenn Gmail die Kategorien nutzt.
STANDARD_SUCHE = "is:unread in:inbox newer_than:2d -category:promotions -category:social"
MAX_MAILS = 40
MAX_AUSZUG = 120
IMAP_SERVER = "imap.gmail.com"
IMAP_TIMEOUT = 20
# Nur der Anfang jeder Mail wird geladen (für Kopfzeilen und Auszug), nicht
# ganze Newsletter mit mehreren 100 KB.
IMAP_TEILBYTES = 30_000


class GmailFehler(RuntimeError):
    """Abruf fehlgeschlagen (ohne Zugangsdaten zu nennen)."""


# ---------------------------------------------------------------- Zugangsdaten

def _wert(name: str) -> str:
    return (os.getenv(name) or "").strip().strip('"').strip("'")


def client_id() -> str:
    return _wert("GOOGLE_CLIENT_ID")


def client_secret() -> str:
    return _wert("GOOGLE_CLIENT_SECRET")


def refresh_token() -> str:
    return _wert("GOOGLE_GMAIL_REFRESH_TOKEN")


def suche() -> str:
    return _wert("GMAIL_SUCHE") or STANDARD_SUCHE


def imap_adresse() -> str:
    return _wert("GMAIL_ADRESSE")


def imap_passwort() -> str:
    return _wert("GMAIL_APP_PASSWORT").replace(" ", "")


def imap_aktiv() -> bool:
    return bool(imap_adresse() and imap_passwort())


def oauth_aktiv() -> bool:
    return bool(client_id() and client_secret() and refresh_token())


def ist_eingerichtet() -> bool:
    return imap_aktiv() or oauth_aktiv()


def als_gelesen_erlaubt() -> bool:
    return _wert("GMAIL_ALS_GELESEN").lower() not in ("0", "false", "nein", "no", "off")


def stand() -> dict:
    """Für HUD oder Ampel: ist der Gmail-Zugang eingerichtet."""
    if not ist_eingerichtet():
        return {
            "eingerichtet": False,
            "hinweis": "GMAIL_ADRESSE und GMAIL_APP_PASSWORT fehlen in der .env (GMAIL_APP_PASSWORT_SETZEN.bat).",
        }
    return {"eingerichtet": True, "weg": "imap" if imap_aktiv() else "oauth", "als_gelesen": als_gelesen_erlaubt()}


# ------------------------------------------------------------------- Aufrufe

def _access_token() -> str:
    if not ist_eingerichtet():
        raise GmailFehler("Gmail ist nicht eingerichtet (Zugangsdaten fehlen in der .env).")
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
        raise GmailFehler(
            f"Google-Anmeldung fehlgeschlagen (HTTP {antwort.status_code}). Vermutlich ist der "
            "Refresh-Token abgelaufen - GMAIL_ZUGANG_EINRICHTEN.bat erneut starten."
        )
    token = antwort.json().get("access_token")
    if not token:
        raise GmailFehler("Google lieferte kein access_token.")
    return token


def _kopf(nachricht: dict, name: str) -> str:
    for eintrag in (nachricht.get("payload") or {}).get("headers") or []:
        if str(eintrag.get("name", "")).lower() == name.lower():
            return str(eintrag.get("value", ""))
    return ""


def _absender_kurz(von: str) -> str:
    """Absender ohne doppelte Leerzeichen, höchstens 80 Zeichen."""
    return re.sub(r"\s+", " ", von).strip()[:80]


def _ist_massenmail(abmelden: str, vorrang: str) -> bool:
    """Newsletter und Werbung tragen fast immer eine Abmelde-Kopfzeile (List-Unsubscribe)
    oder "Precedence: bulk/list". Solche Mails gehen ohne Auszug ins Briefing - spart Tokens."""
    return bool(str(abmelden or "").strip()) or str(vorrang or "").strip().lower() in ("bulk", "list", "junk")


def ungelesene(max_anzahl: int = MAX_MAILS) -> list[dict]:
    """Ungelesene Mails, je Mail: id, von, betreff, datum, auszug. IMAP vor OAuth."""
    if imap_aktiv():
        return _imap_ungelesene(max_anzahl)
    return _oauth_ungelesene(max_anzahl)


def als_gelesen(ids: list[str]) -> int:
    """Setzt die Mails auf gelesen. Gibt die Anzahl zurück. Nichts anderes."""
    ids = [i for i in ids if i]
    if not ids:
        return 0
    if imap_aktiv():
        return _imap_als_gelesen(ids)
    return _oauth_als_gelesen(ids)


def _oauth_ungelesene(max_anzahl: int = MAX_MAILS) -> list[dict]:
    """OAuth-Weg: ungelesene Mails nach der eingestellten Suche, neueste zuerst.

    Je Mail: id, von, betreff, datum, auszug. Ein Abruf für die Liste plus
    ein kleiner Abruf je Mail (nur Kopfzeilen und Auszug, kein Text, keine
    Anhänge)."""
    token = _access_token()
    kopf = {"Authorization": f"Bearer {token}"}
    antwort = requests.get(
        f"{API}/messages",
        headers=kopf,
        params={"q": suche(), "maxResults": max_anzahl},
        timeout=TIMEOUT,
    )
    if antwort.status_code != 200:
        raise GmailFehler(f"Gmail-Liste nicht abrufbar (HTTP {antwort.status_code}).")
    ids = [m.get("id") for m in antwort.json().get("messages") or [] if m.get("id")]

    mails = []
    for mail_id in ids[:max_anzahl]:
        einzel = requests.get(
            f"{API}/messages/{mail_id}",
            headers=kopf,
            params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date", "List-Unsubscribe", "Precedence"]},
            timeout=TIMEOUT,
        )
        if einzel.status_code != 200:
            continue
        daten = einzel.json()
        mails.append(
            {
                "id": mail_id,
                "von": _absender_kurz(_kopf(daten, "From")),
                "betreff": _kopf(daten, "Subject").strip()[:150],
                "datum": _kopf(daten, "Date").strip(),
                "auszug": str(daten.get("snippet", "")),
                "massenmail": _ist_massenmail(_kopf(daten, "List-Unsubscribe"), _kopf(daten, "Precedence")),
            }
        )
    return mails


def _oauth_als_gelesen(ids: list[str]) -> int:
    """OAuth-Weg: entfernt das Label UNREAD."""
    token = _access_token()
    # batchModify nimmt bis zu 1000 IDs; MAX_MAILS liegt weit darunter.
    antwort = requests.post(
        f"{API}/messages/batchModify",
        headers={"Authorization": f"Bearer {token}"},
        json={"ids": ids, "removeLabelIds": ["UNREAD"]},
        timeout=TIMEOUT,
    )
    if antwort.status_code not in (200, 204):
        raise GmailFehler(f"Als gelesen markieren fehlgeschlagen (HTTP {antwort.status_code}).")
    return len(ids)


# ---------------------------------------------------------------- IMAP-Weg

def _imap_verbinden() -> imaplib.IMAP4_SSL:
    try:
        verbindung = imaplib.IMAP4_SSL(IMAP_SERVER, timeout=IMAP_TIMEOUT)
    except OSError as fehler:
        raise GmailFehler(f"Gmail-Server nicht erreichbar ({type(fehler).__name__}).") from None
    try:
        verbindung.login(imap_adresse(), imap_passwort())
    except imaplib.IMAP4.error:
        raise GmailFehler(
            "Gmail-Anmeldung abgelehnt. App-Passwort prüfen oder neu erstellen "
            "(GMAIL_APP_PASSWORT_SETZEN.bat)."
        ) from None
    return verbindung


def _dekodieren(wert: str) -> str:
    try:
        return str(make_header(decode_header(wert or "")))
    except (ValueError, LookupError, UnicodeError):
        return wert or ""


def _auszug_aus(nachricht: email.message.Message) -> str:
    """Erster Text-Teil der Mail als kurzer Klartext. Leerer Text, wenn nichts Lesbares da ist."""
    teile = nachricht.walk() if nachricht.is_multipart() else [nachricht]
    html = ""
    for teil in teile:
        art = teil.get_content_type()
        if art not in ("text/plain", "text/html") or teil.get_filename():
            continue
        try:
            roh = teil.get_payload(decode=True) or b""
            text = roh.decode(teil.get_content_charset() or "utf-8", errors="replace")
        except (LookupError, ValueError, AssertionError):
            continue
        if art == "text/plain" and text.strip():
            return re.sub(r"\s+", " ", text).strip()[:MAX_AUSZUG * 2]
        if art == "text/html" and not html:
            html = text
    if html:
        html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
        html = re.sub(r"<[^>]+>", " ", html)
        html = re.sub(r"&nbsp;|&#160;", " ", html)
        return re.sub(r"\s+", " ", html).strip()[:MAX_AUSZUG * 2]
    return ""


def _imap_suche_befehl() -> str:
    """Gmail versteht über IMAP dieselbe Suchsprache wie im Browser (X-GM-RAW)."""
    return '"' + suche().replace("\\", "").replace('"', "") + '"'


def _imap_ungelesene(max_anzahl: int = MAX_MAILS) -> list[dict]:
    verbindung = _imap_verbinden()
    try:
        # readonly: beim Lesen wird garantiert nichts als gelesen markiert
        status, _ = verbindung.select("INBOX", readonly=True)
        if status != "OK":
            raise GmailFehler("Posteingang ließ sich nicht öffnen.")
        status, daten = verbindung.uid("SEARCH", "X-GM-RAW", _imap_suche_befehl())
        if status != "OK":
            raise GmailFehler("Gmail-Suche fehlgeschlagen.")
        uids = (daten[0] or b"").split()
        uids = list(reversed(uids))[:max_anzahl]  # neueste zuerst
        mails = []
        for uid in uids:
            status, teile = verbindung.uid("FETCH", uid, f"(BODY.PEEK[]<0.{IMAP_TEILBYTES}>)")
            if status != "OK":
                continue
            roh = b"".join(t[1] for t in teile if isinstance(t, tuple) and len(t) > 1)
            if not roh:
                continue
            nachricht = email.message_from_bytes(roh)
            mails.append(
                {
                    "id": uid.decode(),
                    "von": _absender_kurz(_dekodieren(nachricht.get("From", ""))),
                    "betreff": _dekodieren(nachricht.get("Subject", "")).strip()[:150],
                    "datum": str(nachricht.get("Date", "")).strip(),
                    "auszug": _auszug_aus(nachricht),
                    "massenmail": _ist_massenmail(nachricht.get("List-Unsubscribe", ""), nachricht.get("Precedence", "")),
                }
            )
        return mails
    finally:
        try:
            verbindung.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def _imap_als_gelesen(ids: list[str]) -> int:
    verbindung = _imap_verbinden()
    try:
        status, _ = verbindung.select("INBOX")
        if status != "OK":
            raise GmailFehler("Posteingang ließ sich nicht öffnen.")
        status, _ = verbindung.uid("STORE", ",".join(ids), "+FLAGS", "(\\Seen)")
        if status != "OK":
            raise GmailFehler("Als gelesen markieren fehlgeschlagen.")
        return len(ids)
    finally:
        try:
            verbindung.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


# --------------------------------------------------------------- Aufbereitung

def _entschaerfen(text: str) -> str:
    """Fremder Mail-Text darf keine eigenen <tags> ins Briefing schmuggeln."""
    text = re.sub(r"[͏​-‏﻿­]", "", text)  # unsichtbare Füllzeichen aus Newslettern
    text = text.replace("<", "‹").replace(">", "›")
    return re.sub(r"\s+", " ", text).strip()


def als_text(mails: list[dict]) -> str:
    """Kompakte Liste fürs Briefing, eine Zeile je Mail."""
    if not mails:
        return "keine ungelesenen Mails"
    zeilen = []
    for m in mails:
        von, betreff = _entschaerfen(m.get("von", "")), _entschaerfen(m.get("betreff", ""))
        if m.get("massenmail"):
            # Newsletter/Werbung: nur Absender und Betreff, ohne Auszug (Token-Sparhebel)
            zeilen.append(f"- [Newsletter] {von[:50]} | {betreff[:90]}")
            continue
        auszug = _entschaerfen(m.get("auszug", ""))[:MAX_AUSZUG]
        zeilen.append(f"- {von} | {betreff} | {auszug}")
    return "\n".join(zeilen)

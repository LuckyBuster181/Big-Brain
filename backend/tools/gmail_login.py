"""Einmalige Gmail-Freigabe für Jarvis (25.09.2026).

Ablauf:
1. Liest GOOGLE_CLIENT_ID und GOOGLE_CLIENT_SECRET aus der .env im
   Jarvis-Ordner (eingetragen mit GOOGLE_KALENDER_ZUGANG_SETZEN.bat).
2. Startet kurz einen kleinen Empfänger auf http://127.0.0.1:8765 und öffnet
   die Google-Anmeldung im Browser.
3. Nach der Bestätigung tauscht es den Code gegen den Refresh-Token und trägt
   ihn als GOOGLE_GMAIL_REFRESH_TOKEN in die .env ein (vorher Sicherung nach
   data/env_sicherung_gmail.txt). Der Token wird nie angezeigt.
4. Probeabruf: zeigt die Mail-Adresse und die Zahl ungelesener Mails.

Nur Standardbibliothek - läuft mit jedem Python 3.9+, auch ohne venv.
Die Google-Anmeldung akzeptiert für Desktop-Apps jede Adresse auf 127.0.0.1
mit beliebigem Port, deshalb ist keine Änderung in der Cloud Console nötig.
"""

from __future__ import annotations

import http.server
import json
import secrets
import shutil
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

JARVIS = Path(__file__).resolve().parents[2]
ENV = JARVIS / ".env"
SICHERUNG = JARVIS / "data" / "env_sicherung_gmail.txt"
PORT = 8765
REDIRECT = f"http://127.0.0.1:{PORT}/callback"
SCOPE = "https://www.googleapis.com/auth/gmail.modify"
AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
WARTEN_S = 300


def env_lesen(pfad: Path = ENV) -> dict[str, str]:
    werte = {}
    for zeile in pfad.read_text(encoding="utf-8-sig").splitlines():
        if "=" in zeile and not zeile.lstrip().startswith("#"):
            name, _, wert = zeile.partition("=")
            werte[name.strip()] = wert.strip().strip('"').strip("'")
    return werte


def env_setzen(name: str, wert: str, pfad: Path = ENV, sicherung: Path = SICHERUNG) -> None:
    """Ersetzt oder ergänzt EINE Zeile. Alles andere bleibt Zeichen für Zeichen stehen."""
    sicherung.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pfad, sicherung)
    zeilen = pfad.read_text(encoding="utf-8-sig").splitlines()
    neu = [z for z in zeilen if z.split("=", 1)[0].strip() != name]
    neu.append(f"{name}={wert}")
    pfad.write_text("\n".join(neu) + "\n", encoding="utf-8")


def login_url(client_id: str, state: str) -> str:
    return AUTH + "?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT,
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )


def _post(url: str, daten: dict) -> dict:
    anfrage = urllib.request.Request(url, data=urllib.parse.urlencode(daten).encode(), method="POST")
    try:
        with urllib.request.urlopen(anfrage, timeout=15) as antwort:
            return json.loads(antwort.read().decode())
    except urllib.error.HTTPError as fehler:
        raise SystemExit(f"Google lehnte ab (HTTP {fehler.code}): {fehler.read().decode()[:300]}")


def _get(url: str, token: str) -> dict:
    anfrage = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(anfrage, timeout=15) as antwort:
        return json.loads(antwort.read().decode())


def code_abwarten(state: str) -> str:
    """Kleiner Empfänger für genau eine Rückleitung von Google."""
    ergebnis: dict[str, str] = {}
    fertig = threading.Event()

    class Empfang(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            teile = urllib.parse.urlparse(self.path)
            werte = dict(urllib.parse.parse_qsl(teile.query))
            if teile.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            if werte.get("state") != state:
                ergebnis["fehler"] = "Falscher state - Anmeldung nicht von diesem Fenster gestartet."
            elif "error" in werte:
                ergebnis["fehler"] = f"Google meldet: {werte['error']}"
            else:
                ergebnis["code"] = werte.get("code", "")
            text = "Fertig, Sir. Dieses Fenster kann zu." if "code" in ergebnis else f"Fehler: {ergebnis.get('fehler')}"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<html><body style='font-family:sans-serif'><h2>{text}</h2></body></html>".encode())
            fertig.set()

        def log_message(self, *args):  # keine Ausgabe mit Code im Fenster
            return

    server = http.server.HTTPServer(("127.0.0.1", PORT), Empfang)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        if not fertig.wait(WARTEN_S):
            raise SystemExit("Nach 5 Minuten keine Rückmeldung von Google. Bitte neu starten.")
    finally:
        server.shutdown()
    if "fehler" in ergebnis:
        raise SystemExit(ergebnis["fehler"])
    return ergebnis["code"]


def main() -> int:
    if not ENV.exists():
        print(f".env nicht gefunden: {ENV}")
        return 1
    werte = env_lesen()
    cid, secret = werte.get("GOOGLE_CLIENT_ID", ""), werte.get("GOOGLE_CLIENT_SECRET", "")
    if not cid or not secret:
        print("GOOGLE_CLIENT_ID oder GOOGLE_CLIENT_SECRET fehlt in der .env.")
        print("Zuerst GOOGLE_KALENDER_ZUGANG_SETZEN.bat ausführen (gleiche Zugangsdaten).")
        return 1

    state = secrets.token_urlsafe(16)
    url = login_url(cid, state)
    print("Browser öffnet sich. Google-Konto wählen und Gmail-Zugriff erlauben.")
    print("Falls sich nichts öffnet, diese Adresse in Chrome einfügen:\n")
    print(url + "\n")
    webbrowser.open(url)

    code = code_abwarten(state)
    daten = _post(
        TOKEN_URL,
        {"grant_type": "authorization_code", "code": code, "client_id": cid,
         "client_secret": secret, "redirect_uri": REDIRECT},
    )
    token = daten.get("refresh_token")
    if not token:
        print("Google lieferte keinen Refresh-Token. Unter myaccount.google.com/permissions")
        print("den Zugriff für die Jarvis-App entfernen und dieses Skript neu starten.")
        return 1
    env_setzen("GOOGLE_GMAIL_REFRESH_TOKEN", token)
    print("Eingetragen: GOOGLE_GMAIL_REFRESH_TOKEN in der .env (Sicherung: data\\env_sicherung_gmail.txt).")

    # Probeabruf mit dem frischen Zugang
    zugang = daten.get("access_token", "")
    profil = _get("https://gmail.googleapis.com/gmail/v1/users/me/profile", zugang)
    liste = _get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages?"
        + urllib.parse.urlencode({"q": "is:unread in:inbox newer_than:2d", "maxResults": 50}),
        zugang,
    )
    print(f"Probeabruf OK: {profil.get('emailAddress')}, ungelesen (2 Tage, bis 50): {len(liste.get('messages') or [])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

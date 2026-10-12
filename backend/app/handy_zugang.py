"""Handy-Zugang (24.09.2026): Jarvis im Heimnetz vom Handy aus.

Jarvis hört normalerweise nur auf den eigenen PC (127.0.0.1). Mit
"1 Starten/HANDY_STARTEN.bat" hört er auch im Heimnetz (0.0.0.0). Damit dann
nicht jedes Gerät im WLAN auf Kosten von Sir Claude fragen oder etwas steuern
kann, gilt für alle Anfragen, die NICHT vom PC selbst kommen:

1. Ohne JARVIS_HANDY_TOKEN in der .env ist der Zugang ganz aus (403).
2. Der Zugangscode muss stimmen: einmal als ?zugang=CODE in der Adresse,
   danach merkt sich das Handy ihn als Cookie (http-only, 1 Jahr).
3. Nur eine feste Liste von Adressen ist erlaubt (Chat, Briefing, Denkblock,
   Vorschläge, Status, Sprachausgabe, Datei-Ablage, TikTok). Einstellungen, .env, Sonos, PC 2, Reindex, Trading und
   alles andere bleiben dem PC vorbehalten.

Anfragen vom PC selbst (127.0.0.1 / ::1) laufen unverändert.

Geräte mit eigenem Zugang (25.09.2026, app/geraete.py): Wer einen Code aus
JARVIS_ZUGANG_<GERÄT> in der .env hat (z.B. der Laptop), bekommt das VOLLE
HUD. Jede Anfrage bekommt dabei ihr Gerät ("Haupt-PC", "Laptop", "Handy"),
und Zugriffe landen mit Zeit in data/zugriffe.jsonl.
"""

from __future__ import annotations

import hmac
import os

COOKIE = "jarvis_zugang"
# 12.10.2026 (P19): Alexa-Skill "frag Auron". Amazon hat weder Tailnet noch Zugangscode; der
# Endpunkt prüft jede Anfrage selbst (Signatur, Zeitstempel, Skill-ID: app/alexa_pruefung.py).
ALEXA_PFAD = "/api/alexa"
LOOPBACK = {"127.0.0.1", "::1", "localhost"}

# (Methode, Pfad-Anfang) - Pfad muss genau passen oder mit "Anfang/" weitergehen
ERLAUBT: tuple[tuple[str, str], ...] = (
    ("GET", "/handy"),
    ("GET", "/api/health"),
    ("POST", "/api/chat/stream"),
    ("POST", "/api/chat"),
    ("GET", "/api/briefing"),
    ("GET", "/api/denkblock"),
    ("POST", "/api/denkblock"),
    ("GET", "/api/vorschlaege"),
    ("POST", "/api/vorschlaege"),
    ("GET", "/api/kosten"),
    # Sprache (24.09.2026): Jarvis-Stimme (Fish Audio / Piper) und deren Status
    ("GET", "/api/sprache"),
    ("POST", "/api/sprache"),
    # Datei-Ablage (26.09.2026): Fotos und Dateien vom Handy an Jarvis schicken.
    # Landet in data/ablage; app/ablage.py sperrt ausführbare Dateien, begrenzt
    # auf 50 MB und überschreibt nichts. GET deckt auch /api/ablage/datei ab.
    ("GET", "/api/ablage"),
    ("POST", "/api/ablage"),
    # TikTok (26.09.2026): Links hinzufügen und Slides (Foto-Beiträge) direkt vom
    # Handy zuordnen, lesen lassen (Haiku, ca. 0,35 Cent je Bild) und in den Vault.
    ("GET", "/api/tiktok"),
    ("POST", "/api/tiktok"),
    # Trading-Tagebuch (26.09.2026): Trades unterwegs eintragen und schließen. Nur Sirs
    # eigene Notizen zu Trades - Jarvis handelt nie. Einstellungen (PUT) bleiben am PC.
    ("GET", "/api/tagebuch"),
    ("POST", "/api/tagebuch"),
    # Nachtaufträge und Frage des Tages (26.09.2026): unterwegs Aufträge für die
    # Nacht geben, Rückfragen beantworten, Vorschläge freigeben.
    ("GET", "/api/nachtauftraege"),
    ("POST", "/api/nachtauftraege"),
    ("GET", "/api/tagesfrage"),
    ("POST", "/api/tagesfrage"),
    # Alltagsfunktionen (27.09.2026): Mind Maps und Projekte ansehen/anlegen, Dateien umwandeln.
    # Haupt-PC steuern geht vom Handy nur über den Chat (mit Rückfrage bei Herunterfahren).
    ("GET", "/api/mindmaps"),
    ("POST", "/api/mindmaps"),
    ("GET", "/api/projekte"),
    ("POST", "/api/projekte"),
    ("POST", "/api/umwandeln"),
    # Sprachmemos (02.10.2026): Ideen vom Handy hochladen, anhören, Titel ändern, abschreiben (lokal).
    ("GET", "/api/sprachmemos"),
    ("POST", "/api/sprachmemos"),
)


def token() -> str:
    return (os.getenv("JARVIS_HANDY_TOKEN") or "").strip()


def ist_lokal(host: str | None) -> bool:
    return (host or "") in LOOPBACK


def ist_tailnet(host: str | None, tailscale_nutzer: str | None) -> bool:
    """Handy unterwegs (05.10.2026): Anfrage kam über "tailscale serve" auf dem Mini-PC.

    tailscale serve reicht an 127.0.0.1:8000 weiter und setzt X-Forwarded-For auf die
    Tailscale-Adresse des Handys (100.64.0.0/10). uvicorn glaubt dieser Angabe nur, wenn sie
    von 127.0.0.1 kommt (Standard forwarded_allow_ips) - aus dem Heimnetz lässt sie sich also
    nicht fälschen. Dazu muss der Kopf Tailscale-User-Login gesetzt sein (nur angemeldete
    Geräte aus Sirs eigenem Tailnet). Dann gilt dasselbe Recht wie am PC (Entscheidung Sir)."""
    import ipaddress
    if not host or not (tailscale_nutzer or "").strip():
        return False
    try:
        return ipaddress.ip_address(host) in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        return False


def _pfad_erlaubt(methode: str, pfad: str) -> bool:
    pfad = pfad.rstrip("/") or "/"
    for m, anfang in ERLAUBT:
        if methode.upper() == m and (pfad == anfang or pfad.startswith(anfang + "/")):
            # /api/denkblock/<name>/mitdenken kostet Claude-Geld - erlaubt, wie im HUD.
            return True
    return False


def code_passt(eingabe: str | None) -> bool:
    t = token()
    if not t or not eingabe:
        return False
    return hmac.compare_digest(eingabe.strip().encode(), t.encode())


def pruefen(host: str | None, methode: str, pfad: str, cookie: str | None, query_code: str | None,
            tailnet: bool = False) -> dict:
    """Entscheidet über eine Anfrage.

    Rückgabe: {"erlaubt": bool, "status": int, "grund": str, "cookie_setzen": bool,
               "geraet": str, "geraet_schluessel": str, "cookie_wert": str}
    """
    from . import geraete

    if methode.upper() == "POST" and pfad == ALEXA_PFAD:
        # Nur genau POST /api/alexa. Kein Geräteschlüssel: keine IP merken, kein Handy-Recht.
        return {"erlaubt": True, "status": 200, "grund": "alexa", "cookie_setzen": False,
                "geraet": "Alexa", "geraet_schluessel": ""}
    if ist_lokal(host):
        return {"erlaubt": True, "status": 200, "grund": "lokal", "cookie_setzen": False,
                "geraet": geraete.anzeigename(geraete.HAUPTPC), "geraet_schluessel": geraete.HAUPTPC}
    if tailnet:
        return {"erlaubt": True, "status": 200, "grund": "tailscale", "cookie_setzen": False,
                "geraet": geraete.anzeigename("handy"), "geraet_schluessel": "handy"}
    # Geräte mit vollem Zugang (Laptop ...) - vor dem Handy, damit sie auch ohne Handy-Code gehen
    for eingabe, aus_adresse in ((query_code, True), (cookie, False)):
        schluessel = geraete.zugang_fuer_code(eingabe)
        if schluessel:
            return {"erlaubt": True, "status": 200, "grund": "geraet", "cookie_setzen": aus_adresse,
                    "geraet": geraete.anzeigename(schluessel), "geraet_schluessel": schluessel,
                    "cookie_wert": eingabe.strip()}
    if not token():
        return {"erlaubt": False, "status": 403, "grund": "Handy-Zugang ist aus (kein JARVIS_HANDY_TOKEN).", "cookie_setzen": False}
    neu = code_passt(query_code)
    if not (neu or code_passt(cookie)):
        return {"erlaubt": False, "status": 401, "grund": "Zugangscode fehlt oder stimmt nicht.", "cookie_setzen": False}
    if not _pfad_erlaubt(methode, pfad):
        return {"erlaubt": False, "status": 403, "grund": "Vom Handy aus nicht erlaubt.", "cookie_setzen": False}
    return {"erlaubt": True, "status": 200, "grund": "code", "cookie_setzen": neu,
            "geraet": "Handy", "geraet_schluessel": "handy", "cookie_wert": token()}


async def middleware(request, call_next):
    """FastAPI-HTTP-Middleware (in main.py eingehängt)."""
    from starlette.responses import JSONResponse

    from . import geraete

    host = request.client.host if request.client else None
    r = pruefen(host, request.method, request.url.path, request.cookies.get(COOKIE), request.query_params.get("zugang"),
                tailnet=ist_tailnet(host, request.headers.get("tailscale-user-login")))
    if not r["erlaubt"]:
        return JSONResponse({"detail": r["grund"]}, status_code=r["status"])
    # Herkunft: für das ganze Backend (Token-Protokoll usw.) und das Zugriffsprotokoll
    marke = geraete.setzen(r["geraet"])
    try:
        geraete.gesehen(r.get("geraet_schluessel", ""), host)
        geraete.anfrage_protokollieren(r["geraet"], host, request.method, request.url.path)
        antwort = await call_next(request)
    finally:
        geraete.zuruecksetzen(marke)
    if r["cookie_setzen"]:
        antwort.set_cookie(COOKIE, r["cookie_wert"], max_age=365 * 24 * 3600, httponly=True, samesite="strict")
    return antwort

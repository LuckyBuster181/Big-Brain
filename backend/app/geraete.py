"""Geräte im HUD (25.09.2026): alle Rechner sehen und steuern, und wissen, wer wann da war.

Wunsch von Sir: Im HUD auf jeden PC zugreifen (Bildschirm sehen und steuern),
den Laptop mit einer eigenen Datei (nicht über den Handy-Zugang) anbinden und
bei allem festhalten, von welchem Gerät es kommt und wann.

Bausteine:
1. Gerätezugänge: In der .env steht je Gerät ein eigener Zugangscode,
   z.B. JARVIS_ZUGANG_LAPTOP=... Wer im Heimnetz diesen Code hat, bekommt das
   VOLLE HUD (anders als der Handy-Zugang, der nur Chat usw. darf). Die
   Prüfung macht app/handy_zugang.py, die Codes kommen von hier.
2. Herkunft: Jede Anfrage bekommt ein Gerät ("Haupt-PC", "Laptop", "Handy").
   aktuelles() liefert es überall im Backend (z.B. für das Token-Protokoll).
   Zugriffe werden in data/zugriffe.jsonl mit Zeit, Gerät, IP und Aktion
   festgehalten (sparsam: nicht jede Sekunden-Abfrage des HUD).
3. Bildschirm: Auf den Windows-Rechnern läuft TightVNC (VNC = Bildschirm-
   Übertragung). Das HUD zeigt ihn mit noVNC (VNC im Browser, liegt in
   dashboard/novnc). Die Verbindung läuft immer über dieses Backend
   (vnc_bruecke): Browser -> WebSocket -> Backend -> VNC des Zielrechners.
   Dadurch muss der VNC-Port des Laptops nur für den Haupt-PC offen sein, und
   der Haupt-PC lässt VNC nur von sich selbst zu (Loopback).
   VNC-Passwörter: JARVIS_VNC_HAUPTPC, JARVIS_VNC_LAPTOP (höchstens 8 Zeichen,
   das ist eine Grenze von VNC).

Vorerst nur im Heimnetz. Für "überall" später z.B. Tailscale (privates Netz),
dann gilt dieselbe Code-Prüfung.
"""

from __future__ import annotations

import asyncio
import contextvars
import datetime
import hmac
import json
import os
import re
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import quote

import anyio

from . import geraeteschutz

JARVIS = Path(__file__).resolve().parents[2]
NOVNC_ORDNER = JARVIS / "dashboard" / "novnc"
VNC_PORT = 5900
PRUEF_TIMEOUT_S = 0.6
VERBINDEN_TIMEOUT_S = 5
LOG_PAUSE_S = 10 * 60  # dieselbe einfache Abfrage höchstens alle 10 Minuten ins Protokoll

HAUPTPC = "hauptpc"
NAMEN = {HAUPTPC: "Haupt-PC", "laptop": "Laptop", "handy": "Handy", "pc2": "PC 2"}

_geraet: contextvars.ContextVar[str] = contextvars.ContextVar("jarvis_geraet", default=NAMEN[HAUPTPC])
_sperre = threading.Lock()
_zuletzt_geloggt: dict[tuple[str, str], float] = {}


# ------------------------------------------------------------------ Pfade

def _geraete_datei() -> Path:
    return Path(os.getenv("GERAETE_PATH") or (JARVIS / "data" / "geraete.json"))


def _zugriffe_datei() -> Path:
    return Path(os.getenv("ZUGRIFFE_PATH") or (JARVIS / "data" / "zugriffe.jsonl"))


def _jetzt() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


# ------------------------------------------------------------ Zugangscodes

def _wert(name: str) -> str:
    return (os.getenv(name) or "").strip().strip('"').strip("'")


def zugangscodes() -> dict[str, str]:
    """{geraet_schluessel: code} aus allen JARVIS_ZUGANG_<NAME>-Einträgen der .env."""
    codes = {}
    for name, wert in os.environ.items():
        if name.startswith("JARVIS_ZUGANG_"):
            schluessel = name[len("JARVIS_ZUGANG_"):].strip().lower()
            code = str(wert or "").strip().strip('"').strip("'")
            if schluessel and len(code) >= 8:
                codes[schluessel] = code
    return codes


def zugang_fuer_code(code: str | None) -> str | None:
    """Gerät (z.B. 'laptop') zu einem Zugangscode, sonst None. Vergleich in fester Zeit."""
    if not code:
        return None
    eingabe = code.strip().encode()
    for schluessel, richtig in zugangscodes().items():
        if hmac.compare_digest(eingabe, richtig.encode()):
            return schluessel
    return None


def anzeigename(schluessel: str) -> str:
    return NAMEN.get(schluessel, schluessel.replace("_", " ").title())


# ------------------------------------------------------------------ Herkunft

def setzen(name: str) -> contextvars.Token:
    return _geraet.set(name)


def zuruecksetzen(token: contextvars.Token) -> None:
    try:
        _geraet.reset(token)
    except ValueError:
        pass


def aktuelles() -> str:
    """Von welchem Gerät kommt die laufende Anfrage (Standard: Haupt-PC)."""
    return _geraet.get()


def _laden() -> dict:
    try:
        daten = json.loads(_geraete_datei().read_text(encoding="utf-8"))
        return daten if isinstance(daten, dict) else {}
    except (OSError, ValueError):
        return {}


def _nur_geraete(daten: dict) -> dict:
    """Nur echte Geräte-Einträge. Einstellungen wie "_hauptpc_anzeige" liegen in derselben
    Datei, sind aber keine Geräte (Fehler 25.09. abends: Monitor-Wahl brach die Geräteliste)."""
    return {k: v for k, v in daten.items() if isinstance(v, dict) and not str(k).startswith("_")}


def _speichern(daten: dict) -> None:
    datei = _geraete_datei()
    datei.parent.mkdir(parents=True, exist_ok=True)
    tmp = datei.with_suffix(".tmp")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, datei)


def gesehen(schluessel: str, ip: str | None) -> None:
    """Merkt sich die letzte IP-Adresse eines Geräts (für die Bildschirm-Verbindung)."""
    if not schluessel or schluessel in (HAUPTPC, "handy") or not ip:
        return
    if ip in _feste_adressen():
        # 30.09.2026: Der Haupt-PC (.119) öffnete das HUD mit dem Laptop-Code. Jarvis merkte sich
        # daraufhin .119 als Laptop-Adresse und verband "Bildschirm Laptop" mit dem Haupt-PC -
        # falsches Passwort, Laptop "nicht erreichbar". Adressen von Haupt-PC und Mini-PC sind
        # nie die eines anderen Geräts.
        return
    with _sperre:
        daten = _laden()
        eintrag = daten.get(schluessel) or {}
        alt_zeit = eintrag.get("zuletzt_ts", 0)
        if eintrag.get("ip") == ip and time.time() - alt_zeit < 60:
            return
        daten[schluessel] = {"ip": ip, "zuletzt": _jetzt(), "zuletzt_ts": time.time()}
        _speichern(daten)


def _feste_adressen() -> set[str]:
    """IP-Adressen, die fest zu Haupt-PC oder Mini-PC gehören (plus Loopback)."""
    from urllib.parse import urlparse

    feste = {"127.0.0.1", "::1", "localhost"}
    for name in ("HAUPTPC_URL", "PC2_URL"):
        host = urlparse(_wert(name)).hostname if _wert(name) else None
        if host:
            feste.add(host)
    if _wert("HAUPTPC_IP"):
        feste.add(_wert("HAUPTPC_IP"))
    return feste


def geraet_ip(schluessel: str) -> str | None:
    if schluessel == "pc2":
        from urllib.parse import urlparse

        from . import pc2

        host = urlparse(_wert("PC2_URL")).hostname if _wert("PC2_URL") else None
        return "127.0.0.1" if pc2.ist_hier(host) else host
    if schluessel == HAUPTPC:
        # 27.09.2026: Jarvis läuft auf dem Mini-PC - "127.0.0.1" wäre dort der Mini-PC selbst.
        # Deshalb war der Haupt-PC auf der Geräte-Seite immer "nicht erreichbar". Die Adresse
        # kommt jetzt aus HAUPTPC_URL (schreibt PC_STEUERUNG_EINRICHTEN.bat) oder HAUPTPC_IP.
        from urllib.parse import urlparse

        host = urlparse(_wert("HAUPTPC_URL")).hostname if _wert("HAUPTPC_URL") else None
        return host or _wert("HAUPTPC_IP") or "127.0.0.1"
    return (_nur_geraete(_laden()).get(schluessel) or {}).get("ip")


# ---------------------------------------------------------------- Protokoll

def _aktion_lesbar(methode: str, pfad: str) -> str:
    if pfad in ("/", "/handy"):
        return "HUD geöffnet" if pfad == "/" else "Handy-Seite geöffnet"
    if pfad.startswith("/api/chat"):
        return "Frage an Jarvis"
    if pfad.startswith("/api/briefing"):
        return "Briefing"
    if pfad.startswith("/api/geraete/anmelden"):
        return "Gerät angemeldet"
    return f"{methode} {pfad}"


def soll_protokolliert_werden(geraet: str, methode: str, pfad: str) -> bool:
    """Nur das Wesentliche (Wunsch Sir, 25.09. abends): HUD/Handy-Seite geöffnet und Briefing
    (höchstens alle 10 Minuten je Gerät), alles was etwas tut (POST usw.) immer.
    Die vielen Hintergrund-Abfragen des HUD (System, Spotify, Ampel ...) nicht."""
    if pfad.startswith(("/novnc/", "/assets/")) or pfad == "/favicon.ico":
        return False
    if methode.upper() not in ("GET", "HEAD", "OPTIONS"):
        return True
    if pfad not in ("/", "/handy") and not pfad.startswith("/api/briefing"):
        return False
    schluessel = (geraet, pfad.split("?")[0][:20])
    jetzt = time.time()
    with _sperre:
        if jetzt - _zuletzt_geloggt.get(schluessel, 0) < LOG_PAUSE_S:
            return False
        _zuletzt_geloggt[schluessel] = jetzt
    return True


def protokollieren(geraet: str, ip: str | None, aktion: str) -> None:
    """Hängt einen Zugriff an data/zugriffe.jsonl an. Fehler stören nie die Anfrage."""
    try:
        datei = _zugriffe_datei()
        datei.parent.mkdir(parents=True, exist_ok=True)
        eintrag = {"zeit": _jetzt(), "geraet": geraet, "ip": ip or "", "aktion": aktion[:120]}
        with _sperre, datei.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
    except OSError:
        pass


def anfrage_protokollieren(geraet: str, ip: str | None, methode: str, pfad: str) -> None:
    if soll_protokolliert_werden(geraet, methode, pfad):
        protokollieren(geraet, ip, _aktion_lesbar(methode, pfad))


def zugriffe(anzahl: int = 40) -> list[dict]:
    """Die letzten Zugriffe, neueste zuerst."""
    try:
        zeilen = _zugriffe_datei().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    ergebnis = []
    for zeile in reversed(zeilen[-2000:]):
        try:
            ergebnis.append(json.loads(zeile))
        except ValueError:
            continue
        if len(ergebnis) >= anzahl:
            break
    return ergebnis


# ------------------------------------------------------------------ Status

def vnc_passwort(schluessel: str) -> str:
    return _wert(f"JARVIS_VNC_{schluessel.upper()}")[:8]


def port_offen(ip: str | None, port: int = VNC_PORT, timeout: float = PRUEF_TIMEOUT_S) -> bool:
    if not ip:
        return False
    geraeteschutz.netz_pruefen(f"{ip}:{port}", "Gerät prüfen")
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def novnc_da() -> bool:
    return (NOVNC_ORDNER / "vnc.html").is_file()


def bildschirm_url(schluessel: str) -> str:
    """Adresse für das noVNC-Fenster im HUD. Das Passwort steht drin, damit Sir es
    nicht tippen muss - diese Adresse bekommt nur, wer das volle HUD sehen darf."""
    teile = [
        "autoconnect=true", "resize=scale", "reconnect=true", "reconnect_delay=3000",
        f"path={quote(f'api/geraete/{schluessel}/vnc', safe='/')}",
    ]
    pw = vnc_passwort(schluessel)
    if pw:
        teile.append(f"password={quote(pw, safe='')}")
    return "/novnc/vnc.html?" + "&".join(teile)


def liste(eigenes_geraet: str = NAMEN[HAUPTPC]) -> dict:
    """Alles für die HUD-Seite "Geräte"."""
    daten = _nur_geraete(_laden())
    schluessel_alle = [HAUPTPC] + sorted(set(zugangscodes()) | {k for k in daten if k not in (HAUPTPC, "handy")})
    geraete = []
    for s in schluessel_alle:
        ip = geraet_ip(s)
        eingerichtet = bool(vnc_passwort(s))
        vnc_bereit = eingerichtet and port_offen(ip)
        geraete.append(
            {
                "schluessel": s,
                "name": anzeigename(s),
                "ip": ip or "",
                "zuletzt": (daten.get(s) or {}).get("zuletzt", "") if s != HAUPTPC else "",
                "zugang": s == HAUPTPC or s in zugangscodes(),
                "vnc_eingerichtet": eingerichtet,
                "vnc_bereit": vnc_bereit,
                "dieses_geraet": anzeigename(s) == eigenes_geraet,
                "bildschirm_url": bildschirm_url(s) if vnc_bereit else "",
                "anzeigen": list(ANZEIGEN) if s == HAUPTPC else [],
                "anzeige": anzeige_hauptpc() if s == HAUPTPC else "",
                "pc_agent": bool(_wert("HAUPTPC_URL") and _wert("HAUPTPC_TOKEN")) if s == HAUPTPC else False,
                # 27.09.2026: Haupt-PC gilt als erreichbar, wenn der PC-Agent (Port 8766) antwortet -
                # unabhängig davon, ob sein Bildschirm (TightVNC) für den Mini-PC freigegeben ist.
                "online": port_offen(ip, 8766) if s == HAUPTPC and _wert("HAUPTPC_URL") else vnc_bereit,
            }
        )
    return {"geraete": geraete, "novnc_da": novnc_da(), "ich": eigenes_geraet, "zugriffe": zugriffe()}


# --------------------------------------- Monitor-Wahl am Haupt-PC (25.09. abends)
# Der Haupt-PC hat zwei Monitore. TightVNC schickt sonst beide nebeneinander als
# ein sehr breites Bild - auf dem Laptop winzig. tvnserver lässt sich im laufenden
# Betrieb umstellen: -sharedisplay N (ein Monitor) oder -sharefull (alle).
# UNGETESTET: Nummerierung der Monitore (ab 1) und ob der Dienst den Befehl
# ohne Administrator-Rechte annimmt.
# 30.09.2026: Ohne tvnserver.exe hier (Mini-PC) geht der Befehl über den PC-Agent am Haupt-PC.
ANZEIGEN = ("1", "2", "alle")
TVNSERVER_PFADE = (
    r"C:\Program Files\TightVNC\tvnserver.exe",
    r"C:\Program Files (x86)\TightVNC\tvnserver.exe",
)


def _tvnserver() -> str | None:
    eigen = _wert("TVNSERVER_PFAD")
    for pfad in ((eigen,) if eigen else ()) + TVNSERVER_PFADE:
        if pfad and Path(pfad).is_file():
            return pfad
    return None


def anzeige_hauptpc() -> str:
    wahl = str(_laden().get("_hauptpc_anzeige") or "1")
    return wahl if wahl in ANZEIGEN else "1"


def anzeige_anwenden(wahl: str | None = None) -> dict:
    """Stellt TightVNC am Haupt-PC auf Monitor 1, 2 oder alle. Merkt sich die Wahl."""
    wahl = wahl or anzeige_hauptpc()
    if wahl not in ANZEIGEN:
        return {"ok": False, "fehler": "Auswahl muss 1, 2 oder alle sein."}
    with _sperre:
        daten = _laden()
        daten["_hauptpc_anzeige"] = wahl
        _speichern(daten)
    exe = _tvnserver()
    if not exe:
        # 30.09.2026: Jarvis läuft auf dem Mini-PC (Linux) - dort gibt es kein tvnserver.exe.
        # Seitdem gingen die Knöpfe "Monitor 1 / 2 / Beide" nicht mehr. Jetzt stellt der
        # PC-Agent am Haupt-PC (Port 8766, Aktion "anzeige") TightVNC um.
        return _anzeige_ueber_agent(wahl)
    geraeteschutz.lokal_pruefen("TightVNC umstellen")
    befehl = [exe, "-controlservice", "-sharefull"] if wahl == "alle" else [exe, "-controlservice", "-sharedisplay", wahl]
    try:
        ergebnis = subprocess.run(befehl, capture_output=True, text=True, timeout=10,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as fehler:
        return {"ok": False, "anzeige": wahl, "fehler": f"TightVNC-Befehl fehlgeschlagen ({type(fehler).__name__})."}
    if ergebnis.returncode != 0:
        text = (ergebnis.stderr or ergebnis.stdout or "").strip()[:200]
        return {"ok": False, "anzeige": wahl, "fehler": f"TightVNC lehnte ab (Code {ergebnis.returncode}). {text}"}
    return {"ok": True, "anzeige": wahl}


def _anzeige_ueber_agent(wahl: str) -> dict:
    from . import hauptpc

    if not hauptpc.ist_eingerichtet():
        return {"ok": False, "anzeige": wahl,
                "fehler": "PC-Steuerung nicht eingerichtet (3 Einrichten\\PC_STEUERUNG_EINRICHTEN.bat)."}
    try:
        e = hauptpc.aktion("anzeige", wahl)
    except hauptpc.HauptPcFehler as exc:
        return {"ok": False, "anzeige": wahl, "fehler": str(exc)}
    if e.get("ok"):
        return {"ok": True, "anzeige": wahl}
    meldung = str(e.get("meldung") or e.get("fehler") or "unbekannter Grund")
    if meldung.startswith("Unbekannte Aktion"):
        meldung = "Der PC-Agent am Haupt-PC ist noch die alte Version - JARVIS STARTEN.bat am Haupt-PC starten."
    return {"ok": False, "anzeige": wahl, "fehler": meldung}


# ------------------------------------------------- Bildschirm-Brücke (WebSocket)

def _ws_host(websocket) -> str | None:
    client = getattr(websocket, "client", None)
    return client.host if client else None


def ws_berechtigt(websocket) -> str | None:
    """WebSockets laufen NICHT durch die HTTP-Middleware - darum eigene Prüfung.
    Gibt das anfragende Gerät zurück oder None (kein Zugang)."""
    from . import handy_zugang

    host = _ws_host(websocket)
    if handy_zugang.ist_lokal(host):
        return NAMEN[HAUPTPC]
    code = websocket.cookies.get(handy_zugang.COOKIE) or websocket.query_params.get("zugang")
    schluessel = zugang_fuer_code(code)
    return anzeigename(schluessel) if schluessel else None


async def vnc_bruecke(websocket) -> None:
    """Browser (noVNC) <-> WebSocket <-> dieses Backend <-> TCP-VNC des Zielrechners."""
    ziel = str(websocket.path_params.get("name", "")).lower()
    wer = ws_berechtigt(websocket)
    if not wer:
        await websocket.close(code=4401)
        return
    # 27.09.2026: "pc2" = Mini-PC, auf dem Jarvis selbst läuft - x11vnc hat sein eigenes Passwort
    # (noVNC fragt es ab), deshalb hier ohne JARVIS_VNC_PC2.
    if not re.fullmatch(r"[a-z0-9_]{1,30}", ziel) or not (vnc_passwort(ziel) or ziel == "pc2"):
        await websocket.close(code=4404)
        return
    ip = geraet_ip(ziel)
    if not ip:
        await websocket.close(code=4404)
        return
    if ziel == HAUPTPC:
        # gemerkten Monitor einstellen, bevor das Bild kommt (sonst beide Monitore nebeneinander)
        await anyio.to_thread.run_sync(anzeige_anwenden)
    angefragt = websocket.scope.get("subprotocols") or []
    await websocket.accept(subprotocol="binary" if "binary" in angefragt else None)
    try:
        geraeteschutz.netz_pruefen(f"{ip}:{VNC_PORT}", "VNC-Brücke")
        with anyio.fail_after(VERBINDEN_TIMEOUT_S):
            vnc = await anyio.connect_tcp(ip, VNC_PORT)
    except (OSError, TimeoutError):
        await websocket.close(code=4502)
        return
    protokollieren(wer, _ws_host(websocket), f"Bildschirm {anzeigename(ziel)} verbunden")
    browser_weg = False

    async def browser_zu_vnc(gruppe):
        nonlocal browser_weg
        while True:
            nachricht = await websocket.receive()
            if nachricht.get("type") == "websocket.disconnect":
                browser_weg = True
                break
            daten = nachricht.get("bytes")
            if daten is None and nachricht.get("text") is not None:
                daten = nachricht["text"].encode("latin-1", errors="ignore")
            if daten:
                await vnc.send(daten)
        gruppe.cancel_scope.cancel()

    async def vnc_zu_browser(gruppe):
        try:
            while True:
                await websocket.send_bytes(await vnc.receive(65536))
        except (anyio.EndOfStream, anyio.BrokenResourceError, anyio.ClosedResourceError):
            pass
        gruppe.cancel_scope.cancel()

    # anyio statt roher asyncio-Aufgaben: sauberes Beenden, egal welche Seite zuerst trennt
    try:
        async with anyio.create_task_group() as gruppe:
            gruppe.start_soon(browser_zu_vnc, gruppe)
            gruppe.start_soon(vnc_zu_browser, gruppe)
    finally:
        with anyio.CancelScope(shield=True):
            await vnc.aclose()
            if not browser_weg:  # VNC-Seite hat beendet -> Browser sauber trennen
                try:
                    await websocket.close()
                except Exception:  # noqa: BLE001 - schon zu
                    pass


# ------------------------------------------------------ HTTP (Starlette-Stil)

async def api_liste(request):
    from starlette.responses import JSONResponse

    daten = await asyncio.to_thread(liste, aktuelles())
    return JSONResponse(daten, headers={"Cache-Control": "no-store"})


async def api_anmelden(request):
    """Der Laptop meldet sich (JARVIS_OEFFNEN.bat): IP merken, Zeit festhalten."""
    from starlette.responses import JSONResponse

    return JSONResponse({"ok": True, "geraet": aktuelles(), "zeit": _jetzt()})


async def api_anzeige(request):
    """POST /api/geraete/hauptpc/anzeige?auswahl=1|2|alle"""
    from starlette.responses import JSONResponse

    wahl = str(request.query_params.get("auswahl", "")).lower()
    ergebnis = await anyio.to_thread.run_sync(anzeige_anwenden, wahl)
    if ergebnis.get("ok"):
        protokollieren(aktuelles(), request.client.host if request.client else "", f"Haupt-PC zeigt Monitor {wahl}")
    return JSONResponse(ergebnis, status_code=200 if ergebnis.get("ok") else 400)


HTTP_ROUTEN = (
    ("/api/geraete", api_liste, ["GET"]),
    ("/api/geraete/hauptpc/anzeige", api_anzeige, ["POST"]),
    ("/api/geraete/anmelden", api_anmelden, ["POST", "GET"]),
)

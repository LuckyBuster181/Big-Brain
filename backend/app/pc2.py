"""
PC 2 (Linux-Mini-PC) im Hub: Livewerte, Steuerung, Aufwecken, Bildschirm.

Auf dem Linux-PC läuft pc2_agent/jarvis_agent.py. Dieses Modul spricht mit ihm;
der Token bleibt dabei im Backend - der Browser sieht ihn nie.

.env (schreibt PC2_EINRICHTEN.bat):
    PC2_URL          z.B. http://192.168.178.50:8765
    PC2_TOKEN        Token aus der Kopplungszeile
    PC2_MAC          für Wake-on-LAN (optional)
    PC2_VNC_PORT     Port der Bildschirmansicht (noVNC), 0 = aus

Gefährliche Aktionen (Neustart, Herunterfahren, Prozess beenden) gehen nur mit
"bestaetigt": true durch - das HUD fragt vorher nach.
"""

from __future__ import annotations

import json
import os
import re
import socket
import time
from typing import Any, Iterator
from urllib.parse import urlparse

import httpx

from . import geraeteschutz

GEFAEHRLICH = {"neustart", "herunterfahren", "prozess_beenden"}
_MAC = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")


class Pc2Fehler(Exception):
    def __init__(self, meldung: str, status: int = 502) -> None:
        super().__init__(meldung)
        self.status = status


def konfig() -> dict[str, Any]:
    url = (os.getenv("PC2_URL") or "").strip().rstrip("/")
    try:
        vnc = int(os.getenv("PC2_VNC_PORT") or 0)
    except ValueError:
        vnc = 0
    return {
        "url": url,
        "token": (os.getenv("PC2_TOKEN") or "").strip(),
        "mac": (os.getenv("PC2_MAC") or "").strip(),
        "vnc_port": vnc,
    }


def ist_hier(host: str | None) -> bool:
    """True, wenn PC 2 derselbe Rechner ist, auf dem Jarvis läuft (seit 26.09.2026: Mini-PC)."""
    if not host:
        return False
    if host in ("127.0.0.1", "localhost", "::1"):
        return True
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((host, 9))  # sendet nichts, wählt nur die eigene Adresse für dieses Ziel
            return s.getsockname()[0] == host
    except OSError:
        return False


def oeffentliche_konfig() -> dict[str, Any]:
    """Was das HUD wissen darf - ohne Token."""
    k = konfig()
    host = urlparse(k["url"]).hostname if k["url"] else None
    bildschirm = None
    if host and k["vnc_port"] and ist_hier(host):
        # 27.09.2026: Jarvis läuft jetzt AUF PC 2. Das Bild geht deshalb über Jarvis selbst
        # (WebSocket-Brücke zu x11vnc auf 127.0.0.1:5900, wie beim Haupt-PC) statt direkt an
        # Port 6080 - der war per Firewall nur für die alte Adresse des Haupt-PCs frei, darum
        # "Bildschirm nicht erreichbar". Funktioniert so auch vom Laptop und Handy über Jarvis.
        # Das VNC-Passwort fragt noVNC beim ersten Verbinden ab (Browser kann es sich merken).
        bildschirm = ("/novnc/vnc.html?autoconnect=true&resize=scale&reconnect=true&reconnect_delay=1500"
                      "&quality=6&compression=2&show_dot=true&path=api/geraete/pc2/vnc")
    elif host and k["vnc_port"]:
        bildschirm = (
            f"http://{host}:{k['vnc_port']}/vnc.html?autoconnect=true&resize=scale"
            "&reconnect=true&reconnect_delay=1500&quality=6&compression=2&show_dot=true"
        )
    return {
        "eingerichtet": bool(k["url"] and k["token"]),
        "host": host,
        "wecken_moeglich": bool(_MAC.match(k["mac"])),
        "bildschirm_url": bildschirm,
    }


def _kopf() -> dict[str, str]:
    k = konfig()
    if not (k["url"] and k["token"]):
        raise Pc2Fehler("PC 2 ist noch nicht eingerichtet (PC2_EINRICHTEN.bat)", 409)
    geraeteschutz.netz_pruefen(k["url"], "PC 2")  # jeder Aufruf an PC 2 holt vorher den Kopf
    return {"Authorization": f"Bearer {k['token']}"}


def _fehler_aus(exc: Exception) -> Pc2Fehler:
    if isinstance(exc, httpx.ConnectError):
        return Pc2Fehler("PC 2 nicht erreichbar (aus, anderes Netz oder Agent läuft nicht)", 504)
    if isinstance(exc, httpx.TimeoutException):
        return Pc2Fehler("PC 2 antwortet nicht rechtzeitig", 504)
    return Pc2Fehler(f"Verbindung zu PC 2 fehlgeschlagen: {exc}", 502)


def _antwort_pruefen(r: httpx.Response) -> Any:
    try:
        daten = r.json()
    except ValueError:
        daten = {}
    if r.status_code == 401:
        raise Pc2Fehler("PC 2 lehnt den Token ab - Kopplungszeile neu eintragen", 502)
    if r.status_code == 429:
        raise Pc2Fehler("PC 2 sperrt kurz wegen Fehlversuchen", 502)
    if r.status_code >= 400 and not isinstance(daten, dict):
        raise Pc2Fehler(f"PC 2 antwortet mit {r.status_code}", 502)
    return daten


def status() -> dict[str, Any]:
    kopf = _kopf()
    start = time.perf_counter()
    try:
        r = httpx.get(konfig()["url"] + "/status", headers=kopf, timeout=4)
    except httpx.HTTPError as exc:
        raise _fehler_aus(exc) from exc
    daten = _antwort_pruefen(r)
    if isinstance(daten, dict):
        daten["latenz_ms"] = round((time.perf_counter() - start) * 1000)
    return daten


def aktionen() -> dict[str, Any]:
    try:
        r = httpx.get(konfig()["url"] + "/aktionen", headers=_kopf(), timeout=4)
    except httpx.HTTPError as exc:
        raise _fehler_aus(exc) from exc
    return _antwort_pruefen(r)


def aktion(name: str, ziel: Any = None, bestaetigt: bool = False) -> dict[str, Any]:
    if name in GEFAEHRLICH and not bestaetigt:
        raise Pc2Fehler("Diese Aktion braucht eine Bestätigung", 400)
    kopf = _kopf()
    try:
        r = httpx.post(konfig()["url"] + "/aktion", headers=kopf, json={"aktion": name, "ziel": ziel}, timeout=130)
    except httpx.HTTPError as exc:
        # Beim Neustart/Herunterfahren reißt die Verbindung oft ab - das ist Erfolg.
        if name in ("neustart", "herunterfahren"):
            return {"ok": True, "meldung": "Befehl gesendet, PC 2 fährt herunter"}
        raise _fehler_aus(exc) from exc
    daten = _antwort_pruefen(r)
    return daten if isinstance(daten, dict) else {"ok": False, "meldung": "Unerwartete Antwort"}


def stream() -> Iterator[bytes]:
    """Leitet die Server-Sent Events des Agenten 1:1 weiter.

    Bei Abbruch kommt ein eigenes Ereignis "fehler"; das HUD verbindet sich
    dann selbst neu (EventSource). Die Latenz hängt jedes Paket mit an.
    """
    try:
        kopf = _kopf()
    except Pc2Fehler as exc:
        yield _ereignis("fehler", {"meldung": str(exc)})
        return
    try:
        with httpx.stream(
            "GET", konfig()["url"] + "/stream", headers=kopf,
            timeout=httpx.Timeout(5, read=30),
        ) as r:
            if r.status_code != 200:
                r.read()
                try:
                    _antwort_pruefen(r)
                except Pc2Fehler as exc:
                    yield _ereignis("fehler", {"meldung": str(exc)})
                    return
                yield _ereignis("fehler", {"meldung": f"PC 2 antwortet mit {r.status_code}"})
                return
            for zeile in r.iter_lines():
                if zeile.startswith("data: "):
                    yield (zeile + "\n\n").encode("utf-8")
                elif zeile.startswith(":"):
                    yield b": ping\n\n"
    except httpx.HTTPError as exc:
        yield _ereignis("fehler", {"meldung": str(_fehler_aus(exc))})


def _ereignis(typ: str, daten: dict[str, Any]) -> bytes:
    return f"event: {typ}\ndata: {json.dumps(daten, ensure_ascii=False)}\n\n".encode("utf-8")


def magic_packet(mac: str) -> bytes:
    if not _MAC.match(mac):
        raise Pc2Fehler("PC2_MAC fehlt oder ist ungültig", 409)
    roh = bytes.fromhex(re.sub(r"[:-]", "", mac))
    return b"\xff" * 6 + roh * 16


def wecken() -> dict[str, Any]:
    """Wake-on-LAN: Magic Packet als Broadcast (Port 9 und 7)."""
    paket = magic_packet(konfig()["mac"])
    geraeteschutz.lokal_pruefen("Wake-on-LAN")
    ziele = ["255.255.255.255"]
    host = urlparse(konfig()["url"]).hostname or ""
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
        ziele.append(".".join(host.split(".")[:3] + ["255"]))  # Heimnetz /24
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for ziel in ziele:
            for port in (9, 7):
                try:
                    s.sendto(paket, (ziel, port))
                except OSError:
                    pass
    return {"ok": True, "meldung": "Weckruf gesendet - PC 2 braucht ca. 30-60 s"}

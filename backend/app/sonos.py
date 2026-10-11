"""Lautstärke direkt an den Sonos-Boxen im WLAN.

Warum das nötig ist: Spotify lehnt den Lautstärke-Befehl für Sonos-Geräte mit
HTTP 403 ab (am 21.09.2026 am echten Konto bestätigt). Titel, Pause und Suche
gehen über Spotify - nur die Lautstärke läuft über diesen Weg.

Sonos-Boxen sind UPnP-Geräte und hören auf Port 1400. Wir schicken zwei
SOAP-Aufrufe (GetVolume, SetVolume) - keine Amazon-Cloud, kein Konto, kein
zusätzliches Paket. Voraussetzung: der PC ist im selben Netz wie die Boxen.

Die Boxen werden per SSDP gesucht (Rundruf ins Netz). Das kann eine Windows-
Firewall blockieren; dann die Adressen fest in die .env schreiben:

    SONOS_IPS=192.168.1.40,192.168.1.41

Die IP steht in der Sonos-App unter Einstellungen -> System -> Produkte.
"""

from __future__ import annotations

import os
import re
import socket
import threading
import time
from xml.sax.saxutils import escape

import requests

from . import geraeteschutz

PORT = 1400
TIMEOUT = 3
SSDP_ZIEL = ("239.255.255.250", 1900)
SSDP_SUCHE = (
    "M-SEARCH * HTTP/1.1\r\n"
    "HOST: 239.255.255.250:1900\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 1\r\n"
    "ST: urn:schemas-upnp-org:device:ZonePlayer:1\r\n\r\n"
)
CACHE_S = 5 * 60

_sperre = threading.Lock()
_boxen: list[dict] = []
_boxen_zeit = 0.0


class SonosFehler(RuntimeError):
    """Box nicht erreichbar oder Antwort unbrauchbar."""


def _feste_ips() -> list[str]:
    roh = (os.getenv("SONOS_IPS") or "").strip().strip('"').strip("'")
    return [teil.strip() for teil in roh.split(",") if teil.strip()]


def _raumname(ip: str) -> str | None:
    """Fragt die Box, wie ihr Raum heißt (z.B. 'Schlafzimmer')."""
    try:
        geraeteschutz.netz_pruefen(f"{ip}:{PORT}", "Sonos")
        antwort = requests.get(f"http://{ip}:{PORT}/xml/device_description.xml", timeout=TIMEOUT)
        if antwort.status_code != 200:
            return None
        treffer = re.search(r"<roomName>(.*?)</roomName>", antwort.text, re.S)
        return treffer.group(1).strip() if treffer else None
    except requests.RequestException:
        return None


def _ssdp_suche() -> list[str]:
    """Rundruf ins Netz. Gibt die IPs antwortender Sonos-Boxen zurück."""
    gefunden: list[str] = []
    geraeteschutz.lokal_pruefen("Sonos-Suche im Netz")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.settimeout(2)
        s.sendto(SSDP_SUCHE.encode(), SSDP_ZIEL)
        ende = time.time() + 2
        while time.time() < ende:
            try:
                _, adresse = s.recvfrom(2048)
            except socket.timeout:
                break
            if adresse[0] not in gefunden:
                gefunden.append(adresse[0])
        s.close()
    except OSError:
        return []
    return gefunden


def boxen(erzwingen: bool = False) -> list[dict]:
    """Alle gefundenen Boxen als [{'name': 'Schlafzimmer', 'ip': '...'}]."""
    global _boxen, _boxen_zeit
    with _sperre:
        if not erzwingen and _boxen and time.time() - _boxen_zeit < CACHE_S:
            return _boxen
        ips = _feste_ips() or _ssdp_suche()
        liste = []
        for ip in ips:
            name = _raumname(ip)
            if name:
                liste.append({"name": name, "ip": ip})
        _boxen, _boxen_zeit = liste, time.time()
        return liste


def finde(geraetename: str) -> dict | None:
    """Sucht die Box, die zum Spotify-Gerätenamen passt."""
    ziel = (geraetename or "").strip().lower()
    if not ziel:
        return None
    liste = boxen()
    for box in liste:
        if box["name"].lower() == ziel:
            return box
    # Gruppen heißen in Spotify oft "Schlafzimmer + 1" o.ä.
    for box in liste:
        if box["name"].lower() in ziel or ziel.startswith(box["name"].lower()):
            return box
    return None


def alle_mit_namen(geraetename: str) -> list[dict]:
    """Alle Boxen, die zu diesem Gerätenamen passen.

    Bei Sir melden sich zwei Boxen als "Schlafzimmer" (.116 und .113). Ein
    Gruppenbefehl an eine davon hat nur eine geregelt - am 21.09.2026 am
    echten Gerät gesehen. Deshalb sprechen wir beide an."""
    ziel = (geraetename or "").strip().lower()
    if not ziel:
        return []
    liste = boxen()
    genau = [b for b in liste if b["name"].lower() == ziel]
    if genau:
        return genau
    return [b for b in liste if b["name"].lower() in ziel or ziel.startswith(b["name"].lower())]


def _soap(ip: str, aktion: str, koerper: str, dienst: str = "RenderingControl") -> str:
    umschlag = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
        f'<u:{aktion} xmlns:u="urn:schemas-upnp-org:service:{dienst}:1">'
        f"{koerper}</u:{aktion}></s:Body></s:Envelope>"
    )
    geraeteschutz.netz_pruefen(f"{ip}:{PORT}", "Sonos")
    try:
        antwort = requests.post(
            f"http://{ip}:{PORT}/MediaRenderer/{dienst}/Control",
            data=umschlag.encode("utf-8"),
            headers={
                "Content-Type": 'text/xml; charset="utf-8"',
                "SOAPACTION": f'"urn:schemas-upnp-org:service:{dienst}:1#{aktion}"',
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise SonosFehler(f"Box {ip} nicht erreichbar.") from exc
    if antwort.status_code != 200:
        raise SonosFehler(f"Box {ip} antwortete mit HTTP {antwort.status_code}.")
    return antwort.text


def _einzel_lesen(ip: str) -> int:
    text = _soap(ip, "GetVolume", "<InstanceID>0</InstanceID><Channel>Master</Channel>")
    treffer = re.search(r"<CurrentVolume>(\d+)</CurrentVolume>", text)
    if not treffer:
        raise SonosFehler("Box lieferte keine Lautstärke.")
    return int(treffer.group(1))


def _einzel_setzen(ip: str, prozent: int) -> int:
    _soap(
        ip,
        "SetVolume",
        f"<InstanceID>0</InstanceID><Channel>Master</Channel>"
        f"<DesiredVolume>{escape(str(prozent))}</DesiredVolume>",
    )
    return prozent


def _gruppe_lesen(ip: str) -> int:
    """Lautstärke der ganzen Gruppe (Stereopaar, verbundene Räume)."""
    text = _soap(ip, "GetGroupVolume", "<InstanceID>0</InstanceID>", dienst="GroupRenderingControl")
    treffer = re.search(r"<CurrentVolume>(\d+)</CurrentVolume>", text)
    if not treffer:
        raise SonosFehler("Box lieferte keine Gruppenlautstärke.")
    return int(treffer.group(1))


def _gruppe_setzen(ip: str, prozent: int) -> int:
    _soap(
        ip,
        "SetGroupVolume",
        f"<InstanceID>0</InstanceID><DesiredVolume>{escape(str(prozent))}</DesiredVolume>",
        dienst="GroupRenderingControl",
    )
    return prozent


def lautstaerke_lesen(ip: str) -> int:
    """Erst die Gruppe fragen, sonst die einzelne Box.

    Wichtig bei einem Stereopaar: dort tragen beide Boxen denselben Raumnamen
    (bei Sir zweimal "Schlafzimmer", .116 und .113). Nur eine davon zu regeln
    ändert die halbe Anlage."""
    try:
        return _gruppe_lesen(ip)
    except SonosFehler:
        return _einzel_lesen(ip)


def lautstaerke_setzen(ip: str, prozent: int) -> int:
    prozent = max(0, min(100, int(prozent)))
    try:
        return _gruppe_setzen(ip, prozent)
    except SonosFehler:
        return _einzel_setzen(ip, prozent)


def ist_moeglich() -> bool:
    """Gibt es überhaupt erreichbare Boxen?"""
    try:
        return bool(boxen())
    except Exception:  # noqa: BLE001 - Netzfehler dürfen Jarvis nicht stoppen
        return False


def transport(ip: str, aktion: str) -> None:
    """Weiter, Zurück, Pause oder Abspielen direkt an der Box.

    Spotify lehnt diese Befehle für Sonos ebenso ab wie die Lautstärke
    (403). Der lokale Weg über AVTransport funktioniert."""
    koerper = {
        "Next": "<InstanceID>0</InstanceID>",
        "Previous": "<InstanceID>0</InstanceID>",
        "Pause": "<InstanceID>0</InstanceID>",
        "Play": "<InstanceID>0</InstanceID><Speed>1</Speed>",
    }.get(aktion)
    if koerper is None:
        raise SonosFehler(f"Unbekannter Transportbefehl: {aktion}")
    _soap(ip, aktion, koerper, dienst="AVTransport")


def lautstaerke_setzen_alle(boxen_liste: list[dict], prozent: int) -> int:
    """Setzt dieselbe Lautstärke auf allen übergebenen Boxen.

    Gibt den Wert zurück, sobald mindestens eine Box ihn angenommen hat -
    eine stumme zweite Box soll den Regler nicht blockieren."""
    prozent = max(0, min(100, int(prozent)))
    geklappt = False
    letzter: Exception | None = None
    for box in boxen_liste:
        try:
            lautstaerke_setzen(box["ip"], prozent)
            geklappt = True
        except SonosFehler as exc:
            letzter = exc
    if not geklappt:
        raise SonosFehler(str(letzter) if letzter else "Keine Box hat geantwortet.")
    return prozent

"""
Schutz vor echten Geräten und echtem Netz beim Testen (11.10.2026, Claude Code).

Vorfall 11.10.2026: Ein Testlauf auf Sirs Windows-PC hat Chrome geöffnet und den PC
neu gestartet; andere Tests riefen Wikipedia (HTTP 429) und einen Dienst mit HTTP 401 auf.

Diese Datei wird vor jedem App-Import geladen (tests/test_000_isolierung.py läuft beim
"discover" zuerst; die Geräte-Tests laden sie zusätzlich selbst). Sie
  1. setzt AURON_TESTMODUS=1 - die zentrale Sperre in app/geraeteschutz.py greift,
  2. erlaubt Verbindungen nur zu Servern, die der Testlauf selbst geöffnet hat
     (Test-Stubs auf 127.0.0.1) - alles andere (Internet, Sirs PC-Agent, Ollama,
     Sonos, laufendes Jarvis) scheitert sofort,
  3. lässt jeden Test scheitern, in dem so ein Versuch vorkam - auch wenn der
     App-Code den Fehler abfängt.
Der Name beginnt nicht mit test_, damit unittest ihn nicht als Test sammelt.
"""

from __future__ import annotations

import contextlib
import ipaddress
import os
import socket
import sys
import threading
import unittest
from unittest import mock

os.environ["AURON_TESTMODUS"] = "1"

from app import geraeteschutz  # noqa: E402  (erst nach dem Setzen des Testmodus)

_LOOPBACK = {"127.0.0.1", "localhost", "::1", "", "0.0.0.0"}
_eigene_ports: set[int] = set()   # Ports, die dieser Testlauf selbst geöffnet hat (Stub-Server, socketpair)
_verstoesse: list[str] = []
_sperre = threading.Lock()


class NetzGesperrt(geraeteschutz.GeraetGesperrt):
    pass


def verstoesse() -> list[str]:
    with _sperre:
        return list(_verstoesse)


def _verstoss(text: str) -> None:
    meldung = f"Testschutz: {text}. Tests duerfen nur eigene Test-Stubs auf 127.0.0.1 ansprechen (Mock benutzen)."
    with _sperre:
        _verstoesse.append(meldung)
    raise NetzGesperrt(meldung)


def _ist_lokal(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    host = str(host or "").strip("[]").lower()
    if host in _LOOPBACK:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _ist_ip(host) -> bool:
    try:
        ipaddress.ip_address(str(host).strip("[]"))
        return True
    except ValueError:
        return False


def _ziel_erlaubt(adresse) -> bool:
    if not isinstance(adresse, tuple) or len(adresse) < 2:
        return True  # AF_UNIX o.ä. - kein Netz
    host, port = adresse[0], adresse[1]
    with _sperre:
        eigen = port in _eigene_ports
    return _ist_lokal(host) and (eigen or geraeteschutz.ist_testziel("127.0.0.1", port))


_orig_bind = socket.socket.bind
_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
_orig_sendto = socket.socket.sendto
_orig_getaddrinfo = socket.getaddrinfo


def _bind(self, adresse):
    erg = _orig_bind(self, adresse)
    try:
        name = self.getsockname()
        if isinstance(name, tuple) and _ist_lokal(name[0]):
            with _sperre:
                _eigene_ports.add(name[1])
    except OSError:
        pass
    return erg


def _connect(self, adresse):
    # UDP-connect sendet nichts (pc2.ist_hier wählt damit nur die eigene Adresse)
    if self.type != socket.SOCK_DGRAM and not _ziel_erlaubt(adresse):
        _verstoss(f"Verbindung zu {adresse!r} gesperrt")
    return _orig_connect(self, adresse)


def _connect_ex(self, adresse):
    if self.type != socket.SOCK_DGRAM and not _ziel_erlaubt(adresse):
        _verstoss(f"Verbindung zu {adresse!r} gesperrt")
    return _orig_connect_ex(self, adresse)


def _sendto(self, daten, *args):
    adresse = args[-1] if args else None
    if not _ziel_erlaubt(adresse):
        _verstoss(f"Senden an {adresse!r} gesperrt")
    return _orig_sendto(self, daten, *args)


def _getaddrinfo(host, *args, **kwargs):
    # Namensauflösung ist schon Netz (DNS) - nur lokale Namen und IP-Adressen
    if host is not None and not _ist_lokal(host) and not _ist_ip(host):
        _verstoss(f"Namensauflösung für {host!r} gesperrt")
    return _orig_getaddrinfo(host, *args, **kwargs)


# Jeder Test, in dem ein gesperrter Versuch vorkam, scheitert - auch wenn der App-Code
# den Fehler abgefangen und z.B. "nicht erreichbar" gemeldet hat.
_orig_run = unittest.TestCase.run


def _run(self, result=None):
    vorher = len(verstoesse())
    erg = _orig_run(self, result)
    neu = verstoesse()[vorher:]
    if neu and result is not None:
        try:
            raise AssertionError("\n".join(dict.fromkeys(neu)))
        except AssertionError:
            result.addFailure(self, sys.exc_info())
    return erg


@contextlib.contextmanager
def erwartete_verstoesse():
    """Nur für den Test des Wächters selbst: fängt Verstöße im Block ein, statt den Test scheitern zu lassen."""
    with _sperre:
        vorher = len(_verstoesse)
    gefangen: list[str] = []
    try:
        yield gefangen
    finally:
        with _sperre:
            gefangen.extend(_verstoesse[vorher:])
            del _verstoesse[vorher:]


def sperre_aus_weil_gemockt():
    """Schaltet die App-Sperre (app/geraeteschutz.py) für einen Block ab - NUR, wenn der Test
    den gefährlichen Teil selbst ersetzt hat (subprocess.run, httpx.request ...). Der Netz-Wächter
    oben bleibt trotzdem aktiv."""
    return mock.patch.object(geraeteschutz, "testmodus", return_value=False)


def stub_freigeben(testfall: unittest.TestCase, port: int) -> None:
    """Gibt einen Test-Stub auf 127.0.0.1:<port> für die App-Sperre frei, bis zum Ende des Tests."""
    geraeteschutz.testziel_erlauben(port)
    testfall.addCleanup(geraeteschutz.testziel_entfernen, port)


def _einbauen() -> None:
    if getattr(socket, "_auron_testschutz", False):
        return  # schon eingebaut (Datei unter zwei Modulnamen geladen)
    socket._auron_testschutz = True
    socket.socket.bind = _bind
    socket.socket.connect = _connect
    socket.socket.connect_ex = _connect_ex
    socket.socket.sendto = _sendto
    socket.getaddrinfo = _getaddrinfo
    unittest.TestCase.run = _run


_einbauen()

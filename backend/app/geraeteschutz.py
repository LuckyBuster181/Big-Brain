"""
Geräteschutz im Testmodus (11.10.2026, Claude Code).

Vorfall 11.10.2026: Ein Testlauf auf Sirs Windows-PC hat Chrome geöffnet und den PC
neu gestartet - der Test startete den echten PC-Agenten im selben Prozess.

Ist AURON_TESTMODUS=1 gesetzt (setzt tests/testschutz.py vor jedem App-Import),
gilt hier eine zentrale Sperre:
  - Aufrufe an Geräte (Haupt-PC, PC 2, Sonos, Spotify) gehen nur an Test-Stubs,
    die ein Test ausdrücklich mit testziel_erlauben() freigibt (nur 127.0.0.1).
  - Lokale Aktionen (Programme starten, TightVNC umstellen, Herunterfahren ...)
    sind immer gesperrt.
Sonst: GeraetGesperrt mit klarer Meldung. Im normalen Betrieb ändert sich nichts.
"""

from __future__ import annotations

import os
import threading
from urllib.parse import urlparse

LOOPBACK = {"127.0.0.1", "localhost", "::1"}

_testziele: set[int] = set()
_sperre = threading.Lock()


class GeraetGesperrt(RuntimeError):
    """Absichtlich kein OSError: darf von keinem "except OSError" verschluckt werden."""


def testmodus() -> bool:
    return (os.getenv("AURON_TESTMODUS") or "").strip() == "1"


def testziel_erlauben(port: int) -> None:
    """Gibt einen Test-Stub auf 127.0.0.1:<port> frei."""
    with _sperre:
        _testziele.add(int(port))


def testziel_entfernen(port: int) -> None:
    with _sperre:
        _testziele.discard(int(port))


def ist_testziel(host: str | None, port: int | None) -> bool:
    with _sperre:
        return (host or "").lower() in LOOPBACK and port in _testziele


def netz_pruefen(url: str, was: str) -> None:
    """Vor jedem Aufruf an ein Gerät. Im Testmodus nur freigegebene Test-Stubs."""
    if not testmodus():
        return
    teile = urlparse(url if "://" in url else "http://" + url)
    try:
        port = teile.port or (443 if teile.scheme == "https" else 80)
    except ValueError:
        port = None
    if not ist_testziel(teile.hostname, port):
        raise GeraetGesperrt(f"Testmodus: {was} an {url} gesperrt (kein freigegebener Test-Stub).")


def lokal_pruefen(was: str) -> None:
    """Vor jeder lokalen Aktion (Programm, Herunterfahren, Neustart, Browser ...). Im Testmodus immer gesperrt."""
    if testmodus():
        raise GeraetGesperrt(f"Testmodus: {was} gesperrt.")

"""Tests für app/agenten.py (Agenten-Station, 10.10.2026). Ohne KI, ohne Netz."""

from __future__ import annotations

import threading
import unittest
from unittest import mock

from app import agenten


def _als_datei(dateiname: str, funktion: str = "arbeiten"):
    """Baut eine Funktion, deren Code scheinbar in app/<dateiname> steht (für den Aufrufstapel)."""
    quelle = f"def {funktion}(f):\n    return f()\n"
    ns: dict = {}
    exec(compile(quelle, f"/x/backend/app/{dateiname}", "exec"), ns)  # noqa: S102 - nur Test
    return ns[funktion]


class Codestelle(unittest.TestCase):
    def setUp(self):
        agenten.leeren()

    def test_agent_aus_datei(self):
        arbeiten = _als_datei("nachtauftraege.py", "_auftrag_bearbeiten")
        e = arbeiten(lambda: agenten.melden("start", "fragt Test-PC", rechner="Test-PC"))
        self.assertEqual(e["agent"], "nachtauftraege")
        self.assertEqual(e["code"]["datei"], "app/nachtauftraege.py")
        self.assertEqual(e["code"]["funktion"], "_auftrag_bearbeiten")

    def test_hilfsdateien_werden_uebersprungen(self):
        aussen = _als_datei("kamera.py", "sehen")
        hilfe = _als_datei("ki_aufruf.py", "aufrufen")
        e = aussen(lambda: hilfe(lambda: agenten.melden("start", "x")))
        self.assertEqual(e["agent"], "kamera")
        self.assertEqual(e["code"]["datei"], "app/kamera.py")

    def test_als_hat_vorrang(self):
        arbeiten = _als_datei("studium.py")
        with agenten.als("briefing"):
            e = arbeiten(lambda: agenten.melden("info", "x"))
        self.assertEqual(e["agent"], "briefing")
        e2 = arbeiten(lambda: agenten.melden("info", "y"))
        self.assertEqual(e2["agent"], "studium")

    def test_thread_name(self):
        ergebnis = {}
        t = threading.Thread(target=lambda: ergebnis.update(agenten.melden("info", "z")), name="jarvis-nachtarbeit")
        t.start(); t.join()
        self.assertEqual(ergebnis["agent"], "nachtarbeit")

    def test_unbekannt_ist_gespraech(self):
        self.assertEqual(agenten.melden("info", "q")["agent"], "gespraech")


class Uebersicht(unittest.TestCase):
    def setUp(self):
        agenten.leeren()
        self.p1 = mock.patch.object(agenten, "_ampel", return_value={
            "studium": {"name": "Studium", "farbe": "rot", "text": "Letzter Lauf mit Fehler: x"},
            "vault": {"name": "Vault einlesen", "farbe": "gruen", "text": "liest den Vault ein"}})
        self.p2 = mock.patch.object(agenten, "_rechner", return_value=[{"name": "Haupt-PC", "erreichbar": True}])
        self.p1.start(); self.p2.start()

    def tearDown(self):
        self.p1.stop(); self.p2.stop()

    def _a(self, u, aid):
        return next(a for a in u["agenten"] if a["id"] == aid)

    def test_start_und_ende(self):
        agenten.melden("start", "fragt Haupt-PC", agent="gespraech", rechner="Haupt-PC", modell="qwen")
        u = agenten.uebersicht()
        a = self._a(u, "gespraech")
        self.assertEqual(a["zustand"], "arbeitet")
        self.assertEqual(a["rechner"], "Haupt-PC")
        agenten.melden("ende", "fertig", agent="gespraech")
        a = self._a(agenten.uebersicht(), "gespraech")
        self.assertEqual(a["zustand"], "ruht")
        self.assertIn("fertig", a["text"])
        self.assertEqual(len(a["letzte"]), 2)

    def test_ampel_zustaende(self):
        u = agenten.uebersicht()
        self.assertEqual(self._a(u, "studium")["zustand"], "fehler")
        self.assertEqual(self._a(u, "vault")["zustand"], "arbeitet")
        self.assertEqual(self._a(u, "tiktok")["zustand"], "ruht")
        self.assertEqual(len(u["agenten"]), len(agenten.ROLLEN))

    def test_haengender_start_zaehlt_nicht(self):
        e = agenten.melden("start", "fragt", agent="alltag")
        with agenten._lock:  # noqa: SLF001
            agenten._aktuell["alltag"]["t"] -= agenten.HAENGT_NACH_S + 1  # noqa: SLF001
        self.assertEqual(self._a(agenten.uebersicht(), "alltag")["zustand"], "ruht")
        self.assertTrue(e)

    def test_verlauf_begrenzt_und_ohne_t(self):
        for i in range(agenten.MAX_VERLAUF + 20):
            agenten.melden("info", str(i), agent="alltag")
        u = agenten.uebersicht(anzahl=5)
        self.assertEqual(len(u["verlauf"]), 5)
        self.assertEqual(u["verlauf"][0]["text"], str(agenten.MAX_VERLAUF + 19))
        self.assertNotIn("t", u["verlauf"][0])

    def test_melden_wirft_nie(self):
        with mock.patch.object(agenten, "codestelle", side_effect=RuntimeError("kaputt")):
            self.assertEqual(agenten.melden("start", "x"), {})


if __name__ == "__main__":
    unittest.main()

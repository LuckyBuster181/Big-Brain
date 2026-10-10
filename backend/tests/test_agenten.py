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


class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text
        self.citations = None


class _Antwort:
    def __init__(self, text):
        self.content = [_Block(text)]
        self.usage = None
        self.stop_reason = "end_turn"


class _Client:
    """Merkt sich die Aufrufe; antwortet je Aufruf mit dem nächsten Text."""
    def __init__(self, *texte):
        self.texte = list(texte)
        self.aufrufe = []
        self.messages = self

    def create(self, **kw):
        self.aufrufe.append(kw)
        return _Antwort(self.texte.pop(0))


class RollenSucherSchreiber(unittest.TestCase):
    def setUp(self):
        agenten.leeren()
        self.p = [mock.patch("app.ki_aufruf.chat_service.log_usage"),
                  mock.patch("app.ki_aufruf._lokal", return_value=False),
                  mock.patch.object(agenten, "_vault_material", return_value="VAULT-TREFFER Notiz B")]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def test_rollen_vorhanden(self):
        ids = [r["id"] for r in agenten.ROLLEN]
        self.assertIn("sucher", ids)
        self.assertIn("schreiber", ids)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(agenten.ROLLEN_SYSTEM), {"sucher", "schreiber"})

    def test_systemtexte(self):
        self.assertIn("NUR Rohmaterial", agenten.SUCHER_SYSTEM)
        self.assertIn("NICHT selbst", agenten.SUCHER_SYSTEM)
        self.assertIn("Sir", agenten.SCHREIBER_SYSTEM)
        self.assertIn("Emojis", agenten.SCHREIBER_SYSTEM)

    def test_sucher_guenstiges_modell_ohne_internet(self):
        from app import ki_aufruf
        c = _Client("VAULT: x")
        agenten.rolle_aufrufen("sucher", "Wie war das mit dem Vertrag?", client=c, vault_material="Notiz A: ...")
        kw = c.aufrufe[0]
        self.assertEqual(kw["model"], ki_aufruf.HAIKU)
        self.assertNotIn("tools", kw)
        self.assertIn("<vault_treffer>", kw["messages"][0]["content"])

    def test_sucher_mit_internet_nutzt_websuche(self):
        c = _Client("INTERNET: y")
        agenten.rolle_aufrufen("sucher", "Preis Powerbank", client=c, internet=True)
        self.assertEqual(c.aufrufe[0]["tools"][0]["name"], "web_search")

    def test_unbekannte_rolle(self):
        with self.assertRaises(ValueError):
            agenten.rolle_aufrufen("koch", "x", client=_Client("a"))

    def test_sucher_dann_schreiber(self):
        from app import ki_aufruf
        c = _Client("VAULT: Notiz A sagt 5 Euro", "Sir, es kostet 5 Euro.")
        e = agenten.sucher_und_schreiber("Was kostet das?", client=c)
        self.assertEqual(e["text"], "Sir, es kostet 5 Euro.")
        self.assertEqual(e["rohmaterial"], "VAULT: Notiz A sagt 5 Euro")
        sucher, schreiber = c.aufrufe
        self.assertEqual(sucher["model"], ki_aufruf.HAIKU)
        self.assertEqual(schreiber["model"], ki_aufruf.SONNET)
        self.assertIn("Notiz A sagt 5 Euro", schreiber["messages"][0]["content"])
        self.assertNotIn("<rohmaterial>", sucher["messages"][0]["content"])

    def test_meldungen_unter_der_rolle(self):
        agenten.sucher_und_schreiber("Was kostet das?", client=_Client("roh", "Sir, ok."))
        wer = {e["agent"] for e in agenten.uebersicht()["verlauf"]}
        self.assertEqual(wer, {"sucher", "schreiber"})

    def test_vault_wird_selbst_durchsucht(self):
        c = _Client("roh", "Sir, ok.")
        agenten.sucher_und_schreiber("Was steht zum Vertrag?", client=c)
        agenten._vault_material.assert_called_once_with("Was steht zum Vertrag?")  # noqa: SLF001
        self.assertIn("VAULT-TREFFER Notiz B", c.aufrufe[0]["messages"][0]["content"])
        self.assertNotIn("VAULT-TREFFER", c.aufrufe[1]["messages"][0]["content"])  # Schreiber sucht nicht

    def test_mitgegebenes_vault_material_ersetzt_suche(self):
        c = _Client("roh", "Sir, ok.")
        agenten.sucher_und_schreiber("Was steht zum Vertrag?", client=c, vault_material="eigene Treffer")
        agenten._vault_material.assert_not_called()  # noqa: SLF001
        self.assertIn("eigene Treffer", c.aufrufe[0]["messages"][0]["content"])

    def test_zu_kurze_frage(self):
        from app import ki_aufruf
        with self.assertRaises(ki_aufruf.KiFehler):
            agenten.sucher_und_schreiber("hm", client=_Client("a"))


class VaultSucheFehler(unittest.TestCase):
    def test_fehler_wird_text(self):
        from app import werkzeuge
        with mock.patch.object(werkzeuge, "vault_suchen", side_effect=RuntimeError("kein Index")):
            self.assertIn("kein Index", agenten._vault_material("x"))  # noqa: SLF001


class ChatBefehl(unittest.TestCase):
    """Anschluss an den Chat: Erkennung (app/befehle.py) und Ausführung (app/chat_ablauf.py)."""

    def test_erkennung(self):
        from app import alltag
        a = alltag.absicht("Such und schreib: was kostet der neue Vertrag?")
        self.assertEqual(a, {"art": "sucher_schreiber", "frage": "was kostet der neue Vertrag?", "internet": False})
        a = alltag.absicht("Auron, such und schreib im Internet: beste Powerbank unter 50 Euro")
        self.assertEqual(a["art"], "sucher_schreiber")
        self.assertTrue(a["internet"])
        self.assertEqual(a["frage"], "beste Powerbank unter 50 Euro")
        self.assertTrue(alltag.absicht("Sucher und Schreiber: Stand Projekt Garten")["art"] == "sucher_schreiber")

    def test_alte_befehle_unveraendert(self):
        from app import alltag
        self.assertEqual(alltag.absicht("Such im Internet nach Mietpreisen in Köln")["art"], "recherche")
        self.assertIsNone(alltag.absicht("Such und schreib"))   # ohne Doppelpunkt und Frage: normale Nachricht

    def test_ausfuehrung_im_chat(self):
        from app import chat_ablauf
        erg = {"text": "Sir, es kostet 5 Euro.", "rohmaterial": "roh", "kosten_usd": 0.0}
        with mock.patch.object(agenten, "sucher_und_schreiber", return_value=erg) as m:
            text = chat_ablauf._neue_art({"art": "sucher_schreiber", "frage": "Was kostet das?", "internet": True})  # noqa: SLF001
        m.assert_called_once_with("Was kostet das?", internet=True)
        self.assertTrue(text.startswith("Sir, es kostet 5 Euro."))
        self.assertIn("Vault und Internet", text)

    def test_fehler_im_chat_freundlich(self):
        from app import chat_ablauf, ki_aufruf
        with mock.patch.object(agenten, "sucher_und_schreiber", side_effect=ki_aufruf.KiFehler("Rahmen leer")):
            text = chat_ablauf._neue_art({"art": "sucher_schreiber", "frage": "Was kostet das?"})  # noqa: SLF001
        self.assertEqual(text, "Das ging nicht, Sir: Rahmen leer")


if __name__ == "__main__":
    unittest.main()

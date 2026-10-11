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
        agenten.melden("start", "fragt Haupt-PC", agent="sucher", rechner="Haupt-PC", modell="qwen")
        u = agenten.uebersicht()
        a = self._a(u, "sucher")
        self.assertEqual(a["zustand"], "arbeitet")
        self.assertEqual(a["rechner"], "Haupt-PC")
        agenten.melden("ende", "fertig", agent="sucher")
        a = self._a(agenten.uebersicht(), "sucher")
        self.assertEqual(a["zustand"], "ruht")
        self.assertIn("fertig", a["text"])
        self.assertEqual(len(a["letzte"]), 2)

    def test_ampel_zustaende(self):
        u = agenten.uebersicht()
        self.assertEqual(self._a(u, "studium")["zustand"], "fehler")
        self.assertEqual(self._a(u, "vault")["zustand"], "arbeitet")
        self.assertEqual(self._a(u, "tiktok")["zustand"], "ruht")
        self.assertEqual(len(u["agenten"]), len(agenten.ROLLEN) - len(agenten.AUSGEBLENDET))

    def test_haengender_start_zaehlt_nicht(self):
        e = agenten.melden("start", "fragt", agent="kamera")
        with agenten._lock:  # noqa: SLF001
            agenten._aktuell["kamera"]["t"] -= agenten.HAENGT_NACH_S + 1  # noqa: SLF001
        self.assertEqual(self._a(agenten.uebersicht(), "kamera")["zustand"], "ruht")
        self.assertTrue(e)

    def test_verlauf_begrenzt_und_ohne_t(self):
        for i in range(agenten.MAX_VERLAUF + 20):
            agenten.melden("info", str(i), agent="kamera")
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
        self.assertEqual(set(agenten.ROLLEN_SYSTEM), {"sucher", "schreiber", "pruefer", "tester", "boss", "ingenieur", "dichter"})

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


SICHTBAR = ["kamera", "nachtarbeit", "nachtauftraege", "aufgaben_loop", "studium", "vault", "tiktok",
            "sucher", "schreiber", "pruefer", "tester", "boss", "ingenieur", "dichter"]


class StationAufgeraeumt(unittest.TestCase):
    """11.10.2026: Gespräch, Alltag, Briefing, Prüfstand nicht mehr als Agent anzeigen."""

    def setUp(self):
        agenten.leeren()
        self.p = [mock.patch.object(agenten, "_ampel", return_value={}),
                  mock.patch.object(agenten, "_rechner", return_value=[])]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def test_neue_rollen_in_rollen(self):
        ids = [r["id"] for r in agenten.ROLLEN]
        for neu in ("pruefer", "tester", "boss", "ingenieur", "dichter"):
            self.assertIn(neu, ids)
            r = next(x for x in agenten.ROLLEN if x["id"] == neu)
            self.assertTrue(r["name"] and r["rolle"])

    def test_sichtbare_liste(self):
        self.assertEqual([a["id"] for a in agenten.uebersicht()["agenten"]], SICHTBAR)

    def test_ausgeblendete_melden_intern_weiter(self):
        for aid in ("gespraech", "alltag", "briefing", "pruefstand"):
            self.assertEqual(agenten.melden("start", "fragt", agent=aid)["agent"], aid)   # intern weiter erfasst
        agenten.melden("info", "sichtbar", agent="kamera")
        u = agenten.uebersicht()
        self.assertFalse({"gespraech", "alltag", "briefing", "pruefstand"} & {a["id"] for a in u["agenten"]})
        self.assertEqual([e["agent"] for e in u["verlauf"]], ["kamera"])

    def test_api_agenten(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app import routes
        app = FastAPI()
        app.include_router(routes.router)
        agenten.melden("start", "plaudert", agent="gespraech")
        d = TestClient(app).get("/api/agenten").json()
        self.assertEqual([a["id"] for a in d["agenten"]], SICHTBAR)
        self.assertEqual(d["verlauf"], [])


class NeueRollen(unittest.TestCase):
    """Prüfer, Tester, Boss, Ingenieur, Dichter mit Stub-Client (ohne KI, ohne Netz)."""

    def setUp(self):
        agenten.leeren()
        self.p = [mock.patch("app.ki_aufruf.chat_service.log_usage"),
                  mock.patch("app.ki_aufruf._lokal", return_value=False)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def test_systemtexte_grundregeln(self):
        for rolle, text in agenten.ROLLEN_SYSTEM.items():
            for pflicht in ("Auron", '"Sir"', "Nichts erfinden", "ungeprüft"):
                self.assertIn(pflicht, text, f"{rolle}: {pflicht}")

    def test_jede_neue_rolle(self):
        from app import ki_aufruf
        faelle = {
            "pruefer": (dict(rohmaterial="Notiz A: 5 Euro"), ki_aufruf.HAIKU, ("<antwort>", "<rohmaterial>", "Notiz A: 5 Euro")),
            "tester": ({}, ki_aufruf.HAIKU, ("<beschreibung>",)),
            "boss": (dict(ergebnisse={"schreiber": "Sir, 5 Euro."}), ki_aufruf.SONNET,
                     ("<auftrag>", '<ergebnis rolle="schreiber">', "Sir, 5 Euro.")),
            "ingenieur": (dict(format="dot"), ki_aufruf.SONNET, ("<format>dot</format>", "<beschreibung>")),
            "dichter": (dict(zweck="Begrüßung"), ki_aufruf.SONNET, ("<zweck>", "Begrüßung", "<text>")),
        }
        for rolle, (extra, modell, inhalt) in faelle.items():
            with self.subTest(rolle=rolle):
                agenten.leeren()
                c = _Client(f"Antwort {rolle}")
                e = agenten.rolle_aufrufen(rolle, "Eingabe für " + rolle, client=c, **extra)
                kw = c.aufrufe[0]
                self.assertEqual(e["text"], f"Antwort {rolle}")
                self.assertEqual(kw["model"], modell)
                self.assertNotIn("tools", kw)
                self.assertIn("Eingabe für " + rolle, kw["messages"][0]["content"])
                for teil in inhalt:
                    self.assertIn(teil, kw["messages"][0]["content"])
                self.assertIn(agenten.ROLLEN_SYSTEM[rolle].split("\n")[0][:40], str(kw["system"]))
                self.assertEqual({x["agent"] for x in agenten._verlauf}, {rolle})  # noqa: SLF001 - meldet sich unter der Rolle

    def test_ingenieur_nur_mermaid_oder_dot(self):
        with self.assertRaises(ValueError):
            agenten.rolle_aufrufen("ingenieur", "x", client=_Client("a"), format="png")

    def test_urteil_lesen(self):
        self.assertEqual(agenten.urteil_lesen("URTEIL: nachbessern\nBEGRÜNDUNG: Quelle fehlt.\nSTELLEN: keine"),
                         {"urteil": "nachbessern", "begruendung": "Quelle fehlt."})
        self.assertEqual(agenten.urteil_lesen("Sieht gut aus.")["urteil"], "fraglich")   # nicht lesbar: nicht raten

    def test_codeblock(self):
        self.assertEqual(agenten.codeblock("Hier:\n```mermaid\nflowchart TD\n  A-->B\n```\nZeigt A."), "flowchart TD\n  A-->B")
        self.assertEqual(agenten.codeblock("kein Code"), "")

    def test_boss_runden(self):
        zurueck = "ENTSCHEIDUNG: zurück an Prüfer\nGRUND: Quelle fehlt.\nAUFTRAG AN ROLLE: Quelle prüfen."
        e1 = agenten.boss_pruefen("Auftrag", {"schreiber": "x"}, runde=1, client=_Client(zurueck))
        self.assertEqual((e1["entscheidung"], e1["rolle"], e1["auftrag_an_rolle"]), ("zurueck", "pruefer", "Quelle prüfen."))
        e2 = agenten.boss_pruefen("Auftrag", {"schreiber": "x"}, runde=2, client=_Client(zurueck))
        self.assertEqual((e2["entscheidung"], e2["rolle"]), ("an_sir", "pruefer"))
        c3 = _Client("nie gefragt")
        e3 = agenten.boss_pruefen("Auftrag", {}, runde=3, client=c3)
        self.assertEqual((e3["entscheidung"], c3.aufrufe), ("an_sir", []))
        fertig = agenten.boss_pruefen("A", {}, client=_Client("ENTSCHEIDUNG: fertig\nGRUND: Alles belegt."))
        self.assertEqual((fertig["entscheidung"], fertig["grund"]), ("fertig", "Alles belegt."))
        self.assertEqual(agenten.boss_pruefen("A", {}, client=_Client("weiß nicht"))["entscheidung"], "an_sir")
        self.assertEqual(agenten.boss_pruefen("A", {}, client=_Client("ENTSCHEIDUNG: zurück an Koch"))["entscheidung"], "an_sir")


if __name__ == "__main__":
    unittest.main()

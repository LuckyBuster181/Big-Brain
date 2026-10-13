"""P20 (13.10.2026): wechselnde Anreden (app/anrede.py). Zufall nur mit festem Startwert."""

from __future__ import annotations

import datetime
import random
import unittest
from unittest import mock

try:
    import testschutz  # noqa: F401
except ImportError:
    from tests import testschutz  # noqa: F401

from app import anrede, chat_ablauf, chat_service, hauptpc


def um(stunde: int, minute: int = 0) -> datetime.datetime:
    return datetime.datetime(2026, 10, 13, stunde, minute)


class Auswahl(unittest.TestCase):
    def test_warnung_fehler_rueckfrage_immer_sir(self):
        z = random.Random(1)
        for situation in ("warnung", "fehler", "rueckfrage", "stufe2"):
            for stunde in range(24):
                for _ in range(40):
                    self.assertEqual(anrede.anrede(situation, um(stunde), z), "Sir", (situation, stunde))

    def test_morgens_bis_mittags_sir_oder_mein_herr(self):
        z = random.Random(2)
        for stunde in (5, 8, 11, 12):
            for situation in ("normal", "ruhig", "erfolg", "pointe"):
                erlaubt = {"Sir", "mein Herr"} | (set(anrede.SCHWERE) if situation in ("erfolg", "pointe") else set())
                for _ in range(200):
                    self.assertIn(anrede.anrede(situation, um(stunde), z), erlaubt, (stunde, situation))

    def test_abends_und_ruhig_gehoben(self):
        z = random.Random(3)
        gesehen = {anrede.anrede("ruhig", um(19), z) for _ in range(400)}
        self.assertTrue({"der Herr", "junger Herr", "Herr Maxi"} <= gesehen)
        self.assertTrue(gesehen <= {"der Herr", "junger Herr", "Herr Maxi", "Sir"})
        ruhig_mittag = {anrede.anrede("ruhig", um(14), z) for _ in range(400)}
        self.assertTrue(ruhig_mittag <= set(anrede.ANREDEN))

    def test_schwere_anreden_hoechstens_jede_zehnte(self):
        z = random.Random(4)
        n, schwer = 20000, 0
        for i in range(n):
            if anrede.anrede("erfolg" if i % 2 else "pointe", um(6 + i % 15), z) in anrede.SCHWERE:
                schwer += 1
        self.assertGreater(schwer, 0)               # kommt gelegentlich vor
        self.assertLessEqual(schwer / n, 0.105)     # höchstens etwa jede zehnte Antwort

    def test_nie_schwer_bei_normalen_antworten(self):
        z = random.Random(5)
        for situation in ("normal", "ruhig", "warnung"):
            for stunde in range(24):
                for _ in range(100):
                    self.assertNotIn(anrede.anrede(situation, um(stunde), z), anrede.SCHWERE)

    def test_ab_22_uhr_knapp_meist_sir(self):
        z = random.Random(6)
        for stunde in (22, 23, 0, 3):
            antworten = [anrede.anrede("erfolg", um(stunde), z) for _ in range(1000)]
            self.assertTrue(set(antworten) <= {"Sir", "mein Herr"}, stunde)
            self.assertGreater(antworten.count("Sir") / 1000, 0.75, stunde)

    def test_gleicher_startwert_gleiche_folge(self):
        a = [anrede.anrede("ruhig", um(19), random.Random(7)) for _ in range(5)]
        b = [anrede.anrede("ruhig", um(19), random.Random(7)) for _ in range(5)]
        self.assertEqual(a, b)

    def test_mit_anrede_und_erkennung(self):
        self.assertEqual(anrede.mit_anrede("Erledigt.", "fehler", um(10)), "Erledigt, Sir.")
        for text in ("Sehr wohl, Sir.", "Der Herr wünschen Kaffee.", "Gern, mein Herr.", "Sehr wohl, Mylord.",
                     "Wie Eure Exzellenz befehlen.", "Gute Nacht, junger Herr.", "Bitte, Herr Maxi."):
            self.assertTrue(anrede.enthaelt_anrede(text), text)
        self.assertFalse(anrede.enthaelt_anrede("Erledigt."))
        self.assertFalse(anrede.enthaelt_anrede("Das Gesetz gilt für alle Herrscher"))


class Eingebaut(unittest.TestCase):
    def test_prompt_block(self):
        b = anrede.prompt_block(um(19, 5))
        for a in anrede.ANREDEN:
            self.assertIn(a, b)
        self.assertIn("19:05", b)
        self.assertIn("Abend", b)
        self.assertIn("immer \"Sir\"", b)
        self.assertNotIn("Jarvis", b)

    def test_system_prompt_zweiter_block_ohne_cache(self):
        with mock.patch.dict("os.environ", {"PROMPT_CACHE": "true"}):
            plain = chat_service.cache_system("lang")
            mit = chat_service.cache_system("lang", mit_anrede=True)
        self.assertEqual(len(plain), 1)
        self.assertEqual(len(mit), 2)
        self.assertIn("cache_control", mit[0])
        self.assertNotIn("cache_control", mit[1])   # wechselnder Teil stört den Cache nicht
        self.assertIn("ANREDE", mit[1]["text"])
        with mock.patch.dict("os.environ", {"PROMPT_CACHE": "false"}):
            self.assertIn("ANREDE", chat_service.cache_system("lang", mit_anrede=True))

    def test_kanarienvogel_kennt_alle_anreden(self):
        self.assertFalse(chat_ablauf.kanarienvogel("klassisch", "Sehr wohl, der Herr."))
        self.assertFalse(chat_ablauf.kanarienvogel("klassisch", "Erledigt, Mylord."))
        self.assertTrue(chat_ablauf.kanarienvogel("klassisch", "Erledigt."))

    def test_feste_texte_im_hauptpc(self):
        # Rückfrage vor Stufe 2 und Fehler immer "Sir", zu jeder Uhrzeit
        for stunde in (7, 13, 19, 23):
            with mock.patch.object(anrede, "_jetzt", return_value=um(stunde)):
                with mock.patch.dict("os.environ", {"HAUPTPC_URL": "http://127.0.0.1:1", "HAUPTPC_TOKEN": "t" * 32}):
                    frage = hauptpc.ausfuehren({"art": "pc", "aktion": "herunterfahren"})
                    self.assertIn("wirklich den Haupt-PC herunterfahren, Sir?", frage)
                with mock.patch.dict("os.environ", {"HAUPTPC_URL": "", "HAUPTPC_TOKEN": ""}):
                    self.assertIn(", Sir:", hauptpc.ausfuehren({"art": "pc", "aktion": "lauter"}))
            hauptpc._wartend.clear()


if __name__ == "__main__":
    unittest.main()

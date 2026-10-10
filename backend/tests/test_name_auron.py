"""Namenswechsel Jarvis -> Auron (04.10.2026): beide Namen muessen Befehle gleich ausloesen."""
import unittest

from app import alltag


class NameAuronTest(unittest.TestCase):
    FAELLE = [
        "{n}, öffne das Gedächtnis",
        "{n} öffne die geräte",
        "{n}, wie spät ist es",
        "{n}, wie ist der Kurs von Bitcoin",
    ]

    def test_beide_namen_gleich(self):
        for f in self.FAELLE:
            ohne = alltag.absicht(f.format(n="Jarvis"))
            mit = alltag.absicht(f.format(n="Auron"))
            self.assertIsNotNone(mit, f)
            # Uhrzeit-Antwort kann sich minutengenau unterscheiden; Art muss gleich sein
            self.assertEqual(ohne["art"], mit["art"], f)

    def test_seite_vault(self):
        r = alltag.absicht("Auron, öffne das Gedächtnis")
        self.assertEqual(r["seite"], "vault")


if __name__ == "__main__":
    unittest.main()

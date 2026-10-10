"""Tests für die Notizliste des Dashboards (app/vault_list.py)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import vault_list


class VaultListTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        files = {
            "Wissen/A.md": "---\ntitel: Notiz A\nstatus: aktiv\nniveau: einstieg\n---\n# A\n\nInhalt",
            "Wissen/B.md": "# B\n\nOhne Frontmatter, Link auf [[A]] und `[[Im Code]]`",
            "Wissen/C.md": "---\njarvis: ignorieren\n---\n# C\n\nPlatzhalter",
            "Archiv/Alt.md": "# Alt",
            ".obsidian/workspace.md": "x",
        }
        for rel, text in files.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.notes = {n["pfad"]: n for n in vault_list.notes(self.root)}

    def test_uebersprungene_ordner_fehlen(self):
        self.assertNotIn(".obsidian/workspace.md", self.notes)

    def test_titel_status_und_niveau(self):
        a = self.notes["Wissen/A.md"]
        self.assertEqual((a["titel"], a["status"], a["niveau"]), ("Notiz A", "aktiv", "einstieg"))
        self.assertFalse(a["ignoriert"])

    def test_ohne_frontmatter_zaehlt_der_dateiname(self):
        b = self.notes["Wissen/B.md"]
        self.assertEqual(b["titel"], "B")
        self.assertIsNone(b["status"])

    def test_ignorierte_notiz_ist_markiert_archiv_fehlt(self):
        self.assertTrue(self.notes["Wissen/C.md"]["ignoriert"])
        # Archiv kommt nicht in den Index und deshalb auch nicht in die Liste
        self.assertNotIn("Archiv/Alt.md", self.notes)

    def test_links_werden_aufgeloest_code_bleibt_aussen_vor(self):
        self.assertEqual(self.notes["Wissen/B.md"]["links"], ["Wissen/A.md"])
        self.assertEqual(self.notes["Wissen/A.md"]["links"], [])

    def test_ohne_vault_pfad_leere_liste(self):
        self.assertEqual(vault_list.notes(self.root / "gibtsnicht"), [])


if __name__ == "__main__":
    unittest.main()

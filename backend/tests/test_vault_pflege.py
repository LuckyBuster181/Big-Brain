"""
Tests für den Vault-Pflegebericht (tools/vault_pflege.py) an einem Mini-Vault.

Start:
    python -m unittest tests.test_vault_pflege -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import vault_pflege

FILLER = " ".join(f"wort{i}" for i in range(80))


class VaultPflegeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        files = {
            "Gehirn/00 - Übersicht.md": "# Start\n\n[[Wissen/A]] [[Wissen/B]] [[Wissen/Trading/C]] [[Wissen/Leer]]",
            "Wissen/A.md": "---\nstatus: bestätigt\nvertrauen: hoch\nquelle: Nutzer\nerstellt: 2026-09-01\n---\n# A\n\n"
            "[[Gehirn/Trading/C]] [[Gehirn/Trading/C#Abschnitt]] [[Fehlt ganz]] `[[im Code]]` [[Note]] [[B#Gibt es nicht]]\n\n" + FILLER,
            "Wissen/B.md": "---\nstatus: ungeprüft\n---\n# B\n\n## Teil\n\n" + FILLER + "\n\n[[Gehirn/Trading/C]]",
            "Wissen/Trading/C.md": "# C\n\n## Abschnitt\n\nInhalt [[A]]",
            "Wissen/Leer.md": "",
            "Archiv/Alt.md": "# Alt",
        }
        for rel, text in files.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        (self.root / "Wissen/Leerer Ordner").mkdir()
        (self.root / ".obsidian").mkdir()
        self.result = vault_pflege.analyse(self.root, "")

    def test_links_ins_leere_und_verschobener_ordner(self):
        broken = sorted(link.target for _, link in self.result["broken"])
        self.assertEqual(broken, ["Fehlt ganz", "Gehirn/Trading/C", "Gehirn/Trading/C", "Gehirn/Trading/C"])
        (old, new), count = self.result["prefix_moves"].most_common(1)[0]
        self.assertEqual((old, new, count), ("Gehirn/Trading/", "Wissen/Trading/", 3))

    def test_code_und_beispiele_sind_kein_fehler(self):
        targets = {link.target for _, link in self.result["broken"]}
        self.assertNotIn("im Code", targets)
        self.assertEqual([link.target for _, link in self.result["examples"]], ["Note"])

    def test_fehlender_abschnitt(self):
        self.assertEqual([link.anchor for _, link, _ in self.result["missing_anchor"]], ["Gibt es nicht"])

    def test_dubletten_metadaten_leere_ordner(self):
        self.assertEqual(self.result["duplicate_groups"], [["Wissen/A.md", "Wissen/B.md"]])
        missing = {rel: m for rel, m, _ in self.result["metadata_rows"]}
        self.assertNotIn("Wissen/A.md", missing)
        self.assertEqual(missing["Wissen/B.md"], ["vertrauen", "quelle", "Datum"])
        self.assertEqual(self.result["nonstandard_status"]["ungeprüft"], 1)
        self.assertNotIn("aktiv", self.result["nonstandard_status"])  # seit 20.09. Standard
        self.assertEqual(self.result["empty_dirs"], ["Wissen/Leerer Ordner"])

    def test_waisen_und_archiv(self):
        self.assertEqual(self.result["orphans"], ["Gehirn/00 - Übersicht.md"])
        self.assertEqual(self.result["archive_count"], 1)

    def test_bericht_wird_erzeugt(self):
        text = vault_pflege.render(self.result, "2026-09-20")
        self.assertIn("jarvis: ignorieren", text)
        self.assertIn("`Gehirn/Trading/` → `Wissen/Trading/`", text)
        self.assertIn("Links ins Leere", text)


class PlatzhalterTest(unittest.TestCase):
    """Vorlagen-Gruppe: Empfehlung hängt davon ab, ob die Notizen schon ausgenommen sind."""

    def _bericht(self, ignorieren: int) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "Wissen").mkdir()
        (root / "Gehirn").mkdir()
        (root / "Gehirn/00 - Übersicht.md").write_text(
            "# Start\n\n" + " ".join(f"[[Wissen/P{i}]]" for i in range(3)), encoding="utf-8")
        for i in range(3):
            fm = "---\njarvis: ignorieren\n---\n" if i < ignorieren else ""
            (root / f"Wissen/P{i}.md").write_text(fm + f"# P{i}\n\n" + FILLER, encoding="utf-8")
        return vault_pflege.render(vault_pflege.analyse(root, ""), "2026-09-20")

    def test_alle_ausgenommen(self):
        text = self._bericht(3)
        self.assertIn("3 Platzhalter mit fast demselben Text", text)
        self.assertEqual(text.count("– von der Suche ausgenommen"), 3)

    def test_teilweise_ausgenommen(self):
        text = self._bericht(1)
        self.assertIn("3 Notizen bestehen aus fast demselben Text", text)
        self.assertIn("Noch nicht ausgenommen: P1, P2.", text)

    def test_keine_ausgenommen(self):
        text = self._bericht(0)
        self.assertIn("Die Auron-Suche findet sie derzeit noch.", text)


if __name__ == "__main__":
    unittest.main()

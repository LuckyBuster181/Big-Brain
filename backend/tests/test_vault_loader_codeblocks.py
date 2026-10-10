"""
Test für den Chunking-Fix vom 20.09.2026 abends: `#` in Codeblöcken darf nicht
als Überschrift gewertet werden (Befund: 35 betroffene Zeilen, u.a. in den
Notizen "knap" und "defuddle" - Python-Kommentare und Markdown-Beispiele in
```-Blöcken).

Start:
    python -m unittest tests.test_vault_loader_codeblocks -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag.vault_loader import _find_headings, load_note


class CodeblockHeadingTest(unittest.TestCase):
    def test_raute_in_python_codeblock_wird_ignoriert(self):
        text = (
            "# Titel\n\nText.\n\n```python\n# Das ist ein Kommentar\ndef f():\n    return 1\n```\n\n"
            "## Echter Abschnitt\n\nweiterer Text\n"
        )
        heads = [m.group(2) for m in _find_headings(text)]
        self.assertEqual(heads, ["Titel", "Echter Abschnitt"])

    def test_raute_in_tilde_codeblock_wird_ignoriert(self):
        text = "# Titel\n\n~~~\n# keine Überschrift\n~~~\n\n## Abschnitt\n\ntext\n"
        heads = [m.group(2) for m in _find_headings(text)]
        self.assertEqual(heads, ["Titel", "Abschnitt"])

    def test_echte_ueberschriften_bleiben_unveraendert(self):
        text = "# Titel\n\n## A\n\ntext\n\n### B\n\ntext\n"
        heads = [m.group(2) for m in _find_headings(text)]
        self.assertEqual(heads, ["Titel", "A", "B"])

    def test_codeblock_bleibt_im_richtigen_chunk_am_stueck(self):
        text = (
            "# Titel\n\nText.\n\n```python\n# Kommentar, keine Überschrift\n"
            "def f():\n    return 1\n```\n\n## Nächster Abschnitt\n\nweiter\n"
        )
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = root / "Test.md"
            path.write_text(text, encoding="utf-8")
            chunks = load_note(path, root)
        heads = [c.heading_path.split(" > ")[-1] for c in chunks]
        self.assertEqual(heads, ["Titel", "Nächster Abschnitt"])
        titel_chunk = next(c for c in chunks if c.heading_path.split(" > ")[-1] == "Titel")
        self.assertIn("```python", titel_chunk.content)
        self.assertIn("def f():", titel_chunk.content)
        self.assertIn("return 1", titel_chunk.content)

    def test_notiz_ohne_codeblock_unveraendert(self):
        text = "# Titel\n\n## Abschnitt eins\n\ntext eins\n\n## Abschnitt zwei\n\ntext zwei\n"
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = root / "Ohne.md"
            path.write_text(text, encoding="utf-8")
            chunks = load_note(path, root)
        # Die H1 "Titel" hat hier keinen eigenen Text (direkt gefolgt von
        # "## Abschnitt eins") - dieser leere Abschnitt entfällt, nur die
        # beiden Unterabschnitte werden zu Chunks.
        self.assertEqual(len(chunks), 2)
        heads = [c.heading_path.split(" > ")[-1] for c in chunks]
        self.assertEqual(heads, ["Abschnitt eins", "Abschnitt zwei"])


if __name__ == "__main__":
    unittest.main()

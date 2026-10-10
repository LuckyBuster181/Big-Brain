"""
Schnelle Tests ohne Embedding-Modell, ohne Chroma-Datei und ohne Claude-Aufruf
(laufen in wenigen Sekunden, belasten den PC nicht).

Start:
    python -m unittest tests.test_suche -v
"""

from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from rag import retriever
from rag.keywords import keywords, stem_german
from rag.vault_loader import load_note


class StemmerTest(unittest.TestCase):
    def test_snowball_beispiele(self):
        # Beispiele aus der offiziellen Snowball-Beschreibung (snowballstem.org)
        for word, stem in {
            "äckern": "ack",
            "ackers": "ack",
            "armes": "arm",
            "bedürfnissen": "bedurfnis",
            "derbsten": "derb",
            "aufeinanderfolgenden": "aufeinanderfolg",
            "kategorisch": "kategor",
        }.items():
            self.assertEqual(stem_german(word), stem, word)

    def test_beugungsformen_passen_zusammen(self):
        for group in (
            ("prüfe", "prüfen"),
            ("gefahr", "gefahren"),
            ("historische", "historischer"),
            ("handelsstrategie", "handelsstrategien"),
            ("positionsgröße", "positionsgrößen"),
            ("verlust", "verluste"),
        ):
            self.assertEqual(len({stem_german(w) for w in group}), 1, group)


class KeywordsTest(unittest.TestCase):
    def test_fuellwoerter_fallen_weg(self):
        self.assertEqual(
            keywords("Wie prüfe ich eine Handelsstrategie mit alten Kursdaten?"),
            {"pruf", "handelsstrategi", "alt", "kursdat"},
        )

    def test_abkuerzungen_in_grossschrift_zaehlen(self):
        words = keywords("Was kann KI im Trading? So ist es.")
        self.assertIn("ki", words)
        self.assertNotIn("so", words)
        self.assertNotIn("es", words)

    def test_leerer_text(self):
        self.assertEqual(keywords(""), set())
        self.assertEqual(keywords("und oder aber"), set())


class FakeCollection:
    """Minimaler Ersatz für eine Chroma-Collection (nur was der Retriever braucht)."""

    def __init__(self, docs: dict[str, str], vectors: dict[str, list[float]]):
        self.id = uuid.uuid4()
        self.docs = docs
        self.vectors = vectors
        self.get_calls = 0

    def count(self) -> int:
        return len(self.docs)

    def get(self, include=None):
        self.get_calls += 1
        return {"ids": list(self.docs), "documents": list(self.docs.values())}

    def query(self, query_embeddings, n_results, where=None, include=None):
        out = {"ids": [], "documents": [], "metadatas": [], "distances": []}
        for q in query_embeddings:
            scored = []
            for doc_id, vec in self.vectors.items():
                cos = sum(a * b for a, b in zip(q, vec))
                scored.append((1 - cos, doc_id))
            scored.sort()
            scored = scored[:n_results]
            out["ids"].append([d for _, d in scored])
            out["documents"].append([self.docs[d] for _, d in scored])
            out["metadatas"].append(
                [{"file_path": f"{d}.md", "note_title": d, "heading_path": d} for _, d in scored]
            )
            out["distances"].append([dist for dist, _ in scored])
        return out


class FakeEmbedder:
    def __init__(self, vector):
        self.vector = vector

    def embed_query(self, text):
        return self.vector


class RetrieverTest(unittest.TestCase):
    def setUp(self):
        retriever.invalidate_keyword_stats()
        docs = {
            "backtesting": "Backtesting prüft eine Handelsstrategie anhand historischer Kursdaten. Big Brain.",
            "risiko": "Risiko pro Trade begrenzen, Positionsgröße berechnen. Big Brain.",
            "holz": "Holz quillt bei Feuchtigkeit. Big Brain.",
            "uebersicht": "Big Brain Übersicht mit Links. Big Brain.",
        }
        # Alle Chunks semantisch gleich weit weg -> nur der Keyword-Anteil entscheidet
        vectors = {k: [1.0, 0.0] for k in docs}
        self.collection = FakeCollection(docs, vectors)
        self.preset = retriever.get_preset("e5-base")
        patcher = mock.patch.object(retriever, "get_embedder", return_value=FakeEmbedder([1.0, 0.0]))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_stichwort_entscheidet_bei_gleicher_semantik(self):
        hits = retriever.search(
            "Wie prüfe ich eine Handelsstrategie mit alten Kursdaten?",
            top_k=2, collection=self.collection, preset=self.preset,
        )
        self.assertEqual(hits[0].file_path, "backtesting.md")
        self.assertGreater(hits[0].keyword_overlap, hits[1].keyword_overlap)

    def test_seltene_woerter_zaehlen_mehr(self):
        stats = retriever.get_keyword_stats(self.collection)
        query = keywords("Big Brain Backtesting")
        # "backtesting" (selten) passt, "big"/"brain" (überall) auch -> hoher Wert
        with_rare = retriever._keyword_overlap(query, self.collection.docs["backtesting"], stats)
        # nur "big"/"brain" passen (stehen überall) -> deutlich weniger als die 2/3 ohne IDF
        only_common = retriever._keyword_overlap(query, self.collection.docs["holz"], stats)
        without_idf = retriever._keyword_overlap(query, self.collection.docs["holz"])
        self.assertAlmostEqual(with_rare, 1.0)
        self.assertAlmostEqual(without_idf, 2 / 3)
        self.assertLess(only_common, without_idf - 0.1)

    def test_haeufigkeiten_werden_zwischengespeichert(self):
        retriever.get_keyword_stats(self.collection)
        retriever.get_keyword_stats(self.collection)
        self.assertEqual(self.collection.get_calls, 1)
        # neue Chunks -> Anzahl ändert sich -> neu berechnen
        self.collection.docs["neu"] = "Neuer Abschnitt"
        retriever.get_keyword_stats(self.collection)
        self.assertEqual(self.collection.get_calls, 2)
        # nach dem Neu-Einlesen explizit verworfen
        retriever.invalidate_keyword_stats()
        retriever.get_keyword_stats(self.collection)
        self.assertEqual(self.collection.get_calls, 3)

    def test_leere_anfrage(self):
        self.assertEqual(retriever.search_many([("   ", 1.0)], collection=self.collection, preset=self.preset), [])


class VaultLoaderTest(unittest.TestCase):
    def test_chunks_nach_ueberschriften(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            note = root / "Notiz.md"
            note.write_text(
                "---\nstatus: entwurf\n---\n# Titel\n\nEinleitung.\n\n## Abschnitt A\nText A.\n\n### Unterpunkt\nText B.\n",
                encoding="utf-8",
            )
            chunks = load_note(note, root)
        self.assertEqual([c.heading_path for c in chunks], ["Titel", "Titel > Abschnitt A", "Titel > Abschnitt A > Unterpunkt"])
        self.assertEqual(chunks[0].frontmatter.get("status"), "entwurf")
        self.assertTrue(all(c.file_path == "Notiz.md" for c in chunks))

    def test_jarvis_ignorieren_nimmt_notiz_aus_der_suche(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i, value in enumerate(("ignorieren", "false", "Aus")):
                note = root / f"n{i}.md"
                note.write_text(f"---\njarvis: {value}\n---\n# T\n\nText.\n", encoding="utf-8")
                self.assertEqual(load_note(note, root), [], value)
            normal = root / "normal.md"
            normal.write_text("---\njarvis: ja\n---\n# T\n\nText.\n", encoding="utf-8")
            self.assertEqual(len(load_note(normal, root)), 1)


if __name__ == "__main__":
    unittest.main()

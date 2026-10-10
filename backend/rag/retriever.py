"""
Retriever-Modul für Jarvis / Big Brain
-----------------------------------------
Sucht relevante Notiz-Chunks in der Chroma-Vektordatenbank für eine Anfrage.
Kombiniert semantische Suche (Embeddings) mit einem einfachen Keyword-Bonus
("Semantic + Keyword Hybrid", siehe Entwicklungsplan/-log).

Keyword-Anteil (Stand 20.09.2026):
- Stichwörter ohne Füllwörter, auf den Wortstamm gekürzt (rag/keywords.py)
- seltene Wörter zählen mehr als häufige (IDF-Gewichtung): "Backtesting" sagt
  viel über einen Abschnitt, "Big Brain" steht dagegen in fast jeder Notiz.
  Die Häufigkeiten werden einmal aus dem Index berechnet und zwischengespeichert,
  nach jedem Neu-Einlesen automatisch neu.
Gemessen mit tests/eval_search.py (28 Fragen, nur Stichwort-Teil): richtige
Notiz in den Top 3 vorher 16, jetzt 24.

Mehrere Suchanfragen auf einmal (search_many): wird für Folgefragen im Chat
genutzt - z.B. "und welche Risiken gibt es dabei?" allein findet wenig, zusammen
mit der vorherigen Frage aber das Richtige. Die Treffer beider Suchen werden
zusammengeführt, pro Chunk zählt der beste Score.

Der semantische Anteil basiert auf der echten Kosinus-Ähnlichkeit (nicht
relativ zu den anderen Kandidaten). Nur so sind Treffer verschiedener
Suchanfragen vergleichbar: eine vage Folgefrage allein erreicht niedrige Werte
und verdrängt die passenden Treffer der kombinierten Anfrage nicht.

Nutzung:
    python -m rag.retriever "Wie funktioniert Chunking?"
    python -m rag.retriever "Backtesting" --top-k 3 --status bestätigt
    python -m rag.retriever "Risiko pro Trade" --model minilm   # altes Modell zum Vergleich
"""

from __future__ import annotations

import math
import threading
from collections import Counter
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv

from .embedder import ModelPreset, get_embedder, get_preset
from .embeddings import get_client, get_collection
from .keywords import keywords

# Wie stark semantische Ähnlichkeit gegenüber dem Keyword-Treffer gewichtet wird.
SEMANTIC_WEIGHT = 0.7
KEYWORD_WEIGHT = 0.3

# Wie viele semantische Kandidaten vor dem Reranking geholt werden
CANDIDATE_MULTIPLIER = 4


@dataclass
class RetrievedChunk:
    id: str
    content: str
    file_path: str
    note_title: str
    heading_path: str
    score: float
    semantic_similarity: float  # Kosinus-Ähnlichkeit, auf 0..1 gestreckt (fürs Ranking)
    raw_similarity: float  # echte Kosinus-Ähnlichkeit (für "passt das überhaupt?")
    keyword_overlap: float
    metadata: dict[str, Any]


# Seltene Wörter stärker gewichten (IDF). Abschalten nur für Vergleiche.
USE_IDF = True


def _keywords(text: str) -> set[str]:
    return keywords(text)


@dataclass(frozen=True)
class KeywordStats:
    """Wie viele Chunks enthalten welches Stichwort (Dokumenthäufigkeit)."""

    chunk_count: int
    doc_freq: dict[str, int]

    def idf(self, word: str) -> float:
        return math.log(1 + self.chunk_count / (1 + self.doc_freq.get(word, 0)))


_stats_lock = threading.Lock()
_stats_cache: dict[tuple[str, Any], KeywordStats] = {}


def invalidate_keyword_stats() -> None:
    """Nach dem Neu-Einlesen aufrufen, damit die Häufigkeiten neu berechnet werden."""
    with _stats_lock:
        _stats_cache.clear()


def get_keyword_stats(collection, chunk_count: int | None = None) -> KeywordStats:
    """Dokumenthäufigkeiten aller Stichwörter im Index (zwischengespeichert).
    Wird neu berechnet, wenn sich die Anzahl der Chunks geändert hat."""
    count = collection.count() if chunk_count is None else chunk_count
    key = (str(collection.id), _keywords)
    with _stats_lock:
        cached = _stats_cache.get(key)
    if cached is not None and cached.chunk_count == count:
        return cached

    documents = collection.get(include=["documents"]).get("documents") or []
    doc_freq: Counter[str] = Counter()
    for doc in documents:
        doc_freq.update(_keywords(doc or ""))
    stats = KeywordStats(chunk_count=len(documents), doc_freq=dict(doc_freq))
    with _stats_lock:
        _stats_cache[key] = stats
    return stats


def _keyword_overlap(query_words: set[str], content: str, stats: KeywordStats | None = None) -> float:
    """Anteil der Suchwörter, die im Text vorkommen - mit IDF gewichtet, falls
    stats vorhanden (0 = kein Suchwort im Text, 1 = alle)."""
    if not query_words:
        return 0.0
    matched = query_words & _keywords(content)
    if stats is None:
        return len(matched) / len(query_words)
    total = sum(stats.idf(w) for w in query_words)
    return sum(stats.idf(w) for w in matched) / total if total else 0.0


def search_many(
    queries: list[tuple[str, float]],
    top_k: int = 5,
    collection=None,
    where: dict[str, Any] | None = None,
    preset: ModelPreset | None = None,
) -> list[RetrievedChunk]:
    """Semantic + Keyword Hybrid Search über mehrere Anfragen.

    queries: Liste aus (Suchtext, Gewicht). Das Gewicht (0-1) dämpft
    Hilfsanfragen, damit sie die eigentliche Frage nicht verdrängen.
    where: optionaler Chroma-Metadatenfilter, z.B. {"fm_status": "bestätigt"}.
    """
    queries = [(text, weight) for text, weight in queries if text and text.strip()]
    if not queries:
        return []

    preset = preset or get_preset()
    if collection is None:
        collection = get_collection(get_client(), preset)
    chunk_count = collection.count()
    if chunk_count == 0:
        return []
    stats = get_keyword_stats(collection, chunk_count) if USE_IDF else None

    embedder = get_embedder(preset)
    query_embeddings = [embedder.embed_query(text) for text, _ in queries]

    n_candidates = max(top_k * CANDIDATE_MULTIPLIER, top_k)
    raw = collection.query(
        query_embeddings=query_embeddings,
        n_results=n_candidates,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    floor = preset.similarity_floor
    best: dict[str, RetrievedChunk] = {}
    for q_index, (text, weight) in enumerate(queries):
        ids = (raw.get("ids") or [[]])[q_index]
        documents = (raw.get("documents") or [[]])[q_index]
        metadatas = (raw.get("metadatas") or [[]])[q_index]
        distances = (raw.get("distances") or [[]])[q_index]
        if not documents:
            continue

        query_words = _keywords(text)

        for chunk_id, doc, meta, dist in zip(ids, documents, metadatas, distances):
            meta = meta or {}
            raw_similarity = 1 - dist  # Chroma liefert Kosinus-Distanz
            similarity = min(1.0, max(0.0, (raw_similarity - floor) / (1 - floor)))
            keyword_score = _keyword_overlap(query_words, doc, stats)
            combined = (SEMANTIC_WEIGHT * similarity + KEYWORD_WEIGHT * keyword_score) * weight
            existing = best.get(chunk_id)
            if existing is not None and existing.score >= combined:
                continue
            best[chunk_id] = RetrievedChunk(
                id=chunk_id,
                content=doc,
                file_path=meta.get("file_path", "?"),
                note_title=meta.get("note_title", "?"),
                heading_path=meta.get("heading_path", "?"),
                score=combined,
                semantic_similarity=similarity,
                raw_similarity=raw_similarity,
                keyword_overlap=keyword_score,
                metadata=meta,
            )

    results = sorted(best.values(), key=lambda r: r.score, reverse=True)
    return results[:top_k]


def search(
    query: str,
    top_k: int = 5,
    collection=None,
    where: dict[str, Any] | None = None,
    preset: ModelPreset | None = None,
) -> list[RetrievedChunk]:
    """Suche mit einer einzelnen Anfrage."""
    return search_many([(query, 1.0)], top_k=top_k, collection=collection, where=where, preset=preset)


if __name__ == "__main__":
    import argparse
    import sys

    # Windows-Konsolen nutzen standardmäßig eine Legacy-Codepage (z.B. cp1252)
    # statt UTF-8 -> Umlaute/Emojis aus dem Vault (z.B. "🔄" in Überschriften)
    # würden print() sonst mit UnicodeEncodeError abstürzen lassen.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    load_dotenv()
    parser = argparse.ArgumentParser(description="Vault-Suche (Semantic + Keyword Hybrid)")
    parser.add_argument("query", help="Suchanfrage")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--status", default=None, help="Nur Notizen mit diesem Status (fm_status)")
    parser.add_argument("--model", default=None, help="Embedding-Modell (Standard: EMBEDDING_MODEL bzw. e5-base)")
    args = parser.parse_args()

    where = {"fm_status": args.status} if args.status else None
    hits = search(args.query, top_k=args.top_k, where=where, preset=get_preset(args.model))

    if not hits:
        print("Keine Treffer. Ist der Index gebaut? -> python -m rag.embeddings")
    for i, hit in enumerate(hits, 1):
        print(
            f"\n#{i}  score={hit.score:.3f}  (semantic={hit.semantic_similarity:.3f}, "
            f"cos={hit.raw_similarity:.3f}, keyword={hit.keyword_overlap:.3f})"
        )
        print(f"    Quelle: {hit.file_path}  |  {hit.heading_path}")
        preview = hit.content[:220].replace("\n", " ")
        print(f"    {preview}...")

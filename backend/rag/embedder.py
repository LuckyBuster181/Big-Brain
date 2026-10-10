"""
Embedding-Modelle für Jarvis / Big Brain
-----------------------------------------
Wandelt Text in Vektoren um - einmal für die Vault-Chunks beim Indexieren,
einmal für die Frage bei der Suche.

Warum nicht mehr Chromas Standardmodell?
Chromas DefaultEmbeddingFunction ist all-MiniLM-L6-v2, ein rein englisch
trainiertes Modell. Deutsche Fragen fanden damit passende Notizen kaum
(nachgewiesen im Entwicklungslog vom 19.09.2026). Jetzt: multilingual-e5
(Microsoft/intfloat), mehrsprachig trainiert, gut für Deutsch.

Technik ohne neue Pakete:
Das Modell läuft als ONNX-Datei über `onnxruntime`, der Text wird mit
`tokenizers` zerlegt, heruntergeladen wird über `huggingface_hub` - alle drei
sind bereits installiert (Abhängigkeiten von chromadb). Kein torch, kein
sentence-transformers. Der Download passiert einmalig beim ersten Start und
liegt danach im HuggingFace-Cache (%USERPROFILE%\\.cache\\huggingface) -
danach funktioniert alles offline.

Modell wählen (optional, in backend/.env bzw. Jarvis/.env):
    EMBEDDING_MODEL=e5-base        # Standard
    EMBEDDING_MODEL=e5-small       # kleiner/schneller, etwas schwächer
    EMBEDDING_MODEL=e5-base-fp32   # volle Genauigkeit, ~1,1 GB
    EMBEDDING_MODEL=minilm         # altes englisches Modell (nur zum Vergleich)

Jedes Modell hat eine eigene Chroma-Collection. Umschalten zerstört also
keinen Index, das andere Modell baut sich seinen eigenen auf.

CPU-Last begrenzen (Stand 19.09.2026: PC ist beim ersten Indexlauf mit allen
Kernen unter Volllast abgestürzt). Standard sind 2 Rechen-Threads statt aller
Kerne. Anpassen in der .env:
    EMBEDDING_THREADS=2
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class ModelPreset:
    key: str
    description: str
    # HuggingFace-Repo mit ONNX-Export. None = Chromas eingebautes MiniLM.
    repo: str | None
    onnx_file: str | None
    collection: str
    # e5-Modelle erwarten diese Präfixe, sonst sinkt die Suchqualität deutlich.
    query_prefix: str = ""
    doc_prefix: str = ""
    max_tokens: int = 512
    # Unterhalb dieser rohen Kosinus-Ähnlichkeit (bester Treffer) gilt die
    # Suche als unsicher. Werte sind modellabhängig: e5 liefert grundsätzlich
    # hohe Ähnlichkeiten (auch Unpassendes liegt oft bei ~0,75).
    # e5-base gemessen am 20.09.2026 (suchtest.bat, 28 passende + 12 themenfremde
    # Fragen): passende 0,810-0,888, themenfremde 0,735-0,814 -> Schwelle 0,807.
    # Zusätzlich gilt ein Treffer als unsicher, wenn kein einziges Stichwort der
    # Frage darin vorkommt (chat_service.is_low_confidence). Zusammen: 0 passende
    # fälschlich unsicher, 1 themenfremde fälschlich sicher.
    low_similarity: float = 0.3
    # Ähnlichkeit, ab der ein Treffer überhaupt zählt. Wird für das Ranking auf
    # 0..1 gestreckt: (cos - floor) / (1 - floor). Nötig, weil e5 selbst
    # unpassenden Texten ~0,7 gibt - sonst wäre der Keyword-Anteil zu schwach.
    similarity_floor: float = 0.0


PRESETS: dict[str, ModelPreset] = {
    "e5-base": ModelPreset(
        key="e5-base",
        description="multilingual-e5-base, int8-quantisiert (~280 MB)",
        repo="Xenova/multilingual-e5-base",
        onnx_file="onnx/model_quantized.onnx",
        collection="big_brain_vault__e5_base_q8",
        query_prefix="query: ",
        doc_prefix="passage: ",
        low_similarity=0.807,
        similarity_floor=0.70,
    ),
    "e5-base-fp32": ModelPreset(
        key="e5-base-fp32",
        description="multilingual-e5-base, volle Genauigkeit (~1,1 GB)",
        repo="Xenova/multilingual-e5-base",
        onnx_file="onnx/model.onnx",
        collection="big_brain_vault__e5_base",
        query_prefix="query: ",
        doc_prefix="passage: ",
        low_similarity=0.81,
        similarity_floor=0.70,
    ),
    "e5-small": ModelPreset(
        key="e5-small",
        description="multilingual-e5-small, int8-quantisiert (~120 MB)",
        repo="Xenova/multilingual-e5-small",
        onnx_file="onnx/model_quantized.onnx",
        collection="big_brain_vault__e5_small_q8",
        query_prefix="query: ",
        doc_prefix="passage: ",
        low_similarity=0.81,
        similarity_floor=0.70,
    ),
    "minilm": ModelPreset(
        key="minilm",
        description="all-MiniLM-L6-v2 (englisch, altes Standardmodell von Chroma)",
        repo=None,
        onnx_file=None,
        # Name der ursprünglichen Collection - der alte Index bleibt so nutzbar.
        collection="big_brain_vault",
        low_similarity=0.30,
    ),
}

DEFAULT_MODEL_KEY = "e5-base"
DEFAULT_EMBEDDING_THREADS = 2


def embedding_threads() -> int:
    """Anzahl CPU-Threads fürs Embedding (EMBEDDING_THREADS, Standard 2)."""
    try:
        value = int(os.getenv("EMBEDDING_THREADS", DEFAULT_EMBEDDING_THREADS))
    except ValueError:
        value = DEFAULT_EMBEDDING_THREADS
    return max(1, min(value, os.cpu_count() or 1))


def get_preset(key: str | None = None) -> ModelPreset:
    """Liefert das Modell-Preset. Ohne Angabe: EMBEDDING_MODEL aus .env oder Standard."""
    key = (key or os.getenv("EMBEDDING_MODEL") or DEFAULT_MODEL_KEY).strip().lower()
    if key not in PRESETS:
        valid = ", ".join(PRESETS)
        raise ValueError(f"Unbekanntes EMBEDDING_MODEL '{key}'. Erlaubt: {valid}")
    return PRESETS[key]


class Embedder(Protocol):
    preset: ModelPreset

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class OnnxEmbedder:
    """Mean-Pooling über die Token-Vektoren eines ONNX-Transformer-Modells,
    danach L2-normalisiert (so wie sentence-transformers es für e5 macht)."""

    def __init__(self, preset: ModelPreset, batch_size: int = 8) -> None:
        # Imports erst hier: das Laden kostet Zeit und wird nur gebraucht,
        # wenn wirklich eingebettet wird (Health-Check braucht das Modell nicht).
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        assert preset.repo and preset.onnx_file
        self.preset = preset
        self.batch_size = batch_size

        def download(filename: str) -> str:
            # Erst im lokalen Cache suchen: kein Internet nötig, keine
            # HF-Warnung bei jedem Start. Nur beim allerersten Mal herunterladen.
            try:
                return hf_hub_download(preset.repo, filename, local_files_only=True)
            except Exception:  # noqa: BLE001 - nicht im Cache
                return hf_hub_download(preset.repo, filename)

        start = time.time()
        tokenizer_path = download("tokenizer.json")
        model_path = download(preset.onnx_file)

        self.tokenizer = Tokenizer.from_file(tokenizer_path)
        self.tokenizer.enable_truncation(max_length=preset.max_tokens)
        pad_token = next(
            (t for t in ("<pad>", "[PAD]") if self.tokenizer.token_to_id(t) is not None), None
        )
        pad_id = self.tokenizer.token_to_id(pad_token) if pad_token else 0
        self.tokenizer.enable_padding(pad_id=pad_id, pad_token=pad_token or "<pad>")

        options = ort.SessionOptions()
        options.log_severity_level = 3  # nur Fehler, keine Warnungen im Log
        # Ohne Grenze nutzt onnxruntime alle Kerne mit 100 % - das hat den PC
        # zum Absturz gebracht. Wenige Threads = langsamer, aber schonend.
        self.threads = embedding_threads()
        options.intra_op_num_threads = self.threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(
            model_path, sess_options=options, providers=["CPUExecutionProvider"]
        )
        self.input_names = {i.name for i in self.session.get_inputs()}
        output_names = [o.name for o in self.session.get_outputs()]
        self.output_name = "last_hidden_state" if "last_hidden_state" in output_names else output_names[0]
        self.load_seconds = time.time() - start

    def _encode(self, texts: list[str]) -> np.ndarray:
        encodings = self.tokenizer.encode_batch(texts)
        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)

        feeds: dict[str, np.ndarray] = {}
        if "input_ids" in self.input_names:
            feeds["input_ids"] = input_ids
        if "attention_mask" in self.input_names:
            feeds["attention_mask"] = attention_mask
        if "token_type_ids" in self.input_names:
            feeds["token_type_ids"] = np.zeros_like(input_ids)

        hidden = self.session.run([self.output_name], feeds)[0]  # (batch, tokens, dim)
        if hidden.ndim != 3:
            raise RuntimeError(f"Unerwartete Modellausgabe mit Form {hidden.shape}")

        mask = attention_mask[..., None].astype(np.float32)
        summed = (hidden * mask).sum(axis=1)
        counts = np.clip(mask.sum(axis=1), 1e-9, None)
        pooled = summed / counts
        norms = np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)
        return pooled / norms

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # Nach Länge sortieren, damit pro Batch wenig aufgefüllt (gepaddet) wird.
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        result: list[list[float] | None] = [None] * len(texts)
        for start in range(0, len(order), self.batch_size):
            idx = order[start : start + self.batch_size]
            vectors = self._encode([texts[i] for i in idx])
            for row, original_index in enumerate(idx):
                result[original_index] = vectors[row].tolist()
        return [v for v in result if v is not None]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed([self.preset.doc_prefix + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._embed([self.preset.query_prefix + text])[0]


class ChromaDefaultEmbedder:
    """Altes Verhalten: Chromas eingebautes MiniLM (englisch). Nur für Vergleiche."""

    def __init__(self, preset: ModelPreset) -> None:
        from chromadb.utils import embedding_functions

        self.preset = preset
        self._ef = embedding_functions.DefaultEmbeddingFunction()
        self.load_seconds = 0.0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [np.asarray(v, dtype=np.float32).tolist() for v in self._ef(texts)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


_cache: dict[str, Embedder] = {}
_cache_lock = threading.Lock()


def get_embedder(preset: ModelPreset | None = None) -> Embedder:
    """Lädt das Modell beim ersten Aufruf (Download + ONNX-Session), danach aus dem Speicher.
    Thread-sicher: Reindex im Hintergrund und Chat-Anfrage können gleichzeitig kommen."""
    preset = preset or get_preset()
    with _cache_lock:
        embedder = _cache.get(preset.key)
        if embedder is None:
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
            if preset.repo is None:
                embedder = ChromaDefaultEmbedder(preset)
            else:
                print(f"[Embedding] Lade Modell {preset.key} ({preset.description}) ...", flush=True)
                embedder = OnnxEmbedder(preset)
                print(
                    f"[Embedding] Modell bereit nach {embedder.load_seconds:.1f}s "
                    f"({embedder.threads} CPU-Threads)",
                    flush=True,
                )
            _cache[preset.key] = embedder
        return embedder

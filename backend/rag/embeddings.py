"""
Index-Modul für Jarvis / Big Brain
-----------------------------------------
Baut aus den Vault-Chunks (vault_loader) eine persistente Chroma-Vektordatenbank
und hält sie aktuell.

Inkrementell statt komplett neu:
Jeder Chunk trägt den Hash seiner Datei in den Metadaten. Beim Neu-Indexieren
wird pro Notiz verglichen:
    - neu oder geändert  -> alte Chunks der Datei löschen, neu einbetten
    - unverändert         -> übersprungen (kostet nur das Hashen der Datei)
    - im Vault gelöscht   -> Chunks aus dem Index entfernen
Ein Lauf ohne Änderungen dauert dadurch nur Sekundenbruchteile und lädt nicht
einmal das Embedding-Modell.

Die Vektoren berechnet Jarvis selbst (rag/embedder.py) und übergibt sie an
Chroma. Chroma bekommt deshalb bewusst keine eigene embedding_function - so
kann nie versehentlich ein anderes Modell für Suche und Index verwendet werden.

Nutzung:
    python -m rag.embeddings                 # geänderte Notizen neu indexieren
    python -m rag.embeddings --full          # Index komplett neu aufbauen
    python -m rag.embeddings --model e5-small
"""

from __future__ import annotations

import datetime
import os
import time
from pathlib import Path
from typing import Any, Callable

import chromadb
from dotenv import load_dotenv

from .embedder import ModelPreset, get_embedder, get_preset
from .vault_loader import VaultChunk, compute_file_hash, iter_markdown_files, load_note, relative_path

# Standard-Speicherort passend zur Projektstruktur: Jarvis/data/vector_db
DEFAULT_CHROMA_PATH = Path(__file__).resolve().parents[2] / "data" / "vector_db"

# Chroma-Metadaten dürfen nur str/int/float/bool sein - keine Listen/Dates/None
_METADATA_SKIP = {"aliases"}  # aliases landen bereits im Chunk-Text, nicht nötig als Metadatum

UPSERT_BATCH_SIZE = 100

# Kurze Pause nach jeder eingebetteten Notiz, damit die CPU zwischendurch
# durchatmen kann (EMBEDDING_PAUSE_MS in der .env, 0 = aus).
DEFAULT_PAUSE_MS = 100


def _pause_seconds() -> float:
    try:
        return max(0, int(os.getenv("EMBEDDING_PAUSE_MS", DEFAULT_PAUSE_MS))) / 1000
    except ValueError:
        return DEFAULT_PAUSE_MS / 1000

# (erledigte Dateien, zu erledigende Dateien, aktuelle Datei)
ProgressCallback = Callable[[int, int, str], None]


def get_client(persist_path: str | Path | None = None) -> chromadb.ClientAPI:
    path = str(persist_path or os.getenv("CHROMA_PATH") or DEFAULT_CHROMA_PATH)
    Path(path).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=path)


def get_collection(client: chromadb.ClientAPI | None = None, preset: ModelPreset | None = None):
    """Collection des aktiven (oder angegebenen) Embedding-Modells."""
    client = client or get_client()
    preset = preset or get_preset()
    if preset.repo is None:
        # Alte MiniLM-Collection wurde mit Chromas Standard-Funktion angelegt -
        # beim Öffnen dieselbe angeben, sonst meldet Chroma einen Konflikt.
        from chromadb.utils import embedding_functions

        ef = embedding_functions.DefaultEmbeddingFunction()
    else:
        ef = None
    return client.get_or_create_collection(
        name=preset.collection,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine", "embedding_model": preset.key},
    )


def _flatten_value(value: Any) -> str | int | float | bool | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


def _chunk_metadata(chunk: VaultChunk) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "file_path": chunk.file_path,
        "note_title": chunk.note_title,
        "heading_path": chunk.heading_path,
        "chunk_index": chunk.chunk_index,
        "file_hash": chunk.file_hash,
    }
    for key, value in chunk.frontmatter.items():
        if key in _METADATA_SKIP:
            continue
        flat = _flatten_value(value)
        if flat is not None:
            meta[f"fm_{key}"] = flat
    return meta


def indexed_file_hashes(collection) -> dict[str, str]:
    """file_path -> file_hash aller Dateien, die aktuell im Index liegen.
    Chunks ohne Hash (alter Index) ergeben "" und gelten damit als geändert."""
    data = collection.get(include=["metadatas"])
    hashes: dict[str, str] = {}
    for meta in data.get("metadatas") or []:
        if not meta:
            continue
        file_path = meta.get("file_path")
        if file_path:
            hashes[str(file_path)] = str(meta.get("file_hash") or "")
    return hashes


def _write_file_chunks(collection, file_path: str, chunks: list[VaultChunk], embeddings: list[list[float]]) -> None:
    # Erst alle alten Chunks der Datei weg: Chunk-IDs hängen an der
    # Überschriftenstruktur, umbenannte Abschnitte blieben sonst verwaist liegen.
    collection.delete(where={"file_path": file_path})
    for i in range(0, len(chunks), UPSERT_BATCH_SIZE):
        batch = chunks[i : i + UPSERT_BATCH_SIZE]
        collection.upsert(
            ids=[c.id for c in batch],
            documents=[c.content for c in batch],
            metadatas=[_chunk_metadata(c) for c in batch],
            embeddings=embeddings[i : i + UPSERT_BATCH_SIZE],
        )


def build_index(
    vault_path: str | Path,
    full: bool = False,
    persist_path: str | Path | None = None,
    preset: ModelPreset | None = None,
    progress: ProgressCallback | None = None,
    client: chromadb.ClientAPI | None = None,
) -> dict[str, Any]:
    """Bringt den Index auf den Stand des Vaults.

    full=True löscht die Collection vorher komplett (z.B. nach Problemen).
    Gibt eine Statistik zurück (siehe Ende der Funktion)."""
    start = time.time()
    preset = preset or get_preset()
    root = Path(vault_path)
    if not root.is_dir():
        raise FileNotFoundError(f"Vault-Ordner nicht gefunden: {root}")

    client = client or get_client(persist_path)
    if full:
        try:
            client.delete_collection(preset.collection)
        except Exception:
            pass  # gab es noch nicht
    collection = get_collection(client, preset)

    current: dict[str, tuple[Path, str]] = {}
    for path in iter_markdown_files(root):
        current[relative_path(path, root)] = (path, compute_file_hash(path))

    if full:
        indexed = {}
    else:
        try:
            indexed = indexed_file_hashes(collection)
        except Exception as exc:  # noqa: BLE001
            # Index beschädigt (z.B. Absturz mitten im Schreiben) -> sauber neu aufbauen
            print(f"[Index] Vorhandener Index nicht lesbar ({exc}) - baue komplett neu auf.", flush=True)
            full = True
            indexed = {}
            try:
                client.delete_collection(preset.collection)
            except Exception:
                pass
            collection = get_collection(client, preset)
    to_index = [rel for rel, (_, file_hash) in current.items() if indexed.get(rel) != file_hash]
    removed = [rel for rel in indexed if rel not in current]

    for rel in removed:
        collection.delete(where={"file_path": rel})

    embedder = None
    pause = _pause_seconds()
    chunks_written = 0
    files_new = files_changed = files_empty = 0
    for done, rel in enumerate(to_index, 1):
        path, file_hash = current[rel]
        chunks = load_note(path, root, file_hash=file_hash)
        if chunks:
            if embedder is None:
                embedder = get_embedder(preset)
            embeddings = embedder.embed_documents([c.content for c in chunks])
            _write_file_chunks(collection, rel, chunks, embeddings)
            chunks_written += len(chunks)
            if pause:
                time.sleep(pause)
            if rel in indexed:
                files_changed += 1
            else:
                files_new += 1
        elif rel in indexed:
            # Notiz wurde geleert: alte Chunks entfernen
            collection.delete(where={"file_path": rel})
            files_changed += 1
        else:
            # Leere Notiz (nur Frontmatter o.ä.) - hat keine Chunks, also auch
            # keinen gespeicherten Hash. Wird bei jedem Lauf kurz geprüft.
            files_empty += 1
        if progress:
            progress(done, len(to_index), rel)

    return {
        "model": preset.key,
        "full": full,
        "files_total": len(current),
        "files_indexed": files_new + files_changed,
        "files_new": files_new,
        "files_changed": files_changed,
        "files_removed": len(removed),
        "files_unchanged": len(current) - len(to_index),
        "files_empty": files_empty,
        "chunks_written": chunks_written,
        "collection_count": collection.count(),
        "duration_s": round(time.time() - start, 2),
    }


if __name__ == "__main__":
    import argparse
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    load_dotenv()
    parser = argparse.ArgumentParser(description="Vault indexieren (Chroma Vector DB aufbauen/aktualisieren)")
    parser.add_argument("--vault", default=os.getenv("VAULT_PATH"), help="Pfad zum Obsidian-Vault")
    parser.add_argument("--chroma-path", default=None, help="Speicherort der Chroma-DB (Default: Jarvis/data/vector_db)")
    parser.add_argument("--full", action="store_true", help="Index komplett neu aufbauen statt nur Änderungen")
    parser.add_argument("--model", default=None, help="Embedding-Modell (e5-base, e5-small, e5-base-fp32, minilm)")
    args = parser.parse_args()

    if not args.vault:
        raise SystemExit("Kein Vault-Pfad angegeben (--vault oder VAULT_PATH in .env)")

    chosen = get_preset(args.model)
    print(f"Lese Vault ein: {args.vault}")
    print(f"Modell: {chosen.key} ({chosen.description}), Modus: {'komplett' if args.full else 'nur Änderungen'}")

    def show_progress(done: int, total: int, rel: str) -> None:
        print(f"  [{done}/{total}] {rel}")

    stats = build_index(args.vault, full=args.full, persist_path=args.chroma_path, preset=chosen, progress=show_progress)
    print(f"Fertig in {stats['duration_s']}s")
    print(f"  Notizen im Vault:        {stats['files_total']}")
    print(f"  neu indexiert:           {stats['files_new']}")
    print(f"  geändert:                {stats['files_changed']}")
    print(f"  entfernt:                {stats['files_removed']}")
    print(f"  unverändert:             {stats['files_unchanged']}")
    print(f"  leer (ohne Inhalt):      {stats['files_empty']}")
    print(f"  Chunks geschrieben:      {stats['chunks_written']}")
    print(f"  Chunks insgesamt:        {stats['collection_count']}")

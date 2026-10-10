"""
Neu-Indexieren des Vaults im Hintergrund.

Läuft in einem eigenen Thread, damit die API währenddessen erreichbar bleibt
(Chat funktioniert weiter, das Dashboard fragt den Fortschritt ab). Es kann
immer nur ein Lauf gleichzeitig aktiv sein.
"""

from __future__ import annotations

import datetime
import os
import threading
import traceback

from rag.embedder import get_embedder, get_preset
from rag.embeddings import build_index
from rag.retriever import invalidate_keyword_stats

from .schemas import ReindexProgress, ReindexResult, ReindexStatus

_lock = threading.Lock()
_state: dict = {
    "running": False,
    "full": False,
    "started_at": None,
    "finished_at": None,
    "progress": None,
    "last_result": None,
    "error": None,
}


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def status() -> ReindexStatus:
    with _lock:
        snapshot = dict(_state)
    return ReindexStatus(
        running=snapshot["running"],
        full=snapshot["full"],
        started_at=snapshot["started_at"],
        finished_at=snapshot["finished_at"],
        progress=ReindexProgress(**snapshot["progress"]) if snapshot["progress"] else None,
        last_result=ReindexResult(**snapshot["last_result"]) if snapshot["last_result"] else None,
        error=snapshot["error"],
    )


def is_running() -> bool:
    with _lock:
        return bool(_state["running"])


def _on_progress(done: int, total: int, current_file: str) -> None:
    with _lock:
        _state["progress"] = {"done": done, "total": total, "current_file": current_file}


def _run(vault_path: str, full: bool, warmup: bool) -> None:
    try:
        result = build_index(vault_path, full=full, progress=_on_progress)
        print(
            f"[Reindex] fertig in {result['duration_s']}s: {result['files_indexed']} Notizen neu eingelesen, "
            f"{result['files_removed']} entfernt, {result['collection_count']} Chunks im Index",
            flush=True,
        )
        with _lock:
            _state["last_result"] = result
    except Exception as exc:  # noqa: BLE001 - Fehler soll im Dashboard sichtbar werden
        traceback.print_exc()
        with _lock:
            _state["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        # Stichwort-Häufigkeiten der Suche passen evtl. nicht mehr zum Index
        invalidate_keyword_stats()
        with _lock:
            _state["running"] = False
            _state["finished_at"] = _now()

    if warmup:
        # Modell schon jetzt laden, damit die erste Chat-Frage nicht warten muss.
        # Bewusst nach "running = False": das Dashboard soll deswegen keinen
        # laufenden Index anzeigen.
        try:
            get_embedder(get_preset())
        except Exception:  # noqa: BLE001 - Fehler zeigt sich sonst bei der ersten Frage
            traceback.print_exc()


def start(full: bool = False, warmup: bool = False) -> tuple[bool, ReindexStatus]:
    """Startet einen Lauf. Rückgabe: (neu gestartet?, aktueller Status).
    Läuft schon einer, wird kein zweiter gestartet."""
    vault_path = os.getenv("VAULT_PATH")
    if not vault_path:
        raise RuntimeError("VAULT_PATH ist nicht gesetzt (.env prüfen)")

    with _lock:
        if _state["running"]:
            started = False
        else:
            started = True
            _state.update(
                running=True,
                full=full,
                started_at=_now(),
                finished_at=None,
                progress=None,
                error=None,
            )

    if started:
        thread = threading.Thread(
            target=_run, args=(vault_path, full, warmup), name="jarvis-reindex", daemon=True
        )
        thread.start()
    return started, status()

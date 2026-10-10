"""
Wissenslücken-Liste: Fragen, zu denen im Vault nichts Passendes stand.

Zweck: zeigt, welches Wissen im Vault fehlt oder schlecht auffindbar ist. Jede
solche Frage landet als JSON-Zeile in data/wissensluecken.jsonl (nicht im Git).
Abrufbar über GET /api/wissensluecken (neueste zuerst).

Gespeichert wird bewusst der Fragetext - genau darum geht es bei dieser Liste.
Die Datei bleibt lokal auf dem PC. Abschalten in der .env:
    WISSENSLUECKEN_LOG=false
"""

from __future__ import annotations

import datetime
import json
import os
import threading
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "wissensluecken.jsonl"

REASON_NO_HITS = "keine Treffer"
REASON_WEAK_HITS = "Treffer passen schlecht"

_lock = threading.Lock()


def _path() -> Path:
    return Path(os.getenv("WISSENSLUECKEN_PATH") or DEFAULT_PATH)


def enabled() -> bool:
    return os.getenv("WISSENSLUECKEN_LOG", "true").strip().lower() not in ("0", "false", "no", "nein", "off")


def record(question: str, reason: str, best_similarity: float | None = None, mode: str = "klassisch") -> None:
    """Hält eine unbeantwortbare Frage fest. Fehler hier dürfen den Chat nie stören."""
    if not enabled():
        return
    try:
        entry = {
            "zeit": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "frage": question.strip()[:2000],
            "grund": reason,
            "bester_cos": round(best_similarity, 3) if best_similarity is not None else None,
            "modus": mode,
        }
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock, path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        print(f"[Wissenslücken] Speichern fehlgeschlagen: {exc}", flush=True)


def recent(limit: int = 50) -> list[dict]:
    """Die letzten Einträge, neueste zuerst. Kaputte Zeilen werden übersprungen."""
    path = _path()
    if not path.exists():
        return []
    entries = []
    with _lock:
        lines = path.read_text(encoding="utf-8").splitlines()
    for line in reversed(lines):
        if len(entries) >= limit:
            break
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries

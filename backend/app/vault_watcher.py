"""
Automatisches Neu-Einlesen, wenn sich Notizen im Vault ändern.

Bisher wurde der Index nur beim Start des Backends und per Knopf aktualisiert.
Lief Jarvis länger, waren neue Notizen bis dahin nicht durchsuchbar.

So funktioniert es:
- Alle WATCH_INTERVAL_S Sekunden (Standard 30) wird verglichen, ob sich
  Änderungszeit oder Größe einer Notiz geändert hat. Gelesen wird dabei kein
  Dateiinhalt - das kostet praktisch keine Rechenzeit.
- Nach einer Änderung wird gewartet, bis WATCH_QUIET_S Sekunden (Standard 60)
  lang nichts mehr geändert wurde. Obsidian speichert beim Tippen alle paar
  Sekunden - ohne diese Ruhezeit würde ständig neu eingelesen.
- Dann startet ein normaler Lauf "nur Änderungen" (reindex_service), also
  genau das, was auch der Knopf "Vault einlesen" macht.

Abschalten in der .env:
    AUTO_REINDEX_WATCH=false
"""

from __future__ import annotations

import os
import threading
import time
import traceback
from pathlib import Path
from typing import Callable

from rag.vault_loader import iter_markdown_files, relative_path

from . import reindex_service

DEFAULT_INTERVAL_S = 30
DEFAULT_QUIET_S = 60

Snapshot = dict[str, tuple[int, int]]


def _env_float(name: str, default: float) -> float:
    try:
        return max(1.0, float(os.getenv(name, default)))
    except ValueError:
        return float(default)


def watch_enabled() -> bool:
    return os.getenv("AUTO_REINDEX_WATCH", "true").strip().lower() not in ("0", "false", "no", "nein", "off")


def snapshot(vault_path: str | Path) -> Snapshot:
    """Pfad -> (Änderungszeit in ns, Größe) aller Notizen, die auch indexiert werden."""
    root = Path(vault_path)
    result: Snapshot = {}
    for path in iter_markdown_files(root):
        try:
            stat = path.stat()
        except OSError:
            continue  # gerade gelöscht/umbenannt - nächste Runde
        result[relative_path(path, root)] = (stat.st_mtime_ns, stat.st_size)
    return result


class VaultWatcher:
    def __init__(
        self,
        vault_path: str | Path,
        interval_s: float = DEFAULT_INTERVAL_S,
        quiet_s: float = DEFAULT_QUIET_S,
        start_reindex: Callable[..., tuple[bool, object]] | None = None,
        is_running: Callable[[], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.vault_path = Path(vault_path)
        self.interval_s = interval_s
        self.quiet_s = quiet_s
        self._start_reindex = start_reindex or reindex_service.start
        self._is_running = is_running or reindex_service.is_running
        self._clock = clock
        self._indexed: Snapshot | None = None  # Stand beim letzten Einlesen
        self._last_seen: Snapshot | None = None  # Stand bei der letzten Prüfung
        self._changed_at: float | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def check_once(self) -> bool:
        """Eine Prüfung. Gibt True zurück, wenn ein Einlesen gestartet wurde."""
        current = snapshot(self.vault_path)
        now = self._clock()

        if self._indexed is None:
            # Erster Aufruf: Stand merken. Das Einlesen beim Start übernimmt main.py.
            self._indexed = self._last_seen = current
            return False

        if current != self._last_seen:
            # Es wird gerade geändert -> Ruhezeit neu beginnen
            self._last_seen = current
            self._changed_at = now
            return False

        if current == self._indexed:
            self._changed_at = None  # Änderung wurde rückgängig gemacht
            return False

        if self._changed_at is not None and now - self._changed_at < self.quiet_s:
            return False
        if self._is_running():
            return False  # läuft schon (z.B. Knopf gedrückt) - nächste Runde erneut prüfen

        started, _ = self._start_reindex(full=False)
        if started:
            changed = sum(1 for k in set(current) | set(self._indexed) if current.get(k) != self._indexed.get(k))
            print(f"[Watcher] {changed} Notiz(en) geändert - lese Vault neu ein ...", flush=True)
            self._indexed = current
            self._changed_at = None
        return started

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.check_once()
            except Exception:  # noqa: BLE001 - der Watcher darf das Backend nie stoppen
                traceback.print_exc()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.check_once()  # Ausgangsstand merken
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="jarvis-vault-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)


def from_env() -> VaultWatcher | None:
    """Watcher nach .env-Einstellungen, oder None wenn abgeschaltet/kein Vault gesetzt."""
    vault_path = os.getenv("VAULT_PATH")
    if not watch_enabled() or not vault_path:
        return None
    return VaultWatcher(
        vault_path,
        interval_s=_env_float("WATCH_INTERVAL_S", DEFAULT_INTERVAL_S),
        quiet_s=_env_float("WATCH_QUIET_S", DEFAULT_QUIET_S),
    )

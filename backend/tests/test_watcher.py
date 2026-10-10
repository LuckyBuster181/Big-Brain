"""
Tests für die Vault-Überwachung (app/vault_watcher.py) - ohne Modell, ohne Chroma,
mit simulierter Uhr statt echter Wartezeiten.

Start:
    python -m unittest tests.test_watcher -v
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.vault_watcher import VaultWatcher, snapshot


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class WatcherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "a.md").write_text("# A\n\nText", encoding="utf-8")
        (self.root / ".obsidian").mkdir()
        (self.root / ".obsidian" / "workspace.md").write_text("x", encoding="utf-8")
        self.clock = FakeClock()
        self.started: list[bool] = []
        self.running = False
        self.watcher = VaultWatcher(
            self.root,
            interval_s=30,
            quiet_s=60,
            start_reindex=self._start,
            is_running=lambda: self.running,
            clock=self.clock,
        )

    def _start(self, full: bool = False):
        self.started.append(full)
        return True, None

    def _touch(self, name: str, text: str) -> None:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        # Änderungszeit sicher verschieben: Windows speichert sie nur grob (ms-Takt),
        # schnell hintereinander geschriebene Dateien hätten sonst dieselbe Zeit.
        # Jede Änderung bekommt deshalb eine eigene, streng steigende Zeit.
        stat = path.stat()
        self._mtime_ns = max(getattr(self, "_mtime_ns", 0), stat.st_mtime_ns) + 2_000_000_000
        os.utime(path, ns=(stat.st_atime_ns, self._mtime_ns))

    def tick(self, seconds: float = 30) -> bool:
        self.clock.now += seconds
        return self.watcher.check_once()

    def test_ohne_aenderung_passiert_nichts(self):
        self.watcher.check_once()
        for _ in range(5):
            self.assertFalse(self.tick())
        self.assertEqual(self.started, [])

    def test_einlesen_erst_nach_ruhezeit(self):
        self.watcher.check_once()
        self._touch("a.md", "# A\n\nNeuer Text")
        self.assertFalse(self.tick())  # Änderung erkannt, Ruhezeit beginnt
        self.assertFalse(self.tick())  # erst 30 s Ruhe
        self.assertTrue(self.tick())  # 60 s Ruhe -> einlesen (nur Änderungen)
        self.assertEqual(self.started, [False])
        self.assertFalse(self.tick())  # danach wieder Ruhe
        self.assertEqual(len(self.started), 1)

    def test_weiteres_tippen_verschiebt_das_einlesen(self):
        self.watcher.check_once()
        for i in range(4):
            self._touch("a.md", f"# A\n\nVersion {i}")
            self.assertFalse(self.tick())
        self.assertFalse(self.tick())
        self.assertTrue(self.tick())
        self.assertEqual(len(self.started), 1)

    def test_neue_und_geloeschte_notiz(self):
        self.watcher.check_once()
        self._touch("neu.md", "# Neu")
        self.tick()
        self.tick()
        self.assertTrue(self.tick())
        (self.root / "neu.md").unlink()
        self.tick()
        self.tick()
        self.assertTrue(self.tick())
        self.assertEqual(len(self.started), 2)

    def test_uebersprungene_ordner_loesen_nichts_aus(self):
        self.watcher.check_once()
        self._touch(".obsidian/workspace.md", "geändert")
        for _ in range(4):
            self.assertFalse(self.tick())
        self.assertNotIn(".obsidian/workspace.md", snapshot(self.root))

    def test_wartet_wenn_schon_ein_lauf_aktiv_ist(self):
        self.watcher.check_once()
        self._touch("a.md", "# A\n\nNeu")
        self.tick()
        self.tick()
        self.running = True
        self.assertFalse(self.tick())
        self.running = False
        self.assertTrue(self.tick())

    def test_rueckgaengig_gemachte_aenderung(self):
        self.watcher.check_once()
        original = (self.root / "a.md").stat()
        self._touch("a.md", "# A\n\nKurz anders")
        self.tick()
        (self.root / "a.md").write_text("# A\n\nText", encoding="utf-8")
        os.utime(self.root / "a.md", ns=(original.st_atime_ns, original.st_mtime_ns))
        for _ in range(4):
            self.assertFalse(self.tick())
        self.assertEqual(self.started, [])


if __name__ == "__main__":
    unittest.main()

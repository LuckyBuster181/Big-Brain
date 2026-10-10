"""Tests für die Systemwerte (app/system_info.py) - ohne Zusatzpakete."""

from __future__ import annotations

import unittest

from app import system_info


class SystemInfoTest(unittest.TestCase):
    def test_snapshot_hat_alle_felder(self):
        snap = system_info.snapshot()
        for key in ("cpu_prozent", "speicher", "festplatte", "laufzeit_s"):
            self.assertIn(key, snap)
        self.assertGreaterEqual(snap["laufzeit_s"], 0)

    def test_cpu_erster_aufruf_none_dann_zahl(self):
        system_info._last.clear()
        self.assertIsNone(system_info.cpu_percent())
        zweiter = system_info.cpu_percent()
        if zweiter is not None:  # auf Systemen ohne /proc oder Windows-API: None ist erlaubt
            self.assertGreaterEqual(zweiter, 0)
            self.assertLessEqual(zweiter, 100)

    def test_speicher_und_festplatte_plausibel(self):
        mem = system_info.memory()
        if mem:
            self.assertGreater(mem["gesamt_gb"], 0)
            self.assertLessEqual(mem["benutzt_gb"], mem["gesamt_gb"] + 1)
        disk = system_info.disk("/")
        if disk:
            self.assertGreater(disk["gesamt_gb"], 0)
            self.assertLessEqual(disk["prozent"], 100)


if __name__ == "__main__":
    unittest.main()

"""
Tests für die Gesten-Steuerung in Auron (15.10.2026) - ohne Netz, ohne Browser.

Die eigentliche Gesten-Logik läuft im Browser (werkstatt/gesten/gesten.js) und wird im Cloud-Prüfstand
mit einer künstlichen Hand und mit echtem MediaPipe geprüft. Hier nur, was ohne Browser geht:
- GESTEN_HOLEN.bat ist reines ASCII mit Windows-Zeilenenden und lädt genau die Dateien mit genau den
  Prüfsummen, die auch der Prüfstand nutzt (sonst testet die Cloud etwas anderes, als Sir bekommt).
- Version in gesten.js = Version in der .bat; die Dateien sind von git ausgeschlossen (Modell nicht ins Repo).
- auron.html bindet gesten.js ein.

Start:
    python -m unittest tests.test_gesten -v
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from cloud_pruefstand import lauf

REPO = Path(__file__).resolve().parents[2]
BAT = REPO / "werkstatt" / "GESTEN_HOLEN.bat"
JS = REPO / "werkstatt" / "gesten" / "gesten.js"


class GestenDateien(unittest.TestCase):
    def test_bat_ascii_und_crlf(self):
        roh = BAT.read_bytes()
        roh.decode("ascii")   # wirft bei Umlauten
        self.assertNotIn(b"\n", roh.replace(b"\r\n", b""), "nur Windows-Zeilenenden")

    def test_bat_und_pruefstand_gleich(self):
        text = BAT.read_text(encoding="ascii")
        quelle = re.search(r'set "QUELLE=([^"]+)"', text).group(1)
        modell = re.search(r'set "MODELL=([^"]+)"', text).group(1)
        aufrufe = re.findall(r'call :HOLEN "([^"]+)" "%ZIEL%\\([^"]+)" ([0-9a-f]{64})', text)
        bat = {ziel.replace("\\", "/"): (adresse.replace("%QUELLE%", quelle).replace("%MODELL%", modell), summe)
               for adresse, ziel, summe in aufrufe}
        pruefstand = {name: (adresse, summe) for name, adresse, summe in lauf.MEDIAPIPE_DATEIEN}
        self.assertEqual(bat, pruefstand)
        self.assertIn("vision_wasm_internal.wasm", " ".join(bat))
        self.assertIn("hand_landmarker.task", " ".join(bat))

    def test_version_ueberall_gleich(self):
        self.assertIn(f"tasks-vision@{lauf.MEDIAPIPE_VERSION}", BAT.read_text(encoding="ascii"))
        self.assertIn(f'const VERSION = "{lauf.MEDIAPIPE_VERSION}"', JS.read_text(encoding="utf-8"))

    def test_dateien_nicht_im_repo(self):
        self.assertIn("/werkstatt/lib/mediapipe/", (REPO / ".gitignore").read_text(encoding="utf-8").splitlines())

    def test_auron_bindet_gesten_ein(self):
        html = (REPO / "dashboard" / "auron.html").read_text(encoding="utf-8")
        self.assertIn('<script src="/werkstatt/gesten/gesten.js"></script>', html)
        self.assertIn('id="gestenKnopf"', html)
        self.assertIn('id="gestenAnzeige"', html)


if __name__ == "__main__":
    unittest.main()

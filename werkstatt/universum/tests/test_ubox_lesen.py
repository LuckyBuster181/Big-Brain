"""Tests fuer ubox_lesen.py. Start im Ordner universum:
python -m unittest discover -s tests -p "test_*.py"
"""
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ubox_lesen as u  # noqa: E402


def _sim():
    return {
        "Header": {"BuildRevision": "49958"},
        "Name": "Probe",
        "Settings": {"CameraTargetId": 4, "CameraTargetDistance": 1e9, "CameraFOV": 45,
                     "View": {"BodyScaleMultiplier": 4}},
        "Groups": [{"$type": "Galaxy", "Id": 2, "Name": "Milky Way", "Radius": 5e20,
                    "BlackHoleId": 19, "NumberOfArms": 4, "Type": 11, "Color": "1;1;1;1"}],
        "Entities": [
            {"Name": "CameraDummy", "Id": 1, "Position": "0;0;0"},
            {"Name": "Sun", "Id": 4, "Category": "star", "Position": "1;2;3", "Velocity": "0;0;0",
             "Radius": 695500000, "Mass": 2e30, "Color": "RGBA(1.000, 0.950, 0.873, 1.000)", "Group": 0},
            {"Name": "Sagittarius A*", "Id": 19, "Category": "blackhole", "Position": "1E+21;0;-3E+21",
             "Radius": 1e10, "Mass": 8e36, "Color": "RGBA(0,0,0,1)", "Group": 2},
            {"Name": "UI_STRING:abc", "Id": 24, "Category": "", "Group": 2,
             "Position": "1.5E+21;0;-3E+21", "Color": "RGBA(0.569, 0.682, 1.000, 0.500)",
             "Components": [{"$type": "ParticleComponent", "Size": 1.1e20},
                            {"$type": "GalaxyMemberComponent", "Radius": 1.1e20,
                             "AverageStarTemperature": 7103.5, "Brightness": 0.08}]},
            {"Name": "UI_STRING:def", "Id": 25, "Category": "", "Position": "kaputt", "Radius": 5},
        ],
    }


class UboxLesenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ubox = os.path.join(self.tmp.name, "Mein Test.ubox")
        with zipfile.ZipFile(self.ubox, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps({"Entries": [
                {"BaseType": "Simulation", "Path": "simulation-Probe.json"}]}))
            z.writestr("simulation-Probe.json", json.dumps(_sim()))
            z.writestr("simulation-Probe-info.json", "{}")
            z.writestr("simulation-Probe-ui-state.json", json.dumps({"Selector": {"0": 19}}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_hilfsfunktionen(self):
        self.assertEqual(u.vektor("1;-2.5;3E+2"), [1.0, -2.5, 300.0])
        self.assertEqual(u.vektor("kaputt"), [0.0, 0.0, 0.0])
        self.assertEqual(u.farbe("RGBA(0.333, 0.396, 0.514, 1.000)"), [0.333, 0.396, 0.514, 1.0])
        self.assertEqual(u.farbe("1;1;1;1"), [1.0, 1.0, 1.0, 1.0])
        self.assertEqual(u.farbe(None), [1.0, 1.0, 1.0, 1.0])

    def test_umwandeln(self):
        ziel, s = u.datei_umwandeln(self.ubox, os.path.join(self.tmp.name, "szenen"))
        self.assertTrue(ziel.endswith("Mein_Test.json"))
        self.assertEqual(s["format"], u.FORMAT)
        namen = [k["name"] for k in s["koerper"]]
        self.assertEqual(namen, ["Sun", "Sagittarius A*", "Objekt 25"])  # ohne Kamera und Teilchen
        sonne = s["koerper"][0]
        self.assertEqual(sonne["pos"], [1.0, 2.0, 3.0])
        self.assertEqual(sonne["art"], "star")
        self.assertEqual(s["koerper_skala"], 4.0)
        self.assertEqual(s["kamera"]["ziel"], 19)  # Auswahl im Spiel hat Vorrang
        self.assertEqual(s["achsen"], "unity")
        g = s["galaxien"][0]
        self.assertEqual(g["mitte"], [1e21, 0.0, -3e21])  # Mitte = Schwarzes Loch
        t = s["teilchen"][0]
        self.assertEqual(t["pos"], [5e20, 0.0, 0.0])  # relativ zur Mitte
        self.assertEqual(t["temp"], [7103])
        self.assertAlmostEqual(t["groesse"], 1.1e20)

    def test_ordner_und_liste(self):
        ziel = os.path.join(self.tmp.name, "szenen")
        rc = u.main(["x", self.tmp.name, ziel])
        self.assertEqual(rc, 0)
        with open(os.path.join(ziel, "liste.json"), encoding="utf-8") as f:
            liste = json.load(f)
        self.assertEqual(liste[0]["datei"], "Mein_Test.json")
        self.assertEqual(liste[0]["galaxien"], 1)

    def test_kaputte_datei(self):
        schlecht = os.path.join(self.tmp.name, "kaputt.ubox")
        with open(schlecht, "wb") as f:
            f.write(b"kein zip")
        rc = u.main(["x", self.tmp.name, os.path.join(self.tmp.name, "szenen")])
        self.assertEqual(rc, 1)  # Fehler gemeldet, gute Datei trotzdem umgewandelt
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "szenen", "Mein_Test.json")))


if __name__ == "__main__":
    unittest.main()

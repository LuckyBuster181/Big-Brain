"""
P20 (16.10.2026): Jarvis-Reste zu Auron. Prüft Umgebungsvariablen (AURON_ vor JARVIS_), die zentrale
Namensliste, den Übergang "Gemerkt von Jarvis" -> "Gemerkt von Auron", "auron: ignorieren", die
Weiterleitung der alten Startdatei und das Werkzeug für die Vault-Namen (tools/namen_auron.py).
Nur Temp-Ordner, kein Netz, kein echter Vault.

Start:
    python -m unittest tests.test_p20_auron -v
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import alltag, geraete, handy_zugang, namen, schluessel, tagesfrage, vorschlaege
from rag import vault_loader

WURZEL = Path(__file__).resolve().parents[2]


class Umgebung(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for k in [k for k in os.environ if k.startswith(("AURON_", "JARVIS_"))]:
            os.environ.pop(k)

    def tearDown(self):
        self.env.stop()

    def test_auron_vor_jarvis(self):
        os.environ["JARVIS_HANDY_TOKEN"] = "alt-12345678"
        self.assertEqual(namen.env("HANDY_TOKEN"), "alt-12345678")
        self.assertEqual(handy_zugang.token(), "alt-12345678")
        os.environ["AURON_HANDY_TOKEN"] = "neu-12345678"
        self.assertEqual(handy_zugang.token(), "neu-12345678")
        os.environ["AURON_HANDY_TOKEN"] = ""            # leer zählt als nicht gesetzt
        self.assertEqual(handy_zugang.token(), "alt-12345678")
        self.assertEqual(namen.env("GIBT_ES_NICHT", "x"), "x")

    def test_gruppe_zugangscodes_und_vnc(self):
        os.environ.update({"JARVIS_ZUGANG_LAPTOP": "laptop-alt-123", "AURON_ZUGANG_LAPTOP": "laptop-neu-123",
                           "JARVIS_ZUGANG_TABLET": "tablet-alt-123", "JARVIS_VNC_HAUPTPC": "geheim12345",
                           "AURON_ZUGANG_KURZ": "abc"})
        self.assertEqual(geraete.zugangscodes(), {"laptop": "laptop-neu-123", "tablet": "tablet-alt-123"})
        self.assertEqual(geraete.vnc_passwort("hauptpc"), "geheim12")
        os.environ["AURON_VNC_HAUPTPC"] = "neues-pw"
        self.assertEqual(geraete.vnc_passwort("hauptpc"), "neues-pw")

    def test_env_pfad(self):
        os.environ["JARVIS_ENV_PATH"] = "/tmp/alt.env"
        self.assertEqual(schluessel.env_pfad(), Path("/tmp/alt.env"))
        os.environ["AURON_ENV_PATH"] = "/tmp/neu.env"
        self.assertEqual(schluessel.env_pfad(), Path("/tmp/neu.env"))


class Namensliste(unittest.TestCase):
    def test_liste_und_anrede(self):
        self.assertEqual(namen.NAMEN, ("auron", "jarvis"))
        self.assertTrue(namen.ist_name("Jarvis,") and namen.ist_name("AURON"))
        self.assertEqual(namen.ohne_anrede("Jarvis, wie spät ist es"), "wie spät ist es")
        self.assertEqual(namen.ohne_anrede("Auron wie spät ist es"), "wie spät ist es")

    def test_jarvis_gleich_auron(self):
        for satz in ("{n}, merk dir: Test", "{n}, welcher Tag ist heute", "{n}, stopp", "{n}, was steht heute nacht an"):
            a, j = alltag.absicht(satz.format(n="Auron")), alltag.absicht(satz.format(n="Jarvis"))
            self.assertEqual((a or {}).get("art"), (j or {}).get("art"), satz)
            self.assertIsNotNone(a, satz)

    def test_modul_auron_im_hud(self):
        html = (WURZEL / "dashboard/index.html").read_text(encoding="utf-8")
        self.assertIn('if (m === "auron") m = "jarvis";', html)


class Gemerkt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        (self.vault / "Wissen/00 - Eingang").mkdir(parents=True)
        self.env = mock.patch.dict(os.environ, {"VAULT_PATH": str(self.vault),
                                                "VORSCHLAEGE_PATH": str(Path(self.tmp.name) / "v.json")})
        self.env.start()
        self.alt = self.vault / vorschlaege.ALTES_ZIEL
        self.neu = self.vault / vorschlaege.STANDARD_ZIEL

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_uebergang_kopiert_alt_bleibt_hinweis_einmal(self):
        self.alt.write_text("---\ntyp: notiz\n---\n\n# Gemerkt\n\n- Eintrag 1\n", encoding="utf-8")
        self.assertEqual(vorschlaege.gemerkt_uebergang(), "kopiert+hinweis")
        self.assertIn("- Eintrag 1", self.neu.read_text(encoding="utf-8"))
        alt_text = self.alt.read_text(encoding="utf-8")
        self.assertTrue(alt_text.startswith("---\ntyp: notiz\n---\n"))   # Kopfzeile bleibt oben
        self.assertIn("[[Gemerkt von Auron]]", alt_text)
        self.assertIn("- Eintrag 1", alt_text)                           # nichts gelöscht
        self.assertIsNone(vorschlaege.gemerkt_uebergang())               # zweites Mal: nichts mehr
        self.assertEqual(self.alt.read_text(encoding="utf-8").count("Hinweis (P20)"), 1)

    def test_neuer_vorschlag_geht_in_die_neue_datei(self):
        self.alt.write_text("# Gemerkt\n\n- alt\n", encoding="utf-8")
        v = vorschlaege.anlegen("Neuer Gedanke")
        self.assertEqual(v["ziel"], vorschlaege.STANDARD_ZIEL)
        self.assertEqual(v["art"], "anhaengen")                          # neue Datei hat den alten Inhalt
        vorschlaege.uebernehmen(v["id"])
        text = self.neu.read_text(encoding="utf-8")
        self.assertIn("- alt", text)
        self.assertIn("Neuer Gedanke", text)
        self.assertNotIn("Neuer Gedanke", self.alt.read_text(encoding="utf-8"))

    def test_alter_offener_vorschlag_landet_auch_neu(self):
        self.alt.write_text("# Gemerkt\n", encoding="utf-8")
        v = vorschlaege.anlegen("Alt angelegt", ziel=vorschlaege.ALTES_ZIEL)
        self.assertEqual(v["ziel"], vorschlaege.STANDARD_ZIEL)

    def test_ohne_alte_datei_einfach_neu(self):
        v = vorschlaege.anlegen("Erster Eintrag")
        self.assertEqual(v["art"], "neu")
        self.assertFalse(self.alt.exists())


class VaultNamen(unittest.TestCase):
    def test_auron_fassung_wenn_vorhanden(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = Path(tmp)
            (v / "01 - Persönliches").mkdir()
            rel = tagesfrage.VAULT_NOTIZ
            self.assertEqual(namen.vault_datei(v, rel), rel)                  # nichts da: alter Name
            (v / rel).write_text("alt", encoding="utf-8")
            self.assertEqual(namen.vault_datei(v, rel), rel)
            neu = namen.auron_fassung(rel)
            self.assertEqual(neu, "01 - Persönliches/06 - Auron fragt.md")
            (v / neu).write_text("neu", encoding="utf-8")
            self.assertEqual(namen.vault_datei(v, rel), neu)
            with mock.patch.object(tagesfrage, "_vault", return_value=v):
                self.assertEqual(tagesfrage.notiz_rel(), neu)

    def test_auron_ignorieren(self):
        self.assertTrue(vault_loader.is_ignored({"auron": "ignorieren"}))
        self.assertTrue(vault_loader.is_ignored({"jarvis": "ignorieren"}))
        self.assertFalse(vault_loader.is_ignored({"auron": "ja"}))
        self.assertFalse(vault_loader.is_ignored(None))


class Startdatei(unittest.TestCase):
    def test_alte_datei_leitet_weiter(self):
        alt = (WURZEL / "1 Starten/JARVIS STARTEN.bat").read_bytes()
        neu = (WURZEL / "1 Starten/AURON STARTEN.bat").read_bytes()
        for inhalt in (alt, neu):
            self.assertNotIn(b"\r", inhalt)        # LF-Zeilenenden
            inhalt.decode("ascii")                 # nur ASCII
        self.assertIn(b'call "%~dp0AURON STARTEN.bat" %*', alt)
        self.assertLess(alt.count(b"\n"), 10)       # nur Weiterleitung
        self.assertIn(b"jarvis_mini.sh neustart", neu)
        self.assertIn(b"title Auron starten", neu)

    def test_hilfetexte_nennen_die_neue_datei(self):
        for name in ("dashboard/auron.html", "1 Starten/auron_app.ps1", "1 Starten/gpu_miete.ps1"):
            text = (WURZEL / name).read_text(encoding="utf-8")
            self.assertNotIn("JARVIS STARTEN", text, name)

    def test_neue_bat_dateien_ascii_crlf(self):
        inhalt = (WURZEL / "1 Starten/NAMEN AUF AURON UMSTELLEN.bat").read_bytes()
        inhalt.decode("ascii")
        self.assertEqual(inhalt.count(b"\n"), inhalt.count(b"\r\n"))
        self.assertIn(b"choice /c JN", inhalt)


# ------------------------------------------------------------------ Teil C: tools/namen_auron.py

import sys  # noqa: E402

sys.path.insert(0, str(WURZEL / "backend"))
from tools import namen_auron  # noqa: E402


def baum(wurzel: Path) -> dict[str, bytes]:
    return {p.relative_to(wurzel).as_posix(): p.read_bytes() for p in sorted(wurzel.rglob("*")) if p.is_file()}


class VaultUmstellen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.arbeit = Path(self.tmp.name) / "arbeit"
        dateien = {
            "Wissen/Jarvis Projekt Anweisung.md": "# Anweisung\n\nJarvis ist der alte Name.\n",
            "Jarvis/Notiz.md": "# Notiz im Ordner\n",
            "01 - Persönliches/06 - Jarvis fragt.md": "# Fragen\n",
            "Bilder/bild-jarvis.png": "PNG",
            "Wissen/Übersicht.md": (
                "Siehe [[Jarvis Projekt Anweisung]], [[Jarvis Projekt Anweisung|die Anweisung]], "
                "[[Wissen/Jarvis Projekt Anweisung#Teil 2]], ![[bild-jarvis.png]], [[Jarvis/Notiz]], "
                "[Notiz](Jarvis/Notiz.md), [Anw](Wissen/Jarvis%20Projekt%20Anweisung.md), "
                "[Web](https://example.org/Jarvis), [[06 - Jarvis fragt]].\n\nJarvis bleibt im Text.\n"),
            "Konflikt/Jarvis Log.md": "alt",
            "Konflikt/Auron Log.md": "schon da",
            ".obsidian/jarvis.json": "{}",
        }
        for rel, inhalt in dateien.items():
            (self.vault / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.vault / rel).write_text(inhalt, encoding="utf-8")
        self.vorher = baum(self.vault)

    def tearDown(self):
        self.tmp.cleanup()

    def test_probelauf_aendert_nichts(self):
        plan = namen_auron.planen(self.vault)
        links = namen_auron.link_plan(self.vault, plan["dateien"])
        text = namen_auron.bericht(plan, links, probelauf=True)
        self.assertIn("PROBELAUF", text)
        self.assertIn("Jarvis Projekt Anweisung.md  ->  Auron Projekt Anweisung.md", text)
        self.assertEqual(len(plan["konflikte"]), 1)
        self.assertNotIn(".obsidian/jarvis.json", plan["dateien"])
        self.assertEqual(baum(self.vault), self.vorher)

    def test_umstellen_links_und_rueckweg(self):
        erg = namen_auron.ausfuehren(self.vault, self.arbeit)
        self.assertEqual(erg["umbenannt"], 4)        # 3 Dateien + 1 Ordner (der Konflikt bleibt)
        self.assertTrue((self.vault / "Wissen/Auron Projekt Anweisung.md").is_file())
        self.assertTrue((self.vault / "Auron/Notiz.md").is_file())
        self.assertTrue((self.vault / "01 - Persönliches/06 - Auron fragt.md").is_file())
        self.assertTrue((self.vault / "Bilder/bild-auron.png").is_file())
        self.assertEqual((self.vault / "Konflikt/Jarvis Log.md").read_text(encoding="utf-8"), "alt")   # Konflikt: bleibt
        self.assertTrue((self.vault / ".obsidian/jarvis.json").is_file())
        text = (self.vault / "Wissen/Übersicht.md").read_text(encoding="utf-8")
        for soll in ("[[Auron Projekt Anweisung]]", "[[Auron Projekt Anweisung|die Anweisung]]",
                     "[[Wissen/Auron Projekt Anweisung#Teil 2]]", "![[bild-auron.png]]", "[[Auron/Notiz]]",
                     "[Notiz](Auron/Notiz.md)", "[Anw](Wissen/Auron%20Projekt%20Anweisung.md)",
                     "[Web](https://example.org/Jarvis)", "[[06 - Auron fragt]]", "Jarvis bleibt im Text."):
            self.assertIn(soll, text)
        self.assertIn("Jarvis ist der alte Name.", (self.vault / "Wissen/Auron Projekt Anweisung.md").read_text(encoding="utf-8"))
        self.assertTrue((self.arbeit / "sicherung/Wissen/Übersicht.md").is_file())
        # Rückweg: alles wie vorher
        zurueck = namen_auron.zurueck(Path(erg["rueckweg"]))
        self.assertEqual(zurueck["zurueck_benannt"], 4)
        self.assertEqual(baum(self.vault), self.vorher)

    def test_nichts_zu_tun(self):
        leer = Path(self.tmp.name) / "leer"
        (leer / "A").mkdir(parents=True)
        (leer / "A/Auron.md").write_text("x", encoding="utf-8")
        plan = namen_auron.planen(leer)
        self.assertEqual((plan["umbenennen"], plan["dateien"]), ([], {}))

    def test_vault_finden(self):
        jarvis = Path(self.tmp.name) / "Jarvis"
        (jarvis / "data").mkdir(parents=True)
        (jarvis / "data/einstellungen.json").write_text(json.dumps({"vault_pfad": str(self.vault)}), encoding="utf-8")
        self.assertEqual(namen_auron.vault_finden(jarvis), self.vault)
        (jarvis / "data/einstellungen.json").write_text("{}", encoding="utf-8")
        self.assertIsNone(namen_auron.vault_finden(jarvis))

    def test_aufruf_probelauf_und_bericht(self):
        bericht = Path(self.tmp.name) / "bericht.txt"
        with mock.patch("sys.stdout"):
            rc = namen_auron.main(["--vault", str(self.vault), "--bericht", str(bericht)])
        self.assertEqual(rc, 0)
        self.assertIn("PROBELAUF", bericht.read_text(encoding="utf-8"))
        self.assertEqual(baum(self.vault), self.vorher)


if __name__ == "__main__":
    unittest.main()

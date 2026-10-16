"""
Tests für TikTok-Dubletten (P25, 16.10.2026) - ohne Netz, yt-dlp und Vault
werden simuliert.

Start:
    python -m unittest tests.test_tiktok_dubletten -v
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import tiktok, tiktok_sehen

NUMMER = "7684314895554465027"
VOLL = f"https://www.tiktok.com/@ki.tipps/video/{NUMMER}"
KURZ = "https://vm.tiktok.com/ZMabc123/"


class Basis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.vault.mkdir()
        self.patch = mock.patch.dict(os.environ, {"TIKTOK_PATH": str(Path(self.tmp.name) / "tt"), "VAULT_PATH": str(self.vault)})
        self.patch.start()
        tiktok._python_cache = None

    def tearDown(self):
        self.patch.stop()
        tiktok._python_cache = None
        self.tmp.cleanup()

    def fake_run(self, nummer: str = NUMMER, titel: str = "RAG in 60 Sekunden"):
        def run(befehl, **kw):
            if "--version" in befehl:
                return SimpleNamespace(returncode=0, stdout="2026.09.01", stderr="")
            ziel = Path(befehl[befehl.index("-o") + 1]).parent
            (ziel / f"{nummer}.info.json").write_text(json.dumps({
                "id": nummer, "title": titel, "uploader": "ki.tipps", "description": "x", "duration": 58}), encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return run

    def abrufen(self, vid: str, nummer: str = NUMMER) -> dict:
        with mock.patch.object(tiktok.subprocess, "run", side_effect=self.fake_run(nummer)):
            return tiktok.abrufen(vid)

    def in_vault(self, vid: str) -> dict:
        with mock.patch.object(tiktok, "_git_sichern"):
            return tiktok.in_vault(vid)

    def notizen(self) -> list[Path]:
        ordner = self.vault / tiktok.ENTWURF_ORDNER
        return sorted(ordner.glob("*.md")) if ordner.is_dir() else []

    def kurz_id(self) -> str:
        return tiktok.link_id(KURZ)


class Anlegen(Basis):
    def test_voller_link_dann_kurzlink_wird_dublette_ohne_zweite_notiz(self):
        tiktok.hinzufuegen(VOLL)
        self.abrufen(NUMMER)
        original = self.in_vault(NUMMER)
        tiktok.hinzufuegen(KURZ)
        e = self.abrufen(self.kurz_id())
        self.assertEqual((e["status"], e["dublette_von"], e["fehler"]), ("dublette", NUMMER, None))
        self.assertEqual(e["original_titel"], "RAG in 60 Sekunden")
        self.assertEqual(e["original_notiz"], original["notiz"])
        with self.assertRaises(tiktok.TikTokFehler) as ctx:
            self.in_vault(self.kurz_id())
        self.assertIn("Doppelt", str(ctx.exception))
        self.assertEqual(len(self.notizen()), 1)

    def test_dublette_wird_nicht_nochmal_abgerufen(self):
        tiktok.hinzufuegen(VOLL)
        self.abrufen(NUMMER)
        tiktok.hinzufuegen(KURZ)
        self.abrufen(self.kurz_id())
        with mock.patch.object(tiktok.subprocess, "run", side_effect=AssertionError("yt-dlp darf nicht laufen")):
            e = tiktok.abrufen(self.kurz_id())
        self.assertEqual(e["status"], "dublette")
        self.assertEqual(e["original_titel"], "RAG in 60 Sekunden")

    def test_kurzlink_dann_voller_link_wird_gar_nicht_angelegt(self):
        tiktok.hinzufuegen(KURZ)
        self.abrufen(self.kurz_id())
        r = tiktok.hinzufuegen(VOLL)
        self.assertEqual((r["neu"], r["gesamt"]), (0, 1))
        self.assertEqual(len(tiktok.liste()), 1)

    def test_kurzlink_ohne_abruf_bleibt_eigener_eintrag(self):
        tiktok.hinzufuegen(KURZ)
        self.assertEqual(tiktok.hinzufuegen(VOLL)["neu"], 1)


class Vault(Basis):
    def test_in_vault_zweimal_eine_datei_und_bild_block_bleibt(self):
        tiktok.hinzufuegen(VOLL)
        self.abrufen(NUMMER)
        e = self.in_vault(NUMMER)
        datei = self.vault / e["notiz"]
        with datei.open("a", encoding="utf-8") as f:
            f.write("\n<!-- auron-sehen:anfang -->\n![[bild.jpg]]\n<!-- auron-sehen:ende -->\n")
        vorher = datei.read_text(encoding="utf-8")
        zweite = self.in_vault(NUMMER)
        self.assertEqual(zweite["notiz"], e["notiz"])
        self.assertEqual(len(self.notizen()), 1)
        self.assertEqual(datei.read_text(encoding="utf-8"), vorher)
        self.assertIn("![[bild.jpg]]", datei.read_text(encoding="utf-8"))

    def test_fehlende_datei_wird_neu_angelegt(self):
        tiktok.hinzufuegen(VOLL)
        self.abrufen(NUMMER)
        e = self.in_vault(NUMMER)
        (self.vault / e["notiz"]).unlink()
        zweite = self.in_vault(NUMMER)
        self.assertEqual(len(self.notizen()), 1)
        self.assertEqual(zweite["notiz"], e["notiz"])


class Sehen(Basis):
    def _liste(self):
        notiz = f"{tiktok.ENTWURF_ORDNER}/a.md"
        tiktok._speichern([
            {"id": "1", "url": "https://www.tiktok.com/@a/video/111111111", "status": "im_vault", "notiz": notiz,
             "hinzugefuegt": "2026-10-01T10:00:00+02:00", "gesehen": "2026-10-02", "thema": "Sonstiges",
             "sehen_titel": "Original"},
            {"id": "kdubl", "url": KURZ, "status": "dublette", "dublette_von": "1", "notiz": notiz,
             "hinzugefuegt": "2026-10-02T10:00:00+02:00", "gesehen": "2026-10-02", "thema": "Sonstiges",
             "sehen_titel": "Doppelt"},
            {"id": "2", "url": "https://www.tiktok.com/@a/video/222222222", "status": "im_vault", "notiz": "b.md",
             "hinzugefuegt": "2026-10-03T10:00:00+02:00"},
            {"id": "kdubl2", "url": KURZ + "x", "status": "dublette", "dublette_von": "2", "notiz": "b.md",
             "hinzugefuegt": "2026-10-04T10:00:00+02:00"},
        ])

    def test_kandidaten_ohne_dubletten(self):
        self._liste()
        self.assertEqual([e["id"] for e in tiktok_sehen.kandidaten()], ["2"])

    def test_uebersicht_ohne_dubletten(self):
        self._liste()
        pfad = tiktok_sehen.uebersicht_schreiben(str(self.vault))
        text = (self.vault / pfad).read_text(encoding="utf-8")
        self.assertIn("Original", text)
        self.assertNotIn("Doppelt", text)
        self.assertIn("1 ausgewertete", text)

    def test_video_sehen_lehnt_dublette_ab(self):
        self._liste()
        with self.assertRaises(tiktok_sehen.SehenFehler):
            tiktok_sehen.video_sehen("kdubl")


class Reparieren(Basis):
    def test_markiert_bestehendes_paar_und_aendert_keine_notiz(self):
        alt_ordner = self.vault / tiktok.ENTWURF_ORDNER
        alt_ordner.mkdir(parents=True)
        (alt_ordner / "A.md").write_text("Original", encoding="utf-8")
        (alt_ordner / "B.md").write_text("Zweite", encoding="utf-8")
        tiktok._speichern([
            {"id": NUMMER, "url": VOLL, "status": "im_vault", "hinzugefuegt": "2026-10-01T10:00:00+02:00",
             "video_id": NUMMER, "notiz": f"{tiktok.ENTWURF_ORDNER}/A.md"},
            {"id": "kabc", "url": KURZ, "status": "im_vault", "hinzugefuegt": "2026-10-02T10:00:00+02:00",
             "video_id": NUMMER, "notiz": f"{tiktok.ENTWURF_ORDNER}/B.md"},
            {"id": "9999999999", "url": "https://www.tiktok.com/@a/video/9999999999", "status": "neu",
             "hinzugefuegt": "2026-10-03T10:00:00+02:00"},
        ])
        r = tiktok.reparieren()
        self.assertEqual(r["dubletten"], 1)
        self.assertEqual(r["dubletten_notizen"], [f"{tiktok.ENTWURF_ORDNER}/B.md"])
        liste = {e["id"]: e for e in tiktok.liste()}
        self.assertEqual(liste["kabc"]["status"], "dublette")
        self.assertEqual(liste["kabc"]["dublette_von"], NUMMER)
        self.assertNotIn("dublette_von", liste[NUMMER])
        self.assertNotIn("dublette_von", liste["9999999999"])
        self.assertEqual((alt_ordner / "A.md").read_text(encoding="utf-8"), "Original")
        self.assertEqual((alt_ordner / "B.md").read_text(encoding="utf-8"), "Zweite")
        self.assertEqual(len(liste), 3)  # nichts gelöscht
        self.assertEqual(tiktok.reparieren()["dubletten"], 0)  # zweiter Lauf: nichts Neues

    def test_aeltester_bleibt_auch_wenn_er_hinten_in_der_liste_steht(self):
        tiktok._speichern([
            {"id": "kneu", "url": KURZ, "status": "geholt", "hinzugefuegt": "2026-10-05T10:00:00+02:00", "video_id": NUMMER},
            {"id": NUMMER, "url": VOLL, "status": "neu", "hinzugefuegt": "2026-10-01T10:00:00+02:00"},
        ])
        self.assertEqual(tiktok.reparieren()["dubletten"], 1)
        liste = {e["id"]: e for e in tiktok.liste()}
        self.assertEqual(liste["kneu"]["dublette_von"], NUMMER)
        self.assertNotIn("dublette_von", liste[NUMMER])


if __name__ == "__main__":
    unittest.main()

"""
Tests für app/tiktok.py (TikTok-Seite, 23.09.2026) - ohne Netz, yt-dlp wird
simuliert.

Start:
    python -m unittest tests.test_tiktok -v
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import tiktok

VTT = """WEBVTT
Kind: captions
Language: de

1
00:00:00.000 --> 00:00:02.000
<c>Heute zeige ich euch</c>

2
00:00:02.000 --> 00:00:04.000
Heute zeige ich euch
wie RAG funktioniert
"""


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


class Links(Basis):
    def test_links_aus_text(self):
        text = ("schau https://www.tiktok.com/@ki.tipps/video/7684314895554465027?lang=de und "
                "| https://www.tiktokv.com/share/video/7673964184140385567/ | und https://vm.tiktok.com/ZMabc123/. "
                "aber nicht https://youtube.com/watch?v=1")
        urls = tiktok.links_finden(text)
        self.assertEqual(len(urls), 3)
        self.assertTrue(urls[2].endswith("ZMabc123/"))

    def test_id(self):
        self.assertEqual(tiktok.link_id("https://www.tiktok.com/@a/video/7684314895554465027"), "7684314895554465027")
        self.assertTrue(tiktok.link_id("https://vm.tiktok.com/ZMabc/").startswith("k"))

    def test_hinzufuegen_ohne_doppelte(self):
        r1 = tiktok.hinzufuegen("https://www.tiktokv.com/share/video/7673964184140385567/")
        r2 = tiktok.hinzufuegen("https://www.tiktok.com/@x/video/7673964184140385567 https://www.tiktok.com/@x/video/7600000000000000001")
        self.assertEqual((r1["neu"], r2["neu"], r2["gesamt"]), (1, 1, 2))
        self.assertEqual(tiktok.liste()[0]["status"], "neu")

    def test_ohne_link_fehler(self):
        with self.assertRaises(tiktok.TikTokFehler):
            tiktok.hinzufuegen("nur Text")

    def test_ideen_import(self):
        datei = Path(self.tmp.name) / "ideen.md"
        datei.write_text("| 1 | x | https://www.tiktokv.com/share/video/7684314895554465027/ |\n"
                         "| 2 | y | https://www.tiktokv.com/share/video/7673964184140385567/ |\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"TIKTOK_IDEEN_DATEI": str(datei)}):
            self.assertEqual(tiktok.ideen_importieren()["neu"], 2)
            self.assertEqual(tiktok.ideen_importieren()["neu"], 0)

    def test_kaputte_liste_wird_beiseitegelegt(self):
        tiktok.ordner()
        (Path(os.environ["TIKTOK_PATH"]) / "links.json").write_text("{kaputt", encoding="utf-8")
        self.assertEqual(tiktok.liste(), [])
        self.assertTrue((Path(os.environ["TIKTOK_PATH"]) / "links.kaputt.json").exists())


class Untertitel(unittest.TestCase):
    def test_vtt_zu_text(self):
        self.assertEqual(tiktok.vtt_zu_text(VTT), "Heute zeige ich euch wie RAG funktioniert")

    def test_deutsch_bevorzugt(self):
        dateien = [Path("123.eng-US.vtt"), Path("123.deu-DE.vtt"), Path("123.fra.vtt")]
        self.assertEqual(tiktok._untertitel_wahl(dateien).name, "123.deu-DE.vtt")
        self.assertIsNone(tiktok._untertitel_wahl([]))


class Abrufen(Basis):
    def _fake_run(self, rueckgabe=0, info=True, vtt=True):
        def run(befehl, **kw):
            if "--version" in befehl:
                return SimpleNamespace(returncode=0, stdout="2026.09.01", stderr="")
            ziel = Path(befehl[befehl.index("-o") + 1]).parent
            if info:
                (ziel / "7684314895554465027.info.json").write_text(json.dumps({
                    "id": "7684314895554465027", "title": "RAG in 60 Sekunden", "uploader": "ki.tipps",
                    "description": "So funktioniert RAG #ki", "duration": 58, "tags": ["ki", "rag"]}), encoding="utf-8")
            if vtt:
                (ziel / "7684314895554465027.deu-DE.vtt").write_text(VTT, encoding="utf-8")
            return SimpleNamespace(returncode=rueckgabe, stdout="", stderr="ERROR: Video nicht verfügbar")
        return run

    def _neu(self):
        tiktok.hinzufuegen("https://www.tiktok.com/@ki.tipps/video/7684314895554465027")
        return "7684314895554465027"

    def test_abruf_und_vault(self):
        vid = self._neu()
        with mock.patch.object(tiktok.subprocess, "run", side_effect=self._fake_run()) as run:
            e = tiktok.abrufen(vid)
        befehl = run.call_args.args[0]
        self.assertIn("--skip-download", befehl)
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertEqual((e["status"], e["titel"], e["autor"], e["dauer_s"]), ("geholt", "RAG in 60 Sekunden", "ki.tipps", 58))
        self.assertIn("RAG funktioniert", tiktok.details(vid)["transkript"])
        with mock.patch.object(tiktok, "_git_sichern") as git:
            e = tiktok.in_vault(vid)
        self.assertEqual(e["status"], "im_vault")
        text = (self.vault / e["notiz"]).read_text(encoding="utf-8")
        self.assertTrue(e["notiz"].startswith(tiktok.ENTWURF_ORDNER))
        self.assertIn("status: entwurf", text)
        self.assertIn("  - rag\n", text)
        self.assertIn("wie RAG funktioniert", text)
        git.assert_called_once()
        with mock.patch.object(tiktok, "_git_sichern"):
            zweite = tiktok.in_vault(vid)
        self.assertEqual(zweite["notiz"], e["notiz"])  # P25: keine zweite Notiz, nichts überschrieben
        self.assertEqual(len(list((self.vault / tiktok.ENTWURF_ORDNER).glob("*.md"))), 1)

    def test_fehler_von_yt_dlp(self):
        vid = self._neu()
        with mock.patch.object(tiktok.subprocess, "run", side_effect=self._fake_run(rueckgabe=1, info=False, vtt=False)):
            e = tiktok.abrufen(vid)
        self.assertEqual(e["status"], "fehler")
        self.assertIn("nicht verfügbar", e["fehler"])

    def test_zeitueberschreitung(self):
        vid = self._neu()
        def run(befehl, **kw):
            if "--version" in befehl:
                return SimpleNamespace(returncode=0, stdout="x", stderr="")
            raise subprocess.TimeoutExpired(befehl, 1)
        with mock.patch.object(tiktok.subprocess, "run", side_effect=run):
            self.assertEqual(tiktok.abrufen(vid)["status"], "fehler")

    def test_ohne_yt_dlp_klare_meldung(self):
        vid = self._neu()
        with mock.patch.object(tiktok.subprocess, "run", side_effect=OSError("nicht da")):
            with self.assertRaises(tiktok.TikTokFehler) as ctx:
                tiktok.abrufen(vid)
            self.assertIn("TIKTOK_EINRICHTEN.bat", str(ctx.exception))
            self.assertFalse(tiktok.stand()["yt_dlp"])

    def test_vault_erst_nach_abruf(self):
        vid = self._neu()
        with self.assertRaises(tiktok.TikTokFehler):
            tiktok.in_vault(vid)

    def test_dateiname_sicher(self):
        self.assertEqual(tiktok._dateiname('KI: "Tipps" / #1 [neu]?'), "KI Tipps 1 neu.md")
        self.assertEqual(tiktok._dateiname("   "), "TikTok-Video.md")


class Reparatur2309(unittest.TestCase):
    """23.09.2026: zusammengeklebte Links, Foto-Beiträge, hängende Abrufe."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"TIKTOK_PATH": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)

    def test_geklebte_links_werden_getrennt(self):
        text = "https://www.tiktok.com/@tjhttps://www.tiktok.com/@luke.builds.ai/video/7675783328854789390"
        self.assertEqual(tiktok.links_finden(text)[-1], "https://www.tiktok.com/@luke.builds.ai/video/7675783328854789390")

    def test_reparieren(self):
        tiktok._speichern([
            {"id": "a", "url": "https://www.tiktok.com/@x/vihttps://www.tiktok.com/@y/video/1234567890123", "status": "fehler"},
            {"id": "b", "url": "https://www.tiktok.com/@z/video/9876543210987", "status": "laeuft"},
        ])
        r = tiktok.reparieren()
        self.assertEqual((r["getrennt"], r["zurueckgesetzt"]), (1, 1))
        liste = {e["id"]: e for e in tiktok.liste()}
        self.assertEqual(liste["1234567890123"]["status"], "neu")
        self.assertEqual(liste["b"]["status"], "neu")
        self.assertTrue(liste["a"]["repariert"])

    def test_link_mitten_im_link(self):
        """Echte Fälle aus Sir's Liste: zweiter Link wurde MITTEN in den ersten eingefügt."""
        a = "https://www.tiktok.com/@jackroberts____/vihttps://www.tiktok.com/@floknowsai/video/7686196111538769184deo/7686153367625780513"
        b = "https://www.tiktok.com/@tjhttps://www.tiktok.com/@luke.builds.ai/video/7675783328854789390rlover.9/video/7684379026885987598"
        self.assertEqual(tiktok.links_finden(a), ["https://www.tiktok.com/@jackroberts____/video/7686153367625780513",
                                                  "https://www.tiktok.com/@floknowsai/video/7686196111538769184"])
        self.assertEqual(tiktok.links_finden(b), ["https://www.tiktok.com/@tjrlover.9/video/7684379026885987598",
                                                  "https://www.tiktok.com/@luke.builds.ai/video/7675783328854789390"])
        hinter = "https://www.tiktok.com/@a/video/1234567890123https://www.tiktok.com/@b/video/9876543210987"
        self.assertEqual(len(tiktok.links_finden(hinter)), 2)
        self.assertEqual(tiktok.links_finden("x https://vm.tiktok.com/ZMabc123/ y"), ["https://vm.tiktok.com/ZMabc123/"])

    def test_reparieren_echter_fall(self):
        url = "https://www.tiktok.com/@jackroberts____/vihttps://www.tiktok.com/@floknowsai/video/7686196111538769184deo/7686153367625780513"
        tiktok._speichern([{"id": "7686196111538769184", "url": url, "status": "fehler", "repariert": True,
                            "fehler": "Link war zusammengeklebt - aufgeteilt in: kaputt"}])
        r = tiktok.reparieren()
        self.assertEqual(r["getrennt"], 2)
        liste = {e["id"]: e for e in tiktok.liste()}
        self.assertEqual(liste["7686196111538769184"]["url"], "https://www.tiktok.com/@floknowsai/video/7686196111538769184")
        self.assertEqual(liste["7686196111538769184"]["status"], "neu")
        self.assertEqual(liste["7686196111538769184"]["original_url"], url)
        self.assertEqual(liste["7686153367625780513"]["status"], "neu")
        self.assertEqual(tiktok.reparieren()["getrennt"], 0)  # zweimal reparieren ändert nichts mehr

    def test_foto_beitrag_ueber_oembed(self):
        tiktok._speichern([{"id": "7670915815952157972", "url": "https://www.tiktok.com/@zoout/photo/7670915815952157972", "status": "neu"}])
        e = tiktok._foto_beitrag("7670915815952157972", "https://www.tiktok.com/@zoout/photo/7670915815952157972",
                                 holen=lambda url: {"title": "5 KI-Tools #ki #claude", "author_name": "Zoout", "author_unique_id": "zoout"})
        self.assertEqual((e["status"], e["autor"], e["art"]), ("geholt", "zoout", "foto"))
        self.assertIn("ki", e["tags"])
        self.assertIn("keine Abschrift", e["beschreibung"])


JPG = b"\xff\xd8\xff\xe0" + b"0" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


class Slides2609(Basis):
    """Foto-Beiträge / Slides (26.09.2026): Bilder zuordnen, mit Haiku lesen, in den Vault."""

    VID = "7670915815952157972"

    def setUp(self):
        super().setUp()
        self.ablage = Path(self.tmp.name) / "ablage"
        p = mock.patch.dict(os.environ, {"ABLAGE_PATH": str(self.ablage)})
        p.start()
        self.addCleanup(p.stop)
        tiktok._speichern([{"id": self.VID, "url": f"https://www.tiktok.com/@zoout/photo/{self.VID}", "status": "fehler",
                            "fehler": "Foto-Beitrag"}])
        # Claude-Module durch Attrappen ersetzen (Cloud ohne anthropic/chromadb; am PC ohne echte Kosten)
        import app
        self.protokoll, self.rest = [], 5.0
        attrappen = {
            "kosten": SimpleNamespace(uebersicht=lambda: {"rest_usd": self.rest}),
            "chat_service": SimpleNamespace(log_usage=lambda *a, **k: self.protokoll.append(k.get("mode"))),
            "aufgaben_loop": SimpleNamespace(_kosten_usd=lambda m, u: 0.0035, _anthropic_client=lambda: None),
            "pruefschritt": SimpleNamespace(PRUEF_MODELL="claude-haiku-test"),
        }
        for name, modul in attrappen.items():
            p = mock.patch.object(app, name, modul, create=True)
            p.start()
            self.addCleanup(p.stop)
            p = mock.patch.dict("sys.modules", {"app." + name: modul})
            p.start()
            self.addCleanup(p.stop)

    def _client(self, texte):
        anfragen = []

        def create(**kw):
            anfragen.append(kw)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=texte[len(anfragen) - 1])],
                                   usage=SimpleNamespace(input_tokens=1800, output_tokens=200))
        return SimpleNamespace(messages=SimpleNamespace(create=create)), anfragen

    def test_bilder_hinzufuegen_reihenfolge_und_pruefung(self):
        self.assertEqual(tiktok.bild_hinzufuegen(self.VID, JPG)["name"], "01.jpg")
        self.assertEqual(tiktok.bild_hinzufuegen(self.VID, PNG)["name"], "02.png")
        self.assertEqual([b["name"] for b in tiktok.bilder(self.VID)], ["01.jpg", "02.png"])
        with self.assertRaises(tiktok.TikTokFehler):
            tiktok.bild_hinzufuegen(self.VID, b"%PDF-1.4 kein Bild")
        with self.assertRaises(tiktok.TikTokFehler):
            tiktok.bild_hinzufuegen(self.VID, b"")
        with mock.patch.object(tiktok, "MAX_BILD_BYTES", 50), self.assertRaises(tiktok.TikTokFehler):
            tiktok.bild_hinzufuegen(self.VID, JPG)
        with mock.patch.object(tiktok, "MAX_BILDER", 2), self.assertRaises(tiktok.TikTokFehler):
            tiktok.bild_hinzufuegen(self.VID, JPG)
        with self.assertRaises(tiktok.TikTokFehler):
            tiktok.bild_hinzufuegen("gibtsnicht", JPG)

    def test_aus_ablage_uebernehmen_ablage_bleibt(self):
        self.ablage.mkdir(parents=True)
        (self.ablage / "Slide A.jpg").write_bytes(JPG)
        (self.ablage / "notiz.txt").write_text("kein Bild")
        r = tiktok.bilder_aus_ablage(self.VID, ["Slide A.jpg", "notiz.txt", "fehlt.jpg"])
        self.assertEqual(r["uebernommen"], ["01.jpg"])
        self.assertEqual(len(r["fehler"]), 2)
        self.assertTrue((self.ablage / "Slide A.jpg").exists())

    def test_bild_pfad_nur_eigene_namen(self):
        tiktok.bild_hinzufuegen(self.VID, JPG)
        self.assertTrue(tiktok.bild_pfad(self.VID, "01.jpg").is_file())
        for boese in ("../links.json", "..\\x.jpg", "01.exe", ""):
            with self.assertRaises(tiktok.TikTokFehler):
                tiktok.bild_pfad(self.VID, boese)

    def test_lesen_und_vault(self):
        tiktok.bild_hinzufuegen(self.VID, JPG)
        tiktok.bild_hinzufuegen(self.VID, PNG)
        client, anfragen = self._client(["# 5 KI-Tools für Trader\nTool 1: Claude", "Tool 2: n8n\nBild: App-Screenshot"])
        e = tiktok.bilder_lesen(self.VID, client=client)
        self.assertEqual((e["status"], e["art"], e["bilder"], e["autor"]), ("geholt", "foto", 2, "zoout"))
        self.assertEqual(e["titel"], "5 KI-Tools für Trader")
        self.assertAlmostEqual(e["slides_kosten_usd"], 0.007)
        self.assertEqual(self.protokoll, ["tiktok-slides", "tiktok-slides"])
        self.assertEqual(anfragen[0]["model"], "claude-haiku-test")
        self.assertEqual(anfragen[1]["messages"][0]["content"][0]["source"]["media_type"], "image/png")
        self.assertIn("Slide 2:\nTool 2: n8n", tiktok.details(self.VID)["transkript"])

        e = tiktok.in_vault(self.VID)
        notiz = (self.vault / e["notiz"]).read_text(encoding="utf-8")
        self.assertIn("## Slides", notiz)
        self.assertIn(f"![[tiktok-{self.VID}-01.jpg|300]]", notiz)
        self.assertIn("Foto-Beitrag (Slides) von **zoout**", notiz)
        self.assertNotIn("## Abschrift", notiz)
        bilder = self.vault / tiktok.ENTWURF_ORDNER / "Bilder"
        self.assertEqual(sorted(p.name for p in bilder.iterdir()), [f"tiktok-{self.VID}-01.jpg", f"tiktok-{self.VID}-02.png"])
        # zweites Mal: Bilder bleiben, nichts wird überschrieben
        tiktok.in_vault(self.VID)
        self.assertEqual(len(list(bilder.iterdir())), 2)

    def test_lesen_gesperrt_wenn_rahmen_knapp(self):
        tiktok.bild_hinzufuegen(self.VID, JPG)
        self.rest = 0.1
        client, anfragen = self._client(["x"])
        with self.assertRaises(tiktok.TikTokFehler):
            tiktok.bilder_lesen(self.VID, client=client)
        self.assertEqual(anfragen, [])

    def test_lesen_ohne_bilder(self):
        with self.assertRaises(tiktok.TikTokFehler):
            tiktok.bilder_lesen(self.VID, client=self._client([])[0])

    def test_video_notiz_unveraendert(self):
        tiktok._speichern([{"id": "1234567890123", "url": "https://www.tiktok.com/@a/video/1234567890123", "status": "geholt",
                            "titel": "Video", "autor": "a", "dauer_s": 30}])
        e = tiktok.in_vault("1234567890123")
        notiz = (self.vault / e["notiz"]).read_text(encoding="utf-8")
        self.assertIn("Video von **a**, 30 Sekunden.", notiz)
        self.assertIn("## Abschrift", notiz)
        self.assertFalse((self.vault / tiktok.ENTWURF_ORDNER / "Bilder").exists())

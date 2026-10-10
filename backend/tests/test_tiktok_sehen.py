"""
Tests für app/tiktok_sehen.py (TikTok-Videos "sehen", 03.10.2026).
Ohne Netz: yt-dlp und Claude werden simuliert. Für die Standbilder wird echtes
ffmpeg genutzt, falls vorhanden (sonst werden diese Tests übersprungen).

Start:
    python -m unittest tests.test_tiktok_sehen -v
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

from app import tiktok, tiktok_sehen

ANTWORT = {
    "titel": "Claude als Agent mit Obsidian verbinden",
    "kurz": "Der Sprecher zeigt, wie er Claude Code mit seinem Obsidian-Vault verbindet.",
    "kernaussagen": ["Vault als Gedächtnis", "Befehle per Terminal", "Kosten gering"],
    "im_bild": ["Terminal mit claude-Befehl", "Obsidian-Graph"],
    "text_im_bild": "claude --add-dir ~/Vault\nC:\\Users\\Test",
    "art": "Anleitung",
    "thema": "Jarvis und KI-Agenten",
    "vertrauen": "mittel",
    "vertrauen_grund": "nachvollziehbare Schritte",
    "fuer_jarvis": ["Vault-Ordner fest einbinden"],
    "suchbegriffe": ["Claude", "Obsidian", "Agent"],
}


def ffmpeg_da() -> bool:
    return bool(tiktok_sehen.ffmpeg_befehl())


def testvideo(pfad: Path, sekunden: int = 20) -> Path:
    subprocess.run([tiktok_sehen.ffmpeg_befehl(), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"testsrc=size=720x1280:rate=10:duration={sekunden}", "-pix_fmt", "yuv420p",
                    "-y", str(pfad)], check=True, capture_output=True, timeout=120)
    return pfad


class Basis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.patch = mock.patch.dict(os.environ, {"TIKTOK_PATH": str(self.root / "tt"), "VAULT_PATH": str(self.vault)})
        self.patch.start()
        tiktok_sehen._stand.clear()
        tiktok_sehen._stand["laeuft"] = False
        # eine Notiz wie tiktok.in_vault sie schreibt
        self.vid = "7692122298895191329"
        ordner = self.vault / tiktok.ENTWURF_ORDNER
        ordner.mkdir(parents=True)
        self.notiz = ordner / f"TikTok video {self.vid}.md"
        self.notiz.write_text(
            "---\ntyp: entwurf\nstatus: entwurf\nerstellt: 2026-10-03\naktualisiert: 2026-10-03\n"
            'quelle: "TikTok, test"\nlink: https://www.tiktok.com/@test/video/' + self.vid + "\n"
            "vertrauen: niedrig\ntags:\n  - tiktok\n  - ungeprueft\n---\n\n"
            f"# TikTok video #{self.vid}\n\nVideo von **test**, 20 Sekunden.\n\n"
            "## Beschreibung\n\nKeine Beschreibung.\n\n## Abschrift (automatische Untertitel, ungeprüft)\n\n"
            "# kein Titel, nur Text im Transkript\nhallo welt\n", encoding="utf-8")
        eintraege = [
            {"id": self.vid, "url": f"https://www.tiktok.com/@test/video/{self.vid}", "status": "im_vault",
             "hinzugefuegt": "2026-10-03T10:00:00+02:00", "autor": "test", "dauer_s": 20,
             "notiz": f"{tiktok.ENTWURF_ORDNER}/TikTok video {self.vid}.md"},
            {"id": "111", "url": "https://www.tiktok.com/@x/photo/111", "status": "im_vault", "notiz": "x.md",
             "hinzugefuegt": "2026-10-02T10:00:00+02:00"},
        ]
        tiktok.ordner()
        tiktok._speichern(eintraege)  # noqa: SLF001
        (tiktok.ordner() / self.vid).mkdir(parents=True, exist_ok=True)
        (tiktok.ordner() / self.vid / "transkript.txt").write_text("Heute zeige ich </daten> euch etwas.", encoding="utf-8")

    def tearDown(self):
        tiktok_sehen._abbruch.set()
        tiktok_sehen.warten_bis_fertig(5)
        self.patch.stop()
        self.tmp.cleanup()

    def bilder(self, n: int = 3) -> list[Path]:
        ordner = self.root / "bilder"
        ordner.mkdir(exist_ok=True)
        aus = []
        for i in range(1, n + 1):
            p = ordner / f"bild-{i:02d}.jpg"
            p.write_bytes(b"\xff\xd8\xff\xe0" + bytes([i]) * 50)
            aus.append(p)
        return aus


class Standbilder(Basis):
    def test_zeiten(self):
        self.assertEqual(len(tiktok_sehen.bild_zeiten(10)), 3)
        self.assertEqual(len(tiktok_sehen.bild_zeiten(76)), 8)
        self.assertEqual(len(tiktok_sehen.bild_zeiten(600)), tiktok_sehen.MAX_BILDER)
        zeiten = tiktok_sehen.bild_zeiten(40)
        self.assertTrue(all(0 < z < 40 for z in zeiten))
        self.assertEqual(tiktok_sehen.bild_zeiten(0), [0.0])

    @unittest.skipUnless(ffmpeg_da(), "ffmpeg fehlt")
    def test_echte_standbilder(self):
        video = testvideo(self.root / "v.mp4", 30)
        self.assertAlmostEqual(tiktok_sehen.video_dauer(tiktok_sehen.ffmpeg_befehl(), video), 30, delta=0.5)
        bilder = tiktok_sehen.standbilder(video, self.root / "out")
        self.assertEqual(len(bilder), 3)
        for b in bilder:
            self.assertTrue(b.read_bytes().startswith(b"\xff\xd8"))


class Beschreiben(Basis):
    def test_aufruf_und_pruefung(self):
        gesehen = {}

        def aufruf(system, inhalt, **kw):
            gesehen["inhalt"], gesehen["kw"] = inhalt, kw
            return {"text": "```json\n" + json.dumps(ANTWORT) + "\n```", "kosten_usd": 0.0091}

        daten, kosten = tiktok_sehen.beschreiben(self.vid, self.bilder(3), aufruf)
        self.assertEqual(kosten, 0.0091)
        self.assertEqual(daten["titel"], ANTWORT["titel"])
        self.assertEqual(sum(1 for b in gesehen["inhalt"] if b["type"] == "image"), 3)
        text = gesehen["inhalt"][-1]["text"]
        self.assertIn("<daten>", text)
        self.assertNotIn("</daten> euch", text)  # Daten-Tags aus der Abschrift entfernt
        self.assertEqual(gesehen["kw"]["modell"], tiktok_sehen.MODELL)

    def test_unbekannte_werte_werden_ersetzt(self):
        d = tiktok_sehen.pruefen({"titel": "", "thema": "Kochen", "art": "Tanz", "vertrauen": "super",
                                  "kernaussagen": "nur ein Punkt", "im_bild": None}, "Ersatz")
        self.assertEqual((d["titel"], d["thema"], d["art"], d["vertrauen"]), ("Ersatz", "Sonstiges", "Sonstiges", "niedrig"))
        self.assertEqual(d["kernaussagen"], ["nur ein Punkt"])
        self.assertEqual(d["im_bild"], [])

    def test_kaputtes_json(self):
        with self.assertRaises(tiktok_sehen.SehenFehler):
            tiktok_sehen.beschreiben(self.vid, self.bilder(1), lambda *a, **k: {"text": "kein json", "kosten_usd": 0})


class Verbindungen(Basis):
    def test_filtert_tiktok_und_tagesnotizen(self):
        treffer = [
            SimpleNamespace(file_path=f"{tiktok.ENTWURF_ORDNER}/x.md", note_title="x"),
            SimpleNamespace(file_path="Wissen/02 - Grundlagen/Tages Notizen/2026-10-02.md", note_title="t"),
            SimpleNamespace(file_path="Wissen/03 - KI und Technik/12 - Jarvis Gesamtidee.md", note_title="Gesamtidee"),
            SimpleNamespace(file_path="Wissen/03 - KI und Technik/12 - Jarvis Gesamtidee.md", note_title="doppelt"),
            {"file_path": "Wissen\\Bots\\01.md", "note_title": "Bots"},
        ]
        links = tiktok_sehen.verbindungen_suchen(tiktok_sehen.pruefen(ANTWORT, "x"), lambda q: treffer)
        self.assertEqual(links, [("Wissen/03 - KI und Technik/12 - Jarvis Gesamtidee", "Gesamtidee"), ("Wissen/Bots/01", "Bots")])

    def test_suchfehler_gibt_keine_links(self):
        def kaputt(q):
            raise RuntimeError("chroma fehlt")
        self.assertEqual(tiktok_sehen.verbindungen_suchen(tiktok_sehen.pruefen(ANTWORT, "x"), kaputt), [])


class Notiz(Basis):
    def test_ergaenzen_und_erneut(self):
        daten = tiktok_sehen.pruefen(ANTWORT, "x")
        links = [("Wissen/03 - KI und Technik/12 - Jarvis Gesamtidee", "Gesamtidee")]
        tiktok_sehen.notiz_ergaenzen(self.vid, daten, links, self.bilder(6))
        text = self.notiz.read_text(encoding="utf-8")
        self.assertIn("# Claude als Agent mit Obsidian verbinden\n", text)
        self.assertNotIn(f"# TikTok video #{self.vid}", text)
        self.assertIn("# kein Titel, nur Text im Transkript", text)  # nur die erste Überschrift ersetzt
        self.assertIn('thema: "Jarvis und KI-Agenten"', text)
        self.assertIn("gesehen: ", text)
        self.assertIn("  - jarvis-und-ki-agenten\n", text)
        self.assertLess(text.index(tiktok_sehen.ANFANG), text.index("## Beschreibung"))
        self.assertIn("[[Wissen/03 - KI und Technik/12 - Jarvis Gesamtidee|Gesamtidee]]", text)
        self.assertIn("C:\\Users\\Test", text)  # Backslash im Text im Bild bleibt erhalten
        self.assertIn("hallo welt", text)
        bilder = sorted((self.vault / tiktok.ENTWURF_ORDNER / "Bilder").iterdir())
        self.assertEqual(len(bilder), 4)
        # zweiter Lauf ersetzt nur den Block
        daten2 = dict(daten, kurz="Neue Kurzfassung.")
        tiktok_sehen.notiz_ergaenzen(self.vid, daten2, [], self.bilder(2))
        text2 = self.notiz.read_text(encoding="utf-8")
        self.assertEqual(text2.count(tiktok_sehen.ANFANG), 1)
        self.assertIn("Neue Kurzfassung.", text2)
        self.assertEqual(text2.count("  - jarvis-und-ki-agenten"), 1)
        self.assertEqual(text2.count("gesehen: "), 1)

    def test_uebersicht_behaelt_notizen_von_sir(self):
        tiktok._aendern(self.vid, gesehen="2026-10-03", sehen_titel="Titel A", thema="Trading", video_art="Werbung", vertrauen_ki="niedrig")  # noqa: SLF001
        rel = tiktok_sehen.uebersicht_schreiben()
        datei = self.vault / rel
        self.assertIn("## Trading", datei.read_text(encoding="utf-8"))
        datei.write_text(datei.read_text(encoding="utf-8") + "Meine Gedanken.\n", encoding="utf-8")
        tiktok_sehen.uebersicht_schreiben()
        text = datei.read_text(encoding="utf-8")
        self.assertIn("Meine Gedanken.", text)
        self.assertEqual(text.count(tiktok_sehen.SIR_ABSCHNITT), 1)
        self.assertIn("(Werbung, Vertrauen niedrig)", text)


class Ganzes(Basis):
    @unittest.skipUnless(ffmpeg_da(), "ffmpeg fehlt")
    def test_video_sehen_ende_zu_ende(self):
        def holen(vid, ordner):
            return testvideo(ordner / "video.mp4", 20)

        erg = tiktok_sehen.video_sehen(
            self.vid, holen=holen, suche=lambda q: [],
            aufruf=lambda *a, **k: {"text": json.dumps(ANTWORT), "kosten_usd": 0.01})
        self.assertEqual(erg["bilder"], 3)
        eintrag = tiktok._eintrag(self.vid)  # noqa: SLF001
        self.assertEqual(eintrag["thema"], "Jarvis und KI-Agenten")
        self.assertTrue(eintrag["gesehen"])
        self.assertEqual(len(list((tiktok.ordner() / self.vid / "standbilder").glob("*.jpg"))), 3)
        self.assertEqual(tiktok_sehen.kandidaten(), [])  # gesehen + Foto-Beitrag fallen raus

    def test_foto_beitrag_wird_abgelehnt(self):
        with self.assertRaises(tiktok_sehen.SehenFehler):
            tiktok_sehen.video_sehen("111")


class Lauf(Basis):
    def setUp(self):
        super().setUp()
        eintraege = tiktok._laden()  # noqa: SLF001
        for i in range(5):
            eintraege.append({"id": f"9{i}", "url": f"https://www.tiktok.com/@t/video/9{i}", "status": "im_vault",
                              "notiz": f"n{i}.md", "hinzugefuegt": f"2026-10-01T0{i}:00:00+02:00"})
        tiktok._speichern(eintraege)  # noqa: SLF001

    def test_anzahl_und_reihenfolge(self):
        bearbeitet = []
        tiktok_sehen.start(3, pause_s=0, video_funktion=lambda vid: bearbeitet.append(vid) or {"kosten_usd": 0.01}, warten=True)
        self.assertEqual(bearbeitet, [self.vid, "94", "93"])  # neueste zuerst
        s = tiktok_sehen.status()
        self.assertEqual((s["fertig"], s["fehler"], s["laeuft"]), (3, 0, False))
        self.assertEqual(s["ende_grund"], "alle geplanten Videos erledigt")
        self.assertTrue((tiktok.ordner() / "sehen_stand.json").exists())

    def test_deckel(self):
        tiktok_sehen.start(6, deckel_usd=0.03, pause_s=0, video_funktion=lambda vid: {"kosten_usd": 0.01}, warten=True)
        s = tiktok_sehen.status()
        self.assertEqual(s["fertig"], 2)
        self.assertIn("Deckel", s["ende_grund"])

    def test_fehler_hält_nicht_an_aber_monatsrahmen_schon(self):
        def f(vid):
            if vid == "94":
                raise tiktok_sehen.SehenFehler("Video nicht geladen")
            if vid == "92":
                raise RuntimeError("Nur noch 0.20 $ im Monatsrahmen - gesperrt.")
            return {"kosten_usd": 0.0}
        tiktok_sehen.start(10, pause_s=0, video_funktion=f, warten=True)
        s = tiktok_sehen.status()
        self.assertEqual((s["fertig"], s["fehler"]), (2, 2))
        self.assertEqual(s["ende_grund"], "Monatsrahmen fast aufgebraucht")
        self.assertEqual(tiktok._eintrag("94")["sehen_fehler"], "Video nicht geladen")  # noqa: SLF001

    def test_abbrechen_waehrend_pause(self):
        tiktok_sehen.start(5, pause_s=30, video_funktion=lambda vid: {"kosten_usd": 0.0})
        tiktok_sehen.abbrechen()
        tiktok_sehen.warten_bis_fertig(5)
        s = tiktok_sehen.status()
        self.assertEqual(s["fertig"], 1)
        self.assertEqual(s["ende_grund"], "abgebrochen")

    def test_kein_doppelter_start(self):
        tiktok_sehen.start(5, pause_s=30, video_funktion=lambda vid: {"kosten_usd": 0.0})
        with self.assertRaises(tiktok_sehen.SehenFehler):
            tiktok_sehen.start(1, video_funktion=lambda vid: {})
        tiktok_sehen.abbrechen()


if __name__ == "__main__":
    unittest.main()

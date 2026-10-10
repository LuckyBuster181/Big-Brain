"""Tests für app/kamera.py (Kamera-Modus, 10.10.2026). Ohne echten Claude-Aufruf."""

from __future__ import annotations

import base64
import unittest

from app import kamera

JPEG = base64.b64encode(b"\xff\xd8\xff\xe0" + b"0" * 100).decode()
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 100).decode()


def _fake(sammler: list):
    def aufruf(system, inhalt, **kw):
        sammler.append((system, inhalt, kw))
        return {"text": "Ich sehe ein Kabel, Sir.", "kosten_usd": 0.003, "ki": {"quelle": "claude", "modell": "haiku"}}
    return aufruf


class BildPruefen(unittest.TestCase):
    def test_jpeg_und_data_adresse(self):
        self.assertEqual(kamera.bild_pruefen(JPEG), JPEG)
        self.assertEqual(kamera.bild_pruefen("data:image/jpeg;base64," + JPEG), JPEG)

    def test_png_erlaubt(self):
        self.assertEqual(kamera._medientyp(kamera.bild_pruefen(PNG)), "image/png")
        self.assertEqual(kamera._medientyp(JPEG), "image/jpeg")

    def test_fehler(self):
        for schlecht in ("", "   ", "kein base64!!", base64.b64encode(b"GIF89a" + b"0" * 50).decode(),
                         "data:image/jpeg,abc"):
            with self.assertRaises(kamera.KameraFehler, msg=schlecht):
                kamera.bild_pruefen(schlecht)

    def test_zu_gross(self):
        gross = base64.b64encode(b"\xff\xd8\xff" + b"0" * (kamera.MAX_BILD_BYTES + 10)).decode()
        with self.assertRaises(kamera.KameraFehler):
            kamera.bild_pruefen(gross)


class VerlaufPutzen(unittest.TestCase):
    def test_beginnt_mit_user_und_endet_mit_assistant(self):
        v = [{"role": "assistant", "content": "x"}, {"role": "user", "content": "a"},
             {"role": "assistant", "content": "b"}, {"role": "user", "content": "offene Frage"}]
        self.assertEqual([e["role"] for e in kamera.verlauf_putzen(v)], ["user", "assistant"])

    def test_muell_wird_ignoriert(self):
        v = ["text", {"role": "system", "content": "x"}, {"role": "user", "content": ""}, None,
             {"role": "user", "content": "a"}, {"role": "user", "content": "b"}, {"role": "assistant", "content": "c"}]
        out = kamera.verlauf_putzen(v)
        self.assertEqual(out, [{"role": "user", "content": "a\nb"}, {"role": "assistant", "content": "c"}])

    def test_laenge_begrenzt(self):
        v = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)} for i in range(30)]
        self.assertLessEqual(len(kamera.verlauf_putzen(v)), kamera.MAX_VERLAUF)

    def test_none(self):
        self.assertEqual(kamera.verlauf_putzen(None), [])


class Sehen(unittest.TestCase):
    def test_aufruf_mit_bild_und_frage(self):
        s: list = []
        r = kamera.sehen("Was ist das?", "data:image/jpeg;base64," + JPEG, [], aufruf=_fake(s))
        self.assertEqual(r["text"], "Ich sehe ein Kabel, Sir.")
        system, inhalt, kw = s[0]
        self.assertEqual(inhalt[0]["type"], "image")
        self.assertEqual(inhalt[0]["source"]["media_type"], "image/jpeg")
        self.assertEqual(inhalt[0]["source"]["data"], JPEG)
        self.assertEqual(inhalt[1], {"type": "text", "text": "Was ist das?"})
        self.assertEqual(kw["modus"], "kamera")
        self.assertTrue(kw["nur_claude"])
        self.assertLessEqual(kw["max_tokens"], 500)
        self.assertIn("Sir", system)

    def test_leere_frage_beschreibt(self):
        s: list = []
        kamera.sehen("  ", JPEG, aufruf=_fake(s))
        self.assertEqual(s[0][1][1]["text"], kamera.ANLASS_LEER)

    def test_leere_antwort_ist_fehler(self):
        with self.assertRaises(kamera.KameraFehler):
            kamera.sehen("x", JPEG, aufruf=lambda *a, **k: {"text": " "})

    def test_ki_fehler_wird_kamerafehler(self):
        def kaputt(*a, **k):
            raise kamera.ki_aufruf.KiFehler("Monatsrahmen")
        with self.assertRaises(kamera.KameraFehler):
            kamera.sehen("x", JPEG, aufruf=kaputt)


if __name__ == "__main__":
    unittest.main()

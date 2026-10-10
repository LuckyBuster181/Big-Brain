"""
Tests für app/trading_sandbox.py (23.09.2026) - reine Rechnung, keine Broker-
Verbindung, kein Netz.

Start:
    python -m unittest tests.test_trading_sandbox -v
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import trading_sandbox as ts
from app.trading_sandbox import Kerze


def gerade(n=100, start=1.0, schritt=0.0):
    return [Kerze(str(i), start + i * schritt, start + i * schritt + 0.001, start + i * schritt - 0.001,
                  start + i * schritt) for i in range(n)]


class Indikatoren(unittest.TestCase):
    def test_ema_startwert_ist_durchschnitt(self):
        werte = ts.ema([1, 2, 3, 4, 5], 3)
        self.assertEqual(werte[:2], [None, None])
        self.assertAlmostEqual(werte[2], 2.0)
        self.assertAlmostEqual(werte[3], 3.0)  # 4*0.5 + 2*0.5

    def test_ema_zu_kurz(self):
        self.assertEqual(ts.ema([1, 2], 5), [None, None])

    def test_rsi_nur_steigend_ist_100(self):
        self.assertEqual(ts.rsi(list(range(1, 30)), 14)[-1], 100.0)

    def test_rsi_bereich(self):
        werte = [w for w in ts.rsi([k.close for k in ts.demo_kerzen(500)], 14) if w is not None]
        self.assertTrue(all(0 <= w <= 100 for w in werte))

    def test_atr_konstante_spanne(self):
        werte = ts.atr(gerade(40), 14)
        self.assertAlmostEqual(werte[-1], 0.002)
        self.assertIsNone(werte[13])


class CsvLesen(unittest.TestCase):
    ZEILEN = 60

    def test_mt5_export(self):
        kopf = "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
        daten = "".join(f"2024.01.02\t{i:02d}:00:00\t1.1\t1.2\t1.0\t1.15\t100\t0\t5\n" for i in range(self.ZEILEN))
        kerzen = ts.csv_lesen("﻿" + kopf + daten)
        self.assertEqual(len(kerzen), self.ZEILEN)
        self.assertEqual(kerzen[0].zeit, "2024.01.02 00:00:00")
        self.assertEqual((kerzen[0].open, kerzen[0].close), (1.1, 1.15))

    def test_yahoo_mit_null_zeilen(self):
        text = "Date,Open,High,Low,Close,Adj Close,Volume\n"
        text += "".join(f"2024-01-{i % 28 + 1:02d},10,11,9,10.5,10.4,100\n" for i in range(self.ZEILEN))
        text += "2024-02-01,null,null,null,null,null,null\n"
        self.assertEqual(len(ts.csv_lesen(text)), self.ZEILEN)

    def test_semikolon_und_dezimalkomma(self):
        text = "time;open;high;low;close\n" + "".join(f"t{i};1,1;1,2;1,0;1,15\n" for i in range(self.ZEILEN))
        self.assertAlmostEqual(ts.csv_lesen(text)[0].close, 1.15)

    def test_fehlende_spalten(self):
        with self.assertRaises(ts.SandboxFehler):
            ts.csv_lesen("time,preis\n" + "t,1\n" * 60)

    def test_zu_wenige_und_unsinnige_kerzen(self):
        text = "time,open,high,low,close\n" + "t,1,0.5,2,1\n" * 60  # Hoch < Tief
        with self.assertRaises(ts.SandboxFehler):
            ts.csv_lesen(text)
        with self.assertRaises(ts.SandboxFehler):
            ts.csv_lesen("")


class Datenquellen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.trading = Path(self.tmp.name) / "trading"
        self.ablage = Path(self.tmp.name) / "ablage"
        self.patch = mock.patch.dict(os.environ, {"TRADING_DATEN_PATH": str(self.trading), "ABLAGE_PATH": str(self.ablage)})
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_liste_enthaelt_demo_und_csvs(self):
        ts.daten_ordner()
        (self.trading / "EURUSD.csv").write_text("x", encoding="utf-8")
        self.ablage.mkdir(parents=True, exist_ok=True)
        (self.ablage / "DAX.csv").write_text("x", encoding="utf-8")
        (self.ablage / "notiz.md").write_text("x", encoding="utf-8")
        namen = [q["name"] for q in ts.datenquellen()]
        self.assertEqual(namen, ["demo", "trading/EURUSD.csv", "ablage/DAX.csv"])

    def test_pfade_ausserhalb_gesperrt(self):
        for name in ("../geheim.csv", "trading/../../.env", "irgendwo/x.csv", "trading/"):
            with self.subTest(name=name), self.assertRaises(ts.SandboxFehler):
                ts.kerzen_laden(name)

    def test_csv_aus_ablage_backtesten(self):
        self.ablage.mkdir(parents=True, exist_ok=True)
        zeilen = "time,open,high,low,close\n" + "".join(
            f"{k.zeit},{k.open},{k.high},{k.low},{k.close}\n" for k in ts.demo_kerzen(400)
        )
        (self.ablage / "test.csv").write_text(zeilen, encoding="utf-8")
        ergebnis = ts.lauf("ablage/test.csv", "ema_kreuzung")
        self.assertEqual(ergebnis["kerzen"], 400)
        self.assertEqual(ergebnis["datenquelle"], "ablage/test.csv")


class Backtest(unittest.TestCase):
    def _signal_bei(self, index, richtung=1):
        def funktion(kerzen, _p):
            s = [0] * len(kerzen)
            s[index] = richtung
            return s
        return funktion

    def test_einstieg_erst_zur_naechsten_kerze_und_ziel(self):
        kerzen = gerade(60, 1.0, 0.0)
        # Ab Kerze 31 steigt der Kurs kräftig -> Ziel wird erreicht
        for i in range(31, 60):
            k = kerzen[i]
            kerzen[i] = Kerze(k.zeit, 1.0 + (i - 30) * 0.01, 1.0 + (i - 30) * 0.01 + 0.001, 1.0 + (i - 30) * 0.01 - 0.001, 1.0 + (i - 30) * 0.01)
        r = ts.backtest(kerzen, "eigen", risiko={"sl_atr": 1, "tp_atr": 2}, signal_funktion=self._signal_bei(30))
        self.assertEqual(r["gesamt"]["trades"], 1)
        trade = r["trades"][0]
        self.assertEqual(trade["einstieg_zeit"], "31")  # nicht 30: kein Blick in die Zukunft
        self.assertEqual(trade["grund"], "Ziel")
        self.assertGreater(trade["ergebnis"], 0)
        # Risiko 1 % von 10.000 bei Stop-Abstand 1 ATR -> Gewinn bei 2 ATR = 200
        self.assertAlmostEqual(trade["ergebnis"], 200.0, places=0)

    def test_stop_vor_ziel_in_derselben_kerze(self):
        kerzen = gerade(60, 1.0, 0.0)
        k = kerzen[40]
        kerzen[40] = Kerze(k.zeit, 1.0, 1.1, 0.9, 1.0)  # riesige Kerze trifft beides
        r = ts.backtest(kerzen, "eigen", signal_funktion=self._signal_bei(38))
        self.assertEqual(r["trades"][0]["grund"], "Stop")
        self.assertAlmostEqual(r["trades"][0]["ergebnis"], -100.0, places=0)  # genau 1 % Risiko

    def test_spread_kostet(self):
        kerzen = ts.demo_kerzen(800)
        ohne = ts.backtest(kerzen, "ema_kreuzung")
        mit = ts.backtest(kerzen, "ema_kreuzung", risiko={"spread": 0.0002})
        self.assertLess(mit["gesamt"]["gewinn"], ohne["gesamt"]["gewinn"])

    def test_teile_70_30_und_json_tauglich(self):
        r = ts.lauf("demo", "rsi_umkehr")
        self.assertEqual(r["gesamt"]["trades"], r["erster_teil_70"]["trades"] + r["letzter_teil_30"]["trades"])
        self.assertIn("Demo-Daten", r["warnungen"][0])
        json.dumps(r, allow_nan=False)  # kein inf/nan im Ergebnis
        self.assertLessEqual(len(r["kapitalkurve"]), ts.MAX_KURVE_PUNKTE + 2)

    def test_parameter_ueberschreiben(self):
        r = ts.lauf("demo", "ema_kreuzung", parameter={"schnell": 5, "langsam": 10})
        self.assertEqual(r["parameter"], {"schnell": 5, "langsam": 10})

    def test_unzulaessige_eingaben(self):
        kerzen = ts.demo_kerzen(200)
        with self.assertRaises(ts.SandboxFehler):
            ts.backtest(kerzen, "gibtsnicht")
        with self.assertRaises(ts.SandboxFehler):
            ts.backtest(kerzen, "ema_kreuzung", risiko={"risiko_prozent": 25})
        with self.assertRaises(ts.SandboxFehler):
            ts.backtest(kerzen, "ema_kreuzung", risiko={"kapital": 0})

    def test_wenige_trades_warnung(self):
        r = ts.backtest(gerade(100), "eigen", signal_funktion=lambda k, p: [0] * len(k))
        self.assertEqual(r["gesamt"]["trades"], 0)
        self.assertTrue(any("30 Trades" in w for w in r["warnungen"]))

    def test_strategien_liste(self):
        ids = [s["id"] for s in ts.strategien()]
        # seit 23.09.2026 stehen die drei Original-Bots dazwischen (app/trading_bots.py)
        self.assertEqual(ids, ["ema_kreuzung", "rsi_umkehr", "haupt_bot", "david_v2", "divergenz_gold_silber", "_risiko"])

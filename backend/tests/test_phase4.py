"""
Tests für Phase 4 (23.09.2026): Original-Bots im Backtest, Kostenmodell,
Jahres-Tabelle, Zufalls-Vergleich, Marktdaten (Abruf, Speicher, Prüfung),
Paper Trading mit Risiko-Wächter, Markt-Erklärung. Ohne Netz.

Die Soll-Signale in BotsWieOriginal stammen aus den ORIGINAL-strategy.py
(Vault "Wissen/Bots/Orginal Bots", pandas) für dieselben Testkurse - berechnet
am 23.09.2026 in der Cloud-Sandbox. Weicht der Nachbau ab, schlägt der Test an.

Start:
    python -m unittest tests.test_phase4 -v
"""

from __future__ import annotations

import datetime
import json
import math
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from app import markt_analyse, marktdaten, paper_trading, trading_bots as tb, trading_sandbox as ts
from app.trading_sandbox import Kerze


def testkurse(n: int, phase: float = 0.0, basis: float = 100.0) -> list[Kerze]:
    """Feste Kurse (Sinus-Wellen mit leichtem Aufwärtstrend), 4-Stunden-Takt ab 02.01.2023."""
    start = datetime.datetime(2023, 1, 2)

    def wert(i: int) -> float:
        return basis * (1 + 0.08 * math.sin(i / 37 + phase) + 0.0005 * i + 0.012 * math.sin(i / 5.3 + phase)
                        + 0.006 * math.sin(i / 2.1))
    aus = []
    for i in range(n):
        o, c = wert(i - 1), wert(i)
        aus.append(Kerze((start + datetime.timedelta(hours=4 * i)).strftime("%Y-%m-%d %H:%M"), o,
                         max(o, c) * 1.003, min(o, c) * 0.997, c))
    return aus


class BotsWieOriginal(unittest.TestCase):
    def test_haupt_bot(self):
        s = tb.signale_haupt_bot(testkurse(900), tb.BOTS["haupt_bot"]["parameter"])
        self.assertEqual([i for i, x in enumerate(s) if x], [331, 567, 804])
        self.assertAlmostEqual(s[331]["stop"], 1.960176, places=5)
        self.assertAlmostEqual(s[567]["stop"], 2.008256, places=5)

    def test_david_v2_long_und_short(self):
        s = tb.signale_david_v2(testkurse(900), tb.BOTS["david_v2"]["parameter"])
        self.assertEqual([(i, x["richtung"]) for i, x in enumerate(s) if x],
                         [(414, -1), (567, 1), (640, -1), (804, 1), (877, -1)])
        ohne_short = tb.signale_david_v2(testkurse(900), {**tb.BOTS["david_v2"]["parameter"], "trade_short": 0})
        self.assertEqual([i for i, x in enumerate(ohne_short) if x], [567, 804])

    def test_divergenz_mit_silber(self):
        s = tb.signale_divergenz(testkurse(900), tb.BOTS["divergenz_gold_silber"]["parameter"],
                                 testkurse(900, phase=0.9, basis=25.0))
        self.assertEqual([i for i, x in enumerate(s) if x], [340, 574, 807])
        with self.assertRaises(ts.SandboxFehler):
            tb.signale_divergenz(testkurse(300), tb.BOTS["divergenz_gold_silber"]["parameter"], None)

    def test_ewm_wie_pandas(self):
        self.assertEqual(tb.ewm([None, 1.0, 2.0, 3.0], 0.5), [None, 1.0, 1.5, 2.25])
        self.assertEqual(tb.ewm([1.0, 2.0, 3.0], 0.5, 3), [None, None, 2.25])
        self.assertEqual(tb.rsi_haupt([1.0, 1.0, 1.0], 14), [50.0, 50.0, 50.0])  # flach -> 50
        self.assertEqual(tb.rsi_david([1.0] * 20, 14)[-1], 50.0)
        self.assertEqual(tb.rsi_david([float(i) for i in range(20)], 14)[-1], 100.0)

    def test_referenz_ffill(self):
        gold = [Kerze("2024.01.01 00:00", 1, 1, 1, 1), Kerze("2024.01.01 04:00", 1, 1, 1, 1), Kerze("2024.01.01 08:00", 1, 1, 1, 1)]
        silber = [Kerze("2024-01-01 00:00", 5, 5, 5, 5), Kerze("2024-01-01 06:00", 7, 7, 7, 7)]
        self.assertEqual(tb.referenz_ausrichten(gold, silber), [5, 5, 7])


def k(zeit, o, h, l, c):
    return Kerze(zeit, o, h, l, c)


class Simulation(unittest.TestCase):
    P = {"rr": 2.0}
    R = {"kapital": 10000.0, "risiko_prozent": 1.0}

    def test_stop_vor_ziel_in_einer_kerze(self):
        kerzen = [k("2024-01-01 00:00", 100, 100, 100, 100), k("2024-01-01 01:00", 100, 106, 94, 100)]
        trades, _, _ = tb.simulieren(kerzen, [{"richtung": 1, "stop": 5}, None], self.P, self.R)
        self.assertEqual((trades[0]["grund"], trades[0]["r"]), ("Stop", -1.0))

    def test_ziel_gibt_2r_und_kosten_ziehen_ab(self):
        kerzen = [k("2024-01-01 00:00", 100, 100, 100, 100), k("2024-01-01 01:00", 100, 101, 99, 100),
                  k("2024-01-01 02:00", 100, 111, 99, 110)]
        sig = [{"richtung": 1, "stop": 5}, None, None]
        ohne, _, _ = tb.simulieren(kerzen, sig, self.P, self.R)
        self.assertEqual((ohne[0]["grund"], ohne[0]["r"]), ("Ziel", 2.0))
        mit, _, _ = tb.simulieren(kerzen, sig, self.P, {**self.R, "spread": 0.5, "kommission_prozent": 0.01})
        self.assertLess(mit[0]["r"], 2.0)
        self.assertGreater(mit[0]["kosten"], 0)

    def test_gewinn_sichern_david(self):
        # 20 Einheiten Menge (100 Risiko / 5 Abstand): +0,8 % = 80 -> ab +4 Kurs; Stop auf +0,1 % = +0,5
        p = {"rr": 2.0, "gewinn_sichern": 1, "sichern_ab_prozent": 0.8, "sichern_rest_prozent": 0.1}
        kerzen = [k("2024-01-01 00:00", 100, 100, 100, 100), k("2024-01-01 01:00", 100, 104.5, 99.5, 104),
                  k("2024-01-01 02:00", 104, 104, 100, 100.2)]
        trades, _, _ = tb.simulieren(kerzen, [{"richtung": 1, "stop": 5}, None, None], p, self.R)
        self.assertEqual(trades[0]["grund"], "Stop (gesichert)")
        self.assertAlmostEqual(trades[0]["ausstieg"], 100.5, places=4)
        self.assertGreater(trades[0]["r"], 0)

    def test_tageslimit_sperrt_neue_trades(self):
        p = {"rr": 2.0, "tagesverlust_prozent": 1.0}
        kerzen = [k("2024-01-01 00:00", 100, 100, 100, 100), k("2024-01-01 01:00", 100, 100, 94, 95),
                  k("2024-01-01 02:00", 95, 96, 94, 95), k("2024-01-01 03:00", 95, 96, 94, 95)]
        sig = [{"richtung": 1, "stop": 5}, None, {"richtung": 1, "stop": 5}, None]
        trades, _, _ = tb.simulieren(kerzen, sig, p, self.R)
        self.assertEqual(len(trades), 1)  # zweites Signal am selben Tag gesperrt


class BacktestBot(unittest.TestCase):
    def test_ergebnis_mit_jahren_und_zufall(self):
        r = tb.backtest_bot(ts.demo_kerzen(4000, seed=3), "haupt_bot", risiko={"zufall_laeufe": 5})
        for schluessel in ("gesamt", "r_kennzahlen", "jahre", "zufall_urteil", "kapitalkurve", "warnungen"):
            self.assertIn(schluessel, r)
        self.assertTrue(r["bot"])
        self.assertTrue(any("Ohne Kosten" in w for w in r["warnungen"]))
        json.dumps(r)

    def test_ueber_die_sandbox(self):
        r = ts.lauf("demo", "david_v2", {"trade_short": 0}, {"spread": 0.0001, "zufall_laeufe": 3})
        self.assertEqual(r["datenquelle"], "demo")
        self.assertTrue(r["warnungen"][0].startswith("Demo-Daten"))
        with self.assertRaises(ts.SandboxFehler):
            ts.lauf("demo", "divergenz_gold_silber")  # keine Silber-Referenz zu Demo-Daten

    def test_zufall_urteil(self):
        z = {"median_summe_r": 5.0, "p10_summe_r": -2.0, "p90_summe_r": 12.0}
        self.assertIn("90 %", tb.urteil_zufall(20.0, z))
        self.assertIn("nicht belegt", tb.urteil_zufall(7.0, z))
        self.assertIn("Nicht besser", tb.urteil_zufall(1.0, z))

    def test_zu_wenige_kerzen(self):
        with self.assertRaises(ts.SandboxFehler):
            tb.backtest_bot(testkurse(100), "haupt_bot")

    def test_referenz_name(self):
        self.assertEqual(ts.referenz_name("markt/XAUUSD/4h", "XAGUSD"), "markt/XAGUSD/4h")
        self.assertEqual(ts.referenz_name("trading/XAUUSD_H4.csv", "XAGUSD"), "trading/XAGUSD_H4.csv")


# ------------------------------------------------------------- Marktdaten


def yahoo_json(start: int, n: int, schritt: int = 3600, mit_luecke: bool = False) -> bytes:
    zeiten = [start + i * schritt for i in range(n)]
    closes = [100 + i * 0.1 for i in range(n)]
    if mit_luecke:
        closes[3] = None
    return json.dumps({"chart": {"result": [{"timestamp": zeiten, "indicators": {"quote": [{
        "open": closes, "high": [c + 0.5 if c else None for c in closes], "low": [c - 0.5 if c else None for c in closes],
        "close": closes, "volume": [10] * n}]}}], "error": None}}).encode()


class MitDB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"MARKT_DB_PATH": str(Path(self.tmp.name) / "m.db"),
                                         "PAPER_PATH": str(Path(self.tmp.name) / "paper")})
        p.start()
        self.addCleanup(p.stop)


class Marktdaten(MitDB):
    def test_yahoo_lesen_ueberspringt_null(self):
        kerzen = marktdaten.yahoo_lesen(json.loads(yahoo_json(1_700_000_000, 10, mit_luecke=True)))
        self.assertEqual(len(kerzen), 9)
        with self.assertRaises(marktdaten.MarktFehler):
            marktdaten.yahoo_lesen({"chart": {"result": None, "error": {"description": "No data found"}}})

    def test_binance_und_stooq(self):
        b = marktdaten.binance_lesen([[1_700_000_000_000, "1", "2", "0.5", "1.5", "100"]])
        self.assertEqual((b[0]["zeit"], b[0]["close"]), (1_700_000_000, 1.5))
        s = marktdaten.stooq_lesen("Date,Open,High,Low,Close,Volume\n2024-01-02,1,2,0.5,1.5,10\n")
        self.assertEqual(s[0]["close"], 1.5)
        with self.assertRaises(marktdaten.MarktFehler):
            marktdaten.stooq_lesen("Exceeded the daily hits limit")

    def test_aktualisieren_speichert_und_ist_danach_frisch(self):
        aufrufe = []

        def holen(url):
            aufrufe.append(url)
            return yahoo_json(1_700_000_000, 50)
        r = marktdaten.aktualisieren("XAUUSD", "1h", holen=holen)
        self.assertEqual((r["quelle"], r["neu"]), ("yahoo", 50))
        self.assertIn("GC%3DF", aufrufe[0])
        r2 = marktdaten.aktualisieren("XAUUSD", "1h", holen=holen)
        self.assertTrue(r2["frisch"])
        self.assertEqual(len(aufrufe), 1)
        self.assertEqual(len(marktdaten.laden("XAUUSD", "1h")), 50)
        self.assertEqual(marktdaten.letzter_kurs("XAUUSD")["kurs"], 104.9)

    def test_ersatzquelle_bei_fehler(self):
        def holen(url):
            if "yahoo" in url:
                raise OSError("gesperrt")
            return b"Date,Open,High,Low,Close,Volume\n2024-01-02,1,2,0.5,1.5,10\n2024-01-03,1.5,2,1,1.8,10\n"
        r = marktdaten.aktualisieren("EURUSD", "1d", holen=holen)
        self.assertEqual(r["quelle"], "stooq")
        self.assertIn("yahoo", r["fehler_vorher"][0])

    def test_krypto_ueber_binance_mit_seiten(self):
        def holen(url):
            self.assertIn("binance", url)
            ende = 1_700_000_000_000 if "endTime" not in url else int(url.split("endTime=")[1]) + 1
            if "endTime" in url and ende < 1_690_000_000_000:
                return b"[]"
            return json.dumps([[ende - (1000 - i) * 3_600_000, "1", "2", "0.5", "1.5", "1"] for i in range(1000)]).encode()
        r = marktdaten.aktualisieren("BTCUSD", "1h", holen=holen)
        self.assertGreater(r["neu"], 1000)

    def test_4h_aus_1h(self):
        start = 1_704_067_200  # 01.01.2024 00:00 UTC
        kerzen = [{"zeit": start + i * 3600, "open": i, "high": i + 1, "low": i - 1, "close": i + 0.5, "volumen": 1} for i in range(8)]
        vier = marktdaten.zusammenfassen(kerzen, 14400)
        self.assertEqual(len(vier), 2)
        self.assertEqual((vier[0]["open"], vier[0]["high"], vier[0]["low"], vier[0]["close"]), (0, 4, -1, 3.5))

    def test_qualitaet(self):
        start = 1_704_096_000  # Mo 01.01.2024 08:00 UTC
        gut = [{"zeit": start + i * 3600, "open": 100, "high": 101, "low": 99, "close": 100 + (i % 3) * 0.1} for i in range(60)]
        self.assertEqual(marktdaten.qualitaet(gut, "1h", "krypto")["urteil"], "gut")
        luecke = gut[:30] + [dict(x, zeit=x["zeit"] + 50 * 3600) for x in gut[30:]]
        self.assertEqual(marktdaten.qualitaet(luecke, "1h", "krypto")["luecken_anzahl"], 1)
        sprung = [dict(x) for x in gut]
        sprung[40]["close"] = 180
        q = marktdaten.qualitaet(sprung, "1h", "krypto")
        self.assertGreaterEqual(q["ausreisser_anzahl"], 1)
        kaputt = [dict(x) for x in gut]
        kaputt[5]["high"] = 50
        self.assertEqual(marktdaten.qualitaet(kaputt, "1h", "krypto")["urteil"], "prüfen")

    def test_wochenende_keine_luecke(self):
        fr = int(datetime.datetime(2024, 1, 5, 21, tzinfo=datetime.timezone.utc).timestamp())
        mo = int(datetime.datetime(2024, 1, 7, 22, tzinfo=datetime.timezone.utc).timestamp())
        kerzen = [{"zeit": fr, "open": 1, "high": 1, "low": 1, "close": 1}, {"zeit": mo, "open": 1, "high": 1, "low": 1, "close": 1}]
        self.assertEqual(marktdaten.qualitaet(kerzen, "1h", "forex")["luecken_anzahl"], 0)

    def test_sandbox_datenquelle(self):
        marktdaten.aktualisieren("XAUUSD", "1h", holen=lambda url: yahoo_json(1_700_000_000, 300))
        namen = [q["name"] for q in ts.datenquellen()]
        self.assertIn("markt/XAUUSD/1h", namen)
        self.assertIn("markt/XAUUSD/4h", namen)
        self.assertEqual(len(ts.kerzen_laden("markt/XAUUSD/1h")), 300)
        with self.assertRaises(ts.SandboxFehler):
            ts.kerzen_laden("markt/XAGUSD/1h")

    def test_unbekannt(self):
        with self.assertRaises(marktdaten.MarktFehler):
            marktdaten.symbol_pruefen("GME")
        self.assertEqual(marktdaten.intervall_pruefen("H4"), "4h")


# ---------------------------------------------------------- Paper Trading


class Paper(MitDB):
    def kurs_setzen(self, symbol="XAUUSD", kurs=2000.0, zeit=None):
        z = zeit or int(time.time()) - 7200
        marktdaten.speichern(symbol, "1h", [{"zeit": z, "open": kurs, "high": kurs, "low": kurs, "close": kurs}], "test")

    def test_risiko_waechter_lehnt_ab(self):
        self.kurs_setzen()
        ohne_stop = paper_trading.pruefen(paper_trading.laden(), "XAUUSD", 1, 2000, None, 2100, 1.0)
        self.assertFalse(ohne_stop["erlaubt"])
        zu_viel = paper_trading.order("XAUUSD", 1, 1990, 2020, risiko_prozent=2.0)
        self.assertFalse(zu_viel["eroeffnet"])
        self.assertTrue(any("Grenze" in g for g in zu_viel["gruende"]))
        falsche_seite = paper_trading.order("XAUUSD", 1, 2010, 2100)
        self.assertFalse(falsche_seite["eroeffnet"])

    def test_gruppe_metalle_nur_einmal(self):
        self.kurs_setzen("XAUUSD", 2000)
        self.kurs_setzen("XAGUSD", 25)
        self.assertTrue(paper_trading.order("XAUUSD", 1, 1990, 2020)["eroeffnet"])
        zweit = paper_trading.order("XAGUSD", 1, 24.5, 26)
        self.assertFalse(zweit["eroeffnet"])
        self.assertTrue(any("metall" in g for g in zweit["gruende"]))

    def test_order_menge_und_stop_ausloesen(self):
        self.kurs_setzen("XAUUSD", 2000)
        r = paper_trading.order("XAUUSD", 1, 1990, 2020, risiko_prozent=1.0)
        self.assertTrue(r["eroeffnet"])
        self.assertTrue(any("Chance/Risiko" not in w for w in r["warnungen"]) or not r["warnungen"])
        p = r["position"]
        self.assertAlmostEqual(p["menge"], 10.0)  # 100 Risiko / 10 Abstand
        # Kerze NACH dem Einstieg fällt unter den Stop
        marktdaten.speichern("XAUUSD", "1h", [{"zeit": p["zeit_unix"] + 10, "open": 1995, "high": 1996,
                                               "low": 1985, "close": 1988}], "test")
        erg = paper_trading.aktualisieren(kurse_holen=False)
        self.assertEqual(erg["geschlossen"][0]["grund"], "Stop")
        self.assertEqual(erg["stand"]["kontostand"], 9900.0)
        self.assertEqual(erg["stand"]["kennzahlen"]["summe_r"], -1.0)

    def test_von_hand_schliessen_und_zuruecksetzen(self):
        self.kurs_setzen("EURUSD", 1.10)
        pid = paper_trading.order("EURUSD", -1, 1.11, 1.08)["position"]["id"]
        e = paper_trading.schliessen(pid, 1.09)  # Verkauf 1,10 -> 1,09 bei Stop 1,11 = +1 R
        self.assertAlmostEqual(e["r"], 1.0)
        paper_trading.zuruecksetzen(5000)
        self.assertEqual(paper_trading.stand()["kontostand"], 5000)
        self.assertTrue(list(Path(os.environ["PAPER_PATH"]).glob("konto_bis_*.json")))

    def test_bot_signal_nur_einmal(self):
        self.kurs_setzen("XAUUSD", 2000)
        zustand = {"bot": "haupt_bot", "zeit": "2026-09-23 10:00", "signal": {"richtung": 1, "stop": 15.0}}
        kerze = [Kerze("2026-09-23 10:00", 2000, 2001, 1999, 2000)] * 300
        with mock.patch.object(paper_trading, "_geschlossene_kerzen", return_value=kerze), \
                mock.patch.object(tb, "aktueller_zustand", return_value=zustand), \
                mock.patch.object(marktdaten, "aktualisieren"):
            erst = paper_trading.bot_pruefen("haupt_bot", "XAUUSD", "1h")
            zweit = paper_trading.bot_pruefen("haupt_bot", "XAUUSD", "1h")
        self.assertTrue(erst["order"]["eroeffnet"])
        self.assertEqual(erst["order"]["position"]["ziel"], 2030.0)  # 2R
        self.assertIsNone(zweit["order"])
        self.assertIn("schon", zweit["hinweis"])

    def test_regeln(self):
        self.assertEqual(paper_trading.regeln_setzen({"max_positionen": 5})["max_positionen"], 5)
        with self.assertRaises(paper_trading.PaperFehler):
            paper_trading.regeln_setzen({"max_risiko_prozent": 50})


class MarktErklaeren(MitDB):
    def test_zustand_und_frage(self):
        kurse = testkurse(400)
        liste = [{"zeit": 1_700_000_000 + i * 14400, "open": x.open, "high": x.high, "low": x.low, "close": x.close}
                 for i, x in enumerate(kurse)]
        w = markt_analyse.zustand("XAUUSD", "4h", liste)
        self.assertIsNotNone(w["rsi14"])
        self.assertIn("keine Anlageberatung", w["erklaerung"][-1])
        self.assertEqual(len([b for b in w["bots"] if b["bot"] in ("haupt_bot", "david_v2")]), 2)
        self.assertIn("Keine Kaufempfehlung", markt_analyse.frage(w))


if __name__ == "__main__":
    unittest.main()

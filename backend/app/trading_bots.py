"""
Die Original-Bots von Sir im Backtest (Phase 4.4 und 4.6, 23.09.2026).

Quelle: Vault "Wissen/Bots/Orginal Bots" (Community-Release v1.0, Python-Bots
für MetaTrader 5). Nachgebaut wird NUR die Signal-Logik aus den strategy.py-
Dateien - 1:1 mit denselben Formeln wie pandas (ewm mit adjust=False, Wilder-
RSI/ATR, min_periods wie im Original). Kein MT5, keine Orders, kein Echtgeld.

| Bot                    | Regeln (Original-config.py)                                   |
|------------------------|---------------------------------------------------------------|
| haupt_bot              | Long: Schluss über EMA150, RSI14 kreuzt über 35, Stop 2 ATR,  |
|                        | Ziel 2R, 1 % Risiko                                            |
| david_v2               | Long+Short: EMA200 mit Neutralzone 0,25 ATR, RSI 35/65-Kreuz, |
|                        | Stop 1,5 ATR, Ziel 2R, 0,5 % Risiko, Gewinn-Absicherung        |
|                        | 0,8 % -> 0,1 %, Tageslimits -1 % / +5 %                         |
| divergenz_gold_silber  | Long Gold: 20-Kerzen-Renditedifferenz Gold-Silber kreuzt ihr   |
|                        | -1,5-Sigma-Band (100 Kerzen) von unten, Schluss über EMA150,   |
|                        | Stop 2 ATR, Ziel 2R, 1 % Risiko. Braucht Silber als Referenz.   |

Neu gegenüber der bisherigen Sandbox (Feedback "Nachbau 8,7 Jahre Backtest",
Vault, 23.09.2026 - offene Punkte für Claude):
- Kostenmodell: Spread, Kommission und Schlupf (Slippage) je Trade.
- Ergebnis in R (Vielfache des Risikos je Trade) und JAHR FÜR JAHR - eine
  Strategie, die nur in einem Marktregime verdient, fällt so sofort auf.
- Zufalls-Vergleich: gleiche Ausstiege, zufällige Einstiege (Standard 20
  Läufe). Nur was deutlich über der Streuung der Zufallsläufe liegt, ist ein
  echtes Signal und nicht bloß "Markt lief gut".

Vereinfachungen (ehrlich benannt): Einstieg zur Eröffnung der Folgekerze;
Stop und Ziel über Hoch/Tief der Kerze, beides in einer Kerze -> Stop zählt
(vorsichtig). Kein M1-Pfad, keine Swaps. Gewinn in Preis-Einheiten x Menge
(für Vergleiche und R, nicht als Euro-Prognose).
"""

from __future__ import annotations

import math
import random
import re
import statistics
from typing import Any, Callable

from .trading_sandbox import Kerze, SandboxFehler, _kennzahlen, MAX_KURVE_PUNKTE, MAX_TRADES_AUSGABE, TEIL_IN_SAMPLE

ZUFALL_LAEUFE = 20
MAX_ZUFALL_LAEUFE = 50


# ------------------------------------------------------------ Indikatoren
# Wie pandas: Series.ewm(..., adjust=False, min_periods=m).mean()
# (führende NaN werden übersprungen, min_periods zählt gültige Werte)


def ewm(werte: list[float | None], alpha: float, min_periods: int = 0) -> list[float | None]:
    aus: list[float | None] = []
    y = None
    anzahl = 0
    for x in werte:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            aus.append(y if (y is not None and anzahl >= max(min_periods, 1)) else None)
            continue
        anzahl += 1
        y = x if y is None else (1 - alpha) * y + alpha * x
        aus.append(y if anzahl >= max(min_periods, 1) else None)
    return aus


def ema_pd(werte: list[float], laenge: int, min_periods: int = 0) -> list[float | None]:
    return ewm(werte, 2 / (laenge + 1), min_periods)


def _gewinn_verlust(schluss: list[float]) -> tuple[list[float | None], list[float | None]]:
    gewinn: list[float | None] = [None]
    verlust: list[float | None] = [None]
    for i in range(1, len(schluss)):
        d = schluss[i] - schluss[i - 1]
        gewinn.append(max(d, 0.0))
        verlust.append(max(-d, 0.0))
    return gewinn, verlust


def rsi_haupt(schluss: list[float], laenge: int) -> list[float]:
    """RSI wie 1-Haupt-Bot/strategy.py: ohne min_periods, NaN -> 50."""
    g, v = _gewinn_verlust(schluss)
    ag, av = ewm(g, 1 / laenge), ewm(v, 1 / laenge)
    aus = []
    for a, b in zip(ag, av):
        if a is None or b is None or b == 0:
            aus.append(50.0)
        else:
            aus.append(100 - 100 / (1 + a / b))
    return aus


def rsi_david(schluss: list[float], laenge: int) -> list[float | None]:
    """RSI wie 2-David-V2/strategy.py: min_periods=laenge, Sonderfälle flacher Markt."""
    g, v = _gewinn_verlust(schluss)
    ag, av = ewm(g, 1 / laenge, laenge), ewm(v, 1 / laenge, laenge)
    aus: list[float | None] = []
    for a, b in zip(ag, av):
        if a is None or b is None:
            aus.append(None)
        elif b > 0:
            aus.append(100 - 100 / (1 + a / b))
        else:
            aus.append(100.0 if a > 0 else 50.0)
    return aus


def atr_pd(kerzen: list[Kerze], laenge: int, min_periods: int = 0) -> list[float | None]:
    tr: list[float | None] = []
    for i, k in enumerate(kerzen):
        if i == 0:
            tr.append(k.high - k.low)
        else:
            vc = kerzen[i - 1].close
            tr.append(max(k.high - k.low, abs(k.high - vc), abs(k.low - vc)))
    return ewm(tr, 1 / laenge, min_periods)


def _rolling_mean_std(werte: list[float | None], fenster: int) -> tuple[list[float | None], list[float | None]]:
    """rolling(fenster, min_periods=fenster).mean()/.std() (ddof=1) wie pandas."""
    mittel: list[float | None] = []
    abw: list[float | None] = []
    for i in range(len(werte)):
        if i + 1 < fenster:
            mittel.append(None)
            abw.append(None)
            continue
        teil = werte[i + 1 - fenster: i + 1]
        if any(w is None for w in teil):
            mittel.append(None)
            abw.append(None)
            continue
        mittel.append(statistics.fmean(teil))
        abw.append(statistics.stdev(teil))
    return mittel, abw


# ---------------------------------------------------------------- Signale
# Ein Signal gilt am SCHLUSS der Kerze i (wie im Bot: letzte geschlossene
# Kerze). Rückgabe je Kerze: None oder {"richtung": +1/-1, "stop": Abstand}.

Signal = dict[str, float] | None


def signale_haupt_bot(kerzen: list[Kerze], p: dict, referenz: list[Kerze] | None = None) -> list[Signal]:
    schluss = [k.close for k in kerzen]
    trend, rl, al = int(p["trend_len"]), int(p["rsi_len"]), int(p["atr_len"])
    e = ema_pd(schluss, trend)
    r = rsi_haupt(schluss, rl)
    a = atr_pd(kerzen, al)
    noetig = max(trend, rl, al) + 5
    aus: list[Signal] = [None] * len(kerzen)
    for i in range(1, len(kerzen)):
        if i + 1 < noetig or e[i] is None or a[i] is None:
            continue
        if schluss[i] > e[i] and r[i] > p["rsi_oversold"] and r[i - 1] <= p["rsi_oversold"]:
            stop = a[i] * p["atr_stop_mult"]
            if math.isfinite(stop) and stop > 0:
                aus[i] = {"richtung": 1, "stop": stop}
    return aus


def signale_david_v2(kerzen: list[Kerze], p: dict, referenz: list[Kerze] | None = None) -> list[Signal]:
    schluss = [k.close for k in kerzen]
    trend, rl, al = int(p["trend_len"]), int(p["rsi_len"]), int(p["atr_len"])
    e = ema_pd(schluss, trend, trend)
    r = rsi_david(schluss, rl)
    a = atr_pd(kerzen, al, al)
    min_bars = max(trend * 2, rl + 1, al + 1) + 2
    os_, ob = p["rsi_oversold"], 100 - p["rsi_oversold"]
    long_an, short_an = p.get("trade_long", 1) >= 0.5, p.get("trade_short", 1) >= 0.5
    aus: list[Signal] = [None] * len(kerzen)
    for i in range(1, len(kerzen)):
        if i + 1 < min_bars or None in (e[i], r[i], r[i - 1], a[i]):
            continue
        puffer = a[i] * p["trend_buffer_atr"]
        stop = a[i] * p["atr_stop_mult"]
        if stop <= 0:
            continue
        if schluss[i] > e[i] + puffer:
            if long_an and r[i - 1] <= os_ < r[i]:
                aus[i] = {"richtung": 1, "stop": stop}
        elif schluss[i] < e[i] - puffer:
            if short_an and r[i - 1] >= ob > r[i]:
                aus[i] = {"richtung": -1, "stop": stop}
    return aus


def zeit_schluessel(zeit: str) -> str:
    """'2024.01.02 04:00' / '2024-01-02T04:00:00+00:00' -> '2024-01-02 04:00'."""
    z = str(zeit).strip().replace(".", "-").replace("T", " ")
    z = re.sub(r"[+-]\d{2}:?\d{2}$|Z$", "", z)
    return z[:16]


def referenz_ausrichten(kerzen: list[Kerze], referenz: list[Kerze]) -> list[float | None]:
    """Letzter Referenz-Schlusskurs AUF ODER VOR jedem Zeitstempel (wie reindex(method='ffill'))."""
    ref = sorted((zeit_schluessel(k.zeit), k.close) for k in referenz)
    aus: list[float | None] = []
    j, letzter = 0, None
    for k in kerzen:
        z = zeit_schluessel(k.zeit)
        while j < len(ref) and ref[j][0] <= z:
            letzter = ref[j][1]
            j += 1
        aus.append(letzter)
    return aus


def _divergenz_reihen(kerzen: list[Kerze], p: dict, referenz: list[Kerze]) -> tuple[list, list]:
    """Momentum-Differenz d(t) Gold minus Silber und ihr Sigma-Band (wie _diff_und_band im Original)."""
    schluss = [k.close for k in kerzen]
    ret_len, lookback = int(p["ret_len"]), int(p["band_lookback"])
    y = referenz_ausrichten(kerzen, referenz)
    d: list[float | None] = []
    for i in range(len(kerzen)):
        if i < ret_len or y[i] is None or y[i - ret_len] is None or not y[i - ret_len]:
            d.append(None)
            continue
        d.append((schluss[i] / schluss[i - ret_len] - 1) - (y[i] / y[i - ret_len] - 1))
    mittel, abw = _rolling_mean_std(d, lookback)
    band = [None if m is None or s is None else m - p["band_mult"] * s for m, s in zip(mittel, abw)]
    return d, band


def signale_divergenz(kerzen: list[Kerze], p: dict, referenz: list[Kerze] | None = None) -> list[Signal]:
    if not referenz:
        raise SandboxFehler("Der Divergenz-Bot braucht Silber (XAGUSD) als Referenz - "
                            "Kursdaten für Silber im gleichen Zeitrahmen fehlen.")
    schluss = [k.close for k in kerzen]
    ret_len, lookback = int(p["ret_len"]), int(p["band_lookback"])
    trend, al = int(p["trend_len"]), int(p["atr_len"])
    d, band = _divergenz_reihen(kerzen, p, referenz)
    e = ema_pd(schluss, trend)
    a = atr_pd(kerzen, al)
    noetig = max(trend, ret_len + lookback, al) + 5
    aus: list[Signal] = [None] * len(kerzen)
    for i in range(1, len(kerzen)):
        if i + 1 < noetig or None in (d[i], d[i - 1], band[i], band[i - 1]):
            continue
        kreuzung = d[i] > band[i] and d[i - 1] <= band[i - 1]
        if kreuzung and schluss[i] > e[i]:
            stop = a[i] * p["atr_stop_mult"]
            if math.isfinite(stop) and stop > 0:
                aus[i] = {"richtung": 1, "stop": stop}
    return aus


def filter_trend_long(kerzen: list[Kerze], p: dict) -> list[int]:
    """Für den Zufalls-Vergleich: Kerzen über der Trend-EMA (Long-Bots)."""
    schluss = [k.close for k in kerzen]
    e = ema_pd(schluss, int(p["trend_len"]))
    return [1 if e[i] is not None and schluss[i] > e[i] else 0 for i in range(len(kerzen))]


def filter_david(kerzen: list[Kerze], p: dict) -> list[int]:
    schluss = [k.close for k in kerzen]
    e = ema_pd(schluss, int(p["trend_len"]), int(p["trend_len"]))
    a = atr_pd(kerzen, int(p["atr_len"]), int(p["atr_len"]))
    aus = []
    for i in range(len(kerzen)):
        if e[i] is None or a[i] is None:
            aus.append(0)
            continue
        puffer = a[i] * p["trend_buffer_atr"]
        if schluss[i] > e[i] + puffer and p.get("trade_long", 1) >= 0.5:
            aus.append(1)
        elif schluss[i] < e[i] - puffer and p.get("trade_short", 1) >= 0.5:
            aus.append(-1)
        else:
            aus.append(0)
    return aus


BOTS: dict[str, dict[str, Any]] = {
    "haupt_bot": {
        "name": "Haupt-Bot (TrendPullback, Original)",
        "beschreibung": "Long: Schluss über EMA150, RSI14 kreuzt über 35. Stop 2 ATR, Ziel 2R, 1 % Risiko. "
                        "Original-Märkte: Gold/Silber/Platin H1, CHFJPY/USDJPY H4.",
        "parameter": {"trend_len": 150, "rsi_len": 14, "rsi_oversold": 35, "atr_len": 14,
                      "atr_stop_mult": 2.0, "rr": 2.0},
        "risiko": {"risiko_prozent": 1.0},
        "signale": signale_haupt_bot,
        "filter": filter_trend_long,
    },
    "david_v2": {
        "name": "David-V2 (Trend+Pullback, Long und Short, Original)",
        "beschreibung": "EMA200 mit Neutralzone 0,25 ATR, RSI 35/65-Kreuz, Stop 1,5 ATR, Ziel 2R, 0,5 % Risiko, "
                        "Gewinn-Absicherung 0,8 % -> 0,1 %, Tageslimits -1 %/+5 %. trade_short=0 schaltet Short ab.",
        "parameter": {"trend_len": 200, "rsi_len": 14, "rsi_oversold": 35, "trend_buffer_atr": 0.25,
                      "atr_len": 14, "atr_stop_mult": 1.5, "rr": 2.0, "trade_long": 1, "trade_short": 1,
                      "gewinn_sichern": 1, "sichern_ab_prozent": 0.8, "sichern_rest_prozent": 0.1,
                      "tagesverlust_prozent": 1.0, "tagesgewinn_prozent": 5.0},
        "risiko": {"risiko_prozent": 0.5},
        "signale": signale_david_v2,
        "filter": filter_david,
    },
    "divergenz_gold_silber": {
        "name": "Divergenz Gold/Silber (Original)",
        "beschreibung": "Long Gold, wenn die 20-Kerzen-Renditedifferenz Gold minus Silber ihr -1,5-Sigma-Band "
                        "(100 Kerzen) von unten kreuzt und Gold über der EMA150 liegt. Stop 2 ATR, Ziel 2R, "
                        "1 % Risiko. Braucht Silber-Kurse im gleichen Zeitrahmen.",
        "parameter": {"trend_len": 150, "atr_len": 14, "atr_stop_mult": 2.0, "rr": 2.0,
                      "ret_len": 20, "band_lookback": 100, "band_mult": 1.5},
        "risiko": {"risiko_prozent": 1.0},
        "signale": signale_divergenz,
        "filter": filter_trend_long,
        "referenz": "XAGUSD",
    },
}

STANDARD_KOSTEN = {"kapital": 10000.0, "risiko_prozent": 1.0, "spread": 0.0, "kommission_prozent": 0.0,
                   "schlupf": 0.0, "zufall_laeufe": ZUFALL_LAEUFE}


def bots() -> list[dict]:
    return [{"id": bid, "name": b["name"], "beschreibung": b["beschreibung"], "parameter": dict(b["parameter"]),
             "risiko": {**STANDARD_KOSTEN, **b["risiko"]}, "referenz": b.get("referenz"), "bot": True}
            for bid, b in BOTS.items()]


# ------------------------------------------------------------ Simulation


def simulieren(kerzen: list[Kerze], signale: list[Signal], p: dict, r: dict) -> tuple[list[dict], list, bool]:
    """Ein Durchlauf. Rückgabe: Trades, Kapitalkurve, am Ende noch offen?"""
    kapital = float(r["kapital"])
    risiko = float(r["risiko_prozent"]) / 100
    spread, kom, schlupf = float(r.get("spread", 0)), float(r.get("kommission_prozent", 0)) / 100, float(r.get("schlupf", 0))
    rr = float(p.get("rr", 2.0))
    sichern = p.get("gewinn_sichern", 0) >= 0.5
    ab, rest = float(p.get("sichern_ab_prozent", 0)) / 100, float(p.get("sichern_rest_prozent", 0)) / 100
    tagesverlust, tagesgewinn = float(p.get("tagesverlust_prozent", 0)), float(p.get("tagesgewinn_prozent", 0))
    trades: list[dict] = []
    kurve: list[tuple[str, float]] = [(kerzen[0].zeit, kapital)]
    offen: dict | None = None
    tag, tag_start, gesperrt = None, kapital, False

    def schliessen(i: int, preis: float, grund: str) -> None:
        nonlocal kapital, offen
        o = offen
        brutto = (preis - o["einstieg"]) * o["richtung"] * o["menge"]
        kosten = spread * o["menge"] + kom * (o["einstieg"] + preis) * o["menge"]
        ergebnis = brutto - kosten
        kapital += ergebnis
        trades.append({
            "einstieg_zeit": o["zeit"], "ausstieg_zeit": kerzen[i].zeit,
            "richtung": "kauf" if o["richtung"] == 1 else "verkauf",
            "einstieg": round(o["einstieg"], 6), "ausstieg": round(preis, 6), "grund": grund,
            "ergebnis": round(ergebnis, 2), "r": round(ergebnis / o["risiko_betrag"], 3) if o["risiko_betrag"] else 0.0,
            "kosten": round(kosten, 2), "index": i, "jahr": zeit_schluessel(kerzen[i].zeit)[:4],
            "gesichert": o.get("gesichert", False),
        })
        kurve.append((kerzen[i].zeit, kapital))
        offen = None

    def pruefe_ausstieg(i: int) -> None:
        k = kerzen[i]
        o = offen
        if o["richtung"] == 1:
            stop_hit, ziel_hit = k.low <= o["stop"], k.high >= o["ziel"]
        else:
            stop_hit, ziel_hit = k.high >= o["stop"], k.low <= o["ziel"]
        if stop_hit:  # vorsichtig: Stop vor Ziel
            preis = min(o["stop"], k.open) if o["richtung"] == 1 else max(o["stop"], k.open)  # Kurslücke
            schliessen(i, preis - schlupf * o["richtung"], "Stop" if not o.get("gesichert") else "Stop (gesichert)")
        elif ziel_hit:
            schliessen(i, o["ziel"], "Ziel")

    def gewinn_sichern(i: int) -> None:
        """Gewinn-Absicherung (David-V2): ab X % Buchgewinn Stop auf +Y % ziehen.
        Erst NACH der Stop/Ziel-Prüfung der Kerze (vorsichtig), wirkt ab der nächsten."""
        if not (offen and sichern) or offen.get("gesichert"):
            return
        k = kerzen[i]
        bestes = (k.high - offen["einstieg"]) if offen["richtung"] == 1 else (offen["einstieg"] - k.low)
        if bestes * offen["menge"] >= kapital * ab:
            neuer = offen["einstieg"] + offen["richtung"] * (kapital * rest / offen["menge"])
            if (offen["richtung"] == 1 and neuer < k.close) or (offen["richtung"] == -1 and neuer > k.close):
                offen["stop"], offen["gesichert"] = neuer, True

    for i in range(1, len(kerzen)):
        k = kerzen[i]
        heute = zeit_schluessel(k.zeit)[:10]
        if heute != tag:
            tag, tag_start, gesperrt = heute, kapital, False
        if offen:
            pruefe_ausstieg(i)
            gewinn_sichern(i)
        if tagesverlust or tagesgewinn:
            veraenderung = (kapital - tag_start) / tag_start * 100 if tag_start > 0 else 0
            if (tagesverlust and veraenderung <= -tagesverlust) or (tagesgewinn and veraenderung >= tagesgewinn):
                gesperrt = True
        sig = signale[i - 1]
        if offen is None and sig and not gesperrt and kapital > 0:
            richtung = int(sig["richtung"])
            einstieg = k.open + schlupf * richtung
            abstand = float(sig["stop"])
            risiko_betrag = kapital * risiko
            menge = risiko_betrag / abstand
            offen = {"richtung": richtung, "einstieg": einstieg, "zeit": k.zeit, "menge": menge,
                     "stop": einstieg - richtung * abstand, "ziel": einstieg + richtung * abstand * rr,
                     "risiko_betrag": risiko_betrag}
            pruefe_ausstieg(i)  # Stop/Ziel schon in der Einstiegskerze
            gewinn_sichern(i)
    return trades, kurve, offen is not None


def _r_kennzahlen(trades: list[dict]) -> dict:
    rs = [t["r"] for t in trades]
    gewinne = sum(x for x in rs if x > 0)
    verluste = -sum(x for x in rs if x <= 0)
    # größter Rückgang in R (auf der Summe)
    summe = spitze = 0.0
    max_dd = 0.0
    for x in rs:
        summe += x
        spitze = max(spitze, summe)
        max_dd = max(max_dd, spitze - summe)
    return {
        "summe_r": round(sum(rs), 2),
        "schnitt_r": round(sum(rs) / len(rs), 3) if rs else 0.0,
        "profit_faktor_r": round(gewinne / verluste, 2) if verluste > 0 else None,
        "max_rueckgang_r": round(max_dd, 2),
        "kosten_summe": round(sum(t.get("kosten", 0) for t in trades), 2),
    }


def jahre(trades: list[dict], start_kapital: float) -> list[dict]:
    """Jahr für Jahr: Trades, R, Gewinn, Trefferquote, Profit-Faktor."""
    tabelle = []
    kapital = start_kapital
    for jahr in sorted({t["jahr"] for t in trades}):
        teil = [t for t in trades if t["jahr"] == jahr]
        k = _kennzahlen(teil, kapital)
        kapital += sum(t["ergebnis"] for t in teil)
        rk = _r_kennzahlen(teil)
        tabelle.append({"jahr": jahr, "trades": k["trades"], "summe_r": rk["summe_r"],
                        "gewinn": k["gewinn"], "gewinn_prozent": k["gewinn_prozent"],
                        "trefferquote_prozent": k["trefferquote_prozent"], "profit_faktor": k["profit_faktor"],
                        "max_drawdown_prozent": k["max_drawdown_prozent"]})
    return tabelle


def zufalls_vergleich(kerzen: list[Kerze], filter_werte: list[int], anzahl_trades: int, signale: list[Signal],
                      p: dict, r: dict, laeufe: int, seed: int = 7) -> dict | None:
    """Gleiche Ausstiege, zufällige Einstiege auf erlaubten Kerzen (z.B. über der EMA).

    Jede erlaubte Kerze wird mit Wahrscheinlichkeit q zum Einstieg; q wird so
    eingestellt, dass etwa so viele Trades entstehen wie bei der Strategie.
    Nicht abgeschnitten - die Zufalls-Trades verteilen sich über den ganzen
    Zeitraum wie die echten."""
    if anzahl_trades < 5 or laeufe <= 0:
        return None
    atr_grob = atr_pd(kerzen, int(p.get("atr_len", 14)))
    mult = float(p.get("atr_stop_mult", 2.0))
    erlaubt = [i for i, f in enumerate(filter_werte) if f != 0 and atr_grob[i]]
    if len(erlaubt) < anzahl_trades:
        return None
    zufall = random.Random(seed)

    def lauf(q: float) -> list[dict]:
        sig: list[Signal] = [None] * len(kerzen)
        for i in erlaubt:
            if zufall.random() < q:
                sig[i] = {"richtung": filter_werte[i], "stop": atr_grob[i] * mult}
        return simulieren(kerzen, sig, p, r)[0]

    q = min(1.0, anzahl_trades / len(erlaubt))
    for _ in range(3):  # q einstellen
        n = len(lauf(q))
        if n == 0:
            q = min(1.0, q * 4)
            continue
        if abs(n - anzahl_trades) <= max(2, anzahl_trades * 0.1):
            break
        q = min(1.0, q * anzahl_trades / n)
    ergebnisse = []
    for _ in range(min(laeufe, MAX_ZUFALL_LAEUFE)):
        t = lauf(q)
        rk = _r_kennzahlen(t)
        ergebnisse.append((rk["summe_r"], rk["profit_faktor_r"] or 0.0, len(t)))
    summen = sorted(e[0] for e in ergebnisse)

    def quantil(qq: float) -> float:
        pos = qq * (len(summen) - 1)
        u, o = math.floor(pos), math.ceil(pos)
        return summen[u] + (summen[o] - summen[u]) * (pos - u)

    return {
        "laeufe": len(ergebnisse),
        "trades_je_lauf": round(statistics.fmean(e[2] for e in ergebnisse), 1),
        "median_summe_r": round(statistics.median(summen), 2),
        "p10_summe_r": round(quantil(0.1), 2),
        "p90_summe_r": round(quantil(0.9), 2),
        "min_summe_r": round(summen[0], 2),
        "max_summe_r": round(summen[-1], 2),
        "median_profit_faktor": round(statistics.median(e[1] for e in ergebnisse), 2),
    }


def _r(x: float) -> str:
    return f"{x:+.1f}".replace(".", ",")


def urteil_zufall(strategie_r: float, z: dict | None) -> str:
    if not z:
        return "Kein Zufalls-Vergleich (zu wenige Trades oder Kerzen)."
    if strategie_r > z["p90_summe_r"]:
        return (f"Besser als 90 % der Zufallsläufe ({_r(strategie_r)} R gegen Median {_r(z['median_summe_r'])} R) - "
                "Hinweis auf ein echtes Signal, aber noch kein Beweis.")
    if strategie_r > z["median_summe_r"]:
        return (f"Über dem Median der Zufallsläufe ({_r(z['median_summe_r'])} R), aber innerhalb der Streuung "
                f"({_r(z['p10_summe_r'])} bis {_r(z['p90_summe_r'])} R) - das Signal ist nicht belegt.")
    return (f"Nicht besser als zufällige Einstiege (Median {_r(z['median_summe_r'])} R) - der Gewinn/Verlust kommt "
            "vom Markt und den Ausstiegen, nicht vom Signal.")


def backtest_bot(kerzen: list[Kerze], bot: str, parameter: dict | None = None, risiko: dict | None = None,
                 referenz: list[Kerze] | None = None) -> dict:
    if bot not in BOTS:
        raise SandboxFehler(f'Unbekannter Bot "{bot}" - erlaubt: {", ".join(BOTS)}')
    b = BOTS[bot]
    p = {**b["parameter"], **(parameter or {})}
    r = {**STANDARD_KOSTEN, **b["risiko"], **(risiko or {})}
    if float(r["risiko_prozent"]) <= 0 or float(r["risiko_prozent"]) > 10:
        raise SandboxFehler("Risiko pro Trade muss zwischen 0 und 10 % liegen.")
    if float(r["kapital"]) <= 0:
        raise SandboxFehler("Kapital muss größer als 0 sein.")
    if len(kerzen) < 250:
        raise SandboxFehler(f"Zu wenige Kerzen ({len(kerzen)}) - die Bots brauchen mindestens 250 (EMA-Anlauf).")

    signale = b["signale"](kerzen, p, referenz)
    trades, kurve, noch_offen = simulieren(kerzen, signale, p, r)
    start = float(r["kapital"])
    grenze = int(len(kerzen) * TEIL_IN_SAMPLE)
    teil1 = [t for t in trades if t["index"] < grenze]
    teil2 = [t for t in trades if t["index"] >= grenze]
    gesamt = _kennzahlen(trades, start)
    rk = _r_kennzahlen(trades)
    z = zufalls_vergleich(kerzen, b["filter"](kerzen, p), len(trades), signale, p, r, int(r.get("zufall_laeufe", ZUFALL_LAEUFE)))
    jahrestabelle = jahre(trades, start)

    warnungen = []
    if gesamt["trades"] < 30:
        warnungen.append("Weniger als 30 Trades - statistisch kaum aussagekräftig.")
    if len(jahrestabelle) >= 2:
        negativ = [j["jahr"] for j in jahrestabelle if j["summe_r"] < 0]
        if negativ and len(negativ) >= len(jahrestabelle) / 2:
            warnungen.append(f"In {len(negativ)} von {len(jahrestabelle)} Jahren im Minus ({', '.join(negativ)}) - "
                             "Verdacht: verdient nur in einem Marktregime.")
    k1, k2 = _kennzahlen(teil1, start), _kennzahlen(teil2, start + sum(t["ergebnis"] for t in teil1))
    if k1["trades"] and k2["trades"] and k1["gewinn_prozent"] > 0 >= k2["gewinn_prozent"]:
        warnungen.append("Gewinn nur im ersten Teil, Verlust im letzten Teil - Verdacht auf Überanpassung.")
    if not any(float(r.get(x, 0)) for x in ("spread", "kommission_prozent", "schlupf")):
        warnungen.append("Ohne Kosten gerechnet (Spread, Kommission, Schlupf = 0) - echte Ergebnisse sind schlechter.")
    if noch_offen:
        warnungen.append("Am Datenende war noch eine Position offen - nicht mitgezählt.")

    schritt = max(1, len(kurve) // MAX_KURVE_PUNKTE)
    kurve_klein = kurve[::schritt]
    if kurve_klein[-1] != kurve[-1]:
        kurve_klein.append(kurve[-1])
    for t in trades:
        t.pop("index", None)
    return {
        "strategie": bot,
        "strategie_name": b["name"],
        "bot": True,
        "parameter": p,
        "risiko": r,
        "kerzen": len(kerzen),
        "zeitraum": {"von": kerzen[0].zeit, "bis": kerzen[-1].zeit},
        "gesamt": gesamt,
        "r_kennzahlen": rk,
        "erster_teil_70": k1,
        "letzter_teil_30": k2,
        "jahre": jahrestabelle,
        "zufall": z,
        "zufall_urteil": urteil_zufall(rk["summe_r"], z),
        "endkapital": round(start + sum(t["ergebnis"] for t in trades), 2),
        "kapitalkurve": [{"zeit": zt, "kapital": round(c, 2)} for zt, c in kurve_klein],
        "trades": trades[-MAX_TRADES_AUSGABE:],
        "signale_gesamt": sum(1 for s in signale if s),
        "warnungen": warnungen,
        "hinweis": "Nachbau der Signal-Logik aus den Original-strategy.py (Vault, Orginal Bots). Backtest mit "
                   "Vereinfachungen - kein Gewinnversprechen, kein Echtgeld, keine MT5-Verbindung.",
    }


def aktueller_zustand(kerzen: list[Kerze], bot: str, referenz: list[Kerze] | None = None,
                      parameter: dict | None = None) -> dict:
    """Wie market_status() im Bot: Trend, RSI, Abstand zum Signal - und ob die
    letzte geschlossene Kerze ein Signal ist."""
    b = BOTS[bot]
    p = {**b["parameter"], **(parameter or {})}
    if len(kerzen) < 250:
        return {"bot": bot, "bereit": False, "hinweis": "zu wenige Kerzen"}
    signale = b["signale"](kerzen, p, referenz)
    schluss = [k.close for k in kerzen]
    zustand: dict[str, Any] = {"bot": bot, "name": b["name"], "zeit": kerzen[-1].zeit,
                               "signal": signale[-1], "letztes_signal": None}
    for i in range(len(signale) - 1, -1, -1):
        if signale[i]:
            zustand["letztes_signal"] = {"zeit": kerzen[i].zeit, **signale[i]}
            break
    if bot == "haupt_bot":
        # wie market_status() in 1-Haupt-Bot/strategy.py
        e = ema_pd(schluss, int(p["trend_len"]))[-1]
        r = rsi_haupt(schluss, int(p["rsi_len"]))[-1]
        zustand.update({"ema": e, "rsi": r, "ueber_ema": e is not None and schluss[-1] > e,
                        "rsi_bis_signal": round(r - p["rsi_oversold"], 1)})
        zustand["bereit"] = bool(zustand["ueber_ema"] and r <= p["rsi_oversold"] + 5)
    elif bot == "david_v2":
        # wie market_status() in 2-David-V2/strategy.py (mit Neutralzone, Long und Short)
        trend = int(p["trend_len"])
        e = ema_pd(schluss, trend, trend)[-1]
        r = rsi_david(schluss, int(p["rsi_len"]))[-1]
        a = atr_pd(kerzen, int(p["atr_len"]), int(p["atr_len"]))[-1]
        richtung, bereit = "keine", False
        if None not in (e, r, a):
            puffer = a * p["trend_buffer_atr"]
            if schluss[-1] > e + puffer and p.get("trade_long", 1) >= 0.5:
                richtung, bereit = "long", r <= p["rsi_oversold"]
            elif schluss[-1] < e - puffer and p.get("trade_short", 1) >= 0.5:
                richtung, bereit = "short", r >= 100 - p["rsi_oversold"]
        zustand.update({"ema": e, "rsi": r, "ueber_ema": e is not None and schluss[-1] > e, "richtung": richtung,
                        "bereit": bool(bereit)})
    else:
        # wie market_status() in 3-Divergenz-Gold-Silber/strategy.py
        e = ema_pd(schluss, int(p["trend_len"]))[-1]
        d, band = _divergenz_reihen(kerzen, p, referenz) if referenz else (None, None)
        unter = bool(d and band and d[-1] is not None and band[-1] is not None and d[-1] <= band[-1])
        zustand.update({"ema": e, "ueber_ema": schluss[-1] > (e or 0), "unter_band": unter,
                        "d": d[-1] if d else None, "band": band[-1] if band else None})
        zustand["bereit"] = bool(zustand["ueber_ema"] and unter)
    return zustand

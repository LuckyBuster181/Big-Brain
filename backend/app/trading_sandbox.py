"""
Trading-Sandbox (23.09.2026, Wunsch von Sir: "ein Sandbox-Platz, um die
KI-Trading-Bots zu testen"): Strategien auf HISTORISCHEN Kursdaten
durchrechnen (Backtest) - ohne Broker, ohne MT5-Verbindung, ohne Echtgeld,
ohne Claude-Aufruf (kostet also nichts außer etwas Rechenzeit).

Was gebaut ist:
- Kursdaten als CSV: MT5-Export (Tab-getrennt, <DATE> <TIME> <OPEN> ...),
  Yahoo-/yfinance-Format (Date,Open,High,Low,Close) oder schlicht
  time,open,high,low,close. Die CSV legt Sir in die Datei-Ablage (HUD) oder
  nach data/trading. Zusätzlich "demo": künstliche Zufallskurse, nur um die
  Sandbox selbst auszuprobieren - KEINE echten Marktdaten.
- Strategien mit den Bausteinen der David-Bots (EMA, RSI, ATR, siehe Vault
  "00 - Trading-Bots und Dashboard"): EMA-Kreuzung und RSI-Umkehr, jeweils mit
  Stop-Loss/Take-Profit als Vielfaches der ATR und Positionsgröße nach Risiko
  in Prozent vom Konto.
- Kennzahlen: Trades, Trefferquote, Gewinn, Profit-Faktor, größter Rückgang
  (Drawdown), Kapitalkurve - zusätzlich getrennt für die ersten 70 % und die
  letzten 30 % der Daten. Sieht eine Strategie nur im ersten Teil gut aus, ist
  sie vermutlich an die Vergangenheit angepasst (Überanpassung).

Vereinfachungen (bewusst, ehrlich benannt - ein Backtest ist KEIN Gewinnbeweis):
- Einstieg zum Eröffnungskurs der NÄCHSTEN Kerze nach dem Signal (kein Blick
  in die Zukunft). Stop und Ziel werden über Hoch/Tief der Kerze geprüft;
  werden beide in derselben Kerze berührt, zählt vorsichtig der Stop.
- Spread als fester Abzug je Trade in Preis-Einheiten; keine Kommission, kein
  Swap, kein Schlupf (Slippage) - echte Ergebnisse sind schlechter.
- Gewinn in "Preis-Einheiten x Menge": für Währungspaare ohne Kontraktgröße
  und Kontowährung. Die Kennzahlen taugen zum VERGLEICH von Strategien, nicht
  als Euro-Prognose.
- Eine Position gleichzeitig, kein Pyramidisieren.

Noch NICHT gebaut: die echten David-Bots selbst einhängen. Deren Quellcode
liegt nicht in den verbundenen Ordnern (nur die Markdown-Doku im Vault) - dafür
muss Sir sagen, wo der Bot-Ordner liegt. Die Bausteine hier sind so gewählt,
dass die David-Logik (EMA/RSI/ATR) sich später als eigene Strategie ergänzen lässt.
"""

from __future__ import annotations

import csv
import datetime
import io
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import ablage

MAX_KERZEN = int(os.getenv("TRADING_MAX_KERZEN", "200000"))
MAX_KURVE_PUNKTE = 300
MAX_TRADES_AUSGABE = 200
TEIL_IN_SAMPLE = 0.7


class SandboxFehler(ValueError):
    pass


@dataclass
class Kerze:
    zeit: str
    open: float
    high: float
    low: float
    close: float


# ------------------------------------------------------------------ Daten


def daten_ordner() -> Path:
    pfad = Path(os.getenv("TRADING_DATEN_PATH") or Path(__file__).resolve().parents[2] / "data" / "trading")
    pfad.mkdir(parents=True, exist_ok=True)
    return pfad


def datenquellen() -> list[dict]:
    """CSV-Dateien aus data/trading und der Datei-Ablage, gespeicherte Marktdaten
    (Phase 4.1, "markt/XAUUSD/1h") plus die Demo-Daten."""
    quellen = [{"name": "demo", "ort": "eingebaut", "hinweis": "künstliche Zufallskurse, keine Marktdaten"}]
    try:
        from . import marktdaten  # erst hier: marktdaten importiert dieses Modul
        quellen.extend(marktdaten.datenquellen())
    except Exception as exc:  # noqa: BLE001 - ohne Marktdaten-DB geht die Sandbox trotzdem
        print(f"[Sandbox] Marktdaten nicht lesbar: {exc}", flush=True)
    for ort, ordner in (("trading", daten_ordner()), ("ablage", ablage.ordner())):
        for pfad in sorted(ordner.glob("*.csv")):
            quellen.append({"name": f"{ort}/{pfad.name}", "ort": ort, "bytes": pfad.stat().st_size})
    return quellen


def _pfad_zu(name: str) -> Path:
    ort, _, datei = (name or "").partition("/")
    ordner = {"trading": daten_ordner(), "ablage": ablage.ordner()}.get(ort)
    if ordner is None or not datei:
        raise SandboxFehler(f'Unbekannte Datenquelle "{name}" - erwartet z.B. "ablage/EURUSD_H1.csv".')
    pfad = ordner / Path(datei).name  # nur Dateiname, keine Pfade
    if not pfad.is_file():
        raise SandboxFehler(f'Datei "{name}" nicht gefunden.')
    return pfad


def _zahl(text: str) -> float:
    return float(str(text).strip().replace(",", "."))


_SPALTEN = {
    "date": "datum", "<date>": "datum", "datum": "datum",
    "time": "zeit", "<time>": "zeit", "zeit": "zeit", "datetime": "zeit", "timestamp": "zeit",
    "open": "open", "<open>": "open", "eröffnung": "open",
    "high": "high", "<high>": "high", "hoch": "high",
    "low": "low", "<low>": "low", "tief": "low",
    "close": "close", "<close>": "close", "schluss": "close", "adj close": None,
}


def csv_lesen(text: str) -> list[Kerze]:
    """Liest MT5-, Yahoo- oder einfache OHLC-CSVs. Trennzeichen wird erkannt."""
    text = text.lstrip("﻿")
    probe = text[:4096]
    try:
        trenner = csv.Sniffer().sniff(probe, delimiters=",;\t").delimiter
    except csv.Error:
        trenner = "\t" if "\t" in probe else ","
    leser = csv.reader(io.StringIO(text), delimiter=trenner)
    kopf = next(leser, None)
    if not kopf:
        raise SandboxFehler("Die CSV ist leer.")
    index: dict[str, int] = {}
    for i, spalte in enumerate(kopf):
        ziel = _SPALTEN.get(spalte.strip().lower())
        if ziel and ziel not in index:
            index[ziel] = i
    fehlend = [s for s in ("open", "high", "low", "close") if s not in index]
    if fehlend:
        raise SandboxFehler(f"Spalten fehlen: {', '.join(fehlend)} (Kopfzeile: {', '.join(kopf)})")

    kerzen: list[Kerze] = []
    for zeile in leser:
        if not zeile or all(not z.strip() for z in zeile):
            continue
        try:
            teile = [zeile[index[k]].strip() for k in ("datum", "zeit") if k in index]
            kerze = Kerze(
                zeit=" ".join(teile),
                open=_zahl(zeile[index["open"]]),
                high=_zahl(zeile[index["high"]]),
                low=_zahl(zeile[index["low"]]),
                close=_zahl(zeile[index["close"]]),
            )
        except (IndexError, ValueError):
            continue  # kaputte Zeile (z.B. "null" bei Yahoo an Feiertagen)
        if min(kerze.open, kerze.high, kerze.low, kerze.close) <= 0 or kerze.high < kerze.low:
            continue
        kerzen.append(kerze)
        if len(kerzen) >= MAX_KERZEN:
            break
    if len(kerzen) < 50:
        raise SandboxFehler(f"Zu wenige gültige Kerzen ({len(kerzen)}) - mindestens 50 nötig.")
    return kerzen


def demo_kerzen(anzahl: int = 3000, seed: int = 42) -> list[Kerze]:
    """Künstlicher Kursverlauf (Zufallsweg mit leichten Trendphasen) - nur zum
    Ausprobieren der Sandbox, sagt nichts über echte Märkte."""
    zufall = random.Random(seed)
    preis = 1.1000
    trend = 0.0
    start = datetime.datetime(2025, 1, 1)
    kerzen = []
    for i in range(anzahl):
        if i % 200 == 0:
            trend = zufall.uniform(-0.00008, 0.00008)
        eroeffnung = preis
        schluss = max(0.01, eroeffnung + trend + zufall.gauss(0, 0.0012))
        hoch = max(eroeffnung, schluss) + abs(zufall.gauss(0, 0.0005))
        tief = min(eroeffnung, schluss) - abs(zufall.gauss(0, 0.0005))
        kerzen.append(Kerze((start + datetime.timedelta(hours=i)).isoformat(sep=" "), eroeffnung, hoch, tief, schluss))
        preis = schluss
    return kerzen


def kerzen_laden(name: str) -> list[Kerze]:
    if name == "demo":
        return demo_kerzen()
    if name.startswith("markt/"):
        from . import marktdaten
        _, symbol, intervall = (name.split("/") + ["", ""])[:3]
        return marktdaten.als_sandbox_kerzen(symbol, intervall)
    return csv_lesen(_pfad_zu(name).read_text(encoding="utf-8", errors="replace"))


def referenz_name(name: str, referenz_symbol: str) -> str:
    """Passende Referenz-Datenquelle (z.B. Silber zu Gold) im gleichen Zeitrahmen."""
    if name.startswith("markt/"):
        _, _, intervall = (name.split("/") + ["", ""])[:3]
        return f"markt/{referenz_symbol}/{intervall}"
    ort, _, datei = name.partition("/")
    for alt, neu in (("XAUUSD", "XAGUSD"), ("xauusd", "xagusd"), ("XAU", "XAG"), ("GOLD", "SILVER"), ("Gold", "Silber")):
        if alt in datei:
            return f"{ort}/{datei.replace(alt, neu, 1)}"
    raise SandboxFehler(f"Zu {name} finde ich keine Silber-Datei - erwartet z.B. XAGUSD_H4.csv neben XAUUSD_H4.csv.")


# ------------------------------------------------------------- Indikatoren


def ema(werte: list[float], periode: int) -> list[float | None]:
    ergebnis: list[float | None] = [None] * len(werte)
    if periode < 1 or len(werte) < periode:
        return ergebnis
    k = 2 / (periode + 1)
    wert = sum(werte[:periode]) / periode
    ergebnis[periode - 1] = wert
    for i in range(periode, len(werte)):
        wert = werte[i] * k + wert * (1 - k)
        ergebnis[i] = wert
    return ergebnis


def rsi(werte: list[float], periode: int = 14) -> list[float | None]:
    """RSI nach Wilder."""
    ergebnis: list[float | None] = [None] * len(werte)
    if len(werte) <= periode:
        return ergebnis
    gewinne = verluste = 0.0
    for i in range(1, periode + 1):
        d = werte[i] - werte[i - 1]
        gewinne += max(d, 0)
        verluste += max(-d, 0)
    gewinne /= periode
    verluste /= periode
    ergebnis[periode] = 100.0 if verluste == 0 else 100 - 100 / (1 + gewinne / verluste)
    for i in range(periode + 1, len(werte)):
        d = werte[i] - werte[i - 1]
        gewinne = (gewinne * (periode - 1) + max(d, 0)) / periode
        verluste = (verluste * (periode - 1) + max(-d, 0)) / periode
        ergebnis[i] = 100.0 if verluste == 0 else 100 - 100 / (1 + gewinne / verluste)
    return ergebnis


def atr(kerzen: list[Kerze], periode: int = 14) -> list[float | None]:
    """ATR nach Wilder."""
    ergebnis: list[float | None] = [None] * len(kerzen)
    if len(kerzen) <= periode:
        return ergebnis
    tr = [kerzen[0].high - kerzen[0].low]
    for i in range(1, len(kerzen)):
        k, vorher = kerzen[i], kerzen[i - 1].close
        tr.append(max(k.high - k.low, abs(k.high - vorher), abs(k.low - vorher)))
    wert = sum(tr[1: periode + 1]) / periode
    ergebnis[periode] = wert
    for i in range(periode + 1, len(kerzen)):
        wert = (wert * (periode - 1) + tr[i]) / periode
        ergebnis[i] = wert
    return ergebnis


# -------------------------------------------------------------- Strategien
# Eine Strategie liefert je Kerze +1 (kaufen), -1 (verkaufen) oder 0 (nichts).
# Das Signal gilt am Schluss der Kerze, gehandelt wird zur nächsten Eröffnung.


def _signale_ema_kreuzung(kerzen: list[Kerze], p: dict) -> list[int]:
    schluss = [k.close for k in kerzen]
    schnell, langsam = ema(schluss, int(p["schnell"])), ema(schluss, int(p["langsam"]))
    signale = [0] * len(kerzen)
    for i in range(1, len(kerzen)):
        if None in (schnell[i], langsam[i], schnell[i - 1], langsam[i - 1]):
            continue
        if schnell[i - 1] <= langsam[i - 1] and schnell[i] > langsam[i]:
            signale[i] = 1
        elif schnell[i - 1] >= langsam[i - 1] and schnell[i] < langsam[i]:
            signale[i] = -1
    return signale


def _signale_rsi_umkehr(kerzen: list[Kerze], p: dict) -> list[int]:
    werte = rsi([k.close for k in kerzen], int(p["periode"]))
    unten, oben = float(p["unten"]), float(p["oben"])
    signale = [0] * len(kerzen)
    for i in range(1, len(kerzen)):
        if werte[i] is None or werte[i - 1] is None:
            continue
        if werte[i - 1] < unten <= werte[i]:  # kommt aus dem überverkauften Bereich
            signale[i] = 1
        elif werte[i - 1] > oben >= werte[i]:  # kommt aus dem überkauften Bereich
            signale[i] = -1
    return signale


STRATEGIEN: dict[str, dict[str, Any]] = {
    "ema_kreuzung": {
        "name": "EMA-Kreuzung",
        "beschreibung": "Kauf, wenn die schnelle EMA die langsame von unten kreuzt; Verkauf umgekehrt.",
        "parameter": {"schnell": 20, "langsam": 50},
        "funktion": _signale_ema_kreuzung,
    },
    "rsi_umkehr": {
        "name": "RSI-Umkehr",
        "beschreibung": "Kauf, wenn der RSI aus dem überverkauften Bereich zurückkommt; Verkauf aus dem überkauften.",
        "parameter": {"periode": 14, "unten": 30, "oben": 70},
        "funktion": _signale_rsi_umkehr,
    },
}
STANDARD_RISIKO = {"kapital": 10000.0, "risiko_prozent": 1.0, "atr_periode": 14,
                   "sl_atr": 1.5, "tp_atr": 3.0, "spread": 0.0}


def strategien() -> list[dict]:
    from . import trading_bots  # Original-Bots (Phase 4.6)
    return [
        {"id": sid, "name": s["name"], "beschreibung": s["beschreibung"], "parameter": dict(s["parameter"])}
        for sid, s in STRATEGIEN.items()
    ] + trading_bots.bots() + [{"id": "_risiko", "name": "Risiko und Ausführung", "parameter": dict(STANDARD_RISIKO)}]


# ---------------------------------------------------------------- Backtest


def _kennzahlen(trades: list[dict], start_kapital: float) -> dict:
    gewinne = [t["ergebnis"] for t in trades if t["ergebnis"] > 0]
    verluste = [t["ergebnis"] for t in trades if t["ergebnis"] <= 0]
    kapital = spitze = start_kapital
    max_dd = 0.0
    for t in trades:
        kapital += t["ergebnis"]
        spitze = max(spitze, kapital)
        if spitze > 0:
            max_dd = max(max_dd, (spitze - kapital) / spitze)
    summe_verlust = -sum(verluste)
    return {
        "trades": len(trades),
        "trefferquote_prozent": round(len(gewinne) / len(trades) * 100, 1) if trades else 0.0,
        "gewinn": round(sum(t["ergebnis"] for t in trades), 2),
        "gewinn_prozent": round((kapital - start_kapital) / start_kapital * 100, 2) if start_kapital else 0.0,
        # Ohne Verluste ist der Profit-Faktor unendlich - JSON kann das nicht, also None
        "profit_faktor": round(sum(gewinne) / summe_verlust, 2) if summe_verlust > 0 else None,
        "max_drawdown_prozent": round(max_dd * 100, 2),
        "durchschnitt_gewinn": round(sum(gewinne) / len(gewinne), 2) if gewinne else 0.0,
        "durchschnitt_verlust": round(sum(verluste) / len(verluste), 2) if verluste else 0.0,
    }


def backtest(
    kerzen: list[Kerze],
    strategie: str,
    parameter: dict | None = None,
    risiko: dict | None = None,
    signal_funktion: Callable[[list[Kerze], dict], list[int]] | None = None,
) -> dict:
    if strategie not in STRATEGIEN and signal_funktion is None:
        raise SandboxFehler(f'Unbekannte Strategie "{strategie}" - erlaubt: {", ".join(STRATEGIEN)}')
    vorgabe = STRATEGIEN.get(strategie, {"parameter": {}, "name": strategie})
    p = {**vorgabe["parameter"], **(parameter or {})}
    r = {**STANDARD_RISIKO, **(risiko or {})}
    for schluessel in ("kapital", "risiko_prozent", "sl_atr", "tp_atr"):
        if float(r[schluessel]) <= 0:
            raise SandboxFehler(f"{schluessel} muss größer als 0 sein.")
    if float(r["risiko_prozent"]) > 10:
        raise SandboxFehler("Risiko pro Trade über 10 % ist in der Sandbox gesperrt (unrealistisch/gefährlich).")

    signale = (signal_funktion or vorgabe["funktion"])(kerzen, p)
    atr_werte = atr(kerzen, int(r["atr_periode"]))
    kapital = float(r["kapital"])
    spread = float(r["spread"])
    trades: list[dict] = []
    kurve: list[tuple[str, float]] = [(kerzen[0].zeit, kapital)]
    offen: dict | None = None

    for i in range(1, len(kerzen)):
        k = kerzen[i]
        # 1) offene Position gegen Stop/Ziel dieser Kerze prüfen
        if offen:
            richtung = offen["richtung"]
            stop_getroffen = k.low <= offen["stop"] if richtung == 1 else k.high >= offen["stop"]
            ziel_getroffen = k.high >= offen["ziel"] if richtung == 1 else k.low <= offen["ziel"]
            gegen_signal = signale[i - 1] == -richtung
            ausstieg = grund = None
            if stop_getroffen:  # vorsichtig: Stop vor Ziel
                ausstieg, grund = offen["stop"], "Stop"
            elif ziel_getroffen:
                ausstieg, grund = offen["ziel"], "Ziel"
            elif gegen_signal:
                ausstieg, grund = k.open, "Gegensignal"
            if ausstieg is not None:
                ergebnis = (ausstieg - offen["einstieg"]) * richtung * offen["menge"] - spread * offen["menge"]
                kapital += ergebnis
                trades.append({
                    "einstieg_zeit": offen["zeit"], "ausstieg_zeit": k.zeit,
                    "richtung": "kauf" if richtung == 1 else "verkauf",
                    "einstieg": round(offen["einstieg"], 6), "ausstieg": round(ausstieg, 6),
                    "grund": grund, "ergebnis": round(ergebnis, 2), "index": i,
                })
                kurve.append((k.zeit, kapital))
                offen = None
        # 2) neues Signal der VORIGEN Kerze -> Einstieg zur Eröffnung dieser Kerze
        if offen is None and signale[i - 1] != 0 and atr_werte[i - 1]:
            abstand = float(r["sl_atr"]) * atr_werte[i - 1]
            if abstand <= 0 or kapital <= 0:
                continue
            menge = kapital * float(r["risiko_prozent"]) / 100 / abstand
            richtung = signale[i - 1]
            offen = {
                "richtung": richtung, "einstieg": k.open, "zeit": k.zeit, "menge": menge,
                "stop": k.open - richtung * abstand,
                "ziel": k.open + richtung * float(r["tp_atr"]) * atr_werte[i - 1],
            }
            # Stop/Ziel können schon in der Einstiegskerze fallen
            stop_getroffen = k.low <= offen["stop"] if richtung == 1 else k.high >= offen["stop"]
            ziel_getroffen = k.high >= offen["ziel"] if richtung == 1 else k.low <= offen["ziel"]
            if stop_getroffen or ziel_getroffen:
                ausstieg = offen["stop"] if stop_getroffen else offen["ziel"]
                ergebnis = (ausstieg - offen["einstieg"]) * richtung * menge - spread * menge
                kapital += ergebnis
                trades.append({
                    "einstieg_zeit": k.zeit, "ausstieg_zeit": k.zeit,
                    "richtung": "kauf" if richtung == 1 else "verkauf",
                    "einstieg": round(offen["einstieg"], 6), "ausstieg": round(ausstieg, 6),
                    "grund": "Stop" if stop_getroffen else "Ziel", "ergebnis": round(ergebnis, 2), "index": i,
                })
                kurve.append((k.zeit, kapital))
                offen = None

    grenze = int(len(kerzen) * TEIL_IN_SAMPLE)
    teil1 = [t for t in trades if t["index"] < grenze]
    teil2 = [t for t in trades if t["index"] >= grenze]
    kapital_teil2 = float(r["kapital"]) + sum(t["ergebnis"] for t in teil1)
    schritt = max(1, len(kurve) // MAX_KURVE_PUNKTE)
    kurve_klein = kurve[::schritt]
    if kurve_klein[-1] != kurve[-1]:
        kurve_klein.append(kurve[-1])
    for t in trades:
        t.pop("index", None)

    gesamt = _kennzahlen(trades, float(r["kapital"]))
    k1, k2 = _kennzahlen(teil1, float(r["kapital"])), _kennzahlen(teil2, kapital_teil2)
    warnungen = []
    if gesamt["trades"] < 30:
        warnungen.append("Weniger als 30 Trades - statistisch kaum aussagekräftig.")
    if k1["trades"] and k2["trades"] and k1["gewinn_prozent"] > 0 >= k2["gewinn_prozent"]:
        warnungen.append("Gewinn nur im ersten Teil, Verlust im letzten Teil - Verdacht auf Überanpassung.")
    if offen:
        warnungen.append("Am Datenende war noch eine Position offen - nicht mitgezählt.")
    return {
        "strategie": strategie,
        "strategie_name": vorgabe.get("name", strategie),
        "parameter": p,
        "risiko": r,
        "kerzen": len(kerzen),
        "zeitraum": {"von": kerzen[0].zeit, "bis": kerzen[-1].zeit},
        "gesamt": gesamt,
        "erster_teil_70": k1,
        "letzter_teil_30": k2,
        "endkapital": round(kapital, 2),
        "kapitalkurve": [{"zeit": z, "kapital": round(c, 2)} for z, c in kurve_klein],
        "trades": trades[-MAX_TRADES_AUSGABE:],
        "warnungen": warnungen,
        "hinweis": "Backtest auf historischen Daten mit Vereinfachungen (siehe app/trading_sandbox.py) - "
        "kein Gewinnversprechen, kein Echtgeld, keine Broker-Verbindung.",
    }


def lauf(datenquelle: str, strategie: str, parameter: dict | None = None, risiko: dict | None = None) -> dict:
    from . import trading_bots
    if strategie in trading_bots.BOTS:
        kerzen = kerzen_laden(datenquelle)
        referenz = None
        ref_symbol = trading_bots.BOTS[strategie].get("referenz")
        if ref_symbol:
            referenz = kerzen_laden(referenz_name(datenquelle, ref_symbol))
        ergebnis = trading_bots.backtest_bot(kerzen, strategie, parameter, risiko, referenz)
        ergebnis["datenquelle"] = datenquelle
        if datenquelle == "demo":
            ergebnis["warnungen"].insert(0, "Demo-Daten: künstliche Zufallskurse, keine echten Marktdaten.")
        return ergebnis
    ergebnis = backtest(kerzen_laden(datenquelle), strategie, parameter, risiko)
    ergebnis["datenquelle"] = datenquelle
    if datenquelle == "demo":
        ergebnis["warnungen"].insert(0, "Demo-Daten: künstliche Zufallskurse, keine echten Marktdaten.")
    return ergebnis

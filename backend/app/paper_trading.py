"""
Paper Trading mit Risiko-Wächter (Phase 4.5, 23.09.2026).

Ein Übungskonto im Jarvis-Ordner (data/paper/konto.json): Positionen,
Journal, Kennzahlen. KEIN Broker, KEIN Echtgeld, KEINE echten Orders - die
Kurse kommen aus app/marktdaten.py.

Risiko-Wächter (Risk Engine, laut Gesamtplan "darf jeden Trade ablehnen"):
Jede Order läuft vor der Eröffnung durch pruefen(). Harte Regeln (Ablehnung):
- ohne Stop-Loss kein Trade
- Risiko je Trade höchstens MAX_RISIKO (Standard 1 % des Kontos)
- höchstens MAX_POSITIONEN gleichzeitig (Standard 3)
- höchstens MAX_JE_GRUPPE je Gruppe (Standard 1): Gold, Silber und Platin
  laufen fast gleich - drei Metall-Trades wären dreimal dieselbe Wette
  (Punkt 9 im Bot-Feedback vom 23.09.2026)
- Tagesverlust-Grenze (Standard 3 %): danach für heute keine neuen Trades
- Stop auf der richtigen Seite, Ziel auf der richtigen Seite
Weiche Regeln (Warnung, kein Verbot): Chance/Risiko unter 1,5.

Bot-Beobachter (Forward-Test ohne MT5): bot_pruefen() schaut auf die letzte
GESCHLOSSENE Kerze eines Marktes, ob einer der Original-Bots ein Signal hat,
und eröffnet dann eine Paper-Position über den Risiko-Wächter - wie der Bot
es auf dem Demokonto täte. Jedes Signal nur einmal.

Offene Positionen werden mit aktualisieren() gegen die neuen Kerzen seit dem
Einstieg geprüft (Stop vor Ziel, wie im Backtest).
"""

from __future__ import annotations

import datetime
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from . import marktdaten, trading_bots
from .trading_sandbox import Kerze

STANDARD_REGELN = {
    "max_risiko_prozent": 1.0,
    "max_positionen": 3,
    "max_je_gruppe": 1,
    "tagesverlust_grenze_prozent": 3.0,
    "min_chance_risiko": 1.5,
}
GRUPPEN = {
    "metall": {"XAUUSD", "XAGUSD", "XPTUSD"},
    "usd_index": {"SP500", "NASDAQ100", "DOW", "AAPL", "MSFT", "NVDA", "TSLA"},
    "europa": {"DAX", "SAP"},
    "krypto": {"BTCUSD", "ETHUSD", "SOLUSD"},
    "yen": {"USDJPY", "CHFJPY"},
    "usd_forex": {"EURUSD", "GBPUSD"},
}
BOT_INTERVALL = {"haupt_bot": "1h", "david_v2": "1h", "divergenz_gold_silber": "4h"}
_lock = threading.Lock()


class PaperFehler(ValueError):
    pass


def _ordner() -> Path:
    pfad = Path(os.getenv("PAPER_PATH") or Path(__file__).resolve().parents[2] / "data" / "paper")
    pfad.mkdir(parents=True, exist_ok=True)
    return pfad


def _jetzt() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _neues_konto(startkapital: float = 10000.0) -> dict:
    return {"startkapital": startkapital, "kontostand": startkapital, "waehrung": "USD (Preis-Einheiten)",
            "positionen": [], "journal": [], "regeln": dict(STANDARD_REGELN), "bot_signale": {},
            "erstellt": _jetzt(), "tag": None, "tag_start": startkapital}


def laden() -> dict:
    try:
        konto = json.loads((_ordner() / "konto.json").read_text(encoding="utf-8"))
        konto.setdefault("regeln", dict(STANDARD_REGELN))
        konto.setdefault("bot_signale", {})
        return konto
    except (OSError, json.JSONDecodeError):
        return _neues_konto()


def _speichern(konto: dict) -> None:
    ziel = _ordner() / "konto.json"
    tmp = ziel.with_suffix(".tmp")
    tmp.write_text(json.dumps(konto, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ziel)


def zuruecksetzen(startkapital: float = 10000.0) -> dict:
    if not 100 <= float(startkapital) <= 10_000_000:
        raise PaperFehler("Startkapital zwischen 100 und 10 Mio.")
    with _lock:
        alt = laden()
        if alt.get("journal") or alt.get("positionen"):
            sicherung = _ordner() / f"konto_bis_{datetime.date.today().isoformat()}_{uuid.uuid4().hex[:4]}.json"
            sicherung.write_text(json.dumps(alt, ensure_ascii=False, indent=1), encoding="utf-8")
        konto = _neues_konto(float(startkapital))
        _speichern(konto)
    return konto


def gruppe(symbol: str) -> str:
    return next((g for g, s in GRUPPEN.items() if symbol in s), symbol)


def _tag_pruefen(konto: dict) -> None:
    heute = datetime.date.today().isoformat()
    if konto.get("tag") != heute:
        konto["tag"], konto["tag_start"] = heute, konto["kontostand"]


def pruefen(konto: dict, symbol: str, richtung: int, einstieg: float, stop: float | None, ziel: float | None,
            risiko_prozent: float) -> dict:
    """Risiko-Wächter. Rückgabe: {"erlaubt": bool, "gruende": [...], "warnungen": [...]}"""
    regeln = {**STANDARD_REGELN, **konto.get("regeln", {})}
    gruende, warnungen = [], []
    if richtung not in (1, -1):
        gruende.append("Richtung muss Kauf oder Verkauf sein.")
    if not stop or stop <= 0:
        gruende.append("Kein Stop-Loss - ohne Stop gibt es keinen Trade.")
    elif richtung == 1 and stop >= einstieg:
        gruende.append("Stop liegt bei einem Kauf nicht unter dem Einstieg.")
    elif richtung == -1 and stop <= einstieg:
        gruende.append("Stop liegt bei einem Verkauf nicht über dem Einstieg.")
    if ziel is not None and ziel > 0:
        if (richtung == 1 and ziel <= einstieg) or (richtung == -1 and ziel >= einstieg):
            gruende.append("Ziel liegt auf der falschen Seite des Einstiegs.")
        elif stop and abs(einstieg - stop) > 0:
            cr = abs(ziel - einstieg) / abs(einstieg - stop)
            if cr < regeln["min_chance_risiko"]:
                warnungen.append(f"Chance/Risiko nur {cr:.2f} (Regel: mindestens {regeln['min_chance_risiko']}).")
    else:
        warnungen.append("Kein Ziel gesetzt - Ausstieg nur über Stop oder von Hand.")
    if risiko_prozent <= 0:
        gruende.append("Risiko muss größer als 0 sein.")
    elif risiko_prozent > regeln["max_risiko_prozent"]:
        gruende.append(f"Risiko {risiko_prozent:.2f} % über der Grenze von {regeln['max_risiko_prozent']} % je Trade.")
    offen = konto.get("positionen", [])
    if len(offen) >= regeln["max_positionen"]:
        gruende.append(f"Schon {len(offen)} Positionen offen (Grenze {regeln['max_positionen']}).")
    g = gruppe(symbol)
    in_gruppe = [p for p in offen if gruppe(p["symbol"]) == g]
    if len(in_gruppe) >= regeln["max_je_gruppe"]:
        gruende.append(f"Schon {len(in_gruppe)} Position(en) in der Gruppe '{g}' ({', '.join(p['symbol'] for p in in_gruppe)}) - "
                       "das wäre dieselbe Wette noch einmal.")
    _tag_pruefen(konto)
    if konto.get("tag_start"):
        tages = (konto["kontostand"] - konto["tag_start"]) / konto["tag_start"] * 100
        if tages <= -regeln["tagesverlust_grenze_prozent"]:
            gruende.append(f"Tagesverlust {tages:.2f} % - Grenze {regeln['tagesverlust_grenze_prozent']} % erreicht, heute keine neuen Trades.")
    return {"erlaubt": not gruende, "gruende": gruende, "warnungen": warnungen}


def order(symbol: str, richtung: int, stop: float, ziel: float | None = None, risiko_prozent: float | None = None,
          einstieg: float | None = None, notiz: str = "", bot: str | None = None) -> dict:
    """Paper-Position eröffnen (nach Prüfung durch den Risiko-Wächter)."""
    symbol = marktdaten.symbol_pruefen(symbol)
    with _lock:
        konto = laden()
        if einstieg is None:
            letzter = marktdaten.letzter_kurs(symbol)
            if not letzter:
                raise PaperFehler(f"Kein Kurs für {symbol} gespeichert - erst auf der Markt-Seite laden.")
            einstieg = letzter["kurs"]
        risiko_prozent = float(risiko_prozent if risiko_prozent is not None else konto["regeln"].get("max_risiko_prozent", 1.0))
        urteil = pruefen(konto, symbol, int(richtung), float(einstieg), stop, ziel, risiko_prozent)
        if not urteil["erlaubt"]:
            return {"eroeffnet": False, **urteil}
        risiko_betrag = konto["kontostand"] * risiko_prozent / 100
        menge = risiko_betrag / abs(float(einstieg) - float(stop))
        position = {
            "id": uuid.uuid4().hex[:8], "symbol": symbol, "richtung": int(richtung), "menge": menge,
            "einstieg": float(einstieg), "stop": float(stop), "ziel": float(ziel) if ziel else None,
            "risiko_betrag": round(risiko_betrag, 2), "risiko_prozent": risiko_prozent,
            "zeit": _jetzt(), "zeit_unix": int(time.time()), "notiz": (notiz or "")[:500], "bot": bot,
        }
        konto["positionen"].append(position)
        _speichern(konto)
    return {"eroeffnet": True, "position": position, **urteil}


def _schliessen(konto: dict, position: dict, preis: float, grund: str) -> dict:
    ergebnis = (preis - position["einstieg"]) * position["richtung"] * position["menge"]
    konto["kontostand"] = round(konto["kontostand"] + ergebnis, 2)
    konto["positionen"] = [p for p in konto["positionen"] if p["id"] != position["id"]]
    eintrag = {**position, "ausstieg": preis, "ausstieg_zeit": _jetzt(), "grund": grund,
               "ergebnis": round(ergebnis, 2), "r": round(ergebnis / position["risiko_betrag"], 2) if position["risiko_betrag"] else 0}
    konto["journal"].append(eintrag)
    return eintrag


def schliessen(pid: str, preis: float | None = None) -> dict:
    with _lock:
        konto = laden()
        position = next((p for p in konto["positionen"] if p["id"] == pid), None)
        if position is None:
            raise PaperFehler(f"Position {pid} nicht gefunden.")
        if preis is None:
            letzter = marktdaten.letzter_kurs(position["symbol"])
            if not letzter:
                raise PaperFehler("Kein aktueller Kurs - Preis bitte angeben.")
            preis = letzter["kurs"]
        eintrag = _schliessen(konto, position, float(preis), "von Hand")
        _speichern(konto)
    return eintrag


def aktualisieren(kurse_holen: bool = True) -> dict:
    """Offene Positionen gegen die Kerzen seit dem Einstieg prüfen."""
    geschlossen = []
    with _lock:
        konto = laden()
        symbole = {p["symbol"] for p in konto["positionen"]}
    if kurse_holen:
        for s in symbole:
            try:
                marktdaten.aktualisieren(s, "1h")
            except marktdaten.MarktFehler:
                pass
    with _lock:
        konto = laden()
        for p in list(konto["positionen"]):
            # nur Kerzen, die NACH dem Einstieg begonnen haben (Hoch/Tief davor zählen nicht)
            kerzen = [k for k in marktdaten.laden(p["symbol"], "1h", 2000) if k["zeit"] >= p["zeit_unix"]]
            for k in kerzen:
                if p["richtung"] == 1:
                    stop_hit, ziel_hit = k["low"] <= p["stop"], bool(p["ziel"]) and k["high"] >= p["ziel"]
                else:
                    stop_hit, ziel_hit = k["high"] >= p["stop"], bool(p["ziel"]) and k["low"] <= p["ziel"]
                if stop_hit:
                    geschlossen.append(_schliessen(konto, p, p["stop"], "Stop"))
                    break
                if ziel_hit:
                    geschlossen.append(_schliessen(konto, p, p["ziel"], "Ziel"))
                    break
        _speichern(konto)
    return {"geschlossen": geschlossen, "stand": stand()}


def kennzahlen(journal: list[dict]) -> dict:
    rs = [t.get("r", 0) for t in journal]
    gewinne = [t["ergebnis"] for t in journal if t["ergebnis"] > 0]
    verluste = [t["ergebnis"] for t in journal if t["ergebnis"] <= 0]
    je_bot: dict[str, dict] = {}
    for t in journal:
        b = je_bot.setdefault(t.get("bot") or "von Hand", {"trades": 0, "summe_r": 0.0})
        b["trades"] += 1
        b["summe_r"] = round(b["summe_r"] + t.get("r", 0), 2)
    return {
        "trades": len(journal),
        "trefferquote_prozent": round(len(gewinne) / len(journal) * 100, 1) if journal else 0.0,
        "summe_r": round(sum(rs), 2),
        "profit_faktor": round(sum(gewinne) / -sum(verluste), 2) if verluste and sum(verluste) < 0 else None,
        "je_bot": je_bot,
    }


def stand() -> dict:
    konto = laden()
    offen = []
    buchwert = 0.0
    for p in konto["positionen"]:
        letzter = marktdaten.letzter_kurs(p["symbol"])
        kurs = letzter["kurs"] if letzter else None
        pnl = (kurs - p["einstieg"]) * p["richtung"] * p["menge"] if kurs else None
        buchwert += pnl or 0
        offen.append({**p, "kurs": kurs, "buchgewinn": round(pnl, 2) if pnl is not None else None,
                      "r_offen": round(pnl / p["risiko_betrag"], 2) if pnl is not None and p["risiko_betrag"] else None})
    return {
        "startkapital": konto["startkapital"], "kontostand": konto["kontostand"],
        "mit_offenen": round(konto["kontostand"] + buchwert, 2),
        "entwicklung_prozent": round((konto["kontostand"] - konto["startkapital"]) / konto["startkapital"] * 100, 2),
        "positionen": offen, "journal": konto["journal"][-100:][::-1], "regeln": konto["regeln"],
        "kennzahlen": kennzahlen(konto["journal"]), "hinweis": "Übungskonto - keine echten Orders, kein Echtgeld.",
    }


def regeln_setzen(neu: dict) -> dict:
    with _lock:
        konto = laden()
        for k, v in neu.items():
            if k not in STANDARD_REGELN:
                raise PaperFehler(f"Unbekannte Regel: {k}")
            wert = float(v)
            if k == "max_risiko_prozent" and not 0 < wert <= 5:
                raise PaperFehler("Risiko je Trade zwischen 0 und 5 %.")
            if k in ("max_positionen", "max_je_gruppe") and not 1 <= wert <= 20:
                raise PaperFehler(f"{k} zwischen 1 und 20.")
            konto["regeln"][k] = wert
        _speichern(konto)
        return konto["regeln"]


# ------------------------------------------------------------ Bot-Beobachter


def _geschlossene_kerzen(symbol: str, intervall: str, anzahl: int = 1200) -> list[Kerze]:
    liste = marktdaten.laden(symbol, intervall, anzahl)
    schritt = marktdaten.INTERVALLE[intervall]
    jetzt = time.time()
    liste = [k for k in liste if k["zeit"] + schritt <= jetzt]  # laufende Kerze weg (wie bot.py)
    return [Kerze(marktdaten.zeit_text(k["zeit"]), k["open"], k["high"], k["low"], k["close"]) for k in liste]


def bot_pruefen(bot: str, symbol: str, intervall: str | None = None, handeln: bool = True) -> dict:
    """Hat der Bot auf der letzten geschlossenen Kerze ein Signal? Wenn ja und
    handeln=True: Paper-Position über den Risiko-Wächter (jedes Signal einmal)."""
    if bot not in trading_bots.BOTS:
        raise PaperFehler(f"Unbekannter Bot {bot}")
    symbol = marktdaten.symbol_pruefen(symbol)
    intervall = marktdaten.intervall_pruefen(intervall or BOT_INTERVALL[bot])
    try:
        marktdaten.aktualisieren(symbol, intervall)
    except marktdaten.MarktFehler as exc:
        print(f"[Paper] {symbol} {intervall}: {exc}", flush=True)
    kerzen = _geschlossene_kerzen(symbol, intervall)
    referenz = None
    ref = trading_bots.BOTS[bot].get("referenz")
    if ref:
        try:
            marktdaten.aktualisieren(ref, intervall)
        except marktdaten.MarktFehler:
            pass
        referenz = _geschlossene_kerzen(ref, intervall)
    zustand = trading_bots.aktueller_zustand(kerzen, bot, referenz)
    ergebnis: dict[str, Any] = {"bot": bot, "symbol": symbol, "intervall": intervall, "zustand": zustand, "order": None}
    signal = zustand.get("signal")
    if not signal or not handeln:
        return ergebnis
    schluessel = f"{bot}|{symbol}|{intervall}"
    with _lock:
        konto = laden()
        schon = konto["bot_signale"].get(schluessel) == zustand["zeit"]
    if schon:
        ergebnis["hinweis"] = "Signal dieser Kerze wurde schon verarbeitet."
        return ergebnis
    p = trading_bots.BOTS[bot]["parameter"]
    einstieg = kerzen[-1].close
    stop = einstieg - signal["richtung"] * signal["stop"]
    ziel = einstieg + signal["richtung"] * signal["stop"] * p.get("rr", 2.0)
    ergebnis["order"] = order(symbol, signal["richtung"], stop, ziel,
                              trading_bots.BOTS[bot]["risiko"]["risiko_prozent"], einstieg,
                              notiz=f"Signal {bot} auf {intervall}-Kerze {zustand['zeit']}", bot=bot)
    with _lock:
        konto = laden()
        konto["bot_signale"][schluessel] = zustand["zeit"]
        _speichern(konto)
    return ergebnis


# Original-Märkte der Bots (config.py)
BOT_MAERKTE = {
    "haupt_bot": [("XAUUSD", "1h"), ("XAGUSD", "1h"), ("XPTUSD", "1h"), ("CHFJPY", "4h"), ("USDJPY", "4h")],
    "david_v2": [("EURUSD", "1h"), ("GBPUSD", "1h"), ("USDJPY", "1h"), ("XAUUSD", "4h")],
    "divergenz_gold_silber": [("XAUUSD", "4h")],
}


def alle_bots_pruefen(handeln: bool = True) -> list[dict]:
    ergebnisse = []
    for bot, maerkte in BOT_MAERKTE.items():
        for symbol, intervall in maerkte:
            try:
                ergebnisse.append(bot_pruefen(bot, symbol, intervall, handeln))
            except Exception as exc:  # noqa: BLE001 - ein Markt darf die anderen nicht blockieren
                ergebnisse.append({"bot": bot, "symbol": symbol, "intervall": intervall, "fehler": str(exc)})
    return ergebnisse

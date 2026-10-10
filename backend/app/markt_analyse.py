"""
Markt erklären (Phase 4.3, 23.09.2026).

zustand(): rechnet für einen Markt die Kennzahlen, die in Sir's Notizen und
Bots vorkommen (EMA 20/50/150/200, RSI 14, ATR 14, Abstand zur EMA,
Veränderung), dazu den Zustand der drei Original-Bots - und schreibt daraus
eine kurze Erklärung in einfachem Deutsch. Ohne Claude, 0 Kosten.

frage(): baut daraus eine Frage an Jarvis ("Erkläre mir ... anhand meiner
Notizen"). Die geht im HUD über den normalen Chat - Vault-Suche, Quellen,
Kosten wie jede andere Frage (ca. 0,5 Cent mit Sonnet 5).

Keine Anlageberatung: Jarvis erklärt, was die Zahlen bedeuten, und sagt
nicht, ob Sir kaufen soll.
"""

from __future__ import annotations

from typing import Any

from . import marktdaten, trading_bots
from .trading_sandbox import Kerze, atr, ema, rsi


def _prozent(a: float, b: float) -> float | None:
    return round((a - b) / b * 100, 2) if b else None


def zustand(symbol: str, intervall: str = "1d", kerzen_liste: list[dict] | None = None) -> dict:
    symbol, intervall = marktdaten.symbol_pruefen(symbol), marktdaten.intervall_pruefen(intervall)
    roh = kerzen_liste if kerzen_liste is not None else marktdaten.laden(symbol, intervall, 1500)
    if len(roh) < 30:
        raise marktdaten.MarktFehler(f"Zu wenige Kerzen für {symbol} {intervall} ({len(roh)}) - erst laden.")
    kz = [Kerze(marktdaten.zeit_text(k["zeit"]), k["open"], k["high"], k["low"], k["close"]) for k in roh]
    schluss = [k.close for k in kz]
    letzter = schluss[-1]
    werte: dict[str, Any] = {"symbol": symbol, "name": marktdaten.KATALOG[symbol]["name"], "intervall": intervall,
                             "zeit": kz[-1].zeit, "kurs": letzter, "kerzen": len(kz)}
    for n in (20, 50, 150, 200):
        e = ema(schluss, n)[-1] if len(schluss) >= n else None
        werte[f"ema{n}"] = round(e, 6) if e else None
        werte[f"abstand_ema{n}_prozent"] = _prozent(letzter, e) if e else None
    r = rsi(schluss, 14)[-1]
    a = atr(kz, 14)[-1]
    werte["rsi14"] = round(r, 1) if r is not None else None
    werte["atr14"] = round(a, 6) if a else None
    werte["atr_prozent"] = round(a / letzter * 100, 2) if a else None
    werte["veraenderung_20_prozent"] = _prozent(letzter, schluss[-21]) if len(schluss) > 21 else None
    hoch, tief = max(k.high for k in kz[-20:]), min(k.low for k in kz[-20:])
    werte["hoch20"], werte["tief20"] = hoch, tief

    bots = []
    for bot in ("haupt_bot", "david_v2"):
        try:
            bots.append(trading_bots.aktueller_zustand(kz, bot))
        except Exception as exc:  # noqa: BLE001
            bots.append({"bot": bot, "fehler": str(exc)})
    if symbol == "XAUUSD":
        try:
            ref = marktdaten.laden("XAGUSD", intervall, 1500)
            if ref:
                rk = [Kerze(marktdaten.zeit_text(k["zeit"]), k["open"], k["high"], k["low"], k["close"]) for k in ref]
                bots.append(trading_bots.aktueller_zustand(kz, "divergenz_gold_silber", rk))
        except Exception as exc:  # noqa: BLE001
            bots.append({"bot": "divergenz_gold_silber", "fehler": str(exc)})
    werte["bots"] = bots
    werte["erklaerung"] = erklaerung(werte)
    return werte


def de(wert: float, stellen: int = 1) -> str:
    """Zahl mit deutschem Komma."""
    return f"{wert:.{stellen}f}".replace(".", ",")


def erklaerung(w: dict) -> list[str]:
    """Kurze Sätze in einfachem Deutsch - nur Beschreibung, keine Empfehlung."""
    s = []
    trend = w.get("abstand_ema200_prozent") if w.get("abstand_ema200_prozent") is not None else w.get("abstand_ema50_prozent")
    basis = "EMA 200" if w.get("abstand_ema200_prozent") is not None else "EMA 50"
    if trend is not None:
        if trend > 1:
            s.append(f"Der Kurs liegt {de(trend)} % über der {basis} - der längere Trend zeigt nach oben.")
        elif trend < -1:
            s.append(f"Der Kurs liegt {de(abs(trend))} % unter der {basis} - der längere Trend zeigt nach unten.")
        else:
            vorzeichen = "+" if trend >= 0 else "-"
            s.append(f"Der Kurs liegt nah an der {basis} ({vorzeichen}{de(abs(trend))} %) - kein klarer Trend.")
    r = w.get("rsi14")
    if r is not None:
        if r >= 70:
            s.append(f"RSI {r:.0f}: überkauft - der Kurs ist zuletzt stark gestiegen.")
        elif r <= 30:
            s.append(f"RSI {r:.0f}: überverkauft - der Kurs ist zuletzt stark gefallen.")
        elif r <= 40:
            s.append(f"RSI {r:.0f}: im Rücksetzer-Bereich (unter 40) - dort warten die Pullback-Bots.")
        else:
            s.append(f"RSI {r:.0f}: neutral.")
    if w.get("atr_prozent") is not None:
        s.append(f"Typische Schwankung je Kerze (ATR 14): {de(w['atr_prozent'], 2)} % des Kurses.")
    if w.get("veraenderung_20_prozent") is not None:
        v20 = w["veraenderung_20_prozent"]
        s.append(f"Veränderung über die letzten 20 Kerzen: {'+' if v20 >= 0 else '-'}{de(abs(v20))} %.")
    for b in w.get("bots", []):
        if b.get("fehler") or b.get("hinweis"):
            continue
        name = b.get("name", b["bot"])
        if b.get("signal"):
            richtung = "Kauf" if b["signal"]["richtung"] == 1 else "Verkauf"
            s.append(f"{name}: Signal ({richtung}) auf der letzten Kerze.")
        elif b.get("bereit"):
            s.append(f"{name}: Bedingungen fast erfüllt - wartet auf das Auslöse-Kreuz.")
        else:
            s.append(f"{name}: kein Signal.")
    s.append("Das ist eine Beschreibung der Zahlen, keine Anlageberatung.")
    return s


def frage(w: dict) -> str:
    """Frage an Jarvis zum Markt - geht über den normalen Chat (Vault zuerst)."""
    zahlen = (f"Kurs {w['kurs']:.5g}, EMA50 {w.get('ema50')}, EMA200 {w.get('ema200')}, RSI14 {w.get('rsi14')}, "
              f"ATR14 {w.get('atr_prozent')} % des Kurses, 20-Kerzen-Veränderung {w.get('veraenderung_20_prozent')} %")
    return (f"Erkläre mir den aktuellen Zustand von {w['name']} ({w['symbol']}, {w['intervall']}): {zahlen}. "
            "Was bedeuten diese Werte laut meinen Notizen zu EMA, RSI, ATR und Risiko, und was würden meine "
            "Bots daraus machen? Keine Kaufempfehlung, nur Erklärung.")

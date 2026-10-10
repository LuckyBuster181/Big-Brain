"""
Trading-Tagebuch (26.09.2026, Wunsch von Sir).

Sir trägt seine EIGENEN Trades aus MetaTrader ein (Übungskonto oder echtes Geld) -
im HUD, per Chat oder per Sprache ("Gold Long bei 3740, Stopp 3720, Grund Ausbruch").
Jarvis rechnet jeden Trade in R (Vielfache des Einsatzes) und in Euro, wertet die
Woche aus und prüft Sirs eigene Regeln aus "01 - Persönliches/05 - Ziele Einkommen
und Trading":
- höchstens 1 % Risiko je Trade,
- höchstens 3 % Verlust am Tag (bei 2.000 € also 60 €),
- das Konto fällt nie unter 1.000 €.

Unterschied zu app/paper_trading.py: Dort handelt Jarvis selbst mit Übungsgeld auf
Kursdaten. Hier steht, was Sir WIRKLICH gehandelt hat. Jarvis handelt nie.

Keine Claude-Kosten: Erkennen (app/alltag.py), Rechnen und Auswerten laufen lokal.
Speicher: data/tagebuch.json (Einstellungen + Trades), wird nie gelöscht, nur ergänzt.
"""

from __future__ import annotations

import datetime
import json
import os
import threading
from pathlib import Path
from typing import Any

from dateutil import tz

ZEITZONE = tz.gettz("Europe/Berlin") or tz.tzlocal()
_lock = threading.Lock()

STANDARD_EINSTELLUNGEN: dict[str, Any] = {
    "start_kapital": 2000.0,     # Sirs Einsatz (26.09.2026)
    "grenze": 1000.0,            # darunter nie
    "risiko_prozent": 1.0,       # je Trade
    "tagesverlust_prozent": 3.0, # Tageslimit
    "waehrung": "€",
    "modus": "uebung",           # "uebung" (Demokonto) oder "echt"
}
MODI = ("uebung", "echt")
RICHTUNGEN = {"long": 1, "kauf": 1, "buy": 1, "short": -1, "verkauf": -1, "sell": -1}


class TagebuchFehler(ValueError):
    pass


# ------------------------------------------------------------------ Speicher


def pfad() -> Path:
    roh = os.getenv("TAGEBUCH_PATH")
    p = Path(roh) if roh else Path(__file__).resolve().parents[2] / "data" / "tagebuch.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _laden() -> dict:
    p = pfad()
    if not p.exists():
        return {"einstellungen": dict(STANDARD_EINSTELLUNGEN), "trades": []}
    try:
        daten = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TagebuchFehler(f"Tagebuch nicht lesbar ({exc}). Die Datei bleibt unverändert.") from exc
    daten.setdefault("trades", [])
    daten["einstellungen"] = {**STANDARD_EINSTELLUNGEN, **(daten.get("einstellungen") or {})}
    return daten


def _speichern(daten: dict) -> None:
    p = pfad()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)  # erst ganz schreiben, dann austauschen: kein halbes Tagebuch


def _jetzt(jetzt: datetime.datetime | None = None) -> datetime.datetime:
    return jetzt or datetime.datetime.now(ZEITZONE)


# ------------------------------------------------------------------ Rechnen


def r_wert(richtung: int, einstieg: float, stopp: float, ausstieg: float) -> float:
    """Ergebnis in R: 1 R = Abstand Einstieg-Stopp. +2 R = doppelter Einsatz gewonnen."""
    abstand = (einstieg - stopp) * richtung
    if abstand <= 0:
        raise TagebuchFehler("Der Stopp liegt auf der falschen Seite des Einstiegs.")
    return round((ausstieg - einstieg) * richtung / abstand, 2)


def kontostand(daten: dict) -> float:
    e = daten["einstellungen"]
    return round(float(e["start_kapital"]) + sum(t.get("eur") or 0 for t in daten["trades"]
                                                    if t.get("status") == "geschlossen"), 2)


def _tagesergebnis(daten: dict, tag: datetime.date) -> float:
    return round(sum(t.get("eur") or 0 for t in daten["trades"] if t.get("status") == "geschlossen"
                     and datetime.datetime.fromisoformat(t["zeit_zu"]).date() == tag), 2)


def _warnungen(daten: dict, jetzt: datetime.datetime) -> list[str]:
    e = daten["einstellungen"]
    stand, grenze = kontostand(daten), float(e["grenze"])
    w = []
    if stand <= grenze:
        w.append(f"STOPP: Kontostand {_eur(stand, e)} hat Ihre Grenze von {_eur(grenze, e)} erreicht. "
                 "Kein neuer Trade - erst gemeinsam auswerten.")
    elif stand - grenze < float(e["start_kapital"]) * 0.1:
        w.append(f"Achtung: nur noch {_eur(stand - grenze, e)} bis zu Ihrer Grenze von {_eur(grenze, e)}.")
    heute = _tagesergebnis(daten, jetzt.date())
    limit = float(e["start_kapital"]) * float(e["tagesverlust_prozent"]) / 100
    if heute <= -limit:
        w.append(f"Tageslimit erreicht ({_eur(heute, e)} heute, Grenze {_eur(-limit, e)}). Heute kein Trade mehr.")
    return w


def _eur(wert: float, e: dict) -> str:
    text = f"{abs(wert):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("−" if wert < 0 else "") + text + " " + e.get("waehrung", "€")


def _zahl(wert: Any, name: str, pflicht: bool = True) -> float | None:
    if wert in (None, ""):
        if pflicht:
            raise TagebuchFehler(f"{name} fehlt.")
        return None
    try:
        z = float(str(wert).replace(",", "."))
    except ValueError as exc:
        raise TagebuchFehler(f"{name} ist keine Zahl: {wert}") from exc
    if z <= 0:
        raise TagebuchFehler(f"{name} muss größer als 0 sein.")
    return z


# ------------------------------------------------------------------ Trades


def eintragen(symbol: str, richtung: str | int, einstieg: Any, stopp: Any, ziel: Any = None,
              grund: str = "", risiko_eur: Any = None, modus: str | None = None,
              jetzt: datetime.datetime | None = None) -> dict:
    """Neuen offenen Trade eintragen. Rückgabe: {"trade", "hinweise", "warnungen"}."""
    symbol = (symbol or "").strip().upper()[:20]
    if not symbol:
        raise TagebuchFehler("Markt fehlt (z.B. XAUUSD).")
    r = richtung if richtung in (1, -1) else RICHTUNGEN.get(str(richtung).strip().lower())
    if r is None:
        raise TagebuchFehler('Richtung fehlt: "long" oder "short".')
    ein, st = _zahl(einstieg, "Einstieg"), _zahl(stopp, "Stopp")
    zi = _zahl(ziel, "Ziel", pflicht=False)
    r_wert(r, ein, st, ein)  # prüft die Seite des Stopps
    if zi is not None and (zi - ein) * r <= 0:
        raise TagebuchFehler("Das Ziel liegt auf der falschen Seite des Einstiegs.")
    jetzt = _jetzt(jetzt)
    with _lock:
        daten = _laden()
        e = daten["einstellungen"]
        stand = kontostand(daten)
        erlaubt = round(stand * float(e["risiko_prozent"]) / 100, 2)
        risiko = _zahl(risiko_eur, "Risiko", pflicht=False) or erlaubt
        hinweise, warnungen = [], _warnungen(daten, jetzt)
        if risiko > erlaubt * 1.05:
            warnungen.append(f"Risiko {_eur(risiko, e)} ist mehr als Ihre {e['risiko_prozent']:g} % "
                             f"({_eur(erlaubt, e)}).")
        if not (grund or "").strip():
            hinweise.append("Kein Grund angegeben - bei der Auswertung hilft ein Satz, warum.")
        if zi is not None:
            crv = abs(zi - ein) / abs(ein - st)
            if crv < 1.5:
                hinweise.append(f"Chance/Risiko nur {crv:.1f} zu 1 - die Bots nutzen 2 zu 1.")
        neu = {
            "id": max([t["id"] for t in daten["trades"]] or [0]) + 1,
            "status": "offen", "modus": modus if modus in MODI else e["modus"],
            "symbol": symbol, "richtung": r, "einstieg": ein, "stopp": st, "ziel": zi,
            "grund": (grund or "").strip()[:300], "risiko_eur": risiko,
            "zeit_offen": jetzt.isoformat(timespec="seconds"),
            "ausstieg": None, "zeit_zu": None, "r": None, "eur": None, "notiz": "",
        }
        daten["trades"].append(neu)
        _speichern(daten)
    return {"trade": neu, "hinweise": hinweise, "warnungen": warnungen}


def offene(symbol: str | None = None) -> list[dict]:
    daten = _laden()
    return [t for t in daten["trades"] if t["status"] == "offen" and (not symbol or t["symbol"] == symbol.upper())]


def schliessen(trade_id: int | None = None, ausstieg: Any = None, symbol: str | None = None,
               art: str | None = None, eur: Any = None, notiz: str = "",
               jetzt: datetime.datetime | None = None) -> dict:
    """Offenen Trade schließen. Ohne ID: der neueste offene (optional nur dieses Markts).
    art = "stopp" oder "ziel" nimmt den eingetragenen Preis. eur überschreibt den errechneten Betrag."""
    jetzt = _jetzt(jetzt)
    with _lock:
        daten = _laden()
        e = daten["einstellungen"]
        kandidaten = [t for t in daten["trades"] if t["status"] == "offen"
                      and (trade_id is None or t["id"] == int(trade_id))
                      and (not symbol or t["symbol"] == symbol.upper())]
        if not kandidaten:
            raise TagebuchFehler("Kein passender offener Trade im Tagebuch.")
        t = kandidaten[-1]
        if art == "stopp":
            preis = t["stopp"]
        elif art == "ziel":
            if t.get("ziel") is None:
                raise TagebuchFehler("Für diesen Trade ist kein Ziel eingetragen - bitte den Preis nennen.")
            preis = t["ziel"]
        else:
            preis = _zahl(ausstieg, "Ausstiegspreis")
        t["ausstieg"] = preis
        t["r"] = r_wert(t["richtung"], t["einstieg"], t["stopp"], preis)
        betrag = eur if eur not in (None, "") else None
        t["eur"] = round(float(str(betrag).replace(",", ".")), 2) if betrag is not None else round(t["r"] * t["risiko_eur"], 2)
        t["zeit_zu"] = jetzt.isoformat(timespec="seconds")
        t["status"] = "geschlossen"
        if notiz:
            t["notiz"] = notiz.strip()[:300]
        _speichern(daten)
        warnungen = _warnungen(daten, jetzt)
        stand = kontostand(daten)
    return {"trade": t, "kontostand": stand, "warnungen": warnungen, "text": _satz_geschlossen(t, stand, e, warnungen)}


def einstellungen_setzen(werte: dict) -> dict:
    with _lock:
        daten = _laden()
        e = daten["einstellungen"]
        for k in ("start_kapital", "grenze", "risiko_prozent", "tagesverlust_prozent"):
            if k in werte and werte[k] not in (None, ""):
                e[k] = _zahl(werte[k], k)
        if werte.get("modus") in MODI:
            e["modus"] = werte["modus"]
        if e["grenze"] >= e["start_kapital"]:
            raise TagebuchFehler("Die Grenze muss unter dem Startkapital liegen.")
        if e["risiko_prozent"] > 10 or e["tagesverlust_prozent"] > 50:
            raise TagebuchFehler("Risiko höchstens 10 %, Tageslimit höchstens 50 %.")
        _speichern(daten)
    return e


# ------------------------------------------------------------------ Auswertung


def auswertung(tage: int | None = None, modus: str | None = None, jetzt: datetime.datetime | None = None) -> dict:
    """Kennzahlen der geschlossenen Trades (optional nur die letzten N Tage / nur ein Modus)."""
    jetzt = _jetzt(jetzt)
    daten = _laden()
    e = daten["einstellungen"]
    ab = jetzt - datetime.timedelta(days=tage) if tage else None
    zu = [t for t in daten["trades"] if t["status"] == "geschlossen"
          and (not modus or t.get("modus") == modus)
          and (ab is None or datetime.datetime.fromisoformat(t["zeit_zu"]) >= ab)]
    gewinne = [t for t in zu if (t["r"] or 0) > 0]
    plus_r, minus_r = sum(t["r"] for t in gewinne), -sum(t["r"] for t in zu if (t["r"] or 0) < 0)
    kurve, spitze, rueckgang = 0.0, 0.0, 0.0
    for t in sorted(zu, key=lambda x: x["zeit_zu"]):
        kurve += t["eur"] or 0
        spitze = max(spitze, kurve)
        rueckgang = max(rueckgang, spitze - kurve)
    limit = float(e["start_kapital"]) * float(e["tagesverlust_prozent"]) / 100
    tage_ergebnis: dict[str, float] = {}
    for t in zu:
        tag = t["zeit_zu"][:10]
        tage_ergebnis[tag] = tage_ergebnis.get(tag, 0) + (t["eur"] or 0)
    verstoesse = []
    for tag, wert in sorted(tage_ergebnis.items()):
        if wert < -limit - 0.005:
            verstoesse.append(f"{tag}: Tagesverlust {_eur(wert, e)} über dem Limit von {_eur(-limit, e)}")
    for t in zu:
        if t["risiko_eur"] > float(e["start_kapital"]) * float(e["risiko_prozent"]) / 100 * 1.5:
            verstoesse.append(f"Trade {t['id']} ({t['symbol']}): Risiko {_eur(t['risiko_eur'], e)} deutlich über {e['risiko_prozent']:g} %")
    ohne_grund = sum(1 for t in zu if not t.get("grund"))
    return {
        "zeitraum_tage": tage, "modus": modus,
        "trades": len(zu), "gewinner": len(gewinne), "verlierer": len(zu) - len(gewinne),
        "trefferquote_prozent": round(len(gewinne) / len(zu) * 100, 1) if zu else None,
        "summe_r": round(sum(t["r"] for t in zu), 2), "schnitt_r": round(sum(t["r"] for t in zu) / len(zu), 2) if zu else None,
        "profit_faktor": round(plus_r / minus_r, 2) if minus_r else None,
        "nur_gewinner": bool(zu) and not minus_r and plus_r > 0,
        "summe_eur": round(sum(t["eur"] or 0 for t in zu), 2),
        "bester_eur": max((t["eur"] for t in zu), default=None), "schlechtester_eur": min((t["eur"] for t in zu), default=None),
        "max_rueckgang_eur": round(rueckgang, 2),
        "je_markt": _je_markt(zu),
        "ohne_grund": ohne_grund, "regelverstoesse": verstoesse,
        "kontostand": kontostand(daten), "grenze": e["grenze"],
        "abstand_grenze": round(kontostand(daten) - float(e["grenze"]), 2),
        "offen": [t for t in daten["trades"] if t["status"] == "offen"],
        "warnungen": _warnungen(daten, jetzt),
        "einstellungen": e,
    }


def _je_markt(trades: list[dict]) -> dict:
    aus: dict[str, dict] = {}
    for t in trades:
        m = aus.setdefault(t["symbol"], {"trades": 0, "summe_r": 0.0, "summe_eur": 0.0})
        m["trades"] += 1
        m["summe_r"] = round(m["summe_r"] + t["r"], 2)
        m["summe_eur"] = round(m["summe_eur"] + (t["eur"] or 0), 2)
    return aus


def stand() -> dict:
    """Alles fürs HUD: Einstellungen, Trades (neueste zuerst), Auswertung 7 Tage und gesamt."""
    daten = _laden()
    return {"einstellungen": daten["einstellungen"], "trades": list(reversed(daten["trades"]))[:200],
            "woche": auswertung(7), "gesamt": auswertung()}


# ------------------------------------------------------------------ Sätze für Chat und Sprache


def _r_text(r: float) -> str:
    return ("+" if r >= 0 else "−") + f"{abs(r):.2f}".replace(".", ",") + " R"


def _satz_geschlossen(t: dict, stand: float, e: dict, warnungen: list[str]) -> str:
    satz = (f"Trade {t['id']} ({t['symbol']}) geschlossen, Sir: {_r_text(t['r'])}, {_eur(t['eur'], e)}. "
            f"Kontostand im Tagebuch: {_eur(stand, e)}.")
    return satz + ("".join(" " + w for w in warnungen))


def satz_eingetragen(ergebnis: dict) -> str:
    t, e = ergebnis["trade"], _laden()["einstellungen"]
    satz = (f"Eingetragen, Sir: Trade {t['id']}, {t['symbol']} {'Long' if t['richtung'] == 1 else 'Short'} "
            f"bei {t['einstieg']:g}, Stopp {t['stopp']:g}" + (f", Ziel {t['ziel']:g}" if t.get("ziel") else "") +
            f". Risiko {_eur(t['risiko_eur'], e)} ({'Übungskonto' if t['modus'] == 'uebung' else 'echtes Geld'}).")
    for h in ergebnis["warnungen"] + ergebnis["hinweise"]:
        satz += " " + h
    return satz


def satz_auswertung(tage: int | None = 7) -> str:
    a = auswertung(tage)
    e = a["einstellungen"]
    wann = f"in den letzten {tage} Tagen" if tage else "insgesamt"
    if not a["trades"]:
        satz = f"Im Tagebuch gibt es {wann} noch keinen geschlossenen Trade, Sir."
    else:
        pf = a["profit_faktor"]
        pf_text = "nur Gewinner" if a["nur_gewinner"] else ("–" if pf is None else f"{pf:.2f}".replace(".", ","))
        satz = (f"{wann.capitalize()}: {a['trades']} Trades, {a['gewinner']} Gewinner "
                f"({a['trefferquote_prozent']:.0f} %), {_r_text(a['summe_r'])}, {_eur(a['summe_eur'], e)}, "
                f"Profit-Faktor {pf_text}, Sir.")
        if a["regelverstoesse"]:
            satz += f" Regelverstöße: {len(a['regelverstoesse'])} ({a['regelverstoesse'][0]})."
        if a["ohne_grund"]:
            satz += f" {a['ohne_grund']} Trades ohne Grund."
    satz += f" Kontostand {_eur(a['kontostand'], e)}, {_eur(a['abstand_grenze'], e)} über Ihrer Grenze."
    if a["offen"]:
        satz += f" Offen: {len(a['offen'])}."
    for w in a["warnungen"]:
        satz += " " + w
    return satz

"""
Marktdaten (Phase 4.1, 23.09.2026): Kurse laden, prüfen, lokal speichern.

Märkte (Wunsch von Sir: alle vier): Gold/Silber/Platin, Forex, Indizes und
Aktien, Krypto. Quellen ohne Schlüssel und ohne Kosten:
- Yahoo Finance (Chart-Schnittstelle, wie sie auch yfinance nutzt) für
  Metalle, Forex, Indizes, Aktien. Metalle dort als Future (Gold = GC=F,
  Comex) - NICHT exakt der Spot-Kurs XAUUSD beim Broker, der Verlauf ist aber
  fast gleich. 1-Stunden-Kerzen gibt es dort nur für ca. 2 Jahre.
- Binance (data-api.binance.vision) für Krypto, bis zu 1000 Kerzen je Abruf.
- Stooq als Ersatz für Tageskerzen, falls Yahoo nicht antwortet.
Für lange Historien in Broker-Qualität (8+ Jahre H1/H4): MT5_DATEN_EXPORT.bat
(tools/mt5_export.py) - liest nur Kurse aus dem laufenden MT5-Terminal, handelt nicht.

Speicher: data/trading/marktdaten.db (SQLite), Tabelle kerzen
(symbol, intervall, zeit=Unix-Sekunden UTC, open, high, low, close, volumen, quelle).
Neu geladene Kerzen ersetzen alte mit gleichem Zeitstempel (letzte Kerze kann
sich noch ändern).

Datenprüfung (qualitaet): Lücken (fehlende Kerzen außerhalb von Wochenenden),
Ausreißer (Sprünge weit über der üblichen Schwankung), kaputte Kerzen
(Hoch unter Tief usw.), Doppelte. Ohne Prüfung kein Backtest - die Sandbox
zeigt das Ergebnis an.

Keine Claude-Kosten. Netz: nur der PC (in der Cloud-Sandbox ungetestet).
"""

from __future__ import annotations

import csv
import datetime
import io
import json
import math
import os
import sqlite3
import statistics
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .trading_sandbox import Kerze, SandboxFehler

KATALOG: dict[str, dict[str, str]] = {
    # Metalle (Yahoo: Futures)
    "XAUUSD": {"name": "Gold", "markt": "metall", "yahoo": "GC=F", "stooq": "xauusd", "hinweis": "Yahoo: Gold-Future (Comex)"},
    "XAGUSD": {"name": "Silber", "markt": "metall", "yahoo": "SI=F", "stooq": "xagusd", "hinweis": "Yahoo: Silber-Future (Comex)"},
    "XPTUSD": {"name": "Platin", "markt": "metall", "yahoo": "PL=F", "stooq": "xptusd", "hinweis": "Yahoo: Platin-Future (NYMEX)"},
    # Forex
    "EURUSD": {"name": "Euro / US-Dollar", "markt": "forex", "yahoo": "EURUSD=X", "stooq": "eurusd"},
    "GBPUSD": {"name": "Pfund / US-Dollar", "markt": "forex", "yahoo": "GBPUSD=X", "stooq": "gbpusd"},
    "USDJPY": {"name": "US-Dollar / Yen", "markt": "forex", "yahoo": "JPY=X", "stooq": "usdjpy"},
    "CHFJPY": {"name": "Franken / Yen", "markt": "forex", "yahoo": "CHFJPY=X", "stooq": "chfjpy"},
    "EURCHF": {"name": "Euro / Franken", "markt": "forex", "yahoo": "EURCHF=X", "stooq": "eurchf"},
    # Indizes
    "DAX": {"name": "DAX 40", "markt": "index", "yahoo": "^GDAXI", "stooq": "^dax"},
    "SP500": {"name": "S&P 500", "markt": "index", "yahoo": "^GSPC", "stooq": "^spx"},
    "NASDAQ100": {"name": "Nasdaq 100", "markt": "index", "yahoo": "^NDX", "stooq": "^ndx"},
    "DOW": {"name": "Dow Jones", "markt": "index", "yahoo": "^DJI", "stooq": "^dji"},
    # Aktien
    "AAPL": {"name": "Apple", "markt": "aktie", "yahoo": "AAPL", "stooq": "aapl.us"},
    "MSFT": {"name": "Microsoft", "markt": "aktie", "yahoo": "MSFT", "stooq": "msft.us"},
    "NVDA": {"name": "NVIDIA", "markt": "aktie", "yahoo": "NVDA", "stooq": "nvda.us"},
    "TSLA": {"name": "Tesla", "markt": "aktie", "yahoo": "TSLA", "stooq": "tsla.us"},
    "SAP": {"name": "SAP", "markt": "aktie", "yahoo": "SAP.DE", "stooq": "sap.de"},
    # Krypto
    "BTCUSD": {"name": "Bitcoin", "markt": "krypto", "binance": "BTCUSDT", "yahoo": "BTC-USD"},
    "ETHUSD": {"name": "Ethereum", "markt": "krypto", "binance": "ETHUSDT", "yahoo": "ETH-USD"},
    "SOLUSD": {"name": "Solana", "markt": "krypto", "binance": "SOLUSDT", "yahoo": "SOL-USD"},
}
MARKT_NAMEN = {"metall": "Gold und Silber", "forex": "Forex", "index": "Indizes", "aktie": "Aktien", "krypto": "Krypto"}

INTERVALLE = {"1h": 3600, "4h": 14400, "1d": 86400, "1wk": 604800}
# Wie lange gilt ein Abruf als frisch (Sekunden)
FRISCH_S = {"1h": 900, "4h": 900, "1d": 6 * 3600, "1wk": 24 * 3600}
YAHOO_RANGE = {"1h": "730d", "1d": "10y", "1wk": "max"}
BINANCE_INTERVALL = {"1h": "1h", "4h": "4h", "1d": "1d", "1wk": "1w"}
BINANCE_SEITEN = {"1h": 18, "4h": 12, "1d": 4, "1wk": 1}  # je 1000 Kerzen (1h: ca. 2 Jahre)
TIMEOUT_S = 20
AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Jarvis/1.0"

_lock = threading.Lock()
_hintergrund: dict[str, Any] = {"running": False, "started_at": None, "finished_at": None, "fortschritt": None,
                                "ergebnisse": [], "error": None}


class MarktFehler(SandboxFehler):
    pass


# ------------------------------------------------------------------ Speicher


def db_pfad() -> Path:
    roh = os.getenv("MARKT_DB_PATH")
    pfad = Path(roh) if roh else Path(__file__).resolve().parents[2] / "data" / "trading" / "marktdaten.db"
    pfad.parent.mkdir(parents=True, exist_ok=True)
    return pfad


def _verbindung() -> sqlite3.Connection:
    con = sqlite3.connect(db_pfad(), timeout=30)
    con.execute("""CREATE TABLE IF NOT EXISTS kerzen (
        symbol TEXT, intervall TEXT, zeit INTEGER, open REAL, high REAL, low REAL, close REAL,
        volumen REAL, quelle TEXT, PRIMARY KEY (symbol, intervall, zeit))""")
    con.execute("""CREATE TABLE IF NOT EXISTS abrufe (
        symbol TEXT, intervall TEXT, zeit INTEGER, quelle TEXT, anzahl INTEGER, fehler TEXT)""")
    return con


def speichern(symbol: str, intervall: str, kerzen: list[dict], quelle: str) -> int:
    if not kerzen:
        return 0
    with _lock:
        con = _verbindung()
        try:
            con.executemany(
                "INSERT OR REPLACE INTO kerzen VALUES (?,?,?,?,?,?,?,?,?)",
                [(symbol, intervall, int(k["zeit"]), k["open"], k["high"], k["low"], k["close"],
                  k.get("volumen"), quelle) for k in kerzen],
            )
            con.commit()
        finally:
            con.close()
    return len(kerzen)


def _abruf_merken(symbol: str, intervall: str, quelle: str, anzahl: int, fehler: str | None) -> None:
    with _lock:
        con = _verbindung()
        try:
            con.execute("INSERT INTO abrufe VALUES (?,?,?,?,?,?)", (symbol, intervall, int(time.time()), quelle, anzahl, fehler))
            con.commit()
        finally:
            con.close()


def letzter_abruf(symbol: str, intervall: str) -> dict | None:
    con = _verbindung()
    try:
        zeile = con.execute("SELECT zeit, quelle, anzahl, fehler FROM abrufe WHERE symbol=? AND intervall=? "
                            "AND fehler IS NULL ORDER BY zeit DESC LIMIT 1", (symbol, intervall)).fetchone()
    finally:
        con.close()
    return {"zeit": zeile[0], "quelle": zeile[1], "anzahl": zeile[2]} if zeile else None


def laden(symbol: str, intervall: str, anzahl: int | None = None, bis: int | None = None) -> list[dict]:
    """Gespeicherte Kerzen, älteste zuerst. 4h wird aus 1h gebaut, falls keine eigenen 4h-Daten da sind."""
    con = _verbindung()
    try:
        sql = "SELECT zeit, open, high, low, close, volumen FROM kerzen WHERE symbol=? AND intervall=?"
        werte: list[Any] = [symbol, intervall]
        if bis:
            sql += " AND zeit<=?"
            werte.append(int(bis))
        sql += " ORDER BY zeit DESC"
        if anzahl:
            sql += " LIMIT ?"
            werte.append(int(anzahl) * (4 if intervall == "4h" else 1))
        zeilen = con.execute(sql, werte).fetchall()
    finally:
        con.close()
    kerzen = [{"zeit": z[0], "open": z[1], "high": z[2], "low": z[3], "close": z[4], "volumen": z[5]} for z in reversed(zeilen)]
    if intervall == "4h" and not kerzen:
        kerzen = zusammenfassen(laden(symbol, "1h", (anzahl or 0) * 4 or None, bis), 14400)
    return kerzen[-anzahl:] if anzahl else kerzen


def zusammenfassen(kerzen: list[dict], sekunden: int) -> list[dict]:
    """Stundenkerzen zu größeren Kerzen (z.B. 4h, UTC-Blöcke 00/04/08 ...)."""
    aus: list[dict] = []
    for k in kerzen:
        block = int(k["zeit"]) // sekunden * sekunden
        if aus and aus[-1]["zeit"] == block:
            a = aus[-1]
            a["high"], a["low"], a["close"] = max(a["high"], k["high"]), min(a["low"], k["low"]), k["close"]
            a["volumen"] = (a.get("volumen") or 0) + (k.get("volumen") or 0)
        else:
            aus.append({"zeit": block, "open": k["open"], "high": k["high"], "low": k["low"], "close": k["close"],
                        "volumen": k.get("volumen")})
    return aus


# -------------------------------------------------------------------- Abruf


def _holen(url: str) -> bytes:
    anfrage = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "application/json,text/csv,*/*"})
    with urllib.request.urlopen(anfrage, timeout=TIMEOUT_S) as antwort:  # noqa: S310 - feste https-Adressen
        return antwort.read(30_000_000)


def yahoo_lesen(daten: dict) -> list[dict]:
    """Antwort der Yahoo-Chart-Schnittstelle -> Kerzen (Lücken mit null werden übersprungen)."""
    try:
        ergebnis = daten["chart"]["result"][0]
    except (KeyError, IndexError, TypeError) as exc:
        fehler = (daten.get("chart") or {}).get("error") if isinstance(daten, dict) else None
        raise MarktFehler(f"Yahoo: keine Daten ({(fehler or {}).get('description', 'unbekannte Antwort')})") from exc
    zeiten = ergebnis.get("timestamp") or []
    q = ((ergebnis.get("indicators") or {}).get("quote") or [{}])[0]
    kerzen = []
    for i, t in enumerate(zeiten):
        try:
            o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        except (KeyError, IndexError):
            continue
        if None in (o, h, l, c):
            continue
        v = (q.get("volume") or [None] * len(zeiten))[i]
        kerzen.append({"zeit": int(t), "open": float(o), "high": float(h), "low": float(l), "close": float(c),
                       "volumen": float(v) if v is not None else None})
    return kerzen


def binance_lesen(daten: list) -> list[dict]:
    return [{"zeit": int(z[0]) // 1000, "open": float(z[1]), "high": float(z[2]), "low": float(z[3]),
             "close": float(z[4]), "volumen": float(z[5])} for z in daten]


def stooq_lesen(text: str) -> list[dict]:
    leser = csv.DictReader(io.StringIO(text))
    kerzen = []
    for zeile in leser:
        try:
            tag = datetime.datetime.strptime(zeile["Date"], "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
            kerzen.append({"zeit": int(tag.timestamp()), "open": float(zeile["Open"]), "high": float(zeile["High"]),
                           "low": float(zeile["Low"]), "close": float(zeile["Close"]),
                           "volumen": float(zeile["Volume"]) if zeile.get("Volume") else None})
        except (KeyError, ValueError, TypeError):
            continue
    if not kerzen:
        raise MarktFehler("Stooq: keine lesbaren Daten (evtl. Zugang gesperrt).")
    return kerzen


def _yahoo(symbol_yahoo: str, intervall: str, holen: Callable[[str], bytes]) -> list[dict]:
    yi = "1h" if intervall in ("1h", "4h") else intervall
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol_yahoo)}"
           f"?interval={yi}&range={YAHOO_RANGE['1h' if yi == '1h' else yi]}&includePrePost=false")
    kerzen = yahoo_lesen(json.loads(holen(url)))
    return zusammenfassen(kerzen, 14400) if intervall == "4h" else kerzen


def _binance(symbol_binance: str, intervall: str, holen: Callable[[str], bytes]) -> list[dict]:
    alle: list[dict] = []
    ende = None
    for _ in range(BINANCE_SEITEN[intervall]):
        url = (f"https://data-api.binance.vision/api/v3/klines?symbol={symbol_binance}"
               f"&interval={BINANCE_INTERVALL[intervall]}&limit=1000" + (f"&endTime={ende}" if ende else ""))
        teil = binance_lesen(json.loads(holen(url)))
        if not teil:
            break
        alle = teil + alle
        ende = teil[0]["zeit"] * 1000 - 1
        if len(teil) < 1000:
            break
    return alle


def _stooq(symbol_stooq: str, intervall: str, holen: Callable[[str], bytes]) -> list[dict]:
    if intervall not in ("1d", "1wk"):
        raise MarktFehler("Stooq liefert hier nur Tages- und Wochenkerzen.")
    url = f"https://stooq.com/q/d/l/?s={urllib.parse.quote(symbol_stooq)}&i={'d' if intervall == '1d' else 'w'}"
    return stooq_lesen(holen(url).decode("utf-8", errors="replace"))


def symbol_pruefen(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if s not in KATALOG:
        raise MarktFehler(f'Unbekannter Markt "{symbol}". Verfügbar: {", ".join(KATALOG)}')
    return s


def intervall_pruefen(intervall: str) -> str:
    i = (intervall or "").strip().lower()
    i = {"h1": "1h", "h4": "4h", "d1": "1d", "w1": "1wk", "1w": "1wk"}.get(i, i)
    if i not in INTERVALLE:
        raise MarktFehler(f'Unbekanntes Intervall "{intervall}". Erlaubt: {", ".join(INTERVALLE)}')
    return i


def aktualisieren(symbol: str, intervall: str, erzwingen: bool = False,
                  holen: Callable[[str], bytes] | None = None) -> dict:
    """Neue Kerzen laden (wenn nicht frisch) und speichern. Quelle je Markt, mit Ersatzquelle."""
    symbol, intervall = symbol_pruefen(symbol), intervall_pruefen(intervall)
    holen = holen or _holen
    letzter = letzter_abruf(symbol, intervall)
    if letzter and not erzwingen and time.time() - letzter["zeit"] < FRISCH_S[intervall]:
        return {"symbol": symbol, "intervall": intervall, "neu": 0, "quelle": letzter["quelle"], "frisch": True}
    eintrag = KATALOG[symbol]
    versuche: list[tuple[str, Callable]] = []
    if "binance" in eintrag:
        versuche.append(("binance", lambda: _binance(eintrag["binance"], intervall, holen)))
    if "yahoo" in eintrag:
        versuche.append(("yahoo", lambda: _yahoo(eintrag["yahoo"], intervall, holen)))
    if "stooq" in eintrag and intervall in ("1d", "1wk"):
        versuche.append(("stooq", lambda: _stooq(eintrag["stooq"], intervall, holen)))
    fehler = []
    for quelle, aufruf in versuche:
        try:
            kerzen = aufruf()
            if not kerzen:
                raise MarktFehler("leere Antwort")
        except Exception as exc:  # noqa: BLE001 - nächste Quelle versuchen
            fehler.append(f"{quelle}: {exc}")
            _abruf_merken(symbol, intervall, quelle, 0, str(exc)[:300])
            continue
        # 4h aus 1h-Quellen: letzte Stundenkerzen zusätzlich als 1h speichern (für Paper-Trading-Prüfung)
        anzahl = speichern(symbol, intervall, kerzen, quelle)
        _abruf_merken(symbol, intervall, quelle, anzahl, None)
        return {"symbol": symbol, "intervall": intervall, "neu": anzahl, "quelle": quelle, "frisch": False,
                "fehler_vorher": fehler}
    raise MarktFehler(f"{symbol} {intervall}: keine Quelle erreichbar ({' | '.join(fehler) or 'keine Quelle'})")


def kerzen(symbol: str, intervall: str, anzahl: int = 500, aktualisieren_erlaubt: bool = True,
           holen: Callable[[str], bytes] | None = None) -> dict:
    symbol, intervall = symbol_pruefen(symbol), intervall_pruefen(intervall)
    info = None
    if aktualisieren_erlaubt:
        try:
            info = aktualisieren(symbol, intervall, holen=holen)
        except MarktFehler as exc:
            info = {"fehler": str(exc)}
    liste = laden(symbol, intervall, max(10, min(int(anzahl or 500), 20000)))
    if not liste:
        raise MarktFehler(f"Keine Kursdaten für {symbol} {intervall} gespeichert. {(info or {}).get('fehler', '')}".strip())
    return {"symbol": symbol, "name": KATALOG[symbol]["name"], "markt": KATALOG[symbol]["markt"],
            "intervall": intervall, "hinweis": KATALOG[symbol].get("hinweis"), "abruf": info,
            "kerzen": liste, "qualitaet": qualitaet(liste, intervall, KATALOG[symbol]["markt"])}


# ----------------------------------------------------------------- Prüfung


def _wochenende_dazwischen(t1: int, t2: int) -> bool:
    a = datetime.datetime.fromtimestamp(t1, datetime.timezone.utc)
    b = datetime.datetime.fromtimestamp(t2, datetime.timezone.utc)
    tag = a
    while tag <= b:
        if tag.weekday() >= 5:
            return True
        tag += datetime.timedelta(days=1)
    return False


def qualitaet(kerzen: list[dict], intervall: str, markt: str = "forex") -> dict:
    """Lücken, Ausreißer, kaputte Kerzen, Doppelte. Nur Meldung - nichts wird verändert."""
    schritt = INTERVALLE.get(intervall, 3600)
    kaputt = [k["zeit"] for k in kerzen
              if min(k["open"], k["high"], k["low"], k["close"]) <= 0 or k["high"] < k["low"]
              or k["high"] < max(k["open"], k["close"]) - 1e-12 or k["low"] > min(k["open"], k["close"]) + 1e-12]
    zeiten = [k["zeit"] for k in kerzen]
    doppelt = len(zeiten) - len(set(zeiten))
    luecken = []
    for a, b in zip(kerzen, kerzen[1:]):
        abstand = b["zeit"] - a["zeit"]
        if abstand <= schritt * 1.5:
            continue
        if markt != "krypto" and _wochenende_dazwischen(a["zeit"], b["zeit"]) and abstand <= 4 * 86400:
            continue  # Wochenende ist keine Lücke
        if markt != "krypto" and intervall in ("1h", "4h") and abstand <= 26 * 3600:
            continue  # Handelspause über Nacht (Indizes, Aktien, Futures)
        if intervall == "1d" and abstand <= 4 * 86400:
            continue  # Feiertag
        luecken.append({"von": a["zeit"], "bis": b["zeit"], "fehlend_ca": int(abstand / schritt) - 1})
    renditen = [abs(math.log(b["close"] / a["close"])) for a, b in zip(kerzen, kerzen[1:]) if a["close"] > 0 and b["close"] > 0]
    ausreisser = []
    if len(renditen) >= 30:
        typisch = statistics.median(renditen) or 1e-9
        grenze = max(typisch * 12, 0.02 if intervall in ("1h", "4h") else 0.08)
        for k_vor, k, r in zip(kerzen, kerzen[1:], renditen):
            if r > grenze:
                ausreisser.append({"zeit": k["zeit"], "sprung_prozent": round((math.exp(r) - 1) * 100, 2)})
    probleme = len(kaputt) + doppelt + len(luecken) + len(ausreisser)
    urteil = "gut" if probleme == 0 else ("brauchbar" if len(kaputt) == 0 and len(luecken) <= 5 and len(ausreisser) <= 3 else "prüfen")
    return {"kerzen": len(kerzen), "kaputte": len(kaputt), "doppelte": doppelt, "luecken": luecken[:20],
            "luecken_anzahl": len(luecken), "ausreisser": ausreisser[:20], "ausreisser_anzahl": len(ausreisser),
            "urteil": urteil}


# --------------------------------------------------------- für die Sandbox


def zeit_text(zeit: int) -> str:
    return datetime.datetime.fromtimestamp(int(zeit), datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")


def als_sandbox_kerzen(symbol: str, intervall: str, anzahl: int = 20000) -> list[Kerze]:
    liste = laden(symbol_pruefen(symbol), intervall_pruefen(intervall), anzahl)
    if len(liste) < 50:
        raise MarktFehler(f"Zu wenige gespeicherte Kerzen für {symbol} {intervall} ({len(liste)}). "
                          "Erst auf der Markt-Seite laden oder 'Alle Märkte laden' drücken.")
    return [Kerze(zeit_text(k["zeit"]), k["open"], k["high"], k["low"], k["close"]) for k in liste]


def datenquellen() -> list[dict]:
    """Gespeicherte Märkte als Datenquellen für die Sandbox ('markt/XAUUSD/1h')."""
    con = _verbindung()
    try:
        zeilen = con.execute("SELECT symbol, intervall, COUNT(*), MIN(zeit), MAX(zeit) FROM kerzen "
                             "GROUP BY symbol, intervall ORDER BY symbol, intervall").fetchall()
    finally:
        con.close()
    quellen = []
    vorhanden = set()
    for s, i, n, von, bis in zeilen:
        vorhanden.add((s, i))
        quellen.append({"name": f"markt/{s}/{i}", "ort": "markt", "kerzen": n, "von": zeit_text(von), "bis": zeit_text(bis),
                        "hinweis": f"{KATALOG.get(s, {}).get('name', s)}, {i}"})
    for s, i in list(vorhanden):
        if i == "1h" and (s, "4h") not in vorhanden:
            quellen.append({"name": f"markt/{s}/4h", "ort": "markt", "hinweis": f"{KATALOG.get(s, {}).get('name', s)}, 4h (aus 1h gebaut)"})
    return quellen


def letzter_kurs(symbol: str) -> dict | None:
    for intervall in ("1h", "1d"):
        liste = laden(symbol, intervall, 1)
        if liste:
            return {"symbol": symbol, "kurs": liste[-1]["close"], "zeit": liste[-1]["zeit"], "intervall": intervall}
    return None


def uebersicht() -> list[dict]:
    """Letzter Kurs und Veränderung zum Vortag je Markt - nur aus dem Speicher (kein Netz)."""
    aus = []
    for s, e in KATALOG.items():
        tage = laden(s, "1d", 2)
        stunde = laden(s, "1h", 1)
        kurs = (stunde or tage or [{}])[-1].get("close")
        vorher = tage[-2]["close"] if len(tage) >= 2 else None
        aus.append({"symbol": s, "name": e["name"], "markt": e["markt"], "kurs": kurs,
                    "veraenderung_prozent": round((kurs - vorher) / vorher * 100, 2) if kurs and vorher else None,
                    "stand": zeit_text((stunde or tage)[-1]["zeit"]) if (stunde or tage) else None})
    return aus


# ---------------------------------------------------- alle Märkte (Hintergrund)


def alle_laden_status() -> dict:
    with _lock:
        return json.loads(json.dumps(_hintergrund))


def _alle_laden(intervalle: list[str], pause_s: float) -> None:
    ergebnisse = []
    try:
        schritte = [(s, i) for s in KATALOG for i in intervalle]
        for n, (s, i) in enumerate(schritte, 1):
            with _lock:
                _hintergrund["fortschritt"] = {"schritt": n, "von": len(schritte), "markt": s, "intervall": i}
            try:
                ergebnisse.append(aktualisieren(s, i))
            except MarktFehler as exc:
                ergebnisse.append({"symbol": s, "intervall": i, "fehler": str(exc)})
            time.sleep(pause_s)  # gedrosselt: PC und Quellen schonen
        fehler = None
    except Exception as exc:  # noqa: BLE001
        fehler = str(exc)
    with _lock:
        _hintergrund.update(running=False, finished_at=datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                            ergebnisse=ergebnisse, error=fehler, fortschritt=None)


def alle_laden_starten(intervalle: list[str] | None = None, pause_s: float = 0.6) -> tuple[bool, dict]:
    intervalle = [intervall_pruefen(i) for i in (intervalle or ["1d", "1h"])]
    with _lock:
        if _hintergrund["running"]:
            return False, json.loads(json.dumps(_hintergrund))
        _hintergrund.update(running=True, started_at=datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                            finished_at=None, ergebnisse=[], error=None)
    threading.Thread(target=_alle_laden, args=(intervalle, pause_s), daemon=True).start()
    return True, alle_laden_status()


# ------------------------------------------------ Kursfrage im Chat (26.09.2026)
#
# "Wie steht Gold?" wird in app/alltag.py erkannt und hier OHNE Claude beantwortet.
# Vorher ging die Frage an das Modell, und das nannte Kurse aus seinem Trainingswissen
# (Stand 2024). Leichter Abruf: nur die letzten Tage als Stundenkerzen (Yahoo range=5d,
# Binance limit=72) statt der ganzen Historie - dauert ca. 1 Sekunde, kostet nichts.

KURS_FRISCH_S = 5 * 60
_WOCHENTAG_KURZ = ["Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So."]


def _berlin():
    from dateutil import tz  # wie app/alltag.py: dateutil bringt die Zeitzonen unter Windows mit
    return tz.gettz("Europe/Berlin") or tz.tzlocal()


def kurs_holen(symbol: str, holen: Callable[[str], bytes] | None = None) -> dict:
    """Die letzten Stundenkerzen frisch laden und speichern (höchstens alle 5 Minuten)."""
    symbol = symbol_pruefen(symbol)
    holen = holen or _holen
    letzter = letzter_abruf(symbol, "1h")
    if letzter and time.time() - letzter["zeit"] < KURS_FRISCH_S:
        return {"neu": 0, "quelle": letzter["quelle"], "frisch": True}
    e = KATALOG[symbol]
    versuche: list[tuple[str, Callable[[], list[dict]]]] = []
    if "binance" in e:
        versuche.append(("binance", lambda: binance_lesen(json.loads(holen(
            f"https://data-api.binance.vision/api/v3/klines?symbol={e['binance']}&interval=1h&limit=72")))))
    if "yahoo" in e:
        versuche.append(("yahoo", lambda: yahoo_lesen(json.loads(holen(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(e['yahoo'])}"
            f"?interval=1h&range=5d&includePrePost=false")))))
    fehler = []
    for quelle, aufruf in versuche:
        try:
            liste = aufruf()
            if not liste:
                raise MarktFehler("leere Antwort")
        except Exception as exc:  # noqa: BLE001 - nächste Quelle versuchen
            fehler.append(f"{quelle}: {exc}")
            _abruf_merken(symbol, "1h", quelle, 0, str(exc)[:300])
            continue
        anzahl = speichern(symbol, "1h", liste, quelle)
        _abruf_merken(symbol, "1h", quelle, anzahl, None)
        return {"neu": anzahl, "quelle": quelle, "frisch": False}
    raise MarktFehler(f"{symbol}: keine Quelle erreichbar ({' | '.join(fehler) or 'keine Quelle'})")


def _zahl(wert: float, stellen: int) -> str:
    text = f"{wert:,.{stellen}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _stellen(symbol: str, kurs: float) -> int:
    if KATALOG[symbol]["markt"] == "forex":
        return 3 if "JPY" in symbol else 4
    return 2 if kurs < 100_000 else 0


def _einheit(symbol: str) -> str:
    markt = KATALOG[symbol]["markt"]
    if symbol == "SAP":
        return " €"
    return {"metall": " $ je Unze", "krypto": " $", "aktie": " $", "index": " Punkte"}.get(markt, "")


def kurs_antwort(symbol: str, euro: bool = False, holen: Callable[[str], bytes] | None = None,
                 jetzt: float | None = None) -> str:
    """Satz für den Chat: letzter Kurs, Veränderung zum Vortag, Stand, Quelle. Kein Claude."""
    symbol = symbol_pruefen(symbol)
    e = KATALOG[symbol]
    jetzt = jetzt or time.time()
    abruf_fehler = None
    try:
        abruf = kurs_holen(symbol, holen)
    except MarktFehler as exc:
        abruf, abruf_fehler = {}, str(exc)
    stunden = laden(symbol, "1h", 24 * 8)
    if not stunden:
        tage = laden(symbol, "1d", 2)
        if not tage:
            raise MarktFehler(f"Für {e['name']} ist kein Kurs gespeichert und der Abruf ging nicht"
                              f"{': ' + abruf_fehler if abruf_fehler else ''}.")
        stunden, dauer = tage, 86400
    else:
        dauer = 3600
    letzte = stunden[-1]
    kurs = letzte["close"]
    ende = min(letzte["zeit"] + dauer, int(jetzt))
    zone = _berlin()
    zeit = datetime.datetime.fromtimestamp(ende, zone)
    # Vortag: letzter Schlusskurs eines früheren Kalendertags (Berliner Zeit)
    tag_letzte = datetime.datetime.fromtimestamp(letzte["zeit"], zone).date()
    vorher = next((k["close"] for k in reversed(stunden)
                   if datetime.datetime.fromtimestamp(k["zeit"], zone).date() < tag_letzte), None)

    satz = f"{e['name']} steht bei {_zahl(kurs, _stellen(symbol, kurs))}{_einheit(symbol)}, Sir"
    if vorher:
        prozent = (kurs - vorher) / vorher * 100
        satz += f" ({'+' if prozent >= 0 else '−'}{_zahl(abs(prozent), 2)} % zum Vortag)"
    satz += f". Stand: {_WOCHENTAG_KURZ[zeit.weekday()]} {zeit:%d.%m.}, {zeit:%H:%M} Uhr."
    if euro and _einheit(symbol).strip().startswith("$"):
        try:
            if symbol != "EURUSD":
                kurs_holen("EURUSD", holen)
            eurusd = (laden("EURUSD", "1h", 1) or laden("EURUSD", "1d", 1))[-1]["close"]
            satz += f" Das sind etwa {_zahl(kurs / eurusd, 2)} €" + (" je Unze." if e["markt"] == "metall" else ".")
        except (MarktFehler, IndexError, ZeroDivisionError):
            satz += " In Euro kann ich es gerade nicht umrechnen."
    alt_s = jetzt - ende
    if alt_s > 3 * 3600:
        if e["markt"] == "krypto" or not abruf_fehler:
            satz += " Der Markt handelt gerade nicht, das ist der letzte Kurs." if e["markt"] != "krypto" else \
                " Achtung, der Kurs ist älter als drei Stunden."
    if abruf_fehler:
        satz += " Neu laden ging gerade nicht, das ist der zuletzt gespeicherte Kurs."
    quelle = (abruf or {}).get("quelle") or (letzter_abruf(symbol, "1h") or {}).get("quelle") or "gespeichert"
    hinweis = e.get("hinweis")
    satz += f" Quelle: {hinweis or quelle.capitalize()}" + (", weicht vom Spot-Kurs beim Broker leicht ab" if e["markt"] == "metall" else "")
    satz += ". Keine Anlageberatung."
    return satz


def katalog() -> list[dict]:
    return [{"symbol": s, **{k: v for k, v in e.items() if k in ("name", "markt", "hinweis")},
             "markt_name": MARKT_NAMEN[e["markt"]]} for s, e in KATALOG.items()]

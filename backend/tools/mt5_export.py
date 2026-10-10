"""
Kursdaten aus dem laufenden MetaTrader-5-Terminal exportieren (Phase 4.1, 23.09.2026).

NUR LESEN: Dieses Skript ruft ausschließlich Kurs-Funktionen auf
(copy_rates_range, symbol_info). Es gibt keine Order-, Positions- oder
Konto-Änderungen - es kann nichts handeln.

Wozu: Yahoo liefert 1-Stunden-Kerzen nur für ca. 2 Jahre und für Gold/Silber
nur Futures. Das Bot-Feedback (Vault, 23.09.2026) zeigt, dass man die Bots über
8+ Jahre prüfen muss. Die Broker-Historie aus MT5 hat genau die Kurse, mit
denen die Bots handeln.

Aufruf (MT5 muss laufen und eingeloggt sein, Demo reicht):
    MT5_DATEN_EXPORT.bat
    oder: python backend\\tools\\mt5_export.py --von 2017-01-01 --symbole XAUUSD,XAGUSD --tf H1,H4

Ergebnis: Jarvis\\data\\trading\\SYMBOL_TF.csv (erscheint sofort in der
Trading-Sandbox) und data\\trading\\mt5_spreads.json (typischer Spread je
Markt - als Kosten in der Sandbox eintragen).

Protokoll (24.09.2026): Alles, was im Fenster steht, landet zusätzlich in
data\trading\mt5_export_log.txt - Claude liest es selbst.
Genutzt wird das laufende MetaTrader 5 (seit 24.09.2026 das allgemeine
MetaTrader 5 mit MetaQuotes-Demokonto). Findet das Paket kein Terminal, sucht
das Skript terminal64.exe unter "Programme".

Hinweis: Wie viel Historie kommt, hängt von der MT5-Einstellung "Max. Balken
im Chart" ab (Extras > Optionen > Charts) - ggf. auf "Unbegrenzt" stellen und
den Chart des Symbols einmal weit zurückscrollen.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import glob
import json
import os
import statistics
import sys
from pathlib import Path

ZIEL = Path(__file__).resolve().parents[2] / "data" / "trading"
STANDARD_SYMBOLE = ["XAUUSD", "XAGUSD", "XPTUSD", "EURUSD", "GBPUSD", "USDJPY", "CHFJPY"]
STANDARD_TF = ["H1", "H4", "D1"]


class _Protokoll:
    """Schreibt alles, was ausgegeben wird, auch in eine Datei."""

    def __init__(self, datei: Path):
        datei.parent.mkdir(parents=True, exist_ok=True)
        self.datei = datei.open("w", encoding="utf-8")
        self.konsole = sys.stdout
        self.datei.write(f"MT5-Export {datetime.datetime.now():%d.%m.%Y %H:%M}\n")

    def write(self, text):
        self.konsole.write(text)
        self.datei.write(text)
        self.datei.flush()

    def flush(self):
        self.konsole.flush()
        self.datei.flush()


def _terminal_pfade() -> list[str]:
    """Mögliche Orte von terminal64.exe (Broker-Versionen heißen z. B. "Pepperstone MetaTrader 5")."""
    orte = []
    for basis in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
        if basis:
            orte += glob.glob(os.path.join(basis, "*", "terminal64.exe"))
            orte += glob.glob(os.path.join(basis, "Programs", "*", "terminal64.exe"))
    return sorted(set(orte))


def _verbinden(mt5) -> bool:
    """Zuerst das Terminal, das gerade läuft bzw. als Standard eingetragen ist.
    Entscheidung Sir (24.09.2026): genutzt wird das allgemeine MetaTrader 5
    (MetaQuotes-Demo). Nur wenn das nicht geht, werden andere Terminals versucht."""
    if mt5.initialize():
        return True
    print(f"MT5 ohne Pfad nicht erreichbar: {mt5.last_error()}")
    for pfad in _terminal_pfade():
        print(f"Versuche Terminal: {pfad}")
        if mt5.initialize(path=pfad, timeout=60_000):
            return True
        print(f"  nicht erreichbar: {mt5.last_error()}")
    return False


def _broker_symbol(mt5, gesucht: str) -> str | None:
    if mt5.symbol_info(gesucht) is not None:
        return gesucht
    kandidaten = [s.name for s in (mt5.symbols_get(f"*{gesucht}*") or [])]
    if not kandidaten:
        return None
    # z. B. EURUSD.p vor Exoten wie EURUSDx oder Indizes, die EURUSD nur enthalten
    g = gesucht.upper()
    kandidaten.sort(key=lambda n: (not n.upper().startswith(g),
                                   not (n.upper() == g or n.upper()[len(g):].startswith(".")), len(n), n))
    return kandidaten[0]


def main() -> int:
    sys.stdout = _Protokoll(ZIEL / "mt5_export_log.txt")
    parser = argparse.ArgumentParser(description="MT5-Kurse als CSV exportieren (nur lesen)")
    parser.add_argument("--von", default="2015-01-01")
    parser.add_argument("--symbole", default=",".join(STANDARD_SYMBOLE))
    parser.add_argument("--tf", default=",".join(STANDARD_TF))
    args = parser.parse_args()

    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("Das Paket MetaTrader5 fehlt in diesem Python.")
        print("Einmal ausführen:  python -m pip install MetaTrader5")
        print("(Es ist dasselbe Paket, das die Bots benutzen.)")
        return 1

    zeitrahmen = {"M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1,
                  "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}
    if not _verbinden(mt5):
        print("MT5 nicht erreichbar - MetaTrader starten, einloggen und die .bat noch einmal starten.")
        return 1
    konto = mt5.account_info()
    terminal = mt5.terminal_info()
    if terminal is not None:
        print(f"Terminal: {terminal.name} ({terminal.path}), verbunden: {terminal.connected}")
    if konto is not None:
        art = {0: "Demo", 1: "Wettbewerb", 2: "Echtgeld"}.get(getattr(konto, "trade_mode", -1), "?")
        print(f"Konto: {konto.server}, Art: {art} (es wird nur gelesen)")
    ZIEL.mkdir(parents=True, exist_ok=True)
    von = datetime.datetime.fromisoformat(args.von).replace(tzinfo=datetime.timezone.utc)
    bis = datetime.datetime.now(datetime.timezone.utc)
    spreads = {}
    try:
        for gesucht in [s.strip() for s in args.symbole.split(",") if s.strip()]:
            symbol = _broker_symbol(mt5, gesucht)
            if symbol is None:
                print(f"{gesucht}: beim Broker nicht gefunden - übersprungen.")
                continue
            if symbol != gesucht:
                print(f"{gesucht}: nutze Broker-Namen {symbol}")
            mt5.symbol_select(symbol, True)
            info = mt5.symbol_info(symbol)
            for tf in [t.strip().upper() for t in args.tf.split(",") if t.strip()]:
                if tf not in zeitrahmen:
                    print(f"Zeitrahmen {tf} unbekannt - erlaubt: {', '.join(zeitrahmen)}")
                    continue
                kurse = mt5.copy_rates_range(symbol, zeitrahmen[tf], von, bis)
                if kurse is None or len(kurse) == 0:
                    print(f"{symbol} {tf}: keine Daten ({mt5.last_error()})")
                    continue
                datei = ZIEL / f"{gesucht}_{tf}.csv"
                with datei.open("w", newline="", encoding="utf-8") as fh:
                    schreiber = csv.writer(fh)
                    schreiber.writerow(["time", "open", "high", "low", "close", "tick_volume", "spread"])
                    for k in kurse:
                        zeit = datetime.datetime.fromtimestamp(int(k["time"]), datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
                        schreiber.writerow([zeit, k["open"], k["high"], k["low"], k["close"], k["tick_volume"], k["spread"]])
                erste = datetime.datetime.fromtimestamp(int(kurse[0]["time"]), datetime.timezone.utc).date()
                print(f"{symbol} {tf}: {len(kurse)} Kerzen ab {erste} -> {datei.name}")
                if tf == "H1" and info is not None:
                    median = statistics.median(int(k["spread"]) for k in kurse)
                    spreads[gesucht] = {"broker_symbol": symbol, "spread_punkte_median": median,
                                        "point": info.point, "spread_preis": round(median * info.point, 8)}
    finally:
        mt5.shutdown()
    (ZIEL / "mt5_spreads.json").write_text(json.dumps(spreads, indent=1), encoding="utf-8")
    print("\nTypischer Spread (als 'spread' in der Sandbox eintragen):")
    for s, w in spreads.items():
        print(f"  {s}: {w['spread_preis']} (= {w['spread_punkte_median']} Punkte)")
    print("\nFertig. Die Dateien stehen jetzt in der Trading-Sandbox unter 'trading/...'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

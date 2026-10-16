"""
Messung der Stimmen (P05, 16.10.2026): Fish Audio gegen Piper high gegen Piper medium.

Aufruf (auf dem Mini-PC, mit dem Python der venv, im Ordner backend):
    python stimme_messung.py                      schreibt ../data/stimme_messung.txt
    python stimme_messung.py --laeufe 5 --saetze 20 --ausgabe pfad.txt

Gemessen wird die Zeit, bis der fertige Ton da ist. Das ist die Wartezeit der
Oberfläche, denn Fish Audio und Piper liefern die Sprachdatei am Stück (kein
Streaming). "Zeit bis zum ersten Ton" und "Zeit bis zum fertigen Ton" sind
deshalb hier dasselbe.
  1. Ein Satz mit genau 80 Zeichen, je Stimme 5 Läufe (Piper: das Laden der
     Stimme wird einmal getrennt als "Laden" ausgewiesen und zählt nicht in die Läufe).
  2. Zuverlässigkeit: 20 verschiedene Sätze hintereinander, Fehler werden gezählt.
Fish Audio wird nur gemessen, wenn FISH_API_KEY gesetzt ist (wird aus der .env
geladen wie beim Backend, der Schlüssel wird nie ausgegeben). Die Messung
schickt dabei 25 kurze Sätze an Fish Audio (kostenlos bis 30.11.2026).
Dazu entstehen Hörproben: data/piper_probe_high.wav und piper_probe_medium.wav.
"""

from __future__ import annotations

import argparse
import datetime
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Callable

SATZ_80 = "Guten Morgen, Sir. Heute stehen vier Termine an, der erste beginnt um 10:30 Uhr."
assert len(SATZ_80) == 80
SAETZE = [
    "Guten Morgen, Sir.", "Es ist halb acht und die Sonne scheint.", "Heute stehen drei Termine an.",
    "Die Rechnung vom Elektriker ist noch offen.", "Der Mini-PC läuft seit vier Tagen ohne Neustart.",
    "Im Vault gibt es zweihundert neue Notizen.", "Soll ich die Nachtarbeit heute früher starten?",
    "Die Kosten liegen bei zwei Euro dreißig.", "Das Wetter bleibt bis Freitag trocken.",
    "Ihr Zug nach Köln fährt um acht Uhr zwölf.", "Ich habe drei Videos aus der Liste ausgewertet.",
    "Das Backup ist gestern Nacht fertig geworden.", "Bitte bestätigen Sie die Änderung noch einmal.",
    "Der Pod bei RunPod wurde ordnungsgemäß gelöscht.", "Auf der Einkaufsliste stehen Milch, Brot und Äpfel.",
    "Die Spracherkennung läuft jetzt lokal.", "Ich konnte dazu nichts im Vault finden.",
    "Am Samstag ist der Geburtstag von Oma.", "Die nächste Prüfung ist in zwölf Tagen.",
    "Das war alles für heute, Sir.",
]


def messen(aufruf: Callable[[], object], laeufe: int, uhr: Callable[[], float] = time.perf_counter) -> dict:
    """Führt aufruf() laeufe-mal aus und misst die Zeit in Sekunden."""
    zeiten: list[float] = []
    fehler: list[str] = []
    for _ in range(laeufe):
        start = uhr()
        try:
            aufruf()
        except Exception as exc:  # noqa: BLE001 - Fehler gehören in den Bericht
            fehler.append(str(exc)[:120])
            continue
        zeiten.append(uhr() - start)
    return {"zeiten": zeiten, "fehler": fehler}


def zeile(name: str, m: dict, laeufe: int) -> str:
    z = m["zeiten"]
    if not z:
        return f"{name:<22} keine Messung möglich ({len(m['fehler'])} Fehler: {m['fehler'][0] if m['fehler'] else '-'})"
    return (f"{name:<22} Median {statistics.median(z):5.2f} s   schnellster {min(z):5.2f} s   langsamster {max(z):5.2f} s   "
            f"({len(z)} von {laeufe} Läufen)")


def zuverlaessigkeit(aufruf: Callable[[str], object], saetze: int) -> dict:
    texte = (SAETZE * 3)[:saetze]
    fehler: list[str] = []
    start = time.perf_counter()
    for t in texte:
        try:
            aufruf(t)
        except Exception as exc:  # noqa: BLE001
            fehler.append(f"{t[:30]!r}: {str(exc)[:100]}")
    return {"gesamt": len(texte), "fehler": fehler, "dauer": time.perf_counter() - start}


def bericht_bauen(daten: dict, laeufe: int, saetze: int, jetzt: datetime.datetime | None = None) -> str:
    jetzt = jetzt or datetime.datetime.now()
    zeilen = [
        f"Stimmen-Messung vom {jetzt:%d.%m.%Y %H:%M}",
        f"Rechner: {platform.node()} ({platform.system()} {platform.machine()}), Python {platform.python_version()}",
        "",
        f"1. Zeit bis der Ton fertig ist, Satz mit {len(SATZ_80)} Zeichen, {laeufe} Läufe",
        "   (die Oberfläche bekommt die Sprachdatei am Stück, daher gleich der Zeit bis zum ersten Ton)",
        "",
    ]
    for name, d in daten.items():
        if d.get("hinweis"):
            zeilen.append(f"{name:<22} {d['hinweis']}")
            continue
        if d.get("laden") is not None:
            zeilen.append(f"{name:<22} Laden der Stimme (einmalig): {d['laden']:.2f} s")
        zeilen.append(zeile(name, d["zeit"], laeufe))
    zeilen += ["", f"2. Zuverlässigkeit: {saetze} Sätze hintereinander", ""]
    for name, d in daten.items():
        if d.get("hinweis"):
            zeilen.append(f"{name:<22} nicht gemessen")
            continue
        z = d["zuverlaessig"]
        zeilen.append(f"{name:<22} {z['gesamt'] - len(z['fehler'])} von {z['gesamt']} ohne Fehler, {z['dauer']:.1f} s insgesamt")
        zeilen += [f"{'':<22}   Fehler: {f}" for f in z["fehler"][:5]]
    zeilen += ["", "Hinweis: Piper wird auf diesem Rechner gemessen (Mini-PC, CPU). Fish Audio hängt zusätzlich vom Internet ab."]
    return "\n".join(zeilen) + "\n"


def lauf(laeufe: int, saetze: int, ausgabe: Path, probe_ordner: Path) -> str:
    from app import piper_tts, sprache

    daten: dict[str, dict] = {}

    if sprache.verfuegbar():
        daten["Fish Audio"] = {
            "zeit": messen(lambda: sprache.sprich(SATZ_80), laeufe),
            "zuverlaessig": zuverlaessigkeit(lambda t: sprache.sprich(t), saetze),
            "laden": None,
        }
    else:
        daten["Fish Audio"] = {"hinweis": "nicht gemessen (kein FISH_API_KEY)"}

    for qualitaet in piper_tts.QUALITAETEN:
        name = f"Piper {qualitaet}"
        modell = piper_tts.STANDARD_ORDNER / f"de_DE-thorsten-{qualitaet}.onnx"
        if not modell.is_file():
            daten[name] = {"hinweis": f"nicht gemessen ({modell.name} fehlt)"}
            continue
        os.environ["PIPER_STIMME"] = str(modell)
        problem = piper_tts.problem()
        if problem:
            daten[name] = {"hinweis": f"nicht gemessen ({problem})"}
            continue
        piper_tts.vergessen()
        start = time.perf_counter()
        probe = piper_tts.sprechen(SATZ_80)          # erster Aufruf lädt die Stimme
        laden = time.perf_counter() - start
        probe_ordner.mkdir(parents=True, exist_ok=True)
        (probe_ordner / f"piper_probe_{qualitaet}.wav").write_bytes(probe)
        daten[name] = {
            "laden": laden,
            "zeit": messen(lambda: piper_tts.sprechen(SATZ_80), laeufe),
            "zuverlaessig": zuverlaessigkeit(lambda t: piper_tts.sprechen(t), saetze),
        }
    os.environ.pop("PIPER_STIMME", None)

    text = bericht_bauen(daten, laeufe, saetze)
    ausgabe.parent.mkdir(parents=True, exist_ok=True)
    ausgabe.write_text(text, encoding="utf-8")
    return text


def main() -> int:
    wurzel = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from dotenv import load_dotenv

        load_dotenv()   # wie main.py: für FISH_API_KEY; der Schlüssel wird nie ausgegeben
    except ImportError:
        pass
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--laeufe", type=int, default=5)
    parser.add_argument("--saetze", type=int, default=20)
    parser.add_argument("--ausgabe", type=Path, default=wurzel / "data" / "stimme_messung.txt")
    args = parser.parse_args()
    text = lauf(args.laeufe, args.saetze, args.ausgabe, args.ausgabe.parent)
    print(text)
    print(f"Geschrieben: {args.ausgabe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

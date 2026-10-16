"""
Messung der lokalen Spracherkennung (P04, 16.10.2026): wie lange braucht
faster-whisper für 5 und für 10 Sekunden Sprache?

Aufruf (auf dem Mini-PC, mit dem Python der venv, im Ordner backend):
    python whisper_messung.py                       Modell aus WHISPER_MODELL (Standard base)
    python whisper_messung.py --modelle base small  beide nacheinander
    python whisper_messung.py --ausgabe pfad.txt    sonst ../data/whisper_messung.txt

Die Sprachproben macht Piper (P05), falls eingerichtet; sonst wird nur das
Laden des Modells gemessen. Je Länge 3 Läufe, gemessen wird die reine
Erkennung (wie in /api/sprache/erkennen). Dazu ein grober Vergleich, wie viele
Wörter richtig erkannt wurden. Threads: WHISPER_THREADS (Standard 2).
Kosten: 0 EUR, alles bleibt auf dem Rechner.
"""

from __future__ import annotations

import argparse
import datetime
import io
import os
import platform
import re
import statistics
import sys
import time
import wave
from pathlib import Path
from typing import Callable

SAETZE = [
    "Guten Morgen, Sir.", "Wie wird das Wetter heute in Köln?", "Erinnere mich morgen um acht an den Zahnarzt.",
    "Was steht heute in meinem Kalender?", "Setz Milch und Brot auf die Einkaufsliste.",
    "Wie viel habe ich diesen Monat für Claude ausgegeben?", "Spiel bitte etwas ruhige Musik im Wohnzimmer.",
    "Was habe ich gestern im Vault notiert?", "Starte heute Nacht den Code-Auftrag sieben.",
    "Mach das Licht im Büro aus.", "Wann fährt der nächste Zug nach Düsseldorf?",
    "Fasse die letzten drei TikTok-Videos zusammen.",
]


def wav_dauer(daten: bytes) -> float:
    with wave.open(io.BytesIO(daten)) as w:
        return w.getnframes() / float(w.getframerate())


def wav_verbinden(teile: list[bytes]) -> bytes:
    raus = io.BytesIO()
    with wave.open(io.BytesIO(teile[0])) as erste:
        params = erste.getparams()
    with wave.open(raus, "wb") as w:
        w.setparams(params)
        for t in teile:
            with wave.open(io.BytesIO(t)) as r:
                w.writeframes(r.readframes(r.getnframes()))
    return raus.getvalue()


def probe_bauen(sprechen: Callable[[str], bytes], ziel_s: float) -> tuple[bytes, str]:
    """Sätze aneinanderhängen, bis die Probe mindestens ziel_s Sekunden lang ist."""
    teile, texte = [], []
    for satz in SAETZE * 3:
        teile.append(sprechen(satz))
        texte.append(satz)
        if wav_dauer(wav_verbinden(teile)) >= ziel_s:
            break
    return wav_verbinden(teile), " ".join(texte)


def _woerter(text: str) -> list[str]:
    return re.findall(r"[a-zäöüß0-9]+", text.lower())


def trefferquote(soll: str, ist: str) -> float:
    """Anteil der Soll-Wörter, die in der Erkennung vorkommen (grob, ohne Reihenfolge)."""
    s, i = _woerter(soll), _woerter(ist)
    if not s:
        return 0.0
    rest = list(i)
    treffer = 0
    for w in s:
        if w in rest:
            rest.remove(w)
            treffer += 1
    return treffer / len(s)


def bericht_bauen(ergebnisse: list[dict], jetzt: datetime.datetime | None = None, threads: int = 2) -> str:
    jetzt = jetzt or datetime.datetime.now()
    zeilen = [f"Whisper-Messung vom {jetzt:%d.%m.%Y %H:%M}",
              f"Rechner: {platform.node()} ({platform.system()} {platform.machine()}), Python {platform.python_version()}, "
              f"Threads {threads}", ""]
    for e in ergebnisse:
        zeilen.append(f"Modell {e['modell']}: Laden {e['laden_s']:.1f} s")
        if e.get("hinweis"):
            zeilen.append(f"  {e['hinweis']}")
        for p in e.get("proben", []):
            if p.get("fehler"):
                zeilen.append(f"  {p['ziel_s']:>2} s Sprache: FEHLER {p['fehler']}")
                continue
            z = p["zeiten"]
            zeilen.append(f"  {p['ziel_s']:>2} s Sprache (genau {p['audio_s']:.1f} s): Erkennung Median {statistics.median(z):.2f} s, "
                          f"schnellster {min(z):.2f} s, langsamster {max(z):.2f} s ({len(z)} Läufe), "
                          f"Wörter richtig ca. {p['quote'] * 100:.0f} %")
            zeilen.append(f"     erkannt: {p['text'][:160]}")
        zeilen.append("")
    zeilen.append("Hinweis: Proben von Piper (Computerstimme) - echte Sprache am Mikrofon kann schlechter erkannt werden.")
    return "\n".join(zeilen) + "\n"


def lauf(modelle: list[str], ausgabe: Path, laeufe: int = 3) -> str:
    from app import piper_tts, stt

    proben: list[tuple[int, bytes, str]] = []
    hinweis = ""
    if piper_tts.verfuegbar():
        for ziel in (5, 10):
            daten, text = probe_bauen(piper_tts.sprechen, ziel)
            proben.append((ziel, daten, text))
    else:
        hinweis = f"Keine Sprachprobe möglich: {piper_tts.problem()} (erst PIPER MINI-PC.bat)."

    ergebnisse = []
    for modell in modelle:
        os.environ["WHISPER_MODELL"] = modell
        laden = stt.vorladen()
        eintrag = {"modell": modell, "laden_s": laden, "hinweis": hinweis, "proben": []}
        for ziel, daten, text in proben:
            zeiten, erkannt = [], ""
            try:
                for _ in range(laeufe):
                    start = time.perf_counter()
                    erkannt = stt.erkennen(daten, "audio/wav")["text"]
                    zeiten.append(time.perf_counter() - start)
            except Exception as exc:  # noqa: BLE001 - gehört in den Bericht
                eintrag["proben"].append({"ziel_s": ziel, "fehler": str(exc)[:200]})
                continue
            eintrag["proben"].append({"ziel_s": ziel, "audio_s": wav_dauer(daten), "zeiten": zeiten,
                                      "text": erkannt, "quote": trefferquote(text, erkannt)})
        ergebnisse.append(eintrag)

    text = bericht_bauen(ergebnisse, threads=stt.threads())
    ausgabe.parent.mkdir(parents=True, exist_ok=True)
    ausgabe.write_text(text, encoding="utf-8")
    return text


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    wurzel = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--modelle", nargs="+", default=[os.getenv("WHISPER_MODELL") or "base"])
    parser.add_argument("--laeufe", type=int, default=3)
    parser.add_argument("--ausgabe", type=Path, default=wurzel / "data" / "whisper_messung.txt")
    args = parser.parse_args()
    text = lauf(args.modelle, args.ausgabe, args.laeufe)
    print(text)
    print(f"Geschrieben: {args.ausgabe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

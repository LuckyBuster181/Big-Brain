"""
Suchtest für Jarvis: Wie gut findet die Vault-Suche die richtige Notiz, und
ab welcher Ähnlichkeit gilt ein Treffer als "unsicher"?

Start (Backend vorher stoppen, sonst greifen zwei Programme auf dieselbe
Chroma-Datenbank zu):
    backend\\suchtest.bat                    -> Ausgabe + suchtest_log.txt
    python -m tests.eval_search              -> Ausgabe in der Konsole
    python -m tests.eval_search --keyword-only   -> nur Stichwort-Teil, ohne
                                                   Modell und ohne Chroma

Belastung: nur Suchanfragen gegen den vorhandenen Index (kein Neuaufbau),
das Modell rechnet mit EMBEDDING_THREADS (Standard 2) Threads. Dauer < 1 Minute.

Vergleicht die Stichwort-Aufbereitung vorher (jedes Wort ab 3 Buchstaben)
mit der neuen (ohne Füllwörter, Wortstämme, seltene Wörter zählen mehr) und
schlägt eine Schwelle für "Treffer unsicher" vor.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import socket
import statistics
import sys
import time
from collections import Counter
from typing import Callable

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from rag.keywords import keywords as new_keywords  # noqa: E402

# (Frage, akzeptierte Dateien - Teilstring des Pfads reicht)
QUESTIONS: list[tuple[str, list[str]]] = [
    # --- die 8 Fragen aus dem Selbsttest vom 19.09.2026 ---
    ("Wie viel Geld darf ich pro Trade maximal riskieren?", ["06 - Risiko und Positionsgröße"]),
    ("Was passiert, wenn man nach einem Verlust zu aggressiv weiterhandelt?", ["07 - Trading Psychologie"]),
    ("Wie prüfe ich eine Handelsstrategie mit alten Kursdaten?", ["08 - Backtesting"]),
    (
        "Welche Tech-Stack-Entscheidungen habe ich für Jarvis getroffen?",
        ["Big Brain Ziele und Entwicklungsplan", "Jarvis Projekt Anweisung", "Jarvis Entwicklungslog",
         "Jarvis Big Brain Dashboard", "Tages Notizen/2026-09-19"],
    ),
    ("Welche erneuerbaren Energiequellen gibt es für Strom?", ["Energie und Stromerzeugung"]),
    ("Wie werden Erbinformationen in Zellen gespeichert?", ["Genetik und DNA", "Zellbiologie"]),
    ("Was ist der Unterschied zwischen Steuervermeidung und Steuerhinterziehung?", ["Steuern und Finanzwesen"]),
    ("Warum arbeitet Holz, wenn sich die Luftfeuchtigkeit ändert?", ["Holz"]),
    # --- neu am 20.09.2026: natürlich formuliert, nicht aus den Überschriften abgeschrieben ---
    ("Was bedeutet es, wenn eine Strategie zu stark an vergangene Daten angepasst wurde?", ["08 - Backtesting"]),
    ("Wie funktioniert ein Stop-Loss?", ["02 - Märkte und Ordertypen", "06 - Risiko und Positionsgröße"]),
    ("Was zeigt mir der RSI an?", ["04 - Technische Analyse", "M1_RSI_SPIKE_FILTER"]),
    ("Wie geben Nervenzellen Signale aneinander weiter?", ["Gehirn und Neurobiologie"]),
    ("Wie wehrt sich der Körper gegen Krankheitserreger?", ["Mikrobiologie und Infektionen", "Körper und Physiologie"]),
    ("Wie bleiben Brücken und Hochhäuser bei Erdbeben stehen?", ["Strukturen und Tragwerke"]),
    ("Wie tauschen Computer im Internet Daten aus?", ["Internet und Netzwerke"]),
    ("Was unterscheidet kurzfristiges Handeln vom langfristigen Anlegen?", ["01 - Trading Grundlagen"]),
    ("Wie richte ich die Bots für MetaTrader 5 ein?", ["Bots/ANLEITUNG", "Claude_Trading-Bots_Wissen", "OpenAI_Trading-Bots_Dokumentation"]),
    ("In welchem Ton soll mir die KI antworten?", ["02 - Schreibstil und KI-Antworten", "03 - Wie ich arbeite"]),
    ("In welchen Stufen soll Big Brain ausgebaut werden?", ["Big Brain Ziele und Entwicklungsplan", "Jarvis Projekt Anweisung"]),
    ("Wie sortiere ich Notizen nach Projekten, Bereichen und Archiv?", ["Second Brain Methoden", "Obsidian Notizmanagement"]),
    ("Wie steuern Notenbanken die Geldmenge?", ["Steuern und Finanzwesen", "Währungen und Länder"]),
    ("Warum suchen Menschen bevorzugt nach Bestätigung ihrer Meinung?", ["Psychologie und Verhalten", "07 - Trading Psychologie"]),
    ("Wie zerlegt ein Sprachmodell Text in kleine Einheiten?", ["Token, Kontext und RAG", "Künstliche Intelligenz Vertiefung"]),
    ("Wie verknüpfe ich zwei Notizen in Obsidian?", ["02-obsidian-markdown", "00 - Obsidian Grundlagen", "Obsidian Notizmanagement"]),
    ("Wie viel Gewinn sollte ein Trade im Verhältnis zum möglichen Verlust bringen?", ["06 - Risiko und Positionsgröße"]),
    ("Wie entstehen neue Arten im Laufe der Zeit?", ["Evolution und Ursprung"]),
    ("Sind Kryptowährungen richtiges Geld?", ["Währungen und Länder"]),
    ("Was muss das System prüfen, bevor es einen simulierten Trade ausführt?", ["10 - Big Brain Trading Architektur", "06 - Risiko und Positionsgröße"]),
]

# Themen, die (Stand 20.09.2026) nicht im Vault stehen
OFF_TOPIC: list[str] = [
    "Wie backe ich einen Käsekuchen mit Quark?",
    "Wie lange müssen Spaghetti kochen?",
    "Wie pflege ich eine Orchidee richtig?",
    "Wer hat die Fußball-Weltmeisterschaft 2014 gewonnen?",
    "Welche Vereine steigen dieses Jahr aus der Bundesliga ab?",
    "Wie stricke ich einen Schal für Anfänger?",
    "Was sollte in einer Hochzeitsrede für meinen Bruder stehen?",
    "Was packe ich für einen Campingurlaub am Gardasee ein?",
    "Wie bekomme ich Rotweinflecken aus einem Teppich?",
    "Wie mache ich einen guten Espresso mit der Siebträgermaschine?",
    "Welche Farbe passt zu einem grauen Sofa?",
    "Wie trainiere ich für meinen ersten Halbmarathon?",
]

_OLD_WORD_RE = re.compile(r"[a-zA-ZäöüÄÖÜß0-9]+")


def old_keywords(text: str) -> set[str]:
    """Stichwort-Logik bis 19.09.2026 (zum Vergleich)."""
    return {w.lower() for w in _OLD_WORD_RE.findall(text) if len(w) > 2}


def _matches(file_path: str, expected: list[str]) -> bool:
    return any(e in file_path for e in expected)


# ---------------------------------------------------------------------------
# Modus 1: nur Stichwörter (ohne Modell, ohne Chroma)
# ---------------------------------------------------------------------------

def keyword_only(vault: str) -> None:
    from rag.vault_loader import load_vault

    chunks = load_vault(vault)
    print(f"{len(chunks)} Chunks aus {len({c.file_path for c in chunks})} Notizen geladen\n")
    # (Name, Stichwort-Funktion, IDF-Gewichtung)
    variants: list[tuple[str, Callable[[str], set[str]], bool]] = [
        ("alt", old_keywords, False),
        ("neu ohne IDF", new_keywords, False),
        ("neu", new_keywords, True),
    ]
    cache = {name: [fn(c.content) for c in chunks] for name, fn, _ in variants}
    idf = {}
    for name, _, _ in variants:
        df = Counter()
        for words in cache[name]:
            df.update(words)
        n = len(chunks)
        idf[name] = lambda w, df=df, n=n: math.log(1 + n / (1 + df.get(w, 0)))

    summary = {name: [0, 0, 0] for name, _, _ in variants}  # Platz 1, Top 3, Top 10
    for question, expected in QUESTIONS:
        line = [f"{question[:60]:<60}"]
        for name, fn, use_idf in variants:
            qw = fn(question)
            weight = idf[name] if use_idf else (lambda w: 1.0)
            total = sum(weight(w) for w in qw)
            best: dict[str, float] = {}
            for c, words in zip(chunks, cache[name]):
                score = sum(weight(w) for w in qw & words) / total if total else 0.0
                if score > best.get(c.file_path, -1):
                    best[c.file_path] = score
            ranking = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
            rank = next((i for i, (f, _) in enumerate(ranking, 1) if _matches(f, expected)), None)
            if rank is not None:
                summary[name][0] += rank == 1
                summary[name][1] += rank <= 3
                summary[name][2] += rank <= 10
            line.append(f"{name}: {rank if rank else '-':>3}")
        print("  " + "  ".join(line))

    print(f"\nZusammenfassung Stichwort-Suche allein ({len(QUESTIONS)} Fragen, Platz der richtigen Notiz):")
    for name, (p1, p3, p10) in summary.items():
        print(f"  {name:<13} Platz 1: {p1:>2}   Top 3: {p3:>2}   Top 10: {p10:>2}")


# ---------------------------------------------------------------------------
# Modus 2: echte Hybrid-Suche (Modell + Chroma)
# ---------------------------------------------------------------------------

def backend_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", 8000)) == 0


def _run_questions(search, label: str, top_k: int = 3) -> tuple[int, int, list[str]]:
    hit1 = hit3 = 0
    misses = []
    for question, expected in QUESTIONS:
        hits = search(question, top_k=top_k)
        files = [h.file_path for h in hits]
        in1 = bool(files) and _matches(files[0], expected)
        in3 = any(_matches(f, expected) for f in files)
        hit1 += in1
        hit3 += in3
        if not in3:
            misses.append(question)
        print(f"  [{'OK' if in3 else '--'}] {question}")
        for h in hits:
            print(f"        cos={h.raw_similarity:.3f} kw={h.keyword_overlap:.2f} score={h.score:.3f}  "
                  f"{h.file_path} | {h.heading_path[:60]}")
    print(f"  => {label}: Platz 1: {hit1}/{len(QUESTIONS)}, Top 3: {hit3}/{len(QUESTIONS)}")
    return hit1, hit3, misses


def full(threshold_only: bool = False) -> int:
    from rag import retriever
    from rag.embedder import get_embedder, get_preset

    if backend_running():
        print("ABBRUCH: Auf Port 8000 läuft noch das Backend. Bitte mit Strg+C stoppen und neu starten.")
        return 2

    preset = get_preset()
    print(f"Modell: {preset.key}, aktuelle Schwelle 'unsicher': {preset.low_similarity}, "
          f"Threads: {os.getenv('EMBEDDING_THREADS', '2 (Standard)')}")
    start = time.time()
    get_embedder(preset)
    print(f"Modell geladen in {time.time() - start:.1f}s\n")

    results = {}
    if not threshold_only:
        variants = [("alt", old_keywords, False), ("neu ohne IDF", new_keywords, False), ("neu", new_keywords, True)]
        for label, fn, use_idf in variants:
            print(f"==== Stichwort-Logik: {label} ====")
            retriever._keywords = fn  # noqa: SLF001 - bewusst für den Vergleich
            retriever.USE_IDF = use_idf
            start = time.time()
            results[label] = _run_questions(retriever.search, label)
            print(f"  ({(time.time() - start) / len(QUESTIONS) * 1000:.0f} ms pro Suche)\n")
    retriever._keywords = new_keywords  # noqa: SLF001
    retriever.USE_IDF = True

    print("==== Schwelle für 'Treffer unsicher' ====")
    on_cos, on_kw = [], []
    for question, _ in QUESTIONS:
        hits = retriever.search(question, top_k=5)
        on_cos.append(max((h.raw_similarity for h in hits), default=0.0))
        on_kw.append(max((h.keyword_overlap for h in hits), default=0.0))
    off_cos, off_kw = [], []
    for question in OFF_TOPIC:
        hits = retriever.search(question, top_k=5)
        if not hits:
            print("  Index leer - Schwelle kann nicht gemessen werden.")
            return 1
        best = max(hits, key=lambda h: h.raw_similarity)
        off_cos.append(best.raw_similarity)
        off_kw.append(max(h.keyword_overlap for h in hits))
        print(f"  themenfremd: cos={best.raw_similarity:.3f} kw={off_kw[-1]:.2f}  {question}  -> {best.file_path}")

    print(f"\n  passende Fragen:   cos min={min(on_cos):.3f}  median={statistics.median(on_cos):.3f}  max={max(on_cos):.3f}")
    print(f"  themenfremd:       cos min={min(off_cos):.3f}  median={statistics.median(off_cos):.3f}  max={max(off_cos):.3f}")
    print(f"  Stichwort-Treffer: passend median={statistics.median(on_kw):.2f}, themenfremd median={statistics.median(off_kw):.2f}")

    # Beste Schwelle = die mit den wenigsten Fehlern (passend als unsicher / themenfremd als sicher)
    candidates = sorted(set(round(x, 3) for x in on_cos + off_cos))
    best_t, best_err = None, None
    for t in candidates:
        err = sum(c < t for c in on_cos) + sum(c >= t for c in off_cos)
        if best_err is None or err < best_err:
            best_t, best_err = t, err
    print(f"\n  Vorschlag reine cos-Schwelle: {best_t}  ({best_err} Fehler bei "
          f"{len(on_cos)} passenden + {len(off_cos)} themenfremden Fragen)")
    cur = preset.low_similarity
    cur_err_on = sum(c < cur for c in on_cos)
    cur_err_off = sum(c >= cur for c in off_cos)
    print(f"  Aktuelle Schwelle {cur}: {cur_err_on} passende fälschlich unsicher, "
          f"{cur_err_off} themenfremde fälschlich sicher")

    # Kombination: unsicher, wenn cos < Schwelle ODER kein einziges Stichwort passt
    for t in sorted({cur, best_t}):
        err_on = sum(c < t or k == 0 for c, k in zip(on_cos, on_kw))
        err_off = sum(not (c < t or k == 0) for c, k in zip(off_cos, off_kw))
        print(f"  Regel 'cos < {t} ODER kein Stichwort-Treffer': {err_on} passende fälschlich unsicher, "
              f"{err_off} themenfremde fälschlich sicher")

    if results:
        print("\n==== Ergebnis ====")
        for label, (h1, h3, misses) in results.items():
            print(f"  {label}: Platz 1: {h1}/{len(QUESTIONS)}, Top 3: {h3}/{len(QUESTIONS)}")
            for m in misses:
                print(f"       verfehlt: {m}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Suchqualität und Unsicherheits-Schwelle messen")
    parser.add_argument("--keyword-only", action="store_true", help="nur Stichwort-Teil, ohne Modell/Chroma")
    parser.add_argument("--threshold-only", action="store_true", help="nur Schwelle messen")
    parser.add_argument("--vault", default=os.getenv("VAULT_PATH"))
    args = parser.parse_args()
    if args.keyword_only:
        if not args.vault:
            print("FEHLER: VAULT_PATH fehlt (.env oder --vault)")
            return 2
        keyword_only(args.vault)
        return 0
    return full(args.threshold_only)


if __name__ == "__main__":
    sys.exit(main())

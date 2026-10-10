"""
Selbsttest für Jarvis (Stand 19.09.2026: mehrsprachige Embeddings, Reindex, Verlauf).

Start (Backend vorher stoppen!):
    backend\\selftest.bat            -> Ausgabe im Fenster + selftest_log.txt
    python -m tests.selftest        -> Ausgabe direkt in der Konsole
    python -m tests.selftest --no-claude   -> ohne echte Claude-Aufrufe (kostenlos)

Prüft nacheinander:
 1. Embedding-Modell laden (beim ersten Mal Download ~280 MB) + Plausibilität
 2. Index für das neue Modell aufbauen, zweiter Lauf muss "nichts zu tun" melden
 3. Inkrementelles Update in einem Test-Ordner (ändern / löschen / neu)
 4. Deutsche Testfragen: altes Modell (MiniLM) gegen neues Modell (e5)
 5. API: /api/health, /api/reindex, /api/chat mit Gesprächsverlauf
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import sys
import tempfile
import time
import traceback
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from rag.embedder import PRESETS, get_embedder, get_preset  # noqa: E402
from rag.embeddings import build_index, get_client, get_collection  # noqa: E402
from rag.retriever import search  # noqa: E402

# (Frage, akzeptierte Dateien - Teilstring des Pfads reicht)
QUESTIONS: list[tuple[str, list[str]]] = [
    ("Wie viel Geld darf ich pro Trade maximal riskieren?", ["06 - Risiko und Positionsgröße"]),
    ("Was passiert, wenn man nach einem Verlust zu aggressiv weiterhandelt?", ["07 - Trading Psychologie"]),
    ("Wie prüfe ich eine Handelsstrategie mit alten Kursdaten?", ["08 - Backtesting"]),
    (
        "Welche Tech-Stack-Entscheidungen habe ich für Jarvis getroffen?",
        ["Big Brain Ziele und Entwicklungsplan", "Jarvis Projekt Anweisung", "Jarvis Entwicklungslog", "Jarvis Big Brain Dashboard"],
    ),
    ("Welche erneuerbaren Energiequellen gibt es für Strom?", ["Energie und Stromerzeugung"]),
    ("Wie werden Erbinformationen in Zellen gespeichert?", ["Genetik und DNA", "Zellbiologie"]),
    ("Was ist der Unterschied zwischen Steuervermeidung und Steuerhinterziehung?", ["Steuern und Finanzwesen"]),
    ("Warum arbeitet Holz, wenn sich die Luftfeuchtigkeit ändert?", ["Holz"]),
]
OFF_TOPIC = "Wie backe ich einen Käsekuchen mit Quark?"

RESULTS: list[tuple[str, bool, str]] = []


class _Tee:
    """Schreibt gleichzeitig in die Konsole und sofort (fsync) in die Logdatei -
    falls der PC abstürzt, bleibt das Protokoll bis zu diesem Punkt erhalten."""

    def __init__(self, stream, log_file) -> None:
        self.stream = stream
        self.log_file = log_file

    def write(self, text: str) -> int:
        self.stream.write(text)
        self.log_file.write(text)
        if "\n" in text:
            self.flush()
        return len(text)

    def flush(self) -> None:
        self.stream.flush()
        self.log_file.flush()
        try:
            os.fsync(self.log_file.fileno())
        except OSError:
            pass

    def __getattr__(self, name: str):
        # isatty, encoding usw. vom echten Konsolen-Stream
        return getattr(self.stream, name)


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"  [{'OK' if ok else 'FEHLER'}] {name}" + (f" - {detail}" if detail else ""), flush=True)
    return ok


def section(title: str) -> None:
    print(f"\n==== {title} ====", flush=True)


def backend_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", 8000)) == 0


def cos(a: list[float], b: list[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b)))  # Vektoren sind normalisiert


def step_model() -> None:
    section("1. Embedding-Modell")
    preset = get_preset()
    print(f"  Aktives Modell: {preset.key} ({preset.description})")
    start = time.time()
    embedder = get_embedder(preset)
    threads = getattr(embedder, "threads", "?")
    check("Modell geladen", True, f"{time.time() - start:.1f}s, {threads} von {os.cpu_count()} CPU-Threads")

    q = embedder.embed_query("Wie groß sollte meine Position beim Traden sein?")
    docs = embedder.embed_documents(
        [
            "Positionsgröße = Risikobetrag / Stop-Abstand. Maximales Risiko 1 % des Kontos.",
            "Holz ist ein nachwachsender Rohstoff und wird im Bau verwendet.",
        ]
    )
    passend, unpassend = cos(q, docs[0]), cos(q, docs[1])
    print(f"  Dimension: {len(q)}, cos(passend)={passend:.3f}, cos(unpassend)={unpassend:.3f}")
    check("Passender Text ähnlicher als unpassender", passend > unpassend + 0.02)

    de, en = embedder.embed_documents(["Der Hund bellt laut im Garten."]), embedder.embed_documents(
        ["The dog is barking loudly in the garden."]
    )
    other = embedder.embed_documents(["Die Zentralbank erhöht den Leitzins."])
    print(f"  cos(DE-Satz, EN-Übersetzung)={cos(de[0], en[0]):.3f}, cos(DE-Satz, anderes Thema)={cos(de[0], other[0]):.3f}")
    check("Mehrsprachig: Übersetzung ähnlicher als anderes Thema", cos(de[0], en[0]) > cos(de[0], other[0]))


def step_index(vault: str) -> None:
    section("2. Index komplett neu aufbauen, danach Lauf nur mit Änderungen")
    last_print = [0.0]

    def progress(done: int, total: int, rel: str) -> None:
        if time.time() - last_print[0] > 5 or done == total:
            last_print[0] = time.time()
            print(f"    ... {done}/{total} Notizen ({rel})", flush=True)

    # Komplett neu: der erste Versuch wurde durch einen PC-Absturz unterbrochen,
    # halb geschriebene Reste sollen den Test nicht verfälschen.
    stats = build_index(vault, full=True, progress=progress)
    print(f"  Lauf 1: {stats}")
    check("Index enthält Chunks", stats["collection_count"] > 0, f"{stats['collection_count']} Chunks in {stats['duration_s']}s")

    stats2 = build_index(vault)
    print(f"  Lauf 2: {stats2}")
    check("Zweiter Lauf ohne Änderungen indexiert nichts neu", stats2["files_indexed"] == 0 and stats2["files_removed"] == 0)


def step_incremental(vault: str) -> None:
    section("3. Inkrementelles Update (Test-Ordner, echter Vault bleibt unberührt)")
    source = Path(vault)
    notes = [p for p in sorted(source.rglob("*.md")) if "Trading" in str(p) and ".obsidian" not in str(p)][:3]
    if len(notes) < 3:
        check("Testnotizen gefunden", False, "weniger als 3 Trading-Notizen")
        return

    tmp = Path(tempfile.mkdtemp(prefix="jarvis_selftest_"))
    try:
        test_vault = tmp / "vault"
        test_vault.mkdir()
        for i, note in enumerate(notes):
            shutil.copy(note, test_vault / f"notiz_{i}.md")
        client = get_client(tmp / "db")
        preset = get_preset()

        s1 = build_index(test_vault, client=client)
        check("Test-Index aufgebaut", s1["files_new"] == 3, f"{s1['chunks_written']} Chunks")

        changed = test_vault / "notiz_0.md"
        changed.write_text(changed.read_text(encoding="utf-8") + "\n\n## Selbsttest-Abschnitt\nNeuer Inhalt.\n", encoding="utf-8")
        (test_vault / "notiz_1.md").unlink()
        (test_vault / "neu.md").write_text("# Neue Notiz\n\n## Abschnitt\nEin frischer Gedanke.\n", encoding="utf-8")

        s2 = build_index(test_vault, client=client)
        print(f"  Nach Änderungen: {s2}")
        check(
            "Änderung, Löschung und neue Datei erkannt",
            s2["files_changed"] == 1 and s2["files_removed"] == 1 and s2["files_new"] == 1 and s2["files_unchanged"] == 1,
        )
        metas = get_collection(client, preset).get(include=["metadatas"])["metadatas"]
        paths = {m["file_path"] for m in metas}
        check("Gelöschte Notiz nicht mehr im Index", "notiz_1.md" not in paths and "neu.md" in paths)
        check("Neuer Abschnitt im Index", any("Selbsttest-Abschnitt" in m["heading_path"] for m in metas))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # Chroma hält unter Windows evtl. Dateien offen


def _evaluate(preset_key: str) -> tuple[int, int, float, float]:
    preset = PRESETS[preset_key]
    hit1 = hit3 = 0
    start = time.time()
    for question, expected in QUESTIONS:
        hits = search(question, top_k=3, preset=preset)
        files = [h.file_path for h in hits]
        in1 = bool(files) and any(e in files[0] for e in expected)
        in3 = any(any(e in f for e in expected) for f in files)
        hit1 += in1
        hit3 += in3
        print(f"  [{'OK' if in3 else '--'}] {question}")
        for h in hits:
            print(f"        cos={h.raw_similarity:.3f} score={h.score:.3f}  {h.file_path} | {h.heading_path[:70]}")
    avg_ms = (time.time() - start) / len(QUESTIONS) * 1000
    off = search(OFF_TOPIC, top_k=1, preset=preset)
    off_cos = off[0].raw_similarity if off else 0.0
    print(f"  Themenfremde Frage '{OFF_TOPIC}': bester cos={off_cos:.3f} ({off[0].file_path if off else '-'})")
    return hit1, hit3, avg_ms, off_cos


def step_compare() -> None:
    section("4. Deutsche Testfragen: altes gegen neues Modell")
    active = get_preset().key
    old_count = get_collection(get_client(), PRESETS["minilm"]).count()

    results = {}
    if old_count > 0 and active != "minilm":
        print(f"\n  --- minilm (alter Index, {old_count} Chunks, Stand erster Indexlauf) ---")
        results["minilm"] = _evaluate("minilm")
    else:
        print("  Alter MiniLM-Index nicht vorhanden - Vergleich übersprungen.")

    print(f"\n  --- {active} (neu) ---")
    results[active] = _evaluate(active)

    print("\n  Zusammenfassung (von", len(QUESTIONS), "Fragen):")
    for key, (h1, h3, ms, off_cos) in results.items():
        print(f"    {key:<14} richtig auf Platz 1: {h1}   in Top 3: {h3}   ~{ms:.0f} ms/Suche   cos(themenfremd)={off_cos:.3f}")

    new_h3 = results[active][1]
    check("Neues Modell findet mindestens 6 von 8 in Top 3", new_h3 >= 6, f"{new_h3}/8")
    if "minilm" in results:
        check("Neues Modell mindestens so gut wie das alte", new_h3 >= results["minilm"][1])
    low = get_preset().low_similarity
    check(
        "Themenfremde Frage liegt unter der Unsicherheits-Schwelle",
        results[active][3] < low,
        f"cos={results[active][3]:.3f}, Schwelle={low}",
    )


def step_api(use_claude: bool) -> None:
    section("5. API (FastAPI TestClient)")
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as client:
        health = client.get("/api/health").json()
        print(f"  /api/health: {health}")
        check("Health meldet Modell und Index", health.get("embedding_model") == get_preset().key and health.get("vault_indexed"))

        resp = client.post("/api/reindex")
        check("POST /api/reindex -> 202", resp.status_code == 202, str(resp.json().get("running")))
        deadline = time.time() + 600
        status = resp.json()
        while status.get("running") and time.time() < deadline:
            time.sleep(1)
            status = client.get("/api/reindex/status").json()
        print(f"  Reindex-Status: {status}")
        check("Reindex fertig ohne Fehler", not status.get("running") and not status.get("error"))
        check("Reindex liefert Ergebnis", bool(status.get("last_result")))

        bad = client.post("/api/chat", json={"message": "x", "history": [{"role": "system", "content": "x"}]})
        check("Ungültige Rolle im Verlauf wird abgelehnt (422)", bad.status_code == 422)

        if not use_claude:
            print("  Claude-Aufrufe übersprungen (--no-claude)")
            return

        first_q = "Was ist Backtesting?"
        r1 = client.post("/api/chat", json={"message": first_q})
        check("Chat ohne Verlauf", r1.status_code == 200, f"HTTP {r1.status_code}")
        if r1.status_code != 200:
            print(f"  Antwort: {r1.text[:500]}")
            return
        a1 = r1.json()
        print(f"  Antwort 1 ({len(a1['sources'])} Quellen): {a1['answer'][:400]}...")
        for s in a1["sources"]:
            print(f"      - {s['file_path']} | {s['heading_path'][:60]} ({s['score']})")

        follow = "Welche Gefahren gibt es dabei?"
        history = [{"role": "user", "content": first_q}, {"role": "assistant", "content": a1["answer"]}]
        r2 = client.post("/api/chat", json={"message": follow, "history": history})
        check("Folgefrage mit Verlauf", r2.status_code == 200, f"HTTP {r2.status_code}")
        if r2.status_code == 200:
            a2 = r2.json()
            print(f"  Antwort 2 ({len(a2['sources'])} Quellen): {a2['answer'][:600]}...")
            for s in a2["sources"]:
                print(f"      - {s['file_path']} | {s['heading_path'][:60]} ({s['score']})")
            check(
                "Folgefrage findet Backtesting-Notiz",
                any("Backtesting" in s["file_path"] for s in a2["sources"]),
            )


def main_selftest() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-claude", action="store_true", help="keine echten Claude-Aufrufe")
    parser.add_argument("--log", default=None, help="Ausgabe zusätzlich in diese Datei schreiben")
    args = parser.parse_args()

    if args.log:
        log_file = open(args.log, "a", encoding="utf-8")  # noqa: SIM115 - bleibt bis Prozessende offen
        sys.stdout = _Tee(sys.stdout, log_file)
        sys.stderr = _Tee(sys.stderr, log_file)

    vault = os.getenv("VAULT_PATH")
    if not vault:
        print("FEHLER: VAULT_PATH ist nicht gesetzt (.env prüfen)")
        return 2
    if backend_running():
        print("ABBRUCH: Auf Port 8000 läuft noch das Backend.")
        print("Bitte im Backend-Fenster mit Strg+C stoppen und den Test neu starten.")
        print("(Zwei Programme gleichzeitig auf derselben Chroma-Datenbank können sie beschädigen.)")
        return 2

    print(f"Vault: {vault}")
    print(f"Python: {sys.version.split()[0]}, CPU-Kerne: {os.cpu_count()}")
    print(f"EMBEDDING_THREADS={os.getenv('EMBEDDING_THREADS', '2 (Standard)')}, "
          f"EMBEDDING_PAUSE_MS={os.getenv('EMBEDDING_PAUSE_MS', '100 (Standard)')}")
    steps = [
        ("Modell", step_model),
        ("Index", lambda: step_index(vault)),
        ("Inkrementell", lambda: step_incremental(vault)),
        ("Vergleich", step_compare),
        ("API", lambda: step_api(not args.no_claude)),
    ]
    for name, fn in steps:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - weiter mit dem nächsten Schritt
            traceback.print_exc()
            check(f"Schritt '{name}' ohne Absturz", False, f"{type(exc).__name__}: {exc}")

    section("ERGEBNIS")
    failed = [r for r in RESULTS if not r[1]]
    print(f"  {len(RESULTS) - len(failed)} von {len(RESULTS)} Prüfungen OK")
    for name, _, detail in failed:
        print(f"  FEHLER: {name} {('- ' + detail) if detail else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main_selftest())

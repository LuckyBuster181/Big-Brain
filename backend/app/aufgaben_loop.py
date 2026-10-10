"""
Aufgaben-Loop: bearbeitet automatisch wiederkehrende Wissenslücken aus
knowledge_gaps.py. Skizze und Entscheidungen siehe Vault-Notiz
"09 - Jarvis Mehrere Agenten und Aufgaben-Loop.md" (Bauauftrag seit 22.09.2026).

Ablauf pro Lauf, von Max gestartet (HUD-Knopf oder /api/aufgaben-loop/start),
kein Hintergrunddienst, kein Dauerlauf:
1. Bis zu MAX_AUFGABEN_PRO_LAUF wiederkehrende Wissenslücken holen (mindestens
   zweimal aufgetaucht - Kostenschutz, keine Reaktion auf jede Einzelfrage).
2. Je Aufgabe: Rechercheur sucht im Web (serverseitiges Claude-Werkzeug),
   Schreiber macht daraus einen Entwurf, die Notiz wird im Vault angelegt,
   danach git commit (Sicherheitsnetz fürs Schreibrecht).
3. Deckel pro Lauf (Standard 1 $ als Näherung für die von Max genannten 1 €,
   siehe Modulende) - ist er erreicht, wird abgebrochen, kein weiterer Aufruf.
Bewusst KEIN eigener Prüf-Agent: Max prüft die `entwurf`-Notizen selbst.

WICHTIG, ungetestet (Stand 22.09.2026, noch nie am PC gelaufen):
- Die Websuche läuft über Anthropics serverseitiges Werkzeug
  ("web_search_20250305"). Vor dem ersten echten Lauf zeigt sich, ob dieser
  Tool-Typ in der aktuellen API noch so heißt und ob der Schlüssel dafür
  freigeschaltet ist - sonst kommt ein klarer Fehler im Protokoll zurück,
  kein stiller Fehlschlag.
- Die Preisannahmen unten sind wie in Vault-Notiz 08 nicht in der
  Anthropic-Konsole gegengeprüft. Der Deckel ist eine Schätzung, keine
  exakte Abrechnung - nach dem ersten Lauf mit data/usage_log.jsonl und der
  echten Anthropic-Rechnung abgleichen.
- Voraussetzung: der Vault muss ein Git-Repository sein (einmal
  GIT_INIT_VAULT.bat ausführen). Ohne .git-Ordner bricht der Lauf sofort mit
  klarem Fehler ab, bevor irgendetwas geschrieben wird.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import anthropic  # wie app/agent_service.py: eigener Import, nicht über llm/provider.py
# (die Ollama-Abstraktion deckt bewusst nur den einfachen Chat ab, siehe
# llm/provider.py-Docstring - Werkzeug-/Websuche-Wege bleiben bei Claude)

from llm import provider as llm_provider

from . import chat_service, knowledge_gaps

# Preise in $ je Million Token, laut Anthropic-Preisliste und Modellübersicht
# (platform.claude.com/docs, abgerufen am 23.09.2026): Sonnet 5 2/10,
# Opus 5.5 4/20, Haiku 4.5 1/5, Fable 5.1 10/50. Vorher standen hier für
# Sonnet noch 3/15 (Sonnet 4.x) - die Kostenanzeige war also etwa 50 % zu hoch.
# Über die .env korrigierbar, falls Anthropic die Preise ändert.
PREISE_JE_MIO_USD = {
    "input_sonnet": float(os.getenv("PREIS_SONNET_INPUT_JE_MIO", "2.0")),
    "output_sonnet": float(os.getenv("PREIS_SONNET_OUTPUT_JE_MIO", "10.0")),
    "input_haiku": float(os.getenv("PREIS_HAIKU_INPUT_JE_MIO", "1.0")),
    "output_haiku": float(os.getenv("PREIS_HAIKU_OUTPUT_JE_MIO", "5.0")),
    "input_opus": float(os.getenv("PREIS_OPUS_INPUT_JE_MIO", "4.0")),
    "output_opus": float(os.getenv("PREIS_OPUS_OUTPUT_JE_MIO", "20.0")),
    "input_fable": float(os.getenv("PREIS_FABLE_INPUT_JE_MIO", "10.0")),
    "output_fable": float(os.getenv("PREIS_FABLE_OUTPUT_JE_MIO", "50.0")),
    # 03.10.2026: lokale Modelle (Ollama) kosten nichts
    "input_lokal": 0.0,
    "output_lokal": 0.0,
}


def modell_art(modell: str | None) -> str:
    """Preisklasse eines Modellnamens. Bei Kombinationen wie "haiku+sonnet"
    (Agenten-Modus) zählt vorsichtshalber das teuerste beteiligte Modell."""
    m = (modell or "").lower()
    if ":" in m:  # lokales Ollama-Modell wie "qwen3.5:9b" (Claude-Namen haben keinen Doppelpunkt)
        return "lokal"
    for art in ("fable", "opus", "sonnet", "haiku"):
        if art in m:
            return art
    return "sonnet"


# Geschätzter Aufpreis je Websuche des Rechercheurs (serverseitiges Werkzeug,
# wird von Anthropic separat von den Token-Kosten abgerechnet) - ungeprüft.
PREIS_JE_WEBSUCHE_USD = float(os.getenv("PREIS_WEBSUCHE_USD", "0.01"))

# Deckel von Max (22.09.2026): 1 € pro Lauf. Intern wird in Dollar gerechnet,
# weil Anthropic so abrechnet - 1 $ als vorsichtige Näherung, da 1 € meist
# etwas mehr wert ist als 1 $. In der .env auf einen genauen Euro-Wert
# umstellbar, sobald der reale Wechselkurs eine Rolle spielen soll.
LAUF_DECKEL_USD = float(os.getenv("AUFGABEN_LOOP_DECKEL_USD", "1.0"))
MAX_AUFGABEN_PRO_LAUF = int(os.getenv("AUFGABEN_LOOP_MAX_AUFGABEN", "3"))
# Ab wie vielen Wiederholungen eine Wissenslücke bearbeitet wird (Kostenschutz).
MINDEST_WIEDERHOLUNGEN = int(os.getenv("AUFGABEN_LOOP_MINDEST_WIEDERHOLUNGEN", "2"))

RECHERCHEUR_MODEL = chat_service.DEFAULT_MODEL
SCHREIBER_MODEL = chat_service.DEFAULT_MODEL

# Obergrenzen für die Antwortlänge (23.09.2026 von 1024 auf 2048 angehoben).
# Beim ersten Studium-Lauf stießen 4 von 10 Schreiber-Antworten genau an 1024
# Tokens - die Entwürfe brachen ab, teils fehlte der Quellen-Abschnitt ganz.
# Kostet nur, was wirklich geschrieben wird (ca. +0,3 bis 0,6 Cent je Entwurf).
# 27.09.2026 auf 3000: Der Nachtlauf fand 37 von 62 Entwürfen "lückenhaft", viele davon mit
# abgebrochenem Text bzw. Hinweis "abgeschnitten" (Praxis-Stufe trotz 2048). Kostet nur, was
# wirklich geschrieben wird - höchstens ca. +1 Cent je Entwurf.
RECHERCHEUR_MAX_TOKENS = int(os.getenv("RECHERCHEUR_MAX_TOKENS", "3000"))
SCHREIBER_MAX_TOKENS = int(os.getenv("SCHREIBER_MAX_TOKENS", "3000"))
MAX_ZITAT_QUELLEN = 8
ABGESCHNITTEN_HINWEIS = (
    "> Hinweis: Dieser Entwurf wurde beim Schreiben abgeschnitten (Längengrenze erreicht) - "
    "vor Übernahme ergänzen."
)

# Alle Entwürfe landen an einem Ort, damit Max sie beim nächsten
# Vault-Durchgang gebündelt findet und prüft (siehe Vault-Notiz 09).
ENTWURF_ORDNER = "Wissen/07 - Aufgaben-Loop Entwürfe"

# Bereits bearbeitete Fragen (eine JSON-Zeile je Frage, data/ ist nicht im Git).
# Ohne diese Liste bliebe eine bearbeitete Lücke im Wissenslücken-Protokoll
# stehen und würde bei JEDEM weiteren Lauf erneut recherchiert - doppelte
# Kosten, doppelte Entwürfe. Aufgefallen nach dem ersten echten Lauf, 22.09.2026.
DEFAULT_ERLEDIGT_PATH = Path(__file__).resolve().parents[2] / "data" / "aufgaben_loop_erledigt.jsonl"


def _erledigt_pfad() -> Path:
    return Path(os.getenv("AUFGABEN_LOOP_ERLEDIGT_PATH") or DEFAULT_ERLEDIGT_PATH)


def erledigte_fragen() -> set[str]:
    pfad = _erledigt_pfad()
    if not pfad.exists():
        return set()
    fragen = set()
    for zeile in pfad.read_text(encoding="utf-8").splitlines():
        try:
            fragen.add(str(json.loads(zeile).get("frage", "")).strip().lower())
        except (json.JSONDecodeError, AttributeError):
            continue
    fragen.discard("")
    return fragen


def _als_erledigt_merken(frage: str, ergebnis: str, notiz: str | None = None) -> None:
    pfad = _erledigt_pfad()
    pfad.parent.mkdir(parents=True, exist_ok=True)
    eintrag = {"zeit": _now(), "frage": frage, "ergebnis": ergebnis, "notiz": notiz}
    with pfad.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(eintrag, ensure_ascii=False) + "\n")


def _kosten_usd(model: str, usage: Any) -> float:
    art = modell_art(model)
    eingabe = getattr(usage, "input_tokens", 0) or 0
    ausgabe = getattr(usage, "output_tokens", 0) or 0
    return (
        eingabe * PREISE_JE_MIO_USD[f"input_{art}"] + ausgabe * PREISE_JE_MIO_USD[f"output_{art}"]
    ) / 1_000_000


# Das Wissenslücken-Protokoll enthält auch Smalltalk ("wer bist du", "jetzt
# geht's los") - der klassische Modus loggt jede schwach passende Frage. Solche
# Einträge würden sonst Websuche und einen sinnlosen Entwurf kosten. Kostenlose
# Vorsortierung hier, zweite Absicherung im Rechercheur (KEINE_WISSENSFRAGE).
_ANREDE_RE = re.compile(r"\b(du|dich|dir|dein\w*|jarvis|javis|auron|hey|hallo|hi|servus|moin|danke)\b", re.IGNORECASE)
_FRAGEWORT_RE = re.compile(
    r"\b(wer|was|wie|wo|wann|warum|wieso|weshalb|welch\w*|wozu|womit|woher|wohin|erklär\w*|unterschied)\b",
    re.IGNORECASE,
)
KEINE_WISSENSFRAGE = "KEINE_WISSENSFRAGE"


def ist_keine_wissensfrage(frage: str) -> bool:
    """Grobe, kostenlose Vorsortierung. Lieber eine echte Frage zu viel
    aussortieren (kostet nichts) als Smalltalk recherchieren (kostet Geld)."""
    woerter = re.findall(r"\w+", frage)
    if len(woerter) < 3:
        return True
    if len(woerter) <= 6 and _ANREDE_RE.search(frage):
        return True
    if "?" not in frage and not _FRAGEWORT_RE.search(frage):
        return True
    return False


def offene_luecken(limit: int = 30, mindestens: int | None = None) -> list[dict]:
    """Wiederkehrende Wissenslücken aus dem Protokoll (knowledge_gaps.py),
    häufigste zuerst. Kostenschutz aus der Entscheidung von Max (22.09.2026,
    Vault-Notiz 09): der Rechercheur wird nur bei tatsächlich wiederholten
    Lücken aktiv, nicht bei jedem Einzelfall.

    Betrachtet nur die letzten `limit` Log-Einträge insgesamt (nicht je
    Frage) - eine seltene, aber alte Wiederholung kann dadurch durchrutschen.
    Für den ersten Ausbau ausreichend, siehe Modul-Docstring."""
    mindestens = MINDEST_WIEDERHOLUNGEN if mindestens is None else mindestens
    erledigt = erledigte_fragen()
    zaehlung: dict[str, dict] = {}
    for eintrag in knowledge_gaps.recent(limit):
        frage = str(eintrag.get("frage", "")).strip()
        if not frage or ist_keine_wissensfrage(frage):
            continue
        schluessel = frage.lower()
        if schluessel in erledigt:
            continue
        stand = zaehlung.setdefault(schluessel, {"frage": frage, "anzahl": 0, "zuletzt": ""})
        stand["anzahl"] += 1
        zeit = str(eintrag.get("zeit", ""))
        if zeit > stand["zuletzt"]:
            stand["zuletzt"] = zeit
    gefiltert = [v for v in zaehlung.values() if v["anzahl"] >= mindestens]
    gefiltert.sort(key=lambda v: (v["anzahl"], v["zuletzt"]), reverse=True)
    return gefiltert


RECHERCHEUR_SYSTEM = """Du recherchierst für Auron (früher Jarvis), den digitalen Assistenten von Max, eine \
Wissenslücke aus seinem Vault "Big Brain". Nutze die Websuche, um eine kurze, sachlich \
korrekte Antwort mit Quellenangaben zu finden. Erfinde nichts - findest du nichts \
Verlässliches, sag das offen statt zu raten. Antworte auf Deutsch, höchstens 250 Wörter, mit \
den verwendeten Quellen (Titel oder URL) am Ende.

Ist die Frage keine sachliche Wissensfrage (Smalltalk, eine Frage an Auron selbst, eine \
Anweisung oder ein Kommentar), nutze die Websuche NICHT und antworte nur mit dem Wort \
KEINE_WISSENSFRAGE."""


def _anthropic_client():
    return anthropic.Anthropic(api_key=chat_service.get_api_key())


def _feld(obj: Any, name: str) -> Any:
    """Liest ein Feld aus einem SDK-Objekt oder einem dict (beides kommt vor)."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def zitat_quellen(content: Any) -> list[tuple[str, str]]:
    """Quellen aus den Zitaten der Websuche (Feld `citations` an den Text-Blöcken).

    Hintergrund (23.09.2026): Mit Websuche schreibt Claude die Quellen oft NICHT
    als Text ans Ende, sondern hängt sie als Zitat-Objekte an die Text-Blöcke.
    Bisher wurde nur der Text übernommen - so gingen die Quellen verloren und der
    Schreiber meldete "Keine Quellen angegeben", obwohl gesucht wurde.
    Liefert (Titel, URL)-Paare ohne Doppelte, höchstens MAX_ZITAT_QUELLEN."""
    gesehen: set[str] = set()
    quellen: list[tuple[str, str]] = []
    for block in content or []:
        if _feld(block, "type") != "text":
            continue
        for zitat in _feld(block, "citations") or []:
            url = _feld(zitat, "url")
            if not url or url in gesehen:
                continue
            gesehen.add(url)
            quellen.append((str(_feld(zitat, "title") or "").strip(), str(url)))
            if len(quellen) >= MAX_ZITAT_QUELLEN:
                return quellen
    return quellen


def recherche_text(antwort: Any) -> str:
    """Text der Rechercheur-Antwort plus Quellen aus den Websuche-Zitaten, soweit
    die URL nicht schon im Text steht. Abgeschnittene Recherche wird markiert."""
    content = _feld(antwort, "content") or []
    text = "".join(_feld(b, "text") or "" for b in content if _feld(b, "type") == "text").strip()
    if not text:
        return ""
    if text.upper().startswith(KEINE_WISSENSFRAGE):
        return text
    neue = [(t, u) for t, u in zitat_quellen(content) if u not in text]
    if neue:
        zeilen = "\n".join(f"- {t}: {u}" if t else f"- {u}" for t, u in neue)
        text += f"\n\nQuellen (aus der Websuche):\n{zeilen}"
    if _feld(antwort, "stop_reason") == "max_tokens":
        text += "\n\n[Recherche wurde an der Längengrenze abgeschnitten.]"
    return text


def rechercheur(frage: str) -> dict[str, Any]:
    client = _anthropic_client()
    start = time.time()
    antwort = client.messages.create(
        model=RECHERCHEUR_MODEL,
        max_tokens=RECHERCHEUR_MAX_TOKENS,
        system=RECHERCHEUR_SYSTEM,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        messages=[{"role": "user", "content": frage}],
    )
    dauer = time.time() - start
    text = recherche_text(antwort)
    suchen = sum(1 for b in antwort.content if getattr(b, "type", None) == "server_tool_use")
    usage = getattr(antwort, "usage", None)
    kosten = _kosten_usd(RECHERCHEUR_MODEL, usage) + suchen * PREIS_JE_WEBSUCHE_USD
    # Ins gemeinsame Token-Protokoll, damit Briefing und Kostenauswertung den
    # Loop mitzählen (fehlte beim ersten Lauf am 22.09.2026).
    chat_service.log_usage(
        RECHERCHEUR_MODEL, usage, dauer, sources=0, history_messages=0,
        mode="aufgaben-loop-rechercheur", searches=suchen,
    )
    return {"text": text, "kosten_usd": kosten, "dauer_s": dauer, "usage": usage, "suchen": suchen}


SCHREIBER_SYSTEM = """Du bist der Schreiber im Aufgaben-Loop von Auron (früher Jarvis, Max' Assistent). Aus \
einer recherchierten Antwort machst du einen kurzen Entwurf für eine neue Notiz in Max' \
Obsidian-Vault "Big Brain". Halte dich GENAU an dieses Format, ohne zusätzlichen Text davor \
oder danach:

TITEL: <kurzer, klarer Titel, ohne Anführungszeichen>
INHALT:
<Notiztext in Markdown, beginnend mit einer # Überschrift, 100 bis 300 Wörter, sachlich, auf \
Deutsch, ohne Ich-Perspektive>

Regeln: Nichts erfinden, was nicht in der Recherche stand. Ist die Recherche dünn oder \
unsicher, schreib das im Text offen dazu. Keine Quellen-Nummern wie [1] im Fließtext. \
Am Ende des Inhalts ein Abschnitt "## Quellen" mit den Quellen aus der Recherche als \
Liste (Titel und URL, soweit in der Recherche genannt) - nur Quellen, die dort wirklich \
stehen, keine erfundenen. Nennt die Recherche keine Quellen, schreib unter "## Quellen": \
"Keine Quellen angegeben - vor Übernahme prüfen."."""

_TITEL_RE = re.compile(r"^TITEL:\s*(.+)$", re.MULTILINE)
_INHALT_RE = re.compile(r"INHALT:\s*(.*)$", re.DOTALL)


def schreiber_auswerten(antwort: Any, ersatz_titel: str) -> tuple[str, str]:
    """Titel und Inhalt aus der Schreiber-Antwort. Ist die Antwort an der
    Längengrenze abgeschnitten, bekommt der Inhalt einen sichtbaren Hinweis."""
    content = _feld(antwort, "content") or []
    text = "".join(_feld(b, "text") or "" for b in content if _feld(b, "type") == "text").strip()
    titel_treffer = _TITEL_RE.search(text)
    inhalt_treffer = _INHALT_RE.search(text)
    titel = titel_treffer.group(1).strip() if titel_treffer else ersatz_titel
    inhalt = inhalt_treffer.group(1).strip() if inhalt_treffer else text
    if _feld(antwort, "stop_reason") == "max_tokens":
        inhalt = f"{inhalt}\n\n{ABGESCHNITTEN_HINWEIS}"
    return titel, inhalt


def schreiber(frage: str, rechercheur_text: str) -> dict[str, Any]:
    # 03.10.2026: Bei ki_anbieter=ollama schreibt ein lokales Modell (0 Kosten, Nachtreihenfolge:
    # Test-PC zuerst). Die Recherche mit Websuche bleibt bei Claude. Der Entwurf geht wie
    # immer erst zu Sir zur Prüfung, bevor er im Vault landet.
    lokal = llm_provider.provider_name() == "ollama"
    client = llm_provider.get_client(chat_service.get_api_key, tag=False) if lokal else _anthropic_client()
    modell = llm_provider.current_model_label(SCHREIBER_MODEL) if lokal else SCHREIBER_MODEL
    start = time.time()
    nutzer_text = f"Wissenslücke (Frage aus dem Chat): {frage}\n\nRecherche:\n{rechercheur_text}"
    antwort = client.messages.create(
        model=modell,
        max_tokens=SCHREIBER_MAX_TOKENS,
        system=SCHREIBER_SYSTEM,
        messages=[{"role": "user", "content": nutzer_text}],
    )
    dauer = time.time() - start
    titel, inhalt = schreiber_auswerten(antwort, frage[:60])
    usage = getattr(antwort, "usage", None)
    if lokal:
        modell = llm_provider.letztes_ziel.get("modell", modell)
    kosten = _kosten_usd(modell, usage)
    chat_service.log_usage(
        modell, usage, dauer, sources=0, history_messages=0, mode="aufgaben-loop-schreiber",
    )
    return {"titel": titel, "inhalt": inhalt, "kosten_usd": kosten, "dauer_s": dauer, "usage": usage}


_DATEINAME_UNERWUENSCHT_RE = re.compile(r"[^a-zA-Z0-9äöüÄÖÜß \-]+")


def _dateiname(titel: str) -> str:
    bereinigt = _DATEINAME_UNERWUENSCHT_RE.sub("", titel).strip()
    bereinigt = re.sub(r"\s+", " ", bereinigt)[:80] or "Entwurf"
    return bereinigt + ".md"


def _notiz_schreiben(vault_path: str, frage: str, titel: str, inhalt: str) -> str:
    ordner = Path(vault_path) / ENTWURF_ORDNER
    ordner.mkdir(parents=True, exist_ok=True)
    dateiname = _dateiname(titel)
    ziel = ordner / dateiname
    zaehler = 2
    while ziel.exists():
        ziel = ordner / f"{dateiname[:-3]} ({zaehler}).md"
        zaehler += 1
    heute = datetime.date.today().isoformat()
    frage_kurz = frage[:120].replace('"', "'")
    frontmatter = (
        "---\n"
        "typ: entwurf\n"
        "status: entwurf\n"
        f"erstellt: {heute}\n"
        f"aktualisiert: {heute}\n"
        f'quelle: Aufgaben-Loop (Rechercheur/Schreiber), ungeprüft, Frage: "{frage_kurz}"\n'
        "vertrauen: niedrig\n"
        "niveau: einstieg\n"
        "tags:\n"
        "  - aufgaben-loop\n"
        "  - ungeprueft\n"
        "---\n\n"
    )
    ziel.write_text(frontmatter + inhalt + "\n", encoding="utf-8")
    return str(ziel.relative_to(vault_path)).replace("\\", "/")


def _git_verfuegbar(vault_path: str) -> bool:
    return (Path(vault_path) / ".git").is_dir()


def _git_commit(vault_path: str, nachricht: str) -> None:
    try:
        subprocess.run(
            ["git", "add", "-A"], cwd=vault_path, check=True, capture_output=True, timeout=30, text=True
        )
        ergebnis = subprocess.run(
            ["git", "commit", "-m", nachricht], cwd=vault_path, capture_output=True, timeout=30, text=True
        )
        ausgabe = (ergebnis.stdout or "") + (ergebnis.stderr or "")
        if ergebnis.returncode != 0 and "nothing to commit" not in ausgabe.lower():
            raise RuntimeError(f"git commit fehlgeschlagen: {ausgabe.strip()}")
    except FileNotFoundError as exc:
        raise RuntimeError("git ist nicht installiert oder nicht im PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("git-Befehl hat zu lange gebraucht (Timeout)") from exc


# --------------------------------------------------------------- Ablauf/Status
# Gleiches Muster wie app/reindex_service.py: läuft im Hintergrund-Thread,
# das HUD fragt den Fortschritt per Polling ab.

_lock = threading.Lock()
_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "error": None,
    "last_result": None,
}


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def status() -> dict:
    with _lock:
        return dict(_state)


def is_running() -> bool:
    with _lock:
        return bool(_state["running"])


def _lauf(max_aufgaben: int, deckel_usd: float) -> None:
    protokoll: list[dict] = []
    ausgegeben = 0.0
    fehler: str | None = None
    try:
        vault_path = os.getenv("VAULT_PATH")
        if not vault_path:
            raise RuntimeError("VAULT_PATH ist nicht gesetzt (.env prüfen)")
        if not _git_verfuegbar(vault_path):
            raise RuntimeError(
                "Der Vault ist kein Git-Repository. Einmal GIT_INIT_VAULT.bat ausführen, bevor "
                "der Aufgaben-Loop läuft (Sicherheitsnetz fürs Schreibrecht)."
            )

        aufgaben = offene_luecken()[:max_aufgaben]
        if not aufgaben:
            protokoll.append({"status": "Keine wiederkehrenden Wissenslücken gefunden - nichts zu tun."})

        for aufgabe in aufgaben:
            frage = aufgabe["frage"]
            if ausgegeben >= deckel_usd:
                protokoll.append({"frage": frage, "status": "übersprungen: Deckel erreicht"})
                continue
            try:
                rech = rechercheur(frage)
                ausgegeben += rech["kosten_usd"]
                if rech["text"].strip().upper().startswith(KEINE_WISSENSFRAGE):
                    _als_erledigt_merken(frage, "keine Wissensfrage")
                    protokoll.append({"frage": frage, "status": "keine Wissensfrage - übersprungen"})
                    continue
                if not rech["text"]:
                    _als_erledigt_merken(frage, "nichts Verlässliches gefunden")
                    protokoll.append(
                        {"frage": frage, "status": "Rechercheur fand nichts Verlässliches - kein Entwurf"}
                    )
                    continue
                if ausgegeben >= deckel_usd:
                    protokoll.append(
                        {"frage": frage, "status": "Deckel nach der Recherche erreicht - kein Schreiber mehr"}
                    )
                    continue

                schr = schreiber(frage, rech["text"])
                ausgegeben += schr["kosten_usd"]

                pfad = _notiz_schreiben(vault_path, frage, schr["titel"], schr["inhalt"])
                # Schon vor dem Commit als erledigt merken: scheitert git, liegt die
                # Notiz trotzdem im Vault - ein zweiter Lauf soll kein Duplikat anlegen
                # (der nächste erfolgreiche Commit nimmt sie über "git add -A" mit).
                _als_erledigt_merken(frage, "Entwurf angelegt", pfad)
                _git_commit(vault_path, f"Aufgaben-Loop: Entwurf '{schr['titel']}'")
                protokoll.append(
                    {
                        "frage": frage,
                        "status": "Entwurf angelegt",
                        "notiz": pfad,
                        "kosten_usd": round(rech["kosten_usd"] + schr["kosten_usd"], 4),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - eine Aufgabe darf den Lauf nicht abbrechen
                protokoll.append({"frage": frage, "status": f"Fehler: {exc}"})
    except Exception as exc:  # noqa: BLE001 - z.B. fehlendes VAULT_PATH oder .git
        fehler = str(exc)
        traceback.print_exc()

    with _lock:
        _state["running"] = False
        _state["finished_at"] = _now()
        _state["error"] = fehler
        _state["last_result"] = {
            "kosten_usd": round(ausgegeben, 4),
            "deckel_usd": deckel_usd,
            "protokoll": protokoll,
        }
    print(
        f"[Aufgaben-Loop] fertig: {len(protokoll)} Einträge, {round(ausgegeben, 4)} $ ausgegeben "
        f"(Deckel {deckel_usd} $)",
        flush=True,
    )


def start(max_aufgaben: int | None = None, deckel_usd: float | None = None) -> tuple[bool, dict]:
    """Startet einen Lauf im Hintergrund. Läuft schon einer, wird kein
    zweiter gestartet (gleiches Muster wie reindex_service.start())."""
    with _lock:
        if _state["running"]:
            return False, dict(_state)
        _state.update(running=True, started_at=_now(), finished_at=None, error=None)

    thread = threading.Thread(
        target=_lauf,
        args=(max_aufgaben or MAX_AUFGABEN_PRO_LAUF, deckel_usd or LAUF_DECKEL_USD),
        name="jarvis-aufgaben-loop",
        daemon=True,
    )
    thread.start()
    return True, status()

"""
Studium: Jarvis erarbeitet sich systematisch Wissen zu einem Thema, das Sir
eingibt (z.B. "Physik"), statt nur auf wiederkehrende Chat-Fragen zu warten
(das macht schon der Aufgaben-Loop, siehe aufgaben_loop.py). Gleiche
Maschinerie - Rechercheur, Schreiber, Budget-Deckel, Git-Sicherheitsnetz -
nur die Aufgabenquelle ist anders: statt Wissenslücken aus dem Chat kommt
hier eine Themen-Zerlegung durch ein günstiges Modell.

Bauauftrag von Sir (22.09.2026): "das Limit ausreizen mit 1 Dollar und Physik
studiert" - anders als beim Aufgaben-Loop (Obergrenze 3 Aufgaben je Lauf) gibt
es hier bewusst KEINE künstlich niedrige Aufgaben-Obergrenze. Der Lauf
arbeitet Unterthemen ab, bis entweder alle durch sind oder der Geld-Deckel
(Standard 1 $/€, wie beim Aufgaben-Loop) erreicht ist - nur eine Notbremse
gegen ausufernde Themen-Zerlegungen bleibt (ANZAHL_UNTERTHEMEN).

Ablauf pro Lauf, von Sir gestartet (HUD-Knopf oder /api/studium/start):
1. Ein günstiges Modell (TOOL_MODEL, wie der "Sucher" im Werkzeug-Modus)
   zerlegt das Thema in bis zu ANZAHL_UNTERTHEMEN konkrete Unterthemen -
   einmaliger kleiner Zusatzaufruf, kostet mit.
2. Je Unterthema: Rechercheur sucht im Web (serverseitiges Claude-Werkzeug,
   wie im Aufgaben-Loop), Schreiber macht daraus einen Entwurf, die Notiz
   wird im Vault angelegt, danach git commit.
3. Schon bearbeitete Unterthemen zu einem Thema werden beim nächsten Lauf
   zum selben Thema übersprungen (data/studium_erledigt.jsonl) - so lässt
   sich "Physik" über mehrere Läufe/Tage hinweg fortsetzen, ohne doppelt zu
   recherchieren.
Bewusst KEIN eigener Prüf-Agent - wie beim Aufgaben-Loop prüft Sir die
`entwurf`-Notizen selbst.

Stufen (23.09.2026, nach Jarvis' eigener Antwort "keine aktuellen
Forschungsergebnisse nach meinem Trainingsstand, keine Experimente, keine
Intuition aus Laborarbeit" - Sir: "gib Jarvis, was er braucht"):
- grundlagen  Lehrbuch-Grundlagen (bisheriges Verhalten, Standard)
- vertiefung  Formeln mit Einheiten, durchgerechnete Beispielaufgabe, typische Denkfehler
- forschung   aktueller Forschungsstand mit Jahreszahlen, offene Fragen - per Websuche,
              also NICHT auf den Trainingsstand des Modells begrenzt
- praxis      klassische Experimente, typische Messwerte/Größenordnungen, Fehlerquellen,
              Faustregeln - ersetzt keine Laborarbeit, gibt Jarvis aber belegte
              Erfahrungswerte statt Bauchgefühl
Jede Stufe hat eigene Unterthemen, eigene Erledigt-Liste und einen eigenen
Unterordner - "Physik" kann also in jeder Stufe getrennt fortgesetzt werden.

Erster echter Lauf am 22.09.2026, 23:43-23:48 (Physik, Grundlagen): 10 Entwürfe,
1,02 $. Danach repariert: Quellen aus Websuche-Zitaten, Längengrenze 2048,
Reserve gegen angefangene Recherchen über dem Deckel.

Ungetestet (Stand 22.09.2026, noch nie am PC gelaufen) - dieselben Vorbehalte
wie in aufgaben_loop.py gelten hier genauso: Name/Verfügbarkeit des
Websuche-Werkzeugs, Preisannahmen dort ungeprüft, Git-Voraussetzung.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from . import aufgaben_loop, chat_service
from .agent_service import TOOL_MODEL

# Notbremse gegen ausufernde Themen-Zerlegung (ein Tippfehler im Thema soll
# nicht 200 Unterthemen erzeugen) - keine Obergrenze der ABGEARBEITETEN
# Aufgaben pro Lauf, die bestimmt allein der Geld-Deckel (siehe Docstring).
ANZAHL_UNTERTHEMEN = int(os.getenv("STUDIUM_ANZAHL_UNTERTHEMEN", "20"))
LAUF_DECKEL_USD = float(os.getenv("STUDIUM_DECKEL_USD", "1.0"))
# Reserve je Unterthema (23.09.2026): Beim ersten echten Lauf (22.09., Physik,
# 1,02 $) startete nach 0,95 $ noch eine Recherche, deren Ergebnis wegen des
# Deckels nie geschrieben wurde - ca. 7 Cent verschenkt. Jetzt wird ein
# Unterthema nur begonnen, wenn Ausgaben + erwartete Kosten unter dem Deckel
# bleiben. Erwartet = Durchschnitt der schon fertigen Unterthemen dieses Laufs,
# vorher dieser Schätzwert (gemessen: ca. 10 Cent je Unterthema).
SCHAETZUNG_JE_UNTERTHEMA_USD = float(os.getenv("STUDIUM_SCHAETZUNG_USD", "0.10"))

# Eigener Ordner, getrennt von den Aufgaben-Loop-Entwürfen (Notiz 09, Ordner 07) -
# unterschiedliche Herkunft (Themen-Studium statt Chat-Wissenslücke).
ENTWURF_ORDNER = "Wissen/08 - Studium Entwürfe"

DEFAULT_ERLEDIGT_PATH = Path(__file__).resolve().parents[2] / "data" / "studium_erledigt.jsonl"

STANDARD_STUFE = "grundlagen"
# Je Stufe: Zusatz für die Themen-Zerlegung, die Rechercheur-Frage ({u} = Unterthema,
# {t} = Thema), eine Zusatzvorgabe für den Schreiber, Unterordner und Niveau.
STUFEN: dict[str, dict[str, str]] = {
    "grundlagen": {
        "name": "Grundlagen",
        "zerlegung": "",
        "frage": 'Was sind die wichtigsten Grundlagen zu "{u}" (Teilgebiet von {t})?',
        "rechercheur_zusatz": "",
        "schreiber_zusatz": "",
        "ordner": "",
        "niveau": "einstieg",
    },
    "vertiefung": {
        "name": "Vertiefung",
        "zerlegung": "Stufe VERTIEFUNG: Unterthemen wie Kapitel eines Hauptstudiums - konkrete "
        "Gesetze, Modelle und Rechenmethoden, die man sicher anwenden können muss.",
        "frage": 'Erkläre "{u}" (Teilgebiet von {t}) vertieft: die zentralen Formeln mit Bedeutung '
        "und Einheit jeder Größe, eine vollständig durchgerechnete Beispielaufgabe mit Zahlen und "
        "die typischen Denkfehler von Lernenden.",
        "rechercheur_zusatz": "Für diesen Auftrag gilt abweichend: höchstens 450 Wörter. Formeln "
        "als Text mit Einheiten.",
        "schreiber_zusatz": "Zusatzvorgabe für diese Stufe (hat Vorrang vor der Längenangabe): 200 "
        "bis 500 Wörter, gegliedert in \"## Kernidee\", \"## Formeln\" (jede Größe mit Einheit), "
        "\"## Beispielrechnung\" (Schritt für Schritt, mit Zahlen), \"## Typische Fehler\", "
        "danach \"## Quellen\". Formeln in LaTeX mit $...$.",
        "ordner": "Vertiefung",
        "niveau": "vertiefung",
    },
    "forschung": {
        "name": "Forschung",
        "zerlegung": "Stufe FORSCHUNG: Unterthemen sind aktive Forschungsfelder und offene "
        "Fragen des Gebiets, an denen in den letzten Jahren gearbeitet wird (z.B. bei Physik: "
        "\"Dunkle Materie: Suche und Kandidaten\", \"Quantencomputer: Fehlerkorrektur\").",
        "frage": 'Was ist der aktuelle Forschungsstand zu "{u}" (Teilgebiet von {t})? Nenne die '
        "wichtigsten Ergebnisse der letzten Jahre jeweils mit Jahr und beteiligtem Experiment, "
        "Institut oder Team, dazu die wichtigsten offenen Fragen. Nur belegte Ergebnisse.",
        "rechercheur_zusatz": "Für diesen Auftrag gilt abweichend: höchstens 450 Wörter. Jede "
        "Aussage mit Jahreszahl. Bevorzuge aktuelle Quellen (Fachportale, Institute, "
        "Wissenschaftsjournalismus).",
        "schreiber_zusatz": "Zusatzvorgabe für diese Stufe (hat Vorrang vor der Längenangabe): 200 "
        "bis 500 Wörter, gegliedert in \"## Stand der Forschung\", \"## Wichtige Ergebnisse\" "
        "(jeweils mit Jahr), \"## Offene Fragen\", danach \"## Quellen\". Erster Satz nennt, "
        "dass dies der Stand zum Recherchedatum ist.",
        "ordner": "Forschung",
        "niveau": "vertiefung",
    },
    "praxis": {
        "name": "Praxis und Experimente",
        "zerlegung": "Stufe PRAXIS: Unterthemen sind klassische Experimente, Messverfahren und "
        "Anwendungen des Gebiets (z.B. bei Physik: \"Fadenpendel: Messung der Fallbeschleunigung\", "
        "\"Millikan-Versuch\", \"Wärmekapazität messen\").",
        "frage": 'Wie wird "{u}" (Teilgebiet von {t}) praktisch untersucht? Beschreibe Aufbau und '
        "Durchführung des klassischen Experiments, typische Messwerte und Größenordnungen, die "
        "häufigsten Fehlerquellen und brauchbare Faustregeln oder Alltagsbeispiele.",
        "rechercheur_zusatz": "Für diesen Auftrag gilt abweichend: höchstens 450 Wörter. Konkrete "
        "Zahlenwerte mit Einheiten.",
        "schreiber_zusatz": "Zusatzvorgabe für diese Stufe (hat Vorrang vor der Längenangabe): 200 "
        "bis 500 Wörter, gegliedert in \"## Experiment\" (Aufbau, Durchführung), \"## Typische "
        "Messwerte\" (mit Einheiten und Größenordnungen), \"## Fehlerquellen\", \"## Faustregeln "
        "und Alltag\", danach \"## Quellen\".",
        "ordner": "Praxis",
        "niveau": "vertiefung",
    },
}


def stufe_pruefen(stufe: str | None) -> str:
    """Normalisiert die Stufe; unbekannte Werte sind ein klarer Fehler."""
    wert = (stufe or STANDARD_STUFE).strip().lower()
    if wert not in STUFEN:
        raise ValueError(f"Unbekannte Stufe \"{stufe}\" - erlaubt: {', '.join(STUFEN)}")
    return wert


def _erledigt_pfad() -> Path:
    return Path(os.getenv("STUDIUM_ERLEDIGT_PATH") or DEFAULT_ERLEDIGT_PATH)


def erledigte_unterthemen(thema: str, stufe: str = STANDARD_STUFE) -> set[str]:
    """Schon bearbeitete Unterthemen NUR für dieses eine Thema und diese Stufe (ein
    anderes Thema kann zufällig gleich benannte Unterthemen haben, z.B.
    "Grundlagen"). Einträge ohne Stufe stammen aus der Zeit vor den Stufen und
    zählen als "grundlagen"."""
    pfad = _erledigt_pfad()
    if not pfad.exists():
        return set()
    schluessel_thema = thema.strip().lower()
    ergebnis: set[str] = set()
    for zeile in pfad.read_text(encoding="utf-8").splitlines():
        try:
            eintrag = json.loads(zeile)
        except json.JSONDecodeError:
            continue
        if str(eintrag.get("stufe") or STANDARD_STUFE) != stufe:
            continue
        if str(eintrag.get("thema", "")).strip().lower() == schluessel_thema:
            ergebnis.add(str(eintrag.get("unterthema", "")).strip().lower())
    ergebnis.discard("")
    return ergebnis


def _als_erledigt_merken(
    thema: str, unterthema: str, ergebnis: str, notiz: str | None = None, stufe: str = STANDARD_STUFE
) -> None:
    pfad = _erledigt_pfad()
    pfad.parent.mkdir(parents=True, exist_ok=True)
    eintrag = {
        "zeit": aufgaben_loop._now(),  # noqa: SLF001 - internes Hilfsmittel, gleiches Modul-Paket
        "thema": thema,
        "unterthema": unterthema,
        "ergebnis": ergebnis,
        "notiz": notiz,
        "stufe": stufe,
    }
    with pfad.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(eintrag, ensure_ascii=False) + "\n")


# --------------------------------------------------------------- Unterthemen

UNTERTHEMEN_SYSTEM = """Du hilfst Jarvis (Max' digitalem Assistenten), sich systematisch \
Grundlagenwissen zu einem Thema zu erarbeiten, so wie es in einem Grundstudium oder Lehrbuch \
aufgeteilt wäre. Zerlege das genannte Thema in konkrete, klar abgegrenzte Unterthemen, z.B. \
"Physik" -> "Newtonsche Mechanik", "Thermodynamik: Hauptsätze", "Elektromagnetismus: \
Grundlagen", "Optik: Wellen- und Strahlenmodell", "Spezielle Relativitätstheorie: Grundidee".

Antworte NUR mit einer nummerierten Liste, ein Unterthema pro Zeile, ohne Erklärungen davor \
oder danach, auf Deutsch. Jedes Unterthema so konkret, dass eine einzelne Websuche und ein \
kurzer Notiztext (100-300 Wörter) es sinnvoll abdecken - nicht zu breit ("Physik" wäre zu \
breit), nicht zu eng (eine einzelne Formel wäre zu eng)."""

_ZEILE_RE = re.compile(r"^\s*\d+[.)]\s*(.+?)\s*$", re.MULTILINE)


_FUELL = {"und", "der", "die", "das", "von", "mit", "für", "den", "des", "im", "in", "ein", "eine", "grundlagen", "einführung"}


def _woerter(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zäöüß]{4,}", text.lower()) if w not in _FUELL}


def aehnlich_erledigt(unterthema: str, erledigt: set[str], schwelle: float = 0.5) -> bool:
    """Gilt ein Unterthema als schon bearbeitet, auch wenn es anders formuliert ist?
    (23.09.2026: beim zweiten Physik-Lauf kamen "Kinematik: Bewegung ..." und
    "Rotation und Drehmoment" neu, obwohl "... Kinematik" und "Rotationsbewegung und
    Drehmoment" schon da waren - rund 0,90 $ für Doppeltes.) Vergleich über gemeinsame
    Wortstämme (erste 6 Buchstaben), Anteil am kürzeren Titel."""
    neu = {w[:6] for w in _woerter(unterthema)}
    if not neu:
        return unterthema.strip().lower() in erledigt
    for alt in erledigt:
        vorher = {w[:6] for w in _woerter(alt)}
        if vorher and len(neu & vorher) / min(len(neu), len(vorher)) >= schwelle:
            return True
    return False


def unterthemen(
    thema: str, anzahl: int = ANZAHL_UNTERTHEMEN, stufe: str = STANDARD_STUFE, erledigt: set[str] | None = None
) -> list[str]:
    """Zerlegt ein Thema in Unterthemen. Günstiger Zusatzaufruf über TOOL_MODEL
    (dieselbe Rolle wie der "Sucher" im Werkzeug-Modus, siehe agent_service.py).
    Schon bearbeitete Unterthemen werden mitgeschickt, damit das Modell weitermacht
    statt dieselben Kapitel umformuliert nochmal vorzuschlagen."""
    client = aufgaben_loop._anthropic_client()  # noqa: SLF001
    start = time.time()
    auftrag = f"Thema: {thema}\nHöchstens {anzahl} Unterthemen."
    if erledigt:
        liste = "\n".join(f"- {u}" for u in sorted(erledigt)[:80])
        auftrag += (
            "\n\nDiese Unterthemen sind schon bearbeitet - NICHT wiederholen, auch nicht umformuliert. "
            "Schlage die nächsten, noch fehlenden Kapitel vor (weiterführend, nicht dieselben Grundlagen):\n" + liste
        )
    antwort = client.messages.create(
        model=TOOL_MODEL,
        max_tokens=600,
        system=(UNTERTHEMEN_SYSTEM + "\n\n" + STUFEN[stufe]["zerlegung"]).strip(),
        messages=[{"role": "user", "content": auftrag}],
    )
    dauer = time.time() - start
    text = "".join(b.text for b in antwort.content if getattr(b, "type", None) == "text").strip()
    treffer = [m.strip() for m in _ZEILE_RE.findall(text) if m.strip()]
    usage = getattr(antwort, "usage", None)
    chat_service.log_usage(
        TOOL_MODEL, usage, dauer, sources=0, history_messages=0, mode="studium-unterthemen",
    )
    return treffer[:anzahl]


# --------------------------------------------------------- Rechercheur/Schreiber
# Wiederverwendet aus aufgaben_loop.py: RECHERCHEUR_SYSTEM/SCHREIBER_SYSTEM sind
# allgemein genug formuliert ("eine Wissenslücke" -> hier ein Unterthema), nur
# der eigentliche Nutzertext ist anders (kein Bezug auf "Frage aus dem Chat").


# Sparhebel 1 (von Sir freigegeben 27.09.2026): 2 statt 3 Websuchen je Unterthema.
# Die Websuche-Ergebnisse sind der größte Kostenblock des Rechercheurs (Eingabe-Tokens),
# eine Suche weniger spart geschätzt 25-35 % der Studium-Kosten.
STUDIUM_MAX_SUCHEN = int(os.getenv("STUDIUM_MAX_SUCHEN", "2"))


def _rechercheur(thema: str, unterthema: str, stufe: str = STANDARD_STUFE) -> dict[str, Any]:
    client = aufgaben_loop._anthropic_client()  # noqa: SLF001
    vorgabe = STUFEN[stufe]
    frage = vorgabe["frage"].format(u=unterthema, t=thema)
    if stufe == "forschung":
        frage += f" (Heutiges Datum: {datetime.date.today().isoformat()})"
    start = time.time()
    antwort = client.messages.create(
        model=aufgaben_loop.RECHERCHEUR_MODEL,
        max_tokens=aufgaben_loop.RECHERCHEUR_MAX_TOKENS,
        system=(aufgaben_loop.RECHERCHEUR_SYSTEM + "\n\n" + vorgabe["rechercheur_zusatz"]).strip(),
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": STUDIUM_MAX_SUCHEN}],
        messages=[{"role": "user", "content": frage}],
    )
    dauer = time.time() - start
    text = aufgaben_loop.recherche_text(antwort)
    suchen = sum(1 for b in antwort.content if getattr(b, "type", None) == "server_tool_use")
    usage = getattr(antwort, "usage", None)
    kosten = aufgaben_loop._kosten_usd(aufgaben_loop.RECHERCHEUR_MODEL, usage) + suchen * aufgaben_loop.PREIS_JE_WEBSUCHE_USD  # noqa: SLF001, E501
    chat_service.log_usage(
        aufgaben_loop.RECHERCHEUR_MODEL, usage, dauer, sources=0, history_messages=0,
        mode="studium-rechercheur", searches=suchen,
    )
    return {"text": text, "kosten_usd": kosten, "suchen": suchen}


def _schreiber(
    thema: str, unterthema: str, rechercheur_text: str, stufe: str = STANDARD_STUFE
) -> dict[str, Any]:
    client = aufgaben_loop._anthropic_client()  # noqa: SLF001
    nutzer_text = (
        f"Studium-Unterthema: {unterthema} (Teilgebiet von {thema})\n\nRecherche:\n{rechercheur_text}"
    )
    zusatz = STUFEN[stufe]["schreiber_zusatz"]
    if zusatz:
        nutzer_text += f"\n\n{zusatz}"
    start = time.time()
    antwort = client.messages.create(
        model=aufgaben_loop.SCHREIBER_MODEL,
        max_tokens=aufgaben_loop.SCHREIBER_MAX_TOKENS,
        system=aufgaben_loop.SCHREIBER_SYSTEM,
        messages=[{"role": "user", "content": nutzer_text}],
    )
    dauer = time.time() - start
    titel, inhalt = aufgaben_loop.schreiber_auswerten(antwort, unterthema[:60])
    usage = getattr(antwort, "usage", None)
    kosten = aufgaben_loop._kosten_usd(aufgaben_loop.SCHREIBER_MODEL, usage)  # noqa: SLF001
    chat_service.log_usage(
        aufgaben_loop.SCHREIBER_MODEL, usage, dauer, sources=0, history_messages=0, mode="studium-schreiber",
    )
    return {"titel": titel, "inhalt": inhalt, "kosten_usd": kosten}


def _notiz_schreiben(
    vault_path: str, thema: str, unterthema: str, titel: str, inhalt: str, stufe: str = STANDARD_STUFE
) -> str:
    vorgabe = STUFEN[stufe]
    ordner = Path(vault_path) / ENTWURF_ORDNER
    if vorgabe["ordner"]:
        ordner = ordner / vorgabe["ordner"]
    ordner.mkdir(parents=True, exist_ok=True)
    dateiname = aufgaben_loop._dateiname(titel)  # noqa: SLF001
    ziel = ordner / dateiname
    zaehler = 2
    while ziel.exists():
        ziel = ordner / f"{dateiname[:-3]} ({zaehler}).md"
        zaehler += 1
    heute = datetime.date.today().isoformat()
    unterthema_kurz = unterthema[:120].replace('"', "'")
    thema_kurz = thema[:60].replace('"', "'")
    frontmatter = (
        "---\n"
        "typ: entwurf\n"
        "status: entwurf\n"
        f"erstellt: {heute}\n"
        f"aktualisiert: {heute}\n"
        f'quelle: Studium (Rechercheur/Schreiber), ungeprüft, Thema: "{thema_kurz}", '
        f'Unterthema: "{unterthema_kurz}"\n'
        f"stufe: {stufe}\n"
        + (f"recherchiert: {heute}\n" if stufe == "forschung" else "")
        + "vertrauen: niedrig\n"
        f"niveau: {vorgabe['niveau']}\n"
        "tags:\n"
        "  - studium\n"
        + (f"  - {stufe}\n" if stufe != STANDARD_STUFE else "")
        + "  - ungeprueft\n"
        "---\n\n"
    )
    ziel.write_text(frontmatter + inhalt + "\n", encoding="utf-8")
    return str(ziel.relative_to(vault_path)).replace("\\", "/")


# --------------------------------------------------------------- Ablauf/Status
# Gleiches Muster wie aufgaben_loop.py: Hintergrund-Thread, HUD fragt per
# Polling ab. Eigener Zustand, damit Aufgaben-Loop und Studium unabhängig
# ihren Status zeigen - siehe aber die Sperre unten gegen gleichzeitiges Laufen.

_lock = threading.Lock()
_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "error": None,
    "last_result": None,
}


def status() -> dict:
    with _lock:
        return dict(_state)


def is_running() -> bool:
    with _lock:
        return bool(_state["running"])


def _lauf(thema: str, deckel_usd: float, max_aufgaben: int | None, stufe: str = STANDARD_STUFE) -> None:
    protokoll: list[dict] = []
    ausgegeben = 0.0
    fehler: str | None = None
    try:
        # Aufgaben-Loop und Studium schreiben beide per "git add -A" + "git commit"
        # in denselben Vault - gleichzeitig laufen könnte sich die Commits in die
        # Quere bringen. Einfache, robuste Sperre statt echter Nebenläufigkeit.
        if aufgaben_loop.is_running():
            raise RuntimeError(
                "Der Aufgaben-Loop läuft gerade. Erst abwarten, sonst könnten sich die "
                "Git-Commits beider Läufe stören."
            )

        vault_path = os.getenv("VAULT_PATH")
        if not vault_path:
            raise RuntimeError("VAULT_PATH ist nicht gesetzt (.env prüfen)")
        if not aufgaben_loop._git_verfuegbar(vault_path):  # noqa: SLF001
            raise RuntimeError(
                "Der Vault ist kein Git-Repository. Einmal GIT_INIT_VAULT.bat ausführen, bevor "
                "das Studium läuft (Sicherheitsnetz fürs Schreibrecht)."
            )

        erledigt = erledigte_unterthemen(thema, stufe)
        themen = unterthemen(thema, stufe=stufe, erledigt=erledigt)
        if not themen:
            protokoll.append({"status": f'Keine Unterthemen zu "{thema}" gefunden - nichts zu tun.'})

        offene = [u for u in themen if not aehnlich_erledigt(u, erledigt)]
        if max_aufgaben is not None:
            offene = offene[:max_aufgaben]
        uebersprungen_erledigt = len(themen) - len(offene) if themen else 0
        if uebersprungen_erledigt:
            protokoll.append(
                {"status": f"{uebersprungen_erledigt} Unterthema(en) schon bearbeitet - übersprungen."}
            )

        fertige_kosten: list[float] = []
        for unterthema in offene:
            erwartet = (
                sum(fertige_kosten) / len(fertige_kosten) if fertige_kosten else SCHAETZUNG_JE_UNTERTHEMA_USD
            )
            if ausgegeben >= deckel_usd or ausgegeben + erwartet > deckel_usd:
                protokoll.append({"unterthema": unterthema, "status": "übersprungen: Deckel erreicht"})
                continue
            try:
                rech = _rechercheur(thema, unterthema, stufe)
                ausgegeben += rech["kosten_usd"]
                if rech["text"].strip().upper().startswith(aufgaben_loop.KEINE_WISSENSFRAGE):
                    _als_erledigt_merken(thema, unterthema, "vom Rechercheur abgelehnt", stufe=stufe)
                    protokoll.append({"unterthema": unterthema, "status": "vom Rechercheur abgelehnt - übersprungen"})
                    continue
                if not rech["text"]:
                    _als_erledigt_merken(thema, unterthema, "nichts Verlässliches gefunden", stufe=stufe)
                    protokoll.append(
                        {"unterthema": unterthema, "status": "Rechercheur fand nichts Verlässliches - kein Entwurf"}
                    )
                    continue
                if ausgegeben >= deckel_usd:
                    protokoll.append(
                        {"unterthema": unterthema, "status": "Deckel nach der Recherche erreicht - kein Schreiber mehr"}
                    )
                    continue

                schr = _schreiber(thema, unterthema, rech["text"], stufe)
                ausgegeben += schr["kosten_usd"]

                fertige_kosten.append(rech["kosten_usd"] + schr["kosten_usd"])
                pfad = _notiz_schreiben(vault_path, thema, unterthema, schr["titel"], schr["inhalt"], stufe)
                # Vor dem Commit als erledigt merken (siehe aufgaben_loop.py, gleicher
                # Grund): scheitert git, liegt die Notiz trotzdem im Vault und wird
                # nicht doppelt recherchiert.
                _als_erledigt_merken(thema, unterthema, "Entwurf angelegt", pfad, stufe=stufe)
                aufgaben_loop._git_commit(  # noqa: SLF001
                    vault_path, f"Studium ({thema}, {STUFEN[stufe]['name']}): Entwurf '{schr['titel']}'"
                )  # noqa: SLF001
                protokoll.append(
                    {
                        "unterthema": unterthema,
                        "status": "Entwurf angelegt",
                        "notiz": pfad,
                        "kosten_usd": round(rech["kosten_usd"] + schr["kosten_usd"], 4),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - ein Unterthema darf den Lauf nicht abbrechen
                protokoll.append({"unterthema": unterthema, "status": f"Fehler: {exc}"})
    except Exception as exc:  # noqa: BLE001 - z.B. fehlendes VAULT_PATH, .git oder laufender Aufgaben-Loop
        fehler = str(exc)
        traceback.print_exc()

    with _lock:
        _state["running"] = False
        _state["finished_at"] = aufgaben_loop._now()  # noqa: SLF001
        _state["error"] = fehler
        _state["last_result"] = {
            "thema": thema,
            "stufe": stufe,
            "kosten_usd": round(ausgegeben, 4),
            "deckel_usd": deckel_usd,
            "protokoll": protokoll,
        }
    print(
        f"[Studium] '{thema}' fertig: {len(protokoll)} Einträge, {round(ausgegeben, 4)} $ ausgegeben "
        f"(Deckel {deckel_usd} $)",
        flush=True,
    )


def start(
    thema: str, deckel_usd: float | None = None, max_aufgaben: int | None = None, stufe: str | None = None
) -> tuple[bool, dict]:
    """Startet einen Studium-Lauf im Hintergrund. Läuft schon einer, wird kein
    zweiter gestartet (gleiches Muster wie aufgaben_loop.start())."""
    thema = (thema or "").strip()
    if not thema:
        raise RuntimeError("Kein Thema angegeben.")
    stufe = stufe_pruefen(stufe)
    with _lock:
        if _state["running"]:
            return False, dict(_state)
        _state.update(running=True, started_at=aufgaben_loop._now(), finished_at=None, error=None)  # noqa: SLF001

    thread = threading.Thread(
        target=_lauf,
        args=(thema, deckel_usd or LAUF_DECKEL_USD, max_aufgaben, stufe),
        name="jarvis-studium",
        daemon=True,
    )
    thread.start()
    return True, status()

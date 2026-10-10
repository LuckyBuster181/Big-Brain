"""
Modell-Prüfstand (Jarvis-Sandbox, 23.09.2026 - Wunsch von Sir: "ein Sandbox-Platz
für die Jarvis-KI"). Stellt dieselben Testfragen an mehrere Claude-Modelle und
zeigt Antworten, Kosten, Dauer und Quellen nebeneinander. Ziel: Modellwahl nach
Messwerten statt nach Bauchgefühl (z.B. "reicht Haiku für Vault-Fragen?").

Ablauf pro Lauf (von Sir gestartet, HUD-Seite "Labor", kein Dauerlauf):
1. Je Frage EINE Vault-Suche (klassischer Weg aus chat_service) - alle Modelle
   bekommen exakt dieselben Ausschnitte, damit der Vergleich fair ist und die
   Suche nicht mehrfach läuft.
2. Je Modell ein Claude-Aufruf mit Jarvis' normalem System-Prompt und der
   normalen Längengrenze.
3. Automatisch gemessen: Kosten (Schätzung wie in kosten.py), Dauer, Länge,
   Quellennummern, ob "Sir" vorkommt und - bei Fragen mit bekannter Ziel-Notiz -
   ob eine zitierte Quelle die richtige Notiz ist. Die inhaltliche Qualität
   beurteilt Sir selbst beim Lesen (bewusst kein teurer "Richter"-Aufruf).
4. Ergebnis im Speicher (HUD) und als JSON unter data/pruefstand/.

Kosten: eine Sonnet-5-Antwort ca. 0,5 Cent, Opus 5.5 ca. 1 Cent, Haiku ca. 0,25 Cent (Schätzung).
Standardlauf 8 Fragen x 2 Modelle = ca. 8 Cent. Eigener Deckel (Standard 0,50 $),
vor jedem Aufruf wird geprüft, ob die geschätzten Kosten noch hineinpassen.
Einträge im Token-Protokoll mit Modus "pruefstand".

Ungetestet am PC (Stand 23.09.2026): nur in der Cloud-Sandbox mit simuliertem
Claude und simulierter Suche geprüft.
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

DECKEL_USD = float(os.getenv("PRUEFSTAND_DECKEL_USD", "0.5"))
MAX_FRAGEN = 20
MAX_MODELLE = 4
# Vorsichtige Schätzung je Antwort, bevor echte Werte des Laufs vorliegen
SCHAETZUNG_JE_ANTWORT_USD = {"sonnet": 0.008, "haiku": 0.005, "opus": 0.016, "fable": 0.04}
_MODELL_RE = re.compile(r"^claude-[a-z0-9.\-]{3,60}$")
_QUELLE_RE = re.compile(r"\[(\d{1,2})\]")

# Standardfragen: Vault-Fragen mit bekannter Ziel-Notiz (aus tests/eval_search.py,
# dort am PC geprüft) plus zwei Fragen ohne Ziel (Allgemeinwissen/Studium).
STANDARD_FRAGEN: list[dict[str, Any]] = [
    {"frage": "Wie viel Geld darf ich pro Trade maximal riskieren?", "ziel": ["06 - Risiko und Positionsgröße"]},
    {"frage": "Wie prüfe ich eine Handelsstrategie mit alten Kursdaten?", "ziel": ["08 - Backtesting"]},
    {"frage": "Welche Tech-Stack-Entscheidungen habe ich für Jarvis getroffen?",
     "ziel": ["Big Brain Ziele und Entwicklungsplan", "Jarvis Projekt Anweisung", "Jarvis Entwicklungslog",
              "Jarvis Big Brain Dashboard", "Tages Notizen/2026-09-19"]},
    {"frage": "Was zeigt mir der RSI an?", "ziel": ["04 - Technische Analyse", "M1_RSI_SPIKE_FILTER"]},
    {"frage": "Wie geben Nervenzellen Signale aneinander weiter?", "ziel": ["Gehirn und Neurobiologie"]},
    {"frage": "In welchem Ton soll mir die KI antworten?", "ziel": ["02 - Schreibstil und KI-Antworten", "03 - Wie ich arbeite"]},
    {"frage": "Was besagt der zweite Hauptsatz der Thermodynamik?", "ziel": ["Thermodynamik"]},
    {"frage": "Wie funktioniert ein Elektromotor?", "ziel": []},
]


class PruefstandFehler(ValueError):
    pass


# Drittes Vergleichsmodell im Standardlauf (Wunsch von Sir, 23.09.2026):
# Opus 5.5 kostet laut Preisliste doppelt so viel wie Sonnet 5 (4/20 statt 2/10 $).
VERGLEICHS_MODELL = os.getenv("PRUEFSTAND_VERGLEICH", "claude-opus-5-5").strip()


def standard_modelle() -> list[str]:
    modelle = [chat_service.DEFAULT_MODEL]
    for m in (TOOL_MODEL, VERGLEICHS_MODELL):
        if m and m not in modelle and len(modelle) < MAX_MODELLE:
            modelle.append(m)
    return modelle


def _art(modell: str) -> str:
    return aufgaben_loop.modell_art(modell)


def _kosten(modell: str, usage: Any) -> float:
    """Wie kosten.kosten_eintrag: Eingabe, Ausgabe, Cache-Lesen mit 10 %."""
    preise = aufgaben_loop.PREISE_JE_MIO_USD
    art = _art(modell)
    eingabe = getattr(usage, "input_tokens", 0) or 0
    ausgabe = getattr(usage, "output_tokens", 0) or 0
    cache = getattr(usage, "cache_read_input_tokens", 0) or 0
    return (
        eingabe * preise[f"input_{art}"] + cache * preise[f"input_{art}"] * 0.1 + ausgabe * preise[f"output_{art}"]
    ) / 1_000_000


def fragen_pruefen(fragen: list[Any] | None) -> list[dict[str, Any]]:
    """Normalisiert die Fragenliste: Texte oder {"frage", "ziel"}; leer = Standard."""
    if not fragen:
        return [dict(f) for f in STANDARD_FRAGEN]
    ergebnis = []
    for eintrag in fragen:
        if isinstance(eintrag, str):
            eintrag = {"frage": eintrag, "ziel": []}
        text = str(eintrag.get("frage", "")).strip()
        if not text:
            continue
        if len(text) > 500:
            raise PruefstandFehler("Eine Frage ist zu lang (höchstens 500 Zeichen).")
        ziel = [str(z) for z in (eintrag.get("ziel") or []) if str(z).strip()]
        ergebnis.append({"frage": text, "ziel": ziel})
    if not ergebnis:
        raise PruefstandFehler("Keine gültige Frage angegeben.")
    if len(ergebnis) > MAX_FRAGEN:
        raise PruefstandFehler(f"Höchstens {MAX_FRAGEN} Fragen pro Lauf.")
    return ergebnis


def modelle_pruefen(modelle: list[str] | None) -> list[str]:
    liste = [m.strip() for m in (modelle or []) if m and m.strip()] or standard_modelle()
    liste = list(dict.fromkeys(liste))  # Doppelte raus, Reihenfolge bleibt
    for m in liste:
        if not _MODELL_RE.match(m):
            raise PruefstandFehler(f'Ungültiger Modellname "{m}" (erwartet z.B. "claude-haiku-4-5-20251001").')
    if len(liste) > MAX_MODELLE:
        raise PruefstandFehler(f"Höchstens {MAX_MODELLE} Modelle pro Lauf.")
    return liste


def bewerten(antwort: str, treffer: list[Any], ziel: list[str]) -> dict[str, Any]:
    """Automatische, einfache Merkmale einer Antwort (keine Inhaltsbewertung)."""
    nummern = sorted({int(n) for n in _QUELLE_RE.findall(antwort)})
    gueltig = [n for n in nummern if 1 <= n <= len(treffer)]
    zitierte_dateien = [str(getattr(treffer[n - 1], "file_path", "")) for n in gueltig]
    richtige_quelle = None
    if ziel:
        richtige_quelle = any(z.lower() in d.lower() for d in zitierte_dateien for z in ziel)
    return {
        "woerter": len(antwort.split()),
        "quellen_zitiert": len(gueltig),
        "quellen_ungueltig": len(nummern) - len(gueltig),
        "sir": "sir" in antwort.lower(),
        "richtige_quelle": richtige_quelle,
        "zitierte_notizen": zitierte_dateien,
    }


def _anfrage(client: Any, modell: str, nutzer_text: str) -> tuple[str, Any, float]:
    start = time.time()
    antwort = client.messages.create(
        model=modell,
        max_tokens=chat_service.MAX_ANSWER_TOKENS,
        system=chat_service.cache_system(chat_service.SYSTEM_PROMPT),
        messages=[{"role": "user", "content": nutzer_text}],
    )
    dauer = time.time() - start
    text = "".join(b.text for b in antwort.content if getattr(b, "type", None) == "text").strip()
    return text, getattr(antwort, "usage", None), dauer


def zusammenfassen(ergebnisse: list[dict], modelle: list[str]) -> list[dict]:
    """Je Modell: Summe/Schnitt der Messwerte über alle beantworteten Fragen."""
    tabelle = []
    for modell in modelle:
        antworten = [a for e in ergebnisse for a in e["antworten"] if a["modell"] == modell and not a.get("fehler")]
        mit_ziel = [a for a in antworten if a["bewertung"]["richtige_quelle"] is not None]
        n = len(antworten)
        tabelle.append({
            "modell": modell,
            "antworten": n,
            "kosten_usd": round(sum(a["kosten_usd"] for a in antworten), 4),
            "kosten_je_antwort_cent": round(sum(a["kosten_usd"] for a in antworten) / n * 100, 3) if n else None,
            "dauer_schnitt_s": round(sum(a["dauer_s"] for a in antworten) / n, 2) if n else None,
            "woerter_schnitt": round(sum(a["bewertung"]["woerter"] for a in antworten) / n) if n else None,
            "richtige_quelle": f"{sum(1 for a in mit_ziel if a['bewertung']['richtige_quelle'])}/{len(mit_ziel)}",
            "sir_prozent": round(sum(1 for a in antworten if a["bewertung"]["sir"]) / n * 100) if n else None,
            "fehler": sum(1 for e in ergebnisse for a in e["antworten"] if a["modell"] == modell and a.get("fehler")),
        })
    return tabelle


# ------------------------------------------------------------ Ablauf/Status

_lock = threading.Lock()
_state: dict = {"running": False, "started_at": None, "finished_at": None, "error": None, "last_result": None}


def status() -> dict:
    with _lock:
        return dict(_state)


def _ergebnis_ordner() -> Path:
    pfad = Path(os.getenv("PRUEFSTAND_PATH") or Path(__file__).resolve().parents[2] / "data" / "pruefstand")
    pfad.mkdir(parents=True, exist_ok=True)
    return pfad


def _lauf(fragen: list[dict], modelle: list[str], deckel_usd: float, top_k: int) -> None:
    ergebnisse: list[dict] = []
    ausgegeben = 0.0
    fehler: str | None = None
    je_modell_kosten: dict[str, list[float]] = {m: [] for m in modelle}
    abgebrochen = False
    try:
        client = aufgaben_loop._anthropic_client()  # noqa: SLF001
        for eintrag in fragen:
            treffer = chat_service.search_many([(eintrag["frage"], 1.0)], top_k=top_k)
            nutzer_text = chat_service.build_user_message(eintrag["frage"], treffer)
            zeile = {
                "frage": eintrag["frage"],
                "ziel": eintrag["ziel"],
                "treffer": [str(getattr(t, "file_path", "")) for t in treffer],
                "antworten": [],
            }
            for modell in modelle:
                bisher = je_modell_kosten[modell]
                erwartet = sum(bisher) / len(bisher) if bisher else SCHAETZUNG_JE_ANTWORT_USD[_art(modell)]
                if ausgegeben + erwartet > deckel_usd:
                    zeile["antworten"].append({"modell": modell, "fehler": "übersprungen: Deckel erreicht"})
                    abgebrochen = True
                    continue
                try:
                    text, usage, dauer = _anfrage(client, modell, nutzer_text)
                except Exception as exc:  # noqa: BLE001 - ein Modell darf den Lauf nicht abbrechen
                    zeile["antworten"].append({"modell": modell, "fehler": str(exc)[:300]})
                    continue
                kosten = _kosten(modell, usage)
                ausgegeben += kosten
                bisher.append(kosten)
                chat_service.log_usage(modell, usage, dauer, len(treffer), 0, mode="pruefstand")
                zeile["antworten"].append({
                    "modell": modell,
                    "antwort": text,
                    "kosten_usd": round(kosten, 5),
                    "dauer_s": round(dauer, 2),
                    "tokens_ein": getattr(usage, "input_tokens", None),
                    "tokens_aus": getattr(usage, "output_tokens", None),
                    "bewertung": bewerten(text, treffer, eintrag["ziel"]),
                })
            ergebnisse.append(zeile)
    except Exception as exc:  # noqa: BLE001 - z.B. fehlender API-Schlüssel oder Index
        fehler = str(exc)
        traceback.print_exc()

    ergebnis = {
        "zeit": aufgaben_loop._now(),  # noqa: SLF001
        "modelle": modelle,
        "deckel_usd": deckel_usd,
        "kosten_usd": round(ausgegeben, 4),
        "deckel_erreicht": abgebrochen,
        "zusammenfassung": zusammenfassen(ergebnisse, modelle),
        "fragen": ergebnisse,
    }
    try:
        name = datetime.datetime.now().strftime("pruefstand_%Y-%m-%d_%H-%M-%S.json")
        (_ergebnis_ordner() / name).write_text(json.dumps(ergebnis, ensure_ascii=False, indent=2), encoding="utf-8")
        ergebnis["datei"] = f"data/pruefstand/{name}"
    except OSError as exc:
        print(f"[Prüfstand] Ergebnis nicht gespeichert: {exc}", flush=True)
    with _lock:
        _state.update(running=False, finished_at=aufgaben_loop._now(), error=fehler, last_result=ergebnis)  # noqa: SLF001
    print(f"[Prüfstand] fertig: {len(ergebnisse)} Fragen, {round(ausgegeben, 4)} $", flush=True)


def start(
    fragen: list[Any] | None = None,
    modelle: list[str] | None = None,
    deckel_usd: float | None = None,
    top_k: int | None = None,
) -> tuple[bool, dict]:
    """Startet einen Prüfstand-Lauf im Hintergrund. Läuft schon einer, kein zweiter."""
    fragen_liste = fragen_pruefen(fragen)
    modell_liste = modelle_pruefen(modelle)
    deckel = float(deckel_usd or DECKEL_USD)
    if not 0 < deckel <= 2.0:
        raise PruefstandFehler("Deckel muss zwischen 0 und 2 $ liegen.")
    with _lock:
        if _state["running"]:
            return False, dict(_state)
        _state.update(running=True, started_at=aufgaben_loop._now(), finished_at=None, error=None)  # noqa: SLF001
    threading.Thread(
        target=_lauf,
        args=(fragen_liste, modell_liste, deckel, int(top_k or chat_service.DEFAULT_TOP_K)),
        name="jarvis-pruefstand",
        daemon=True,
    ).start()
    return True, status()

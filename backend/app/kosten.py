"""
Kosten-Übersicht (Ausbauplan Phase A, 23.09.2026): wertet das eigene
Token-Protokoll data/usage_log.jsonl aus - Monat gegen den Rahmen von Sir
(20 $), je Funktion, je Tag, je Modell, Hochrechnung aufs Monatsende.

WICHTIG: Das ist eine SCHÄTZUNG aus dem eigenen Protokoll, keine Abrechnung.
- Preise: dieselben Annahmen wie im Aufgaben-Loop (aufgaben_loop.PREISE_JE_MIO_USD,
  per .env korrigierbar), in der Anthropic-Konsole noch nicht gegengeprüft.
- Cache-Lesen wird mit 10 % des Eingabepreises gerechnet, das Schreiben in den
  Cache (etwas teurer als normale Eingabe) steht nicht im Protokoll und fehlt.
- Websuchen werden nur bei den Rechercheur-Modi berechnet - "suchen" heißt in
  den Chat-Modi Vault-Suchen, die nichts extra kosten.
- Agenten-Einträge ("haiku+sonnet") fassen Sucher und Antworter zusammen und
  werden vorsichtig komplett zum Sonnet-Preis gerechnet.
Den echten Stand zeigt nur die Anthropic-Konsole (Link im Ergebnis). Das
Wochenlimit des Claude-Pro-Abos ist davon völlig getrennt und nicht abfragbar.
"""

from __future__ import annotations

import calendar
import datetime
import json
import os
from pathlib import Path
from typing import Any, Iterable

from . import aufgaben_loop, chat_service

RAHMEN_USD = float(os.getenv("KOSTEN_RAHMEN_USD", "30.0"))  # 27.09.2026: Sir hebt den Rahmen auf 30 $
CACHE_LESEN_ANTEIL = 0.1
# Anthropic hat die Konsole Ende 2025 umgezogen (console.anthropic.com leitet
# weiter) - über die .env anpassbar, falls sich die Adresse wieder ändert.
LINK_AUFLADEN = os.getenv("ANTHROPIC_BILLING_URL", "https://console.anthropic.com/settings/billing")
LINK_VERBRAUCH = os.getenv("ANTHROPIC_USAGE_URL", "https://console.anthropic.com/usage")
WEBSUCHE_MODI = ("aufgaben-loop-rechercheur", "studium-rechercheur", "recherche-chat", "nachtauftrag")

# Lesbare Namen für die Modi im Protokoll
FUNKTIONEN = {
    "klassisch": "Chat (klassisch)",
    "werkzeug": "Chat (Werkzeug)",
    "werkzeug+agenten": "Chat (Agenten)",
    "briefing-morgen": "Briefing morgens",
    "briefing-abend": "Briefing abends",
    "aufgaben-loop-rechercheur": "Aufgaben-Loop",
    "aufgaben-loop-schreiber": "Aufgaben-Loop",
    "studium-unterthemen": "Studium",
    "studium-rechercheur": "Studium",
    "studium-schreiber": "Studium",
    "pruefstand": "Modell-Prüfstand",
    "denkblock": "Denkblock (Mitdenken)",
    "tiktok-slides": "TikTok-Slides lesen",
    "smalltalk": "Smalltalk",
    "alexa": "Alexa (frag Auron)",  # 12.10.2026, P19
    # 27.09.2026: Alltagsfunktionen
    "schreiben-text": "Texte schreiben",
    "schreiben-prompt": "Prompts schreiben",
    "recherche-chat": "Recherche (Websuche)",
    "mindmap": "Mind Maps",
    "projekt": "Projekte planen",
    "tagesplan": "Tagesplan",
    "termin-lesen": "Termine lesen",
    # 29.09.2026: Wissensimport aus Wikipedia (Sammelaufträge, halber Preis)
    "wissensimport-schreiben": "Wissensimport",
    "wissensimport-pruefen": "Wissensimport",
    "wissensimport-nachbessern": "Wissensimport",
    "wissensimport-nachpruefen": "Wissensimport",
}


def _log_pfad() -> Path:
    return Path(os.getenv("USAGE_LOG_PATH") or chat_service.DEFAULT_USAGE_LOG)


def eintraege(pfad: Path | None = None) -> list[dict]:
    """Alle lesbaren Protokoll-Einträge; kaputte Zeilen werden übersprungen."""
    pfad = pfad or _log_pfad()
    if not pfad.exists():
        return []
    ergebnis = []
    for zeile in pfad.read_text(encoding="utf-8").splitlines():
        try:
            eintrag = json.loads(zeile)
        except json.JSONDecodeError:
            continue
        if isinstance(eintrag, dict) and eintrag.get("zeit"):
            ergebnis.append(eintrag)
    return ergebnis


def _preisart(modell: str) -> str:
    # "haiku+sonnet" (Agenten) enthält Sonnet -> vorsichtig als Sonnet rechnen
    return aufgaben_loop.modell_art(modell)


def kosten_eintrag(eintrag: dict) -> float:
    """Geschätzte Kosten eines Protokoll-Eintrags in $."""
    preise = aufgaben_loop.PREISE_JE_MIO_USD
    art = _preisart(str(eintrag.get("modell", "")))
    eingabe = eintrag.get("input_tokens") or 0
    ausgabe = eintrag.get("output_tokens") or 0
    cache = eintrag.get("cache_read_tokens") or 0
    usd = (
        eingabe * preise[f"input_{art}"]
        + cache * preise[f"input_{art}"] * CACHE_LESEN_ANTEIL
        + ausgabe * preise[f"output_{art}"]
    ) / 1_000_000
    if eintrag.get("modus") in WEBSUCHE_MODI:
        usd += (eintrag.get("suchen") or 0) * aufgaben_loop.PREIS_JE_WEBSUCHE_USD
    # 29.09.2026: Sammelaufträge (Message Batches, app/wissensimport.py) kosten die Hälfte
    if eintrag.get("batch"):
        usd *= 0.5
    return usd


def _datum(eintrag: dict) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(str(eintrag["zeit"])[:10])
    except (KeyError, ValueError):
        return None


def uebersicht(heute: datetime.date | None = None, alle: Iterable[dict] | None = None) -> dict[str, Any]:
    """Monatsübersicht für das HUD."""
    heute = heute or datetime.date.today()
    alle = list(eintraege() if alle is None else alle)
    monat = heute.strftime("%Y-%m")

    im_monat = [(e, _datum(e)) for e in alle]
    im_monat = [(e, d) for e, d in im_monat if d and d.strftime("%Y-%m") == monat and d <= heute]

    gesamt = 0.0
    heute_usd = 0.0
    je_funktion: dict[str, dict] = {}
    je_modell: dict[str, dict] = {}
    je_tag: dict[str, float] = {}
    for eintrag, datum in im_monat:
        usd = kosten_eintrag(eintrag)
        gesamt += usd
        if datum == heute:
            heute_usd += usd
        funktion = FUNKTIONEN.get(str(eintrag.get("modus")), str(eintrag.get("modus") or "unbekannt"))
        f = je_funktion.setdefault(funktion, {"funktion": funktion, "aufrufe": 0, "usd": 0.0})
        f["aufrufe"] += 1
        f["usd"] += usd
        modell = str(eintrag.get("modell") or "unbekannt")
        m = je_modell.setdefault(modell, {"modell": modell, "aufrufe": 0, "usd": 0.0})
        m["aufrufe"] += 1
        m["usd"] += usd
        je_tag[datum.isoformat()] = je_tag.get(datum.isoformat(), 0.0) + usd

    tage_im_monat = calendar.monthrange(heute.year, heute.month)[1]
    # Hochrechnung ab dem ersten Tag mit Protokoll-Einträgen in diesem Monat -
    # sonst würden Tage vor dem Start von Jarvis den Schnitt künstlich senken.
    erster = min((d for _, d in im_monat), default=heute)
    tage_gelaufen = (heute - erster).days + 1
    prognose = gesamt / tage_gelaufen * (tage_im_monat - erster.day + 1) if im_monat else 0.0

    def rund(liste: list[dict]) -> list[dict]:
        for x in liste:
            x["usd"] = round(x["usd"], 4)
        return sorted(liste, key=lambda x: x["usd"], reverse=True)

    anteil = gesamt / RAHMEN_USD * 100 if RAHMEN_USD else 0.0
    return {
        "monat": monat,
        "rahmen_usd": RAHMEN_USD,
        "ausgegeben_usd": round(gesamt, 4),
        "rest_usd": round(RAHMEN_USD - gesamt, 4),
        "anteil_prozent": round(anteil, 1),
        "heute_usd": round(heute_usd, 4),
        "prognose_monatsende_usd": round(prognose, 2),
        "ampel": "rot" if anteil >= 90 or prognose > RAHMEN_USD else ("gelb" if anteil >= 60 else "gruen"),
        "anfragen": len(im_monat),
        "je_funktion": rund(list(je_funktion.values())),
        "je_modell": rund(list(je_modell.values())),
        "je_tag": [{"tag": t, "usd": round(u, 4)} for t, u in sorted(je_tag.items())],
        "links": {"aufladen": LINK_AUFLADEN, "verbrauch": LINK_VERBRAUCH},
        "hinweis": (
            "Schätzung aus dem eigenen Token-Protokoll, Preise ungeprüft. Der echte Kontostand "
            "steht nur in der Anthropic-Konsole. Das Wochenlimit des Claude-Pro-Abos ist davon "
            "getrennt und hier nicht sichtbar."
        ),
    }

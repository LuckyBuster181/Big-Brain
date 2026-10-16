"""
Kosten-Übersicht (Ausbauplan Phase A, 23.09.2026): wertet das eigene
Token-Protokoll data/usage_log.jsonl aus - Monat gegen den Rahmen von Sir
(20 $), je Funktion, je Tag, je Modell, Hochrechnung aufs Monatsende.

P23 (13.10.2026): ZWEI Töpfe. Aurons selbst ausgelöste Code-Aufgaben (Modus mit Präfix "code-") haben einen
eigenen Deckel (KOSTEN_CODE_RAHMEN_USD, Standard 10 $). Der normale Rahmen (KOSTEN_RAHMEN_USD, Standard 20 $)
zählt code-* nicht mit; beide Töpfe stoppen unabhängig voneinander. Die Schlüssel "rahmen_usd", "rest_usd" usw.
auf oberster Ebene bleiben der normale Topf; der Code-Topf steht unter "code". Die Werte kommen aus der
Umgebung (.env wird nie von Claude gelesen oder geändert).

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
import re
from pathlib import Path
from typing import Any, Iterable

from . import aufgaben_loop, chat_service

CODE_PREFIX = "code-"
RAHMEN_STANDARD_USD = 20.0       # Entscheidung 11.10.2026 (vorher 30 $ seit 27.09.)
CODE_RAHMEN_STANDARD_USD = 10.0  # P23, 13.10.2026


def betrag_aus_env(name: str, standard: float) -> float:
    """Betrag in $ aus der Umgebung. Fehlt er, ist er kaputt oder nicht positiv: Standard."""
    roh = (os.getenv(name) or "").strip().replace(",", ".")
    if not roh:
        return standard
    try:
        wert = float(roh)
    except ValueError:
        return standard
    return wert if wert > 0 else standard


RAHMEN_USD = betrag_aus_env("KOSTEN_RAHMEN_USD", RAHMEN_STANDARD_USD)
CODE_RAHMEN_USD = betrag_aus_env("KOSTEN_CODE_RAHMEN_USD", CODE_RAHMEN_STANDARD_USD)
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


# Entscheidung Sir 13.10.2026: Code-Aufgaben nutzen nachts nie Claude (Regel "Nachtarbeit nie mit Claude").
NACHT_VON_STUNDE = int(betrag_aus_env("KOSTEN_CODE_NACHT_VON", 23))
NACHT_BIS_STUNDE = int(betrag_aus_env("KOSTEN_CODE_NACHT_BIS", 6))


def ist_nacht(jetzt: datetime.datetime | None = None) -> bool:
    """True zwischen 23 und 6 Uhr (Ortszeit; per KOSTEN_CODE_NACHT_VON/BIS änderbar)."""
    if jetzt is None:
        from . import alltag

        jetzt = alltag.jetzt()
    h = jetzt.hour
    if NACHT_VON_STUNDE > NACHT_BIS_STUNDE:
        return h >= NACHT_VON_STUNDE or h < NACHT_BIS_STUNDE
    return NACHT_VON_STUNDE <= h < NACHT_BIS_STUNDE


def ist_code_modus(modus: Any) -> bool:
    """True für Aufrufe, die in den Code-Topf zählen (Modus mit Präfix "code-")."""
    return str(modus or "").startswith(CODE_PREFIX)


def _funktionsname(modus: Any) -> str:
    modus = str(modus or "")
    if ist_code_modus(modus):
        return "Code: " + (modus[len(CODE_PREFIX):] or "Aufgabe")
    return FUNKTIONEN.get(modus, modus or "unbekannt")


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


def _ampel(anteil: float, prognose: float, rahmen: float) -> str:
    """60 % gelb, 90 % rot (oder Hochrechnung über dem Deckel)."""
    return "rot" if anteil >= 90 or prognose > rahmen else ("gelb" if anteil >= 60 else "gruen")


def _prognose(gesamt: float, eintraege_monat: list[tuple[dict, datetime.date]], heute: datetime.date) -> float:
    """Hochrechnung ab dem ersten Tag mit Protokoll-Einträgen in diesem Monat -
    sonst würden Tage vor dem Start von Jarvis den Schnitt künstlich senken."""
    if not eintraege_monat:
        return 0.0
    tage_im_monat = calendar.monthrange(heute.year, heute.month)[1]
    erster = min(d for _, d in eintraege_monat)
    tage_gelaufen = (heute - erster).days + 1
    return gesamt / tage_gelaufen * (tage_im_monat - erster.day + 1)


def _topf(eintraege_monat: list[tuple[dict, datetime.date]], rahmen: float, heute: datetime.date) -> dict[str, Any]:
    """Kennzahlen eines Topfes (Rahmen, ausgegeben, Rest, Hochrechnung, Ampel)."""
    gesamt = sum(kosten_eintrag(e) for e, _ in eintraege_monat)
    heute_usd = sum(kosten_eintrag(e) for e, d in eintraege_monat if d == heute)
    prognose = _prognose(gesamt, eintraege_monat, heute)
    anteil = gesamt / rahmen * 100 if rahmen else 0.0
    return {
        "rahmen_usd": rahmen,
        "ausgegeben_usd": round(gesamt, 4),
        "rest_usd": round(rahmen - gesamt, 4),
        "anteil_prozent": round(anteil, 1),
        "heute_usd": round(heute_usd, 4),
        "prognose_monatsende_usd": round(prognose, 2),
        "ampel": _ampel(anteil, prognose, rahmen),
        "anfragen": len(eintraege_monat),
    }


def uebersicht(heute: datetime.date | None = None, alle: Iterable[dict] | None = None) -> dict[str, Any]:
    """Monatsübersicht für das HUD. Oberste Ebene = normaler Topf, "code" = Code-Topf (P23)."""
    heute = heute or datetime.date.today()
    alle = list(eintraege() if alle is None else alle)
    monat = heute.strftime("%Y-%m")

    im_monat = [(e, _datum(e)) for e in alle]
    im_monat = [(e, d) for e, d in im_monat if d and d.strftime("%Y-%m") == monat and d <= heute]
    code_monat = [(e, d) for e, d in im_monat if ist_code_modus(e.get("modus"))]
    im_monat = [(e, d) for e, d in im_monat if not ist_code_modus(e.get("modus"))]

    je_funktion: dict[str, dict] = {}
    je_modell: dict[str, dict] = {}
    je_tag: dict[str, float] = {}
    for eintrag, datum in im_monat:
        usd = kosten_eintrag(eintrag)
        funktion = _funktionsname(eintrag.get("modus"))
        f = je_funktion.setdefault(funktion, {"funktion": funktion, "aufrufe": 0, "usd": 0.0})
        f["aufrufe"] += 1
        f["usd"] += usd
        modell = str(eintrag.get("modell") or "unbekannt")
        m = je_modell.setdefault(modell, {"modell": modell, "aufrufe": 0, "usd": 0.0})
        m["aufrufe"] += 1
        m["usd"] += usd
        je_tag[datum.isoformat()] = je_tag.get(datum.isoformat(), 0.0) + usd

    code_je_funktion: dict[str, dict] = {}
    for eintrag, _ in code_monat:
        funktion = _funktionsname(eintrag.get("modus"))
        f = code_je_funktion.setdefault(funktion, {"funktion": funktion, "aufrufe": 0, "usd": 0.0})
        f["aufrufe"] += 1
        f["usd"] += kosten_eintrag(eintrag)

    def rund(liste: list[dict]) -> list[dict]:
        for x in liste:
            x["usd"] = round(x["usd"], 4)
        return sorted(liste, key=lambda x: x["usd"], reverse=True)

    normal = _topf(im_monat, RAHMEN_USD, heute)
    code = _topf(code_monat, CODE_RAHMEN_USD, heute)
    code["je_funktion"] = rund(list(code_je_funktion.values()))
    return {
        "monat": monat,
        **normal,
        "je_funktion": rund(list(je_funktion.values())),
        "je_modell": rund(list(je_modell.values())),
        "je_tag": [{"tag": t, "usd": round(u, 4)} for t, u in sorted(je_tag.items())],
        "code": code,
        "gpu": _gpu_topf(),
        "gesamt_ausgegeben_usd": round(normal["ausgegeben_usd"] + code["ausgegeben_usd"], 4),
        "links": {"aufladen": LINK_AUFLADEN, "verbrauch": LINK_VERBRAUCH},
        "hinweis": (
            "Schätzung aus dem eigenen Token-Protokoll, Preise ungeprüft. Der echte Kontostand "
            "steht nur in der Anthropic-Konsole. Das Wochenlimit des Claude-Pro-Abos ist davon "
            "getrennt und hier nicht sichtbar. Zwei Töpfe: normaler Rahmen und Code-Deckel (Modus code-*)."
        ),
    }


def _gpu_topf() -> dict | None:
    """P24 (16.10.2026): dritter Topf, GPU-Miete in EUR (app/gpu_miete.py). Fehler dürfen die Übersicht nie stören."""
    try:
        from . import gpu_miete

        return gpu_miete.kosten_topf()
    except Exception:  # noqa: BLE001
        return None


def code_rest(heute: datetime.date | None = None) -> float:
    """Was im Code-Topf diesen Monat noch übrig ist ($)."""
    return float(uebersicht(heute)["code"]["rest_usd"])


# ------------------------------------------------------------------ Texte (Chat, Briefing)

_AMPEL_WORT = {"gruen": "grün", "gelb": "gelb", "rot": "rot"}


def _de(wert: float, stellen: int = 2) -> str:
    return f"{wert:.{stellen}f}".replace(".", ",")


def _topf_zeile(name: str, t: dict) -> str:
    return (f"{name}: {_de(t['ausgegeben_usd'])} von {_de(t['rahmen_usd'], 0)} $ ({_de(t['anteil_prozent'], 0)} %), "
            f"Rest {_de(t['rest_usd'])} $, Hochrechnung Monatsende {_de(t['prognose_monatsende_usd'])} $, "
            f"Ampel {_AMPEL_WORT.get(t['ampel'], t['ampel'])}")


def deckel_zeilen(u: dict | None = None) -> list[str]:
    """Zwei Zeilen: normaler Rahmen und Code-Deckel, je mit Rest, Hochrechnung und Ampel.
    P24: dritte Zeile für die GPU-Miete (EUR), sobald ein RunPod-Schlüssel gesetzt ist oder GPU-Kosten angefallen sind."""
    u = u or uebersicht()
    zeilen = [_topf_zeile("Normaler Rahmen", u), _topf_zeile("Code-Deckel", u["code"])]
    g = u.get("gpu")
    if g and (g.get("aktiv") or g.get("ausgegeben_eur")):
        from . import gpu_miete

        zeilen.append(gpu_miete.zeile(g))
    return zeilen


def chat_text(u: dict | None = None) -> str:
    """Chat-Antwort ohne KI auf "Kostenstand" (0 Cent)."""
    u = u or uebersicht()
    zeilen = deckel_zeilen(u)
    heute = _de(u["heute_usd"] + u["code"]["heute_usd"])
    return (f"Kostenstand {u['monat']}, Sir:\n\n" + "\n".join(f"- {z}" for z in zeilen) + "\n\n"
            f"Heute zusammen {heute} $. Das ist eine Schätzung aus dem Protokoll; den echten Stand zeigt die "
            "Anthropic-Konsole. Die eigene KI kostet nichts.")


# ------------------------------------------------------------------ Chat-Befehl (0 Cent, ohne KI)

_V = r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:bitte\s+)?"
_ANBIETER = r"(?:claude|ki|api|auron|code)"
_KOSTEN_FRAGE = re.compile(
    _V + r"(?:(?:zeig\w*|nenn\w*|sag\w*|gib)\s+(?:mir\s+)?(?:den\s+|die\s+|das\s+|meinen\s+)?)?(?:"
    r"kosten-?(?:stand|übersicht|uebersicht|karte|deckel)|"
    + _ANBIETER + r"-?(?:kosten|rahmen|budget|verbrauch|guthaben|deckel)|"
    r"wie\s+(?:viel|hoch)\s+(?:ist|sind)\s+(?:noch\s+)?(?:der\s+|die\s+|mein\w*\s+)?(?:" + _ANBIETER + r"-?)?"
    r"(?:rahmen|deckel|budget|kosten)(?:\s+(?:noch\s+)?(?:übrig|uebrig|frei))?|"
    r"wie\s+viel\s+(?:hat|haben)\s+(?:mich\s+)?(?:auron|claude|die\s+ki|der\s+code|das\s+api)\s+"
    r"(?:(?:diesen\s+monat|heute|bisher|schon)\s+)*gekostet|"
    r"wie\s+(?:steht|stehen)\s+(?:es\s+um\s+)?(?:den|die|der|meinen)?\s*(?:kostendeckel|rahmen|kosten)|"
    r"wie\s+viel\s+(?:rahmen|budget|deckel|guthaben)\s+(?:ist\s+)?(?:noch\s+)?(?:übrig|uebrig|frei)|"
    r"wie\s+viel\s+(?:ist\s+)?(?:noch\s+)?(?:im|in\s+dem|vom)\s+(?:" + _ANBIETER + r"-?)?(?:deckel|rahmen|budget)\s+"
    r"(?:noch\s+)?(?:übrig|uebrig|frei)"
    r")\s*[?.!]*\s*$|"
    + _V + r"(?:zeig\w*|nenn\w*|sag\w*|gib)\s+(?:mir\s+)?(?:die\s+|meine\s+)?kosten"
    r"(?:\s+(?:von\s+)?(?:diesen\s+monat|heute))?\s*[?.!]*\s*$", re.I)


def absicht(text: str) -> dict | None:
    """Erkennt "Kostenstand" und ähnliche Fragen. Antwort aus dem Protokoll, ohne KI, 0 Cent.
    Bewusst eng: "Was kostet Bitcoin" (Kurs) und "Wie viel habe ich ausgegeben" (Finanzen) gehören nicht hierher."""
    t = (text or "").strip()
    if not t or len(t) > 100 or not _KOSTEN_FRAGE.match(t):
        return None
    return {"art": "antwort", "text": chat_text()}

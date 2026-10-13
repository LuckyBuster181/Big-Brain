"""
Anrede (P20, 13.10.2026): Auron spricht gehoben und wechselt die Anrede je nach Uhrzeit und Lage.

Auswahl: "Sir", "der Herr" (3. Person: "Der Herr wünschen ..."), "mein Herr", "Mylord",
"Eure Exzellenz", "junger Herr", "Herr Maxi".

Regeln (Entscheidung Sir 13.10.2026):
- Warnung, Fehler und jede Rückfrage vor Stufe 2 (Löschen, Herunterfahren): immer "Sir".
- Morgens bis mittags: "Sir" oder "mein Herr".
- Abends und in ruhigen Gesprächen: "der Herr", "junger Herr", "Herr Maxi" (und "Sir").
- Erfolg oder Pointe: gelegentlich "Mylord" oder "Eure Exzellenz", höchstens etwa jede zehnte Antwort.
- Ab 22 Uhr knapp, meist "Sir".

Feste Antworttexte rufen anrede(situation) auf. Dem Sprachmodell geht prompt_block() mit der Tabelle,
der Uhrzeit und der Lage mit (ohne den Cache des langen System-Prompts zu stören).
Kosten: keine, reine Textauswahl.
"""

from __future__ import annotations

import datetime
import random
import re

SIR = "Sir"
ANREDEN = ("Sir", "der Herr", "mein Herr", "Mylord", "Eure Exzellenz", "junger Herr", "Herr Maxi")
SCHWERE = ("Mylord", "Eure Exzellenz")
DRITTE_PERSON = ("der Herr",)

IMMER_SIR = frozenset({"warnung", "fehler", "rueckfrage", "stufe2"})
FEIERLICH = frozenset({"erfolg", "pointe"})
SCHWER_ANTEIL = 0.10  # höchstens jede zehnte Antwort

_SPAET_AB = 22
_NACHT_BIS = 5
_MORGEN_BIS = 13   # morgens bis mittags
_ABEND_AB = 17

_ERKENNUNG = re.compile(
    r"\b(?:Sir|der Herr|mein Herr|Mylord|Eure Exzellenz|junger Herr|Herr Maxi)\b", re.I)


def enthaelt_anrede(text: str) -> bool:
    """True, wenn der Text mindestens eine der erlaubten Anreden enthält (für die Warnlampe im Chat)."""
    return bool(_ERKENNUNG.search(text or ""))


def _jetzt(jetzt: datetime.datetime | None) -> datetime.datetime:
    if jetzt is not None:
        return jetzt
    from . import alltag

    return alltag.jetzt()


def tageszeit(jetzt: datetime.datetime | None = None) -> str:
    h = _jetzt(jetzt).hour
    if h >= _SPAET_AB or h < _NACHT_BIS:
        return "spaet"
    if h < _MORGEN_BIS:
        return "morgens"
    if h < _ABEND_AB:
        return "nachmittags"
    return "abends"


def anrede(situation: str = "ruhig", jetzt: datetime.datetime | None = None,
           zufall: random.Random | None = None) -> str:
    """Wählt die Anrede. situation: warnung, fehler, rueckfrage, stufe2 (immer Sir), erfolg, pointe,
    ruhig, normal. `zufall` mit festem Startwert macht die Auswahl in Tests wiederholbar."""
    z = zufall or random
    s = (situation or "normal").lower()
    if s in IMMER_SIR:
        return SIR
    zeit = tageszeit(jetzt)
    if zeit == "spaet":  # knapp, meist Sir
        return SIR if z.random() < 0.85 else "mein Herr"
    if s in FEIERLICH and z.random() < SCHWER_ANTEIL:
        return z.choice(SCHWERE)
    if zeit in ("morgens", "nachmittags"):
        return SIR if z.random() < 0.65 else "mein Herr"
    # abends und ruhige Gespräche
    if zeit == "abends" or s == "ruhig":
        return z.choice(("der Herr", "junger Herr", "Herr Maxi", "Sir"))
    return SIR


def mit_anrede(satz: str, situation: str = "normal", jetzt: datetime.datetime | None = None,
               zufall: random.Random | None = None) -> str:
    """'Erledigt' -> 'Erledigt, Sir.' (oder eine andere Anrede). Nimmt ein vorhandenes Satzende zurück."""
    a = anrede(situation, jetzt, zufall)
    return f"{(satz or '').rstrip(' .!')}, {a}."


def lage_hinweis(jetzt: datetime.datetime | None = None) -> str:
    return {"morgens": "Morgen/Vormittag", "nachmittags": "Nachmittag", "abends": "Abend",
            "spaet": "spät (ab 22 Uhr) oder Nacht"}[tageszeit(jetzt)]


def prompt_block(jetzt: datetime.datetime | None = None) -> str:
    """Anrede-Regeln für das Sprachmodell: Tabelle, Uhrzeit, Lage."""
    z = _jetzt(jetzt)
    return (
        "ANREDE (wechselt, gehobene Sprache, weiterhin kurz und sachlich)\n"
        f"Es ist {z:%H:%M} Uhr ({lage_hinweis(z)}). Die Lage (Arbeit, ruhig, gestresst, Erfolg, Warnung) erkennst "
        "du am Ton der Frage.\n"
        "Verfügbar: \"Sir\", \"der Herr\" (dritte Person: \"Der Herr wünschen ...\"), \"mein Herr\", \"Mylord\", "
        "\"Eure Exzellenz\", \"junger Herr\", \"Herr Maxi\".\n"
        "- Warnung, Fehler und jede Rückfrage vor Stufe 2 (Löschen, Herunterfahren): immer \"Sir\".\n"
        "- Morgens bis mittags: \"Sir\" oder \"mein Herr\".\n"
        "- Abends und in ruhigen Gesprächen: \"der Herr\", \"junger Herr\", \"Herr Maxi\".\n"
        "- Erfolg oder Pointe: gelegentlich \"Mylord\" oder \"Eure Exzellenz\", höchstens in etwa jeder zehnten Antwort.\n"
        "- Ab 22 Uhr knapp, meist \"Sir\".\n"
        "Mindestens eine Anrede pro Antwort, nicht in jedem Satz. Du sagst und schreibst den Namen Auron, nie einen alten Namen."
    )

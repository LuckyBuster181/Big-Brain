"""
Tagesnotizen lesen, ohne KI (P21, 13.10.2026, Claude Code, Fehler am 12.10.2026).

Fehler vorher: "Leg mir die neue Tagesnotiz vor" ging über die Ähnlichkeitssuche, lieferte
Notizen vom September, und die KI schrieb ungefragt einen Entwurf. Index und Ablage waren in
Ordnung - die Suche versteht "neueste" nicht.

Hier wird nach dem DATEINAMEN gesucht (JJJJ-MM-TT.md im Tagesnotiz-Ordner des Vaults), nicht nach
Ähnlichkeit. Nur lesen: nichts wird geschrieben, nichts gelöscht, nie ein Entwurf erzeugt. Kosten 0 €.

Befehle (Chat und Sprache, siehe absicht()):
    "Leg mir die neue Tagesnotiz vor"   "neueste/letzte/aktuelle Tagesnotiz"
    "Tagesnotiz von heute/gestern/vorgestern"   "Tagesnotiz vom 10.10.[2026] / 10. Oktober / 2026-10-10"
Fehlt die Datei, sagt Auron das und bietet die jüngste an ("ja" zeigt sie, 2 Minuten lang).
Bewusst NICHT: "Schreib/Erstelle/Lege eine Tagesnotiz an", Zusammenfassen, Fragen ÜBER Tagesnotizen.
"""

from __future__ import annotations

import datetime
import re
import time
from pathlib import Path

from . import alltag, briefing

ANGEBOT_S = 120   # so lange gilt das Angebot "die jüngste zeigen?" (wie bei hauptpc.py)

_DATEINAME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.md$")
_angebot: dict = {}


# ------------------------------------------------------------------ Dateien

def ordner() -> Path | None:
    wurzel = briefing.vault_pfad()
    return wurzel / briefing.TAGESNOTIZ_ORDNER if wurzel else None


def vorhandene() -> list[datetime.date]:
    """Alle Tage mit Tagesnotiz, älteste zuerst. Nur Dateien, die genau JJJJ-MM-TT.md heißen;
    Übersichtsnotizen, Monatsnotizen und andere Dateien zählen nicht."""
    pfad = ordner()
    if not pfad:
        return []
    try:
        namen = [p.name for p in pfad.iterdir() if p.is_file()]
    except OSError:
        return []
    tage = []
    for name in namen:
        m = _DATEINAME.match(name)
        if not m:
            continue
        try:
            tage.append(datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            continue
    return sorted(tage)


def neueste() -> datetime.date | None:
    tage = vorhandene()
    return tage[-1] if tage else None


def quelle(tag: datetime.date) -> str:
    return f"{briefing.TAGESNOTIZ_ORDNER}/{tag.isoformat()}.md"


def roh(tag: datetime.date) -> str:
    """Tagesnotiz wie sie ist (mit Frontmatter), auf MAX_NOTIZ_ZEICHEN gekürzt. Leer, wenn es sie
    nicht gibt. Das Briefing nutzt diese Fassung (Verhalten unverändert seit 25.09.2026)."""
    pfad = ordner()
    if not pfad:
        return ""
    try:
        text = (pfad / f"{tag.isoformat()}.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    return text[:briefing.MAX_NOTIZ_ZEICHEN]


def frontmatter_entfernen(text: str) -> str:
    """Schneidet einen YAML-Kopf (--- ... ---) am Anfang ab."""
    if not text.startswith("---"):
        return text
    m = re.match(r"^---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|$)", text, re.S)
    return text[m.end():].lstrip("\r\n") if m else text


def _lesen(tag: datetime.date) -> tuple[str, bool] | None:
    """(Text ohne Frontmatter, gekürzt?) oder None, wenn es die Datei nicht gibt."""
    pfad = ordner()
    if not pfad:
        return None
    try:
        text = (pfad / f"{tag.isoformat()}.md").read_text(encoding="utf-8")
    except OSError:
        return None
    text = frontmatter_entfernen(text).strip()
    gekuerzt = len(text) > briefing.MAX_NOTIZ_ZEICHEN
    return text[:briefing.MAX_NOTIZ_ZEICHEN].rstrip(), gekuerzt


def lesen(tag: datetime.date) -> str:
    """Tagesnotiz ohne Frontmatter, auf MAX_NOTIZ_ZEICHEN gekürzt. Leer, wenn es sie nicht gibt."""
    r = _lesen(tag)
    return r[0] if r else ""


# ------------------------------------------------------------------ Wortmuster

_MONATE = {m.lower(): i + 1 for i, m in enumerate(alltag.MONATE)}
_MONATE.update({"maerz": 3, "jan": 1, "feb": 2, "mär": 3, "mrz": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
                "sep": 9, "sept": 9, "okt": 10, "nov": 11, "dez": 12})

_NOTIZ = r"tages[\s-]?notiz(?:en)?"
_WUNSCH = re.compile(_NOTIZ, re.I)
# Schreib-/Zusammenfass-Wünsche und Fragen ÜBER Tagesnotizen sind keine Lese-Befehle
_SCHREIBEN = re.compile(
    r"\b(?:schreib\w*|erstell\w*|erzeug\w*|generier\w*|entwirf\w*|entwurf|verfass\w*|anlege\w*|fass\w*|zusammen\w*|"
    r"mach(?:e|st)?|ergänz\w*|ergaenz\w*|hinzu\w*|lösch\w*|loesch\w*|verwerf\w*|änder\w*|aender\w*|bearbeit\w*|"
    r"speicher\w*|merk\w*|notier\w*|wie|warum|wozu|wieso|weshalb|was\s+ist\s+eine|brauch\w*|sollte|sollst)\b"
    r"|\bleg(?:e|st)?\b.*\ban\b|\beine?\s+(?:neue|aktuelle|weitere)\b|\bneu\s+an\b",
    re.I,
)
_AUSWAHL = re.compile(r"\b(?:neu[es]\w*|letzte\w*|aktuelle\w*|jüngste\w*|juengste\w*)\b", re.I)
_HEUTE = re.compile(r"\b(heute|heutige\w*|gestern|gestrige\w*|vorgestern|vorgestrige\w*)\b", re.I)
_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_PUNKT = re.compile(r"(?<!\d)(\d{1,2})\.\s?(\d{1,2})\.(?:(\d{4}|\d{2}))?(?!\d)")
_MONATSNAME = re.compile(r"(?<!\d)(\d{1,2})\.?\s+([a-zäöü]{3,9})\.?(?:\s+(\d{4}))?(?!\d)", re.I)


def _datum_bauen(tag: int, monat: int, jahr: int | None, heute: datetime.date) -> datetime.date | None:
    """Ohne Jahr: das jüngste solche Datum, das nicht in der Zukunft liegt."""
    try:
        if jahr is not None:
            return datetime.date(jahr if jahr >= 100 else 2000 + jahr, monat, tag)
        d = datetime.date(heute.year, monat, tag)
        return d if d <= heute else datetime.date(heute.year - 1, monat, tag)
    except ValueError:
        return None


def _datum_lesen(text: str, heute: datetime.date) -> tuple[datetime.date | None, bool]:
    """(Datum, steht ein Datum da, das es nicht gibt?). (None, False) = gar kein Datum im Text."""
    m = _ISO.search(text)
    if m:
        d = _datum_bauen(int(m.group(3)), int(m.group(2)), int(m.group(1)), heute)
        return d, d is None
    m = _PUNKT.search(text)
    if m:
        d = _datum_bauen(int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None, heute)
        return d, d is None
    for m in _MONATSNAME.finditer(text):
        monat = _MONATE.get(m.group(2).lower().rstrip("."))
        if monat:
            d = _datum_bauen(int(m.group(1)), monat, int(m.group(3)) if m.group(3) else None, heute)
            return d, d is None
    m = _HEUTE.search(text)
    if m:
        wort = m.group(1).lower()
        tage = 2 if wort.startswith(("vorgest", "vorgestr")) else 1 if wort.startswith(("gest")) else 0
        return heute - datetime.timedelta(days=tage), False
    return None, False


def absicht(text: str, heute: datetime.date | None = None) -> dict | None:
    """Erkennt "neueste Tagesnotiz" / "Tagesnotiz von gestern/vom 10.10.". None = nicht gemeint.

    Rückgabe: {"art": "tagesnotiz", "wunsch": "neueste"}
              {"art": "tagesnotiz", "wunsch": "tag", "tag": "2026-10-10"}
              {"art": "tagesnotiz", "wunsch": "ungueltig", "text": "..."}   (Datum gibt es nicht)
    """
    t = (text or "").strip()
    if not t or len(t) > 200 or not _WUNSCH.search(t):
        return None
    if _SCHREIBEN.search(t):
        return None
    heute = heute or alltag.jetzt().date()
    d, ungueltig = _datum_lesen(t, heute)
    if ungueltig:
        return {"art": "tagesnotiz", "wunsch": "ungueltig"}
    if d is not None:
        return {"art": "tagesnotiz", "wunsch": "tag", "tag": d.isoformat()}
    if _AUSWAHL.search(t):
        return {"art": "tagesnotiz", "wunsch": "neueste"}
    return None   # "Tagesnotiz" allein oder Fragen darüber: normaler Weg


# ------------------------------------------------------------------ Antworten

def _datum_text(tag: datetime.date) -> str:
    return f"{alltag.WOCHENTAGE[tag.weekday()]}, {tag:%d.%m.%Y}"


def _kurz(tag: datetime.date) -> str:
    return f"{tag:%d.%m.%Y}"


def inhalt(tag: datetime.date) -> dict | None:
    """Baustein für Chat und Alexa: {"tag", "text", "gekuerzt", "quelle"} oder None."""
    r = _lesen(tag)
    if r is None:
        return None
    return {"tag": tag, "text": r[0], "gekuerzt": r[1], "quelle": quelle(tag)}


def anzeige(tag: datetime.date) -> str | None:
    """Fertiger Chat-Text mit Datum, Inhalt und Quelle. None = es gibt die Datei nicht."""
    i = inhalt(tag)
    if i is None:
        return None
    if not i["text"]:
        return f"Die Tagesnotiz vom {_datum_text(tag)} ist leer, Sir.\n\nQuelle: {i['quelle']}"
    gekuerzt = "\n\n(Gekürzt, der Rest steht in der Notiz.)" if i["gekuerzt"] else ""
    return f"Tagesnotiz vom {_datum_text(tag)}, Sir:\n\n{i['text']}{gekuerzt}\n\nQuelle: {i['quelle']}"


def antwort(a: dict, heute: datetime.date | None = None) -> str:
    """Chat-Antwort für eine erkannte Absicht. Merkt sich ein Angebot, wenn die Datei fehlt."""
    heute = heute or alltag.jetzt().date()
    _angebot.clear()
    if a.get("wunsch") == "ungueltig":
        return "Dieses Datum gibt es nicht, Sir. Bitte noch einmal, zum Beispiel \"Tagesnotiz vom 10.10.\"."
    if a.get("wunsch") == "neueste":
        tag = neueste()
        if tag is None:
            return "Im Vault liegt keine Tagesnotiz, Sir."
        return anzeige(tag) or "Die Tagesnotiz konnte ich nicht lesen, Sir."
    tag = datetime.date.fromisoformat(a["tag"])
    text = anzeige(tag)
    if text:
        return text
    jung = neueste()
    if jung is None:
        return f"Für den {_kurz(tag)} gibt es keine Tagesnotiz, Sir. Im Vault liegt überhaupt keine."
    _angebot.update({"tag": jung.isoformat(), "zeit": time.time()})
    return (f"Für den {_kurz(tag)} gibt es keine Tagesnotiz, Sir. Die jüngste ist vom {_kurz(jung)}. "
            f"Soll ich sie zeigen? Sagen Sie \"ja\" (gilt 2 Minuten).")


def bestaetigung(text: str) -> str | None:
    """Antwort auf das Angebot "die jüngste zeigen?". None = kein Angebot offen oder keine Antwort darauf.
    Jede andere Nachricht beendet das Angebot."""
    if not _angebot:
        return None
    if time.time() - _angebot.get("zeit", 0) > ANGEBOT_S:
        _angebot.clear()
        return None
    if alltag._JA.match(text or ""):  # noqa: SLF001 - gleiche Wortliste wie überall
        tag = datetime.date.fromisoformat(_angebot["tag"])
        _angebot.clear()
        return anzeige(tag) or "Die Tagesnotiz konnte ich nicht lesen, Sir."
    if alltag._NEIN.match(text or ""):  # noqa: SLF001
        _angebot.clear()
        return "In Ordnung, Sir."
    _angebot.clear()
    return None

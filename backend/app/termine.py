"""
Termine im Gespräch (05.10.2026, Claude Cowork, Wunsch Sir: "Kalender von Auron erreichbar").

Zwei Dinge, beide OHNE KI (0 €, sofort):

1. Terminfragen aus dem Google-Kalender beantworten (app/kalender.py, iCal, 15 Min. Zwischenspeicher):
       "Was steht heute an?"  "Habe ich morgen Termine?"  "Was habe ich am Freitag vor?"
       "Welche Termine habe ich diese Woche?"  "Wann ist mein nächster Termin?"
       "Wann ist der Zahnarzt?" (sucht im Titel; nichts gefunden -> normale Antwort über die KI)
   Vorher landeten solche Fragen in der Vault-Suche, und die KI antwortete "Dazu steht nichts in
   Ihren Notizen" - der Kalender war für das Gespräch unsichtbar.

2. Termin-Sätze selbst lesen ("Zahnarzt Dienstag 10 Uhr", "Meeting mit Tom am 12.10. von 14:30 bis
   15:30 in Kevelaer"): Tag, Uhrzeit, Ende, Ort und Titel per Regeln. Vorher las das ein Sprachmodell -
   seit dem lokalen Betrieb das kleine qwen-Modell, das bei "Dienstag" gern daneben liegt. Nur wenn
   die Regeln keinen Tag finden, fragt planung.py weiter die KI. Dazu: Hinweis, was an dem Tag schon
   im Kalender steht (Überschneidung).
"""

from __future__ import annotations

import datetime
import re

from . import alltag

WOCHENTAGE_KLEIN = [w.lower() for w in alltag.WOCHENTAGE]
_WT = r"(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)"
MONATE_KLEIN = ["januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september",
                "oktober", "november", "dezember"]
_MONAT_ALIAS = {"jan": 1, "feb": 2, "mär": 3, "maer": 3, "märz": 3, "maerz": 3, "apr": 4, "jun": 6, "jul": 7,
                "aug": 8, "sep": 9, "sept": 9, "okt": 10, "nov": 11, "dez": 12}
_V = r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:sag\s+mal\s*,?\s*|bitte\s+)?"
MAX_ZEILEN = 12


# ------------------------------------------------------------------ Zeitraum aus Text

def _monat(wort: str) -> int | None:
    w = wort.lower().rstrip(".")
    if w in MONATE_KLEIN:
        return MONATE_KLEIN.index(w) + 1
    return _MONAT_ALIAS.get(w)


def _datum_bauen(tag: int, monat: int, jahr: int | None, heute: datetime.date) -> datetime.date | None:
    try:
        if jahr is not None:
            return datetime.date(jahr if jahr > 100 else 2000 + jahr, monat, tag)
        d = datetime.date(heute.year, monat, tag)
        return d if d >= heute - datetime.timedelta(days=1) else datetime.date(heute.year + 1, monat, tag)
    except ValueError:
        return None


def datum_finden(text: str, heute: datetime.date) -> tuple[datetime.date | None, str]:
    """Erstes Datum im Text. Rückgabe: (Datum oder None, gefundener Textteil)."""
    t = text.lower()
    m = re.search(r"\b(übermorgen|uebermorgen|morgen|heute)\b", t)
    kandidaten: list[tuple[int, datetime.date, str]] = []
    if m:
        d = {"heute": 0, "morgen": 1}.get(m.group(1), 2)
        kandidaten.append((m.start(), heute + datetime.timedelta(days=d), m.group(0)))
    m = re.search(r"\b(?:(nächste[nmr]?|naechste[nmr]?|kommende[nmr]?|diese[nmr]?)\s+)?(" + _WT + r")s?\b", t)
    if m:
        ziel = WOCHENTAGE_KLEIN.index(m.group(2))
        abstand = (ziel - heute.weekday()) % 7
        if m.group(1) and m.group(1).startswith(("nächst", "naechst")) and abstand == 0:
            abstand = 7
        kandidaten.append((m.start(), heute + datetime.timedelta(days=abstand), m.group(0)))
    m = re.search(r"\b(\d{1,2})\.\s?(\d{1,2})\.(?:\s?(\d{2,4}))?(?!\d)", t)
    if m:
        d = _datum_bauen(int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None, heute)
        if d:
            kandidaten.append((m.start(), d, m.group(0)))
    m = re.search(r"\b(\d{1,2})\.?\s+([a-zäöü]{3,9})\.?(?:\s+(\d{4}))?\b", t)
    if m and _monat(m.group(2)):
        d = _datum_bauen(int(m.group(1)), _monat(m.group(2)), int(m.group(3)) if m.group(3) else None, heute)
        if d:
            kandidaten.append((m.start(), d, m.group(0)))
    m = re.search(r"\bin\s+(\d{1,2}|einem|zwei|drei|vier|fünf|fuenf|sechs|sieben)\s+tag(?:en)?\b", t)
    if m:
        zahl = {"einem": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "fuenf": 5, "sechs": 6, "sieben": 7}.get(m.group(1))
        kandidaten.append((m.start(), heute + datetime.timedelta(days=zahl or int(m.group(1))), m.group(0)))
    if not kandidaten:
        return None, ""
    kandidaten.sort(key=lambda k: k[0])
    # "morgen" + "Dienstag" zusammen: das genauere (Wochentag/Datum) gewinnt nicht automatisch -
    # das zuerst genannte zählt, wie man es spricht ("Dienstag, also morgen" ist selten).
    _, d, teil = kandidaten[0]
    return d, teil


def zeitraum(text: str, heute: datetime.date | None = None) -> tuple[datetime.date, datetime.date, str] | None:
    """Zeitraum einer Terminfrage: (von, bis einschließlich, Bezeichnung). None = nicht verstanden.
    Leerer Text = heute."""
    heute = heute or alltag.jetzt().date()
    t = (text or "").lower().strip(" ?!,")   # Punkt bleibt: "am 12.10." braucht ihn
    t = re.sub(r"\b(?:so|denn|eigentlich|noch|alles|bei\s+mir|für\s+mich|fuer\s+mich|vor|an|los|für|fuer|am|im|in|der|die|das)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t or t in ("tag", "heutigen tag"):
        return heute, heute, "heute"
    if re.fullmatch(r"(?:diese|die)\s*woche|woche", t):
        ende = heute + datetime.timedelta(days=6 - heute.weekday())
        return heute, ende, "diese Woche"
    if re.fullmatch(r"(?:nächste|naechste|kommende)\s*woche", t):
        start = heute + datetime.timedelta(days=7 - heute.weekday())
        return start, start + datetime.timedelta(days=6), "nächste Woche"
    if re.fullmatch(r"(?:diese[sm]?|am|kommende[sm]?)?\s*wochenende", t):
        sa = heute + datetime.timedelta(days=(5 - heute.weekday()) % 7) if heute.weekday() != 6 else heute
        return sa, sa + datetime.timedelta(days=1 if sa.weekday() == 5 else 0), "am Wochenende"
    if re.fullmatch(r"(?:die\s+)?nächsten\s+tage|naechsten\s+tage|demnächst|demnaechst|bald", t):
        return heute, heute + datetime.timedelta(days=6), "in den nächsten Tagen"
    d, teil = datum_finden(t, heute)
    if d is None:
        return None
    rest = t.replace(teil, " ").strip(" .")
    if rest and not re.fullmatch(r"[\s,]*(?:abend|morgen|früh|frueh|vormittag|nachmittag|mittag)?[\s,]*", rest):
        return None   # da steht noch mehr ("im Projekt X") - keine reine Zeitangabe
    return d, d, tag_bezeichnung(d, heute)


def tag_bezeichnung(d: datetime.date, heute: datetime.date) -> str:
    wt = alltag.WOCHENTAGE[d.weekday()]
    vorne = {0: "heute", 1: "morgen", 2: "übermorgen"}.get((d - heute).days)
    datum = f"{wt}, {d:%d.%m.}"
    return f"{vorne} ({datum})" if vorne else f"am {datum}"


# ------------------------------------------------------------------ Kalender lesen

def _alle() -> list[dict] | None:
    """Termine aus dem Kalender oder None, wenn er nicht eingerichtet/erreichbar ist."""
    from . import kalender

    if not kalender.ist_eingerichtet():
        return None
    try:
        return list(kalender.hole().get("termine") or [])
    except kalender.KalenderFehler:
        return None


def _start(t: dict) -> datetime.datetime:
    s = str(t.get("start") or "")
    try:
        return datetime.datetime.fromisoformat(s if "T" in s else s + "T00:00")
    except ValueError:
        return datetime.datetime.max


def _tag(t: dict) -> datetime.date:
    return _start(t).date()


def _ganztags(t: dict) -> bool:
    return "T" not in str(t.get("start") or "")


def _bis_tag(t: dict) -> datetime.date:
    """Letzter Tag eines Termins (ganztägige Termine enden im iCal am Folgetag)."""
    e = str(t.get("ende") or "")
    try:
        ende = datetime.datetime.fromisoformat(e if "T" in e else e + "T00:00") if e else _start(t)
    except ValueError:
        return _tag(t)
    if _ganztags(t) and ende.date() > _tag(t):
        return ende.date() - datetime.timedelta(days=1)
    return max(ende.date(), _tag(t))


def im_zeitraum(alle: list[dict], von: datetime.date, bis: datetime.date) -> list[dict]:
    return sorted((t for t in alle if _tag(t) <= bis and _bis_tag(t) >= von), key=_start)


def zeile(t: dict, mit_tag: bool = False) -> str:
    titel = str(t.get("titel") or "(ohne Titel)")
    ort = f" ({t['ort']})" if t.get("ort") else ""
    tag = f"{alltag.WOCHENTAGE[_tag(t).weekday()][:2]} {_tag(t):%d.%m.}, " if mit_tag else ""
    if t.get("kategorie") == "feiertag":
        return f"- {tag}Feiertag: {titel}"
    if _ganztags(t):
        return f"- {tag}ganztägig: {titel}{ort}"
    s = str(t["start"])[11:16]
    e = str(t.get("ende") or "")
    bis = f"–{e[11:16]}" if "T" in e and e[:10] == str(t["start"])[:10] else ""
    return f"- {tag}{s}{bis} Uhr: {titel}{ort}"


KEIN_KALENDER = ("Ihren Kalender kann ich gerade nicht lesen, Sir (nicht eingerichtet oder Google antwortet nicht). "
                 "Auf der Seite „Heute“ steht der zuletzt geladene Stand.")


def antwort_zeitraum(von: datetime.date, bis: datetime.date, name: str, alle: list[dict] | None = None,
                     heute: datetime.date | None = None) -> str:
    heute = heute or alltag.jetzt().date()
    alle = _alle() if alle is None else alle
    if alle is None:
        return KEIN_KALENDER
    liste = im_zeitraum(alle, von, bis)
    if von == heute == bis:
        jetzt = alltag.jetzt().replace(tzinfo=None)
        vorbei = [t for t in liste if not _ganztags(t) and _start(t) < jetzt - datetime.timedelta(hours=1)]
        liste = [t for t in liste if t not in vorbei]
    else:
        vorbei = []
    kopf = name[0].upper() + name[1:]
    eigene = [t for t in liste if t.get("kategorie") != "feiertag"]
    if not liste:
        zusatz = f" (heute schon vorbei: {len(vorbei)})" if vorbei else ""
        return f"{kopf} steht nichts im Kalender, Sir.{zusatz}"
    mehrere_tage = von != bis
    if not eigene:
        satz = f"{kopf} keine eigenen Termine, Sir, nur:"
    elif len(eigene) == 1:
        satz = f"{kopf} haben Sie einen Termin, Sir:"
    else:
        satz = f"{kopf} haben Sie {len(eigene)} Termine, Sir:"
    zeilen = [zeile(t, mehrere_tage) for t in liste[:MAX_ZEILEN]]
    if len(liste) > MAX_ZEILEN:
        zeilen.append(f"- … und {len(liste) - MAX_ZEILEN} weitere (Seite „Heute“)")
    return satz + "\n\n" + "\n".join(zeilen)


def antwort_naechster(alle: list[dict] | None = None) -> str:
    alle = _alle() if alle is None else alle
    if alle is None:
        return KEIN_KALENDER
    jetzt = alltag.jetzt().replace(tzinfo=None)
    kommend = [t for t in sorted(alle, key=_start) if t.get("kategorie") != "feiertag"
               and (_start(t) >= jetzt if not _ganztags(t) else _bis_tag(t) >= jetzt.date())]
    if not kommend:
        return "In den nächsten 90 Tagen steht kein Termin im Kalender, Sir."
    t = kommend[0]
    wann = tag_bezeichnung(_tag(t), jetzt.date())
    return f"Ihr nächster Termin ist {wann}, Sir:\n\n{zeile(t)}"


def antwort_suche(was: str, alle: list[dict] | None = None) -> str | None:
    """Termin nach Titel suchen. None = nichts gefunden (dann antwortet die KI wie bisher)."""
    alle = _alle() if alle is None else alle
    w = re.sub(r"(?:termin|termine)$", "", was.lower()).strip(" -")
    if alle is None or len(w) < 3:
        return None
    heute = alltag.jetzt().date()
    treffer = [t for t in sorted(alle, key=_start) if w in str(t.get("titel") or "").lower() and _bis_tag(t) >= heute]
    if not treffer:
        return None
    t = treffer[0]
    satz = f"{t.get('titel')} ist {tag_bezeichnung(_tag(t), heute)}, Sir:\n\n{zeile(t)}"
    if len(treffer) > 1:
        satz += "\n\nDanach noch:\n" + "\n".join(zeile(x, True) for x in treffer[1:4])
    return satz


# ------------------------------------------------------------------ Absicht erkennen (ohne KI)

_FRAGE_AN = re.compile(_V + r"was\s+(?:steht|liegt)\s+(?P<wann>.{0,40}?)\s*an\s*\??\s*$", re.I)
_FRAGE_HABE = re.compile(
    _V + r"(?:habe|hab|hätte|haette)\s+ich\s+(?P<wann>.{0,30}?)\s*(?:noch\s+)?(?:einen?\s+|irgendwelche\s+|irgendeinen\s+)?"
    r"termine?\b(?P<rest>.{0,30}?)\s*\??\s*$", re.I)
_FRAGE_WELCHE = re.compile(
    _V + r"(?:welche|was\s+für|was\s+fuer|zeig\w*\s+(?:mir\s+)?(?:meine|die)|meine)\s+termine\s*"
    r"(?:habe\s+ich\s+|hab\s+ich\s+|stehen\s+|gibt\s+es\s+)?(?P<wann>.{0,30}?)\s*(?:an)?\s*\??\s*$", re.I)
_FRAGE_VOR = re.compile(
    _V + r"was\s+(?:habe|hab|mache|mach)\s+ich\s+(?P<wann>.{0,30}?)\s*(?:so\s+)?(?:vor|geplant|im\s+kalender)\s*\??\s*$", re.I)
_FRAGE_KALENDER = re.compile(_V + r"was\s+(?:steht|ist)\s+(?P<wann>.{0,30}?)\s*(?:in\s+meinem|im)\s+kalender\s*\??\s*$", re.I)
_NAECHSTER = re.compile(
    _V + r"(?:wann|was)\s+(?:ist|habe\s+ich)\s+(?:mein(?:en)?|der|den)\s+(?:nächste[nr]?|naechste[nr]?)\s+termin\s*\??\s*$|"
    + _V + r"(?:mein\s+)?(?:nächster|naechster)\s+termin\s*\??\s*$", re.I)
_SUCHE = re.compile(
    _V + r"wann\s+(?:ist|habe\s+ich|hab\s+ich|bin\s+ich\s+beim?|muss\s+ich\s+zu[mr]?)\s+(?:mein(?:en)?\s+|meine\s+|der\s+|die\s+|das\s+|den\s+|beim?\s+)?"
    r"(?P<was>[a-zäöüß][\wäöüß .\-]{2,40}?)\s*(?:dran)?\s*\??\s*$", re.I)


def absicht(text: str) -> dict | None:
    """Terminfrage erkannt -> {"art": "antwort", "text": ...} (fertig, ohne KI). Sonst None."""
    t = (text or "").strip()
    if not t or len(t) > 160:
        return None
    if _NAECHSTER.match(t):
        return {"art": "antwort", "text": antwort_naechster()}
    for muster in (_FRAGE_AN, _FRAGE_HABE, _FRAGE_WELCHE, _FRAGE_VOR, _FRAGE_KALENDER):
        m = muster.match(t)
        if not m:
            continue
        rest = (m.groupdict().get("rest") or "").strip()
        if rest and not zeitraum(rest):
            continue
        z = zeitraum(m.group("wann") + " " + rest)
        if z:
            return {"art": "antwort", "text": antwort_zeitraum(*z)}
    m = _SUCHE.match(t)
    if m and not re.search(r"\b(?:heute|morgen|feierabend|schluss|zeit|wetter)\b", m.group("was"), re.I):
        text_suche = antwort_suche(m.group("was"))
        if text_suche:
            return {"art": "antwort", "text": text_suche}
    return None


# ------------------------------------------------------------------ Termin-Satz lesen (ohne KI)

_UHR = re.compile(
    r"\b(?:(?:von|ab|um|gegen)\s+)?(?P<h1>[01]?\d|2[0-3])(?:[:.](?P<m1>[0-5]\d))?\s*(?:uhr)?"
    r"(?:\s*(?:-|–|bis)\s*(?P<h2>[01]?\d|2[0-3])(?:[:.](?P<m2>[0-5]\d))?)?\s*(?:uhr)?\b", re.I)
_TAGESZEIT = re.compile(r"\b(abends|nachmittags|am\s+abend|am\s+nachmittag|morgens|vormittags|früh|frueh)\b", re.I)
_ORT = re.compile(r"\s+(?:in|im)\s+(?P<ort>[A-ZÄÖÜ][\wäöüß\-]+(?:\s+[A-ZÄÖÜ][\wäöüß\-]+){0,2})\s*$")
_FUELL = re.compile(r"\b(?:am|um|von|bis|ab|gegen|uhr|nächste[nmr]?|naechste[nmr]?|kommende[nmr]?|diese[nmr]?|den|der|ganztags|ganztägig)\b",
                    re.I)


def termin_lesen(satz: str, jetzt: datetime.datetime | None = None) -> dict | None:
    """Termin aus einem Satz. None = kein Tag/Uhrzeit sicher erkannt (dann fragt planung.py die KI).
    Rückgabe wie planung.termin_lesen: titel, start, ende, ganztags, ort, unklar."""
    jetzt = (jetzt or alltag.jetzt()).replace(tzinfo=None)
    heute = jetzt.date()
    rest = " " + re.sub(r"\s+", " ", satz or "").strip() + " "
    ort = ""
    m = _ORT.search(rest.rstrip(" .!"))
    if m:
        ort = m.group("ort")
        rest = rest[:m.start()] + " "
    tag, teil = datum_finden(rest, heute)
    if teil:
        rest = re.sub(re.escape(teil), " ", rest, count=1, flags=re.I)
    # Uhrzeit: nur Zahlen mit "Uhr", Doppelpunkt oder "um/von/ab" davor - "12 Flaschen" ist keine Uhrzeit
    zeit = None
    for z in _UHR.finditer(rest):
        stueck = z.group(0).lower()
        if "uhr" in stueck or ":" in stueck or re.match(r"(?:um|von|ab|gegen)\s", stueck) or z.group("h2"):
            zeit = z
            break
    unklar = ""
    start_t = ende_t = None
    if zeit:
        h1, m1 = int(zeit.group("h1")), int(zeit.group("m1") or 0)
        abends = _TAGESZEIT.search(rest)
        if abends and abends.group(1).lower().startswith(("abend", "am abend", "nachmittag", "am nachmittag")) and h1 < 12:
            h1 += 12
        start_t = datetime.time(h1, m1)
        if zeit.group("h2"):
            h2, m2 = int(zeit.group("h2")), int(zeit.group("m2") or 0)
            if abends and h2 < 12 and h1 >= 12:
                h2 += 12
            ende_t = datetime.time(h2, m2)
        rest = rest[:zeit.start()] + " " + rest[zeit.end():]
        if abends:
            rest = rest.replace(abends.group(0), " ")
    if tag is None and start_t is None:
        return None
    if tag is None:
        tag = heute if datetime.datetime.combine(heute, start_t) > jetzt else heute + datetime.timedelta(days=1)
        unklar = f"kein Tag genannt – ich habe {tag_bezeichnung(tag, heute)} genommen"
    titel = _FUELL.sub(" ", rest)
    titel = re.sub(r"[\s,;:\-–]+", " ", titel).strip(" .!,")
    titel = re.sub(r"^(?:mit\s+)?$", "", titel)
    if len(titel) < 2:
        return None
    titel = titel[0].upper() + titel[1:]
    start = datetime.datetime.combine(tag, start_t or datetime.time(0, 0))
    ende = datetime.datetime.combine(tag, ende_t) if ende_t else None
    if ende and ende <= start:
        ende = None
    return {"titel": titel[:150], "start": start, "ende": ende, "ganztags": start_t is None, "ort": ort[:150],
            "unklar": unklar, "kosten_usd": 0.0}


def am_selben_tag(start: datetime.datetime) -> list[str]:
    """Was an dem Tag schon im Kalender steht (für den Hinweis beim Eintragen)."""
    alle = _alle()
    if not alle:
        return []
    return [zeile(t) for t in im_zeitraum(alle, start.date(), start.date()) if t.get("kategorie") != "feiertag"][:5]

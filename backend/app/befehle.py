"""
Neue Chat-/Sprachbefehle (27.09.2026, Claude Cowork) - Erkennung ohne Claude, 0 Cent.

Wird von app/alltag.absicht() aufgerufen, NACH "ja/nein" auf offene Vorschläge,
Stopp, Uhrzeit und Datum, aber VOR dem Seitenwechsel im HUD und dem Diktat -
sonst würde "Mach eine Mind Map ..." die HUD-Seite "Karte" öffnen und
"Merk dir die Recherche" ein Diktat anlegen.

Was erkannt wird (Beispiele in den Modulen):
    art "pc"                  app/hauptpc.py      Haupt-PC steuern
    art "schreiben"           app/schreiben.py    Text oder Prompt schreiben
    art "recherche"           app/recherche.py    Websuche am Tag
    art "recherche_speichern" app/recherche.py
    art "mindmap"             app/mindmap.py      neu / ergänzen / liste
    art "projekt"             app/projekte.py     neu / ergänzen / liste / zeigen
    art "termin"              app/planung.py      Termin eintragen (Link oder direkt)
    art "tagesplan"           app/planung.py
    art "umwandeln"           app/umwandeln.py    Dateien in der Ablage umwandeln
    art "whatsapp"            app/whatsapp.py     Link mit fertigem Text, Kontakte merken
"""

from __future__ import annotations

import re

_V = r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:bitte\s+)?(?:(?:kannst|könntest|koenntest)\s+du\s+(?:mir\s+)?)?"
_MM = r"(?:mind\s*-?\s*maps?|mindmaps?)"

# --------------------------------------------------------------- Schreiben
_PROMPT = re.compile(_V + r"(?:schreib|formulier|erstell|bau|mach|entwirf|verfass)\w*\s+(?:mir\s+)?(?:(?:einen|nen|ein|den)\s+)?"
                     r"(?:guten\s+|kurzen\s+|langen\s+|besseren\s+)?(?:ki-?\s*)?prompt\b", re.I)
_TEXT = re.compile(_V + r"(?:schreib|formulier|verfass|entwirf|entwerf)\w*\s+(?:mir\s+)?(?:(?:eine?n?|die|den|das|nen|ne)\s+)?"
                   r"(?:kurze\w*\s+|nette\w*\s+|freundliche\w*\s+|förmliche\w*\s+|lockere\w*\s+|höfliche\w*\s+)?"
                   r"(?:whatsapp|nachricht|mail|e-?mail|sms|text|brief|antwort|bewerbung|anschreiben|kündigung|"
                   r"kuendigung|beitrag|post|caption|kommentar|entschuldigung|einladung|absage|zusage|glückwunsch|"
                   r"gluckwunsch|glueckwunsch|rede|beschreibung|anfrage|beschwerde)\w*\b", re.I)
_VERBESSERN = re.compile(_V + r"(?:verbesser|korrigier|überarbeit|ueberarbeit|kürz|kuerz)\w*\s+(?:mir\s+)?"
                         r"(?:diese\w*|den|die|das|meine\w*)\s+(?:text|nachricht|mail|e-?mail|satz|sätze|absatz|prompt)\b", re.I)

# --------------------------------------------------------------- WhatsApp (27.09.2026, app/whatsapp.py)
_WA_DIREKT = re.compile(_V + r"(?:whatsapp|whats\s*app|wa)\s+(?:an|für|fuer|to)\s+(?P<name>[^:\n]{1,40}?)\s*:\s*(?P<text>.+)$",
                        re.I | re.S)
_WA_KONTAKT = re.compile(_V + r"(?:speicher\w*|merk\s*dir|neuer|leg\w*\s+an)\s+(?:den\s+|einen\s+)?kontakt\s*:?\s*"
                         r"(?P<name>[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß .'-]{0,38}?)\s*[:,]?\s*(?:nummer\s*:?\s*)?"
                         r"(?P<nr>\+?[\d][\d /-]{5,20})\s*[.!]?\s*$", re.I)
_WA_LISTE = re.compile(_V + r"(?:meine\s+kontakte|welche\s+kontakte\s+(?:hast\s+du|kennst\s+du)|zeig\w*\s+(?:mir\s+)?"
                       r"(?:meine\s+|die\s+)?kontakte)\s*\??\s*$", re.I)

# --------------------------------------------------------------- Recherche
_RECHERCHE = re.compile(
    _V + r"(?:recherchier\w*|such\w*\s+(?:mal\s+)?im\s+(?:internet|netz|web)|google\s*(?:mal)?|"
    r"schau\w*\s+(?:mal\s+)?im\s+(?:internet|netz)(?:\s+nach)?|finde?\s+im\s+(?:internet|netz)|"
    r"was\s+gibt\s+es\s+neues\s+(?:zu|über|ueber|bei|von))\s*[:,]?\s*(?:mal\s+)?(?:nach\s+)?(?P<frage>.{3,})$",
    re.I | re.S)
_RECHERCHE_SPEICHERN = re.compile(
    _V + r"(?:speicher\w*|sicher\w*|merk\s*dir|leg\w*\s+ab)\s+(?:die|diese|das|deine)\s+(?:recherche|ergebnis\w*|suche)"
    r"(?:\s+(?:im|in\s+den)\s+vault)?\s*(?:ab)?\s*[.!]?\s*$", re.I)

# --------------------------------------------------------------- Mind Maps
_MM_LISTE = re.compile(_V + r"(?:welche\s+|meine\s+|zeig\w*\s+(?:mir\s+)?(?:alle\s+|meine\s+)?|liste\w*\s+(?:alle\s+)?)"
                       + _MM + r"(?:\s+(?:habe|hab)\s+ich)?\s*\??\s*$", re.I)
_MM_NEU = re.compile(
    _V + r"(?:(?:neue\s+)?" + _MM + r"\s*[:\-–]\s*(?P<a>.{2,})|"
    r"(?:mach|erstell|bau|zeichne|mal|entwirf|entwerf)\w*\s+(?:mir\s+)?(?:(?:eine|ne|die)\s+)?(?:neue\s+)?" + _MM
    + r"\s*(?:zu[mr]?|über|ueber|für|fuer|von|aus|:|-|–)\s*(?:de[mnr]\s+|die\s+|das\s+|meine\w*\s+)?(?P<b>.{2,}))$",
    re.I | re.S)
_MM_ERG = re.compile(
    _V + r"(?:(?:ergänz|ergaenz|erweiter|änder|aender|aktualisier|überarbeit|ueberarbeit)\w*\s+(?:die\s+)?" + _MM
    + r"\s+(?P<a>.+?)|" + _MM + r"\s+(?P<b>.+?)\s+(?:ergänzen|ergaenzen|erweitern|ändern|aendern))\s*[:\-–]\s*(?P<text>.{2,})$",
    re.I | re.S)

# --------------------------------------------------------------- Projekte
_PR_NEU = re.compile(
    _V + r"(?:neues\s+projekt|projekt\s+anlegen|lass\s+uns\s+(?:ein\s+)?(?:neues\s+)?projekt\s+(?:planen|starten|anlegen)|"
    r"plan\w*\s+(?:mit\s+mir\s+)?(?:ein|das)\s+(?:neues\s+)?projekt)\s*[:\-–,]?\s*(?P<text>.{3,})$", re.I | re.S)
_PR_LISTE = re.compile(_V + r"(?:meine\s+projekte|welche\s+projekte\s+(?:habe|hab|laufen|gibt\s+es)\w*(?:\s+ich)?|"
                       r"zeig\w*\s+(?:mir\s+)?(?:meine\s+|alle\s+)?projekte)\s*\??\s*$", re.I)
_PR_ZEIGEN = re.compile(_V + r"(?:was\s+steht\s+(?:im|in|bei)\s+(?:dem\s+)?projekt|was\s+ist\s+(?:als\s+)?n(?:ä|ae)chstes\s+"
                        r"(?:dran\s+)?(?:im|in|bei)\s+(?:dem\s+)?projekt|stand\s+(?:vom|von|im)\s+projekt)\s+(?P<name>.+?)"
                        r"(?:\s+an)?\s*\??\s*$", re.I)
_PR_ERG = re.compile(_V + r"projekt\s+(?P<name>[^:\n]{2,60}?)\s*[:\-–]\s*(?P<text>.{3,})$", re.I | re.S)

# --------------------------------------------------------------- Planung
_TERMIN = re.compile(
    _V + r"(?:(?:neuer\s+)?termin\s*[:\-–]\s*(?P<a>.{4,})|trag\w*\s+(?:mir\s+)?(?P<b>.{4,}?)\s+in\s+(?:den|meinen)\s+kalender"
    r"(?:\s+ein)?|(?:trag|schreib)\w*\s+(?:mir\s+)?(?:in\s+den\s+kalender\s+)?ein\s*[:\-–]\s*(?P<c>.{4,}))\s*[.!]?\s*$",
    re.I | re.S)
_TAGESPLAN = re.compile(
    _V + r"(?:tagesplan\b|(?:plan|plane|planen)\w*\s+(?:mir\s+|mit\s+mir\s+)*(?:meinen|den)\s+(?:tag|montag|dienstag|mittwoch|"
    r"donnerstag|freitag|samstag|sonntag)\b|(?:plan|plane)\s+(?:mir\s+|mit\s+mir\s+)*(?:heute|morgen|übermorgen|uebermorgen)\b|"
    r"lass\s+uns\s+(?:den|meinen)\s+(?:tag|morgigen\s+tag)\s+planen|was\s+mache\s+ich\s+(?:heute|morgen)\s+wann)", re.I)

# --------------------------------------------------------------- Briefing (05.10.2026)
# Vorher landete "Briefing" im Chat in der Vault-Suche, und die KI erfand ein Briefing aus alten Notizen.
_BRIEFING = re.compile(
    _V + r"(?:(?:mein|das|ein|dein)\s+)?(?:tages-?|morgen-?|abend-?)?briefing(?:\s+(?:bitte|jarvis|auron|für\s+heute|fuer\s+heute))?|"
    + _V + r"(?:gib|mach)\w*\s+(?:mir\s+)?(?:das|ein|mein)\s+(?:tages-?)?briefing|" + _V + r"brief\s+mich", re.I)
_BRIEFING_GANZ = re.compile(r"\s*[.!?]*\s*$")

# --------------------------------------------------------------- Umwandeln
_ZIEL = r"(?P<ziel>png|jpe?g|webp|gif|bmp|pdf|txt|text|bilder?|fotos?)s?"
_UMW1 = re.compile(_V + r"(?:wandle?|konvertier\w*|verwandel\w*|änder\w*|aender\w*|mach|speicher\w*|exportier\w*)\s+"
                   r"(?P<quelle>.+?)\s+(?:in|zu|nach|als)\s+(?:eine?n?\s+|ein\s+)?" + _ZIEL
                   + r"(?:-?dateien?|-?datei)?\s*(?:um)?\s*[.!]?\s*$", re.I)
_UMW2 = re.compile(_V + r"(?:mach|erstell|bau)\w*\s+(?:mir\s+)?aus\s+(?P<quelle>.+?)\s+(?:eine?n?\s+|ein\s+)?" + _ZIEL
                   + r"\s*[.!]?\s*$", re.I)
_UMW_MEHR = re.compile(_V + r"(?:(?:mach|pack|füg|fueg)\w*\s+)?(?:(?:mir\s+)?aus\s+)?(?:die\s+)?letzten\s+(?P<n>\d{1,2})\s+"
                       r"(?:bilder|fotos)\s+(?:als|zu|in)\s+(?:eine?\s+|ein\s+)?pdf\b.*$", re.I)
_DATEI = re.compile(r"[\w\-. ()äöüÄÖÜß]+\.(?:pdf|png|jpe?g|webp|gif|bmp|tiff?|docx?|odt|pptx?|xlsx?|heic)\b", re.I)


def _quelle(roh: str) -> dict:
    roh = roh.strip().strip('"\'')
    m = _DATEI.search(roh)
    if m:
        return {"datei": m.group(0).strip()}
    r = roh.lower()
    if "pdf" in r:
        return {"typ": "pdf"}
    if re.search(r"bild|foto|screenshot|png|jpg|webp", r):
        return {"typ": "bild"}
    if re.search(r"(?:letzte|neueste|diese|die|der|das)\s*(?:datei|dokument)?$|datei|dokument", r):
        return {}
    return {"datei": roh}


def _umwandeln(t: str) -> dict | None:
    m = _UMW_MEHR.match(t)
    if m:
        return {"art": "umwandeln", "ziel": "pdf", "anzahl": int(m.group("n"))}
    m = _UMW1.match(t) or _UMW2.match(t)
    if not m:
        return None
    quelle = m.group("quelle")
    # nur mit erkennbarer Datei, sonst ist "Mach das als Text" o.ä. gemeint
    if not (_DATEI.search(quelle) or re.search(r"\b(?:pdf|datei|dokument|bild|bilder|foto|fotos|screenshot)\b", quelle, re.I)):
        return None
    ziel = m.group("ziel").lower()
    ziel = {"bild": "png", "bilder": "png", "foto": "jpg", "fotos": "jpg", "text": "txt", "jpeg": "jpg"}.get(ziel, ziel)
    return {"art": "umwandeln", "ziel": ziel, **_quelle(quelle)}


def absicht(text: str) -> dict | None:
    t = (text or "").strip()
    if not t or len(t) > 4000:
        return None
    from . import hauptpc

    pc = hauptpc.absicht(t)
    if pc:
        return pc
    m = _WA_DIREKT.match(t)
    if m:
        return {"art": "whatsapp", "aktion": "direkt", "name": m.group("name").strip(), "text": m.group("text").strip()}
    m = _WA_KONTAKT.match(t)
    if m:
        return {"art": "whatsapp", "aktion": "kontakt", "name": m.group("name").strip(), "nummer": m.group("nr").strip()}
    if _WA_LISTE.match(t):
        return {"art": "whatsapp", "aktion": "liste"}
    if _MM_LISTE.match(t):
        return {"art": "mindmap", "aktion": "liste"}
    m = _MM_ERG.match(t)
    if m:
        return {"art": "mindmap", "aktion": "ergaenzen", "name": (m.group("a") or m.group("b")).strip(),
                "text": m.group("text").strip()}
    m = _MM_NEU.match(t)
    if m:
        return {"art": "mindmap", "aktion": "neu", "thema": (m.group("a") or m.group("b")).strip()}
    if _PR_LISTE.match(t):
        return {"art": "projekt", "aktion": "liste"}
    m = _PR_NEU.match(t)
    if m:
        return {"art": "projekt", "aktion": "neu", "text": m.group("text").strip()}
    m = _PR_ZEIGEN.match(t)
    if m:
        return {"art": "projekt", "aktion": "zeigen", "name": m.group("name").strip()}
    m = _PR_ERG.match(t)
    if m:
        return {"art": "projekt", "aktion": "ergaenzen", "name": m.group("name").strip(), "text": m.group("text").strip()}
    if _RECHERCHE_SPEICHERN.match(t):
        return {"art": "recherche_speichern"}
    m = _RECHERCHE.match(t)
    if m:
        return {"art": "recherche", "frage": m.group("frage").strip()}
    if _PROMPT.match(t):
        return {"art": "schreiben", "was": "prompt", "auftrag": t}
    if _TEXT.match(t) or _VERBESSERN.match(t):
        return {"art": "schreiben", "was": "text", "auftrag": t}
    b = _BRIEFING.match(t)
    if b and _BRIEFING_GANZ.fullmatch(t[b.end():]):
        return {"art": "briefing"}
    m = _TERMIN.match(t)
    if m:
        return {"art": "termin", "text": (m.group("a") or m.group("b") or m.group("c")).strip()}
    if _TAGESPLAN.match(t):
        return {"art": "tagesplan", "text": t}
    u = _umwandeln(t)
    if u:
        return u
    return None

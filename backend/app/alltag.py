"""
Alltagswerkzeuge und Absichts-Erkennung (Phase 2.7 und 3, 23.09.2026).

Alles hier läuft OHNE Claude-Aufruf und kostet deshalb nichts:
- rechnen():   sicherer Taschenrechner (nur Zahlen und Rechenzeichen, kein eval)
- datum_text() / uhrzeit_text(): Datum, Wochentag, Kalenderwoche, Uhrzeit
- kurs_symbol(): erkennt kurze Kursfragen ("Wie steht Gold?") - die Antwort holt
               app/marktdaten.kurs_antwort() ohne Claude (seit 26.09.2026)
- absicht():   erkennt, ob eine Eingabe eine FRAGE (-> normaler Chat), ein
               BEFEHL (HUD-Seite wechseln, still sein, Uhrzeit, Rechnen) oder
               ein DIKTAT ("Merk dir ...", "Notiere ...") ist. Diktate werden
               nicht sofort geschrieben, sondern als Vorschlag angelegt, den
               Sir bestätigt (app/vorschlaege.py) - Jarvis kündigt jede
               Änderung vorher an.

Bewusst vorsichtig: Im Zweifel ist es eine Frage und geht an Claude. Ein
falsch erkannter Befehl wäre ärgerlicher als ein paar Zehntel Cent.
"""

from __future__ import annotations

import ast
import datetime
import math
import operator
import re
from dateutil import tz

# dateutil statt zoneinfo: unter Windows fehlt zoneinfo die Zeitzonen-Datenbank
# (Paket tzdata), dateutil bringt sie mit - wie app/kalender.py.
ZEITZONE = tz.gettz("Europe/Berlin") or tz.tzlocal()

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
          "Oktober", "November", "Dezember"]


class RechenFehler(ValueError):
    pass


# ------------------------------------------------------------------ Rechner

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_EINSTELLIG = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNKTIONEN = {
    "sqrt": math.sqrt, "wurzel": math.sqrt, "abs": abs, "round": round, "runden": round,
    "min": min, "max": max, "log": math.log, "ln": math.log, "log10": math.log10,
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "exp": math.exp,
}
_KONSTANTEN = {"pi": math.pi, "e": math.e}

# Wörter -> Rechenzeichen (Reihenfolge wichtig: längere zuerst)
_WORTE = [
    (r"\bgeteilt\s+durch\b", "/"), (r"\bdividiert\s+durch\b", "/"), (r"\bdurch\b", "/"),
    (r"\bmultipliziert\s+mit\b", "*"), (r"\bmal\b", "*"), (r"\bplus\b", "+"), (r"\bminus\b", "-"),
    (r"\bhoch\b", "**"), (r"\bmodulo\b", "%"), (r"\bquadrat\b", "**2"),
    (r"\bwurzel\s+aus\b", "sqrt"), (r"\bwurzel\s+von\b", "sqrt"),
]
_PROZENT_VON = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:%|prozent)\s+(?:von|aus)\s+(\d+(?:[.,]\d+)?)", re.I)
_ERLAUBT = re.compile(r"^[\d\s+\-*/%().,a-z_]*$")
MAX_ZEICHEN = 200
MAX_POTENZ = 1000


def _auswerten(knoten: ast.AST) -> float:
    if isinstance(knoten, ast.Expression):
        return _auswerten(knoten.body)
    if isinstance(knoten, ast.Constant) and isinstance(knoten.value, (int, float)) and not isinstance(knoten.value, bool):
        return knoten.value
    if isinstance(knoten, ast.BinOp) and type(knoten.op) in _OPS:
        links, rechts = _auswerten(knoten.left), _auswerten(knoten.right)
        if isinstance(knoten.op, ast.Pow) and abs(rechts) > MAX_POTENZ:
            raise RechenFehler("Exponent zu groß.")
        return _OPS[type(knoten.op)](links, rechts)
    if isinstance(knoten, ast.UnaryOp) and type(knoten.op) in _EINSTELLIG:
        return _EINSTELLIG[type(knoten.op)](_auswerten(knoten.operand))
    if isinstance(knoten, ast.Call) and isinstance(knoten.func, ast.Name) and knoten.func.id in _FUNKTIONEN:
        if knoten.keywords or len(knoten.args) > 3:
            raise RechenFehler("Ungültiger Funktionsaufruf.")
        return _FUNKTIONEN[knoten.func.id](*[_auswerten(a) for a in knoten.args])
    if isinstance(knoten, ast.Name) and knoten.id in _KONSTANTEN:
        return _KONSTANTEN[knoten.id]
    raise RechenFehler("Nur Zahlen, + - * / % ** und einfache Funktionen erlaubt.")


def ausdruck_normalisieren(text: str) -> str:
    """Deutsche Schreibweisen in Python-Rechenausdruck umwandeln."""
    t = text.strip().lower().rstrip("?!.= ")
    t = re.sub(r"^(was|wie\s*viel)\s+(ist|sind|ergibt|macht|gibt)\s+(die\s+|der\s+|das\s+)?", "", t)
    t = re.sub(r"^(rechne|berechne|rechne mal|bitte)\s*:?\s*", "", t)
    t = _PROZENT_VON.sub(lambda m: f"({m.group(1)}/100*{m.group(2)})", t)
    for muster, ersatz in _WORTE:
        t = re.sub(muster, f" {ersatz} ", t)
    t = t.replace("×", "*").replace("÷", "/").replace("^", "**")
    t = re.sub(r"(?<=\d)\s*x\s*(?=\d)", "*", t)
    t = re.sub(r"sqrt\s+(\d+(?:[.,]\d+)?)", r"sqrt(\1)", t)
    # 3,5 -> 3.5 (nur zwischen Ziffern); Tausenderpunkte 1.000 bleiben 1.000 = 1.0 -> vorher entfernen
    t = re.sub(r"(?<=\d)\.(?=\d{3}\b)", "", t)
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)
    t = t.replace(" ,", ",")
    return re.sub(r"\s+", " ", t).strip()


def rechnen(text: str) -> float:
    ausdruck = ausdruck_normalisieren(text)
    if not ausdruck or len(ausdruck) > MAX_ZEICHEN or not _ERLAUBT.match(ausdruck) or not re.search(r"\d", ausdruck):
        raise RechenFehler("Kein Rechenausdruck.")
    try:
        baum = ast.parse(ausdruck, mode="eval")
    except SyntaxError as exc:
        raise RechenFehler("Rechenausdruck nicht lesbar.") from exc
    try:
        ergebnis = _auswerten(baum)
    except ZeroDivisionError as exc:
        raise RechenFehler("Division durch null.") from exc
    except (OverflowError, ValueError, TypeError) as exc:
        raise RechenFehler(f"Nicht berechenbar: {exc}") from exc
    if isinstance(ergebnis, complex) or (isinstance(ergebnis, float) and not math.isfinite(ergebnis)):
        raise RechenFehler("Ergebnis ist keine endliche Zahl.")
    return ergebnis


def zahl_deutsch(wert: float) -> str:
    if isinstance(wert, int) or float(wert).is_integer():
        return f"{int(wert):,}".replace(",", ".")
    text = f"{wert:,.6f}".rstrip("0").rstrip(".")
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


# ------------------------------------------------------------ Datum/Uhrzeit


def jetzt() -> datetime.datetime:
    return datetime.datetime.now(ZEITZONE)


def datum_text(zeit: datetime.datetime | None = None) -> str:
    z = zeit or jetzt()
    kw = z.isocalendar()[1]
    return f"{WOCHENTAGE[z.weekday()]}, der {z.day}. {MONATE[z.month - 1]} {z.year} (KW {kw})"


def uhrzeit_text(zeit: datetime.datetime | None = None) -> str:
    z = zeit or jetzt()
    return f"{z.hour}:{z.minute:02d} Uhr"


def datum_uhrzeit(zeit: datetime.datetime | None = None) -> dict:
    z = zeit or jetzt()
    return {"datum": z.date().isoformat(), "uhrzeit": z.strftime("%H:%M"), "wochentag": WOCHENTAGE[z.weekday()],
            "kalenderwoche": z.isocalendar()[1], "text": f"{datum_text(z)}, {uhrzeit_text(z)}"}


# --------------------------------------------------------------- Absichten

# HUD-Seiten, auf die Jarvis per Sprache wechseln kann (id wie in index.html)
SEITEN = {
    "markt": ("markt", "kurse", "chart", "börse", "boerse", "trading"),
    "alltag": ("alltag", "wetter", "kalender", "termine"),
    "jarvis": ("jarvis", "auron", "chat", "gespräch", "gespraech"),
    "vault": ("gedächtnis", "gedaechtnis", "vault", "notizen", "wissensnetz"),
    "settings": ("einstellungen", "einstellung", "optionen"),
    "labor": ("labor", "sandbox", "backtest", "prüfstand", "pruefstand", "paper", "papertrading"),
    "tiktok": ("tiktok", "tik tok"),
    "denkblock": ("denkblock", "denk block", "gedanken", "ideen", "denkseite"),
    "karte": ("karte", "gesamtkarte", "mindmap", "mind map", "übersichtskarte", "uebersichtskarte"),
    # 26.09.2026: fehlten noch
    "pc2": ("pc 2", "pc2", "pc zwei", "mini-pc", "minipc", "mini pc", "zweiter pc", "server"),
    "geraete": ("geräte", "geraete", "geräteseite", "bildschirme"),
    # 26.09.2026 abends: Nachtaufträge + Frage des Tages
    "nacht": ("nacht", "nachtaufträge", "nachtauftraege", "nachtauftrag", "nachtarbeit", "aufträge", "auftraege"),
    # 11.10.2026: Bereich Finanzen (werkstatt/finanzen, app/finanzen.py)
    "finanzen": ("finanzen", "finanzbereich", "konten", "kontoauszüge", "kontoauszuege", "kosten und abos"),
}
_NAV = re.compile(
    r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:bitte\s+)?(?:zeig(?:e)?|öffne|oeffne|geh(?:e)?|wechsel(?:e)?|wechsle|spring(?:e)?|mach)"
    r"\s+(?:mir\s+)?(?:zu[mr]?\s+|auf\s+|in\s+|nach\s+)?(?:(?:den|die|das|dem|der)\s+)?"
    r"(?P<ziel>[a-zäöüß0-9\- ]{2,20}?)\s*(?:seite|an|auf)?\s*(?:bitte)?[.!]?\s*$",  # 26.09.: Ziffern und Bindestrich (PC 2, Mini-PC)
    re.I,
)
_STUMM = re.compile(r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:stopp|stop|halt|sei still|ruhe|psst|pst|hör auf|hoer auf)\s*[.!]?\s*$", re.I)
_UHRZEIT = re.compile(r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:wie\s*spät\s*ist\s*es|wie\s*viel\s*uhr\s*(?:ist\s*es|haben\s*wir)|uhrzeit)\s*\??\s*$", re.I)
_DATUM = re.compile(
    r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:welcher\s*tag\s*ist\s*heute|welches\s*datum\s*(?:ist\s*heute|haben\s*wir)?|"
    r"der\s*wievielte\s*ist\s*heute|was\s*ist\s*heute\s*für\s*ein\s*tag|datum|welche\s*kalenderwoche(?:\s*ist)?(?:\s*heute)?|welche\s*kw)\s*\??\s*$",
    re.I,
)
_DIKTAT = re.compile(
    r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:bitte\s+)?(?:merk\s*dir|merke\s*dir|notier(?:e)?|schreib\s*(?:dir\s*)?auf|"
    r"halte\s*fest|halt\s*fest|speicher(?:e)?\s*(?:dir\s*)?|vermerke)\s*[:,]?\s*(?:dass\s+)?(?P<text>.+)$",
    re.I | re.S,
)
_JA = re.compile(r"^\s*(?:ja|jawohl|genau|mach(?:\s*das)?|übernehmen|uebernehmen|ok(?:ay)?|passt|bestätigt|bestaetigt|einverstanden)\b[\s.!]*$", re.I)
_NEIN = re.compile(r"^\s*(?:nein|nee|verwerfen|lass(?:\s*es)?|abbrechen|doch\s*nicht)\b[\s.!]*$", re.I)
_URL = re.compile(r"https?://\S+", re.I)

# 26.09.2026: Kursfragen ("Wie steht Gold?", "Was kostet Bitcoin?") ohne Claude beantworten.
# Vorher ging so eine Frage an Claude, und das Modell nannte Kurse aus seinem alten
# Trainingswissen (Stand 2024). Jetzt holt app/marktdaten.py den Kurs (Yahoo/Binance, 0 Cent).
# Reihenfolge wichtig: "euro" zuletzt, damit "Was kostet Gold in Euro?" Gold bleibt.
KURS_NAMEN: list[tuple[str, str]] = [
    ("XAUUSD", r"gold|xau(?:usd)?"),
    ("XAGUSD", r"silber|xag(?:usd)?"),
    ("XPTUSD", r"platin|xpt(?:usd)?"),
    ("BTCUSD", r"bitcoin|btc(?:usd)?"),
    ("ETHUSD", r"ethereum|eth(?:usd)?|ether"),
    ("SOLUSD", r"solana|sol(?:usd)?"),
    ("DAX", r"dax(?:\s*40)?"),
    ("SP500", r"s\s*&\s*p(?:\s*500)?|sp\s*500|s\s+und\s+p\s*500"),
    ("NASDAQ100", r"nasdaq(?:\s*100)?|ndx"),
    ("DOW", r"dow(?:\s+jones)?"),
    ("AAPL", r"apple(?:-aktie)?|aapl"),
    ("MSFT", r"microsoft(?:-aktie)?|msft"),
    ("NVDA", r"nvidia(?:-aktie)?|nvda"),
    ("TSLA", r"tesla(?:-aktie)?|tsla"),
    ("SAP", r"sap(?:-aktie)?"),
    ("CHFJPY", r"chf\s*/?\s*jpy|franken\s*/?\s*yen"),
    ("EURCHF", r"eur\s*/?\s*chf|euro\s*/?\s*franken"),
    ("GBPUSD", r"gbp\s*/?\s*usd|pfund|cable"),
    ("USDJPY", r"usd\s*/?\s*jpy|dollar\s*/?\s*yen|yen"),
    ("EURUSD", r"eur\s*/?\s*usd|euro\s*/?\s*dollar|euro"),
]
_KURS_WORT = re.compile(
    r"\b(?:preis|kurs|kostet|kosten|steht|stehen|notiert|wert|aktuell\w*|gerade|heute|jetzt|momentan|"
    r"derzeit|stand|chart|wie\s+viel|wieviel)\b|(?:preis|kurs)\b", re.I)
# Keine Kursabfrage, sondern Erklärung, Meinung oder Prognose -> geht an Claude
_KURS_NICHT = re.compile(
    r"\b(?:warum|wieso|weshalb|erkl(?:ä|ae)r\w*|was\s+(?:ist|sind)\s+(?:ein|eine)|"
    r"strategie|bot|backtest|prognose|vorhersage|wird|werden|steigen|fallen|sinken|kaufen|verkaufen|"
    r"investier\w*|lohnt|sollte|soll\s+ich|analyse|trend|rsi|merk|notier|vault|notiz|"
    r"gekostet|ausgegeben|budget|rahmen|verbrauch|claude|token|studium|monat|woche|jahr)\b", re.I)
# Währungen per Wort ("Euro", "Pfund", "Yen") nur mit klarem Kurswort - "Wie viel Euro ..."
# ist meist keine Kursfrage.
_KURS_WORT_STRENG = re.compile(r"\b(?:kurs|wechselkurs|steht|stehen|notiert|stand)\b|kurs\b", re.I)
_WAEHRUNG = {"EURUSD", "GBPUSD", "USDJPY", "EURCHF", "CHFJPY"}
KURS_MAX_ZEICHEN = 90


def kurs_symbol(text: str) -> str | None:
    """Symbol aus einer kurzen Kursfrage ("Wie steht Gold?", "Goldpreis aktuell"), sonst None."""
    t = (text or "").strip().lower()
    if not t or len(t) > KURS_MAX_ZEICHEN or _KURS_NICHT.search(t):
        return None
    for symbol, namen in KURS_NAMEN:
        m = re.search(r"(?<![a-zäöüß])(?:" + namen + r")(?:-?(?:preis|kurs|stand|chart))?(?![a-zäöüß])", t)
        if m:
            rest = t[:m.start()] + " " + t[m.end():]
            # "Goldpreis", "Bitcoinkurs" zählen selbst als Kurswort
            wort = _KURS_WORT_STRENG if symbol in _WAEHRUNG else _KURS_WORT
            if wort.search(rest) or re.search(r"(?:preis|kurs|stand)$", m.group(0)):
                return symbol
            return None
    return None


# ------------------------------------------------ Trading-Tagebuch (26.09.2026)
# "Gold Long bei 3740, Stopp 3720, Ziel 3780, Grund Ausbruch"   -> eintragen
# "Gold geschlossen bei 3760" / "Trade 3 raus bei 3760"          -> schließen
# "Stopp erreicht" / "Ziel erreicht"                             -> schließen zum Stopp/Ziel
# "Wie läuft mein Trading?" / "Tagebuch Auswertung"              -> Auswertung
# Die Arbeit macht app/tagebuch.py, hier wird nur erkannt (kein Claude, 0 Cent).
_ZAHL = r"(\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)"
_SYMBOL_TICKER = r"[a-z]{6}|dax|sp500|nasdaq100|dow|aapl|msft|nvda|tsla|sap"
_TB_RICHTUNG = r"(?P<richtung>long|short|kauf|gekauft|verkauf|verkauft|buy|sell)"
_TB_EINTRAG = re.compile(
    r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:(?:neuer\s+)?trade|tagebuch|eintrag(?:en)?)?\s*:?\s*"
    r"(?P<symbol>[a-zäöüß&/\s\d]{2,20}?)\s+" + _TB_RICHTUNG + r"\s+(?:bei|@|zu|auf)?\s*(?P<einstieg>" + _ZAHL[1:-1] + r")"
    r"(?P<rest>.*)$", re.I | re.S)
_TB_STOPP = re.compile(r"\b(?:stopp?|sl|stop[\s-]*loss)\s*(?:bei|@|auf|:)?\s*" + _ZAHL, re.I)
_TB_ZIEL = re.compile(r"\b(?:ziel|tp|take[\s-]*profit)\s*(?:bei|@|auf|:)?\s*" + _ZAHL, re.I)
_TB_RISIKO = re.compile(r"\brisiko\s*(?:von|:)?\s*" + _ZAHL + r"\s*(?:€|euro|eur)", re.I)
_TB_GRUND = re.compile(r"\b(?:grund|weil|wegen)\s*:?\s*(?P<grund>.+)$", re.I | re.S)
_TB_ZU = re.compile(
    r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:trade\s+(?P<id>\d+)\s+|(?P<symbol>[a-zäöüß&/]{2,15})(?:\s+trade)?\s+|trade\s+)?"
    r"(?:geschlossen|raus|ausgestiegen|beendet|zugemacht|glattgestellt)\s*(?:bei|@|zu|auf)?\s*(?P<preis>" + _ZAHL[1:-1] + r")"
    r"(?:\s*(?:mit|,)?\s*(?P<eur>[+-]?\d+(?:[.,]\d+)?)\s*(?:€|euro|eur))?\s*[.!]?\s*$", re.I)
_TB_ZU_ART = re.compile(
    r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:(?:bei\s+)?(?:trade\s+(?P<id>\d+)|(?P<symbol>[a-zäöüß&/]{2,15}))\s*[:,]?\s*)?"
    r"(?P<art>stopp?|sl|stop[\s-]*loss|ziel|tp|take[\s-]*profit)\s+(?:wurde\s+|ist\s+)?"
    r"(?:erreicht|getroffen|ausgel(?:ö|oe)st|gerissen|gegriffen)\s*[.!]?\s*$", re.I)
_TB_AUSWERTUNG = re.compile(
    r"\b(?:wie\s+l(?:ä|ae)uft|auswertung|bilanz|stand|zusammenfassung|statistik)\b.{0,25}"
    r"\b(?:trading|tagebuch|trades|meine[rn]?\s+trades)\b|\b(?:tagebuch|trading)[\s-]*(?:auswertung|bilanz|stand)\b", re.I)


def zahl_lesen(text: str) -> float:
    """3.740,50 / 3740.5 / 3 740 / 1.0850 -> float."""
    t = text.strip().replace(" ", "")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", t) and not re.fullmatch(r"\d\.\d{3}", t):
        t = t.replace(".", "")  # 3.740 -> 3740, aber 1.085 (Devisen) bleibt
    return float(t)


def tagebuch_symbol(wort: str) -> str | None:
    w = (wort or "").strip().lower()
    for symbol, namen in KURS_NAMEN:
        if re.fullmatch(r"(?:" + namen + r")", w):
            return symbol
    if re.fullmatch(_SYMBOL_TICKER, w):
        return w.upper()
    return None


def tagebuch_absicht(text: str) -> dict | None:
    t = (text or "").strip()
    if not t or len(t) > 400:
        return None
    m = _TB_EINTRAG.match(t)
    if m:
        symbol = tagebuch_symbol(m.group("symbol"))
        if symbol:
            rest = m.group("rest")
            stopp = _TB_STOPP.search(rest)
            if not stopp:
                return {"art": "antwort", "text": "Mir fehlt noch der Stopp, Sir. Zum Beispiel: "
                        '"Gold Long bei 3740, Stopp 3720, Ziel 3780, Grund Ausbruch".'}
            ziel, risiko, grund = _TB_ZIEL.search(rest), _TB_RISIKO.search(rest), _TB_GRUND.search(rest)
            return {"art": "tagebuch", "aktion": "eintragen", "symbol": symbol,
                    "richtung": m.group("richtung").lower(), "einstieg": zahl_lesen(m.group("einstieg")),
                    "stopp": zahl_lesen(stopp.group(1)), "ziel": zahl_lesen(ziel.group(1)) if ziel else None,
                    "risiko_eur": zahl_lesen(risiko.group(1)) if risiko else None,
                    "grund": grund.group("grund").strip().rstrip(".") if grund else ""}
    m = _TB_ZU.match(t)
    if m:
        symbol = tagebuch_symbol(m.group("symbol")) if m.group("symbol") else None
        if m.group("symbol") and not symbol:
            return None
        return {"art": "tagebuch", "aktion": "schliessen", "id": int(m.group("id")) if m.group("id") else None,
                "symbol": symbol, "ausstieg": zahl_lesen(m.group("preis")),
                "eur": float(m.group("eur").replace(",", ".")) if m.group("eur") else None}
    m = _TB_ZU_ART.match(t)
    if m:
        symbol = tagebuch_symbol(m.group("symbol")) if m.group("symbol") else None
        if m.group("symbol") and not symbol:
            return None
        art = "ziel" if re.match(r"ziel|tp|take", m.group("art"), re.I) else "stopp"
        return {"art": "tagebuch", "aktion": "schliessen", "id": int(m.group("id")) if m.group("id") else None,
                "symbol": symbol, "zu_art": art}
    if _TB_AUSWERTUNG.search(t) and len(t) <= 80:
        tage = None if re.search(r"\b(?:insgesamt|gesamt|alle|bisher)\b", t, re.I) else 7
        return {"art": "tagebuch", "aktion": "auswertung", "tage": tage}
    return None


def url_saeubern(url: str) -> str:
    """Satzzeichen am Ende weg - eine ")" nur, wenn sie keine "(" im Link schließt.
    26.09.2026: ".../Obsidian_(Software)" wurde zu ".../Obsidian_(Software" gekürzt (HTTP 404)."""
    url = url.rstrip(".,;:!?")
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1].rstrip(".,;:!?")
    return url


def ziel_seite(wort: str) -> str | None:
    w = wort.strip().lower()
    for seite, namen in SEITEN.items():
        if any(w == n or w.endswith(" " + n) or w.startswith(n + " ") for n in namen):
            return seite
    return None


# ------------------------------------------------------------ Nachtaufträge / Frage des Tages (26.09.2026)
_NA_VERB = (r"recherchier|such|plan|bau|entwickl|schreib|finde|überleg|ueberleg|vergleich|erstell|arbeite|"
            r"prüf|pruef|analysier|sammel|mach|denk|schmied|programmier|lies|lese")
_NA_ANLEGEN = re.compile(
    r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:bitte\s+)?(?:(?:heute|diese)\s+nacht|über\s+nacht|ueber\s+nacht|nachtauftrag|"
    r"f(?:ü|ue)r\s+(?:heute\s+|die\s+)?nacht)\b\s*(?P<trenner>[:,\-–]?)\s*(?P<text>.{5,})$", re.I | re.S)
_NA_LISTE = re.compile(
    r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:was\s+(?:steht|machst\s+du|macht\s+(?:jarvis|auron)|l(?:ä|ae)uft|ist\s+geplant)\s+"
    r"(?:(?:f(?:ü|ue)r\s+)?(?:heute|diese)\s+)?nacht\b.*|(?:zeig\w*\s+(?:mir\s+)?(?:die\s+)?)?nachtauftr(?:ä|ae)ge\s*\??)\s*$", re.I)
_NA_ANTWORT = re.compile(
    r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:antwort\s+(?:zu|f(?:ü|ue)r|auf)\s+(?:den\s+)?)?auftrag\s*(?:nr\.?\s*)?(?P<nr>\d+)\s*[:\-–]\s*(?P<text>.+)$",
    re.I | re.S)
_NA_AKTION = re.compile(
    r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:auftrag|vorschlag)\s*(?:nr\.?\s*)?(?P<nr>\d+)\s+"
    r"(?P<aktion>freigeben|starten|annehmen|verwerfen|l(?:ö|oe)schen|streichen)\b[\s.!]*$", re.I)
_TF_ANTWORT = re.compile(
    r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:antwort(?:\s+auf\s+(?:die\s+)?(?:tages)?frage)?|tagesfrage)\s*:\s*(?P<text>.+)$", re.I | re.S)
_TF_ZEIGEN = re.compile(
    r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:was\s+ist\s+(?:die\s+|deine\s+)?)?(?:frage\s+des\s+tages|tagesfrage)\s*\??\s*$", re.I)


def nachtauftrag_absicht(text: str) -> dict | None:
    """Nachtaufträge und Frage des Tages per Chat/Sprache, ohne Claude erkannt."""
    t = (text or "").strip()
    m = _NA_ANTWORT.match(t)
    if m:
        return {"art": "nachtauftrag", "aktion": "antwort", "nr": int(m.group("nr")), "text": m.group("text").strip()}
    m = _NA_AKTION.match(t)
    if m:
        aktion = "freigeben" if m.group("aktion").lower() in ("freigeben", "starten", "annehmen") else "verwerfen"
        return {"art": "nachtauftrag", "aktion": aktion, "nr": int(m.group("nr"))}
    if _NA_LISTE.match(t):
        return {"art": "nachtauftrag", "aktion": "liste"}
    m = _NA_ANLEGEN.match(t)
    if m:
        inhalt = m.group("text").strip()
        # ohne Doppelpunkt nur, wenn eine Arbeit gemeint ist ("heute Nacht recherchierst du ...")
        if m.group("trenner") or re.search(r"\b(?:" + _NA_VERB + r")\w*", inhalt, re.I):
            inhalt = re.sub(r"^(?:bitte\s+)?(?:(?:kannst|könntest|koenntest|sollst|wirst)\s+du\s+)?", "", inhalt, flags=re.I)
            return {"art": "nachtauftrag", "aktion": "anlegen", "text": inhalt}
    if _TF_ZEIGEN.match(t):
        return {"art": "tagesfrage", "aktion": "zeigen"}
    m = _TF_ANTWORT.match(t)
    if m:
        return {"art": "tagesfrage", "aktion": "antwort", "text": m.group("text").strip()}
    return None


def absicht(text: str, offener_vorschlag: str | None = None) -> dict | None:
    """Erkennt Befehl oder Diktat. None = normale Frage (geht an Claude).

    Rückgabe z.B.:
        {"art": "antwort", "text": "Es ist 18:42 Uhr, Sir."}      (Uhrzeit, Datum, Rechnen)
        {"art": "hud", "aktion": "seite", "seite": "markt", "text": ...}
        {"art": "hud", "aktion": "stumm", "text": ""}
        {"art": "diktat", "text": "..."}                            (-> Vorschlag anlegen)
        {"art": "bestaetigung", "ja": True/False, "vorschlag": id}  (nur mit offenem Vorschlag)
        {"art": "webseite", "url": ...}                              ("speicher die Seite https://...")
        {"art": "tagesnotiz", "wunsch": "neueste"|"tag"|"ungueltig"}  ("neueste Tagesnotiz", app/tagesnotizen.py)
    """
    t = (text or "").strip()
    if not t or len(t) > 2000:
        return None
    if offener_vorschlag:
        if _JA.match(t):
            return {"art": "bestaetigung", "ja": True, "vorschlag": offener_vorschlag}
        if _NEIN.match(t):
            return {"art": "bestaetigung", "ja": False, "vorschlag": offener_vorschlag}
    if _STUMM.match(t):
        return {"art": "hud", "aktion": "stumm", "text": ""}
    if _UHRZEIT.match(t):
        return {"art": "antwort", "text": f"Es ist {uhrzeit_text()}, Sir."}
    if _DATUM.match(t):
        return {"art": "antwort", "text": f"Heute ist {datum_text()}, Sir."}
    # 13.10.2026 (P23): "Kostenstand" - beide Deckel (normal und Code) aus dem Protokoll, ohne KI
    from . import kosten

    ks = kosten.absicht(t)
    if ks:
        return ks
    # 16.10.2026 (P24b): "GPU Status", "GPU aufräumen", "Code-Auftrag 7 auf die GPU" (mit Nachfrage), ohne KI
    from . import gpu_befehl

    gb = gpu_befehl.absicht(t)
    if gb:
        return gb
    # 13.10.2026 (P21): "neueste Tagesnotiz" / "Tagesnotiz von gestern" nach Dateiname, ohne KI -
    # VOR allem anderen, sonst landet die Frage in der Ähnlichkeitssuche (app/tagesnotizen.py)
    from . import tagesnotizen

    tn = tagesnotizen.absicht(t)
    if tn:
        return tn
    # 27.09.2026: neue Befehle (PC, Mind Maps, Projekte, Schreiben, Recherche, Termine,
    # Umwandeln) VOR Seitenwechsel und Diktat - siehe app/befehle.py
    from . import befehle

    neu = befehle.absicht(t)
    if neu:
        return neu
    # 05.10.2026: Terminfragen ("Was steht morgen an?") direkt aus dem Kalender, ohne KI (app/termine.py)
    from . import termine

    tf = termine.absicht(t)
    if tf:
        return tf
    nav = _NAV.match(t)
    if nav:
        seite = ziel_seite(nav.group("ziel"))
        if seite:
            return {"art": "hud", "aktion": "seite", "seite": seite, "text": "Sofort, Sir."}
    diktat = _DIKTAT.match(t)
    if diktat:
        inhalt = diktat.group("text").strip()
        url = _URL.search(inhalt)
        if url and re.search(r"\b(seite|webseite|artikel|link)\b", inhalt, re.I):
            return {"art": "webseite", "url": url_saeubern(url.group(0))}
        if len(inhalt) >= 3:
            return {"art": "diktat", "text": inhalt}
    na = nachtauftrag_absicht(t)
    if na:
        return na
    tb = tagebuch_absicht(t)
    if tb:
        return tb
    symbol = kurs_symbol(t)
    if symbol:
        return {"art": "kurs", "symbol": symbol, "euro": bool(re.search(r"\b(?:in|auf)\s+euro\b|€", t, re.I))}
    # Reine Rechnung ("Was ist 17 mal 23?", "15 % von 240")
    if re.search(r"\d", t) and len(t) <= 120:
        try:
            wert = rechnen(t)
        except RechenFehler:
            return None
        return {"art": "antwort", "text": f"Das ergibt {zahl_deutsch(round(wert, 10))}, Sir.", "rechnung": ausdruck_normalisieren(t)}
    return None

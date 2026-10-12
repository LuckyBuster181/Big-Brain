"""
Alexa-Skill "frag Auron" (P19, 12.10.2026, Claude Code, Entscheidung Sir 12.10.).

"Computer, frag Agent Auron ..." am Echo Dot (Aufrufname "agent auron": Amazon verlangt
zwei Wörter, Wahl Sir 12.10.) -> Amazon -> POST /api/alexa (Prüfung in
app/alexa_pruefung.py) -> verarbeiten() hier -> bestehende Auron-Funktionen.

Fähigkeiten (Intents, Modell in backend/alexa/interaktionsmodell_de.json):
  VaultFrageIntent    chat_service.ask()             0 € lokal, Claude-Rückfall kostet (20-$-Rahmen)
  BriefingIntent      briefing.hole()                0 € (Zwischenspeicher, lokal)
  MerkenIntent        vorschlaege.anlegen/uebernehmen 0 €, erst nach "Ja" am Echo
  StatusIntent        nachtarbeit, kosten            0 €
  TermineIntent       termine.antwort_zeitraum()     0 €
  NachtauftragIntent  nachtauftraege.anlegen()       0 €, erst nach "Ja"
  AktionIntent        nur ALEXA_AKTIONEN (Whitelist) 0 €, erst nach "Ja"
  LetzteAntwortIntent liest data/alexa_letzte_antwort.json
Bewusst NICHT per Sprache: Trades, Käufe, Mails, Löschen (Fehlauslösung zu leicht).

Zeitbudget: Alexa wartet nur wenige Sekunden. Dauert etwas länger als ZEITBUDGET_S, sagt
Auron "dauert länger" und legt das Ergebnis ab; "frag Auron nach der letzten Antwort" liest es vor.
Sprechlänge: höchstens SPRACH_MAX_ZEICHEN (ca. 8-10 s), gekürzt nur an Satzgrenzen.
Die volle Antwort steht als Karte in der Alexa-App.
"""

from __future__ import annotations

import concurrent.futures
import datetime
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

# Aktionen, die Sir per Stimme auslösen darf (Entscheidung Sir 12.10.2026, P19).
# NUR fest hinterlegte, vorab geprüfte Abläufe. Kein freier Code, kein "schreib und führ aus",
# nichts löschen, keine Trades, Käufe oder Mails (Fehlauslösung per Stimme ist zu leicht).
# Neue Aktion = Eintrag hier + Funktion in _AUSFUEHRUNG + Wert im Slot-Typ AURON_AKTION
# (backend/alexa/interaktionsmodell_de.json) + Test in tests/test_alexa.py. Sonst nichts.
# Der Schlüssel muss genau der Slot-ID im Interaktionsmodell entsprechen.
ALEXA_AKTIONEN: dict[str, dict[str, Any]] = {
    "nachtarbeit_starten": {
        "name": "Nachtarbeit",
        "aktiv": True,
        "antwort": "Die Nachtarbeit startet, Sir.",
    },
    "vault_einlesen": {
        "name": "Vault neu einlesen",
        "aktiv": True,
        "antwort": "Der Vault wird neu eingelesen, Sir.",
    },
    # INHALT_PRUEFEN_HINTERGRUND.bat liegt auf dem Haupt-PC, Auron läuft auf dem Mini-PC. Erst wenn
    # der PC-Agent dafür eine feste Aktion hat (Stufe 2, pc_agent_windows ins Repo), hier aktivieren.
    "pruefen_hintergrund": {
        "name": "Prüflauf",
        "aktiv": False,
        "antwort": "Den Prüflauf kann ich per Sprache noch nicht starten, Sir.",
    },
}

ZEITBUDGET_S = float(os.getenv("ALEXA_ZEITBUDGET_S", "6"))
SPRACH_MAX_ZEICHEN = int(os.getenv("ALEXA_SPRACH_MAX_ZEICHEN", "220"))
LETZTE_GUELTIG_MIN = 30
KARTE_MAX_ZEICHEN = 7000
MEHR_HINWEIS = "Mehr steht in der Alexa-App."
_JARVIS = Path(__file__).resolve().parents[2]

_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="alexa")
_lauf = threading.local()   # merkt je Anfrage, ob das Zeitbudget überschritten wurde (Protokoll)
_datei_sperre = threading.Lock()


def _log_pfad() -> Path:
    return Path(os.getenv("ALEXA_LOG_PATH") or _JARVIS / "data" / "alexa_log.jsonl")


def _letzte_pfad() -> Path:
    return Path(os.getenv("ALEXA_LETZTE_PATH") or _JARVIS / "data" / "alexa_letzte_antwort.json")


# ------------------------------------------------------------------ Text für die Sprache

_SATZENDE = re.compile(r"(?<=[.!?])\s+")


def fuer_sprache(text: str, max_zeichen: int | None = None) -> tuple[str, bool]:
    """Markdown, Quellennummern und Listen entfernen, an Satzgrenzen kürzen.
    Rückgabe: (Sprechtext, gekürzt?). Nie mitten im Satz abschneiden: Ist schon der erste
    Satz zu lang, bleibt er ganz."""
    grenze = max_zeichen or SPRACH_MAX_ZEICHEN
    t = str(text or "")
    t = re.sub(r"\[([^\]]+)\]\((?:https?://)?[^)]*\)", r"\1", t)      # [Text](Link) -> Text
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"\[\d+(?:\s*[,–-]\s*\d+)*\]", "", t)                  # [1], [1, 2]
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)               # Überschriften
    t = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", t, flags=re.M)        # Listenzeichen
    t = re.sub(r"[*_`>|]+", "", t)
    zeilen = [z.strip() for z in t.splitlines() if z.strip()]
    t = " ".join(z if re.search(r"[.!?:;,]$", z) else z + "." for z in zeilen)
    t = re.sub(r"\s+([.,!?;:])", r"\1", re.sub(r"\s+", " ", t)).strip()
    if len(t) <= grenze:
        return t, False
    saetze = _SATZENDE.split(t)
    platz = grenze - len(MEHR_HINWEIS) - 1
    teil = saetze[0]
    for s in saetze[1:]:
        if len(teil) + 1 + len(s) > platz:
            break
        teil += " " + s
    return teil, True


def _zahl(x: float, stellen: int = 2) -> str:
    return f"{x:.{stellen}f}".replace(".", ",")


# ------------------------------------------------------------------ Antwortformat

def antwort(sprache: str, karte: str | None = None, ende: bool = True, nachfrage: str | None = None,
            direktiven: list[dict] | None = None) -> dict:
    """Antwort im Alexa-Format (version 1.0)."""
    r: dict[str, Any] = {"shouldEndSession": ende}
    if sprache:
        r["outputSpeech"] = {"type": "PlainText", "text": sprache}
    if karte:
        r["card"] = {"type": "Simple", "title": "Auron", "content": karte[:KARTE_MAX_ZEICHEN]}
    if nachfrage and not ende:
        r["reprompt"] = {"outputSpeech": {"type": "PlainText", "text": nachfrage}}
    if direktiven:
        r["directives"] = direktiven
    return {"version": "1.0", "response": r}


def _sprechen(text: str, karte: str | None = None, ende: bool = True) -> dict:
    """Text kürzen, bei Kürzung Hinweis anhängen; volle Fassung in die Karte."""
    kurz, gekuerzt = fuer_sprache(text)
    if gekuerzt:
        kurz = f"{kurz} {MEHR_HINWEIS}"
    return antwort(kurz, karte or (text if gekuerzt else None), ende=ende)


# ------------------------------------------------------------------ Protokoll, letzte Antwort

def _protokoll(intent: str, ergebnis: str, start: float, claude: bool = False, **mehr: Any) -> None:
    """Eine Zeile je Anfrage - ohne Inhalte (keine Fragen, keine Notizen).
    mehr (12.10.2026, Diagnose Echo): Anfrage-Art, Prüfdauer, Gerät mit/ohne Bildschirm,
    Platzhalter leer, Zeitbudget überschritten."""
    try:
        zeile = {"zeit": datetime.datetime.now().isoformat(timespec="seconds"), "intent": intent,
                 "ergebnis": ergebnis, "dauer_ms": int((time.time() - start) * 1000), "claude": claude, **mehr}
        pfad = _log_pfad()
        pfad.parent.mkdir(parents=True, exist_ok=True)
        with _datei_sperre, pfad.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(zeile, ensure_ascii=False) + "\n")
    except OSError:
        pass


def ablehnung_protokollieren(grund: str, pruef_ms: int) -> None:
    """Abgelehnte Anfrage, die wie Alexa aussah (Signatur-Kopfzeile vorhanden). Hilft, wenn ein
    Gerät nichts bekommt: Kam die Anfrage an und scheiterte an der Prüfung?"""
    _protokoll("-", "abgelehnt", time.time(), grund=str(grund)[:120], pruef_ms=pruef_ms)


def zeilen(anzahl: int = 25) -> list[dict]:
    """Die letzten Protokollzeilen (für den Fehlerbericht)."""
    try:
        roh = _log_pfad().read_text(encoding="utf-8").splitlines()[-anzahl:]
    except OSError:
        return []
    ergebnis = []
    for z in roh:
        try:
            ergebnis.append(json.loads(z))
        except ValueError:
            continue
    return ergebnis


def _letzte_speichern(intent: str, ergebnis: dict) -> None:
    try:
        pfad = _letzte_pfad()
        pfad.parent.mkdir(parents=True, exist_ok=True)
        daten = {"zeit": time.time(), "intent": intent, **ergebnis}
        with _datei_sperre:
            pfad.write_text(json.dumps(daten, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _letzte_lesen() -> dict | None:
    try:
        daten = json.loads(_letzte_pfad().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() - float(daten.get("zeit") or 0) > LETZTE_GUELTIG_MIN * 60:
        return None
    return daten


def _fehler_melden(intent: str, exc: BaseException) -> None:
    try:
        from . import fehlerbericht

        fehlerbericht.merken("fehler", f"Alexa {intent}: {type(exc).__name__}: {exc}", quelle="alexa")
    except Exception:  # noqa: BLE001 - Fehlerbericht darf nie stören
        pass


FEHLER_SATZ = "Da ist etwas schiefgegangen, Sir. Der Fehler steht im Fehlerbericht."
DAUERT_SATZ = ("Das dauert etwas länger, Sir. Fragen Sie gleich: Computer, frag Agent Auron nach der letzten Antwort.")


def _mit_zeitbudget(intent: str, arbeit: Callable[[], dict]) -> dict:
    """Führt arbeit() aus (Rückgabe {"sprache", "karte", "claude"}). Ist sie nach ZEITBUDGET_S
    nicht fertig, läuft sie weiter und landet in der "letzten Antwort"."""
    def _fertig(f: concurrent.futures.Future) -> None:
        try:
            _letzte_speichern(intent, f.result())
        except Exception as exc:  # noqa: BLE001
            _fehler_melden(intent, exc)
            _letzte_speichern(intent, {"sprache": FEHLER_SATZ, "karte": None})

    zukunft = _pool.submit(arbeit)
    zukunft.add_done_callback(_fertig)
    try:
        return zukunft.result(timeout=ZEITBUDGET_S)
    except concurrent.futures.TimeoutError:
        _lauf.dauert = True
        return {"sprache": DAUERT_SATZ, "karte": None, "dauert": True}


# ------------------------------------------------------------------ Slots

def _intent(anfrage: dict) -> dict:
    return (anfrage.get("request") or {}).get("intent") or {}


def _slot(anfrage: dict, name: str) -> str:
    slot = (_intent(anfrage).get("slots") or {}).get(name) or {}
    return str(slot.get("value") or "").strip()


def _slot_id(anfrage: dict, name: str) -> str:
    """Aufgelöste ID eines eigenen Slot-Typs (nie der gesprochene Rohtext)."""
    slot = (_intent(anfrage).get("slots") or {}).get(name) or {}
    for autoritaet in ((slot.get("resolutions") or {}).get("resolutionsPerAuthority") or []):
        if (autoritaet.get("status") or {}).get("code") != "ER_SUCCESS_MATCH":
            continue
        for wert in autoritaet.get("values") or []:
            wid = str(((wert.get("value") or {}).get("id")) or "")
            if wid:
                return wid
    return ""


def _bestaetigung(anfrage: dict) -> str:
    return str(_intent(anfrage).get("confirmationStatus") or "NONE")


def _weitergeben() -> dict:
    """Alexa soll den Dialog (Nachfrage, Bestätigung) selbst führen."""
    return antwort("", ende=False, direktiven=[{"type": "Dialog.Delegate"}])


# ------------------------------------------------------------------ Fähigkeiten

def _quellenname(quelle: Any) -> str:
    pfad = str(getattr(quelle, "file_path", "") or "")
    return Path(pfad.replace("\\", "/")).stem if pfad else ""


def _vault_frage(frage: str) -> dict:
    from . import chat_service

    try:
        r = chat_service.ask(frage, mode="klassisch", laenge="sprache", log_modus="alexa")
    except RuntimeError as exc:  # z. B. Rahmen erschöpft, lokale KI aus und kein Rückfall
        return {"sprache": f"{str(exc).rstrip('.')}.", "karte": None}
    claude = (getattr(r, "ki", None) or {}).get("quelle") == "claude"
    if not r.used_vault:
        return {"sprache": "Dazu steht nichts im Vault, Sir.", "karte": None, "claude": claude}
    namen = [n for n in dict.fromkeys(_quellenname(q) for q in r.sources) if n]
    kurz, gekuerzt = fuer_sprache(r.answer, SPRACH_MAX_ZEICHEN - (len(namen[0]) + 10 if namen else 0))
    sprache = kurz + (f" Quelle: {namen[0]}." if namen else "") + (f" {MEHR_HINWEIS}" if gekuerzt else "")
    karte = r.answer.strip()
    if namen:
        karte += "\n\nQuellen: " + ", ".join(namen)
    if claude:
        karte += "\n\nAntwort von Claude (Rückfall), Kosten im Kostenrahmen erfasst."
    return {"sprache": sprache, "karte": karte, "claude": claude}


def _briefing() -> dict:
    from . import briefing

    daten = briefing.hole()
    text = str(daten.get("text") or "").strip()
    if not text:
        return {"sprache": "Es gibt gerade kein Briefing, Sir.", "karte": None}
    punkte = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", z).strip() for z in text.splitlines()
              if re.match(r"^\s*(?:[-*•]|\d+[.)])\s+\S", z)]
    kern = " ".join(p if p.endswith((".", "!", "?")) else p + "." for p in punkte[:3]) if punkte else text
    kurz, gekuerzt = fuer_sprache(kern)
    sprache = kurz if "sir" in kurz.lower() else f"Sir, {kurz}"
    return {"sprache": sprache + (f" {MEHR_HINWEIS}" if gekuerzt or len(punkte) > 3 else ""), "karte": text}


def _merken(text: str) -> dict:
    from . import vorschlaege

    v = vorschlaege.anlegen(text, quelle="alexa", grund="Alexa: Merk dir")
    vorschlaege.uebernehmen(v["id"])
    return {"sprache": "Gemerkt, Sir.", "karte": f"Gemerkt in {v['ziel']}:\n{text}"}


def _status() -> dict:
    from . import kosten, nachtarbeit

    teile = ["Die Nachtarbeit läuft gerade." if nachtarbeit.is_running() else "Die Nachtarbeit ruht."]
    nacht = nachtarbeit.letzte_nacht()
    if nacht:
        try:
            tag = datetime.date.fromisoformat(str(nacht.get("datum")))
            datum = f"{tag:%d.%m.}"
        except ValueError:
            datum = str(nacht.get("datum") or "")
        status = {"durchgefuehrt": "durchgeführt", "uebersprungen": "übersprungen", "fehler": "mit Fehler"}.get(
            str(nacht.get("status")), str(nacht.get("status") or "unbekannt"))
        cent = float(nacht.get("kosten_usd") or 0) * 100
        teile.append(f"Letzte Nacht am {datum}: {status}, {_zahl(cent, 1)} Cent.")
    u = kosten.uebersicht()
    teile.append(f"Vom Rahmen sind {_zahl(u['ausgegeben_usd'])} von {_zahl(u['rahmen_usd'], 0)} Dollar verbraucht, "
                 f"{_zahl(u['anteil_prozent'], 0)} Prozent, Sir.")
    return {"sprache": " ".join(teile), "karte": None}


def _zeitraum(wert: str, heute: datetime.date) -> tuple[datetime.date, datetime.date, str]:
    """AMAZON.DATE: 2026-10-13, 2026-W42, 2026-W42-WE, 2026-10. Sonst heute."""
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", wert):
            tag = datetime.date.fromisoformat(wert)
            name = {0: "heute", 1: "morgen", 2: "übermorgen"}.get((tag - heute).days, f"am {tag:%d.%m.}")
            return tag, tag, name
        m = re.fullmatch(r"(\d{4})-W(\d{2})(-WE)?", wert)
        if m:
            montag = datetime.date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
            if m.group(3):
                return montag + datetime.timedelta(days=5), montag + datetime.timedelta(days=6), "am Wochenende"
            return montag, montag + datetime.timedelta(days=6), "in dieser Woche"
        m = re.fullmatch(r"(\d{4})-(\d{2})", wert)
        if m:
            erster = datetime.date(int(m.group(1)), int(m.group(2)), 1)
            naechster = (erster + datetime.timedelta(days=32)).replace(day=1)
            return erster, naechster - datetime.timedelta(days=1), f"im {erster:%m.%Y}"
    except ValueError:
        pass
    return heute, heute, "heute"


def _termine(wert: str) -> dict:
    from . import alltag, termine

    heute = alltag.jetzt().date()
    von, bis, name = _zeitraum(wert, heute)
    text = termine.antwort_zeitraum(von, bis, name)
    kopf, _, rest = text.partition("\n\n")
    eintraege = [z[2:].strip() for z in rest.splitlines() if z.startswith("- ")]
    if not eintraege:
        return {"sprache": fuer_sprache(kopf)[0], "karte": None}
    sprache = kopf.rstrip(":") + ": " + "; ".join(eintraege[:3])
    sprache += f", und {len(eintraege) - 3} weitere." if len(eintraege) > 3 else "."
    kurz, gekuerzt = fuer_sprache(sprache)
    return {"sprache": kurz + (f" {MEHR_HINWEIS}" if gekuerzt else ""), "karte": text}


def _nachtauftrag(text: str) -> dict:
    from . import nachtauftraege

    try:
        a = nachtauftraege.anlegen(text, quelle="alexa", pruefen=False)
    except nachtauftraege.NachtauftragFehler as exc:
        return {"sprache": str(exc), "karte": None}
    return {"sprache": f"Auftrag {a['id']} für die Nacht notiert, Sir.", "karte": f"Nachtauftrag {a['id']}: {text}"}


def _aktion_nachtarbeit() -> bool:
    from . import nachtarbeit

    gestartet, _ = nachtarbeit.start()
    return gestartet


def _aktion_vault_einlesen() -> bool:
    from . import reindex_service

    gestartet, _ = reindex_service.start(full=False)
    return gestartet


# Feste Zuordnung Whitelist-Schlüssel -> Funktion. Kein getattr/eval mit Text aus der Anfrage.
_AUSFUEHRUNG: dict[str, Callable[[], bool]] = {
    "nachtarbeit_starten": _aktion_nachtarbeit,
    "vault_einlesen": _aktion_vault_einlesen,
}


def aktion_ausfuehren(aid: str) -> str:
    eintrag = ALEXA_AKTIONEN.get(aid)
    if not eintrag:
        return "Diese Aktion kenne ich nicht, Sir."
    if not eintrag["aktiv"] or aid not in _AUSFUEHRUNG:
        return eintrag["antwort"]
    try:
        gestartet = _AUSFUEHRUNG[aid]()
    except RuntimeError as exc:
        return f"{eintrag['name']} geht gerade nicht, Sir: {str(exc).rstrip('.')}."
    return eintrag["antwort"] if gestartet else f"{eintrag['name']} läuft bereits, Sir."


HILFE = ("Sie können zum Beispiel sagen: frag Agent Auron nach dem Gartenhaus, frag Agent Auron was morgen ansteht, "
         "oder sag Agent Auron merk dir einen Gedanken.")


# ------------------------------------------------------------------ Einstieg

def _diagnose(anfrage: dict, typ: str, pruef_ms: int) -> dict:
    """Protokoll-Zusatz ohne Inhalte: Anfrage-Art, Prüfdauer, Gerät mit Bildschirm (App, Echo Show)
    oder ohne (Echo Dot), welche Platzhalter leer ankamen, Zeitbudget überschritten."""
    ctx = anfrage.get("context") or {}
    slots = _intent(anfrage).get("slots") or {}
    return {"typ": typ, "pruef_ms": pruef_ms,
            "bildschirm": bool(ctx.get("Viewport") or ctx.get("Viewports")),
            "slots_leer": sorted(k for k, v in slots.items() if not str((v or {}).get("value") or "").strip()),
            "dialog": (anfrage.get("request") or {}).get("dialogState") or "",
            "dauert": bool(getattr(_lauf, "dauert", False))}


def verarbeiten(anfrage: dict, pruef_ms: int = 0) -> dict:
    """Geprüfte Alexa-Anfrage -> Alexa-Antwort. Wirft nie (Fehler -> gesprochene Meldung)."""
    start = time.time()
    _lauf.dauert = False
    req = anfrage.get("request") or {}
    typ = str(req.get("type") or "")
    name = str(_intent(anfrage).get("name") or typ)
    claude = False
    try:
        if typ == "LaunchRequest":
            ergebnis = antwort("Auron hört, Sir.", ende=False, nachfrage="Was kann ich tun, Sir?")
        elif typ == "SessionEndedRequest":
            ergebnis = {"version": "1.0", "response": {}}
        elif typ != "IntentRequest":
            ergebnis = antwort("Das kann ich per Sprache nicht, Sir.")
        else:
            ergebnis, claude = _intent_verarbeiten(anfrage, name)
        _protokoll(name, "ok", start, claude, **_diagnose(anfrage, typ, pruef_ms))
        return ergebnis
    except Exception as exc:  # noqa: BLE001 - Alexa braucht immer eine Antwort
        _fehler_melden(name, exc)
        _protokoll(name, "fehler", start, claude, **_diagnose(anfrage, typ, pruef_ms))
        return antwort(FEHLER_SATZ)


def _intent_verarbeiten(anfrage: dict, name: str) -> tuple[dict, bool]:
    if (anfrage.get("request") or {}).get("dialogState") in ("STARTED", "IN_PROGRESS"):
        return _weitergeben(), False

    if name == "VaultFrageIntent":
        frage = _slot(anfrage, "frage")
        if not frage:
            return antwort("Was möchten Sie wissen, Sir?", ende=False, nachfrage="Was möchten Sie wissen, Sir?"), False
        e = _mit_zeitbudget(name, lambda: _vault_frage(frage))
        return antwort(e["sprache"], e.get("karte")), bool(e.get("claude"))

    if name == "BriefingIntent":
        e = _mit_zeitbudget(name, _briefing)
        return antwort(e["sprache"], e.get("karte")), False

    if name == "StatusIntent":
        e = _status()
        return _sprechen(e["sprache"]), False

    if name == "TermineIntent":
        e = _mit_zeitbudget(name, lambda: _termine(_slot(anfrage, "tag")))
        return antwort(e["sprache"], e.get("karte")), False

    if name in ("MerkenIntent", "NachtauftragIntent", "AktionIntent"):
        return _mit_bestaetigung(anfrage, name), False

    if name == "LetzteAntwortIntent":
        d = _letzte_lesen()
        if not d:
            return antwort("Es liegt keine neue Antwort vor, Sir."), False
        return antwort(str(d.get("sprache") or ""), d.get("karte")), False

    if name == "AMAZON.HelpIntent":
        return antwort(HILFE, ende=False, nachfrage="Was kann ich tun, Sir?"), False
    if name in ("AMAZON.StopIntent", "AMAZON.CancelIntent", "AMAZON.NavigateHomeIntent"):
        return antwort("In Ordnung, Sir."), False
    return antwort("Das kann ich per Sprache nicht, Sir."), False


def _mit_bestaetigung(anfrage: dict, name: str) -> dict:
    """Merken, Nachtauftrag, Aktion: nur nach "Ja" am Echo (Alexa fragt selbst nach)."""
    status = _bestaetigung(anfrage)
    if status == "DENIED":
        return antwort("In Ordnung, Sir. Nichts geändert.")
    if status != "CONFIRMED":
        return _weitergeben()
    if name == "MerkenIntent":
        text = _slot(anfrage, "notiz")
        if not text:
            return _weitergeben()
        e = _merken(text)
        return antwort(e["sprache"], e.get("karte"))
    if name == "NachtauftragIntent":
        text = _slot(anfrage, "auftrag")
        if not text:
            return _weitergeben()
        e = _nachtauftrag(text)
        return antwort(e["sprache"], e.get("karte"))
    return antwort(aktion_ausfuehren(_slot_id(anfrage, "aktion")))

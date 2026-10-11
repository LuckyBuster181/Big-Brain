"""
Haupt-PC steuern (27.09.2026, Claude Cowork).

Jarvis läuft auf dem Mini-PC; auf dem Haupt-PC (Windows) läuft der PC-Agent
(pc_agent_windows/jarvis_pc_agent.py, eingerichtet mit
"3 Einrichten\\PC_STEUERUNG_EINRICHTEN.bat"). Dieses Modul spricht mit ihm.
Der Token bleibt im Backend.

.env (schreibt die Einrichtung):
    HAUPTPC_URL     z.B. http://192.168.68.120:8766
    HAUPTPC_TOKEN

Chat (0 Cent, ohne Claude) - app/alltag.py ruft absicht() auf:
    "Öffne Chrome" / "Starte Obsidian am PC" / "Öffne den Downloads-Ordner"
    "Öffne youtube.com am PC"
    "PC lauter" / "Mach den PC leiser" / "PC stumm"
    "PC Pause" / "Nächster Titel am PC"
    "Sperr den PC" / "Bildschirm aus"
    "Fahr den PC herunter" / "Starte den PC neu"  -> Rückfrage, "ja" innerhalb 2 Min.
    "Herunterfahren abbrechen"
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

import httpx

from . import geraeteschutz

GEFAEHRLICH = {"herunterfahren", "neustart"}
BESTAETIGUNG_S = 120

# Schlüssel wie in pc_agent_windows/programme.json -> Wörter, an denen Jarvis sie erkennt
PROGRAMM_NAMEN: dict[str, tuple[str, ...]] = {
    "chrome": ("chrome", "google chrome", "browser", "den browser", "crome", "chrom", "krom", "krome"),
    "edge": ("edge", "microsoft edge"),
    "explorer": ("explorer", "datei explorer", "dateiexplorer", "datei-explorer"),
    "obsidian": ("obsidian", "den vault in obsidian"),
    "spotify": ("spotify",),
    "discord": ("discord",),
    "steam": ("steam",),
    "metatrader": ("metatrader", "meta trader", "mt5", "metatrader 5"),
    "rechner": ("rechner", "taschenrechner"),
    "editor": ("editor", "notepad", "texteditor"),
    "taskmanager": ("taskmanager", "task-manager", "task manager"),
    "einstellungen": ("windows einstellungen", "windows-einstellungen", "systemeinstellungen"),
    "word": ("word", "microsoft word"),
    "excel": ("excel", "microsoft excel"),
    "vscode": ("vs code", "vscode", "visual studio code"),
    "claude": ("claude", "claude app", "die claude app"),
}
ORDNER_NAMEN: dict[str, tuple[str, ...]] = {
    "downloads": ("downloads", "download"),
    "dokumente": ("dokumente", "documents"),
    "desktop": ("desktop",),
    "bilder": ("bilder",),
    "ki": ("ki", "ki ordner"),
    "jarvis": ("jarvis", "jarvis ordner"),
    "ablage": ("ablage", "datei ablage", "datei-ablage"),
    "vault": ("vault", "gehirn"),
}

# 27.09.2026 abends: "Öffne YouTube" tat nichts (YouTube ist kein Programm) - bekannte Webseiten
WEBSEITEN: dict[str, tuple[str, tuple[str, ...]]] = {
    "youtube": ("https://www.youtube.com", ("youtube", "you tube", "yt")),
    "google": ("https://www.google.de", ("google",)),
    "gmail": ("https://mail.google.com", ("gmail", "meine mails", "mails", "e-mails", "emails", "posteingang")),
    "kalender": ("https://calendar.google.com", ("google kalender", "google calendar")),
    "whatsapp": ("https://web.whatsapp.com", ("whatsapp", "whats app", "whatsapp web")),
    "netflix": ("https://www.netflix.com", ("netflix",)),
    "amazon": ("https://www.amazon.de", ("amazon",)),
    "tradingview": ("https://www.tradingview.com/chart/", ("tradingview", "trading view")),
    "chatgpt": ("https://chatgpt.com", ("chatgpt", "chat gpt")),
    "twitch": ("https://www.twitch.tv", ("twitch",)),
    "instagram": ("https://www.instagram.com", ("instagram", "insta")),
    "maps": ("https://www.google.de/maps", ("google maps", "maps", "karte von google")),
    "wikipedia": ("https://de.wikipedia.org", ("wikipedia",)),
}
_YT_SUCHE = re.compile(
    r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:bitte\s+)?(?:such\w*|spiel\w*|zeig\w*(?:\s+mir)?|öffne|oeffne|mach)\s+(?:mir\s+)?(?:auf|in|bei)\s+"
    r"(?:youtube|you\s*tube)\s+(?:nach\s+|das\s+video\s+|den\s+song\s+)?(?P<q>.+?)(?:\s+(?:an|ab|auf))?\s*[.!?]?\s*$|"
    r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:bitte\s+)?(?:such\w*|spiel\w*)\s+(?P<q2>.+?)\s+(?:auf|in|bei)\s+(?:youtube|you\s*tube)"
    r"(?:\s+(?:an|ab))?\s*[.!?]?\s*$", re.I)

_PC = r"(?:(?:den|meinen|dem|am|auf\s+dem|beim)\s+)?(?:pc|computer|rechner|haupt-?pc)"
_VOR = r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:bitte\s+)?"
_OEFFNEN = re.compile(_VOR + r"(?:öffne|oeffne|starte|start|mach)\s+(?:mir\s+)?(?:(?:den|die|das)\s+)?(?P<ziel>.{2,60}?)"
                      r"(?:\s+(?:am|auf\s+dem|auf\s+meinem)\s+(?:pc|computer|rechner|haupt-?pc))?(?:\s+auf)?\s*(?:bitte)?[.!]?\s*$",
                      re.I)
_LAUT = re.compile(_VOR + r"(?:(?:mach|stell)\s+)?(?:" + _PC + r"|ton|lautstärke|lautstaerke)\s*(?:am\s+pc\s+)?"
                   r"(?P<wie>lauter|leiser|stumm|laut|leise|hoch|runter|aus|an)\b(?:\s+(?:am|auf dem)\s+pc)?\s*[.!]?\s*$", re.I)
_LAUT2 = re.compile(_VOR + r"(?:mach|stell)\s+(?:" + _PC + r")\s+(?P<wie>lauter|leiser|stumm)\s*[.!]?\s*$", re.I)
_MEDIEN = re.compile(_VOR + r"(?:" + _PC + r")\s*[:,]?\s*(?P<was>pause|play|weiter|abspielen|nächster(?:\s+titel)?|"
                     r"naechster(?:\s+titel)?|vorheriger(?:\s+titel)?)\s*[.!]?\s*$|"
                     + _VOR + r"(?P<was2>nächster|naechster|vorheriger)\s+titel\s+am\s+pc\s*[.!]?\s*$", re.I)
_SPERREN = re.compile(_VOR + r"(?:sperr(?:e)?\s+(?:" + _PC + r")|(?:" + _PC + r")\s+sperren)\s*[.!]?\s*$", re.I)
_BILDSCHIRM = re.compile(_VOR + r"(?:bildschirm|monitor)\s+(?:aus|ausschalten)(?:\s+am\s+pc)?\s*[.!]?\s*$", re.I)
_RUNTER = re.compile(_VOR + r"(?:fahr(?:e)?\s+(?:" + _PC + r")\s+(?:herunter|runter)|(?:" + _PC + r")\s+(?:herunterfahren|runterfahren|"
                     r"ausschalten|aus)|schalte?\s+(?:" + _PC + r")\s+aus)\s*[.!]?\s*$", re.I)
_NEU = re.compile(_VOR + r"(?:start(?:e)?\s+(?:" + _PC + r")\s+neu|(?:" + _PC + r")\s+neu\s*starten|neustart\s+(?:" + _PC + r"))\s*[.!]?\s*$", re.I)
_ABBRECHEN = re.compile(_VOR + r"(?:herunterfahren|neustart|shutdown)\s+abbrechen\s*[.!]?\s*$", re.I)
_URL = re.compile(r"^(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/\S*)?$", re.I)
_JA = re.compile(r"^\s*(?:ja|jawohl|mach(?:\s*das)?|ok(?:ay)?|bestätigt|bestaetigt|genau)\b[\s.!]*$", re.I)
_NEIN = re.compile(r"^\s*(?:nein|nee|abbrechen|lass(?:\s*es)?|doch\s*nicht|stopp)\b[\s.!]*$", re.I)

_wartend: dict[str, Any] = {}


class HauptPcFehler(Exception):
    pass


def konfig() -> dict[str, str]:
    return {"url": (os.getenv("HAUPTPC_URL") or "").strip().rstrip("/"),
            "token": (os.getenv("HAUPTPC_TOKEN") or "").strip()}


def ist_eingerichtet() -> bool:
    k = konfig()
    return bool(k["url"] and k["token"])


def _anfrage(methode: str, pfad: str, json_daten: dict | None = None, timeout: float = 8) -> dict:
    k = konfig()
    if not (k["url"] and k["token"]):
        raise HauptPcFehler("Die PC-Steuerung ist noch nicht eingerichtet: am Haupt-PC einmal "
                            "\"3 Einrichten\\PC_STEUERUNG_EINRICHTEN.bat\" starten, danach \"JARVIS STARTEN.bat\".")
    geraeteschutz.netz_pruefen(k["url"] + pfad, "Haupt-PC")
    try:
        r = httpx.request(methode, k["url"] + pfad, headers={"Authorization": f"Bearer {k['token']}"},
                          json=json_daten, timeout=timeout)
    except httpx.ConnectError as exc:
        raise HauptPcFehler("Der Haupt-PC antwortet nicht (aus, schläft, oder der PC-Agent läuft nicht).") from exc
    except httpx.TimeoutException as exc:
        raise HauptPcFehler("Der Haupt-PC antwortet nicht rechtzeitig.") from exc
    except httpx.HTTPError as exc:
        raise HauptPcFehler(f"Verbindung zum Haupt-PC fehlgeschlagen: {exc}") from exc
    if r.status_code == 401:
        raise HauptPcFehler("Der PC-Agent lehnt den Schlüssel ab - PC_STEUERUNG_EINRICHTEN.bat erneut starten.")
    if r.status_code == 429:
        raise HauptPcFehler("Der PC-Agent sperrt kurz wegen Fehlversuchen.")
    try:
        daten = r.json()
    except ValueError:
        daten = {}
    return daten if isinstance(daten, dict) else {}


def status() -> dict:
    return _anfrage("GET", "/status", timeout=4)


def aktionen() -> dict:
    return _anfrage("GET", "/aktionen", timeout=4)


def aktion(name: str, ziel: Any = None, bestaetigt: bool = False) -> dict:
    if name in GEFAEHRLICH and not bestaetigt:
        raise HauptPcFehler("Diese Aktion braucht eine Bestätigung.")
    return _anfrage("POST", "/aktion", {"aktion": name, "ziel": ziel}, timeout=15)


# ------------------------------------------------------------------ Absichten

def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\wäöüß\- ]", " ", (t or "").lower())).strip()


def _finde(ziel: str, namen: dict[str, tuple[str, ...]]) -> str | None:
    z = _norm(ziel)
    z = re.sub(r"^(?:den|die|das|mein(?:en)?|meine)\s+", "", z)
    z = re.sub(r"\s*-?\s*ordner$", "", z).strip()
    for schluessel, woerter in namen.items():
        if z == schluessel or z in woerter:
            return schluessel
    return None


def absicht(text: str) -> dict | None:
    """Erkennt PC-Befehle. None = kein PC-Befehl (dann gehen HUD-Befehle und Claude vor)."""
    t = (text or "").strip()
    if not t or len(t) > 120:
        return None
    if _ABBRECHEN.match(t):
        return {"art": "pc", "aktion": "abbrechen"}
    if _RUNTER.match(t):
        return {"art": "pc", "aktion": "herunterfahren"}
    if _NEU.match(t):
        return {"art": "pc", "aktion": "neustart"}
    if _SPERREN.match(t):
        return {"art": "pc", "aktion": "sperren"}
    if _BILDSCHIRM.match(t):
        return {"art": "pc", "aktion": "bildschirm_aus"}
    m = _LAUT.match(t) or _LAUT2.match(t)
    if m:
        wie = m.group("wie").lower()
        akt = {"lauter": "lauter", "laut": "lauter", "hoch": "lauter", "an": "stumm",
               "leiser": "leiser", "leise": "leiser", "runter": "leiser", "stumm": "stumm", "aus": "stumm"}[wie]
        return {"art": "pc", "aktion": akt}
    m = _MEDIEN.match(t)
    if m:
        was = (m.group("was") or m.group("was2") or "").lower()
        ziel = "naechster" if was.startswith(("nächst", "naechst")) else ("vorheriger" if was.startswith("vorher") else "play_pause")
        return {"art": "pc", "aktion": "medien", "ziel": ziel}
    m = _YT_SUCHE.match(t)
    if m:
        from urllib.parse import quote_plus

        q = (m.group("q") or m.group("q2") or "").strip()
        return {"art": "pc", "aktion": "url", "ziel": "https://www.youtube.com/results?search_query=" + quote_plus(q)}
    m = _OEFFNEN.match(t)
    if m:
        ziel = m.group("ziel").strip()
        am_pc = bool(re.search(r"\b(?:am|auf\s+dem|auf\s+meinem)\s+(?:pc|computer|rechner|haupt-?pc)\b", t, re.I))
        if re.search(r"\bneu\b", ziel, re.I):
            return None
        from .alltag import ziel_seite

        if not am_pc and ziel_seite(ziel):
            return None  # "Öffne Einstellungen" = HUD-Seite, nicht Windows
        prog = _finde(ziel, PROGRAMM_NAMEN)
        if prog:
            return {"art": "pc", "aktion": "programm", "ziel": prog}
        if re.search(r"ordner\b", ziel, re.I) or am_pc:
            ordner = _finde(ziel, ORDNER_NAMEN)
            if ordner:
                return {"art": "pc", "aktion": "ordner", "ziel": ordner}
        seite = _finde(ziel, {k: w for k, (_, w) in WEBSEITEN.items()})
        if seite:
            return {"art": "pc", "aktion": "url", "ziel": WEBSEITEN[seite][0]}
        roh = ziel.split()[-1] if ziel else ""
        if _URL.match(roh) and (am_pc or "." in roh):
            url = roh if roh.lower().startswith("http") else "https://" + roh
            return {"art": "pc", "aktion": "url", "ziel": url}
    return None


SAETZE = {
    "herunterfahren": "den Haupt-PC herunterfahren",
    "neustart": "den Haupt-PC neu starten",
}


def ausfuehren(a: dict) -> str:
    """Chat-Antwort für eine erkannte PC-Absicht."""
    name = a["aktion"]
    if name in GEFAEHRLICH:
        _wartend.clear()
        _wartend.update({"aktion": name, "zeit": time.time()})
        return (f"Soll ich wirklich {SAETZE[name]}, Sir? Sagen Sie \"ja\" (gilt 2 Minuten). "
                f"Danach bleiben noch 60 Sekunden, in denen \"Herunterfahren abbrechen\" es stoppt.")
    try:
        e = aktion(name, a.get("ziel"))
    except HauptPcFehler as exc:
        return f"Das ging nicht, Sir: {exc}"
    if e.get("ok"):
        return f"{e.get('meldung') or 'Erledigt'}, Sir."
    return f"Das hat der Haupt-PC abgelehnt, Sir: {e.get('meldung') or e.get('fehler') or 'unbekannter Grund'}."


def bestaetigung(text: str) -> str | None:
    """Antwort auf eine offene Rückfrage (Herunterfahren/Neustart). None = keine offene Rückfrage."""
    if not _wartend:
        return None
    if time.time() - _wartend.get("zeit", 0) > BESTAETIGUNG_S:
        _wartend.clear()
        return None
    if _JA.match(text or ""):
        name = _wartend.pop("aktion")
        _wartend.clear()
        try:
            e = aktion(name, bestaetigt=True)
        except HauptPcFehler as exc:
            return f"Das ging nicht, Sir: {exc}"
        return f"{e.get('meldung') or 'Erledigt'}, Sir. \"Herunterfahren abbrechen\" stoppt es noch." if e.get("ok") \
            else f"Das hat der Haupt-PC abgelehnt, Sir: {e.get('meldung')}."
    if _NEIN.match(text or ""):
        _wartend.clear()
        return "In Ordnung, Sir, der PC bleibt an."
    return None

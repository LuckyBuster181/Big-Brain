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

Freigabe-Stufen (P22, 13.10.2026) - der Agent setzt sie ebenfalls durch, hier ist die erste Sperre:
    Stufe 0 frei, Stufe 1 feste Befehlsliste (sechs Befehle), Stufe 2 nur nach "ja" (2 Minuten),
    Stufe 3 verboten (freie Befehle, endgültig löschen, Käufe, Überweisungen, Passwörter, Trades, Sicherheit).
    Befehle ohne Claude (0 Cent): "Prüflauf starten", "Backup starten", "Index neu einlesen", "Suche testen",
    "Updates prüfen", "Vault pflegen"; Bericht: "Wie war der Prüflauf?"
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

import httpx

from . import anrede as _anrede
from . import geraeteschutz

# Stufe je Aktion - muss zur Tabelle im Agenten passen (pc_agent_windows/agent_stufen.py)
STUFEN: dict[str, int] = {
    "programm": 0, "ordner": 0, "url": 0, "lauter": 0, "leiser": 0, "stumm": 0, "medien": 0, "anzeige": 0,
    "abbrechen": 0,
    "befehl": 1,
    "sperren": 2, "bildschirm_aus": 2, "herunterfahren": 2, "neustart": 2,
}
STUFE_2 = frozenset(a for a, s in STUFEN.items() if s == 2)
GEFAEHRLICH = STUFE_2  # alter Name
BESTAETIGUNG_S = 120

# Stufe 1: genau diese sechs, mehr nicht (Name -> Wörter für Antworten)
BEFEHLE: dict[str, str] = {
    "pruefen": "Prüflauf",
    "vault_pflege": "Vault-Pflege",
    "reindex": "Index neu einlesen",
    "suchtest": "Suchtest",
    "backup": "Backup",
    "updates_pruefen": "Updates prüfen",
}


def _a(situation: str = "normal") -> str:
    """Anrede für feste Antworten (siehe app/anrede.py): Fehler und Rückfragen immer "Sir"."""
    return _anrede.anrede(situation)


def stufe(name: str) -> int | None:
    """0, 1, 2 oder None (unbekannt/verboten = Stufe 3)."""
    return STUFEN.get(name)

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
# Stufe 1 (P22): feste Befehle ohne Claude. Genau diese sechs.
_BEF_WORTE = {
    "pruefen": r"pr(?:ü|ue|u)f-?lauf",
    "backup": r"backup|sicherung",
    "reindex": r"index\s+neu\s+(?:einlesen|aufbauen)|reindex",
    "suchtest": r"suche\s+testen|such-?test",
    "updates_pruefen": r"updates?\s+pr(?:ü|ue|u)fen|nach\s+updates?\s+suchen",
    "vault_pflege": r"vault-?\s*pflege|vault\s+pflegen",
}
_BEF_START = {
    n: re.compile(_VOR + r"(?:(?:starte?|mach|führe?|fuehre?|lass)\s+)?(?:(?:mal|bitte)\s+)?(?:(?:den|die|das|einen|eine|ein)\s+)?"
                  r"(?:" + w + r")(?:\s+(?:starten|laufen|durchführen|durchfuehren|durch|an))?(?:\s+am\s+pc)?\s*[.!]?\s*$", re.I)
    for n, w in _BEF_WORTE.items()
}
_BEF_NOMEN = {
    "pruefen": r"pr(?:ü|ue|u)f-?lauf",
    "backup": r"backup|sicherung",
    "reindex": r"re-?index|index(?:lauf)?|einlesen",
    "suchtest": r"such-?test",
    "updates_pruefen": r"update-?\s*(?:pr(?:ü|ue|u)fung|check)",
    "vault_pflege": r"vault-?\s*pflege",
}
BERICHT_FRAGE = {"pruefen": "Wie war der Prüflauf?", "backup": "Wie war das Backup?", "reindex": "Wie war der Index?",
                 "suchtest": "Wie war der Suchtest?", "updates_pruefen": "Wie war der Updatecheck?",
                 "vault_pflege": "Wie war die Vault-Pflege?"}
_BEF_BERICHT = {
    n: re.compile(_VOR + r"(?:wie\s+(?:war|lief|ist)\s+(?:der|die|das)\s+(?:" + w + r")(?:\s+gelaufen)?|"
                  r"was\s+hat\s+(?:der|die|das)\s+(?:" + w + r")\s+(?:ergeben|gebracht)|"
                  r"(?:zeig|lies)\s+(?:mir\s+)?(?:den|die|das)\s+(?:bericht|ergebnis)\s+(?:vom|von|des|der)\s+(?:" + w + r"))\s*[?.!]?\s*$", re.I)
    for n, w in _BEF_NOMEN.items()
}
_URL = re.compile(r"^(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/\S*)?$", re.I)
_JA = re.compile(r"^\s*(?:ja|jawohl|mach(?:\s*das)?|ok(?:ay)?|bestätigt|bestaetigt|genau)\b[\s.!]*$", re.I)
_NEIN = re.compile(r"^\s*(?:nein|nee|abbrechen|lass(?:\s*es)?|doch\s*nicht|stopp)\b[\s.!]*$", re.I)

_wartend: dict[str, Any] = {}


class HauptPcFehler(Exception):
    pass


NICHT_EINGERICHTET = ("Die PC-Steuerung ist noch nicht eingerichtet: am Haupt-PC einmal "
                      "\"3 Einrichten\\PC_STEUERUNG_EINRICHTEN.bat\" starten, danach \"JARVIS STARTEN.bat\".")


def konfig() -> dict[str, str]:
    return {"url": (os.getenv("HAUPTPC_URL") or "").strip().rstrip("/"),
            "token": (os.getenv("HAUPTPC_TOKEN") or "").strip()}


def ist_eingerichtet() -> bool:
    k = konfig()
    return bool(k["url"] and k["token"])


def _anfrage(methode: str, pfad: str, json_daten: dict | None = None, timeout: float = 8) -> dict:
    k = konfig()
    if not (k["url"] and k["token"]):
        raise HauptPcFehler(NICHT_EINGERICHTET)
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
    s = stufe(name)
    if s is None:
        raise HauptPcFehler(f"Die Aktion \"{name}\" gibt es nicht (Stufe 3, verboten).")
    if s == 2 and not bestaetigt:
        raise HauptPcFehler("Diese Aktion braucht eine Bestätigung.")
    if s == 1 and name == "befehl" and ziel not in BEFEHLE:
        raise HauptPcFehler("Dieser Befehl steht nicht auf der festen Liste.")
    daten: dict[str, Any] = {"aktion": name, "ziel": ziel}
    if s == 2:
        daten["bestaetigt"] = True
    return _anfrage("POST", "/aktion", daten, timeout=15)


def befehl_bericht(name: str) -> dict:
    """Letzte Zeilen des jüngsten Laufs eines Befehls (Stufe 0, nur lesen)."""
    if name not in BEFEHLE:
        raise HauptPcFehler("Dieser Befehl steht nicht auf der festen Liste.")
    return _anfrage("GET", f"/befehl_bericht?name={name}", timeout=6)


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
    for n, muster in _BEF_BERICHT.items():
        if muster.match(t):
            return {"art": "pc", "aktion": "bericht", "ziel": n}
    for n, muster in _BEF_START.items():
        if muster.match(t):
            return {"art": "pc", "aktion": "befehl", "ziel": n}
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
    "sperren": "den Haupt-PC sperren",
    "bildschirm_aus": "den Bildschirm des Haupt-PCs ausschalten",
}
MIT_ABBRUCH = {"herunterfahren", "neustart"}


def _bericht_text(name: str) -> str:
    try:
        e = befehl_bericht(name)
    except HauptPcFehler as exc:
        return f"Das ging nicht, {_a('fehler')}: {exc}"
    if not e.get("ok"):
        return f"{e.get('meldung') or 'Kein Bericht vorhanden'}, {_a('fehler')}."
    zeilen = [z for z in (e.get("zeilen") or []) if str(z).strip()][-15:]
    stand = "läuft noch" if e.get("laeuft") else ("fertig" if e.get("fertig") else "Stand unklar")
    kopf = f"{BEFEHLE[name]}: {stand} ({e.get('datei', '')}), {_a()}. Letzte Zeilen:"
    return kopf + "\n\n```\n" + "\n".join(str(z) for z in zeilen) + "\n```"


def ausfuehren(a: dict) -> str:
    """Chat-Antwort für eine erkannte PC-Absicht."""
    name = a["aktion"]
    if name == "bericht":
        return _bericht_text(a["ziel"]) if ist_eingerichtet() else \
            f"Die PC-Steuerung ist noch nicht eingerichtet, {_a('fehler')}."
    if name in STUFE_2:
        if not ist_eingerichtet():
            return f"Das ging nicht, {_a('fehler')}: {NICHT_EINGERICHTET}"
        _wartend.clear()
        _wartend.update({"aktion": name, "zeit": time.time()})
        text = f"Soll ich wirklich {SAETZE[name]}, {_a('stufe2')}? Sagen Sie \"ja\" (gilt 2 Minuten)."
        if name in MIT_ABBRUCH:
            text += " Danach bleiben noch 60 Sekunden, in denen \"Herunterfahren abbrechen\" es stoppt."
        return text
    try:
        e = aktion(name, a.get("ziel"))
    except HauptPcFehler as exc:
        return f"Das ging nicht, {_a('fehler')}: {exc}"
    if e.get("ok") and name == "befehl":
        n = BEFEHLE.get(a.get("ziel"), a.get("ziel"))
        return f"{n} läuft jetzt am Haupt-PC, {_a('erfolg')}. Später: \"{BERICHT_FRAGE[a.get('ziel')]}\""
    if e.get("ok"):
        return f"{e.get('meldung') or 'Erledigt'}, {_a('erfolg')}."
    return f"Das hat der Haupt-PC abgelehnt, {_a('fehler')}: {e.get('meldung') or e.get('fehler') or 'unbekannter Grund'}."


def bestaetigung(text: str) -> str | None:
    """Antwort auf eine offene Rückfrage (Stufe 2). None = keine offene Rückfrage."""
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
            return f"Das ging nicht, {_a('fehler')}: {exc}"
        if not e.get("ok"):
            return f"Das hat der Haupt-PC abgelehnt, {_a('fehler')}: {e.get('meldung')}."
        zusatz = " \"Herunterfahren abbrechen\" stoppt es noch." if name in MIT_ABBRUCH else ""
        return f"{e.get('meldung') or 'Erledigt'}, {_a('erfolg')}.{zusatz}"
    if _NEIN.match(text or ""):
        name = _wartend.get("aktion")
        _wartend.clear()
        a = _a("normal")
        return f"In Ordnung, {a}, der PC bleibt an." if name in MIT_ABBRUCH else f"In Ordnung, {a}, nichts wird ausgeführt."
    return None

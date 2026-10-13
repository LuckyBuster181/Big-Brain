"""
Freigabe-Stufen und feste Befehlsliste für den PC-Agenten am Haupt-PC (P22, 13.10.2026).

Stufe 0  frei             Programm, Ordner, Adresse, Lautstärke, Medien, Anzeige, Abbrechen
Stufe 1  feste Liste      nur die sechs Befehle aus befehle_standard.json (oder lokaler befehle.json)
Stufe 2  nur nach Ja      sperren, Bildschirm aus, herunterfahren, neustart  (Request: "bestaetigt": true)
Stufe 3  verboten         freie Befehle, endgültig löschen, Käufe, Überweisungen, Passwörter,
                          Echtgeld-Trades ohne Regelwerk, Sicherheitseinstellungen

Das Modul hängt nur von der Standardbibliothek ab. jarvis_pc_agent.py ruft es auf
(siehe projekt-aufgaben/UEBERGABE P22.md). Der AGENT entscheidet - das Backend ist nur die erste Sperre.
Nichts hier startet etwas von selbst; Prozesse starten nur über befehl_starten().
"""

from __future__ import annotations

import datetime
import json
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Callable

VERSION_STUFEN = "1.2.0"

STUFEN: dict[str, int] = {
    "programm": 0, "ordner": 0, "url": 0, "lauter": 0, "leiser": 0, "stumm": 0, "medien": 0, "anzeige": 0,
    "abbrechen": 0,
    "befehl": 1,
    "sperren": 2, "bildschirm_aus": 2, "herunterfahren": 2, "neustart": 2,
}

# Namen, die ausdrücklich Stufe 3 sind: sie bekommen eine eigene Ablehnung (nicht nur "unbekannt")
STUFE_3 = {"shell", "cmd", "powershell", "terminal", "exec", "loeschen", "endgueltig_loeschen", "kauf",
           "ueberweisung", "passwort", "trade", "sicherheit", "firewall", "defender", "registry"}

FESTE_BEFEHLE = ("pruefen", "vault_pflege", "reindex", "suchtest", "backup", "updates_pruefen")

HERUNTERFAHREN_NACHRICHT = "Auron: Herunterfahren in 60 Sekunden"
NEUSTART_NACHRICHT = "Auron: Neustart in 60 Sekunden"

ZEITLIMIT_STANDARD_S = 1800
BERICHT_ZEILEN = 40


def stufe(aktion: str) -> int | None:
    """0, 1, 2 - oder 3 für ausdrücklich verbotene Namen. None = unbekannte Aktion."""
    name = (aktion or "").strip().lower()
    if name in STUFEN:
        return STUFEN[name]
    if name in STUFE_3:
        return 3
    return None


def freigabe(aktion: str, bestaetigt: bool = False) -> tuple[bool, str, int | None]:
    """Prüft eine Aktion vor der Ausführung. Rückgabe: (erlaubt, Meldung bei Ablehnung, Stufe)."""
    s = stufe(aktion)
    if s is None:
        return False, f"Unbekannte Aktion: {aktion}", None
    if s == 3:
        return False, f"Stufe 3, verboten: {aktion} gibt es am Haupt-PC nicht.", 3
    if s == 2 and bestaetigt is not True:
        return False, f"Stufe 2: {aktion} braucht Ihr Ja (bestaetigt fehlt).", 2
    return True, "", s


def aktionen_mit_stufe() -> dict[str, int]:
    """Für /aktionen: Stufe je Aktion."""
    return dict(STUFEN)


def protokoll_zeile(stufe_: int | None, aktion: str, ziel, absender: str, ergebnis: str,
                    jetzt: datetime.datetime | None = None) -> str:
    """Eine Zeile für agent_protokoll.txt: Zeit, Stufe, Aktion, Ziel, Absender, Ergebnis."""
    t = (jetzt or datetime.datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    st = "?" if stufe_ is None else str(stufe_)
    ziel_text = "-" if ziel in (None, "") else str(ziel).replace("\n", " ")[:120]
    erg = (ergebnis or "").replace("\n", " ")[:160]
    return f"{t} | Stufe {st} | {aktion} | {ziel_text} | von {absender or '-'} | {erg}"


# ------------------------------------------------------------------ Befehlsliste (Stufe 1)

def _gueltig(eintrag) -> bool:
    return isinstance(eintrag, dict) and isinstance(eintrag.get("datei"), str) and bool(eintrag["datei"].strip())


def befehle_laden(jarvis: Path, lokal: Path | None = None, standard: Path | None = None) -> dict[str, dict]:
    """Befehlsliste: lokale befehle.json, wenn sie Befehle enthält - sonst befehle_standard.json.

    Die Standardliste hat nur relative Pfade (relativ zum Jarvis-Ordner) und darf nur auf Dateien
    in pc_befehle\\ zeigen. Die lokale Liste bleibt wie bisher nur am PC änderbar (absolute Pfade erlaubt).
    """
    if lokal is not None and lokal.is_file():
        try:
            roh = json.loads(lokal.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            roh = {}
        if isinstance(roh, dict):
            lokale = {k: v for k, v in roh.items() if _gueltig(v)}
            if lokale:
                return {k: dict(v, _basis=str(jarvis)) for k, v in lokale.items()}
    if standard is None or not standard.is_file():
        return {}
    try:
        roh = json.loads(standard.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(roh, dict):
        return {}
    ergebnis: dict[str, dict] = {}
    erlaubt = (jarvis / "pc_befehle").resolve()
    for name, e in roh.items():
        if name not in FESTE_BEFEHLE or not _gueltig(e):
            continue
        ziel = (jarvis / e["datei"]).resolve()
        if ziel.parent != erlaubt:  # kein "..", keine fremden Ordner
            continue
        ergebnis[name] = dict(e, datei=str(ziel))
    return ergebnis


_sperre = threading.Lock()
_laeuft: dict[str, str] = {}


def laeuft_gerade() -> str | None:
    return _laeuft.get("name")


def befehl_starten(name: str, befehle: dict[str, dict], ausgabe_ordner: Path,
                   starter: Callable[..., "subprocess.CompletedProcess"] | None = None,
                   jetzt: datetime.datetime | None = None, im_hintergrund: bool = True,
                   ) -> tuple[bool, str, threading.Thread | None]:
    """Startet EINEN Stufe-1-Befehl. Höchstens einer gleichzeitig; Zeitlimit; Ausgabe in Datei.

    Rückgabe: (gestartet, Meldung, Thread). `starter` ersetzt subprocess.run (Tests).
    """
    eintrag = befehle.get(name)
    if eintrag is None:
        return False, f"Unbekannter Befehl: {name}", None
    if not _sperre.acquire(blocking=False):
        return False, f"Es läuft schon ein Befehl: {_laeuft.get('name', '?')}", None
    _laeuft.clear()
    _laeuft["name"] = name
    t = jetzt or datetime.datetime.now()
    ausgabe_ordner.mkdir(parents=True, exist_ok=True)
    datei = ausgabe_ordner / f"{name}_{t:%Y-%m-%d}.txt"
    zeitlimit = int(eintrag.get("zeitlimit_s") or ZEITLIMIT_STANDARD_S)
    lauf = starter or subprocess.run

    def arbeit() -> None:
        try:
            with datei.open("w", encoding="utf-8") as f:
                f.write(f"==== START {name} {t:%Y-%m-%d %H:%M:%S} ====\n")
                f.flush()
                try:
                    r = lauf(["cmd", "/c", eintrag["datei"]], stdout=f, stderr=subprocess.STDOUT,
                             timeout=zeitlimit, stdin=subprocess.DEVNULL)
                    f.write(f"\n==== ENDE {name}, Code {getattr(r, 'returncode', '?')} ====\n")
                except subprocess.TimeoutExpired:
                    f.write(f"\n==== ABGEBROCHEN {name}: Zeitlimit {zeitlimit} s ====\n")
                except OSError as exc:
                    f.write(f"\n==== FEHLER {name}: {exc} ====\n")
        finally:
            _laeuft.clear()
            _sperre.release()

    th = threading.Thread(target=arbeit, name=f"befehl-{name}", daemon=True)
    if im_hintergrund:
        th.start()
    else:
        arbeit()
        th = None
    return True, f"{eintrag.get('titel') or name} gestartet", th


def bericht(name: str, ausgabe_ordner: Path, zeilen: int = BERICHT_ZEILEN) -> dict:
    """Letzte Zeilen des jüngsten Laufs eines Befehls (Stufe 0, nur lesen)."""
    if name not in FESTE_BEFEHLE:
        return {"ok": False, "meldung": f"Unbekannter Befehl: {name}"}
    dateien = sorted(ausgabe_ordner.glob(f"{name}_????-??-??.txt")) if ausgabe_ordner.is_dir() else []
    if not dateien:
        return {"ok": False, "meldung": f"Noch kein Lauf von {name} vorhanden."}
    datei = dateien[-1]
    try:
        with datei.open("r", encoding="utf-8", errors="replace") as f:
            letzte = [z.rstrip("\n") for z in deque(f, maxlen=max(1, zeilen))]
    except OSError as exc:
        return {"ok": False, "meldung": f"Bericht nicht lesbar: {exc}"}
    text = "\n".join(letzte)
    fertig = any(m in text for m in ("==== ENDE ", "==== ABGEBROCHEN ", "==== FEHLER "))
    return {"ok": True, "name": name, "datei": datei.name, "laeuft": laeuft_gerade() == name and not fertig,
            "fertig": fertig, "zeilen": letzte}

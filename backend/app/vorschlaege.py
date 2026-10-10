"""
Merken mit Freigabe (Phase 2.3, 23.09.2026).

Entscheidung von Sir (20.09.2026): Jarvis darf in ALLE Notizen des Vaults
schreiben, kündigt jede Änderung vorher an und löscht keine Notiz. Genau das
setzt dieses Modul um:

1. Jarvis legt einen VORSCHLAG an (Diktat "Merk dir ...", Werkzeug
   notiz_vorschlagen, Tagesnotiz aus den Chats, Webseite speichern).
   Dabei wird noch NICHTS im Vault geändert.
2. Das HUD zeigt den Vorschlag mit Ziel-Notiz und Text an ("Jarvis möchte in
   ... schreiben"). Sir klickt "Übernehmen" oder "Verwerfen" (oder sagt "ja").
3. Erst beim Übernehmen wird geschrieben - und zwar nur ANGEHÄNGT (bestehende
   Notiz) oder NEU ANGELEGT. Nie überschrieben, nie gelöscht. Vor dem Anhängen
   wird die alte Fassung nach data/vorschlaege/sicherung/ kopiert; ist der
   Vault ein Git-Repository, folgt zusätzlich ein Commit.

Neue Notizen bekommen status: zu-prüfen (wie im Gesamtplan 2.3 vorgesehen).
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

DEFAULT_DATEI = Path(__file__).resolve().parents[2] / "data" / "vorschlaege.json"
STANDARD_ZIEL = "Wissen/00 - Eingang/Gemerkt von Jarvis.md"
TAGESNOTIZ_ORDNER = "Wissen/02 - Grundlagen/Tages Notizen"
MAX_TEXT = 30_000
MAX_EINTRAEGE = 300
_UNERLAUBT = re.compile(r'[<>:"|?*\x00-\x1f]')
_lock = threading.Lock()


class VorschlagFehler(ValueError):
    pass


def _datei() -> Path:
    return Path(os.getenv("VORSCHLAEGE_PATH") or DEFAULT_DATEI)


def _sicherungsordner() -> Path:
    pfad = _datei().parent / "vorschlaege" / "sicherung"
    pfad.mkdir(parents=True, exist_ok=True)
    return pfad


def vault_pfad() -> Path:
    roh = (os.getenv("VAULT_PATH") or "").strip()
    if not roh or not Path(roh).is_dir():
        raise VorschlagFehler("VAULT_PATH ist nicht gesetzt oder der Ordner fehlt (.env prüfen).")
    return Path(roh)


def _jetzt() -> datetime.datetime:
    return datetime.datetime.now().astimezone()


def _laden() -> list[dict]:
    try:
        daten = json.loads(_datei().read_text(encoding="utf-8"))
        return daten if isinstance(daten, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _speichern(liste: list[dict]) -> None:
    ziel = _datei()
    ziel.parent.mkdir(parents=True, exist_ok=True)
    # erledigte alte Einträge kappen, offene bleiben immer
    offen = [v for v in liste if v.get("status") == "offen"]
    rest = [v for v in liste if v.get("status") != "offen"][-MAX_EINTRAEGE:]
    geordnet = sorted(offen + rest, key=lambda v: v.get("zeit", ""))
    tmp = ziel.with_suffix(".tmp")
    tmp.write_text(json.dumps(geordnet, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ziel)


def ziel_pruefen(ziel: str) -> str:
    """Relativer Pfad innerhalb des Vaults, nur .md, keine Tricks mit .. oder Laufwerken."""
    z = (ziel or "").strip().replace("\\", "/").strip("/")
    if not z:
        return STANDARD_ZIEL
    if not z.lower().endswith(".md"):
        z += ".md"
    teile = [t.strip() for t in z.split("/")]
    if any(t in ("", ".", "..") for t in teile) or re.match(r"^[a-zA-Z]:", z) or any(_UNERLAUBT.search(t) for t in teile):
        raise VorschlagFehler(f"Ungültiges Ziel: {ziel!r}")
    if teile[0].startswith(".") or any(t.startswith(".") for t in teile):
        raise VorschlagFehler("Versteckte Ordner (.obsidian, .git) sind tabu.")
    return "/".join(teile)


def _absolut(rel: str) -> Path:
    basis = vault_pfad().resolve()
    pfad = (basis / rel).resolve()
    if basis not in pfad.parents:
        raise VorschlagFehler("Ziel liegt außerhalb des Vaults.")
    return pfad


def anlegen(text: str, ziel: str | None = None, grund: str = "", quelle: str = "chat",
            titel: str | None = None, art: str | None = None) -> dict:
    """Legt einen Vorschlag an. Schreibt NICHT in den Vault."""
    text = (text or "").strip()
    if not text:
        raise VorschlagFehler("Leerer Vorschlag.")
    if len(text) > MAX_TEXT:
        raise VorschlagFehler(f"Text zu lang ({len(text)} Zeichen, höchstens {MAX_TEXT}).")
    rel = ziel_pruefen(ziel or STANDARD_ZIEL)
    try:
        existiert = _absolut(rel).is_file()
    except VorschlagFehler:
        raise
    art = "anhaengen" if existiert else "neu"
    vorschlag = {
        "id": uuid.uuid4().hex[:10],
        "zeit": _jetzt().isoformat(timespec="seconds"),
        "status": "offen",
        "art": art,
        "ziel": rel,
        "titel": (titel or Path(rel).stem)[:120],
        "text": text,
        "grund": (grund or "").strip()[:500],
        "quelle": quelle,
    }
    with _lock:
        liste = _laden()
        liste.append(vorschlag)
        _speichern(liste)
    return vorschlag


def liste(status: str | None = "offen") -> list[dict]:
    alle = _laden()
    return [v for v in alle if status in (None, "", "alle") or v.get("status") == status][::-1]


def _finden(liste_: list[dict], vid: str) -> dict:
    v = next((x for x in liste_ if x.get("id") == vid), None)
    if v is None:
        raise KeyError(f"Vorschlag {vid} nicht gefunden.")
    if v.get("status") != "offen":
        raise VorschlagFehler(f"Vorschlag {vid} ist schon {v.get('status')}.")
    return v


def _neue_notiz(v: dict) -> str:
    heute = _jetzt().date().isoformat()
    if v["ziel"].startswith(TAGESNOTIZ_ORDNER + "/"):
        tag = Path(v["ziel"]).stem
        return (
            "---\n"
            f"datum: {tag}\n"
            "typ: tagesnotiz\n"
            "projekt: Jarvis\n"
            "status: aktiv\n"
            "---\n\n"
            f"# Tagesnotizen — {tag}\n\n"
            f"{v['text'].rstrip()}\n"
        )
    return (
        "---\n"
        "typ: notiz\n"
        "status: zu-prüfen\n"
        f"erstellt: {heute}\n"
        f"aktualisiert: {heute}\n"
        f"quelle: Jarvis ({v.get('quelle', 'chat')}), von Sir freigegeben\n"
        "vertrauen: mittel\n"
        "niveau: einstieg\n"
        "tags:\n  - jarvis\n"
        "---\n\n"
        f"# {v.get('titel') or Path(v['ziel']).stem}\n\n"
        f"{v['text'].rstrip()}\n"
    )


def _anhang(v: dict, vorhandener_text: str) -> str:
    stempel = _jetzt().strftime("%d.%m.%Y %H:%M")
    trenner = "" if vorhandener_text.endswith("\n\n") else ("\n" if vorhandener_text.endswith("\n") else "\n\n")
    kopf = f"### Von Jarvis ergänzt ({stempel})"
    if v.get("grund"):
        kopf += f"\n\n*{v['grund']}*"
    return f"{trenner}{kopf}\n\n{v['text'].rstrip()}\n"


def uebernehmen(vid: str) -> dict:
    """Schreibt den Vorschlag in den Vault (anhängen oder neu anlegen)."""
    with _lock:
        alle = _laden()
        v = _finden(alle, vid)
        rel = ziel_pruefen(v["ziel"])
        pfad = _absolut(rel)
        if pfad.is_file():
            alt = pfad.read_text(encoding="utf-8", errors="replace")
            sicherung = _sicherungsordner() / f"{vid}_{pfad.name}"
            shutil.copy2(pfad, sicherung)
            with pfad.open("a", encoding="utf-8") as fh:
                fh.write(_anhang(v, alt))
            v["art"] = "anhaengen"
            v["sicherung"] = str(sicherung)
        else:
            pfad.parent.mkdir(parents=True, exist_ok=True)
            pfad.write_text(_neue_notiz(v), encoding="utf-8")
            v["art"] = "neu"
        v["status"] = "uebernommen"
        v["erledigt"] = _jetzt().isoformat(timespec="seconds")
        _speichern(alle)
    v["git"] = _git_commit_versuchen(f"Jarvis: Vorschlag {vid} übernommen ({rel})")
    return v


def verwerfen(vid: str) -> dict:
    with _lock:
        alle = _laden()
        v = _finden(alle, vid)
        v["status"] = "verworfen"
        v["erledigt"] = _jetzt().isoformat(timespec="seconds")
        _speichern(alle)
    return v


def _git_commit_versuchen(nachricht: str) -> str:
    """Commit, wenn der Vault ein Git-Repository ist. Fehler brechen nichts ab -
    die Sicherungskopie in data/vorschlaege/sicherung gibt es ohnehin."""
    try:
        from . import aufgaben_loop  # erst hier: vermeidet Import-Kreise
        vp = str(vault_pfad())
        if not aufgaben_loop._git_verfuegbar(vp):  # noqa: SLF001
            return "kein Git im Vault"
        from . import studium
        if aufgaben_loop.is_running() or studium.is_running():
            return "Aufgaben-Loop oder Studium läuft - deren nächster Commit nimmt die Änderung mit"
        aufgaben_loop._git_commit(vp, nachricht)  # noqa: SLF001
        return "committet"
    except Exception as exc:  # noqa: BLE001
        return f"Git: {exc}"


def tagesnotiz_ziel(tag: datetime.date | str | None = None) -> str:
    t = tag if isinstance(tag, str) else (tag or _jetzt().date()).isoformat()
    return f"{TAGESNOTIZ_ORDNER}/{t}.md"


def kurz(v: dict[str, Any]) -> str:
    was = "an die Notiz anhängen" if v.get("art") == "anhaengen" else "als neue Notiz anlegen"
    return f'Vorschlag {v["id"]}: "{v["ziel"]}" {was}.'

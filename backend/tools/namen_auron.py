"""
Namen im Vault auf Auron umstellen (P20 Teil C, 16.10.2026).

Benennt Dateien und Ordner im Vault um, deren Name "Jarvis" enthält ("06 - Jarvis fragt.md" ->
"06 - Auron fragt.md"), und passt die Links darauf an ([[...]], ![[...]] und [..](...)).
Der Fließtext bleibt, wie er ist: alte Erwähnungen von "Jarvis" in Notizen werden NICHT geändert.

Sicherheit:
- Ohne --ausfuehren nur Probelauf: zeigt, was passieren würde, ändert nichts.
- Nichts wird gelöscht. Gibt es den neuen Namen schon, bleibt die Datei, wie sie ist (steht im Bericht).
- Vor dem Umstellen: Git-Commit im Vault (falls Git da ist) und Kopie jeder Notiz, deren Links sich ändern,
  nach data/namen_auron/<Zeit>/sicherung/. Der Rückweg steht in data/namen_auron/<Zeit>/rueckweg.json.
- --rueckweg <rueckweg.json>: stellt die alten Namen und Notizen wieder her.
- Ausgelassen: versteckte Ordner (.obsidian, .git, .trash).

Aufruf (Sir startet "1 Starten/NAMEN AUF AURON UMSTELLEN.bat", das macht Probelauf, Frage J/N, Umstellen):
    python tools/namen_auron.py --vault "C:/.../Vault"                 Probelauf
    python tools/namen_auron.py --vault "C:/.../Vault" --ausfuehren    umstellen
    python tools/namen_auron.py --rueckweg data/namen_auron/<Zeit>/rueckweg.json
    python tools/namen_auron.py --jarvis-ordner "C:/.../Jarvis"        Vault aus data/einstellungen.json bzw. VAULT_PATH der .env
Kosten: 0 EUR, keine KI.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

ALT_RE = re.compile(r"\b(Jarvis|JARVIS|jarvis)\b")
ERSATZ = {"Jarvis": "Auron", "JARVIS": "AURON", "jarvis": "auron"}
WIKILINK_RE = re.compile(r"(!?\[\[)([^\]|#\n]+)((?:#[^\]|\n]*)?(?:\|[^\]\n]*)?\]\])")
MDLINK_RE = re.compile(r"(\]\()([^)\s]+)(\))")
WURZEL = Path(__file__).resolve().parents[2]


class NamenFehler(RuntimeError):
    pass


def neuer_name(name: str) -> str:
    return ALT_RE.sub(lambda m: ERSATZ[m.group(1)], name)


def _versteckt(rel: Path) -> bool:
    return any(t.startswith(".") for t in rel.parts)


# ------------------------------------------------------------------ Planen


def planen(vault: Path) -> dict:
    """Was umbenannt würde. Rückgabe: {"umbenennen": [(alt_rel, neu_rel)], "konflikte": [...], "dateien": {alt->neu}}
    umbenennen ist in Ausführungsreihenfolge: erst Dateien, dann Ordner von innen nach außen."""
    vault = Path(vault)
    eintraege = []
    for wurzel, ordner, dateien in os.walk(vault):
        rel_wurzel = Path(wurzel).relative_to(vault)
        ordner[:] = [o for o in ordner if not o.startswith(".")]
        for name in ordner + dateien:
            rel = rel_wurzel / name
            if _versteckt(rel) or not ALT_RE.search(name):
                continue
            eintraege.append((rel, (vault / rel).is_dir()))
    umbenennen, konflikte = [], []
    # Dateien zuerst (im alten Ordner), dann Ordner, tiefste zuerst
    for rel, ist_ordner in sorted(eintraege, key=lambda e: (e[1], -len(e[0].parts), str(e[0]))):
        ziel = rel.with_name(neuer_name(rel.name))
        if (vault / ziel).exists():
            konflikte.append((rel.as_posix(), ziel.as_posix(), "neuer Name existiert schon"))
            continue
        umbenennen.append((rel.as_posix(), ziel.as_posix(), ist_ordner))
    # Endgültiger Pfad jeder Datei (alt -> neu), auch für Dateien in umbenannten Ordnern
    ordner_neu = {a: n for a, n, o in umbenennen if o}
    datei_neu = {a: n for a, n, o in umbenennen if not o}
    alle = {}
    for wurzel, ordner, dateien in os.walk(vault):
        ordner[:] = [o for o in ordner if not o.startswith(".")]
        for name in dateien:
            rel = (Path(wurzel) / name).relative_to(vault)
            if _versteckt(rel):
                continue
            alt = rel.as_posix()
            teile = list(rel.parts)
            neu_teile = []
            for i in range(len(teile)):
                stueck = "/".join(teile[: i + 1])
                if i == len(teile) - 1:
                    neu_teile.append(Path(datei_neu.get(stueck, stueck)).name)
                else:
                    neu_teile.append(Path(ordner_neu.get(stueck, stueck)).name)
            neu = "/".join(neu_teile)
            if neu != alt:
                alle[alt] = neu
    return {"umbenennen": umbenennen, "konflikte": konflikte, "dateien": alle}


def _link_ersatz(ziel: str, dateien: dict[str, str], namen: dict[str, str]) -> str | None:
    """Neues Link-Ziel oder None. ziel ist der Teil vor # und |, z.B. "Ordner/Jarvis X" oder "Jarvis X.md"."""
    pfad = ziel.strip().replace("\\", "/").lstrip("/")
    if pfad in dateien:                           # voller Pfad mit Endung (auch Bilder)
        return dateien[pfad]
    if pfad + ".md" in dateien:                   # voller Pfad ohne .md (Obsidian-Standard)
        return dateien[pfad + ".md"][:-3]
    if "/" not in pfad and pfad in namen:         # nur der Name (Obsidian-Kurzform)
        return namen[pfad]
    return None


def links_ersetzen(text: str, dateien: dict[str, str]) -> tuple[str, list[tuple[str, str]]]:
    """Ersetzt Link-Ziele auf umbenannte Dateien. Gibt den neuen Text und die Änderungen zurück."""
    namen: dict[str, str] = {}
    mehrfach: set[str] = set()
    for alt, neu in dateien.items():
        for a, n in ((Path(alt).name, Path(neu).name), (Path(alt).stem, Path(neu).stem) if alt.endswith(".md") else (None, None)):
            if a is None or a == n:
                continue
            if a in namen and namen[a] != n:
                mehrfach.add(a)
            namen[a] = n
    for a in mehrfach:                            # gleicher alter Name, verschiedene neue: nicht raten
        namen.pop(a, None)
    aenderungen: list[tuple[str, str]] = []

    def wiki(m: re.Match) -> str:
        neu = _link_ersatz(m.group(2), dateien, namen)
        if neu is None or neu == m.group(2):
            return m.group(0)
        aenderungen.append((m.group(2), neu))
        return m.group(1) + neu + m.group(3)

    def md(m: re.Match) -> str:
        ziel = m.group(2)
        if re.match(r"^[a-z]+://", ziel, re.I):
            return m.group(0)
        anker = ""
        if "#" in ziel:
            ziel, anker = ziel.split("#", 1)
            anker = "#" + anker
        entschluesselt = urllib.parse.unquote(ziel)
        neu = _link_ersatz(entschluesselt, dateien, namen)
        if neu is None or neu == entschluesselt:
            return m.group(0)
        neu_kodiert = urllib.parse.quote(neu, safe="/") if ziel != entschluesselt else neu
        aenderungen.append((m.group(2), neu_kodiert + anker))
        return m.group(1) + neu_kodiert + anker + m.group(3)

    text = WIKILINK_RE.sub(wiki, text)
    text = MDLINK_RE.sub(md, text)
    return text, aenderungen


def link_plan(vault: Path, dateien: dict[str, str]) -> dict[str, list[tuple[str, str]]]:
    """{alter Pfad der Notiz: [(altes Ziel, neues Ziel), ...]} für alle Notizen mit betroffenen Links."""
    plan = {}
    if not dateien:
        return plan
    for pfad in Path(vault).rglob("*.md"):
        rel = pfad.relative_to(vault)
        if _versteckt(rel):
            continue
        try:
            text = pfad.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        _, aenderungen = links_ersetzen(text, dateien)
        if aenderungen:
            plan[rel.as_posix()] = aenderungen
    return plan


# ------------------------------------------------------------------ Ausführen


def _git(vault: Path, *befehl: str) -> str:
    if not (vault / ".git").exists() or not shutil.which("git"):
        return "kein Git im Vault"
    try:
        erg = subprocess.run(["git", "-C", str(vault), *befehl], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Git-Fehler: {exc}"
    return (erg.stdout or erg.stderr or "").strip()[:200] or "ok"


def git_sichern(vault: Path, nachricht: str) -> str:
    if _git(vault, "add", "-A") == "kein Git im Vault":
        return "kein Git im Vault"
    return _git(vault, "commit", "-q", "-m", nachricht) or "ok"


def ausfuehren(vault: Path, arbeitsordner: Path, plan: dict | None = None) -> dict:
    """Umbenennen + Links anpassen. Schreibt Sicherung und Rückweg nach arbeitsordner."""
    vault = Path(vault)
    plan = plan or planen(vault)
    links = link_plan(vault, plan["dateien"])
    arbeitsordner.mkdir(parents=True, exist_ok=True)
    sicherung = arbeitsordner / "sicherung"
    rueckweg = {"zeit": datetime.datetime.now().isoformat(timespec="seconds"), "vault": str(vault),
                "umbenannt": [], "notizen": {}, "git": git_sichern(vault, "Vor NAMEN AUF AURON UMSTELLEN (P20)")}
    rueck_datei = arbeitsordner / "rueckweg.json"

    def merken() -> None:
        rueck_datei.write_text(json.dumps(rueckweg, ensure_ascii=False, indent=1), encoding="utf-8")

    # 1. Notizen mit betroffenen Links sichern (unter ihrem alten Pfad)
    for alt_rel in links:
        ziel = sicherung / alt_rel
        ziel.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(vault / alt_rel, ziel)
        rueckweg["notizen"][plan["dateien"].get(alt_rel, alt_rel)] = alt_rel
    merken()
    # 2. Umbenennen (Dateien, dann Ordner von innen nach außen) - nach jedem Schritt Rückweg schreiben
    for alt, neu, _ordner in plan["umbenennen"]:
        quelle, ziel = vault / alt, vault / neu
        if not quelle.exists() or ziel.exists():
            continue
        quelle.rename(ziel)
        rueckweg["umbenannt"].append([alt, neu])
        merken()
    # 3. Links anpassen (Notizen liegen jetzt unter ihrem neuen Pfad)
    geaendert = 0
    for alt_rel in links:
        pfad = vault / plan["dateien"].get(alt_rel, alt_rel)
        text = pfad.read_text(encoding="utf-8")
        neu_text, aenderungen = links_ersetzen(text, plan["dateien"])
        if aenderungen:
            pfad.write_text(neu_text, encoding="utf-8")
            geaendert += 1
    rueckweg["links_geaendert"] = geaendert
    merken()
    return {"umbenannt": len(rueckweg["umbenannt"]), "notizen_mit_links": geaendert,
            "konflikte": plan["konflikte"], "rueckweg": str(rueck_datei), "git": rueckweg["git"]}


def zurueck(rueck_datei: Path) -> dict:
    """Alte Namen und alte Notizen wiederherstellen. Löscht nichts: Notizen werden aus der Sicherung zurückkopiert."""
    daten = json.loads(Path(rueck_datei).read_text(encoding="utf-8"))
    vault = Path(daten["vault"])
    sicherung = Path(rueck_datei).parent / "sicherung"
    zurueck_benannt, uebersprungen = 0, []
    for alt, neu in reversed(daten.get("umbenannt", [])):
        quelle, ziel = vault / neu, vault / alt
        if quelle.exists() and not ziel.exists():
            quelle.rename(ziel)
            zurueck_benannt += 1
        else:
            uebersprungen.append(f"{neu} -> {alt}")
    wiederhergestellt = 0
    for _neu, alt_rel in daten.get("notizen", {}).items():
        kopie = sicherung / alt_rel
        if kopie.is_file() and (vault / alt_rel).exists():
            shutil.copy2(kopie, vault / alt_rel)
            wiederhergestellt += 1
    return {"zurueck_benannt": zurueck_benannt, "notizen_wiederhergestellt": wiederhergestellt, "uebersprungen": uebersprungen}


# ------------------------------------------------------------------ Bericht und Aufruf


def bericht(plan: dict, links: dict[str, list[tuple[str, str]]], probelauf: bool) -> str:
    zeilen = [("PROBELAUF - es wurde nichts geändert." if probelauf else "UMGESTELLT."), ""]
    dateien = [u for u in plan["umbenennen"] if not u[2]]
    ordner = [u for u in plan["umbenennen"] if u[2]]
    zeilen.append(f"Umbenennen: {len(dateien)} Dateien, {len(ordner)} Ordner")
    for alt, neu, ist_ordner in plan["umbenennen"]:
        zeilen.append(f"  {'[Ordner] ' if ist_ordner else ''}{alt}  ->  {Path(neu).name}")
    zeilen += ["", f"Bleiben, wie sie sind (neuer Name gibt es schon): {len(plan['konflikte'])}"]
    zeilen += [f"  {a}  ({grund}: {Path(n).name})" for a, n, grund in plan["konflikte"]]
    zeilen += ["", f"Links anpassen: {sum(len(v) for v in links.values())} Links in {len(links)} Notizen"]
    for notiz, aend in sorted(links.items())[:200]:
        zeilen.append(f"  {notiz}: " + "; ".join(f"{a} -> {n}" for a, n in aend[:5]) + (" ..." if len(aend) > 5 else ""))
    zeilen += ["", "Der Fließtext bleibt unverändert (alte Erwähnungen von Jarvis bleiben stehen). Nichts wird gelöscht."]
    return "\n".join(zeilen) + "\n"


def vault_finden(jarvis_ordner: Path) -> Path | None:
    """Vault aus data/einstellungen.json (vault_pfad), sonst VAULT_PATH aus der .env (nur diese eine Zeile)."""
    try:
        pfad = json.loads((jarvis_ordner / "data" / "einstellungen.json").read_text(encoding="utf-8")).get("vault_pfad")
        if pfad and Path(pfad).is_dir():
            return Path(pfad)
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    env = jarvis_ordner / ".env"
    if env.is_file():
        for zeile in env.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^\s*VAULT_PATH\s*=\s*(.+?)\s*$", zeile)
            if m:
                pfad = m.group(1).strip().strip('"').strip("'")
                if Path(pfad).is_dir():
                    return Path(pfad)
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--vault", type=Path)
    p.add_argument("--jarvis-ordner", type=Path, default=WURZEL)
    p.add_argument("--ausfuehren", action="store_true", help="wirklich umstellen (sonst Probelauf)")
    p.add_argument("--rueckweg", type=Path, help="rueckweg.json einer früheren Umstellung: alles zurück")
    p.add_argument("--bericht", type=Path, help="Bericht zusätzlich in diese Datei schreiben")
    a = p.parse_args(argv)

    if a.rueckweg:
        erg = zurueck(a.rueckweg)
        text = (f"RÜCKWEG: {erg['zurueck_benannt']} Namen zurück, {erg['notizen_wiederhergestellt']} Notizen wiederhergestellt.\n"
                + "".join(f"  übersprungen: {u}\n" for u in erg["uebersprungen"]))
    else:
        vault = a.vault or vault_finden(a.jarvis_ordner)
        if not vault or not Path(vault).is_dir():
            print("FEHLER: Vault nicht gefunden. Mit --vault \"Pfad\" angeben.")
            return 2
        vault = Path(vault)
        plan = planen(vault)
        links = link_plan(vault, plan["dateien"])
        text = f"Vault: {vault}\n" + bericht(plan, links, probelauf=not a.ausfuehren)
        if a.ausfuehren:
            ordner = a.jarvis_ordner / "data" / "namen_auron" / datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            erg = ausfuehren(vault, ordner, plan)
            text += (f"\nERGEBNIS: {erg['umbenannt']} umbenannt, Links in {erg['notizen_mit_links']} Notizen angepasst.\n"
                     f"Git vorher: {erg['git']}\nRückweg: {erg['rueckweg']}\n")
    print(text)
    if a.bericht:
        a.bericht.parent.mkdir(parents=True, exist_ok=True)
        with a.bericht.open("a", encoding="utf-8") as f:
            f.write(f"===== {datetime.datetime.now():%d.%m.%Y %H:%M:%S} =====\n{text}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Namen (P20, 16.10.2026): Der Assistent heißt Auron. "Jarvis" bleibt nur als stilles Synonym bei
Befehlen und als Rückfall bei Umgebungsvariablen und Vault-Dateinamen.

- NAMEN / ANREDE: zentrale Liste für die Befehlserkennung ("Auron, ..." == "Jarvis, ...").
  Das Weckwort im Browser (dashboard/auron.html, WECKWORT) hat zusätzlich Hörfehler-Varianten.
- env("HANDY_TOKEN"): liest zuerst AURON_HANDY_TOKEN, sonst JARVIS_HANDY_TOKEN. Die .env bleibt, wie sie ist.
- vault_datei(vault, "…/06 - Jarvis fragt.md"): nimmt die Auron-Fassung, sobald es sie gibt
  (nach NAMEN AUF AURON UMSTELLEN.bat), sonst die alte Datei.
Nicht geändert (bewusst): Collection-Namen, data-Pfade, Projektordner und Dienst "jarvis" auf dem Mini-PC.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

NAME = "Auron"
NAMEN = ("auron", "jarvis")                      # erster = heutiger Name
ANREDE = "(?:" + "|".join(NAMEN) + ")"           # für Befehls-Regex, immer mit re.I benutzen
PRAEFIXE = ("AURON_", "JARVIS_")                 # Umgebungsvariablen: neuer Name zuerst


def ist_name(wort: str) -> bool:
    return (wort or "").strip(" ,.!?:;").lower() in NAMEN


def ohne_anrede(text: str) -> str:
    """'Jarvis, wie spät ist es' -> 'wie spät ist es' (gleich für Auron)."""
    return re.sub(r"^\s*" + ANREDE + r"\b[\s,.:!?-]*", "", text or "", flags=re.I)


def env(schluessel: str, standard: str | None = None) -> str | None:
    """AURON_<schluessel>, sonst JARVIS_<schluessel>, sonst standard. Leere Werte zählen als nicht gesetzt."""
    for praefix in PRAEFIXE:
        wert = os.getenv(praefix + schluessel)
        if wert not in (None, ""):
            return wert
    return standard


def env_gruppe(praefix: str) -> dict[str, str]:
    """Alle Einträge AURON_<praefix>* und JARVIS_<praefix>*; bei gleichem Rest gewinnt AURON_.
    Schlüssel = Rest nach dem Präfix (z.B. "ZUGANG_" -> {"LAPTOP": "..."})."""
    gefunden: dict[str, str] = {}
    for vorne in reversed(PRAEFIXE):             # JARVIS_ zuerst, AURON_ überschreibt
        ganz = vorne + praefix
        for name, wert in os.environ.items():
            if name.startswith(ganz) and wert not in (None, ""):
                gefunden[name[len(ganz):]] = wert
    return gefunden


def auron_fassung(rel: str) -> str:
    """Vault-Pfad mit dem neuen Namen ('06 - Jarvis fragt.md' -> '06 - Auron fragt.md')."""
    return re.sub(r"\bJarvis\b", NAME, rel)


def vault_datei(vault: str | Path, rel: str) -> str:
    """Relativer Vault-Pfad, der gerade gilt: die Auron-Fassung, wenn es sie gibt, sonst die alte.
    Gibt es keine von beiden, die Auron-Fassung nur dann, wenn ihr Ordner schon umbenannt ist, sonst die alte."""
    neu = auron_fassung(rel)
    if neu == rel:
        return rel
    basis = Path(vault)
    if (basis / neu).exists():
        return neu
    if (basis / rel).exists():
        return rel
    return neu if (basis / neu).parent.exists() and not (basis / rel).parent.exists() else rel

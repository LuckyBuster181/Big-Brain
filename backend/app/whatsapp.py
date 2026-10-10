"""
WhatsApp-Links (27.09.2026, Claude Cowork) - 0 Cent, ohne WhatsApp-Zugang.

Jarvis verschickt NICHTS selbst: Für private WhatsApp-Konten gibt es keinen
offiziellen Weg, und automatisches Senden kann zur Sperre der Nummer führen.
Stattdessen baut Jarvis einen Link (wa.me). Ein Tipp darauf öffnet WhatsApp
(Handy: App, PC: WhatsApp Desktop/Web) mit fertig eingetragenem Text - Sir
drückt nur noch "Senden".

Chat:
    "WhatsApp an Lisa: Ich komme 10 Minuten später"   -> Link sofort, Text wie diktiert
    "Schreib eine WhatsApp an Lisa, dass ..."          -> Jarvis formuliert (app/schreiben.py),
                                                          je Variante ein Link
    "Speicher Kontakt Lisa 0170 1234567"               -> Nummer merken (data/kontakte.json)
    "Meine Kontakte"
Ohne gespeicherte Nummer fragt WhatsApp nach dem Empfänger.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import quote

MAX_TEXT = 3000


class WhatsAppFehler(ValueError):
    pass


def _datei() -> Path:
    return Path(os.getenv("KONTAKTE_PATH") or Path(__file__).resolve().parents[2] / "data" / "kontakte.json")


def kontakte() -> dict[str, dict]:
    try:
        d = json.loads(_datei().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def nummer_normal(roh: str) -> str:
    """'0170 123 4567' -> '491701234567', '+49 170 ...' -> '49170...' (Format für wa.me)."""
    ziffern = re.sub(r"[^\d+]", "", roh or "")
    if ziffern.startswith("+"):
        ziffern = ziffern[1:]
    elif ziffern.startswith("00"):
        ziffern = ziffern[2:]
    elif ziffern.startswith("0"):
        ziffern = "49" + ziffern[1:]
    if not re.fullmatch(r"\d{8,15}", ziffern):
        raise WhatsAppFehler("Die Nummer sieht nicht gültig aus, Sir (z. B. 0170 1234567 oder +49 170 1234567).")
    return ziffern


def _schluessel(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def kontakt_speichern(name: str, nummer: str) -> dict:
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not name or len(name) > 40:
        raise WhatsAppFehler("Wie heißt der Kontakt, Sir?")
    alle = kontakte()
    alle[_schluessel(name)] = {"name": name, "nummer": nummer_normal(nummer)}
    p = _datei()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(alle, ensure_ascii=False, indent=1), encoding="utf-8")
    return alle[_schluessel(name)]


def kontakt_finden(text: str) -> dict | None:
    """Sucht einen gespeicherten Namen im Text ("an Lisa", "an meinen Chef")."""
    t = _schluessel(text)
    treffer = None
    for k, v in kontakte().items():
        if re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", t) and (treffer is None or len(k) > len(_schluessel(treffer["name"]))):
            treffer = v
    return treffer


def link(text: str, nummer: str | None = None) -> str:
    text = (text or "").strip()[:MAX_TEXT]
    ziel = f"https://wa.me/{nummer}" if nummer else "https://wa.me/"
    return f"{ziel}?text={quote(text, safe='')}"


def direkt(name: str, text: str) -> str:
    """Antwort für "WhatsApp an Lisa: ..." - 0 Cent."""
    text = (text or "").strip()
    if not text:
        raise WhatsAppFehler("Was soll in der Nachricht stehen, Sir?")
    k = kontakt_finden(name)
    wem = f" an {k['name']}" if k else ""
    hinweis = "" if k else (f"\n\nFür {name.strip()} habe ich keine Nummer, WhatsApp fragt nach dem Empfänger. "
                            f"Mit \"Speicher Kontakt {name.strip()} 0170 …\" merke ich sie mir.")
    return (f"Fertig, Sir. Ein Tipp öffnet WhatsApp mit dem Text, Sie drücken nur noch Senden:\n\n"
            f"```\n{text}\n```\n[In WhatsApp öffnen{wem}]({link(text, k['nummer'] if k else None)}){hinweis}")


_CODEBLOCK = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.S)


def links_anhaengen(antwort: str, auftrag: str) -> str:
    """Hängt an jede Variante (Codeblock) einer geschriebenen WhatsApp einen Link."""
    bloecke = [b.strip() for b in _CODEBLOCK.findall(antwort or "") if b.strip()]
    if not bloecke:
        return antwort
    k = kontakt_finden(auftrag)
    nummer = k["nummer"] if k else None
    wem = f" an {k['name']}" if k else ""
    zeilen = [f"- [Variante {i} in WhatsApp öffnen{wem}]({link(b, nummer)})" if len(bloecke) > 1
              else f"[In WhatsApp öffnen{wem}]({link(b, nummer)})" for i, b in enumerate(bloecke, 1)]
    return antwort.rstrip() + "\n\n" + "\n".join(zeilen)


def liste_text() -> str:
    alle = kontakte()
    if not alle:
        return "Noch keine Kontakte gespeichert, Sir. Beispiel: \"Speicher Kontakt Lisa 0170 1234567\"."
    return "Gespeicherte Kontakte, Sir:\n" + "\n".join(f"- {v['name']}: +{v['nummer']}" for v in alle.values())

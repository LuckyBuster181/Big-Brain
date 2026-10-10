"""
Liste aller Notizen im Vault für das Dashboard.

Liest nur die Metadaten (Frontmatter) und die Dateigröße, keinen Index und kein
Modell. Es sind genau die Notizen, die auch in den Suchindex kommen: Archiv und
Importarchiv lässt iter_markdown_files bereits weg.

Start (zum Ausprobieren):
    python -m app.vault_list
"""

from __future__ import annotations

import datetime
import os
import re
from pathlib import Path
from typing import Any

from rag.vault_loader import (
    IGNORE_VALUES,
    _read_text,
    _split_frontmatter,
    iter_markdown_files,
    relative_path,
)

# [[Ziel]] oder [[Ziel|Text]] oder [[Ziel#Abschnitt]] - Code-Blöcke bleiben außen vor
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
CODE_RE = re.compile(r"```.*?```|`[^`]*`", re.DOTALL)


def _links(body: str, bekannt: dict[str, str]) -> list[str]:
    """Wikilinks einer Notiz, aufgelöst auf Pfade im Vault (unbekannte fallen weg)."""
    ziele = []
    for raw in WIKILINK_RE.findall(CODE_RE.sub(" ", body)):
        name = raw.strip().rstrip("/")
        treffer = bekannt.get(name.lower()) or bekannt.get(name.rsplit("/", 1)[-1].lower())
        if treffer and treffer not in ziele:
            ziele.append(treffer)
    return ziele


def _first(frontmatter: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = frontmatter.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def notes(vault_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Alle indexierten Notizen mit Pfad, Titel, Status und Änderungszeit, neueste zuerst."""
    vault_path = vault_path or os.getenv("VAULT_PATH")
    if not vault_path:
        return []
    root = Path(vault_path)
    if not root.is_dir():
        return []

    dateien = list(iter_markdown_files(root))
    # Nachschlagewerk für Links: voller Pfad ohne .md und reiner Dateiname
    bekannt: dict[str, str] = {}
    for path in dateien:
        rel = relative_path(path, root)
        bekannt.setdefault(rel[:-3].lower(), rel)
        bekannt.setdefault(path.stem.lower(), rel)

    result: list[dict[str, Any]] = []
    for path in dateien:
        try:
            stat = path.stat()
        except OSError:
            continue  # gerade gelöscht oder umbenannt
        raw = _read_text(path) or ""
        frontmatter, body = _split_frontmatter(raw)
        rel = relative_path(path, root)
        parts = rel.split("/")
        result.append(
            {
                "pfad": rel,
                "ordner": "/".join(parts[:-1]),
                "titel": _first(frontmatter, "titel", "title") or path.stem,
                "status": _first(frontmatter, "status"),
                "niveau": _first(frontmatter, "niveau"),
                "vertrauen": _first(frontmatter, "vertrauen"),
                "typ": _first(frontmatter, "typ", "type"),
                "zeichen": len(body),
                "geaendert": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "ignoriert": str(frontmatter.get("jarvis", "")).strip().lower() in IGNORE_VALUES,
                "links": _links(body, bekannt),
            }
        )
    result.sort(key=lambda note: note["geaendert"], reverse=True)
    return result


if __name__ == "__main__":  # pragma: no cover
    from dotenv import load_dotenv

    load_dotenv()
    alle = notes()
    print(f"{len(alle)} Notizen im Index-Bereich des Vaults")
    for note in alle[:10]:
        print(f"  {note['geaendert']}  {note['pfad']}")

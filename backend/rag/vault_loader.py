"""
Vault Loader für Jarvis / Big Brain
------------------------------------
Liest Markdown-Notizen aus dem Obsidian-Vault ein, trennt YAML-Frontmatter
vom Inhalt und teilt den Inhalt anhand der Markdown-Überschriftenstruktur
in Chunks auf (nicht stumpf nach Zeichenanzahl).

Nutzung:
    from rag.vault_loader import load_vault
    chunks = load_vault(vault_path)

Jeder Chunk ist ein VaultChunk mit:
    id            - stabile, deterministische ID (sha1), gleich bei erneutem Lauf
    file_path     - Pfad relativ zum Vault-Root (für Quellenangaben)
    note_title    - Titel der Notiz (H1 oder Dateiname)
    heading_path  - Breadcrumb der Überschriften, z. B. "Titel > Abschnitt > Unterabschnitt"
    content       - Text des Chunks (inkl. Breadcrumb-Präfix für Kontext)
    chunk_index   - Position innerhalb der Notiz
    frontmatter   - geparste YAML-Metadaten (typ, status, vertrauen, tags, ...)
    file_hash     - Fingerabdruck der Datei (für inkrementelles Neu-Indexieren)
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Ordner, die beim Einlesen übersprungen werden (Konfig/Plugin-Daten, Archiv, Duplikate)
DEFAULT_SKIP_DIRS = {
    ".obsidian",
    ".claude",
    ".claudian",
    ".git",
    "Archiv",
    "90 - Archivierte Dubletten",
    "90 - Importarchiv",
}

# Notizen mit "jarvis: ignorieren" im Frontmatter werden nicht indexiert (z.B.
# Platzhalter ohne Inhalt, Berichte, Listen). Gleiche Wirkung: aus, nein, false.
IGNORE_VALUES = {"ignorieren", "aus", "nein", "false", "off"}

# Chunks über dieser Zeichenzahl werden zusätzlich an Absätzen aufgeteilt
MAX_CHUNK_CHARS = 1500

# Wird bei Änderungen an der Chunk-Logik erhöht. Fließt in den Datei-Hash ein,
# dadurch indexiert der nächste inkrementelle Lauf automatisch alles neu.
# 3 (20.09.2026 abends): # in Codeblöcken zaehlt nicht mehr als Überschrift.
INDEX_FORMAT_VERSION = "3"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?\n)---\s*\n?", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.MULTILINE)
# Fenced Code-Blöcke (``` oder ~~~, mind. 3 Zeichen, schließende Zeile mit
# demselben Zeichen/derselben Länge). Zeilen darin sind KEINE Überschriften -
# ohne diesen Filter hält die Suche z.B. "# 7. BPE" oder ein Kommentar wie
# "# TODO" in einem Codebeispiel für eine echte Überschrift und schneidet den
# Abschnitt dort ab (Befund 20.09.2026: 35 betroffene Zeilen, u.a. in den
# Notizen "knap" und "defuddle").
CODE_FENCE_RE = re.compile(r"^([`~]{3,})[^\n]*\n.*?^\1[ \t]*$", re.MULTILINE | re.DOTALL)


@dataclass
class VaultChunk:
    id: str
    file_path: str
    note_title: str
    heading_path: str
    content: str
    chunk_index: int
    frontmatter: dict[str, Any] = field(default_factory=dict)
    file_hash: str = ""


def compute_file_hash(path: Path) -> str:
    """SHA-1 über den Dateiinhalt (+ Format-Version). Unabhängig vom Änderungsdatum,
    damit reines Speichern ohne Änderung (z.B. durch Sync) keinen Reindex auslöst."""
    digest = hashlib.sha1(INDEX_FORMAT_VERSION.encode("utf-8"))
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _read_text(path: Path) -> str | None:
    """Liest eine Datei robust ein. Bekanntes Problem im Projekt: einzelne
    Dateien wurden versehentlich als UTF-16 statt UTF-8 gespeichert
    (siehe Entwicklungslog 2026-09-19, PowerShell Out-File BOM)."""
    for encoding in ("utf-8", "utf-8-sig", "utf-16"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return None


def _split_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(raw)
    if not match:
        return {}, raw
    fm_text = match.group(1)
    body = raw[match.end():]
    try:
        fm = yaml.safe_load(fm_text) or {}
        if not isinstance(fm, dict):
            fm = {}
    except yaml.YAMLError:
        fm = {}
    return fm, body


def _note_title(body: str, frontmatter: dict[str, Any], filename: str, headings: list[re.Match]) -> str:
    # Nur verwenden, wenn die ERSTE Überschrift im Dokument tatsächlich Level 1 ist.
    # In diesem Vault kommt "#" teils auch mitten im Text für nummerierte
    # Unterabschnitte vor (z.B. "# 7. BPE -- Grundprinzip"), das ist kein Titel.
    if headings and len(headings[0].group(1)) == 1:
        return headings[0].group(2).strip()
    aliases = frontmatter.get("aliases")
    if isinstance(aliases, list) and aliases:
        return str(aliases[0])
    return filename


def _split_by_paragraphs(text: str, max_chars: int) -> list[str]:
    """Teilt einen zu langen Abschnitt an Absatzgrenzen (nicht mitten im Satz)."""
    paragraphs = re.split(r"\n\s*\n", text.strip())
    parts: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) > max_chars and current:
            parts.append(current.strip())
            current = para
        else:
            current = candidate
    if current.strip():
        parts.append(current.strip())
    return parts or [text.strip()]


def _chunk_body(body: str, note_title: str, headings: list[re.Match]) -> list[tuple[str, str]]:
    """Teilt den Notiz-Text an Überschriften auf.
    Gibt Liste von (heading_path, section_text) zurück."""
    if not headings:
        text = body.strip()
        return [(note_title, text)] if text else []

    sections: list[tuple[str, str]] = []
    # Text vor der ersten Überschrift (z. B. Einleitung) als eigener Abschnitt
    pre_text = body[: headings[0].start()].strip()
    if pre_text:
        sections.append((note_title, pre_text))

    stack: list[tuple[int, str]] = []  # (level, title)
    for i, m in enumerate(headings):
        level = len(m.group(1))
        title = m.group(2).strip()
        start = m.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        text = body[start:end].strip()

        # Breadcrumb-Stack auf aktuelles Level zurückschneiden
        stack = [s for s in stack if s[0] < level]
        stack.append((level, title))
        path_parts = [t for _, t in stack]
        # note_title nicht doppeln, falls die H1-Überschrift bereits dem Titel entspricht
        if not path_parts or path_parts[0] != note_title:
            path_parts = [note_title] + path_parts
        heading_path = " > ".join(path_parts)

        if text:
            sections.append((heading_path, text))

    return sections


def _find_headings(body: str) -> list[re.Match]:
    """Wie HEADING_RE.finditer(body), aber ohne Treffer innerhalb von Codeblöcken."""
    spans = [(m.start(), m.end()) for m in CODE_FENCE_RE.finditer(body)]
    if not spans:
        return list(HEADING_RE.finditer(body))
    return [m for m in HEADING_RE.finditer(body) if not any(s <= m.start() < e for s, e in spans)]


def _make_id(file_path: str, heading_path: str, index: int) -> str:
    raw = f"{file_path}::{heading_path}::{index}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def relative_path(path: Path, vault_root: Path) -> str:
    """Pfad relativ zum Vault mit "/" - so steht er in den Metadaten und Quellenangaben."""
    return str(path.relative_to(vault_root)).replace("\\", "/")


def load_note(path: Path, vault_root: Path, file_hash: str | None = None) -> list[VaultChunk]:
    raw = _read_text(path)
    if raw is None:
        return []
    if file_hash is None:
        file_hash = compute_file_hash(path)

    frontmatter, body = _split_frontmatter(raw)
    if str(frontmatter.get("jarvis", "")).strip().lower() in IGNORE_VALUES:
        return []  # bewusst von der Suche ausgenommen
    rel_path = relative_path(path, vault_root)
    filename = path.stem
    headings = _find_headings(body)
    note_title = _note_title(body, frontmatter, filename, headings)

    sections = _chunk_body(body, note_title, headings)
    if not sections:
        return []  # leere Notiz - nichts zu indexieren

    chunks: list[VaultChunk] = []
    idx = 0
    for heading_path, text in sections:
        if len(text) > MAX_CHUNK_CHARS:
            for part in _split_by_paragraphs(text, MAX_CHUNK_CHARS):
                content = f"{heading_path}\n\n{part}"
                chunks.append(
                    VaultChunk(
                        id=_make_id(rel_path, heading_path, idx),
                        file_path=rel_path,
                        note_title=note_title,
                        heading_path=heading_path,
                        content=content,
                        chunk_index=idx,
                        frontmatter=frontmatter,
                        file_hash=file_hash,
                    )
                )
                idx += 1
        else:
            content = f"{heading_path}\n\n{text}"
            chunks.append(
                VaultChunk(
                    id=_make_id(rel_path, heading_path, idx),
                    file_path=rel_path,
                    note_title=note_title,
                    heading_path=heading_path,
                    content=content,
                    chunk_index=idx,
                    frontmatter=frontmatter,
                    file_hash=file_hash,
                )
            )
            idx += 1

    return chunks


def iter_markdown_files(vault_path: str | Path, skip_dirs: set[str] | None = None):
    root = Path(vault_path)
    skip = skip_dirs if skip_dirs is not None else DEFAULT_SKIP_DIRS
    for path in sorted(root.rglob("*.md")):
        if any(part in skip for part in path.relative_to(root).parts[:-1]):
            continue
        yield path


def load_vault(vault_path: str | Path, skip_dirs: set[str] | None = None) -> list[VaultChunk]:
    root = Path(vault_path)
    all_chunks: list[VaultChunk] = []
    for path in iter_markdown_files(root, skip_dirs):
        all_chunks.extend(load_note(path, root))
    return all_chunks


if __name__ == "__main__":
    import argparse
    import os
    import sys

    from dotenv import load_dotenv

    # Windows-Konsolen nutzen standardmäßig eine Legacy-Codepage (z.B. cp1252)
    # statt UTF-8 -> Umlaute/Emojis aus dem Vault würden print() sonst mit
    # UnicodeEncodeError abstürzen lassen.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    load_dotenv()
    parser = argparse.ArgumentParser(description="Vault einlesen und Chunk-Statistik ausgeben")
    parser.add_argument("--vault", default=os.getenv("VAULT_PATH"), help="Pfad zum Obsidian-Vault")
    args = parser.parse_args()

    if not args.vault:
        raise SystemExit("Kein Vault-Pfad angegeben (--vault oder VAULT_PATH in .env)")

    chunks = load_vault(args.vault)
    files = {c.file_path for c in chunks}
    print(f"{len(files)} Notizen eingelesen, {len(chunks)} Chunks erzeugt.")
    for c in chunks[:5]:
        preview = c.content[:120].replace("\n", " ")
        print(f"  [{c.file_path}] {c.heading_path}: {preview}...")

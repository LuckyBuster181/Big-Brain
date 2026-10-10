"""
Vault-Pflegebericht für Big Brain.

Prüft den Obsidian-Vault und schreibt einen Bericht als Notiz. Ändert keine
andere Notiz - nur der Bericht selbst wird (neu) geschrieben.

Geprüft wird (nach den Regeln aus "03 - Big Brain Ziele und Entwicklungsplan"):
- Links, die ins Leere zeigen, auf fehlende Abschnitte, mehrdeutig sind oder
  ins Archiv führen
- Notizen ohne eingehende Links (Waisen) und ohne ausgehende Links (Sackgassen)
- Metadaten: status, vertrauen, quelle, Datum; Status-Werte außerhalb des Standards
- doppelte Inhalte zwischen aktiven Notizen und doppelte Dateinamen
- große Sammelnotizen (Kandidaten zum Aufteilen) und Überschriften-Struktur
- generische KI-Importe (Vorlagen-Gliederung, oft wenig eigener Inhalt)
- Tag-Varianten, leere Ordner, Dateien mit falscher Zeichenkodierung

Aktiv = alles außer Archiv/, "90 - Importarchiv" und "90 - Archivierte Dubletten".
Archivierte Notizen zählen nur als Linkziele.

Start:
    backend\\vault_pflege.bat
    python -m tools.vault_pflege                  (Vault aus VAULT_PATH in .env)
    python -m tools.vault_pflege --vault PFAD --out BERICHT.md
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from rag.vault_loader import HEADING_RE, IGNORE_VALUES, _read_text, _split_frontmatter, load_note

REPORT_NAME = "Vault-Pflegebericht.md"
REPORT_DIR = "Wissen/06 - Quellen und Pflege"

SKIP_DIRS = {".obsidian", ".claude", ".claudian", ".git", ".trash"}
ARCHIVE_PARTS = {"Archiv", "90 - Importarchiv", "90 - Archivierte Dubletten"}

# "aktiv" = laufend fortgeschrieben (Entscheidung 20.09.2026, siehe Entwicklungsplan)
STANDARD_STATUS = {"bestätigt", "aktiv", "entwurf", "zu-prüfen", "veraltet"}
DATE_KEYS = ("zuletzt_geprüft", "aktualisiert", "erstellt", "stand", "datum", "date", "recherchiert")
# Gleiche Bedeutung, unterschiedlich geschrieben
KEY_SYNONYMS = [("date", "datum"), ("title", "titel"), ("typ", "type")]

# Gliederung der generischen KI-Importe (Perplexity-Vorlage)
TEMPLATE_HEADINGS = {
    "einführung und bedeutung",
    "kern-konzepte und grundlagen",
    "wichtige theorien und modelle",
    "aktuelle forschung und entwicklungen",
    "praktische anwendungen",
    "zukünftige perspektiven",
    "herausforderungen und kontroversen",
    "ethische überlegungen",
    "zusammenfassung",
}

# Typische Platzhalter in Anleitungen ("Immer [[Note]] statt URL verwenden") - kein echter Fehler
EXAMPLE_TARGETS = {"note", "note name", "notiz", "notizname", "seite", "page", "link", "datei", "file",
                   "my note", "meine notiz", "andere notiz", "other note", "titel", "title"}

LARGE_NOTE_CHARS = 20_000
LARGE_NOTE_CHUNKS = 60
DUPLICATE_CONTAINMENT = 0.5  # Anteil gemeinsamer Wortfolgen der kleineren Notiz
SHINGLE = 6

WIKILINK_RE = re.compile(r"(!?)\[\[([^\[\]]+?)\]\]")
MDLINK_RE = re.compile(r"(?<!!)\[[^\]\n]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE_RE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.MULTILINE | re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
TAG_INLINE_RE = re.compile(r"(?<![\w/#&])#([A-Za-zÄÖÜäöüß][\w\-/ÄÖÜäöüß]*)")
WORD_RE = re.compile(r"[a-zA-ZäöüÄÖÜß0-9]+")
MOJIBAKE_RE = re.compile(r"Ã[¤¶¼„–œŸ]|â€[™œ“”\x9d]")


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


@dataclass
class Link:
    raw: str
    target: str
    anchor: str | None
    embed: bool
    kind: str  # wiki | md


@dataclass
class Note:
    rel: str
    path: Path
    active: bool
    text: str | None = None
    frontmatter: dict = field(default_factory=dict)
    body: str = ""
    links: list[Link] = field(default_factory=list)
    headings: list[tuple[int, str]] = field(default_factory=list)
    chunks: int = 0
    long_sections: int = 0

    @property
    def name(self) -> str:
        return Path(self.rel).stem


# ---------------------------------------------------------------------------
# Einlesen
# ---------------------------------------------------------------------------

def is_archive(rel: str) -> bool:
    return any(part in ARCHIVE_PARTS for part in rel.split("/")[:-1])


def scan(vault: Path, report_rel: str) -> tuple[list[Note], list[str], list[str]]:
    """Alle Dateien (für Linkziele), alle Notizen, leere Ordner."""
    notes: list[Note] = []
    all_files: list[str] = []
    empty_dirs: list[str] = []
    for dirpath, dirnames, filenames in os.walk(vault):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        rel_dir = Path(dirpath).relative_to(vault).as_posix()
        if rel_dir != "." and not dirnames and not filenames:
            empty_dirs.append(rel_dir)
        for filename in sorted(filenames):
            rel = nfc((Path(rel_dir) / filename).as_posix() if rel_dir != "." else filename)
            all_files.append(rel)
            if filename.lower().endswith(".md") and rel != report_rel:
                notes.append(Note(rel=rel, path=Path(dirpath) / filename, active=not is_archive(rel)))
    return notes, all_files, sorted(empty_dirs)


def strip_code(text: str) -> str:
    return INLINE_CODE_RE.sub("", FENCE_RE.sub("", text))


def parse_links(body: str) -> list[Link]:
    links: list[Link] = []
    clean = strip_code(body)
    for m in WIKILINK_RE.finditer(clean):
        inner = m.group(2).split("|", 1)[0].rstrip("\\").strip()
        target, _, anchor = inner.partition("#")
        links.append(Link(m.group(0), nfc(target.strip()), anchor.strip() or None, bool(m.group(1)), "wiki"))
    for m in MDLINK_RE.finditer(clean):
        url = m.group(1)
        if re.match(r"^[a-z][a-z0-9+.-]*:", url, re.IGNORECASE) or url.startswith("#"):
            continue  # http, mailto, obsidian:// usw.
        target, _, anchor = unquote(url).partition("#")
        links.append(Link(m.group(0), nfc(target.strip()), anchor.strip() or None, False, "md"))
    return links


def load(note: Note) -> None:
    raw = _read_text(note.path)
    if raw is None:
        note.text = None
        return
    note.text = raw
    note.frontmatter, note.body = _split_frontmatter(raw)
    note.links = parse_links(note.body)
    clean = strip_code(note.body)
    note.headings = [(len(m.group(1)), m.group(2).strip()) for m in HEADING_RE.finditer(clean)]


# ---------------------------------------------------------------------------
# Links auflösen (angelehnt an Obsidian)
# ---------------------------------------------------------------------------

class Resolver:
    def __init__(self, all_files: list[str]) -> None:
        self.by_path = {f.lower(): f for f in all_files}
        self.by_name: dict[str, list[str]] = defaultdict(list)
        for f in all_files:
            self.by_name[f.rsplit("/", 1)[-1].lower()].append(f)

    def resolve(self, target: str, source_rel: str) -> list[str]:
        if not target:
            return [source_rel]  # [[#Abschnitt]] = Link in dieselbe Notiz
        link = target.replace("\\", "/").strip().lstrip("/")
        candidates = [link] if Path(link).suffix.lower() in (".md", ".canvas", ".base", ".png", ".jpg",
                                                               ".jpeg", ".gif", ".svg", ".webp", ".pdf") else [link + ".md", link]
        src_dir = source_rel.rsplit("/", 1)[0] if "/" in source_rel else ""
        for cand in candidates:
            hit = self.by_path.get(cand.lower())
            if hit:
                return [hit]
            if src_dir:
                rel = os.path.normpath(f"{src_dir}/{cand}").replace("\\", "/")
                hit = self.by_path.get(rel.lower())
                if hit:
                    return [hit]
        for cand in candidates:
            if "/" in cand:
                suffix = "/" + cand.lower()
                matches = [f for low, f in self.by_path.items() if low.endswith(suffix)]
            else:
                matches = list(self.by_name.get(cand.lower(), []))
            if matches:
                return matches
        return []


def heading_exists(note: Note, anchor: str) -> bool:
    if anchor.startswith("^"):
        return f"^{anchor[1:]}" in (note.body or "")
    wanted = anchor.split("#")[-1].strip().lower()
    return any(h.lower() == wanted for _, h in note.headings)


# ---------------------------------------------------------------------------
# Prüfungen
# ---------------------------------------------------------------------------

def shingles(text: str) -> set[tuple[str, ...]]:
    words = [w.lower() for w in WORD_RE.findall(strip_code(text))]
    return {tuple(words[i : i + SHINGLE]) for i in range(max(0, len(words) - SHINGLE + 1))}


def normalize_tag(tag: str) -> str:
    tag = tag.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    tag = re.sub(r"[-_ ]", "", tag)
    return tag[:-1] if tag.endswith("s") and len(tag) > 4 else tag


def note_tags(note: Note) -> list[str]:
    tags = note.frontmatter.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in re.split(r"[,\s]+", tags) if t.strip()]
    result = [str(t).lstrip("#") for t in tags if t]
    result += TAG_INLINE_RE.findall(strip_code(note.body or ""))
    return result


def link_label(rel: str) -> str:
    """Klickbarer Link auf eine vorhandene Notiz (Pipes für Tabellen maskiert)."""
    path = rel[:-3] if rel.endswith(".md") else rel
    return f"[[{path}\\|{Path(rel).stem}]]"


def md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def analyse(vault: Path, report_rel: str, not_checked: set[str] | None = None) -> dict:
    """not_checked = Notizen, die nur als Linkziel zählen (z.B. nicht lesbar)."""
    not_checked = {nfc(r) for r in (not_checked or set())}
    notes, all_files, empty_dirs = scan(vault, report_rel)
    for note in notes:
        load(note)
    by_rel = {n.rel: n for n in notes}
    active = [n for n in notes if n.active and n.text is not None and n.rel not in not_checked]
    unreadable = [n.rel for n in notes if n.text is None]
    resolver = Resolver(all_files)

    broken, examples, missing_anchor, ambiguous, to_archive = [], [], [], [], []
    incoming: dict[str, set[str]] = defaultdict(set)
    outgoing_active: dict[str, set[str]] = defaultdict(set)
    for note in active:
        for link in note.links:
            matches = resolver.resolve(link.target, note.rel)
            if not matches:
                if link.target.strip().lower() in EXAMPLE_TARGETS:
                    examples.append((note.rel, link))
                else:
                    broken.append((note.rel, link))
                continue
            active_matches = [m for m in matches if not is_archive(m)]
            if len(matches) > 1:
                ambiguous.append((note.rel, link, matches))
            chosen = (active_matches or matches)[0]
            if is_archive(chosen) and not is_archive(note.rel):
                to_archive.append((note.rel, link, chosen))
            if chosen != note.rel and chosen in by_rel:
                incoming[chosen].add(note.rel)
                if by_rel[chosen].active:
                    outgoing_active[note.rel].add(chosen)
            target_note = by_rel.get(chosen)
            if link.anchor and target_note and target_note.text is not None and not heading_exists(target_note, link.anchor):
                missing_anchor.append((note.rel, link, chosen))

    orphans = [n.rel for n in active if not incoming.get(n.rel)]
    dead_ends = [n.rel for n in active if not outgoing_active.get(n.rel)]

    # Metadaten
    metadata_rows, nonstandard_status, key_mix = [], Counter(), Counter()
    no_frontmatter = []
    for note in active:
        fm = note.frontmatter
        if not fm:
            no_frontmatter.append(note.rel)
        status = str(fm.get("status") or "").strip()
        if status and status not in STANDARD_STATUS:
            nonstandard_status[status] += 1
        missing = [k for k in ("status", "vertrauen", "quelle") if not fm.get(k)]
        if not any(fm.get(k) for k in DATE_KEYS):
            missing.append("Datum")
        if missing:
            metadata_rows.append((note.rel, missing, status))
        for a, b in KEY_SYNONYMS:
            if a in fm:
                key_mix[a] += 1
            if b in fm:
                key_mix[b] += 1

    # Größe und Struktur
    large, structure, templates = [], [], []
    for note in active:
        chunks = load_note(note.path, vault)
        note.chunks = len(chunks)
        size = len(note.text or "")
        if size > LARGE_NOTE_CHARS or note.chunks > LARGE_NOTE_CHUNKS:
            large.append((note.rel, size, note.chunks))
        h1 = [h for level, h in note.headings if level == 1]
        issues = []
        if len(h1) > 1:
            issues.append(f"{len(h1)}× Überschrift der Ebene 1")
        if note.headings and note.headings[0][0] > 2 and not h1:
            issues.append(f"beginnt mit Ebene {note.headings[0][0]}")
        if issues:
            structure.append((note.rel, ", ".join(issues)))
        template_hits = {h.lower() for _, h in note.headings} & TEMPLATE_HEADINGS
        if len(template_hits) >= 5:
            templates.append((note.rel, len(template_hits), str(note.frontmatter.get("status") or "–")))

    # Doppelte Inhalte
    shingle_sets = {n.rel: shingles(n.body) for n in active}
    duplicates = []
    rels = sorted(shingle_sets)
    for i, a in enumerate(rels):
        for b in rels[i + 1 :]:
            sa, sb = shingle_sets[a], shingle_sets[b]
            smaller = min(len(sa), len(sb))
            if smaller < 30:
                continue
            common = len(sa & sb)
            share = common / smaller
            if share >= DUPLICATE_CONTAINMENT:
                small, big = (a, b) if len(sa) <= len(sb) else (b, a)
                duplicates.append((small, big, share))
    duplicates.sort(key=lambda d: -d[2])

    # Gruppen: Notizen, die paarweise fast gleich sind (z.B. derselbe Vorlagentext)
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for small, big, _ in duplicates:
        parent[find(small)] = find(big)
    groups: dict[str, list[str]] = defaultdict(list)
    for rel in {r for d in duplicates for r in d[:2]}:
        groups[find(rel)].append(rel)
    duplicate_groups = sorted((sorted(g) for g in groups.values()), key=lambda g: (-len(g), g))

    names = Counter(Path(n.rel).name.lower() for n in active)
    same_names = sorted(
        (name, sorted(n.rel for n in active if Path(n.rel).name.lower() == name)) for name, c in names.items() if c > 1
    )

    # Tags
    tag_variants: dict[str, Counter] = defaultdict(Counter)
    for note in active:
        for tag in note_tags(note):
            tag_variants[normalize_tag(tag)][tag] += 1
    tag_groups = sorted(
        ((k, v) for k, v in tag_variants.items() if len(v) > 1), key=lambda kv: -sum(kv[1].values())
    )
    tag_total = len({t for v in tag_variants.values() for t in v})

    mojibake = [n.rel for n in active if MOJIBAKE_RE.search(n.text or "")]
    encoding_issues = []
    for note in active:
        head = note.path.read_bytes()[:4]
        if head.startswith((b"\xff\xfe", b"\xfe\xff")):
            encoding_issues.append((note.rel, "UTF-16"))
        elif head.startswith(b"\xef\xbb\xbf"):
            encoding_issues.append((note.rel, "UTF-8 mit BOM"))

    fixes = []  # (Notiz, Link, Vorschlag oder None)
    prefix_moves: Counter = Counter()
    for rel, link in broken:
        best = best_match(link.target, all_files)
        fixes.append((rel, link, best))
        if best:
            # kompletter Ordnerpfad alt -> neu (nicht nur der erste Ordner, sonst
            # würde eine Ersetzung auch funktionierende Links verändern)
            old_dir = link.target.replace("\\", "/").rpartition("/")[0]
            new_dir = best.rpartition("/")[0]
            if old_dir.lower() != new_dir.lower():
                prefix_moves[(old_dir + "/" if old_dir else "", new_dir + "/" if new_dir else "")] += 1

    return {
        "fixes": fixes,
        "prefix_moves": prefix_moves,
        "examples": examples,
        "duplicate_groups": duplicate_groups,
        "notes": notes,
        "active": active,
        "archive_count": sum(1 for n in notes if not n.active),
        "unreadable": unreadable,
        "all_files": all_files,
        "empty_dirs": empty_dirs,
        "broken": broken,
        "missing_anchor": missing_anchor,
        "ambiguous": ambiguous,
        "to_archive": to_archive,
        "orphans": orphans,
        "dead_ends": dead_ends,
        "metadata_rows": metadata_rows,
        "no_frontmatter": no_frontmatter,
        "nonstandard_status": nonstandard_status,
        "key_mix": key_mix,
        "large": sorted(large, key=lambda x: -x[1]),
        "structure": structure,
        "templates": templates,
        "duplicates": duplicates,
        "same_names": same_names,
        "tag_groups": tag_groups,
        "tag_total": tag_total,
        "mojibake": mojibake,
        "encoding": encoding_issues,
    }


# ---------------------------------------------------------------------------
# Bericht
# ---------------------------------------------------------------------------

def search_ignored(result: dict) -> set[str]:
    """Notizen, die per `jarvis: ignorieren` (o. ä.) nicht in den Suchindex kommen."""
    return {
        n.rel for n in result["notes"]
        if str((n.frontmatter or {}).get("jarvis", "")).strip().lower() in IGNORE_VALUES
    }


def render(result: dict, today: str, skipped_note: str | None = None) -> str:
    active = result["active"]
    n_active = len(active)
    meta_missing = Counter(k for _, missing, _ in result["metadata_rows"] for k in missing)

    rows = [
        ("Links ins Leere", len(result["broken"]), "hoch", "#links-ins-leere"),
        ("Links auf fehlende Abschnitte", len(result["missing_anchor"]), "mittel", "#links-auf-fehlende-abschnitte"),
        ("Notizen mit fast gleichem Text", sum(len(g) for g in result["duplicate_groups"]), "hoch", "#doppelte-inhalte"),
        ("Notizen ohne eingehende Links", len(result["orphans"]), "mittel", "#notizen-ohne-eingehende-links"),
        (f"Notizen ohne Status (von {n_active})", meta_missing["status"], "mittel", "#metadaten"),
        (f"Notizen ohne Vertrauen (von {n_active})", meta_missing["vertrauen"], "mittel", "#metadaten"),
        (f"Notizen ohne Quelle (von {n_active})", meta_missing["quelle"], "mittel", "#metadaten"),
        (f"Notizen ohne Datum (von {n_active})", meta_missing["Datum"], "mittel", "#metadaten"),
        ("Große Sammelnotizen", len(result["large"]), "mittel", "#grosse-sammelnotizen"),
        ("Generische KI-Importe", len(result["templates"]), "niedrig", "#generische-ki-importe"),
        ("Mehrdeutige Links", len(result["ambiguous"]), "niedrig", "#mehrdeutige-links"),
        ("Links ins Archiv", len(result["to_archive"]), "niedrig", "#links-ins-archiv"),
        ("Notizen ohne ausgehende Links", len(result["dead_ends"]), "niedrig", "#notizen-ohne-ausgehende-links"),
        ("Überschriften-Struktur auffällig", len(result["structure"]), "niedrig", "#ueberschriften"),
        ("Tag-Varianten (Gruppen)", len(result["tag_groups"]), "niedrig", "#tags"),
        ("Leere Ordner", len(result["empty_dirs"]), "niedrig", "#leere-ordner"),
        ("Zeichenkodierung auffällig", len(result["encoding"]) + len(result["mojibake"]), "niedrig", "#zeichenkodierung"),
    ]

    out: list[str] = []
    w = out.append
    w("---")
    w("typ: bericht")
    w("status: aktiv")
    w(f"erstellt: {today}")
    w("quelle: automatische Prüfung (Jarvis/backend/tools/vault_pflege.py)")
    w("vertrauen: hoch")
    w("jarvis: ignorieren")
    w("tags:")
    w("  - vault-pflege")
    w("  - qualitaet")
    w("---")
    w("")
    w("# Vault-Pflegebericht")
    w("")
    w("[[Gehirn/00 - Übersicht|Startseite]] · [[Wissen/06 - Quellen und Pflege/00 - Quellen und Pflege|Quellen und Pflege]] · "
      "Regeln: [[Wissen/03 - KI und Technik/03 - Big Brain Ziele und Entwicklungsplan|Entwicklungsplan]]")
    w("")
    w("> [!info] Automatisch erzeugt")
    w(f"> Stand {today}. Geprüft: {n_active} aktive Notizen, {result['archive_count']} archivierte (nur als Linkziel). "
      "Der Bericht ändert keine Notiz. Neu erzeugen: `Jarvis\\backend\\vault_pflege.bat` – diese Datei wird dabei überschrieben.")
    if skipped_note:
        w(f"> {skipped_note}")
    w("")
    w("## Übersicht")
    w("")
    w("| Prüfung | Anzahl | Wichtigkeit |")
    w("| --- | --- | --- |")
    for label, count, weight, anchor in rows:
        w(f"| {label} | {count} | {weight if count else '–'} |")
    w("")

    # --- Empfehlungen
    w("## Was zuerst tun")
    w("")
    todo = []
    if result["broken"]:
        text = f"**{len(result['broken'])} Links zeigen ins Leere** – ein Klick darauf legt in Obsidian eine leere neue Notiz an."
        moves = result["prefix_moves"].most_common()
        if moves and moves[0][1] >= 3:
            (old_p, new_p), count = moves[0]
            text += (f" {count} davon lassen sich mit einer einzigen Ersetzung reparieren: "
                     f"`{old_p or '(ohne Ordner)'}` → `{new_p or '(ohne Ordner)'}` (Ordner wurde verschoben).")
        missing = Counter(l.target for _, l, best in result["fixes"] if not best)
        if missing:
            top = ", ".join(f"`{t}` ({c}×)" for t, c in missing.most_common(2))
            text += f" Gar nicht vorhanden: {top}."
        todo.append(text)
    ignored = search_ignored(result)
    for group in result["duplicate_groups"]:
        if len(group) > 2:
            names = ", ".join(Path(r).stem for r in group)
            open_rels = [r for r in group if r not in ignored]
            if not open_rels:
                todo.append(f"**{len(group)} Platzhalter mit fast demselben Text** ({names}) sind schon mit "
                            "`jarvis: ignorieren` von der Suche ausgenommen. Offen: mit echtem Inhalt füllen "
                            "(dann die Zeile wieder löschen) oder die Notizen löschen.")
                continue
            text = (f"**{len(group)} Notizen bestehen aus fast demselben Text** ({names}). Das sind Platzhalter "
                    "aus einem Import ohne echten Fachinhalt. Entweder mit Inhalt füllen oder bis dahin mit "
                    "`jarvis: ignorieren` im Frontmatter von der Suche ausnehmen.")
            if len(open_rels) < len(group):
                text += " Noch nicht ausgenommen: " + ", ".join(Path(r).stem for r in open_rels) + "."
            else:
                text += " Die Jarvis-Suche findet sie derzeit noch."
            todo.append(text)
    pairs = [g for g in result["duplicate_groups"] if len(g) == 2]
    if pairs:
        names = "; ".join(" / ".join(Path(r).stem for r in g) for g in pairs)
        label = "1 Notizpaar" if len(pairs) == 1 else f"{len(pairs)} Notizpaare"
        todo.append(f"**{label} mit weitgehend gleichem Inhalt** ({names}) – eine Hauptnotiz behalten, "
                    "die andere darauf verlinken (Regel 5 im Entwicklungsplan).")
    if meta_missing["status"] or meta_missing["vertrauen"]:
        todo.append(f"**Metadaten ergänzen**: {meta_missing['vertrauen']} von {n_active} Notizen ohne `vertrauen`, "
                    f"{meta_missing['status']} ohne `status`. Jarvis warnt nur bei Notizen, die diese Felder haben.")
    if result["nonstandard_status"]:
        values = ", ".join(f"`{s}` ({c}×)" for s, c in result["nonstandard_status"].most_common())
        todo.append(f"**Status-Werte vereinheitlichen**: Standard ist bestätigt / aktiv / entwurf / zu-prüfen / veraltet, im Vault stehen auch {values}.")
    if result["large"]:
        names = ", ".join(Path(r).stem for r, _, _ in result["large"][:3])
        todo.append(f"**{len(result['large'])} große Sammelnotizen aufteilen** (Regel 3), zuerst: {names}. Kleinere Notizen findet die Suche gezielter.")
    if result["orphans"]:
        todo.append(f"**{len(result['orphans'])} Notizen ohne eingehende Links** in eine Übersicht eintragen (Regel 2).")
    in_groups = {r for g in result["duplicate_groups"] for r in g}
    other_templates = [r for r, _, _ in result["templates"] if r not in in_groups]
    if other_templates:
        todo.append(f"**{len(other_templates)} generische KI-Importe prüfen** – gleiche Vorlagen-Gliederung, oft allgemeines "
                    "Lehrbuchwissen ohne Quelle. Behalten, kürzen oder als `entwurf` markieren.")
    if result["empty_dirs"]:
        todo.append(f"**{len(result['empty_dirs'])} leere Ordner löschen** (vor allem unter `Archiv/Wissen`).")
    for i, item in enumerate(todo, 1):
        w(f"{i}. {item}")
    if not todo:
        w("Keine dringenden Punkte.")
    w("")

    # --- Details
    w("## Links ins Leere")
    w("")
    if result["broken"]:
        grouped: dict[tuple[str, str], list] = defaultdict(list)
        for rel, link, best in result["fixes"]:
            grouped[(rel, link.target)].append((link, best))
        moves = result["prefix_moves"].most_common()
        main_move = moves[0][0] if moves and moves[0][1] >= 3 else None
        rest = []
        by_note: Counter = Counter()
        for (rel, target), items in grouped.items():
            best = items[0][1]
            if main_move and best and target.startswith(main_move[0]) and best.startswith(main_move[1]):
                by_note[rel] += len(items)
            else:
                rest.append((rel, target, items))
        if by_note:
            old_p, new_p = main_move
            w(f"**Verschobener Ordner:** {sum(by_note.values())} Links in {len(by_note)} Notizen zeigen noch auf "
              f"`{old_p}` statt `{new_p}`. In Obsidian: Suchen und Ersetzen im ganzen Vault (oder Claude/Jarvis "
              "damit beauftragen). Betroffen:")
            w("")
            w(", ".join(f"{link_label(r).replace(chr(92), '')} ({c})" for r, c in sorted(by_note.items())))
            w("")
        if rest:
            w("| Notiz | Link | Vorschlag |")
            w("| --- | --- | --- |")
            for rel, target, items in sorted(rest):
                count = f" ({len(items)}×)" if len(items) > 1 else ""
                best = items[0][1]
                hint = f"`{best[:-3] if best.endswith('.md') else best}`" if best else "Notiz existiert nicht"
                w(f"| {link_label(rel)} | `{md_escape(items[0][0].raw)}`{count} | {hint} |")
    else:
        w("Keine.")
    if result["examples"]:
        w("")
        w("Kein Fehler, nur Beispiele im Text: " + ", ".join(
            f"`{md_escape(l.raw)}` in {link_label(r).replace(chr(92), '')}" for r, l in result["examples"]))
    w("")

    w("## Links auf fehlende Abschnitte")
    w("")
    if result["missing_anchor"]:
        w("| Notiz | Link | Ziel |")
        w("| --- | --- | --- |")
        for rel, link, target in result["missing_anchor"]:
            w(f"| {link_label(rel)} | `{md_escape(link.raw)}` | {link_label(target)} |")
    else:
        w("Keine.")
    w("")

    w("## Doppelte Inhalte")
    w("")
    if result["duplicate_groups"]:
        share_of = {}
        for small, big, share in result["duplicates"]:
            for r in (small, big):
                share_of[r] = max(share_of.get(r, 0), share)
        w(f"Gezählt wird, wie viel Text (Folgen von {SHINGLE} Wörtern) einer Notiz auch in einer anderen steht. "
          f"Ab {DUPLICATE_CONTAINMENT:.0%} gilt sie als Dublette.")
        w("")
        for i, group in enumerate(result["duplicate_groups"], 1):
            label = "Vorlagentext-Gruppe" if len(group) > 2 else "Paar"
            w(f"**{label} {i}** ({len(group)} Notizen, bis {max(share_of[r] for r in group):.0%} gleich):")
            w("")
            for r in group:
                hint = " – von der Suche ausgenommen" if r in ignored else ""
                w(f"- {link_label(r).replace(chr(92), '')}{hint}")
            w("")
    else:
        w("Keine.")
    if result["same_names"]:
        w("")
        w("Gleiche Dateinamen in aktiven Ordnern (Links nur mit Namen sind dann mehrdeutig):")
        w("")
        for name, rels in result["same_names"]:
            w(f"- `{name}`: " + ", ".join(f"`{r}`" for r in rels))
    w("")

    w("## Notizen ohne eingehende Links")
    w("")
    if result["orphans"]:
        for rel in sorted(result["orphans"]):
            w(f"- {link_label(rel).replace(chr(92), '')}")
    else:
        w("Keine.")
    w("")

    w("## Metadaten")
    w("")
    w("Standard laut Entwicklungsplan: `quelle`, `erstellt`/`aktualisiert`, `vertrauen`, `status` (bestätigt, aktiv, entwurf, zu-prüfen, veraltet), `tags`, optional `niveau` (einstieg, vertiefung).")
    w("")
    if result["key_mix"]:
        mixes = [f"`{a}` ({result['key_mix'][a]}×) und `{b}` ({result['key_mix'][b]}×)"
                 for a, b in KEY_SYNONYMS if result["key_mix"][a] and result["key_mix"][b]]
        if mixes:
            w("Gleiche Felder, verschieden benannt: " + "; ".join(mixes) + ".")
            w("")
    if result["metadata_rows"]:
        w(f"> [!note]- {len(result['metadata_rows'])} Notizen mit fehlenden Feldern anzeigen")
        w("> | Notiz | Status | fehlt |")
        w("> | --- | --- | --- |")
        for rel, missing, status in sorted(result["metadata_rows"]):
            w(f"> | {link_label(rel)} | {md_escape(status) or '–'} | {', '.join(missing)} |")
    w("")

    w("## Große Sammelnotizen")
    w("")
    if result["large"]:
        w(f"Grenze: mehr als {LARGE_NOTE_CHARS:,} Zeichen oder mehr als {LARGE_NOTE_CHUNKS} Suchabschnitte.".replace(",", "."))
        w("")
        w("| Notiz | Zeichen | Suchabschnitte |")
        w("| --- | --- | --- |")
        for rel, size, chunks in result["large"]:
            w(f"| {link_label(rel)} | {f'{size:,}'.replace(',', '.')} | {chunks} |")
    else:
        w("Keine.")
    w("")

    w("## Generische KI-Importe")
    w("")
    if result["templates"]:
        w("Mindestens 5 der 9 Vorlagen-Überschriften (Einführung und Bedeutung, Kern-Konzepte, Aktuelle Forschung, Ethische Überlegungen …).")
        w("")
        w("| Notiz | Vorlagen-Überschriften | Status |")
        w("| --- | --- | --- |")
        for rel, hits, status in sorted(result["templates"]):
            w(f"| {link_label(rel)} | {hits} von 9 | {md_escape(status)} |")
    else:
        w("Keine.")
    w("")

    w("## Mehrdeutige Links")
    w("")
    if result["ambiguous"]:
        w("| Notiz | Link | mögliche Ziele |")
        w("| --- | --- | --- |")
        for rel, link, matches in result["ambiguous"]:
            w(f"| {link_label(rel)} | `{md_escape(link.raw)}` | {len(matches)} ({', '.join('Archiv' if is_archive(m) else 'aktiv' for m in matches)}) |")
    else:
        w("Keine.")
    w("")

    w("## Links ins Archiv")
    w("")
    if result["to_archive"]:
        w(f"{len(result['to_archive'])} Links führen ins Archiv oder Importarchiv – meist bewusst als Verweis auf den "
          "Originalimport. Wichtig erst, wenn das Archiv gelöscht werden soll.")
        w("")
        w("> [!note]- Liste anzeigen")
        for rel, link, target in result["to_archive"]:
            w(f"> - {link_label(rel).replace(chr(92), '')} → `{target}`")
    else:
        w("Keine.")
    w("")

    w("## Notizen ohne ausgehende Links")
    w("")
    if result["dead_ends"]:
        w(", ".join(link_label(r).replace(chr(92), "") for r in sorted(result["dead_ends"])))
    else:
        w("Keine.")
    w("")

    w("## Überschriften")
    w("")
    if result["structure"]:
        w("Mehrere Überschriften der Ebene 1 in einer Notiz verwirren die Aufteilung für die Suche (Titel wird falsch erkannt).")
        w("")
        for rel, issue in result["structure"]:
            w(f"- {link_label(rel).replace(chr(92), '')}: {issue}")
    else:
        w("Unauffällig.")
    w("")

    w("## Tags")
    w("")
    w(f"{result['tag_total']} verschiedene Tags.")
    if result["tag_groups"]:
        w(" Varianten, die vermutlich dasselbe meinen:")
        w("")
        for _, variants in result["tag_groups"]:
            w("- " + ", ".join(f"`{t}` ({c}×)" for t, c in variants.most_common()))
    w("")

    w("## Leere Ordner")
    w("")
    if result["empty_dirs"]:
        for d in result["empty_dirs"]:
            w(f"- `{d}`")
    else:
        w("Keine.")
    w("")

    w("## Zeichenkodierung")
    w("")
    if result["encoding"] or result["mojibake"]:
        for rel, kind in result["encoding"]:
            w(f"- `{rel}`: {kind}")
        for rel in result["mojibake"]:
            w(f"- `{rel}`: kaputte Umlaute (z. B. „Ã¤“ statt „ä“)")
    else:
        w("Alle aktiven Notizen sind sauber als UTF-8 gespeichert.")
    if result["unreadable"]:
        w("")
        w("Nicht lesbar: " + ", ".join(f"`{r}`" for r in result["unreadable"]))
    w("")
    return "\n".join(out)


def best_match(target: str, all_files: list[str]) -> str | None:
    """Vorschlag für ein kaputtes Linkziel: gleiche Datei unter anderem Pfad.
    Bei mehreren Kandidaten gewinnt der mit den meisten passenden Ordnern am Ende."""
    if not target:
        return None
    parts = [p.lower() for p in target.replace("\\", "/").split("/")]
    name = parts[-1]
    candidates = [f for f in all_files if f.rsplit("/", 1)[-1].lower() in (name, name + ".md") and not is_archive(f)]
    if not candidates:
        return None

    def score(path: str) -> int:
        cparts = [p.lower() for p in (path[:-3] if path.endswith(".md") else path).split("/")]
        n = 0
        while n < min(len(parts), len(cparts)) and parts[-1 - n] == cparts[-1 - n]:
            n += 1
        return n

    ranked = sorted(candidates, key=lambda c: (-score(c), len(c)))
    if len(ranked) > 1 and score(ranked[0]) == score(ranked[1]):
        return None  # nicht eindeutig
    return ranked[0]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    parser = argparse.ArgumentParser(description="Vault-Pflegebericht erzeugen (ändert keine Notiz)")
    parser.add_argument("--vault", default=os.getenv("VAULT_PATH"))
    parser.add_argument("--out", default=None, help=f"Zieldatei (Standard: <Vault>/{REPORT_DIR}/{REPORT_NAME})")
    parser.add_argument("--date", default=datetime.date.today().isoformat())
    parser.add_argument("--hinweis", default=None, help="zusätzliche Zeile im Info-Kasten")
    parser.add_argument("--nicht-pruefen", nargs="*", default=[], help="Notizen (Pfad im Vault), die nur als Linkziel zählen")
    args = parser.parse_args()
    if not args.vault:
        print("FEHLER: Vault-Pfad fehlt (--vault oder VAULT_PATH in .env)")
        return 2
    vault = Path(args.vault)
    out = Path(args.out) if args.out else vault / REPORT_DIR / REPORT_NAME
    try:
        report_rel = nfc(out.resolve().relative_to(vault.resolve()).as_posix())
    except ValueError:
        report_rel = ""
    result = analyse(vault, report_rel, set(args.nicht_pruefen))
    text = render(result, args.date, args.hinweis)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"Bericht geschrieben: {out}")
    print(f"  aktive Notizen: {len(result['active'])}, Links ins Leere: {len(result['broken'])}, "
          f"Dubletten-Gruppen: {len(result['duplicate_groups'])}, ohne eingehende Links: {len(result['orphans'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

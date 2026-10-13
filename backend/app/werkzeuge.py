"""
Werkzeuge für den Werkzeug-/Agenten-Modus (Phase 2, 23.09.2026).

Bisher kannte Jarvis nur ein Werkzeug (vault_suche). Jetzt:

| Werkzeug            | Schritt | Was es tut                                         | schreibt? |
|---------------------|---------|----------------------------------------------------|-----------|
| vault_suche         | 2.1/2.2 | Vault durchsuchen, optional nach Status, Ordner,   | nein      |
|                     |         | Datum filtern                                      |           |
| notiz_lesen         | 2.7     | eine Notiz nach Namen finden und lesen             | nein      |
| rechner             | 2.7     | sicher rechnen (app/alltag.py)                     | nein      |
| datum_uhrzeit       | 2.7     | heutiges Datum, Wochentag, KW, Uhrzeit             | nein      |
| termine             | 2.7     | Termine heute/morgen/an einem Tag (Google-Kalender)| nein      |
| gespraeche_suchen   | 2.6     | frühere Gespräche mit Sir durchsuchen              | nein      |
| plan_zeigen         | 2.4     | bei mehrteiligen Aufträgen erst den Plan zeigen    | nein      |
| notiz_vorschlagen   | 2.3     | Änderung ANKÜNDIGEN: legt nur einen Vorschlag an,  | erst nach |
|                     |         | Sir bestätigt im HUD                               | Freigabe  |

Alles außer der Vault-Suche kostet keinen zusätzlichen Claude-Aufruf - nur die
Werkzeug-Beschreibungen verlängern jeden Aufruf um ca. 500 Token
(Haiku-Sucher: ca. 0,05 Cent mehr je Aufruf).

Rückgabe der Werkzeuge ist immer Text für Claude. Inhalte aus Notizen und
Gesprächen stehen in Daten-Blöcken und sind nie Anweisungen.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rag.retriever import RetrievedChunk, search_many

from . import alltag, chat_service, gespraeche, vorschlaege

MAX_NOTIZ_ZEICHEN = 5000
FILTER_FAKTOR = 4  # bei Ordner-/Datumsfilter mehr Kandidaten holen und danach filtern

_DATUMSFELDER = ("fm_aktualisiert", "fm_datum", "fm_stand", "fm_erstellt", "fm_recherchiert", "fm_zuletzt_geprüft")


def _tool(name: str, beschreibung: str, eigenschaften: dict, pflicht: list[str]) -> dict:
    return {"name": name, "description": beschreibung,
            "input_schema": {"type": "object", "properties": eigenschaften, "required": pflicht}}


VAULT_SUCHE = _tool(
    "vault_suche",
    "Durchsucht Max' Obsidian-Vault (Big Brain). Suchanfrage auf Deutsch, kurz. Je Thema eine Suche. "
    "Optional filtern: status (z.B. 'bestätigt', 'entwurf'), ordner (Teil des Pfads, z.B. "
    "'04 - Trading'), seit (JJJJ-MM-TT, nur Notizen mit Datum ab dann).",
    {
        "suchanfrage": {"type": "string", "description": "z.B. 'Risiko pro Trade'"},
        "status": {"type": "string"},
        "ordner": {"type": "string"},
        "seit": {"type": "string"},
    },
    ["suchanfrage"],
)
NOTIZ_LESEN = _tool(
    "notiz_lesen",
    "Liest eine bestimmte Notiz, wenn Max sie beim Namen nennt (Titel oder Dateiname, ungefähr reicht).",
    {"name": {"type": "string"}}, ["name"],
)
RECHNER = _tool(
    "rechner", "Rechnet einen Ausdruck exakt aus, z.B. '10000 * 0.01 / 25' oder '15 % von 240'.",
    {"ausdruck": {"type": "string"}}, ["ausdruck"],
)
DATUM_UHRZEIT = _tool("datum_uhrzeit", "Heutiges Datum, Wochentag, Kalenderwoche und Uhrzeit (Europe/Berlin).", {}, [])
TERMINE = _tool(
    "termine", "Termine aus Max' Google-Kalender. tag: 'heute', 'morgen' oder JJJJ-MM-TT.",
    {"tag": {"type": "string"}}, [],
)
GESPRAECHE_SUCHEN = _tool(
    "gespraeche_suchen",
    "Durchsucht frühere Gespräche zwischen Max und Auron (z.B. frühere Entscheidungen). Stichwörter angeben.",
    {"suchbegriff": {"type": "string"}}, ["suchbegriff"],
)
PLAN_ZEIGEN = _tool(
    "plan_zeigen",
    "Bei Aufträgen mit mehreren Schritten ZUERST aufrufen: zeigt Max den Plan (2-6 kurze Schritte). "
    "Danach nur lesende Werkzeuge nutzen.",
    {"schritte": {"type": "array", "items": {"type": "string"}}}, ["schritte"],
)
NOTIZ_VORSCHLAGEN = _tool(
    "notiz_vorschlagen",
    "Kündigt eine Änderung im Vault an, wenn Max etwas festhalten oder ergänzen will. Schreibt NICHT "
    "selbst: Max bestätigt im HUD. ziel = Pfad der Notiz im Vault (leer = Eingangs-Notiz 'Gemerkt').",
    {"text": {"type": "string"}, "ziel": {"type": "string"}, "grund": {"type": "string"}},
    ["text"],
)

# 27.09.2026: Alltagsfunktionen auch im Werkzeug-Modus (Claude entscheidet selbst)
INTERNET_RECHERCHE = _tool(
    "internet_recherche",
    "Sucht im Internet (höchstens 3 Websuchen, ca. 5-10 Cent). NUR wenn Max ausdrücklich eine Recherche, "
    "aktuelle Infos, Preise oder Vergleiche aus dem Internet will.",
    {"frage": {"type": "string"}}, ["frage"],
)
MINDMAP = _tool(
    "mindmap",
    "Erstellt eine neue Mind Map (Obsidian-Karte im Vault) oder ergänzt eine vorhandene. Für neue: thema. "
    "Zum Ergänzen: name der vorhandenen Karte und auftrag (was dazu soll). Kostet ca. 2-4 Cent.",
    {"thema": {"type": "string"}, "name": {"type": "string"}, "auftrag": {"type": "string"}}, [],
)
PROJEKT = _tool(
    "projekt",
    "Plant ein Projekt mit Max: legt eine Projektnotiz mit Ziel, Schritten, Risiken, Rückfragen und Mind Map an "
    "(beschreibung) oder überarbeitet ein vorhandenes (name + info). Ca. 3-5 Cent.",
    {"beschreibung": {"type": "string"}, "name": {"type": "string"}, "info": {"type": "string"}}, [],
)
PC_STEUERN = _tool(
    "pc_steuern",
    "Steuert Max' Haupt-PC (Windows). aktion: programm (ziel z.B. chrome, obsidian, spotify, metatrader, explorer, "
    "rechner, editor, word, excel, vscode), ordner (downloads, dokumente, desktop, bilder, ki, jarvis, ablage, vault), "
    "url (ziel https-Adresse), lauter, leiser, stumm, medien (play_pause/naechster/vorheriger), sperren, "
    "bildschirm_aus. Herunterfahren und Neustart gehen hier NICHT - dafür soll Max 'Fahr den PC herunter' sagen.",
    {"aktion": {"type": "string"}, "ziel": {"type": "string"}}, ["aktion"],
)
DATEI_UMWANDELN = _tool(
    "datei_umwandeln",
    "Wandelt eine Datei aus der Datei-Ablage um (0 Cent): PDF -> png/jpg/txt, Bild -> png/jpg/webp/pdf. "
    "datei = Dateiname (leer = neueste Datei), ziel = Zielformat.",
    {"datei": {"type": "string"}, "ziel": {"type": "string"}}, ["ziel"],
)
TERMIN_VORBEREITEN = _tool(
    "termin_vorbereiten",
    "Bereitet einen Kalendertermin vor (Link zum Eintragen in Google Kalender, oder direkt, wenn eingerichtet). "
    "satz = Termin in einem Satz mit Tag und Uhrzeit, z.B. 'Zahnarzt Dienstag 10 Uhr'.",
    {"satz": {"type": "string"}}, ["satz"],
)

ALLE = [VAULT_SUCHE, NOTIZ_LESEN, RECHNER, DATUM_UHRZEIT, TERMINE, GESPRAECHE_SUCHEN, PLAN_ZEIGEN, NOTIZ_VORSCHLAGEN,
        INTERNET_RECHERCHE, MINDMAP, PROJEKT, PC_STEUERN, DATEI_UMWANDELN, TERMIN_VORBEREITEN]
NAMEN = {t["name"] for t in ALLE}

PROMPT_ZUSATZ = """

Weitere Werkzeuge (Phase 2): notiz_lesen (Notiz beim Namen lesen), rechner (exakt rechnen \
statt schätzen), datum_uhrzeit, termine (Kalender), gespraeche_suchen (frühere Gespräche und \
Entscheidungen), plan_zeigen (bei Aufträgen mit mehreren Schritten zuerst den Plan zeigen), \
notiz_vorschlagen (wenn Max etwas festhalten will - das schreibt nicht selbst, Max bestätigt \
im HUD; sag ihm, dass der Vorschlag zur Freigabe bereitliegt). Löschen oder Überschreiben \
von Notizen gibt es nicht.
Seit 27.09.2026 außerdem: internet_recherche (nur auf ausdrücklichen Wunsch), mindmap, projekt, \
pc_steuern, datei_umwandeln, termin_vorbereiten. Übernimm deren Ergebnis (Links, Pfade, Kosten) in \
deine Antwort."""


@dataclass
class Kontext:
    """Zustand über alle Werkzeugaufrufe EINER Frage."""
    top_k: int = chat_service.DEFAULT_TOP_K
    status: str | None = None
    cited: list[RetrievedChunk] = field(default_factory=list)
    number_of: dict[str, int] = field(default_factory=dict)
    best_similarities: list[float] = field(default_factory=list)
    searches: int = 0
    ereignisse: list[dict] = field(default_factory=list)   # fürs HUD (Plan, Vorschlag)
    extra_texte: list[str] = field(default_factory=list)   # Nicht-Such-Ergebnisse für den Antworter
    suche: Any = None  # Suchfunktion (agent_service reicht seine eigene durch - Tests ersetzen sie)


def _datum_der_notiz(meta: dict) -> str | None:
    for feld in _DATUMSFELDER:
        wert = meta.get(feld)
        if wert:
            return str(wert)[:10]
    return None


def filter_anwenden(hits: list[RetrievedChunk], ordner: str | None, seit: str | None) -> list[RetrievedChunk]:
    ergebnis = hits
    if ordner:
        o = ordner.strip().lower().replace("\\", "/")
        ergebnis = [h for h in ergebnis if o in h.file_path.lower().replace("\\", "/")]
    if seit and re.match(r"^\d{4}-\d{2}-\d{2}$", seit.strip()):
        grenze = seit.strip()
        ergebnis = [h for h in ergebnis if (_datum_der_notiz(h.metadata or {}) or "") >= grenze]
    return ergebnis


def vault_suchen(eingabe: dict, k: Kontext) -> str:
    query = str(eingabe.get("suchanfrage", "")).strip()
    if not query:
        return "Ungültiger Aufruf: 'suchanfrage' fehlt."
    status = (eingabe.get("status") or k.status or "").strip() or None
    ordner = (eingabe.get("ordner") or "").strip() or None
    seit = (eingabe.get("seit") or "").strip() or None
    where = {"fm_status": status} if status else None
    anzahl = k.top_k * (FILTER_FAKTOR if (ordner or seit) else 1)
    k.searches += 1
    suchfunktion = k.suche or search_many
    hits = filter_anwenden(suchfunktion([(query, 1.0)], top_k=anzahl, where=where), ordner, seit)[: k.top_k]
    if hits:
        k.best_similarities.append(max(h.raw_similarity for h in hits))
    numbered = []
    for hit in hits:
        if hit.id not in k.number_of:
            k.cited.append(hit)
            k.number_of[hit.id] = len(k.cited)
        numbered.append((k.number_of[hit.id], hit))
    if not numbered:
        filter_txt = ", ".join(f"{n}={w}" for n, w in (("status", status), ("ordner", ordner), ("seit", seit)) if w)
        return f"Keine Treffer im Vault für: {query}" + (f" (Filter: {filter_txt})" if filter_txt else "")
    kontext = chat_service.build_context([h for _, h in numbered], [n for n, _ in numbered])
    if chat_service.is_low_confidence([h for _, h in numbered]):
        kontext = ("Hinweis: Diese Treffer passen inhaltlich nur schwach zur Suchanfrage. "
                   "Verwende sie nur, wenn sie die Frage wirklich beantworten.\n\n" + kontext)
    return kontext


def _vault_notizen() -> list[Path]:
    try:
        basis = vorschlaege.vault_pfad()
    except vorschlaege.VorschlagFehler:
        return []
    return [p for p in basis.rglob("*.md") if not any(t.startswith(".") for t in p.relative_to(basis).parts)]


def _normal(text: str) -> str:
    return re.sub(r"[^a-z0-9äöüß]+", " ", (text or "").lower()).strip()


def notiz_finden(name: str) -> Path | None:
    """Bester Treffer nach Dateiname: exakt > enthält > gemeinsame Wörter."""
    gesucht = _normal(name)
    if not gesucht:
        return None
    worte = set(gesucht.split())
    bester, punkte_bester = None, 0.0
    for pfad in _vault_notizen():
        stamm = _normal(pfad.stem)
        stamm_ohne_nr = re.sub(r"^\d+\s+", "", stamm)
        if gesucht in (stamm, stamm_ohne_nr):
            return pfad
        if gesucht in stamm:
            punkte = 0.9 - len(stamm) / 1000
        else:
            gemeinsam = worte & set(stamm.split())
            punkte = len(gemeinsam) / max(len(worte), 1) * 0.8
        if punkte > punkte_bester:
            bester, punkte_bester = pfad, punkte
    return bester if punkte_bester >= 0.5 else None


def notiz_lesen(eingabe: dict, k: Kontext) -> str:
    pfad = notiz_finden(str(eingabe.get("name", "")))
    if pfad is None:
        return f"Keine Notiz gefunden, die '{eingabe.get('name', '')}' heißt."
    rel = str(pfad.relative_to(vorschlaege.vault_pfad())).replace("\\", "/")
    text = pfad.read_text(encoding="utf-8", errors="replace")
    gekuerzt = len(text) > MAX_NOTIZ_ZEICHEN
    text = chat_service._neutralize_tags(text[:MAX_NOTIZ_ZEICHEN])  # noqa: SLF001
    k.ereignisse.append({"typ": "werkzeug", "werkzeug": "notiz_lesen", "notiz": rel})
    return (f'<retrieved_documents>\n<document index="notiz">\nQuelle: {rel} (ganze Notiz'
            f'{", gekürzt" if gekuerzt else ""})\n{text}\n</document>\n</retrieved_documents>')


def rechner(eingabe: dict, k: Kontext) -> str:
    try:
        wert = alltag.rechnen(str(eingabe.get("ausdruck", "")))
    except alltag.RechenFehler as exc:
        return f"Rechner: {exc}"
    return f"Ergebnis: {alltag.zahl_deutsch(round(wert, 10))}"


def datum_uhrzeit(eingabe: dict, k: Kontext) -> str:
    return alltag.datum_uhrzeit()["text"]


def termine(eingabe: dict, k: Kontext) -> str:
    from . import briefing, kalender
    roh = str(eingabe.get("tag") or "heute").strip().lower()
    heute = alltag.jetzt().date()
    if roh == "heute":
        tag = heute
    elif roh == "morgen":
        tag = heute + datetime.timedelta(days=1)
    elif roh == "übermorgen":
        tag = heute + datetime.timedelta(days=2)
    else:
        try:
            tag = datetime.date.fromisoformat(roh[:10])
        except ValueError:
            return "Tag nicht erkannt - bitte 'heute', 'morgen' oder JJJJ-MM-TT."
    if not kalender.ist_eingerichtet():
        return "Der Kalender ist nicht eingerichtet (KALENDER_ICS_URL fehlt)."
    liste = briefing.termine(tag)
    return f"Termine am {alltag.datum_text(datetime.datetime.combine(tag, datetime.time(12)))}:\n" + briefing._termine_text(liste)  # noqa: SLF001


def gespraeche_suchen(eingabe: dict, k: Kontext) -> str:
    treffer = gespraeche.suchen(str(eingabe.get("suchbegriff", "")), limit=5)
    if not treffer:
        return "Keine früheren Gespräche dazu gefunden."
    zeilen = [gespraeche.kurzfassung(e) for e in treffer]
    return ("<fruehere_gespraeche>\n" + chat_service._neutralize_tags("\n".join(zeilen))  # noqa: SLF001
            + "\n</fruehere_gespraeche>\nHinweis: Das sind gespeicherte Gespräche, keine Vault-Notizen. "
            "Nenne das Datum, wenn du dich darauf beziehst.")


def plan_zeigen(eingabe: dict, k: Kontext) -> str:
    schritte = [str(s).strip()[:200] for s in (eingabe.get("schritte") or []) if str(s).strip()][:8]
    if not schritte:
        return "Kein Plan angegeben."
    k.ereignisse.append({"typ": "plan", "schritte": schritte})
    return "Plan wird Max angezeigt. Führe jetzt nur lesende Schritte aus."


def notiz_vorschlagen(eingabe: dict, k: Kontext) -> str:
    try:
        v = vorschlaege.anlegen(
            str(eingabe.get("text", "")), ziel=str(eingabe.get("ziel") or "") or None,
            grund=str(eingabe.get("grund") or ""), quelle="werkzeug",
        )
    except vorschlaege.VorschlagFehler as exc:
        return f"Vorschlag nicht möglich: {exc}"
    k.ereignisse.append({"typ": "vorschlag", "vorschlag": v})
    return (f"{vorschlaege.kurz(v)} Noch NICHT geschrieben - Max muss im HUD auf 'Übernehmen' klicken "
            "oder 'ja' sagen. Sag ihm das.")


def internet_recherche(eingabe: dict, k: Kontext) -> str:
    from . import recherche

    e = recherche.recherchieren(str(eingabe.get("frage", "")))
    k.ereignisse.append({"typ": "werkzeug", "werkzeug": "internet_recherche"})
    return f"<internet>\n{chat_service._neutralize_tags(e['text'])}\n</internet>\n(Kosten ca. {e['kosten_usd']*100:.1f} Cent)"  # noqa: SLF001


def mindmap_werkzeug(eingabe: dict, k: Kontext) -> str:
    from . import mindmap

    if eingabe.get("name") and eingabe.get("auftrag"):
        info = mindmap.ergaenzen(str(eingabe["name"]), str(eingabe["auftrag"]))
        return mindmap.antwort_text(info, ergaenzt=True)
    return mindmap.antwort_text(mindmap.erstellen(str(eingabe.get("thema") or eingabe.get("auftrag") or "")))


def projekt_werkzeug(eingabe: dict, k: Kontext) -> str:
    from . import projekte

    if eingabe.get("name") and eingabe.get("info"):
        return projekte.antwort_text(projekte.ueberarbeiten(str(eingabe["name"]), str(eingabe["info"])))
    return projekte.antwort_text(projekte.anlegen(str(eingabe.get("beschreibung") or "")))


def pc_steuern(eingabe: dict, k: Kontext) -> str:
    from . import hauptpc

    aktion = str(eingabe.get("aktion", "")).strip().lower()
    if hauptpc.stufe(aktion) != 0:
        return "Diese Aktion (Herunterfahren, Neustart, Sperren, feste Befehle) läuft nur per direktem Befehl von Sir, bei Stufe 2 mit Rückfrage."
    return hauptpc.ausfuehren({"aktion": aktion, "ziel": eingabe.get("ziel")})


def datei_umwandeln(eingabe: dict, k: Kontext) -> str:
    from . import umwandeln

    datei = str(eingabe.get("datei") or "").strip() or None
    return umwandeln.antwort({"ziel": str(eingabe.get("ziel", "")), "datei": datei})


def termin_vorbereiten(eingabe: dict, k: Kontext) -> str:
    from . import planung

    return planung.termin_eintragen(str(eingabe.get("satz", "")))


AUSFUEHRER = {
    "internet_recherche": internet_recherche, "mindmap": mindmap_werkzeug, "projekt": projekt_werkzeug,
    "pc_steuern": pc_steuern, "datei_umwandeln": datei_umwandeln, "termin_vorbereiten": termin_vorbereiten,
    "vault_suche": vault_suchen, "notiz_lesen": notiz_lesen, "rechner": rechner,
    "datum_uhrzeit": datum_uhrzeit, "termine": termine, "gespraeche_suchen": gespraeche_suchen,
    "plan_zeigen": plan_zeigen, "notiz_vorschlagen": notiz_vorschlagen,
}


def ausfuehren(name: str, eingabe: Any, k: Kontext, max_suchen: int) -> str:
    """Ein Werkzeug ausführen. Fehler werden als Text an Claude zurückgegeben."""
    if name not in AUSFUEHRER:
        return f"Unbekanntes Werkzeug: {name}"
    eingabe = eingabe if isinstance(eingabe, dict) else {}
    if name == "vault_suche" and k.searches >= max_suchen:
        return "Suchlimit erreicht. Antworte jetzt mit den bisherigen Ergebnissen."
    try:
        ergebnis = AUSFUEHRER[name](eingabe, k)
    except Exception as exc:  # noqa: BLE001 - ein Werkzeug darf die Antwort nicht verhindern
        ergebnis = f"Werkzeug {name} fehlgeschlagen: {exc}"
    if name not in ("vault_suche", "plan_zeigen"):
        k.extra_texte.append(f"[{name}] {ergebnis}")
    return ergebnis

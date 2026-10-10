"""
Ablauf einer Chat-Anfrage (23.09.2026) - aus app/routes.py herausgezogen,
damit er ohne FastAPI testbar ist. routes.chat_stream() macht daraus nur noch
Server-Sent-Events.

Reihenfolge:
1. Absicht erkennen (app/alltag.py, OHNE Claude, 0 Kosten):
   - "ja"/"nein" auf einen offenen Vorschlag -> übernehmen/verwerfen
   - Uhrzeit, Datum, reine Rechnung -> sofortige Antwort
   - Kursfrage ("Wie steht Gold?") -> Kurs aus app/marktdaten.py (seit 26.09.2026)
   - Trading-Tagebuch ("Gold Long bei 3740, Stopp 3720") -> app/tagebuch.py (seit 26.09.2026)
   - "Zeig mir den Markt", "stopp" -> HUD-Befehl (Seite wechseln, still sein)
   - "Merk dir ..." / "Notiere ..." -> Vorschlag anlegen (Phase 2.3)
   - "Speicher die Seite https://..." -> Webseiten-Vorschlag
2. Musikbefehle (app/spotify.py, wie bisher, 0 Kosten)
3. Sonst: klassisch, Werkzeug oder Werkzeug+Agenten (wie bisher), jetzt mit
   wählbarem Modell (z.B. Opus 5.5) und Antwortlänge.
4. Jeder Austausch wird gespeichert (app/gespraeche.py, Phase 2.6) - das HUD
   bekommt die ID ("antwort_id") für Bewerten und Prüfen.

Ereignisse zusätzlich zu den bisherigen (text/quellen/fertig/fehler/agent/token):
    {"typ": "hud", "aktion": "seite"|"stumm", "seite": ...}
    {"typ": "vorschlag", "vorschlag": {...}}          - wartet auf Freigabe
    {"typ": "vorschlag_erledigt", "vorschlag": {...}} - übernommen/verworfen
    {"typ": "plan", "schritte": [...]}
    {"typ": "antwort_id", "id": "..."}
    {"typ": "kanarienvogel", "text": "..."}          - Antwort ohne "Sir" (Regel-Warnung)
"""

from __future__ import annotations

import datetime
import re
import time
from typing import Any, Iterator

from . import (agent_service, alltag, chat_service, gespraeche, hauptpc, ki_aufruf, marktdaten, nachtauftraege,
               spotify, tagebuch, tagesfrage, vorschlaege, webseite)
from .schemas import ChatRequest

TAGESNOTIZ_MODELL = agent_service.TOOL_MODEL


def _direkt(text: str, extra: list[dict] | None = None) -> Iterator[dict]:
    for e in extra or []:
        yield e
    if text:
        yield {"typ": "text", "text": text}
    yield {"typ": "quellen", "quellen": [], "vault": False}


def _absicht_ausfuehren(a: dict) -> Iterator[dict]:
    art = a.get("art")
    if art == "antwort":
        yield from _direkt(a["text"])
    elif art == "hud":
        yield from _direkt(a.get("text", ""), [{"typ": "hud", "aktion": a["aktion"], "seite": a.get("seite")}])
    elif art == "bestaetigung":
        try:
            if a["ja"]:
                v = vorschlaege.uebernehmen(a["vorschlag"])
                text = f'Erledigt, Sir. Eingetragen in "{v["ziel"]}".'
            else:
                v = vorschlaege.verwerfen(a["vorschlag"])
                text = "Verworfen, Sir. Im Vault wurde nichts geändert."
            yield from _direkt(text, [{"typ": "vorschlag_erledigt", "vorschlag": v}])
        except (KeyError, vorschlaege.VorschlagFehler) as exc:
            yield from _direkt(f"Das ging nicht, Sir: {exc}")
    elif art == "diktat":
        try:
            v = vorschlaege.anlegen(a["text"], grund="Diktat", quelle="diktat")
        except vorschlaege.VorschlagFehler as exc:
            yield from _direkt(f"Das konnte ich nicht vormerken, Sir: {exc}")
            return
        text = (f'Soll ich das in "{v["titel"]}" eintragen, Sir? Sagen Sie "ja" oder klicken Sie auf '
                f'"Übernehmen". Bis dahin ist nichts geschrieben.')
        yield from _direkt(text, [{"typ": "vorschlag", "vorschlag": v}])
    elif art == "kurs":
        # 26.09.2026: Kurse nie aus dem Modellwissen - frisch aus app/marktdaten.py, 0 Cent
        try:
            text = marktdaten.kurs_antwort(a["symbol"], euro=a.get("euro", False))
        except Exception as exc:  # noqa: BLE001 - Netz, Datenbank: freundlich melden statt abbrechen
            text = (f"Den Kurs konnte ich gerade nicht holen, Sir ({exc}). Auf der Seite Markt steht der "
                    "zuletzt gespeicherte Stand.")
        yield from _direkt(text)
    elif art == "tagebuch":
        # 26.09.2026: Trading-Tagebuch per Chat/Sprache, 0 Cent
        try:
            if a["aktion"] == "eintragen":
                text = tagebuch.satz_eingetragen(tagebuch.eintragen(
                    a["symbol"], a["richtung"], a["einstieg"], a["stopp"], a.get("ziel"), a.get("grund", ""),
                    a.get("risiko_eur")))
            elif a["aktion"] == "schliessen":
                text = tagebuch.schliessen(a.get("id"), a.get("ausstieg"), symbol=a.get("symbol"),
                                           art=a.get("zu_art"), eur=a.get("eur"))["text"]
            else:
                text = tagebuch.satz_auswertung(a.get("tage"))
        except tagebuch.TagebuchFehler as exc:
            text = f"Das konnte ich nicht ins Tagebuch schreiben, Sir: {exc}"
        yield from _direkt(text)
    elif art == "nachtauftrag":
        yield from _direkt(_nachtauftrag(a))
    elif art == "tagesfrage":
        yield from _direkt(_tagesfrage(a))
    elif art in NEUE_ARTEN:
        # 27.09.2026: PC, Schreiben, Recherche, Mind Maps, Projekte, Termine, Umwandeln
        ergebnis = _neue_art(a)
        if isinstance(ergebnis, tuple):
            yield from _direkt(*ergebnis)
        else:
            yield from _direkt(ergebnis)
    elif art == "webseite":
        try:
            v = webseite.als_vorschlag(a["url"])
        except (webseite.WebseitenFehler, vorschlaege.VorschlagFehler) as exc:
            yield from _direkt(f"Die Seite konnte ich nicht speichern, Sir: {exc}")
            return
        yield from _direkt(
            f'Ich habe die Seite gelesen, Sir. Soll ich sie als Notiz "{v["titel"]}" anlegen? '
            'Sagen Sie "ja" oder klicken Sie auf "Übernehmen".',
            [{"typ": "vorschlag", "vorschlag": v}],
        )


NEUE_ARTEN = ("pc", "whatsapp", "schreiben", "recherche", "recherche_speichern", "mindmap", "projekt", "termin", "tagesplan",
              "umwandeln", "sucher_schreiber")


def _neue_art(a: dict) -> str | tuple[str, list[dict]]:
    """Neue Alltagsfunktionen (27.09.2026). Fehler kommen als freundlicher Satz zurück."""
    from . import agenten, mindmap, planung, projekte, recherche, schreiben, umwandeln, whatsapp

    art = a["art"]
    try:
        if art == "pc":
            return hauptpc.ausfuehren(a)
        if art == "whatsapp":
            if a["aktion"] == "kontakt":
                k = whatsapp.kontakt_speichern(a["name"], a["nummer"])
                return f"Gemerkt, Sir: {k['name']} (+{k['nummer']}). WhatsApp-Links an {k['name']} gehen jetzt direkt an diese Nummer."
            if a["aktion"] == "liste":
                return whatsapp.liste_text()
            return whatsapp.direkt(a["name"], a["text"])
        if art == "schreiben":
            e = schreiben.schreiben(a["auftrag"], a.get("was", "text"))
            return f"{e['text']}\n\n*Kosten ca. {ki_aufruf.cent(e['kosten_usd'])}.*"
        if art == "recherche":
            e = recherche.recherchieren(a["frage"])
            return (f"{e['text']}\n\n*Websuche ({e['suchen']} Suchen), Kosten ca. {ki_aufruf.cent(e['kosten_usd'])}. "
                    "\"Speicher die Recherche\" legt sie als Notiz an.*")
        if art == "sucher_schreiber":
            # 10.10.2026: Sucher (Haiku) sammelt Rohmaterial, Schreiber formuliert (app/agenten.py)
            e = agenten.sucher_und_schreiber(a["frage"], internet=a.get("internet", False))
            wo = "Vault und Internet" if a.get("internet") else "Vault"
            return f"{e['text']}\n\n*Sucher und Schreiber ({wo}), Kosten ca. {ki_aufruf.cent(e['kosten_usd'])}.*"
        if art == "recherche_speichern":
            v = recherche.letzte_speichern()
            return (f'Soll ich die Recherche als Notiz "{v["titel"]}" in "{recherche.ORDNER}" anlegen, Sir? '
                    'Sagen Sie "ja" oder klicken Sie auf "Übernehmen".', [{"typ": "vorschlag", "vorschlag": v}])
        if art == "mindmap":
            if a["aktion"] == "liste":
                alle = mindmap.liste()
                if not alle:
                    return "Noch keine Mind Maps, Sir. Sagen Sie z. B. \"Mind Map: Mein neuer Job\"."
                return "Ihre Mind Maps, Sir:\n\n" + "\n".join(
                    f"- [{e['titel']}]({e['obsidian']}) ({e['geaendert'].replace('T', ' ')})" for e in alle[:25])
            if a["aktion"] == "ergaenzen":
                return mindmap.antwort_text(mindmap.ergaenzen(a["name"], a["text"]), ergaenzt=True)
            return mindmap.antwort_text(mindmap.erstellen(a["thema"]))
        if art == "projekt":
            if a["aktion"] == "liste":
                return projekte.liste_text()
            if a["aktion"] == "zeigen":
                return projekte.projekt_text(a["name"])
            if a["aktion"] == "ergaenzen":
                return projekte.antwort_text(projekte.ueberarbeiten(a["name"], a["text"]))
            return projekte.antwort_text(projekte.anlegen(a["text"]))
        if art == "termin":
            return planung.termin_eintragen(a["text"])
        if art == "tagesplan":
            return planung.tagesplan(a["text"])
        if art == "umwandeln":
            return umwandeln.antwort(a)
    except (ki_aufruf.KiFehler, mindmap.MindmapFehler, projekte.ProjektFehler, umwandeln.UmwandelFehler,
            vorschlaege.VorschlagFehler, hauptpc.HauptPcFehler, whatsapp.WhatsAppFehler) as exc:
        return f"Das ging nicht, Sir: {exc}"
    return "Das kann ich noch nicht, Sir."


def _fragen_text(fragen: list[str]) -> str:
    return "\n".join(f"- {f}" for f in fragen)


def _nachtauftrag(a: dict) -> str:
    """Nachtaufträge per Chat (26.09.2026). Anlegen prüft die Klarheit (Haiku, ca. 0,1 Cent)."""
    aktion = a.get("aktion")
    try:
        if aktion == "anlegen":
            n = nachtauftraege.anlegen(a["text"], quelle="chat")
            if n["status"] == "rueckfrage":
                return (f"Bevor ich das heute Nacht angehe, Sir, kurz nachgefragt (Auftrag Nr. {n['id']}):\n"
                        f"{_fragen_text(n['rueckfragen'])}\n\nAntworten Sie einfach in Ihrer nächsten Nachricht. "
                        "\"abbrechen\" verwirft den Auftrag.")
            return (f"Notiert, Sir: Auftrag Nr. {n['id']} ({n['art']}) \"{n['titel']}\" läuft heute Nacht. "
                    "Sonnet arbeitet, Opus prüft, das Ergebnis steht morgen im Briefing.")
        if aktion == "antwort":
            n = nachtauftraege.beantworten(a["nr"], a["text"])
            return f"Danke, Sir. Auftrag Nr. {n['id']} \"{n['titel']}\" steht jetzt für heute Nacht bereit."
        if aktion == "freigeben":
            n = nachtauftraege.freigeben(a["nr"])
            return f"Freigegeben, Sir: Auftrag Nr. {n['id']} \"{n['titel']}\" läuft in der nächsten Nacht."
        if aktion == "verwerfen":
            n = nachtauftraege.verwerfen(a["nr"])
            return f"Verworfen, Sir: Auftrag Nr. {n['id']} \"{n['titel']}\"."
        teile = []
        for status, kopf in (("offen", "Geplant für die nächste Nacht"), ("rueckfrage", "Wartet auf Ihre Antwort"),
                             ("vorschlag", "Vorschläge von mir, warten auf Freigabe")):
            eintraege = nachtauftraege.liste(status)
            if eintraege:
                teile.append(f"**{kopf}:**\n" + "\n".join("- " + nachtauftraege.kurzliste(x) for x in eintraege))
        return "\n\n".join(teile) + "\n\nSir, das ist der Stand." if teile else \
            "Für heute Nacht liegt noch kein Auftrag vor, Sir. Sagen Sie z. B. \"Heute Nacht: recherchiere ...\"."
    except nachtauftraege.NachtauftragFehler as exc:
        return f"Das ging nicht, Sir: {exc}"


def _tagesfrage(a: dict) -> str:
    try:
        if a.get("aktion") == "antwort":
            e = tagesfrage.beantworten(a["text"])
            wo = f' Eingetragen in "{e["vault"]}".' if e.get("vault") else ""
            return f"Danke, Sir, das merke ich mir.{wo}"
        e = tagesfrage.heute()
        if e.get("antwort"):
            return f"Die heutige Frage haben Sie schon beantwortet, Sir: {e['frage']} – {e['antwort']}"
        return f"{e['frage']}\n\nAntworten Sie mit \"Antwort: ...\", Sir, dann trage ich es in \"{tagesfrage.VAULT_NOTIZ}\" ein."
    except ValueError as exc:
        return f"Das ging nicht, Sir: {exc}"


_ABBRECHEN = re.compile(r"^\s*(?:abbrechen|vergiss\s+(?:es|das)|verwerfen|doch\s+nicht|lass\s+(?:es|das))\b[\s.!]*$", re.I)


def _rueckfrage_antwort(message: str) -> str | None:
    """Wartet ein per Chat angelegter Nachtauftrag auf Antwort (höchstens 30 Min.),
    gilt die nächste Nachricht als Antwort - außer Smalltalk wie "danke"."""
    offen = nachtauftraege.offene_chat_rueckfrage()
    if not offen or chat_service.ist_smalltalk(message):
        return None
    if _ABBRECHEN.match(message):
        nachtauftraege.verwerfen(offen["id"])
        return f"Verworfen, Sir: Auftrag Nr. {offen['id']}."
    n = nachtauftraege.beantworten(offen["id"], message)
    return f"Danke, Sir. Auftrag Nr. {n['id']} \"{n['titel']}\" steht jetzt für heute Nacht bereit."


def _inner(request: ChatRequest, modell: str | None, laenge: str | None) -> Iterator[dict]:
    """Die eigentliche Antwort - Absicht, Musik oder Claude."""
    # 27.09.2026: "ja"/"nein" auf eine offene Rückfrage zum Herunterfahren/Neustart des Haupt-PCs
    pc_antwort = hauptpc.bestaetigung(request.message)
    if pc_antwort:
        yield {"typ": "_modus", "modus": "direkt"}
        yield from _direkt(pc_antwort)
        yield {"typ": "fertig"}
        return
    a = alltag.absicht(request.message, request.offener_vorschlag)
    if a and a.get("art") == "briefing":
        # 05.10.2026: echtes Briefing (Tagesnotiz, Termine, Kosten, Mails, Nacht) statt Vault-Suche
        yield {"typ": "_modus", "modus": "briefing"}
        from . import briefing

        try:
            b = briefing.hole(nur_claude=chat_service.claude_erzwungen(modell))
            yield from _direkt(b["text"])
            if b.get("ki"):
                yield {"typ": "ki", **b["ki"]}
        except Exception as exc:  # noqa: BLE001 - freundlich melden statt abbrechen
            yield from _direkt(f"Das Briefing ging gerade nicht, Sir: {exc}")
        yield {"typ": "fertig"}
        return
    if a:
        yield {"typ": "_modus", "modus": "direkt"}
        yield from _absicht_ausfuehren(a)
        yield {"typ": "fertig"}
        return

    # Antwort auf eine Rückfrage zu einem Nachtauftrag (26.09.2026, 0 Kosten)
    try:
        rueck = _rueckfrage_antwort(request.message)
    except nachtauftraege.NachtauftragFehler:
        rueck = None
    if rueck:
        yield {"typ": "_modus", "modus": "direkt"}
        yield from _direkt(rueck)
        yield {"typ": "fertig"}
        return

    # Musikbefehle zuerst, ohne Claude (siehe app/spotify.py)
    befehl = spotify.erkenne_befehl(request.message) if spotify.ist_eingerichtet() else None
    if befehl:
        yield {"typ": "_modus", "modus": "musik"}
        try:
            antwort = spotify.ausfuehren(befehl)
        except spotify.SpotifyFehler as exc:
            antwort = f"Das hat nicht geklappt, Sir: {exc}"
        yield from _direkt(antwort)
        yield {"typ": "fertig"}
        return

    # Smalltalk (26.09.2026): ohne Vault-Suche, ein kurzer Aufruf mit Persönlichkeit -
    # in jedem Modus, weil Werkzeuge und Agenten dafür nur Geld kosten würden.
    if chat_service.ist_smalltalk(request.message):
        yield {"typ": "_modus", "modus": "smalltalk"}
        yield from chat_service.smalltalk_stream(request.message, history=request.history, modell=modell)
        return

    modus = chat_service.resolve_mode(request.mode)
    if modus == "werkzeug" and request.agenten:
        yield {"typ": "_modus", "modus": "werkzeug+agenten"}
        yield from agent_service.ask_with_tools_stream(
            request.message, top_k=request.top_k, status=request.status, history=request.history,
            modell=modell, laenge=laenge,
        )
        return

    if modus == "werkzeug":
        yield {"typ": "_modus", "modus": "werkzeug"}
        try:
            ergebnis = chat_service.ask(
                request.message, top_k=request.top_k, status=request.status, history=request.history,
                mode="werkzeug", modell=modell, laenge=laenge,
            )
        except RuntimeError as exc:
            yield {"typ": "fehler", "text": str(exc)}
            return
        except Exception as exc:  # noqa: BLE001 - Stream sauber beenden statt abzubrechen
            yield {"typ": "fehler", "text": f"Fehler bei der Anfrage an Claude: {exc}"}
            return
        for e in getattr(ergebnis, "ereignisse", None) or []:
            yield e
        yield {"typ": "text", "text": ergebnis.answer}
        yield {"typ": "quellen", "quellen": [s.model_dump() for s in ergebnis.sources], "vault": ergebnis.used_vault}
        yield {"typ": "fertig"}
        return

    yield {"typ": "_modus", "modus": "klassisch"}
    if modell or laenge:
        yield from chat_service.ask_stream(
            request.message, top_k=request.top_k, status=request.status, history=request.history,
            modell=modell, laenge=laenge,
        )
    else:
        yield from chat_service.ask_stream(
            request.message, top_k=request.top_k, status=request.status, history=request.history
        )


CLAUDE_MODI = ("klassisch", "werkzeug", "werkzeug+agenten", "smalltalk")
_SIR_RE = re.compile(r"\bSir\b")
KANARIE_TEXT = ('Hinweis: In dieser Antwort fehlt "Sir". Das ist das Warnzeichen, dass Auron seine '
                'Regeln nicht mehr sicher befolgt (meist bei langem Verlauf). "Verlauf leeren" startet frisch.')


def kanarienvogel(modus: str | None, antwort: str) -> bool:
    """True, wenn eine Claude-Antwort ohne "Sir" kam (TikTok-Idee "Canary", 23.09.2026).
    Jarvis soll Sir in jeder Antwort ansprechen - fehlt es, hat Claude mindestens eine
    Regel fallen lassen. Kostet nichts, prüft nur den fertigen Text."""
    return modus in CLAUDE_MODI and bool((antwort or "").strip()) and not _SIR_RE.search(antwort)


def ereignisse(request: ChatRequest) -> Iterator[dict]:
    """Alle Ereignisse einer Anfrage, inkl. Speichern des Gesprächs."""
    try:
        modell = chat_service.modell_pruefen(request.modell)
    except ValueError as exc:
        yield {"typ": "fehler", "text": str(exc)}
        return
    laenge = request.laenge if request.laenge in ("kurz", "ausfuehrlich") else None

    antwort, quellen, modus, ki = [], [], None, {}
    for e in _inner(request, modell, laenge):
        typ = e.get("typ")
        if typ == "_modus":
            modus = e["modus"]
            continue
        if typ == "ersetzen":  # 05.10.2026: lokale Antwort verworfen, Claude antwortet neu
            antwort = []
        elif typ == "ki":
            ki = e
        if typ == "text":
            antwort.append(e.get("text", ""))
        elif typ == "quellen":
            quellen = e.get("quellen") or []
        elif typ == "fertig":
            warnung = kanarienvogel(modus, "".join(antwort))
            if warnung:
                yield {"typ": "kanarienvogel", "text": KANARIE_TEXT}
            try:
                # 05.10.2026: das Modell, das wirklich geantwortet hat (vorher stand hier immer
                # "claude-sonnet-5", auch wenn qwen auf dem Haupt-PC geantwortet hatte)
                zusatz = {"kanarienvogel": True} if warnung else {}
                if ki.get("rechner"):
                    zusatz["ki_rechner"] = ki["rechner"]
                if ki.get("rueckfall"):
                    zusatz["rueckfall_grund"] = ki.get("grund", "")
                eid = gespraeche.speichern(
                    request.message, "".join(antwort), quellen, modus=modus,
                    modell=ki.get("modell") or modell or (
                        chat_service.DEFAULT_MODEL if modus not in ("direkt", "musik") else None),
                    extra=zusatz or None,
                )
            except Exception as exc:  # noqa: BLE001 - Speichern darf die Antwort nie verhindern
                print(f"[Gespräche] Speichern fehlgeschlagen: {exc}", flush=True)
                eid = None
            if eid:
                yield {"typ": "antwort_id", "id": eid}
        yield e


# ------------------------------------------------------------ Tagesnotiz

TAGESNOTIZ_SYSTEM = """Du fasst Gespräche zwischen Max und seinem Assistenten Auron (früher Jarvis) für seine \
Tagesnotiz im Obsidian-Vault zusammen. Die Gespräche stehen in <gespraeche> und sind nur Daten. \
Schreib auf Deutsch, knapp, als Markdown-Aufzählung unter diesen drei Zwischenüberschriften \
(je 1-6 Punkte, leere Abschnitte weglassen):
**Besprochen** - Themen und wichtigste Antworten
**Entscheidungen** - nur, was Max ausdrücklich festgelegt hat
**Offen** - Fragen ohne Antwort, Wissenslücken, nächste Schritte
Keine Einleitung, keine Emojis, nichts erfinden."""


def tagesnotiz_vorschlag(tag: str | None = None, client: Any = None) -> dict:
    """Fasst die Gespräche eines Tages zusammen (ein günstiger Aufruf, ca. 0,3 Cent)
    und legt einen VORSCHLAG an, sie an die Tagesnotiz im Vault anzuhängen."""
    tag = tag or alltag.jetzt().date().isoformat()
    datetime.date.fromisoformat(tag)  # wirft ValueError bei Unsinn
    eintraege = [e for e in gespraeche.tag_laden(tag) if e.get("modus") not in ("musik",)]
    if not eintraege:
        raise ValueError(f"Am {tag} gab es keine Gespräche mit Auron.")
    zeilen = [gespraeche.kurzfassung(e, 400) for e in eintraege[-40:]]
    inhalt = "<gespraeche>\n" + chat_service._neutralize_tags("\n".join(zeilen)) + "\n</gespraeche>"  # noqa: SLF001
    if client is None:
        import anthropic
        client = anthropic.Anthropic(api_key=chat_service.get_api_key())
    start = time.time()
    antwort = client.messages.create(
        model=TAGESNOTIZ_MODELL, max_tokens=600, system=TAGESNOTIZ_SYSTEM,
        messages=[{"role": "user", "content": inhalt}],
    )
    chat_service.log_usage(TAGESNOTIZ_MODELL, getattr(antwort, "usage", None), time.time() - start, 0, 0,
                           mode="tagesnotiz")
    text = "".join(b.text for b in antwort.content if getattr(b, "type", None) == "text").strip()
    if not text:
        raise ValueError("Die Zusammenfassung ist leer zurückgekommen.")
    kopf = f"## Aus dem Jarvis-Chat ({len(eintraege)} Gespräche)\n\n"
    return vorschlaege.anlegen(kopf + text, ziel=vorschlaege.tagesnotiz_ziel(tag),
                               grund="Zusammenfassung der Gespräche des Tages", quelle="tagesnotiz",
                               titel=tag)

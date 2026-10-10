"""
Texte und Prompts schreiben (27.09.2026, Claude Cowork).

Sir nutzte Claude im Alltag oft zum Formulieren (WhatsApp, Mails, offizielle
Schreiben) und will, dass Jarvis auch Prompts für andere KIs schreiben kann.
Beides ohne Vault-Suche - ein Sonnet-Aufruf, ca. 0,5-2 Cent.

Chat (app/alltag.schreib_absicht):
    "Schreib eine WhatsApp an Lisa, dass ich später komme"
    "Formulier eine Mail an meinen Chef: ..."
    "Schreib einen Prompt für Claude, der ..."
    "Verbessere diesen Text: ..."
"""

from __future__ import annotations

import re
from typing import Any

from . import ki_aufruf

MAX_TOKENS = 1100

STIL_SIR = """Stilregeln von Sir (Max) für Texte, die er selbst verschickt:
- Deutsch, einfach, klar, ganze Sätze. Keine KI-Floskeln ("Ich hoffe, diese Nachricht erreicht Sie gut", \
"Gerne!", "Zögern Sie nicht"), keine Emojis, außer Sir verlangt sie.
- Privat (WhatsApp, Freunde, Familie, Flirt): natürlich, locker, direkt, darf frech und humorvoll sein, \
nicht übertrieben romantisch, nicht cringe, nicht zu perfekt - so, wie ein Mensch am Handy schreibt.
- Arbeit, Behörde, Bundeswehr, Schule, Bewerbung: formell, höflich, sachlich, knapp.
- Hat Sir schon eine eigene Formulierung mitgeschickt und die ist gut, nur das Nötige ändern.
- Wenn Sir Varianten will, mach sie deutlich unterschiedlich (z.B. kurz / locker / förmlich)."""

TEXT_SYSTEM = f"""Du bist Auron (früher Jarvis), der Assistent von Max. Du schreibst einen Text, den Max selbst \
verschickt oder benutzt. Der Auftrag steht in <auftrag> und ist die einzige Anweisung.

{STIL_SIR}

Ausgabe:
- Zuerst ein kurzer Satz an Max mit "Sir" (z.B. "Hier zwei Varianten, Sir.").
- Dann den fertigen Text bzw. die Varianten, jede in einem eigenen Block, ohne Anrede "Sir" im Text selbst.
- Standard: 2 Varianten, wenn der Ton unklar ist; 1 Variante, wenn Ton und Inhalt klar sind; so viele, \
wie Max verlangt.
- Fehlen Angaben, die man nicht sinnvoll erfinden kann (Datum, Name, Betrag), setz [Platzhalter] und \
nenne sie am Ende in einem Satz.
- Nichts erfinden, was Max nicht gesagt hat (keine Gründe, keine Zusagen)."""

PROMPT_SYSTEM = """Du bist Auron (früher Jarvis), der Assistent von Max. Du schreibst einen PROMPT - also eine \
Anweisung, die Max in eine andere KI (Claude, ChatGPT, ein Bildmodell o.ä.) einfügt. Der Auftrag steht \
in <auftrag> und ist die einzige Anweisung.

So baust du einen guten Prompt:
1. Rolle und Ziel in einem Satz: wer die KI sein soll und was am Ende herauskommen muss.
2. Kontext: alles, was die KI wissen muss (Zielgruppe, Vorwissen, Rahmen) - aus dem Auftrag, nichts erfinden.
3. Konkrete Aufgabe in klaren Schritten.
4. Format der Ausgabe (Länge, Aufbau, Tabelle/Liste, Sprache, Ton).
5. Grenzen: was sie NICHT tun soll, und dass sie bei Unklarheit nachfragen soll.
6. Bei Bedarf ein kurzes Beispiel für die gewünschte Ausgabe.
Schreib direkt und positiv ("Schreibe ..." statt "Schreibe nicht ..."), ohne Füllwörter. Für Bild-KIs \
statt der Punkte oben: Motiv, Stil, Licht, Perspektive, Farben, Format in einem dichten Absatz.
Sprache des Prompts: wie Max es sagt, sonst Deutsch. Ist unklar, für welche KI, schreib ihn allgemein.

Ausgabe:
- Ein Satz an Max mit "Sir".
- Der fertige Prompt in einem Codeblock (```), damit er ihn mit einem Klick kopieren kann.
- Danach höchstens 2 Sätze: welche [Platzhalter] er noch füllen sollte."""


WHATSAPP_ZUSATZ = """

Das ist eine WhatsApp/SMS: Setze JEDE Variante in einen eigenen Codeblock (```), nur den reinen \
Nachrichtentext, ohne Überschrift im Block. Auron hängt danach je Variante einen Link an, der WhatsApp \
mit dem Text öffnet. Kurz halten, wie am Handy geschrieben."""

_WA_RE = re.compile(r"whats\s*app|\bwa\b|\bsms\b|nachricht\s+an", re.I)


def ist_whatsapp(auftrag: str) -> bool:
    return bool(_WA_RE.search(auftrag or ""))


def schreiben(auftrag: str, art: str = "text", client: Any = None) -> dict:
    """art = "text" oder "prompt". Rückgabe {"text", "kosten_usd"}."""
    auftrag = (auftrag or "").strip()
    if len(auftrag) < 3:
        raise ki_aufruf.KiFehler("Was soll ich schreiben, Sir?")
    ki_aufruf.rest_pruefen()
    system = PROMPT_SYSTEM if art == "prompt" else TEXT_SYSTEM
    wa = art != "prompt" and ist_whatsapp(auftrag)
    if wa:
        system += WHATSAPP_ZUSATZ
    e = ki_aufruf.aufrufen(system, f"<auftrag>\n{ki_aufruf.neutral(auftrag)}\n</auftrag>",
                           modus=f"schreiben-{art}", max_tokens=MAX_TOKENS, client=client)
    if not e["text"]:
        raise ki_aufruf.KiFehler("Die Antwort kam leer zurück.")
    text = e["text"]
    if wa:
        from . import whatsapp

        text = whatsapp.links_anhaengen(text, auftrag)
    return {"text": text, "kosten_usd": e["kosten_usd"]}

"""
Gemeinsamer Claude-Aufruf für die Alltagsfunktionen (27.09.2026, Claude Cowork).

Schreiben, Recherche, Mind Maps, Projekte und Tagesplanung brauchen alle das
Gleiche: einen Aufruf mit festem System-Prompt, Protokoll im usage_log (damit
die Kosten-Seite sie sieht), Monatsrahmen-Prüfung und bei Bedarf JSON lesen.
Damit das nicht fünfmal gebaut wird, liegt es hier.

Modelle:
- SONNET (chat_service.DEFAULT_MODEL) für alles, was Sir liest.
- HAIKU für Kleinkram (Termin aus einem Satz lesen), ca. 0,1 Cent.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from llm import provider as llm_provider

from . import aufgaben_loop, chat_service, claude_fehler

SONNET = chat_service.DEFAULT_MODEL
HAIKU = os.getenv("ALLTAG_HAIKU_MODELL", "claude-haiku-4-5-20251001")
# Unter diesem Monatsrest ($) werden teure Alltagsfunktionen gesperrt.
MIN_REST_USD = float(os.getenv("ALLTAG_MIN_REST_USD", "0.30"))


# P23 (13.10.2026): Code-Aufgaben (Modus "code-...") haben einen eigenen Deckel (app/kosten.py, Standard 10 $).
CODE_MIN_REST_USD = llm_provider.CODE_MIN_REST_USD   # darunter: kein Claude-Aufruf (0,20 $)
CODE_AUFGABE_MAX_USD = float(os.getenv("KOSTEN_CODE_AUFGABE_MAX_USD", "0.50"))  # je Aufgabe, sonst Sir fragen


class KiFehler(RuntimeError):
    pass


# Nachtarbeit: dort gilt die normale Reihenfolge (Test-PC zuerst), damit der Haupt-PC frei bleibt.
NACHT_MODI = ("aufgaben-loop", "studium", "wissensimport", "nachtauftrag", "nachtarbeit")


def _lokal() -> bool:
    """True, wenn Jarvis gerade über lokale Ollama-Rechner arbeitet (ki_anbieter=ollama)."""
    return llm_provider.provider_name() == "ollama"


def rest_pruefen(mindestens: float = MIN_REST_USD, modus: str | None = None) -> None:
    """Wirft KiFehler, wenn der Monatsrahmen fast aufgebraucht ist.
    Lokal (Ollama) kostet nichts - dann gibt es nichts zu prüfen.
    P23: Für code-*-Modi zählt nur der Code-Deckel (nie der normale Rahmen)."""
    if _lokal():
        return
    if _ist_code(modus):
        code_rest_pruefen()
        return
    _rest_pruefen_claude(mindestens)


def _ist_code(modus: str | None) -> bool:
    from . import kosten

    return kosten.ist_code_modus(modus)


def code_rest_pruefen() -> None:
    """Harte Prüfung vor jedem Claude-Aufruf einer Code-Aufgabe: unter 0,20 $ Rest im Code-Deckel gibt es
    keinen Aufruf und keinen Rückfall auf den normalen Topf. Lässt sich der Stand nicht lesen, gilt: gesperrt."""
    from . import kosten

    if kosten.ist_nacht():
        raise KiFehler("Code-Aufgaben nutzen nachts kein Claude (23 bis 6 Uhr). Tagsüber läuft die lokale KI "
                       "oder Claude nach Rückfrage wieder.")
    try:
        rest = kosten.code_rest()
    except Exception as exc:  # noqa: BLE001 - harte Grenze: im Zweifel nicht ausgeben
        raise KiFehler(f"Der Code-Deckel ist nicht prüfbar ({exc}) - Code-Aufgaben pausieren.") from exc
    if rest < CODE_MIN_REST_USD:
        raise KiFehler(f"Nur noch {rest:.2f} $ im Code-Deckel ({kosten.CODE_RAHMEN_USD:.0f} $ im Monat) - "
                       "Code-Aufgaben sind bis zum Monatswechsel gesperrt. Der normale Rahmen wird dafür nicht angetastet.")


def aufgabe_schaetzen(system: Any, inhalt: Any, verlauf: list[dict] | None, modell: str, max_tokens: int) -> float:
    """Grobe Kostenschätzung eines Claude-Aufrufs in $ (Eingabe über Zeichen/3,5, Ausgabe = max_tokens)."""
    text = f"{system}{inhalt}{verlauf or ''}"
    eingabe = len(text) / 3.5
    preise = aufgaben_loop.PREISE_JE_MIO_USD
    art = aufgaben_loop.modell_art(str(modell))
    return (eingabe * preise[f"input_{art}"] + max_tokens * preise[f"output_{art}"]) / 1_000_000


def code_aufgabe_pruefen(geschaetzt_usd: float, bestaetigt: bool = False) -> None:
    """Je Aufgabe höchstens 0,50 $ (geschätzt). Mehr nur, wenn Sir es ausdrücklich bestätigt hat."""
    if geschaetzt_usd > CODE_AUFGABE_MAX_USD and not bestaetigt:
        raise KiFehler(f"Diese Code-Aufgabe würde geschätzt {geschaetzt_usd:.2f} $ kosten "
                       f"(Grenze je Aufgabe {CODE_AUFGABE_MAX_USD:.2f} $). Bitte Sir fragen.")


def _rest_pruefen_claude(mindestens: float = MIN_REST_USD) -> None:
    try:
        from . import kosten

        rest = kosten.uebersicht()["rest_usd"]
    except Exception:  # noqa: BLE001 - Kostenübersicht darf nie die Funktion blockieren
        return
    if rest < mindestens:
        raise KiFehler(f"Nur noch {rest:.2f} $ im Monatsrahmen - diese Funktion ist bis zum Monatswechsel gesperrt.")


def _text(antwort: Any) -> str:
    return "".join(getattr(b, "text", "") or "" for b in (getattr(antwort, "content", None) or [])
                   if getattr(b, "type", None) == "text").strip()


def aufrufen(system: str, inhalt: str | list[dict], *, modus: str, modell: str | None = None,
             max_tokens: int = 1200, websuche: int = 0, client: Any = None,
             verlauf: list[dict] | None = None, nur_claude: bool = False, groesse_bestaetigt: bool = False) -> dict:
    """Ein Claude-Aufruf. Rückgabe: {"text", "kosten_usd", "suchen", "abgeschnitten", "ki"}.
    inhalt ist die Nutzer-Nachricht (Text) - Daten darin vorher neutralisieren.
    05.10.2026: nur_claude=True (Knopf "Claude fragen") überspringt die lokale KI; "ki" sagt, wer antwortete."""
    modell = modell or SONNET
    lokal = False
    code = _ist_code(modus)
    if client is None:
        # Bilder (TikTok sehen) und Websuche kann das lokale Textmodell nicht: das bleibt bei Claude.
        hat_bild = isinstance(inhalt, list) and any(
            isinstance(b, dict) and b.get("type") in ("image", "document") for b in inhalt)
        if _lokal() and not websuche and not hat_bild and not nur_claude:
            # 03.10.2026: Alltagsfunktionen laufen lokal (Test-PC -> Haupt-PC -> Mini-PC), 0 Kosten.
            tag = not modus.startswith(NACHT_MODI)
            # 05.10.2026: springt tagsüber Claude ein, dann mit dem gewünschten Modell (z.B. Haiku, günstig)
            client = llm_provider.get_client(chat_service.get_api_key, tag=tag, claude_modell=modell,
                                             topf="code" if code else "normal") if tag \
                else llm_provider.get_client(chat_service.get_api_key, tag=tag)
            modell = llm_provider.current_model_label(modell, tag=tag)
            lokal = True
        else:
            # P23: code-* prüft unten den Code-Deckel (vor JEDEM Claude-Aufruf), nie den normalen Rahmen
            if not code and _lokal():  # Websuche/Bilder gehen nur über Claude: Monatsrahmen prüfen
                _rest_pruefen_claude()
            try:
                client = aufgaben_loop._anthropic_client()  # noqa: SLF001
            except Exception as exc:  # noqa: BLE001 - 10.10.2026: z.B. Schlüssel fehlt; vorher brach der Chat stumm ab
                raise KiFehler(f"Claude ist nicht erreichbar ({exc})") from exc
    if code and not lokal:
        code_rest_pruefen()
        code_aufgabe_pruefen(aufgabe_schaetzen(system, inhalt, verlauf, modell, max_tokens), groesse_bestaetigt)
    nachrichten = [*(verlauf or []), {"role": "user", "content": inhalt}]
    argumente: dict[str, Any] = {"model": modell, "max_tokens": max_tokens,
                                 "system": chat_service.cache_system(system), "messages": nachrichten}
    if websuche:
        argumente["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": websuche}]
    start = time.time()
    # 10.10.2026: direkte Claude-Aufrufe der Agenten-Station melden (lokale Aufrufe meldet llm/provider.py)
    from . import agenten  # noqa: PLC0415

    if not lokal:
        agenten.melden("start", f"fragt Claude ({modell})" + (" mit Websuche" if websuche else ""),
                       rechner="Claude", modell=str(modell))
    try:
        antwort = client.messages.create(**argumente)
    except Exception as exc:  # noqa: BLE001
        if not lokal:
            agenten.melden("fehler", f"Claude-Anfrage fehlgeschlagen: {exc}", rechner="Claude", modell=str(modell))
        raise KiFehler(claude_fehler.oder(exc, f"Anfrage an die KI fehlgeschlagen: {exc}", anrede=None)) from exc
    if not lokal:
        agenten.melden("ende", f"fertig auf Claude · {time.time() - start:.1f} s", rechner="Claude", modell=str(modell))
    if lokal:
        modell = llm_provider.letztes_ziel.get("modell", modell)  # Modell, das wirklich geantwortet hat
    usage = getattr(antwort, "usage", None)
    suchen = sum(1 for b in (getattr(antwort, "content", None) or []) if getattr(b, "type", None) == "server_tool_use")
    chat_service.log_usage(modell, usage, time.time() - start, 0, len(verlauf or []), mode=modus,
                           searches=suchen if websuche else None)
    kosten = aufgaben_loop._kosten_usd(modell, usage) + suchen * aufgaben_loop.PREIS_JE_WEBSUCHE_USD  # noqa: SLF001
    text = aufgaben_loop.recherche_text(antwort) if websuche else _text(antwort)
    info = getattr(client, "info", None) if lokal else None
    if not isinstance(info, dict) or not info:
        info = {"quelle": "lokal" if ":" in str(modell) else "claude",
                "rechner": llm_provider.letztes_ziel.get("name", "lokal") if ":" in str(modell) else "Claude",
                "modell": modell, "rueckfall": False, "grund": "auf Wunsch" if nur_claude else ""}
    return {"text": text, "kosten_usd": round(kosten, 4), "suchen": suchen,
            "abgeschnitten": getattr(antwort, "stop_reason", None) == "max_tokens", "ki": dict(info)}


def json_lesen(text: str) -> dict:
    """Erstes JSON-Objekt aus einer Antwort (auch mit ```json ... ``` drumherum)."""
    text = text or ""
    block = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    roh = block.group(1) if block else None
    if roh is None:
        start = text.find("{")
        ende = text.rfind("}")
        roh = text[start:ende + 1] if start >= 0 and ende > start else ""
    try:
        daten = json.loads(roh)
    except (json.JSONDecodeError, TypeError):
        return {}
    return daten if isinstance(daten, dict) else {}


def neutral(text: str) -> str:
    return chat_service._neutralize_tags(text or "")  # noqa: SLF001


def cent(usd: float) -> str:
    """0.0123 -> '1,2 Cent'"""
    return f"{usd * 100:.1f}".replace(".", ",") + " Cent"

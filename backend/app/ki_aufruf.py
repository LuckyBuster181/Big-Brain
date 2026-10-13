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


class KiFehler(RuntimeError):
    pass


# Nachtarbeit: dort gilt die normale Reihenfolge (Test-PC zuerst), damit der Haupt-PC frei bleibt.
NACHT_MODI = ("aufgaben-loop", "studium", "wissensimport", "nachtauftrag", "nachtarbeit")


def _lokal() -> bool:
    """True, wenn Jarvis gerade über lokale Ollama-Rechner arbeitet (ki_anbieter=ollama)."""
    return llm_provider.provider_name() == "ollama"


def rest_pruefen(mindestens: float = MIN_REST_USD) -> None:
    """Wirft KiFehler, wenn der Monatsrahmen fast aufgebraucht ist.
    Lokal (Ollama) kostet nichts - dann gibt es nichts zu prüfen."""
    if _lokal():
        return
    _rest_pruefen_claude(mindestens)


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
             verlauf: list[dict] | None = None, nur_claude: bool = False) -> dict:
    """Ein Claude-Aufruf. Rückgabe: {"text", "kosten_usd", "suchen", "abgeschnitten", "ki"}.
    inhalt ist die Nutzer-Nachricht (Text) - Daten darin vorher neutralisieren.
    05.10.2026: nur_claude=True (Knopf "Claude fragen") überspringt die lokale KI; "ki" sagt, wer antwortete."""
    modell = modell or SONNET
    lokal = False
    if client is None:
        # Bilder (TikTok sehen) und Websuche kann das lokale Textmodell nicht: das bleibt bei Claude.
        hat_bild = isinstance(inhalt, list) and any(
            isinstance(b, dict) and b.get("type") in ("image", "document") for b in inhalt)
        if _lokal() and not websuche and not hat_bild and not nur_claude:
            # 03.10.2026: Alltagsfunktionen laufen lokal (Test-PC -> Haupt-PC -> Mini-PC), 0 Kosten.
            tag = not modus.startswith(NACHT_MODI)
            # 05.10.2026: springt tagsüber Claude ein, dann mit dem gewünschten Modell (z.B. Haiku, günstig)
            client = llm_provider.get_client(chat_service.get_api_key, tag=tag, claude_modell=modell) if tag \
                else llm_provider.get_client(chat_service.get_api_key, tag=tag)
            modell = llm_provider.current_model_label(modell, tag=tag)
            lokal = True
        else:
            if _lokal():  # Websuche/Bilder gehen nur über Claude: Monatsrahmen prüfen
                _rest_pruefen_claude()
            try:
                client = aufgaben_loop._anthropic_client()  # noqa: SLF001
            except Exception as exc:  # noqa: BLE001 - 10.10.2026: z.B. Schlüssel fehlt; vorher brach der Chat stumm ab
                raise KiFehler(f"Claude ist nicht erreichbar ({exc})") from exc
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

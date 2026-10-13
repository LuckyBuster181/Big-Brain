"""
Kurze, klare Meldung, wenn Claude nicht antworten kann (P20, 13.10.2026).

Anlass: Das API-Guthaben kann aufgebraucht sein. Die Anthropic-Bibliothek wirft dann einen langen
Fehler mit JSON-Text. Sir bekommt stattdessen einen Satz. Gilt für den Rückfall auf Claude und den Knopf
"Claude fragen". Lokale Antworten und Befehle ohne Claude laufen unabhängig davon weiter.

kurz(exc) gibt None zurück, wenn der Fehler kein erkennbarer Claude-Fehler ist (dann bleibt die bisherige
Meldung). Keine Imports der Anthropic-Bibliothek nötig: erkannt wird am Klassennamen und am Text.
"""

from __future__ import annotations

WEITER = "Lokale Antworten und Befehle ohne Claude laufen weiter"


def _text(exc: BaseException) -> str:
    return f"{type(exc).__name__} {exc}".lower()


def kurz(exc: BaseException, anrede: str | None = "Sir") -> str | None:
    t = _text(exc)
    ende = f"{WEITER}, {anrede}." if anrede else f"{WEITER}."
    if "credit balance" in t or "purchase credits" in t:
        return f"Claude ist gerade nicht erreichbar: Das API-Guthaben ist aufgebraucht. {ende}"
    if "authenticationerror" in t or "invalid x-api-key" in t or "invalid api key" in t or "permissiondeniederror" in t:
        return f"Claude lehnt den Schlüssel ab (ANTHROPIC_API_KEY prüfen). {ende}"
    if "ratelimiterror" in t or "rate_limit" in t or "overloaded" in t or "internalservererror" in t:
        return f"Claude ist gerade überlastet oder gedrosselt, bitte später noch einmal. {ende}"
    if "apiconnectionerror" in t or "apitimeouterror" in t or "connection error" in t:
        return f"Claude ist nicht erreichbar (keine Verbindung). {ende}"
    return None


def oder(exc: BaseException, bisher: str, anrede: str | None = "Sir") -> str:
    """Kurze Meldung, falls erkennbar, sonst der bisherige Text."""
    return kurz(exc, anrede) or bisher

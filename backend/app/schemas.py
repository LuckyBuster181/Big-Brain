"""Pydantic-Schemas für die Jarvis-API.

Werden im Dashboard in dashboard/src/types/chat.ts gespiegelt - Änderungen
hier dort mitziehen.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HistoryMessage(BaseModel):
    """Eine frühere Nachricht aus dem laufenden Gespräch."""

    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=50_000)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="Frage des Nutzers")
    top_k: int = Field(
        3, ge=1, le=20,
        description="Wie viele Vault-Chunks als Kontext geholt werden (Standard 3 statt 5 seit "
        "der Kostenoptimierung 20.09.2026 - suchtest.bat zeigte die richtige Notiz in 25 von 28 "
        "Testfragen weiterhin unter den ersten 3 Treffern)",
    )
    status: str | None = Field(
        None, description="Nur Notizen mit diesem Frontmatter-Status (z.B. 'bestätigt') berücksichtigen"
    )
    history: list[HistoryMessage] = Field(
        default_factory=list,
        max_length=100,
        description="Bisheriger Gesprächsverlauf (älteste zuerst), ohne die aktuelle Frage",
    )
    mode: Literal["klassisch", "werkzeug"] | None = Field(
        None,
        description="klassisch = feste Vault-Suche vor der Antwort, werkzeug = Claude sucht selbst "
        "(bis zu 3-mal). Ohne Angabe gilt CHAT_MODE aus der .env (Standard: klassisch).",
    )
    agenten: bool = Field(
        False,
        description="Nur im Werkzeug-Modus wirksam. True = Suchen laufen über ein günstigeres "
        "Modell (ANTHROPIC_TOOL_MODEL, Rolle 'Sucher'), nur die fertige Antwort über das "
        "Hauptmodell (Rolle 'Antworter'). Der Stream liefert dazu 'agent'- und 'token'-Ereignisse "
        "fürs HUD (Knopf 'Agenten'). False (Standard) = bisheriges Verhalten, ein Modell für alles.",
    )
    modell: str | None = Field(
        None, max_length=60,
        description="Nur für diese Frage ein anderes Modell (z.B. 'claude-opus-5-5'). Leer = Standard aus der .env.",
    )
    laenge: Literal["kurz", "normal", "ausfuehrlich"] | None = Field(
        None, description="Antwortlänge (Kurz/ausführlich-Schalter im HUD)."
    )
    offener_vorschlag: str | None = Field(
        None, max_length=40,
        description="ID eines Vorschlags, auf den ein 'ja'/'nein' antworten würde (Sprach-Bestätigung).",
    )


class Source(BaseModel):
    file_path: str
    heading_path: str
    score: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    used_vault: bool  # False, wenn keine relevanten Chunks gefunden wurden
    ereignisse: list[dict] = Field(default_factory=list)  # Plan/Vorschlag aus dem Werkzeug-Modus


class HealthResponse(BaseModel):
    status: str
    vault_indexed: bool
    chunk_count: int | None = None
    embedding_model: str | None = None
    reindex_running: bool = False


class ReindexResult(BaseModel):
    model: str
    full: bool
    files_total: int
    files_indexed: int
    files_new: int
    files_changed: int
    files_removed: int
    files_unchanged: int
    files_empty: int = 0
    chunks_written: int
    collection_count: int
    duration_s: float


class ReindexProgress(BaseModel):
    done: int
    total: int
    current_file: str | None = None


class ReindexStatus(BaseModel):
    running: bool
    full: bool = False
    started_at: str | None = None
    finished_at: str | None = None
    progress: ReindexProgress | None = None
    last_result: ReindexResult | None = None
    error: str | None = None


class KnowledgeGap(BaseModel):
    """Eine Frage, zu der im Vault nichts Passendes stand (siehe app/knowledge_gaps.py)."""

    zeit: str = ""
    frage: str
    grund: str = ""
    bester_cos: float | None = None
    modus: str | None = None


class SpracheRequest(BaseModel):
    """Text, den Jarvis vorlesen soll (siehe app/sprache.py)."""

    text: str
    tempo: float = 1.0


class SpotifyBefehl(BaseModel):
    """Ein gesprochener oder getippter Musikbefehl (siehe app/spotify.py)."""

    text: str = Field(..., min_length=1, max_length=300)


class SchluesselSetzen(BaseModel):
    """Einen bekannten API-Schlüssel in die .env schreiben (siehe app/schluessel.py)."""

    name: str = Field(..., min_length=1, max_length=60)
    wert: str = Field(..., min_length=1, max_length=1000)


class BacktestRequest(BaseModel):
    """Ein Lauf der Trading-Sandbox (siehe app/trading_sandbox.py)."""

    datenquelle: str = Field("demo", max_length=200, description='"demo" oder z.B. "ablage/EURUSD_H1.csv"')
    strategie: str = Field("ema_kreuzung", max_length=60)
    parameter: dict[str, float] = Field(default_factory=dict)
    risiko: dict[str, float] = Field(default_factory=dict)


class PruefstandRequest(BaseModel):
    """Ein Lauf des Modell-Prüfstands (siehe app/pruefstand.py). Leere Listen = Standard."""

    fragen: list[str] = Field(default_factory=list, max_length=20)
    modelle: list[str] = Field(default_factory=list, max_length=4)
    deckel_usd: float | None = Field(None, gt=0, le=2)


class DenkblockSpeichernRequest(BaseModel):
    """Denk-Notiz anlegen oder Sirs Text speichern (siehe app/denkblock.py)."""

    name: str = Field(..., min_length=1, max_length=80)
    text: str = Field("", max_length=20_000)


class DenkblockMitdenkenRequest(BaseModel):
    modell: str | None = Field(None, max_length=60)


class DenkblockUebernehmenRequest(BaseModel):
    gedanken: str = Field(..., min_length=1, max_length=10_000)


class KarteAntwortRequest(BaseModel):
    """Sirs Antwort zu einem Punkt der Gesamtkarte (siehe app/gesamtkarte.py)."""

    text: str = Field(..., min_length=1, max_length=4000)


class KarteBesprechenRequest(BaseModel):
    """Mit Jarvis über einen Punkt der Gesamtkarte reden. Ohne Nachricht fragt Jarvis selbst."""

    nachricht: str | None = Field(None, max_length=2000)
    verlauf: list[dict] = Field(default_factory=list, max_length=20)
    modell: str | None = Field(None, max_length=60)


class TikTokLinksRequest(BaseModel):
    """Beliebiger Text mit TikTok-Links (siehe app/tiktok.py)."""

    text: str = Field(..., min_length=1, max_length=200_000)


class TerminAnlegenRequest(BaseModel):
    """Ein Termin, der im Google-Kalender angelegt werden soll
    (siehe app/kalender_schreiben.py). Nur zum Anlegen, kein Ändern/Löschen."""

    titel: str = Field(..., min_length=1, max_length=200)
    start: str = Field(..., description="z.B. '2026-09-23T15:00:00'")
    ende: str | None = Field(None, description="Ohne Angabe: eine Stunde nach dem Start")
    ort: str = Field("", max_length=200)
    beschreibung: str = Field("", max_length=2000)


class VorschlagRequest(BaseModel):
    """Vorschlag von Hand anlegen (Phase 2.3) - geschrieben wird erst nach "Übernehmen"."""

    text: str = Field(..., min_length=1, max_length=30_000)
    ziel: str | None = Field(None, max_length=300, description="Pfad im Vault, leer = 'Gemerkt von Jarvis'")
    grund: str = Field("", max_length=500)


class BewertungRequest(BaseModel):
    wert: Literal[1, -1]
    kommentar: str = Field("", max_length=1000)


class WebseiteRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2000)


class PaperOrderRequest(BaseModel):
    """Paper-Trade (Phase 4.5) - geht immer durch den Risiko-Wächter."""

    symbol: str = Field(..., min_length=2, max_length=20)
    richtung: Literal["kauf", "verkauf"]
    stop: float = Field(..., gt=0)
    ziel: float | None = Field(None, gt=0)
    risiko_prozent: float | None = Field(None, gt=0, le=5)
    einstieg: float | None = Field(None, gt=0, description="Leer = letzter gespeicherter Kurs")
    notiz: str = Field("", max_length=500)


class Pc2AktionRequest(BaseModel):
    """Aktion auf PC 2 (Linux) - gefährliche nur mit bestaetigt=true."""

    aktion: str = Field(..., min_length=3, max_length=80, pattern=r"^[a-z_]+(:[A-Za-z0-9_.-]+)?$")
    ziel: str | int | None = Field(None, description="Dienstname oder Prozessnummer")
    bestaetigt: bool = False

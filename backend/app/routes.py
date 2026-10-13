"""API-Routen für Jarvis."""

from __future__ import annotations

import json
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from rag.embedder import get_preset
from rag.embeddings import get_client, get_collection

from . import (
    ablage,
    agenten,
    ampel,
    agent_service,
    alltag,
    aufgaben_loop,
    briefing,
    chat_ablauf,
    chat_service,
    denkblock,
    einstellungen,
    gesamtkarte,
    gespraeche,
    kalender,
    kalender_schreiben,
    kamera,
    ki_status,
    knowledge_gaps,
    kosten,
    markt_analyse,
    marktdaten,
    nachtarbeit,
    nachtauftraege,
    nachtbericht,
    paper_trading,
    pc2,
    piper_tts,
    pruefschritt,
    pruefstand,
    reindex_service,
    schluessel,
    sonos,
    sprache,
    spotify,
    stt,
    studium,
    system_info,
    tagebuch,
    tagesfrage,
    tiktok,
    tiktok_sehen,
    trading_sandbox,
    vault_list,
    vorschlaege,
    webseite,
    wissensimport,
)
from .schemas import (
    BacktestRequest,
    BewertungRequest,
    ChatRequest,
    ChatResponse,
    DenkblockMitdenkenRequest,
    DenkblockSpeichernRequest,
    DenkblockUebernehmenRequest,
    HealthResponse,
    KarteAntwortRequest,
    KarteBesprechenRequest,
    KnowledgeGap,
    PaperOrderRequest,
    Pc2AktionRequest,
    PruefstandRequest,
    ReindexStatus,
    SchluesselSetzen,
    SpotifyBefehl,
    SpracheRequest,
    TerminAnlegenRequest,
    TikTokLinksRequest,
    VorschlagRequest,
    WebseiteRequest,
)

router = APIRouter()


@router.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    preset = get_preset()
    running = reindex_service.is_running()
    try:
        count = get_collection(get_client(), preset).count()
        return HealthResponse(
            status="ok",
            vault_indexed=count > 0,
            chunk_count=count,
            embedding_model=preset.key,
            reindex_running=running,
        )
    except Exception:
        # Chroma-DB existiert evtl. noch nicht (Index wurde noch nicht gebaut)
        return HealthResponse(
            status="ok", vault_indexed=False, chunk_count=0, embedding_model=preset.key, reindex_running=running
        )


@router.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    try:
        return chat_service.ask(
            request.message,
            top_k=request.top_k,
            status=request.status,
            history=request.history,
            mode=request.mode,
            modell=chat_service.modell_pruefen(request.modell),
            laenge=request.laenge if request.laenge in ("kurz", "ausfuehrlich") else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        # z.B. fehlender ANTHROPIC_API_KEY - Konfigurationsfehler, kein Serverfehler
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # Anthropic-API-Fehler, Netzwerk, etc.
        raise HTTPException(status_code=502, detail=f"Fehler bei der Anfrage an Claude: {exc}") from exc


ALEXA_MAX_BYTES = 64 * 1024


@router.post("/api/alexa")
async def alexa_anfrage(request: Request) -> Response:
    """Alexa-Skill "frag Auron" (P19, 12.10.2026). Über den Funnel-Knoten "auron-alexa" aus dem
    Internet erreichbar - Schutz ist allein die Prüfung in app/alexa_pruefung.py (Signatur,
    Zeitstempel, Skill-ID). Ohne ALEXA_AKTIV=1 in der .env gibt es den Endpunkt nicht (404)."""
    from . import alexa, alexa_pruefung

    if not alexa_pruefung.ist_aktiv():
        raise HTTPException(status_code=404, detail="Not Found")
    rohtext = await request.body()
    if len(rohtext) > ALEXA_MAX_BYTES:
        return JSONResponse({"detail": "Bad Request"}, status_code=400)
    start = time.time()
    try:
        await run_in_threadpool(alexa_pruefung.signatur_pruefen, dict(request.headers), rohtext)
        anfrage = json.loads(rohtext)
        alexa_pruefung.inhalt_pruefen(anfrage)
    except (alexa_pruefung.AlexaAbgelehnt, ValueError) as exc:
        # Nur ins Konsolen-Log: Der Endpunkt ist öffentlich, Fremdanfragen sollen den Fehlerbericht nicht füllen.
        print(f"[Alexa] Anfrage abgelehnt: {exc}", flush=True)
        if request.headers.get("signaturecertchainurl"):   # sah aus wie Alexa: fürs Alexa-Protokoll (Diagnose)
            alexa.ablehnung_protokollieren(str(exc), int((time.time() - start) * 1000))
        return JSONResponse({"detail": "Bad Request"}, status_code=400)
    pruef_ms = int((time.time() - start) * 1000)
    return JSONResponse(await run_in_threadpool(alexa.verarbeiten, anfrage, pruef_ms))


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("/api/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Wie /api/chat, aber die Antwort kommt häppchenweise als Server-Sent-
    Events (das HUD zeigt sie dann wortweise statt nach mehreren Sekunden
    Stille auf einmal).

    Werkzeug-Modus ohne "agenten": lässt sich technisch schlecht Wort für Wort
    streamen (mehrere Claude-Aufrufe nacheinander, siehe app/agent_service.py)
    - die fertige Antwort kommt als ein einziges "text"-Ereignis.

    Werkzeug-Modus MIT "agenten" (Knopf "Agenten" im HUD): Sucher und Antworter
    laufen getrennt (app/agent_service.py, ask_with_tools_stream) und liefern
    zusätzlich "agent"- und "token"-Ereignisse - die Antworter-Phase wird dabei
    wortweise gestreamt."""

    def ereignisse():
        # Ablauf siehe app/chat_ablauf.py (Absicht -> Musik -> Claude, danach speichern)
        for event in chat_ablauf.ereignisse(request):
            yield _sse(event)

    return StreamingResponse(
        ereignisse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/api/reindex", response_model=ReindexStatus, status_code=202)
def reindex(
    full: bool = Query(False, description="True = Index komplett neu aufbauen statt nur Änderungen"),
) -> ReindexStatus:
    """Startet das Neu-Einlesen des Vaults im Hintergrund. Läuft schon ein
    Lauf, wird kein zweiter gestartet - die Antwort zeigt dann den laufenden."""
    try:
        _, current = reindex_service.start(full=full)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return current


@router.get("/api/fehlerbericht")
def fehlerbericht_abrufen(tage: int = Query(7, ge=1, le=60)) -> Response:
    """10.10.2026: Fehlerbericht als Markdown (app/fehlerbericht.py). FEHLERBERICHT SENDEN.bat legt ihn
    ins Repo, damit Claude ihn liest. Nur gelesen, 0 Kosten."""
    from . import fehlerbericht  # noqa: PLC0415

    return Response(fehlerbericht.bericht(tage), media_type="text/markdown; charset=utf-8")


@router.get("/api/agenten")
def agenten_uebersicht(anzahl: int = Query(40, ge=1, le=300)) -> dict:
    """10.10.2026: Agenten-Station im Universum - wer arbeitet gerade, woran, auf welchem Rechner,
    an welcher Codestelle. Nur gelesen, 0 Kosten (app/agenten.py)."""
    return agenten.uebersicht(anzahl)


@router.get("/api/ampel")
def ampel_uebersicht() -> dict:
    """Ampel für alle Hintergrund-Arbeiten (app/ampel.py): grün läuft, gelb wartet
    auf Sir, rot Fehler, grau ruht. 0 Kosten."""
    return ampel.uebersicht()


@router.get("/api/reindex/status", response_model=ReindexStatus)
def reindex_status() -> ReindexStatus:
    return reindex_service.status()


@router.get("/api/vault")
def vault() -> list[dict]:
    """Alle Notizen im Vault mit Titel, Status und Änderungszeit (fürs Dashboard)."""
    return vault_list.notes()


@router.get("/api/einstellungen")
def einstellungen_lesen() -> dict:
    """Was gerade gilt und was davon im HUD gespeichert wurde."""
    return einstellungen.aktueller_stand()


@router.put("/api/einstellungen")
def einstellungen_speichern(werte: dict) -> dict:
    """Einstellungen aus dem HUD speichern. Wirkt nach einem Neustart."""
    try:
        einstellungen.speichern(werte)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return einstellungen.aktueller_stand()


@router.get("/api/briefing")
def briefing_holen(
    modus: str | None = Query(None, description="morgen oder abend; ohne Angabe nach Uhrzeit"),
    erzwingen: bool = Query(False, description="Zwischenspeicher übergehen und neu erzeugen"),
) -> dict:
    """Tagesbriefing aus Tagesnotiz, Terminen und Tokenverbrauch.

    Kostet einen Claude-Aufruf, das Ergebnis gilt 10 Minuten."""
    try:
        return briefing.hole(modus=modus, erzwingen=erzwingen)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Briefing fehlgeschlagen: {exc}") from exc


@router.get("/api/kalender")
def kalender_termine(erzwingen: bool = Query(False, description="Zwischenspeicher übergehen und sofort neu abrufen")) -> dict:
    """Termine aus dem Google-Kalender (iCal-Adresse aus der .env).

    Antwortet im selben Format wie die alte dashboard/public/kalender.json,
    damit das HUD beide Quellen lesen kann. Ist keine Adresse hinterlegt oder
    Google nicht erreichbar, kommt 503 - das HUD fällt dann auf die Datei
    zurück. Die Adresse selbst steht in keiner Antwort."""
    if not kalender.ist_eingerichtet():
        raise HTTPException(
            status_code=503,
            detail="Keine Kalender-Adresse hinterlegt. KALENDER_ICS_URL in die .env eintragen.",
        )
    try:
        return kalender.hole(erzwingen=erzwingen)
    except kalender.KalenderFehler as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ----------------------------------------------------- Kalender schreiben (22.09.2026)


@router.get("/api/kalender-schreiben/status")
def kalender_schreiben_status() -> dict:
    """Ist der Schreibzugriff eingerichtet (ohne Zugangsdaten zu zeigen)."""
    return kalender_schreiben.stand()


@router.get("/api/kalender-schreiben/login")
def kalender_schreiben_login() -> RedirectResponse:
    """Einmalige Freigabe. Leitet zu Google weiter; danach kommt der
    Erneuerungs-Schlüssel auf der Rückleitungsseite zum Eintragen in die .env."""
    try:
        return RedirectResponse(kalender_schreiben.login_url())
    except kalender_schreiben.KalenderSchreibenFehler as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/api/kalender-schreiben/callback", response_class=HTMLResponse)
def kalender_schreiben_callback(
    code: str | None = Query(None), error: str | None = Query(None)
) -> HTMLResponse:
    """Rückleitung von Google. Zeigt den Schlüssel EINMAL an - er wird
    absichtlich nicht automatisch gespeichert, damit nichts still in eine
    Datei geschrieben wird."""
    if error:
        return HTMLResponse(f"<h2>Google hat abgelehnt: {error}</h2>", status_code=400)
    if not code:
        return HTMLResponse("<h2>Kein Code erhalten.</h2>", status_code=400)
    try:
        schluessel = kalender_schreiben.code_einloesen(code)
    except kalender_schreiben.KalenderSchreibenFehler as exc:
        return HTMLResponse(f"<h2>Fehlgeschlagen: {exc}</h2>", status_code=502)
    return HTMLResponse(
        "<html><body style=\"font-family:sans-serif;background:#111;color:#eee;padding:40px\">"
        "<h2>Geschafft, Sir.</h2><p>Diese Zeile in <code>Jarvis\\.env</code> eintragen "
        "und das Backend neu starten:</p>"
        f"<pre style=\"background:#000;padding:16px;overflow-wrap:anywhere;white-space:pre-wrap\">"
        f"GOOGLE_CALENDAR_REFRESH_TOKEN={schluessel}</pre>"
        "<p>Danach dieses Fenster schließen. Der Schlüssel wird hier nur einmal angezeigt.</p>"
        "</body></html>"
    )


@router.post("/api/kalender-schreiben/termin")
def kalender_schreiben_termin(request: TerminAnlegenRequest) -> dict:
    """Legt einen Termin im Google-Kalender an. Nur Anlegen, kein Ändern/Löschen.

    Vorerst ein reiner Testweg fürs HUD - noch keine Anbindung an den Chat."""
    try:
        start = datetime.fromisoformat(request.start)
        ende = datetime.fromisoformat(request.ende) if request.ende else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Datum/Uhrzeit ungültig: {exc}") from exc
    try:
        return kalender_schreiben.termin_anlegen(
            request.titel, start, ende=ende, ort=request.ort, beschreibung=request.beschreibung
        )
    except kalender_schreiben.KalenderSchreibenFehler as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/api/system")
def system() -> dict:
    """CPU, Speicher, Festplatte und Laufzeit für die Systemanzeige im HUD."""
    return system_info.snapshot()


# ---------------------------------------------------------------- PC 2 (Linux)
@router.get("/api/pc2/konfig")
def pc2_konfig() -> dict:
    """Ist PC 2 eingerichtet, kann er geweckt werden, gibt es eine Bildschirmansicht."""
    return pc2.oeffentliche_konfig()


@router.get("/api/pc2/status")
def pc2_status() -> dict:
    try:
        return pc2.status()
    except pc2.Pc2Fehler as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.get("/api/pc2/stream")
def pc2_stream() -> StreamingResponse:
    """Livewerte von PC 2 als Server-Sent Events, ein Paket pro Sekunde."""
    return StreamingResponse(
        pc2.stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/api/pc2/aktionen")
def pc2_aktionen() -> dict:
    try:
        return pc2.aktionen()
    except pc2.Pc2Fehler as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.post("/api/pc2/aktion")
def pc2_aktion(request: Pc2AktionRequest) -> dict:
    try:
        return pc2.aktion(request.aktion, request.ziel, request.bestaetigt)
    except pc2.Pc2Fehler as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.post("/api/pc2/wecken")
def pc2_wecken() -> dict:
    try:
        return pc2.wecken()
    except pc2.Pc2Fehler as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.get("/api/wissensluecken", response_model=list[KnowledgeGap])
def wissensluecken(limit: int = Query(50, ge=1, le=500)) -> list[KnowledgeGap]:
    """Fragen, zu denen im Vault nichts Passendes stand - neueste zuerst."""
    return [KnowledgeGap(**entry) for entry in knowledge_gaps.recent(limit) if "frage" in entry]


@router.post("/api/aufgaben-loop/start", status_code=202)
def aufgaben_loop_start(
    max_aufgaben: int | None = Query(None, ge=1, le=10, description="Wie viele Wissenslücken höchstens, Standard 3"),
    deckel_usd: float | None = Query(None, gt=0, description="Budget-Deckel für diesen Lauf in Dollar, Standard 1.0"),
) -> dict:
    """Startet einen Lauf im Hintergrund: Rechercheur sucht im Web zu
    wiederkehrenden Wissenslücken, Schreiber legt Entwürfe im Vault an,
    danach git commit (siehe app/aufgaben_loop.py). Läuft schon einer, wird
    kein zweiter gestartet - die Antwort zeigt dann den laufenden."""
    try:
        _, current = aufgaben_loop.start(max_aufgaben=max_aufgaben, deckel_usd=deckel_usd)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return current


@router.get("/api/aufgaben-loop/status")
def aufgaben_loop_status() -> dict:
    return aufgaben_loop.status()


# --------------------------------------------------------------------- Studium
# Wie der Aufgaben-Loop, aber mit einem Thema statt echten Chat-Wissenslücken
# als Quelle (22.09.2026, Wunsch von Sir: "das Limit ausreizen ... Physik
# studiert"). Siehe app/studium.py.


@router.post("/api/studium/start", status_code=202)
def studium_start(
    thema: str = Query(..., min_length=1, max_length=100, description="Thema, z.B. 'Physik'"),
    deckel_usd: float | None = Query(None, gt=0, description="Budget-Deckel für diesen Lauf in Dollar, Standard 1.0"),
    max_aufgaben: int | None = Query(None, ge=1, le=50, description="Höchstens so viele Unterthemen; ohne Angabe alle bis zum Deckel"),
    stufe: str = Query("grundlagen", description="grundlagen, vertiefung, forschung oder praxis"),
) -> dict:
    """Startet einen Studium-Lauf im Hintergrund: ein Thema wird in Unterthemen
    zerlegt, je Unterthema recherchiert der Rechercheur und der Schreiber legt
    einen Entwurf im Vault an, danach git commit (siehe app/studium.py). Läuft
    schon einer, wird kein zweiter gestartet."""
    try:
        _, current = studium.start(thema, deckel_usd=deckel_usd, max_aufgaben=max_aufgaben, stufe=stufe)
    except ValueError as exc:  # unbekannte Stufe
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return current


@router.get("/api/studium/status")
def studium_status() -> dict:
    return studium.status()


@router.get("/api/studium/stufen")
def studium_stufen() -> list[dict]:
    """Die Studium-Stufen für die Auswahl im HUD."""
    return [{"id": sid, "name": s["name"]} for sid, s in studium.STUFEN.items()]


# -------------------------------------------------------------- Wissensimport
# 29.09.2026 (Sir): Wikipedia-Artikel -> Sonnet fasst zusammen -> Haiku prüft jede,
# Opus jede 10. Notiz -> Vault. Deckel 10 $ gesamt. Siehe app/wissensimport.py.


@router.post("/api/wissensimport/start", status_code=202)
def wissensimport_start(
    anzahl: int = Query(20, ge=1, le=1000, description="So viele neue Notizen (wird auf den Deckel gekürzt)"),
) -> dict:
    try:
        return wissensimport.start(anzahl)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except wissensimport.ImportFehler as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/wissensimport/status")
def wissensimport_status() -> dict:
    return wissensimport.status()


@router.post("/api/wissensimport/abbrechen")
def wissensimport_abbrechen() -> dict:
    return wissensimport.abbrechen()


# -------------------------------------------------------------- TikTok sehen
# 03.10.2026 (Sir): TikTok-Videos auch im Bild auswerten (Standbilder + Haiku,
# ca. 1 Cent je Video), Notiz ergänzen, Übersicht nach Themen. Siehe app/tiktok_sehen.py.


@router.post("/api/tiktok-sehen/start", status_code=202)
def tiktok_sehen_start(
    anzahl: int = Query(3, ge=1, le=1000, description="So viele noch nicht gesehene Videos (neueste zuerst)"),
    deckel: float = Query(tiktok_sehen.DECKEL_USD, gt=0, le=10, description="Höchstens so viele $ in diesem Lauf"),
    pause: float = Query(tiktok_sehen.PAUSE_S, ge=0, le=600, description="Sekunden Pause zwischen zwei Videos"),
) -> dict:
    try:
        return tiktok_sehen.start(anzahl, deckel_usd=deckel, pause_s=pause)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except tiktok_sehen.SehenFehler as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/tiktok-sehen/status")
def tiktok_sehen_status() -> dict:
    return tiktok_sehen.status()


@router.post("/api/tiktok-sehen/abbrechen")
def tiktok_sehen_abbrechen() -> dict:
    return tiktok_sehen.abbrechen()


# ------------------------------------------------------------------ Nachtarbeit
# Jarvis arbeitet nachts allein weiter, mit festem Kostendeckel (Sirs
# Entscheidung 24.09.2026: 3 $/Nacht, 4 Nächte/Monat, Stopp vor dem
# 20-$-Rahmen). Ausgelöst über NACHTARBEIT.bat (Windows-Aufgabenplanung)
# oder später einen Linux-Timer. Siehe app/nachtarbeit.py.


@router.post("/api/nachtarbeit/start", status_code=202)
def nachtarbeit_start() -> dict:
    """Startet die Nachtarbeit im Hintergrund, wenn Deckel und Monats-Limit
    es erlauben - sonst wird der Lauf übersprungen (kein Fehler, steht im
    Ergebnis). Läuft schon eine, wird keine zweite gestartet."""
    _, current = nachtarbeit.start()
    return current


@router.get("/api/nachtarbeit/status")
def nachtarbeit_status() -> dict:
    return nachtarbeit.status()


@router.get("/api/nachtarbeit/kurz")
def nachtarbeit_kurz() -> dict:
    """05.10.2026: Kurzfassung der letzten Nacht für die Mitteilung in Auron (app/nachtbericht.py)."""
    return nachtbericht.kurz()


@router.get("/api/ki/status")
def ki_status_abfragen(neu: bool = Query(False)) -> dict:
    """05.10.2026: Sind die lokalen KI-Rechner erreichbar, ist das Modell da und geladen?
    Für die Fehleranzeige in Auron (app/ki_status.py). Kostet nichts."""
    return ki_status.status(neu)


@router.post("/api/kamera/sehen")
def kamera_sehen(anfrage: dict) -> dict:
    """10.10.2026: Kamera-Modus. Ein Standbild der Webcam (Base64-JPEG) plus Frage an Claude (Haiku).
    Das Bild wird nicht gespeichert. Kosten grob 0,2-0,5 Cent je Frage."""
    try:
        return kamera.sehen(str(anfrage.get("frage") or ""), str(anfrage.get("bild") or ""), anfrage.get("verlauf"))
    except kamera.KameraFehler as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


_SUCHE_WARM = {"gestartet": False}


def _suche_aufwaermen() -> None:
    """10.10.2026: Gemessen kam die erste Antwort nach einem Neustart des Mini-PCs erst nach 31 s
    (danach 1-2 s). Ursache: Such-Modell und Vault-Index werden erst bei der ersten Frage geladen.
    Eine Probesuche im Hintergrund lädt beides vorab. Kostet nichts."""
    try:
        chat_service.search_many([("Auron Sir", 1.0)], top_k=1)
    except Exception as exc:  # noqa: BLE001 - Aufwärmen darf nie stören
        print(f"[Aufwärmen] Probesuche fehlgeschlagen: {exc}", flush=True)


@router.post("/api/ki/aufwaermen")
def ki_aufwaermen() -> dict:
    """05.10.2026: Modell auf dem Tag-Rechner vorab laden (Ladebildschirm von Auron), damit die erste
    Antwort nicht ca. 20 s auf das Laden wartet. Kostet nichts.
    10.10.2026: zusätzlich einmal je Backend-Start die Vault-Suche vorwärmen (im Hintergrund)."""
    if not _SUCHE_WARM["gestartet"]:
        _SUCHE_WARM["gestartet"] = True
        import threading  # noqa: PLC0415

        threading.Thread(target=_suche_aufwaermen, name="suche-aufwaermen", daemon=True).start()
    return ki_status.aufwaermen()


# ------------------------------------------------ Ausbauplan Phase A (23.09.2026)


@router.get("/api/kosten")
def kosten_uebersicht() -> dict:
    """Monatskosten aus dem eigenen Token-Protokoll (Schätzung, siehe app/kosten.py)."""
    return kosten.uebersicht()


@router.get("/api/schluessel")
def schluessel_status() -> list[dict]:
    """Stand der API-Schlüssel - nie der Schlüssel selbst (siehe app/schluessel.py)."""
    return schluessel.status()


@router.post("/api/schluessel")
def schluessel_setzen(request: SchluesselSetzen) -> dict:
    try:
        return schluessel.setzen(request.name, request.wert)
    except schluessel.SchluesselFehler as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/ablage")
def ablage_liste() -> list[dict]:
    return ablage.liste()


@router.post("/api/ablage")
async def ablage_hochladen(
    request: Request, name: str = Query(..., min_length=1, max_length=200, description="Dateiname")
) -> dict:
    """Datei ablegen: roher Inhalt im Anfrage-Körper, Name als Parameter
    (bewusst ohne python-multipart, siehe app/ablage.py)."""
    inhalt = await request.body()
    try:
        return ablage.speichern(name, inhalt)
    except ablage.AblageFehler as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ------------------------------------------------------- Finanzen (11.10.2026, app/finanzen.py, nur lesend)

@router.get("/api/finanzen")
def finanzen_uebersicht() -> dict:
    """Monatskosten, Abos, Verlauf. Nur gelesen, 0 Kosten."""
    from . import finanzen  # noqa: PLC0415

    return finanzen.uebersicht()


@router.post("/api/finanzen/einlesen")
def finanzen_einlesen() -> dict:
    """CSV-Exporte aus data/finanzen/eingang (und der Ablage) einlesen. 0 Kosten."""
    from . import finanzen  # noqa: PLC0415

    return finanzen.einlesen()


@router.post("/api/finanzen/hochladen")
async def finanzen_hochladen(
    request: Request, name: str = Query(..., min_length=1, max_length=200, description="Dateiname (.csv)")
) -> dict:
    """CSV-Export ablegen (roher Inhalt im Anfrage-Körper wie bei /api/ablage) und gleich einlesen."""
    from . import finanzen  # noqa: PLC0415

    try:
        gespeichert = finanzen.speichern_eingang(name, await request.body())
    except finanzen.FinanzFehler as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"gespeichert": gespeichert, **finanzen.einlesen()}


@router.get("/api/finanzen/umsaetze")
def finanzen_umsaetze(monat: str | None = Query(None, description="JJJJ-MM")) -> list[dict]:
    from . import finanzen  # noqa: PLC0415

    try:
        return finanzen.umsaetze_monat(monat)
    except finanzen.FinanzFehler as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/finanzen/kuendigung")
def finanzen_kuendigung(abo: str = Query(..., min_length=1, max_length=40)) -> dict:
    """Weg erklären und Kündigungstext entwerfen (Vorlage, 0 Kosten). Auron verschickt nichts."""
    from . import finanzen  # noqa: PLC0415

    try:
        return finanzen.kuendigung(abo)
    except finanzen.FinanzFehler as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/ablage/datei")
def ablage_datei(name: str = Query(..., min_length=1, max_length=200)) -> FileResponse:
    try:
        pfad = ablage.pfad_fuer(name)
    except (ablage.AblageFehler, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.") from exc
    return FileResponse(pfad, filename=pfad.name)


# ------------------------------------------------ Modell-Prüfstand (23.09.2026)


@router.get("/api/pruefstand/vorgaben")
def pruefstand_vorgaben() -> dict:
    """Standardfragen und -modelle für das HUD."""
    return {
        "fragen": [f["frage"] for f in pruefstand.STANDARD_FRAGEN],
        "modelle": pruefstand.standard_modelle(),
        "deckel_usd": pruefstand.DECKEL_USD,
    }


@router.post("/api/pruefstand/start", status_code=202)
def pruefstand_start(request: PruefstandRequest) -> dict:
    """Stellt dieselben Fragen an mehrere Modelle (Hintergrund, eigener Deckel)."""
    try:
        _, stand = pruefstand.start(request.fragen, request.modelle, request.deckel_usd)
    except pruefstand.PruefstandFehler as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return stand


@router.get("/api/pruefstand/status")
def pruefstand_status() -> dict:
    return pruefstand.status()


# ------------------------------------------------ TikTok (23.09.2026)


def _tiktok(aufruf):
    try:
        return aufruf()
    except tiktok.TikTokFehler as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ------------------------------------------------------------ Denkblock (23.09.2026)

def _denkblock(aufruf):
    try:
        return aufruf()
    except denkblock.DenkblockFehler as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/denkblock")
def denkblock_liste() -> dict:
    return {"notizen": _denkblock(denkblock.liste), "ordner": denkblock.ORDNER}


@router.get("/api/denkblock/{name}")
def denkblock_laden(name: str) -> dict:
    return _denkblock(lambda: denkblock.laden(name))


@router.post("/api/denkblock")
def denkblock_speichern(request: DenkblockSpeichernRequest) -> dict:
    return _denkblock(lambda: denkblock.speichern(request.name, request.text))


@router.post("/api/denkblock/{name}/mitdenken")
def denkblock_mitdenken(name: str, request: DenkblockMitdenkenRequest | None = None) -> dict:
    modell = request.modell if request else None
    try:
        return _denkblock(lambda: denkblock.mitdenken(name, modell=modell))
    except HTTPException:
        raise
    except RuntimeError as exc:  # z.B. API-Schlüssel fehlt
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Fehler bei der Anfrage an Claude: {exc}") from exc


@router.post("/api/denkblock/{name}/uebernehmen")
def denkblock_uebernehmen(name: str, request: DenkblockUebernehmenRequest) -> dict:
    return _denkblock(lambda: denkblock.uebernehmen(name, request.gedanken))


# ------------------------------------------------------------ Gesamtkarte (24.09.2026)

def _karte(aufruf):
    try:
        return aufruf()
    except gesamtkarte.KartenFehler as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/gesamtkarte")
def gesamtkarte_laden() -> dict:
    return _karte(gesamtkarte.karte)


@router.get("/api/gesamtkarte/frage")
def gesamtkarte_naechste_frage(nach: str | None = Query(None, max_length=120)) -> dict:
    """Nächste offene Frage der Karte - ohne Claude, kostet nichts."""
    return _karte(lambda: gesamtkarte.naechste_frage(nach))


@router.post("/api/gesamtkarte/{kid}/antwort")
def gesamtkarte_antwort(kid: str, request: KarteAntwortRequest) -> dict:
    """Speichert Sirs Antwort und legt einen Vorschlag für Notiz 12 an (geschrieben wird erst nach Freigabe)."""
    return _karte(lambda: gesamtkarte.antworten(kid, request.text))


@router.post("/api/gesamtkarte/{kid}/besprechen")
def gesamtkarte_besprechen(kid: str, request: KarteBesprechenRequest | None = None) -> dict:
    """Ein Claude-Aufruf zu einem Punkt der Karte (ca. 0,5-1 Cent mit Sonnet 5)."""
    r = request or KarteBesprechenRequest()
    try:
        return _karte(lambda: gesamtkarte.besprechen(kid, r.nachricht, r.verlauf, r.modell))
    except HTTPException:
        raise
    except RuntimeError as exc:  # z.B. API-Schlüssel fehlt
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Fehler bei der Anfrage an Claude: {exc}") from exc


@router.get("/api/tiktok")
def tiktok_liste() -> dict:
    """Gesammelte Links plus Stand (ist yt-dlp erreichbar?)."""
    return {"stand": tiktok.stand(), "links": tiktok.liste()}


@router.post("/api/tiktok/links")
def tiktok_links(request: TikTokLinksRequest) -> dict:
    return _tiktok(lambda: tiktok.hinzufuegen(request.text))


@router.post("/api/tiktok/reparieren")
def tiktok_reparieren() -> dict:
    """Zusammengeklebte Links trennen, hängende Abrufe zurücksetzen (23.09.2026)."""
    return _tiktok(tiktok.reparieren)


@router.post("/api/tiktok/import-ideen")
def tiktok_import_ideen() -> dict:
    """Einmal-Import der Favoritenliste aus Jarvis/Ideen/tiktok-ai-lernen-links.md."""
    return _tiktok(tiktok.ideen_importieren)


@router.get("/api/tiktok/{vid}")
def tiktok_details(vid: str) -> dict:
    return _tiktok(lambda: tiktok.details(vid))


@router.post("/api/tiktok/{vid}/abrufen")
def tiktok_abrufen(vid: str) -> dict:
    """Holt Metadaten und Untertitel EINES Videos über yt-dlp (kein Videodownload)."""
    return _tiktok(lambda: tiktok.abrufen(vid))


@router.post("/api/tiktok/{vid}/vault")
def tiktok_vault(vid: str) -> dict:
    """Legt eine Entwurfs-Notiz im Vault an (Wissen/09 - TikTok Entwürfe)."""
    return _tiktok(lambda: tiktok.in_vault(vid))


# Slides / Foto-Beiträge (26.09.2026): Bilder zuordnen, Text mit Haiku lesen.
@router.get("/api/tiktok/{vid}/bilder")
def tiktok_bilder(vid: str) -> list[dict]:
    return _tiktok(lambda: tiktok.bilder(vid))


@router.post("/api/tiktok/{vid}/bilder")
async def tiktok_bild_hoch(vid: str, request: Request) -> dict:
    """Ein Slide-Bild als roher Inhalt im Anfrage-Körper (wie /api/ablage)."""
    inhalt = await request.body()
    return _tiktok(lambda: tiktok.bild_hinzufuegen(vid, inhalt))


@router.post("/api/tiktok/{vid}/bilder/aus-ablage")
async def tiktok_bilder_aus_ablage(vid: str, request: Request) -> dict:
    """Bilder aus data/ablage zuordnen. Körper: {"namen": ["a.jpg", ...]} in Slide-Reihenfolge."""
    daten = await request.json()
    namen = [str(n) for n in (daten.get("namen") or [])] if isinstance(daten, dict) else []
    return _tiktok(lambda: tiktok.bilder_aus_ablage(vid, namen))


@router.get("/api/tiktok/{vid}/bilder/datei")
def tiktok_bild_datei(vid: str, name: str = Query(..., min_length=1, max_length=20)) -> FileResponse:
    return FileResponse(_tiktok(lambda: tiktok.bild_pfad(vid, name)))


@router.post("/api/tiktok/{vid}/bilder/lesen")
def tiktok_bilder_lesen(vid: str) -> dict:
    """Text jeder Slide mit Haiku lesen (ca. 0,3-0,4 Cent je Bild)."""
    try:
        return _tiktok(lambda: tiktok.bilder_lesen(vid))
    except HTTPException:
        raise
    except RuntimeError as exc:  # z.B. API-Schlüssel fehlt
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Fehler bei der Anfrage an Claude: {exc}") from exc


# ------------------------------------------------ Trading-Sandbox (23.09.2026)


@router.get("/api/trading-sandbox/daten")
def trading_daten() -> list[dict]:
    return trading_sandbox.datenquellen()


@router.get("/api/trading-sandbox/strategien")
def trading_strategien() -> list[dict]:
    return trading_sandbox.strategien()


@router.post("/api/trading-sandbox/backtest")
def trading_backtest(request: BacktestRequest) -> dict:
    """Backtest auf historischen Daten - keine Broker-Verbindung, kein Echtgeld."""
    try:
        return trading_sandbox.lauf(request.datenquelle, request.strategie, request.parameter, request.risiko)
    except trading_sandbox.SandboxFehler as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/sprache/status")
def sprache_status() -> dict:
    """Ob die Sprachausgabe über Fish Audio bereitsteht (ohne den Schlüssel zu zeigen)."""
    return sprache.stand()


@router.post("/api/sprache")
def sprache_erzeugen(request: SpracheRequest) -> Response:
    """Text vorlesen lassen und die fertige MP3 zurückgeben.

    Achtung: Der Text verlässt dabei den PC (siehe app/sprache.py)."""
    try:
        daten = sprache.sprich(request.text, tempo=request.tempo)
    except sprache.SpracheFehler as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content=daten,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store", "Content-Length": str(len(daten))},
    )


# --------------------------------------------------------------------- Spotify


@router.get("/api/spotify/status")
def spotify_status() -> dict:
    """Ist Spotify eingerichtet, und was läuft gerade (fürs HUD)."""
    return spotify.stand()


@router.get("/api/spotify/login")
def spotify_login() -> RedirectResponse:
    """Einmalige Freigabe. Leitet zu Spotify weiter; danach kommt der
    Erneuerungs-Schlüssel auf der Rückleitungsseite zum Eintragen in die .env."""
    try:
        return RedirectResponse(spotify.login_url())
    except spotify.SpotifyFehler as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/api/spotify/callback", response_class=HTMLResponse)
def spotify_callback(
    code: str | None = Query(None), error: str | None = Query(None)
) -> HTMLResponse:
    """Rückleitung von Spotify. Zeigt den Schlüssel EINMAL an - er wird
    absichtlich nicht automatisch gespeichert, damit nichts still in eine
    Datei geschrieben wird."""
    if error:
        return HTMLResponse(f"<h2>Spotify hat abgelehnt: {error}</h2>", status_code=400)
    if not code:
        return HTMLResponse("<h2>Kein Code erhalten.</h2>", status_code=400)
    try:
        schluessel = spotify.code_einloesen(code)
    except spotify.SpotifyFehler as exc:
        return HTMLResponse(f"<h2>Fehlgeschlagen: {exc}</h2>", status_code=502)
    return HTMLResponse(
        "<html><body style=\"font-family:sans-serif;background:#111;color:#eee;padding:40px\">"
        "<h2>Geschafft, Sir.</h2><p>Diese Zeile in <code>Jarvis\\.env</code> eintragen "
        "und das Backend neu starten:</p>"
        f"<pre style=\"background:#000;padding:16px;overflow-wrap:anywhere;white-space:pre-wrap\">"
        f"SPOTIFY_REFRESH_TOKEN={schluessel}</pre>"
        "<p>Danach dieses Fenster schließen. Der Schlüssel wird hier nur einmal angezeigt.</p>"
        "</body></html>"
    )


@router.get("/api/spotify/geraete")
def spotify_geraete() -> dict:
    """Welche Spotify-Geräte im Netz sichtbar sind (Sonos-Boxen, Handy, PC)."""
    try:
        return {"geraete": spotify.geraete()}
    except spotify.SpotifyFehler as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/api/spotify/befehl")
def spotify_befehl(request: SpotifyBefehl) -> dict:
    """Einen Musikbefehl ausführen. Kostet keinen Claude-Aufruf."""
    befehl = spotify.erkenne_befehl(request.text)
    if not befehl:
        return {"erkannt": False, "antwort": "Das war kein Musikbefehl, Sir."}
    try:
        return {"erkannt": True, "aktion": befehl["aktion"], "antwort": spotify.ausfuehren(befehl)}
    except spotify.SpotifyFehler as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/api/spotify/boxen")
def spotify_boxen(erzwingen: bool = Query(False, description="Netz neu durchsuchen statt Zwischenspeicher")) -> dict:
    """Welche Sonos-Boxen im WLAN gefunden wurden (für die Lautstärke).

    Leere Liste heißt: SSDP-Rundruf blockiert oder Boxen in einem anderen
    Netz. Dann SONOS_IPS in der .env setzen."""
    return {"boxen": sonos.boxen(erzwingen=erzwingen)}


@router.get("/api/spotify/diagnose")
def spotify_diagnose() -> dict:
    """Zeigt auf einen Blick, woran die Lautstärke scheitert.

    Kein Steuerbefehl, nur lesen. Jede Stufe wird einzeln gemeldet, damit
    sichtbar wird, ob der Gerätename stimmt, ob die Box gefunden wird und ob
    sie auf Port 1400 antwortet."""
    ergebnis: dict = {"code_stand": "2026-09-21-sonos-fix"}

    try:
        ergebnis["geraetename"] = spotify._geraetename()
    except Exception as exc:  # noqa: BLE001
        ergebnis["geraetename"] = None
        ergebnis["geraetename_fehler"] = str(exc)

    try:
        ergebnis["spotify_geraete"] = [
            {"name": g.get("name"), "typ": g.get("type"), "aktiv": g.get("is_active"),
             "lautstaerke": g.get("volume_percent")}
            for g in spotify.geraete()
        ]
    except Exception as exc:  # noqa: BLE001
        ergebnis["spotify_geraete_fehler"] = str(exc)

    try:
        gefunden = sonos.boxen(erzwingen=True)
        ergebnis["sonos_boxen"] = gefunden
        ergebnis["sonos_quelle"] = "SONOS_IPS aus der .env" if sonos._feste_ips() else "Rundruf im Netz (SSDP)"
    except Exception as exc:  # noqa: BLE001
        gefunden = []
        ergebnis["sonos_fehler"] = str(exc)

    box = sonos.finde(ergebnis.get("geraetename") or "")
    ergebnis["passende_box"] = box
    if box:
        try:
            ergebnis["box_lautstaerke"] = sonos.lautstaerke_lesen(box["ip"])
            ergebnis["urteil"] = "Alles bereit. Die Lautstärke geht direkt an die Box."
        except Exception as exc:  # noqa: BLE001
            ergebnis["box_lesen_fehler"] = str(exc)
            ergebnis["urteil"] = f"Box {box['name']} gefunden, antwortet aber nicht auf Port 1400."
    elif gefunden:
        ergebnis["urteil"] = (
            f"Boxen gefunden ({', '.join(b['name'] for b in gefunden)}), aber keine passt zum "
            f"Spotify-Gerät \"{ergebnis.get('geraetename')}\". Namen vergleichen."
        )
    else:
        ergebnis["urteil"] = (
            "Keine Sonos-Box gefunden. Rundruf vermutlich von der Firewall geblockt - "
            "SONOS_IPS in der .env setzen."
        )
    return ergebnis


@router.post("/api/spotify/lautstaerke")
def spotify_lautstaerke(wert: int = Query(..., ge=0, le=100)) -> dict:
    """Schneller Weg für den Regler im HUD. Kein Claude, kein Umweg."""
    try:
        return {"lautstaerke": spotify.lautstaerke_schnell(wert)}
    except spotify.SpotifyFehler as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ------------------------------------------------ Phase 2 (23.09.2026): Vorschläge, Gespräche, Prüfschritt


def _vorschlag(aufruf):
    try:
        return aufruf()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except (vorschlaege.VorschlagFehler, webseite.WebseitenFehler, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/vorschlaege")
def vorschlaege_liste(status: str = Query("offen", max_length=20)) -> list[dict]:
    """Angekündigte Änderungen am Vault (Phase 2.3). Noch nichts davon ist geschrieben."""
    return vorschlaege.liste(status)


@router.post("/api/vorschlaege")
def vorschlag_anlegen(request: VorschlagRequest) -> dict:
    return _vorschlag(lambda: vorschlaege.anlegen(request.text, ziel=request.ziel, grund=request.grund, quelle="hud"))


@router.post("/api/vorschlaege/{vid}/uebernehmen")
def vorschlag_uebernehmen(vid: str) -> dict:
    """Schreibt in den Vault: anhängen oder neu anlegen, nie überschreiben, nie löschen."""
    return _vorschlag(lambda: vorschlaege.uebernehmen(vid))


@router.post("/api/vorschlaege/{vid}/verwerfen")
def vorschlag_verwerfen(vid: str) -> dict:
    return _vorschlag(lambda: vorschlaege.verwerfen(vid))


@router.post("/api/webseite")
def webseite_speichern(request: WebseiteRequest) -> dict:
    """Webseite holen und als Vorschlag für eine Entwurfs-Notiz anlegen (0 Claude-Kosten)."""
    return _vorschlag(lambda: webseite.als_vorschlag(request.url.strip()))


@router.get("/api/gespraeche")
def gespraeche_tage() -> list[dict]:
    return gespraeche.tage()


@router.get("/api/gespraeche/suche")
def gespraeche_suche(q: str = Query(..., min_length=2, max_length=200)) -> list[dict]:
    return gespraeche.suchen(q, limit=30)


@router.get("/api/gespraeche/tag/{tag}")
def gespraeche_tag(tag: str) -> list[dict]:
    return _vorschlag(lambda: gespraeche.tag_laden(tag))


@router.post("/api/gespraeche/{eid}/bewertung")
def gespraech_bewerten(eid: str, request: BewertungRequest) -> dict:
    return _vorschlag(lambda: gespraeche.bewerten(eid, request.wert, request.kommentar))


@router.post("/api/gespraeche/{eid}/pruefen")
def gespraech_pruefen(eid: str) -> dict:
    """Prüfschritt (2.5): ein günstiger Haiku-Aufruf, ca. 0,2-0,4 Cent."""
    e = gespraeche.eintrag(eid)
    if e is None:
        raise HTTPException(status_code=404, detail=f"Gespräch {eid} nicht gefunden.")
    if e.get("pruefung"):
        return e["pruefung"]
    try:
        ergebnis = pruefschritt.pruefen(e.get("frage", ""), e.get("antwort", ""), e.get("quellen", []))
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Prüfung fehlgeschlagen: {exc}") from exc
    gespraeche.pruefung_merken(eid, ergebnis)
    return ergebnis


@router.post("/api/gespraeche/tagesnotiz")
def gespraeche_tagesnotiz(tag: str | None = Query(None, max_length=10)) -> dict:
    """Fasst die Gespräche eines Tages zusammen (ca. 0,3 Cent) und legt einen
    Vorschlag für die Tagesnotiz im Vault an."""
    try:
        return chat_ablauf.tagesnotiz_vorschlag(tag)
    except (ValueError, vorschlaege.VorschlagFehler) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Zusammenfassung fehlgeschlagen: {exc}") from exc


@router.get("/api/modelle")
def modelle() -> dict:
    """Modelle für die Auswahl im HUD, mit Preisen (Anthropic-Preisliste 23.09.2026)."""
    preise = aufgaben_loop.PREISE_JE_MIO_USD
    namen = {"claude-sonnet-5": "Sonnet 5", "claude-opus-5-5": "Opus 5.5", "claude-haiku-4-5-20251001": "Haiku 4.5"}
    liste = []
    for mid, name in namen.items():
        art = aufgaben_loop.modell_art(mid)
        liste.append({"id": mid, "name": name, "eingabe_usd_je_mio": preise[f"input_{art}"],
                      "ausgabe_usd_je_mio": preise[f"output_{art}"],
                      "cent_je_frage_ca": round((2000 * preise[f"input_{art}"] + 300 * preise[f"output_{art}"]) / 1e4, 2)})
    return {"standard": chat_service.DEFAULT_MODEL, "modelle": liste}


@router.get("/api/alltag/jetzt")
def alltag_jetzt() -> dict:
    return alltag.datum_uhrzeit()


# ------------------------------------------------ Phase 4 (23.09.2026): Marktdaten, Erklären, Paper Trading


def _markt(aufruf):
    try:
        return aufruf()
    except (marktdaten.MarktFehler, paper_trading.PaperFehler, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/markt/katalog")
def markt_katalog() -> list[dict]:
    return marktdaten.katalog()


@router.get("/api/markt/uebersicht")
def markt_uebersicht() -> list[dict]:
    """Letzte Kurse aus dem Speicher (kein Netz) - schnell fürs HUD."""
    return marktdaten.uebersicht()


@router.get("/api/markt/kerzen")
def markt_kerzen(symbol: str = Query(..., max_length=20), intervall: str = Query("1d", max_length=5),
                 anzahl: int = Query(500, ge=10, le=20000)) -> dict:
    """Kerzen laden (Netz nur, wenn nicht frisch), speichern, prüfen."""
    return _markt(lambda: marktdaten.kerzen(symbol, intervall, anzahl))


@router.post("/api/markt/laden", status_code=202)
def markt_alle_laden(intervalle: str = Query("1d,1h", max_length=40)) -> dict:
    """Alle Märkte im Hintergrund laden, gedrosselt (ca. 1-2 Minuten)."""
    _, stand = _markt(lambda: marktdaten.alle_laden_starten([i for i in intervalle.split(",") if i.strip()]))
    return stand


@router.get("/api/markt/laden/status")
def markt_laden_status() -> dict:
    return marktdaten.alle_laden_status()


@router.get("/api/markt/zustand")
def markt_zustand(symbol: str = Query(..., max_length=20), intervall: str = Query("1d", max_length=5)) -> dict:
    """Kennzahlen, Bot-Zustand und Erklärung in einfachem Deutsch (0 Kosten)."""
    def machen():
        w = markt_analyse.zustand(symbol, intervall)
        w["frage_an_jarvis"] = markt_analyse.frage(w)
        return w
    return _markt(machen)


@router.get("/api/paper")
def paper_stand() -> dict:
    return paper_trading.stand()


@router.post("/api/paper/order")
def paper_order(request: PaperOrderRequest) -> dict:
    return _markt(lambda: paper_trading.order(
        request.symbol, 1 if request.richtung == "kauf" else -1, request.stop, request.ziel,
        request.risiko_prozent, request.einstieg, request.notiz))


@router.post("/api/paper/{pid}/schliessen")
def paper_schliessen(pid: str, preis: float | None = Query(None, gt=0)) -> dict:
    return _markt(lambda: paper_trading.schliessen(pid, preis))


@router.post("/api/paper/aktualisieren")
def paper_aktualisieren() -> dict:
    """Offene Positionen gegen neue Kerzen prüfen (Stop/Ziel)."""
    return _markt(paper_trading.aktualisieren)


@router.post("/api/paper/zuruecksetzen")
def paper_zuruecksetzen(startkapital: float = Query(10000.0, ge=100, le=10_000_000)) -> dict:
    """Neues Übungskonto. Das alte wird vorher als Datei gesichert."""
    return _markt(lambda: paper_trading.zuruecksetzen(startkapital))


@router.put("/api/paper/regeln")
def paper_regeln(werte: dict) -> dict:
    return _markt(lambda: paper_trading.regeln_setzen(werte))


@router.post("/api/paper/bots-pruefen")
def paper_bots_pruefen(handeln: bool = Query(True)) -> list[dict]:
    """Original-Bots auf ihren Märkten prüfen; bei Signal Paper-Position über den Risiko-Wächter."""
    return _markt(lambda: paper_trading.alle_bots_pruefen(handeln))


# ------------------------------------------------ Phase 3 (23.09.2026): Whisper lokal, Piper offline


@router.get("/api/sprache/erkennen/status")
def sprache_erkennen_status() -> dict:
    return stt.stand()


@router.post("/api/sprache/erkennen")
async def sprache_erkennen(request: Request) -> dict:
    """Aufnahme (webm/ogg/wav als Rohdaten) -> Text mit Whisper auf dem PC.
    Nur wenn in den Einstellungen "lokal" gewählt und faster-whisper installiert ist."""
    from starlette.concurrency import run_in_threadpool

    daten = await request.body()
    typ = request.headers.get("content-type", "audio/webm")
    try:
        return await run_in_threadpool(stt.erkennen, daten, typ)
    except stt.SttFehler as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Spracherkennung fehlgeschlagen: {exc}") from exc


@router.get("/api/sprache/piper/status")
def sprache_piper_status() -> dict:
    return piper_tts.stand()


@router.post("/api/sprache/piper")
def sprache_piper(request: SpracheRequest) -> Response:
    """Vorlesen mit Piper - offline, nichts verlässt den PC."""
    try:
        daten = piper_tts.sprechen(request.text, tempo=request.tempo)
    except piper_tts.PiperFehler as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - z.B. Zeitüberschreitung
        raise HTTPException(status_code=502, detail=f"Piper: {exc}") from exc
    return Response(content=daten, media_type="audio/wav",
                    headers={"Cache-Control": "no-store", "Content-Length": str(len(daten))})



# ------------------------------------------------ Trading-Tagebuch (26.09.2026)
# Sirs eigene Trades aus MetaTrader, Auswertung in R und Euro, Regelprüfung. 0 Cent.


def _tagebuch(aufruf):
    try:
        return aufruf()
    except tagebuch.TagebuchFehler as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/tagebuch")
def tagebuch_stand() -> dict:
    return _tagebuch(tagebuch.stand)


@router.post("/api/tagebuch")
def tagebuch_eintragen(werte: dict) -> dict:
    return _tagebuch(lambda: tagebuch.eintragen(
        werte.get("symbol", ""), werte.get("richtung", ""), werte.get("einstieg"), werte.get("stopp"),
        werte.get("ziel"), str(werte.get("grund") or ""), werte.get("risiko_eur"), werte.get("modus")))


@router.post("/api/tagebuch/{trade_id}/schliessen")
def tagebuch_schliessen(trade_id: int, werte: dict | None = None) -> dict:
    w = werte or {}
    return _tagebuch(lambda: tagebuch.schliessen(trade_id, w.get("ausstieg"), art=w.get("art"),
                                                 eur=w.get("eur"), notiz=str(w.get("notiz") or "")))


@router.get("/api/tagebuch/auswertung")
def tagebuch_auswertung(tage: int | None = Query(None, ge=1, le=3650)) -> dict:
    return _tagebuch(lambda: {**tagebuch.auswertung(tage), "text": tagebuch.satz_auswertung(tage)})


@router.put("/api/tagebuch/einstellungen")
def tagebuch_einstellungen(werte: dict) -> dict:
    return _tagebuch(lambda: tagebuch.einstellungen_setzen(werte))


# ------------------------------------------------------------ Nachtaufträge (26.09.2026)
# Sonnet arbeitet nachts, Opus prüft (app/nachtauftraege.py). Anlegen prüft die
# Klarheit mit Haiku (ca. 0,1 Cent) - unklare Aufträge stehen auf "rueckfrage".

def _na(aufruf):
    try:
        return aufruf()
    except nachtauftraege.NachtauftragFehler as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/nachtauftraege")
def nachtauftraege_liste(status: str | None = Query(None)) -> dict:
    return {
        "auftraege": nachtauftraege.liste(status)[::-1],
        "naechster_lauf": nachtarbeit.naechster_lauf(),
        "letzte_nacht": nachtarbeit.letzte_nacht(),
        "laeuft": nachtarbeit.is_running(),
    }


@router.post("/api/nachtauftraege")
def nachtauftrag_anlegen(werte: dict) -> dict:
    art = werte.get("art") or None
    return _na(lambda: nachtauftraege.anlegen(str(werte.get("text") or ""), art=art, quelle=str(werte.get("quelle") or "hud")))


@router.post("/api/nachtauftraege/{aid}/antwort")
def nachtauftrag_antwort(aid: int, werte: dict) -> dict:
    return _na(lambda: nachtauftraege.beantworten(aid, str(werte.get("antwort") or "")))


@router.post("/api/nachtauftraege/{aid}/freigeben")
def nachtauftrag_freigeben(aid: int) -> dict:
    return _na(lambda: nachtauftraege.freigeben(aid))


@router.post("/api/nachtauftraege/{aid}/verwerfen")
def nachtauftrag_verwerfen(aid: int) -> dict:
    return _na(lambda: nachtauftraege.verwerfen(aid))


# ------------------------------------------------------------ Frage des Tages (26.09.2026)

@router.get("/api/tagesfrage")
def tagesfrage_heute() -> dict:
    return {**tagesfrage.heute(), "vault_notiz": tagesfrage.VAULT_NOTIZ}


@router.post("/api/tagesfrage")
def tagesfrage_antworten(werte: dict) -> dict:
    try:
        return tagesfrage.beantworten(str(werte.get("antwort") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ------------------------------------------------------------ Alltagsfunktionen (27.09.2026)
# Mind Maps, Projekte, Schreiben, Recherche, Tagesplan, Umwandeln, Haupt-PC.
# Dieselben Funktionen gibt es als Chat-/Sprachbefehl (app/befehle.py).

def _alltag_neu(aufruf):
    from . import hauptpc, ki_aufruf, mindmap, projekte, umwandeln

    try:
        return aufruf()
    except (ki_aufruf.KiFehler, mindmap.MindmapFehler, projekte.ProjektFehler, umwandeln.UmwandelFehler,
            hauptpc.HauptPcFehler, vorschlaege.VorschlagFehler) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/mindmaps")
def mindmaps_liste() -> list[dict]:
    from . import mindmap

    return mindmap.liste()


@router.post("/api/mindmaps")
def mindmap_neu(werte: dict) -> dict:
    from . import mindmap

    def los() -> dict:
        if werte.get("name") and werte.get("auftrag"):
            info = mindmap.ergaenzen(str(werte["name"]), str(werte["auftrag"]))
            return {**info, "text": mindmap.antwort_text(info, ergaenzt=True)}
        info = mindmap.erstellen(str(werte.get("thema") or ""))
        return {**info, "text": mindmap.antwort_text(info)}

    return _alltag_neu(los)


@router.get("/api/projekte")
def projekte_liste() -> list[dict]:
    from . import projekte

    return projekte.liste()


@router.post("/api/projekte")
def projekt_neu(werte: dict) -> dict:
    from . import projekte

    def los() -> dict:
        if werte.get("name") and werte.get("info"):
            info = projekte.ueberarbeiten(str(werte["name"]), str(werte["info"]))
        else:
            info = projekte.anlegen(str(werte.get("beschreibung") or ""))
        return {**info, "text": projekte.antwort_text(info)}

    return _alltag_neu(los)


@router.post("/api/schreiben")
def text_schreiben(werte: dict) -> dict:
    from . import schreiben

    return _alltag_neu(lambda: schreiben.schreiben(str(werte.get("auftrag") or ""),
                                                   "prompt" if werte.get("art") == "prompt" else "text"))


@router.post("/api/recherche")
def recherche_starten(werte: dict) -> dict:
    from . import recherche

    return _alltag_neu(lambda: recherche.recherchieren(str(werte.get("frage") or "")))


@router.post("/api/tagesplan")
def tagesplan_bauen(werte: dict) -> dict:
    from . import planung

    return _alltag_neu(lambda: {"text": planung.tagesplan(str(werte.get("text") or "Plan meinen Tag"))})


@router.post("/api/umwandeln")
def datei_umwandeln(werte: dict) -> dict:
    from . import umwandeln

    def los() -> dict:
        datei = str(werte.get("datei") or "").strip() or None
        quelle = umwandeln.quelle_finden(datei)[0]
        return {"quelle": quelle.name, "dateien": umwandeln.umwandeln(quelle, str(werte.get("ziel") or ""))}

    return _alltag_neu(los)


@router.get("/api/hauptpc/status")
def hauptpc_status() -> dict:
    from . import hauptpc

    if not hauptpc.ist_eingerichtet():
        return {"eingerichtet": False}
    return _alltag_neu(lambda: {"eingerichtet": True, **hauptpc.status()})


@router.get("/api/hauptpc/aktionen")
def hauptpc_aktionen() -> dict:
    from . import hauptpc

    return _alltag_neu(hauptpc.aktionen)


@router.get("/api/hauptpc/befehl_bericht")
def hauptpc_befehl_bericht(name: str) -> dict:
    from . import hauptpc

    return _alltag_neu(lambda: hauptpc.befehl_bericht(name))


@router.post("/api/hauptpc/aktion")
def hauptpc_aktion(werte: dict) -> dict:
    from . import hauptpc

    return _alltag_neu(lambda: hauptpc.aktion(str(werte.get("aktion") or ""), werte.get("ziel"),
                                              bool(werte.get("bestaetigt"))))

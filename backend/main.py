"""
Jarvis Backend - Einstiegspunkt.

Start:
    start_jarvis.bat im Jarvis-Ordner (Backend + Dashboard + Browser)
    oder von Hand:
    venv\\Scripts\\activate
    python -m uvicorn main:app --port 8000

Beim Start liest das Backend automatisch alle geänderten Vault-Notizen neu ein
(im Hintergrund, die API ist sofort erreichbar). Solange es läuft, werden
Änderungen im Vault erkannt und nach einer Minute Ruhe eingelesen
(app/vault_watcher.py). Abschalten in der .env:
    AUTO_REINDEX_ON_START=false
    AUTO_REINDEX_WATCH=false

Ohne --reload starten (siehe start_jarvis.bat): --reload startet das Backend
bei jeder Code-Änderung neu - am 19.09.2026 hat genau das einen Indexlauf unter
Volllast ausgelöst, bei dem der PC abgestürzt ist.

Testen:
    curl http://localhost:8000/api/health
    curl -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" ^
         -d "{\"message\": \"Was ist der aktuelle Stand des Jarvis Backends?\"}"
"""

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

# Windows-Konsolen nutzen standardmäßig eine Legacy-Codepage statt UTF-8 -
# Umlaute/Emojis aus dem Vault würden print()/Logging sonst zum Absturz bringen
# (siehe rag/retriever.py für den gleichen Fix).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 10.10.2026: Fehler selbst sammeln (Tracebacks, WARNUNG, ...) für den Fehlerbericht an Claude
# (app/fehlerbericht.py, "1 Starten/FEHLERBERICHT SENDEN.bat"). Abschalten: FEHLERBERICHT=aus in der .env.
from app import fehlerbericht  # noqa: E402

fehlerbericht.einrichten()

if not os.getenv("ANTHROPIC_API_KEY"):
    print("WARNUNG: ANTHROPIC_API_KEY ist nicht gesetzt - /api/chat wird fehlschlagen (.env prüfen).")

from app import einstellungen, reindex_service, vault_watcher  # noqa: E402  (nach load_dotenv, damit os.getenv() in Modulen greift)

# Im HUD gespeicherte Einstellungen überschreiben die .env-Werte
einstellungen.anwenden()
from app.routes import router  # noqa: E402


def _auto_reindex_enabled() -> bool:
    return os.getenv("AUTO_REINDEX_ON_START", "true").strip().lower() not in ("0", "false", "no", "nein", "off")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if _auto_reindex_enabled():
        try:
            reindex_service.start(full=False, warmup=True)
            print("[Reindex] Vault wird im Hintergrund auf Änderungen geprüft ...", flush=True)
        except Exception as exc:  # noqa: BLE001 - Backend soll trotzdem starten
            print(f"WARNUNG: Automatisches Neu-Einlesen nicht gestartet: {exc}", flush=True)

    # 29.09.2026: angefangenen Wissensimport weiterführen (Sammelaufträge laufen bei Anthropic weiter)
    try:
        from app import wissensimport

        if wissensimport.fortsetzen():
            print("[Wissensimport] Angefangener Lauf wird fortgesetzt.", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"WARNUNG: Wissensimport nicht fortgesetzt: {exc}", flush=True)

    # 16.10.2026 (P24): einmal beim Start prüfen, ob bei RunPod ein Pod hängt (nur mit RUNPOD_API_KEY)
    try:
        from app import gpu_miete

        gpu_miete.start_pruefung()
    except Exception as exc:  # noqa: BLE001
        print(f"WARNUNG: GPU-Start-Prüfung nicht gestartet: {exc}", flush=True)

    watcher = None
    try:
        watcher = vault_watcher.from_env()
        if watcher:
            watcher.start()
            print(
                f"[Watcher] Vault wird auf Änderungen überwacht (alle {watcher.interval_s:.0f}s, "
                f"Einlesen nach {watcher.quiet_s:.0f}s Ruhe)",
                flush=True,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"WARNUNG: Vault-Überwachung nicht gestartet: {exc}", flush=True)
        watcher = None

    yield

    if watcher:
        watcher.stop()


app = FastAPI(title="Auron Backend", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Handy-Zugang (24.09.2026): Anfragen, die nicht vom PC selbst kommen, brauchen
# den Zugangscode und dürfen nur Chat, Briefing, Denkblock und Vorschläge
# (app/handy_zugang.py). Ohne JARVIS_HANDY_TOKEN ist das Heimnetz ganz gesperrt.
from app import handy_zugang  # noqa: E402

app.middleware("http")(handy_zugang.middleware)

app.include_router(router)

# Geräte (25.09.2026, app/geraete.py): Liste, Anmeldung, Bildschirm-Brücke (WebSocket)
# und noVNC (VNC im Browser, einmal geladen von 3 Einrichten/GERAETE_EINRICHTEN.bat).
# Reine Starlette-Routen (ohne FastAPI-Parameterlogik), gleich wie in tests/test_geraete.py.
from starlette.routing import Route, WebSocketRoute  # noqa: E402
from starlette.staticfiles import StaticFiles  # noqa: E402

from app import geraete  # noqa: E402

for _pfad, _funktion, _methoden in geraete.HTTP_ROUTEN:
    app.router.routes.append(Route(_pfad, _funktion, methods=_methoden, include_in_schema=False))
app.router.routes.append(WebSocketRoute("/api/geraete/{name}/vnc", geraete.vnc_bruecke))
# Sprachmemos (02.10.2026, app/sprachmemos.py): Ideen einsprechen/hochladen und anhören.
from app import sprachmemos  # noqa: E402

for _pfad, _funktion, _methoden in sprachmemos.HTTP_ROUTEN:
    app.router.routes.append(Route(_pfad, _funktion, methods=_methoden, include_in_schema=False))

if geraete.novnc_da():
    app.mount("/novnc", StaticFiles(directory=str(geraete.NOVNC_ORDNER), html=True), name="novnc")
else:
    print("[Geräte] noVNC fehlt noch (dashboard/novnc) - 3 Einrichten/GERAETE_EINRICHTEN.bat, danach NEUSTART.bat.", flush=True)


# HUD direkt vom Backend ausliefern (24.09.2026): auf dem Mini-PC läuft kein
# Vite/npm. Aufruf dort über den SSH-Tunnel http://127.0.0.1:8001/ - die
# /api-Adressen im HUD sind relativ und gehen dadurch an dieses Backend.
_HUD = Path(__file__).resolve().parents[1] / "dashboard" / "index.html"


@app.get("/", include_in_schema=False)
def hud_seite():
    from fastapi.responses import FileResponse

    return FileResponse(_HUD, headers={"Cache-Control": "no-cache"})


# Auron (04.10.2026): neue, aufgeräumte Oberfläche. Das alte HUD bleibt unter "/" erreichbar.
_AURON = Path(__file__).resolve().parents[1] / "dashboard" / "auron.html"


@app.get("/auron", include_in_schema=False)
def auron_seite():
    from fastapi.responses import FileResponse

    return FileResponse(_AURON, headers={"Cache-Control": "no-cache"})


# 3D-Stadt für die Tour in Auron (werkstatt/stadt_3d.html samt lib/three).
_WERKSTATT = Path(__file__).resolve().parents[1] / "werkstatt"
if _WERKSTATT.is_dir():
    app.mount("/werkstatt", StaticFiles(directory=str(_WERKSTATT)), name="werkstatt")


_HANDY = Path(__file__).resolve().parents[1] / "dashboard" / "handy.html"


@app.get("/handy", include_in_schema=False)
def handy_seite():
    """Handy-Oberfläche (1 Starten/HANDY_STARTEN.bat, Aufruf vom Handy im Heimnetz)."""
    from fastapi.responses import FileResponse

    return FileResponse(_HANDY, headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000)

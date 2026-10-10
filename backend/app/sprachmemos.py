"""
Sprachmemos (02.10.2026, Claude Cowork) - Wunsch von Sir: Ideen einsprechen,
hochladen und später wieder anhören.

Ablage: Jarvis/data/sprachmemos/ (per .env SPRACHMEMOS_PATH änderbar)
    <id>.<endung>   die Aufnahme selbst
    memos.json      Liste: Titel, Zeit, Gerät, Größe, abgeschriebener Text
Der Ordner liegt im Syncthing-Ordner "jarvis" und ist damit auch am Haupt-PC.

Wege hinein:
- HUD (Seite Denkblock) und Handy-Seite: "Aufnehmen" (Mikrofon im Browser) oder
  "Datei hochladen" (z.B. Sprachmemo-App des Handys).
  Hinweis: Browser erlauben das Mikrofon nur über eine sichere Verbindung.
  Am Haupt-PC (http://127.0.0.1:8001, Tunnel) geht das. Vom Handy/Laptop über
  http://192.168.68.139:8000 blockiert der Browser das Mikrofon - dort nimmt man
  mit der Aufnahme-App des Handys auf und lädt die Datei hoch.

Abschreiben (optional, 0 €): lokal mit Whisper (app/stt.py), nur wenn
faster-whisper installiert ist. Ohne Whisper bleibt das Memo eine Audiodatei.

Regeln wie im ganzen Projekt: nichts wird gelöscht oder überschrieben.
Upload ohne python-multipart: roher Inhalt im Anfrage-Körper (wie app/ablage.py).
"""

from __future__ import annotations

import datetime
import json
import os
import re
import secrets
import threading
from pathlib import Path

MAX_BYTES = int(float(os.getenv("SPRACHMEMO_MAX_MB", "50")) * 1024 * 1024)
TITEL_MAX = 120

# Content-Type -> Endung. Nur Audio, nichts Ausführbares.
TYPEN = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/3gpp": ".3gp",
    "audio/amr": ".amr",
    "audio/flac": ".flac",
    "video/webm": ".webm",  # manche Browser melden Audio-Aufnahmen als video/webm
}
ENDUNG_ZU_TYP = {
    ".webm": "audio/webm", ".ogg": "audio/ogg", ".opus": "audio/ogg", ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4", ".aac": "audio/aac", ".wav": "audio/wav", ".3gp": "audio/3gpp",
    ".amr": "audio/amr", ".flac": "audio/flac",
}
_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
_sperre = threading.Lock()


class MemoFehler(ValueError):
    pass


def ordner() -> Path:
    pfad = Path(os.getenv("SPRACHMEMOS_PATH") or Path(__file__).resolve().parents[2] / "data" / "sprachmemos")
    pfad.mkdir(parents=True, exist_ok=True)
    return pfad


def _liste_datei() -> Path:
    return ordner() / "memos.json"


def _laden() -> list[dict]:
    try:
        daten = json.loads(_liste_datei().read_text(encoding="utf-8"))
        return [m for m in daten if isinstance(m, dict) and _ID_RE.match(str(m.get("id", "")))] if isinstance(daten, list) else []
    except (OSError, ValueError):
        return []


def _speichern(memos: list[dict]) -> None:
    ziel = _liste_datei()
    tmp = ziel.with_suffix(".tmp")
    tmp.write_text(json.dumps(memos, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, ziel)


def _jetzt() -> datetime.datetime:
    return datetime.datetime.now().astimezone()


def endung_fuer(typ: str | None, dateiname: str | None = None) -> str:
    """Endung aus Content-Type, sonst aus dem Dateinamen. Kein Audio -> Fehler."""
    t = (typ or "").split(";")[0].strip().lower()
    if t in TYPEN:
        return TYPEN[t]
    endung = Path((dateiname or "").replace("\\", "/").split("/")[-1]).suffix.lower()
    if endung in ENDUNG_ZU_TYP:
        return endung
    raise MemoFehler("Das ist keine Audiodatei (erlaubt: webm, ogg, mp3, m4a, aac, wav, 3gp, amr, flac).")


def titel_pruefen(titel: str | None, standard: str = "") -> str:
    t = re.sub(r"[\x00-\x1f]", " ", str(titel or "")).strip()
    return (t or standard)[:TITEL_MAX]


def anlegen(inhalt: bytes, typ: str | None = None, dateiname: str | None = None,
            titel: str | None = None, geraet: str = "") -> dict:
    if not inhalt:
        raise MemoFehler("Die Aufnahme ist leer.")
    if len(inhalt) > MAX_BYTES:
        raise MemoFehler(f"Aufnahme zu groß (höchstens {MAX_BYTES // (1024 * 1024)} MB).")
    endung = endung_fuer(typ, dateiname)
    jetzt = _jetzt()
    with _sperre:
        memos = _laden()
        while True:  # eindeutige ID, nichts überschreiben
            mid = jetzt.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
            if not (ordner() / f"{mid}{endung}").exists() and all(m["id"] != mid for m in memos):
                break
        (ordner() / f"{mid}{endung}").write_bytes(inhalt)
        memo = {
            "id": mid,
            "titel": titel_pruefen(titel, "Idee " + jetzt.strftime("%d.%m.%Y %H:%M")),
            "datei": f"{mid}{endung}",
            "typ": ENDUNG_ZU_TYP.get(endung, "audio/webm"),
            "bytes": len(inhalt),
            "erstellt": jetzt.isoformat(timespec="seconds"),
            "geraet": geraet or "",
            "original": Path((dateiname or "").replace("\\", "/").split("/")[-1]).name[:150],
            "text": "",
        }
        memos.append(memo)
        _speichern(memos)
    return memo


def liste() -> list[dict]:
    return sorted(_laden(), key=lambda m: m.get("erstellt", ""), reverse=True)


def holen(mid: str) -> dict:
    if not _ID_RE.match(str(mid or "")):
        raise MemoFehler("Unbekanntes Memo.")
    for m in _laden():
        if m["id"] == mid:
            return m
    raise MemoFehler("Unbekanntes Memo.")


def audio_pfad(mid: str) -> Path:
    m = holen(mid)
    pfad = ordner() / Path(m["datei"]).name
    if not pfad.is_file():
        raise MemoFehler("Die Audiodatei fehlt.")
    return pfad


def _aendern(mid: str, **felder) -> dict:
    with _sperre:
        memos = _laden()
        for m in memos:
            if m["id"] == mid:
                m.update(felder)
                _speichern(memos)
                return m
    raise MemoFehler("Unbekanntes Memo.")


def titel_setzen(mid: str, titel: str) -> dict:
    holen(mid)
    t = titel_pruefen(titel)
    if not t:
        raise MemoFehler("Der Titel ist leer.")
    return _aendern(mid, titel=t)


def abschreiben(mid: str) -> dict:
    """Lokal mit Whisper in Text umwandeln (0 €). Blockiert - in der Route im Thread-Pool."""
    from . import stt

    if not stt.installiert():
        raise MemoFehler("Abschreiben braucht Whisper (WHISPER_EINRICHTEN.bat) - ist auf diesem Rechner nicht installiert.")
    m = holen(mid)
    try:
        ergebnis = stt.erkennen(audio_pfad(mid).read_bytes(), m.get("typ") or "audio/webm")
    except stt.SttFehler as exc:
        raise MemoFehler(str(exc)) from exc
    text = (ergebnis.get("text") or "").strip() or "(nichts verstanden)"
    return _aendern(mid, text=text, abgeschrieben=_jetzt().isoformat(timespec="seconds"))


# ------------------------------------------------------ HTTP (Starlette-Stil, wie app/geraete.py)

def _fehler(exc: Exception, code: int = 400):
    from starlette.responses import JSONResponse

    return JSONResponse({"detail": str(exc)}, status_code=code)


async def api_liste(request):
    from starlette.concurrency import run_in_threadpool
    from starlette.responses import JSONResponse

    from . import stt

    memos = await run_in_threadpool(liste)
    return JSONResponse({"memos": memos, "abschreiben_moeglich": stt.installiert(),
                         "max_mb": MAX_BYTES // (1024 * 1024)}, headers={"Cache-Control": "no-store"})


async def api_hochladen(request):
    """POST /api/sprachmemos?titel=...&name=datei.m4a - roher Inhalt im Körper."""
    from starlette.concurrency import run_in_threadpool
    from starlette.responses import JSONResponse

    from . import geraete

    laenge = int(request.headers.get("content-length") or 0)
    if laenge > MAX_BYTES:
        return _fehler(MemoFehler(f"Aufnahme zu groß (höchstens {MAX_BYTES // (1024 * 1024)} MB)."), 413)
    inhalt = await request.body()
    try:
        memo = await run_in_threadpool(
            anlegen, inhalt, request.headers.get("content-type"), request.query_params.get("name"),
            request.query_params.get("titel"), geraete.aktuelles())
    except MemoFehler as exc:
        return _fehler(exc)
    return JSONResponse(memo, status_code=201)


async def api_audio(request):
    from starlette.responses import FileResponse

    mid = request.path_params.get("mid", "")
    try:
        pfad = audio_pfad(mid)
        typ = holen(mid).get("typ") or "audio/webm"
    except MemoFehler as exc:
        return _fehler(exc, 404)
    return FileResponse(pfad, media_type=typ, filename=pfad.name,
                        content_disposition_type="inline", headers={"Cache-Control": "no-cache"})


async def api_titel(request):
    from starlette.responses import JSONResponse

    try:
        return JSONResponse(titel_setzen(request.path_params.get("mid", ""), request.query_params.get("titel", "")))
    except MemoFehler as exc:
        return _fehler(exc)


async def api_abschreiben(request):
    from starlette.concurrency import run_in_threadpool
    from starlette.responses import JSONResponse

    try:
        return JSONResponse(await run_in_threadpool(abschreiben, request.path_params.get("mid", "")))
    except MemoFehler as exc:
        return _fehler(exc)


HTTP_ROUTEN = (
    ("/api/sprachmemos", api_liste, ["GET"]),
    ("/api/sprachmemos", api_hochladen, ["POST"]),
    ("/api/sprachmemos/{mid}/audio", api_audio, ["GET"]),
    ("/api/sprachmemos/{mid}/titel", api_titel, ["POST"]),
    ("/api/sprachmemos/{mid}/abschreiben", api_abschreiben, ["POST"]),
)

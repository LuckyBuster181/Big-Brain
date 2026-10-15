"""
Cloud-Prüfstand für Auron (10.10.2026, Claude Code).

Wunsch Sir: Auron soll vor der Lieferung irgendwo automatisch getestet und ausgewertet werden, damit Sir nur
fertige Versionen bekommt. Dieses Skript startet das ECHTE Backend in einer abgeschotteten Kopie und prüft es:

1. Kopie von backend, dashboard, werkstatt in einen Temp-Ordner, dazu ein erfundener Test-Vault
   (cloud_pruefstand/testvault) und ein leerer data-Ordner. Das Repo selbst bleibt unberührt.
2. Statt Ollama ein Ersatz (ersatz_ollama.py), statt Claude nichts: kein Schlüssel, keine Kosten.
   Funktionen, die nur mit Claude gehen, müssen eine freundliche Meldung liefern statt abzustürzen.
3. Prüfungen:
   - Start: Backend antwortet, Test-Vault wird eingelesen (echtes Suchmodell e5-small, falls ladbar).
   - API: jede GET-Adresse ohne Platzhalter einmal aufrufen. Serverfehler (5xx) = Fehler.
   - Chat: typische Befehle über /api/chat/stream, Antwort muss kommen und "Sir" enthalten.
   - Browser (Chromium über Playwright): Auron, jedes Modul, Agenten-Station, altes HUD, Handy, 3D-Seiten.
     Gesten (15.10.2026): Logik mit künstlicher Hand, dazu echtes MediaPipe mit der Ersatz-Kamera von Chromium.
     JavaScript-Fehler, fehlgeschlagene Anfragen und Serverfehler werden gesammelt, von jeder Seite ein Bild.
   - Server-Protokoll: Tracebacks des Backends.
4. Bericht: <ausgabe>/bericht.md (lesbar), bericht.json, bilder/*.png. Rückgabewert 1, wenn es Fehler gab.

Start (im Ordner backend, mit allen Paketen aus requirements.txt; für den Browser zusätzlich "pip install
playwright", Chromium muss vorhanden sein - in Claude-Cloud-Sitzungen liegt es unter /opt/pw-browsers):
    python -m cloud_pruefstand.lauf --ausgabe /tmp/pruefstand

Grenzen (ehrlich): echte Modelle, Sirs Vault, Mikrofon, Kamera, Haupt-PC, Mini-PC, Tunnel, Spotify, Gmail und
Kalender gibt es hier nicht. Fehler dort zeigt erst der Fehlerbericht vom PC.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

from . import ersatz_ollama

HIER = Path(__file__).resolve().parent
REPO = HIER.parents[1]

# Seiten im alten HUD, die Auron als Modul zeigt (dashboard/auron.html, SEITENNAME)
MODULE = ["alltag", "jarvis", "vault", "markt", "settings", "nacht", "denkblock", "tiktok", "labor", "karte",
          "geraete", "pc2"]
SEITEN = ([("auron", "/auron")] + [(f"modul_{m}", f"/?modul={m}&farbe=silber") for m in MODULE]
          + [("agenten", "/werkstatt/agenten/index.html?farbe=silber"),
             ("finanzen", "/werkstatt/finanzen/index.html?farbe=silber"), ("hud_alt", "/"), ("handy", "/handy"),
             ("universum", "/werkstatt/universum/universum_3d.html?auron=1"), ("stadt_3d", "/werkstatt/stadt_3d.html")])

# (Nachricht, Text, der in der Antwort stehen muss, Erklärung)
CHATS = [
    ("Wie spät ist es?", "Uhr", "Uhrzeit ohne KI"),
    ("Was ist 17 mal 23?", "391", "Rechnen ohne KI"),
    ("Was steht in meinen Notizen über das Gartenhaus?", "Sir", "normale Frage: Vault-Suche + lokale KI"),
    ("Such und schreib: Was kostet das Gartenhaus?", "Sir", "Sucher und Schreiber"),
    ("Merk dir: Prüfstand-Testeintrag", "Sir", "Diktat -> Vorschlag"),
    ("Recherchiere: beste Powerbank", "Sir", "braucht Claude: muss freundlich ablehnen, nicht abstürzen"),
    ("Zeig mir den Markt", "Sir", "Seitenwechsel-Befehl"),
    ("Welche Abos habe ich?", "3 Abos", "Finanzen: Abo-Übersicht aus den Beispiel-CSVs"),
    # 13.10.2026 (P21): nach Dateiname, nicht über die Ähnlichkeitssuche; die Septembernotiz darf nicht kommen
    ("Leg mir die neue Tagesnotiz vor", "Pruefstand-Tagesnotiz", "neueste Tagesnotiz ohne KI"),
]

# Meldungen, die nur die Cloud betreffen (kein Mikrofon, keine Lautsprecher, keine Grafikkarte, kein Netz nach außen)
CLOUD_GRENZEN = ("speechsynthesis", "speechrecognition", "getusermedia", "notallowederror", "notsupportederror",
                 "autoplay", "play() failed", "audiocontext", "webgl", "gpu", "net::err_name_not_resolved",
                 "net::err_internet_disconnected", "net::err_connection_refused", "fonts.googleapis",
                 "fonts.gstatic", "notfounderror: requested device not found")


# Antworten, die in der Cloud erwartet sind, weil der Dienst hier nicht eingerichtet ist (Adresse enthält ..., Grund)
NICHT_EINGERICHTET = [
    ("/api/kalender", "Kalender in der Cloud nicht eingerichtet"),
    ("/kalender.json", "Ersatzdatei, nur gefragt, wenn der Kalender nicht eingerichtet ist"),
    ("/api/spotify", "Spotify in der Cloud nicht eingerichtet"),
    ("/api/pc2/", "Mini-PC (PC 2) in der Cloud nicht erreichbar"),
    ("/api/hauptpc/", "Haupt-PC in der Cloud nicht erreichbar"),
    ("/modelle/iss.glb", "3D-Modell fehlt im Repo (vermutlich > 5 MB, REPO HOCHLADEN nimmt es nicht mit); Ersatz-Station greift"),
]


# 15.10.2026 (Gesten): MediaPipe-Dateien wie in werkstatt/GESTEN_HOLEN.bat (gleiche Adressen und Prüfsummen,
# tests/test_gesten.py vergleicht beide). Nicht im Repo; der Prüfstand lädt sie in den Arbeitsordner, falls sie fehlen.
MEDIAPIPE_VERSION = "0.10.35"
_MP = f"https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@{MEDIAPIPE_VERSION}"
MEDIAPIPE_DATEIEN = [
    ("vision_bundle.mjs", f"{_MP}/vision_bundle.mjs", "55d7ab624fbb70dcc5adc4ae6d7ea9cfcb569139d3dbfbf2b1deafcb966bc0fe"),
    ("wasm/vision_wasm_internal.js", f"{_MP}/wasm/vision_wasm_internal.js",
     "e7fd9858e8e8f221d9b96eddc11f8e077f263e0b7bbd79d3cbe882b134274f8c"),
    ("wasm/vision_wasm_internal.wasm", f"{_MP}/wasm/vision_wasm_internal.wasm",
     "6a5c64584c2ab61c763b6e204afbdbc7ce1caf7f5216187322bca8df94f646bc"),
    ("wasm/vision_wasm_nosimd_internal.js", f"{_MP}/wasm/vision_wasm_nosimd_internal.js",
     "438d1fe8ff7f4d946025bc211c291543c037d8a3785ed4eee60f1f521b236296"),
    ("wasm/vision_wasm_nosimd_internal.wasm", f"{_MP}/wasm/vision_wasm_nosimd_internal.wasm",
     "8a3092d34c79d3f57e6ba8592105e8a90f6b07c27891ffecd14cca428bfd3e31"),
    ("hand_landmarker.task",
     "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
     "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1"),
]


def _nicht_eingerichtet(adresse: str) -> str | None:
    return next((grund for teil, grund in NICHT_EINGERICHTET if teil in adresse), None)


def _freier_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _cloud_grenze(text: str) -> bool:
    t = (text or "").lower()
    return any(m in t for m in CLOUD_GRENZEN)


class Bericht:
    def __init__(self) -> None:
        self.fehler: list[dict] = []
        self.hinweise: list[dict] = []
        self.ok: list[str] = []
        self.abschnitte: dict[str, list[str]] = {}

    def f(self, bereich: str, text: str, **mehr) -> None:
        self.fehler.append({"bereich": bereich, "text": text, **mehr})

    def h(self, bereich: str, text: str, **mehr) -> None:
        self.hinweise.append({"bereich": bereich, "text": text, **mehr})

    def zeile(self, abschnitt: str, text: str) -> None:
        self.abschnitte.setdefault(abschnitt, []).append(text)


# ------------------------------------------------------------------ Aufbau

def arbeitsordner_bauen(ziel: Path) -> dict[str, Path]:
    weg = shutil.ignore_patterns("__pycache__", "node_modules", "*.pyc", "*.log", ".env", "venv", ".venv",
                                 "cloud_pruefstand")
    for teil in ("backend", "dashboard", "werkstatt"):
        if (REPO / teil).is_dir():
            shutil.copytree(REPO / teil, ziel / teil, ignore=weg)
    vault = ziel / "vault"
    shutil.copytree(HIER / "testvault", vault)
    (ziel / "data").mkdir()
    # 11.10.2026: erfundene Beispiel-Exporte (Volksbank, Revolut) für den Bereich Finanzen
    eingang = ziel / "data" / "finanzen" / "eingang"
    eingang.mkdir(parents=True)
    for csv_datei in (REPO / "backend" / "tests" / "daten" / "finanzen").glob("*.csv"):
        shutil.copy(csv_datei, eingang / csv_datei.name)
    return {"backend": ziel / "backend", "vault": vault, "data": ziel / "data"}


def umgebung(pfade: dict[str, Path], ollama_url: str, suchmodell: str | None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not any(w in k.upper() for w in ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWORT"))}
    env.update({
        "VAULT_PATH": str(pfade["vault"]),
        "LLM_PROVIDER": "ollama", "OLLAMA_URL": ollama_url, "OLLAMA_MODEL": ersatz_ollama.MODELL,
        "KI_TAG_RUECKFALL": "aus",
        "AUTO_REINDEX_ON_START": "true" if suchmodell else "false", "AUTO_REINDEX_WATCH": "false",
        "EMBEDDING_PAUSE_MS": "0", "EMBEDDING_THREADS": "2",
        "JARVIS_ENV_PATH": str(pfade["data"] / ".env"),
        "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", "TZ": "Europe/Berlin",
        # 12.10.2026 (P19): Alexa-Endpunkt eingeschaltet, damit seine Ablehnung geprüft wird
        "ALEXA_AKTIV": "1", "ALEXA_SKILL_ID": "amzn1.ask.skill.pruefstand",
    })
    if suchmodell:
        env["EMBEDDING_MODEL"] = suchmodell
    return env


def backend_starten(pfade: dict[str, Path], env: dict[str, str], port: int, log: Path) -> subprocess.Popen:
    datei = open(log, "w", encoding="utf-8")  # noqa: SIM115 - bleibt offen, solange der Prozess läuft
    return subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=pfade["backend"], env=env, stdout=datei, stderr=subprocess.STDOUT)


def warten_auf(url: str, sekunden: float, proc: subprocess.Popen) -> bool:
    ende = time.time() + sekunden
    while time.time() < ende:
        if proc.poll() is not None:
            return False
        try:
            if requests.get(url, timeout=2).status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


# ------------------------------------------------------------------ Prüfungen

def pruefe_einlesen(basis: str, b: Bericht, sekunden: float = 600) -> None:
    ende = time.time() + sekunden
    st: dict = {}
    while time.time() < ende:
        try:
            st = requests.get(basis + "/api/reindex/status", timeout=5).json()
        except (requests.RequestException, ValueError):
            st = {}
        if st and not st.get("running") and (st.get("finished_at") or st.get("error")):
            break
        time.sleep(2)
    if st.get("error"):
        b.f("Start", f"Vault einlesen fehlgeschlagen: {st['error']}")
    elif st.get("finished_at"):
        b.ok.append(f"Test-Vault eingelesen ({json.dumps(st.get('last_result') or {}, ensure_ascii=False)[:160]})")
    else:
        b.h("Start", f"Einlesen nach {sekunden:.0f} s nicht fertig (Stand: {json.dumps(st)[:200]})")


def pruefe_api(basis: str, b: Bericht) -> None:
    try:
        schema = requests.get(basis + "/openapi.json", timeout=20).json()
    except (requests.RequestException, ValueError) as exc:
        b.f("API", f"/openapi.json nicht lesbar: {exc}")
        return
    pfade = sorted(p for p, m in schema.get("paths", {}).items() if "get" in m and "{" not in p)
    gut = 0
    for p in pfade:
        start = time.time()
        try:
            r = requests.get(basis + p, timeout=(3, 30), stream=True)
            art = r.headers.get("content-type", "")
            inhalt = "" if "event-stream" in art else r.text[:400]
            r.close()
        except requests.RequestException as exc:
            b.f("API", f"GET {p}: keine Antwort ({exc.__class__.__name__})")
            continue
        dauer = time.time() - start
        grund = _nicht_eingerichtet(p)
        if r.status_code >= 400 and grund:
            b.h("API", f"GET {p}: {r.status_code} - {grund}")
        elif r.status_code >= 500:
            if "ANTHROPIC_API_KEY" in inhalt or "api_key" in inhalt.lower():
                b.h("API", f"GET {p}: braucht Claude-Schlüssel (in der Cloud absichtlich nicht da)", status=r.status_code)
            else:
                b.f("API", f"GET {p}: Serverfehler {r.status_code}", antwort=inhalt[:300])
        elif r.status_code >= 400:
            b.h("API", f"GET {p}: {r.status_code}", antwort=inhalt[:200])
        else:
            gut += 1
        if dauer > 10:
            b.h("API", f"GET {p}: langsam ({dauer:.1f} s)")
    b.ok.append(f"API: {gut} von {len(pfade)} GET-Adressen ohne Fehler")


def _sse(basis: str, nachricht: str) -> list[dict]:
    r = requests.post(basis + "/api/chat/stream", json={"message": nachricht}, timeout=(3, 120), stream=True)
    r.raise_for_status()
    ereignisse = []
    for zeile in r.iter_lines(decode_unicode=True):
        if zeile and zeile.startswith("data: "):
            try:
                ereignisse.append(json.loads(zeile[6:]))
            except json.JSONDecodeError:
                ereignisse.append({"typ": "kaputt", "roh": zeile[:200]})
    return ereignisse


def pruefe_chat(basis: str, b: Bericht) -> None:
    for nachricht, erwartet, was in CHATS:
        try:
            ev = _sse(basis, nachricht)
        except requests.RequestException as exc:
            b.f("Chat", f"„{nachricht}“ ({was}): keine Antwort ({exc})")
            continue
        typen = [e.get("typ") for e in ev]
        text = "".join(e.get("text", "") for e in ev if e.get("typ") in ("text", "token") and e.get("text"))
        fehler = [e for e in ev if e.get("typ") == "fehler"]
        kurz = text.replace("\n", " ")[:160]
        if "kaputt" in typen:
            b.f("Chat", f"„{nachricht}“: unlesbares Ereignis im Stream")
        if fehler:
            b.f("Chat", f"„{nachricht}“ ({was}): Fehler-Ereignis: {fehler[0].get('text') or fehler[0]}"[:300])
        elif erwartet not in text:
            b.f("Chat", f"„{nachricht}“ ({was}): „{erwartet}“ fehlt in der Antwort: {kurz!r}")
        else:
            b.ok.append(f"Chat „{nachricht}“ ({was})")
        if "kanarienvogel" in typen:
            b.h("Chat", f"„{nachricht}“: Antwort ohne „Sir“ (Kanarienvogel)")
        b.zeile("Chat-Antworten", f"- **{nachricht}** → {kurz or '(kein Text)'} · Ereignisse: {', '.join(t for t in typen if t)}")


def pruefe_finanzen(basis: str, b: Bericht) -> None:
    """Beispiel-CSVs einlesen und auswerten (Bereich Finanzen, nur lesend)."""
    try:
        e = requests.post(basis + "/api/finanzen/einlesen", timeout=30).json()
        u = requests.get(basis + "/api/finanzen", timeout=30).json()
    except (requests.RequestException, ValueError) as exc:
        b.f("Finanzen", f"keine Antwort ({exc})")
        return
    if e.get("neu") != 25 or e.get("meldungen"):
        b.f("Finanzen", f"Einlesen der Beispiel-CSVs: {e.get('text', e)!r}"[:300])
    elif len(u.get("abos", [])) != 3:
        b.f("Finanzen", f"3 Abos erwartet, gefunden: {[a.get('name') for a in u.get('abos', [])]}")
    else:
        b.ok.append("Finanzen: 25 Beispiel-Umsätze eingelesen, 3 Abos erkannt")


def pruefe_alexa(basis: str, b: Bericht) -> None:
    """Alexa-Endpunkt (P19): ohne Amazon-Signatur muss er mit 400 ablehnen, ohne Netz-Zugriff."""
    try:
        r = requests.post(basis + "/api/alexa", json={"request": {"type": "LaunchRequest"}}, timeout=30)
    except requests.RequestException as exc:
        b.f("Alexa", f"/api/alexa antwortet nicht ({exc})")
        return
    if r.status_code != 400:
        b.f("Alexa", f"Anfrage ohne Signatur: {r.status_code} statt 400 ({r.text[:120]!r})")
    else:
        b.ok.append("Alexa: Anfrage ohne Amazon-Signatur wird abgelehnt (400)")


def pruefe_fehlerbericht(basis: str, b: Bericht) -> None:
    """Sammelt das Backend seine Fehler? Die Start-Warnung zum fehlenden Schlüssel muss im Bericht stehen."""
    try:
        t = requests.get(basis + "/api/fehlerbericht", timeout=60).text
    except requests.RequestException as exc:
        b.f("Fehlerbericht", f"/api/fehlerbericht antwortet nicht ({exc})")
        return
    if not t.startswith("# Fehlerbericht Auron"):
        b.f("Fehlerbericht", f"unerwarteter Inhalt: {t[:200]!r}")
    elif "ANTHROPIC_API_KEY ist nicht gesetzt" not in t:
        b.f("Fehlerbericht", "Start-Warnung fehlt im Bericht - Fehlersammlung greift nicht")
    else:
        b.ok.append("Fehlerbericht: Backend sammelt seine Meldungen")


def mediapipe_bereitstellen(werkstatt: Path, b: Bericht) -> bool:
    """Legt die MediaPipe-Dateien in <arbeit>/werkstatt/lib/mediapipe ab (wie GESTEN_HOLEN.bat), prüft SHA256."""
    import hashlib

    ziel = werkstatt / "lib" / "mediapipe"
    for name, adresse, pruefsumme in MEDIAPIPE_DATEIEN:
        datei = ziel / name
        if datei.is_file() and hashlib.sha256(datei.read_bytes()).hexdigest() == pruefsumme:
            continue
        try:
            r = requests.get(adresse, timeout=120)
            r.raise_for_status()
        except requests.RequestException as exc:
            b.h("Gesten", f"MediaPipe-Datei {name} nicht ladbar ({str(exc)[:120]}) - echte Handerkennung nicht geprüft")
            return False
        if hashlib.sha256(r.content).hexdigest() != pruefsumme:
            b.f("Gesten", f"MediaPipe-Datei {name}: Prüfsumme falsch (Quelle geändert?)")
            return False
        datei.parent.mkdir(parents=True, exist_ok=True)
        datei.write_bytes(r.content)
    return True


def _chromium() -> str | None:
    kandidaten = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))
    return kandidaten[-1] if kandidaten else None


def pruefe_browser(basis: str, b: Bericht, ausgabe: Path, mit_mediapipe: bool = False) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        b.h("Browser", "playwright nicht installiert - Browser-Prüfung übersprungen (pip install playwright)")
        return
    bilder = ausgabe / "bilder"
    bilder.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        # 15.10.2026: Ersatz-Kamera von Chromium (Testbild, keine Hand) für die Gesten-Prüfung
        start = {"headless": True, "args": ["--autoplay-policy=no-user-gesture-required", "--use-gl=swiftshader",
                                            "--enable-unsafe-swiftshader", "--use-fake-device-for-media-stream",
                                            "--use-fake-ui-for-media-stream"]}
        pfad = _chromium()
        if pfad:
            start["executable_path"] = pfad
        try:
            browser = pw.chromium.launch(**start)
        except Exception as exc:  # noqa: BLE001
            b.h("Browser", f"Chromium startet nicht ({exc}) - Browser-Prüfung übersprungen")
            return
        for name, adresse in SEITEN:
            _seite_pruefen(browser, basis, name, adresse, b, bilder)
        _auron_chat_pruefen(browser, basis, b, bilder)
        _finanzen_kuendigen_pruefen(browser, basis, b, bilder)
        _agenten_lichter_pruefen(browser, basis, b, bilder)
        _gesten_rechnen_pruefen(browser, basis, b, bilder)
        if mit_mediapipe:
            _gesten_echt_pruefen(browser, basis, b, bilder)
            _gesten_fotos_pruefen(browser, basis, b)
        browser.close()


def _seite_pruefen(browser, basis: str, name: str, adresse: str, b: Bericht, bilder: Path) -> None:
    kontext = browser.new_context(viewport={"width": 1440, "height": 900}, locale="de-DE")
    seite = kontext.new_page()
    funde: list[tuple[str, str]] = []
    seite.on("console", lambda m: funde.append(("Konsole", m.text))
             if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
    seite.on("pageerror", lambda e: funde.append(("JavaScript", str(e))))
    seite.on("requestfailed", lambda r: funde.append(("Anfrage", f"{r.method} {r.url} - {r.failure}")))
    seite.on("response", lambda r: funde.append(("Antwort", f"{r.status} {r.request.method} {r.url}"))
             if r.status >= 400 else None)
    try:
        seite.goto(basis + adresse, wait_until="load", timeout=30000)
        seite.wait_for_timeout(6000)   # Seiten laden Daten nach, 3D braucht Zeit
    except Exception as exc:  # noqa: BLE001
        funde.append(("Laden", str(exc)[:300]))
    try:
        seite.screenshot(path=str(bilder / f"{name}.png"), timeout=60000)
    except Exception as exc:  # noqa: BLE001 - ohne Grafikkarte (GitHub) ist 3D manchmal zu langsam fürs Foto
        b.h("Browser", f"{name}: kein Bildschirmfoto ({str(exc).splitlines()[0][:120]})")
    kontext.close()
    echte = 0
    for art, text in dict.fromkeys(funde):   # gleiche Meldung nur einmal
        grund = _nicht_eingerichtet(text)
        if grund:
            b.h("Browser", f"{name}: {text[:160]} - {grund}")
        elif art in ("Antwort", "Anfrage") and not text.split(" ", 2)[-1].startswith(basis) and basis not in text:
            b.h("Browser", f"{name}: externe Adresse: {text[:200]}")
        elif _cloud_grenze(text):
            b.h("Browser", f"{name}: {art}: {text[:200]} (Cloud-Grenze)")
        else:
            echte += 1
            b.f("Browser", f"{name}: {art}: {text[:300]}", seite=adresse)
    if not echte:
        b.ok.append(f"Seite {name} ({adresse})")


def _auron_chat_pruefen(browser, basis: str, b: Bericht, bilder: Path) -> None:
    """In Auron eine Frage tippen und auf die Antwort warten (wie Sir es tut)."""
    kontext = browser.new_context(viewport={"width": 1440, "height": 900}, locale="de-DE")
    seite = kontext.new_page()
    try:
        seite.goto(basis + "/auron", wait_until="load", timeout=30000)
        seite.wait_for_timeout(3000)
        for knopf in ("#tourUeberspringen",):
            if seite.locator(knopf).is_visible():
                seite.locator(knopf).click()
        seite.fill("#frage", "Was ist 6 mal 7?")
        seite.press("#frage", "Enter")
        seite.wait_for_function("document.body.innerText.includes('42')", timeout=30000)
        seite.screenshot(path=str(bilder / "auron_chat.png"))
        b.ok.append("Auron: Frage getippt, Antwort erschienen")
    except Exception as exc:  # noqa: BLE001
        try:
            seite.screenshot(path=str(bilder / "auron_chat_fehler.png"))
        except Exception:  # noqa: BLE001
            pass
        b.f("Browser", f"Auron-Chat: keine Antwort im Fenster ({str(exc)[:200]})")
    kontext.close()


def _finanzen_kuendigen_pruefen(browser, basis: str, b: Bericht, bilder: Path) -> None:
    """Im Bereich Finanzen auf "Kündigen" klicken: Wege und Kündigungstext müssen erscheinen."""
    kontext = browser.new_context(viewport={"width": 1440, "height": 900}, locale="de-DE")
    seite = kontext.new_page()
    try:
        seite.goto(basis + "/werkstatt/finanzen/index.html?farbe=silber", wait_until="load", timeout=30000)
        seite.get_by_role("button", name="Kündigen").first.click(timeout=15000)
        seite.wait_for_function("document.getElementById('kText').value.includes('hiermit kündige ich')", timeout=15000)
        seite.screenshot(path=str(bilder / "finanzen_kuendigen.png"), timeout=60000)
        b.ok.append("Finanzen: Kündigungshilfe erscheint mit Text")
    except Exception as exc:  # noqa: BLE001
        b.f("Browser", f"Finanzen-Kündigungshilfe: {str(exc).splitlines()[0][:200]}")
    kontext.close()


def _agenten_lichter_pruefen(browser, basis: str, b: Bericht, bilder: Path) -> None:
    """Agenten-Station: Lichter nur bei aktivem Agent, aus ohne Aktivität. Die Ersatz-KI antwortet zu schnell für
    einen echten "arbeitet"-Zustand - deshalb wird /api/agenten im Browser durch eine Antwort mit aktivem Sucher ersetzt."""
    try:
        echt = requests.get(basis + "/api/agenten", timeout=20).json()
    except (requests.RequestException, ValueError) as exc:
        b.f("Agenten", f"/api/agenten antwortet nicht ({exc})")
        return
    ausgeblendet = {"gespraech", "alltag", "briefing", "pruefstand"} & {a["id"] for a in echt.get("agenten", [])}
    if ausgeblendet:
        b.f("Agenten", f"ausgeblendete Agenten noch sichtbar: {sorted(ausgeblendet)}")
    aktiv = json.loads(json.dumps(echt))
    for a in aktiv.get("agenten", []):
        if a["id"] == "sucher":
            a.update(zustand="arbeitet", text="fragt Ersatz-KI", seit_s=3)
    antwort = {"daten": aktiv}
    kontext = browser.new_context(viewport={"width": 1440, "height": 900}, locale="de-DE")
    seite = kontext.new_page()
    try:
        seite.route("**/api/agenten*", lambda r: r.fulfill(json=antwort["daten"]))
        seite.goto(basis + "/werkstatt/agenten/index.html?farbe=gold", wait_until="load", timeout=30000)
        seite.wait_for_timeout(1500)
        an = seite.evaluate("({...window.lichter})")
        seite.screenshot(path=str(bilder / "agenten_lichter.png"), timeout=60000)
        antwort["daten"] = echt
        seite.wait_for_timeout(3600)   # nächste Abfrage nach 3 s: niemand aktiv
        aus = seite.evaluate("({...window.lichter})")
        if not (an.get("laeuft") and an.get("punkte", 0) > 0):
            b.f("Agenten", f"keine Lichter bei aktivem Sucher ({an})")
        elif aus.get("laeuft"):
            b.f("Agenten", "Lichter laufen ohne aktiven Agenten weiter")
        else:
            b.ok.append("Agenten-Station: Lichter bei aktivem Agent, aus ohne Aktivität")
    except Exception as exc:  # noqa: BLE001
        b.f("Browser", f"Agenten-Lichter: {str(exc).splitlines()[0][:200]}")
    kontext.close()


# Künstliche Hand (21 Punkte) für die Gesten-Prüfung: Zeigefingerspitze landet genau auf (sx, sy) der Seite.
_HAND_JS = """
window.__hand = (pose, sx, sy) => {
  const s = 16 / 9, r = AuronGesten.EINSTELLUNG.rand;
  const u = { 0: [0, 0], 1: [-0.08, -0.04], 2: [-0.13, -0.08], 3: [-0.17, -0.12], 4: [-0.23, -0.17],
    5: [-0.05, -0.18], 6: [-0.06, -0.26], 7: [-0.065, -0.31], 8: [-0.07, -0.36],
    9: [0, -0.19], 10: [0, -0.28], 11: [0, -0.33], 12: [0, -0.38],
    13: [0.045, -0.18], 14: [0.05, -0.26], 15: [0.052, -0.3], 16: [0.055, -0.34],
    17: [0.085, -0.16], 18: [0.095, -0.22], 19: [0.1, -0.26], 20: [0.11, -0.29] };
  if (pose !== "offen") {   // Mittel-, Ring- und kleiner Finger eingerollt, Daumen angelegt
    Object.assign(u, { 10: [0, -0.25], 11: [0, -0.2], 12: [0, -0.17], 14: [0.05, -0.23], 15: [0.05, -0.19], 16: [0.05, -0.16],
      18: [0.09, -0.2], 19: [0.09, -0.17], 20: [0.09, -0.14], 3: [-0.06, -0.12], 4: [-0.03, -0.14] });
  }
  if (pose === "pinch") u[4] = [u[8][0] + 0.02, u[8][1] + 0.01];
  if (pose === "faust") Object.assign(u, { 6: [-0.06, -0.24], 7: [-0.05, -0.2], 8: [-0.045, -0.18], 4: [-0.04, -0.19] });
  const nx = sx / (innerWidth - 1), ny = sy / (innerHeight - 1);
  const x8 = 1 - r - nx * (1 - 2 * r), y8 = r + ny * (1 - 2 * r);
  const p = [];
  for (let i = 0; i < 21; i++) p.push({ x: x8 + (u[i][0] - u[8][0]) / s, y: y8 + (u[i][1] - u[8][1]), z: 0 });
  return p;
};
window.__zeit = 100000;
window.__bilder = (pose, sx, sy, n) => {
  for (let i = 0; i < n; i++) { window.__zeit += 67; AuronGesten.verarbeiten(pose ? window.__hand(pose, sx, sy) : null, window.__zeit, 16 / 9); }
};
window.__zeiger = () => {
  const e = document.getElementById("gestenZeiger"), m = /translate\\((-?[\\d.]+)px, ?(-?[\\d.]+)px/.exec(e.style.transform) || [0, NaN, NaN];
  return { da: e.classList.contains("da"), ueber: e.classList.contains("ueber"), x: +m[1], y: +m[2] };
};
"""


def _auron_oeffnen(browser, basis: str, kamera: bool = False):
    kontext = browser.new_context(viewport={"width": 1440, "height": 900}, locale="de-DE",
                                  permissions=["camera"] if kamera else [])
    seite = kontext.new_page()
    seite.goto(basis + "/auron", wait_until="load", timeout=30000)
    seite.wait_for_timeout(3000)
    if seite.locator("#tourUeberspringen").is_visible():
        seite.locator("#tourUeberspringen").click()
        seite.wait_for_timeout(1200)
    return kontext, seite


def _gesten_rechnen_pruefen(browser, basis: str, b: Bericht, bilder: Path) -> None:
    """Gesten-Logik mit künstlicher Hand (ohne Kamera, ohne MediaPipe): Zeigen, Pinch = Klick, offene Hand = Zurück."""
    kontext, seite = _auron_oeffnen(browser, basis)
    schritt = "Start"
    try:
        if not seite.evaluate("!!window.AuronGesten"):
            raise AssertionError("window.AuronGesten fehlt (werkstatt/gesten/gesten.js nicht geladen)")
        seite.evaluate(_HAND_JS)
        k = seite.locator("#knopfBereiche").bounding_box()
        x, y = k["x"] + k["width"] / 2, k["y"] + k["height"] / 2
        schritt = "Zeigen"
        seite.evaluate(f"__bilder('zeigen', {x}, {y}, 5)")
        z = seite.evaluate("__zeiger()")
        if not (z["da"] and z["ueber"] and abs(z["x"] - x) <= 3 and abs(z["y"] - y) <= 3):
            raise AssertionError(f"Punkt nicht auf dem Knopf: {z}, erwartet {round(x)}/{round(y)}")
        schritt = "Pinch 1 Bild (darf nicht klicken)"
        seite.evaluate(f"__bilder('pinch', {x}, {y}, 1); __bilder('zeigen', {x}, {y}, 2)")
        if seite.evaluate("!document.getElementById('schleier').hidden"):
            raise AssertionError("ein einzelnes Pinch-Bild hat schon geklickt")
        schritt = "Pinch = Klick"
        seite.evaluate(f"__bilder('pinch', {x}, {y}, 3); __bilder('zeigen', {x}, {y}, 3)")
        if seite.evaluate("document.getElementById('schleier').hidden"):
            raise AssertionError("Pinch hat 'Alle Bereiche' nicht geöffnet")
        if "Klick" not in seite.evaluate("AuronGesten.info().geste"):
            raise AssertionError("letzte Geste ist nicht 'Klick'")
        seite.screenshot(path=str(bilder / "gesten_klick.png"))
        schritt = "Offene Hand kurz (darf nicht schließen)"
        seite.evaluate(f"__bilder('offen', {x}, {y}, 6); __bilder('zeigen', {x}, {y}, 2)")
        if seite.evaluate("document.getElementById('schleier').hidden"):
            raise AssertionError("offene Hand für 0,4 s hat schon geschlossen")
        schritt = "Offene Hand halten = Zurück"
        seite.evaluate(f"__bilder('offen', {x}, {y}, 17)")
        if not seite.evaluate("document.getElementById('schleier').hidden"):
            raise AssertionError("offene Hand (1,1 s) hat 'Alle Bereiche' nicht geschlossen")
        if "Zurück" not in seite.evaluate("AuronGesten.info().geste"):
            raise AssertionError("letzte Geste ist nicht 'Zurück'")
        schritt = "Faust (darf nicht klicken)"
        seite.evaluate(f"__bilder('zeigen', {x}, {y}, 3); __bilder('faust', {x}, {y}, 4); __bilder('zeigen', {x}, {y}, 3)")
        if not seite.evaluate("document.getElementById('schleier').hidden"):
            raise AssertionError("eine Faust hat geklickt")
        schritt = "Hand weg"
        seite.evaluate("__bilder(null, 0, 0, 12)")
        if seite.evaluate("__zeiger().da"):
            raise AssertionError("Punkt bleibt sichtbar, obwohl keine Hand mehr da ist")
        b.ok.append("Gesten (künstliche Hand): Zeigen, Pinch = Klick, offene Hand = Zurück, kein Fehlklick (1 Bild, Faust)")
    except Exception as exc:  # noqa: BLE001
        b.f("Gesten", f"Logik, Schritt '{schritt}': {str(exc).splitlines()[0][:250]}")
    kontext.close()


# Echte Handfotos aus den MediaPipe-Testdaten (gleicher Server wie das Modell): (Datei, Prüfsumme, Erwartung)
GESTEN_FOTOS = [
    ("fist.jpg", "43fa1cabf3f90d574accc9a56986e2ee48638ce59fc65af1846487f73bb2ef24", "faust"),
    ("pointing_up.jpg", "ecf8ca2611d08fa25948a4fc10710af9120e88243a54da6356bacea17ff3e36e", "zeigen"),
    ("victory.jpg", "84cb8853e3df614e0cb5c93a25e3e2f38ea5e4f92fd428ee7d867ed3479d5764", "zeigen"),
    ("right_hands.jpg", "4b5134daa4cb60465535239535f9f74c2842aba3aa5fd30bf04ef5678f93d87f", "offen"),
]
_FOTO_JS = """async (fotos) => {
  const mp = await import("/werkstatt/lib/mediapipe/vision_bundle.mjs");
  const f = await mp.FilesetResolver.forVisionTasks("/werkstatt/lib/mediapipe/wasm");
  const h = await mp.HandLandmarker.createFromOptions(f, { baseOptions: { modelAssetPath: "/werkstatt/lib/mediapipe/hand_landmarker.task",
    delegate: "CPU" }, runningMode: "IMAGE", numHands: 2 });
  const R = AuronGesten.rechnen, E = AuronGesten.EINSTELLUNG, aus = {};
  for (const [name, daten] of fotos) {
    const bild = new Image(); bild.src = daten; await bild.decode();
    const s = bild.naturalWidth / bild.naturalHeight;
    aus[name] = h.detect(bild).landmarks.map((p) => { const a = R.einordnen(p, s);
      return a.offen ? "offen" : a.faust ? "faust" : a.pinch < E.pinchAn ? "pinch" : "zeigen"; });
  }
  h.close();
  return aus;
}"""


def _gesten_fotos_pruefen(browser, basis: str, b: Bericht) -> None:
    """Echtes Modell an echten Händen: Faust darf nie Klick sein, offene Hände müssen als offen gelten."""
    import base64
    import hashlib

    fotos = []
    for name, pruefsumme, _ in GESTEN_FOTOS:
        try:
            r = requests.get(f"https://storage.googleapis.com/mediapipe-assets/{name}", timeout=60)
            r.raise_for_status()
        except requests.RequestException as exc:
            b.h("Gesten", f"Testfoto {name} nicht ladbar ({str(exc)[:100]}) - Fotoprüfung übersprungen")
            return
        if hashlib.sha256(r.content).hexdigest() != pruefsumme:
            b.h("Gesten", f"Testfoto {name} hat sich geändert - Fotoprüfung übersprungen")
            return
        fotos.append([name, "data:image/jpeg;base64," + base64.b64encode(r.content).decode()])
    kontext, seite = _auron_oeffnen(browser, basis)
    try:
        erg = seite.evaluate(_FOTO_JS, fotos)
        falsch = [f"{name}: {erg.get(name)} statt {soll}" for name, _, soll in GESTEN_FOTOS
                  if not erg.get(name) or any(art != soll for art in erg[name])]
        if falsch:
            b.f("Gesten", "Fotos falsch eingeordnet: " + "; ".join(falsch))
        else:
            b.ok.append("Gesten (echtes Modell, echte Fotos): Faust kein Klick, Zeigen und Victory kein Klick, offene Hände offen")
        b.zeile("Gesten", "- Fotos: " + ", ".join(f"{k} = {'/'.join(v)}" for k, v in erg.items()))
    except Exception as exc:  # noqa: BLE001
        b.f("Gesten", f"Fotoprüfung: {str(exc).splitlines()[0][:250]}")
    kontext.close()


def _gesten_echt_pruefen(browser, basis: str, b: Bericht, bilder: Path) -> None:
    """Echtes MediaPipe mit der Ersatz-Kamera von Chromium: lädt, höchstens 15/s, Pause bei unsichtbarer Seite,
    Sprachbefehl aus, und mit Gesten an geht eine normale Frage NICHT an Claude (/api/kamera/sehen)."""
    kontext, seite = _auron_oeffnen(browser, basis, kamera=True)
    anfragen: list[str] = []
    seite.on("request", lambda r: anfragen.append(r.url))
    fehler: list[str] = []
    seite.on("pageerror", lambda e: fehler.append(str(e)))
    schritt = "Knopf Gesten"
    try:
        seite.click("#gestenKnopf")
        seite.wait_for_function("AuronGesten.info().an || /nicht|fehlen/.test(document.getElementById('hinweis').textContent)",
                                timeout=90000)
        if not seite.evaluate("AuronGesten.info().an"):
            raise AssertionError("startet nicht: " + seite.inner_text("#hinweis"))
        schritt = "Auswertungen"
        seite.wait_for_timeout(4000)   # ohne Grafikkarte (Cloud) ca. 0,3 s je Auswertung, am PC mit Grafikkarte viel schneller
        i = seite.evaluate("AuronGesten.info()")
        if i["gesamt"] < 3 or i["proSekunde"] > 15:
            raise AssertionError(f"{i['gesamt']} Auswertungen in 4 s, {i['proSekunde']} pro Sekunde (erwartet mind. 3, höchstens 15/s)")
        anzeige = seite.inner_text("#gestenAnzeige")
        if "/s" not in anzeige or not seite.is_visible("#kamera") or seite.inner_text("#kameraStatus") != "Gesten an":
            raise AssertionError(f"Anzeige fehlt: '{anzeige}', Status '{seite.inner_text('#kameraStatus')}'")
        b.zeile("Gesten", f"- Ersatz-Kamera: {i['proSekunde']} Auswertungen/s, {i['rechner']}, {i['msJeAuswertung']} ms je Auswertung, "
                          f"Anzeige: {anzeige.replace(chr(10), ' / ')}")
        seite.screenshot(path=str(bilder / "gesten_an.png"))
        schritt = "Pause bei unsichtbarer Seite"
        seite.evaluate("Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });"
                       " document.dispatchEvent(new Event('visibilitychange'))")
        seite.wait_for_timeout(1500)
        i = seite.evaluate("AuronGesten.info()")
        seite.wait_for_timeout(1500)
        if not i["pause"] or i["proSekunde"] != 0 or seite.evaluate("AuronGesten.info().gesamt") != i["gesamt"]:
            raise AssertionError(f"keine Pause: {i}")
        seite.evaluate("Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });"
                       " document.dispatchEvent(new Event('visibilitychange'))")
        seite.wait_for_function(f"AuronGesten.info().gesamt >= {i['gesamt'] + 2}", timeout=15000)   # läuft weiter
        schritt = "Frage mit Gesten an (kein Claude-Bild)"
        seite.fill("#frage", "Was ist 6 mal 7?")
        seite.press("#frage", "Enter")
        seite.wait_for_function("document.body.innerText.includes('42')", timeout=30000)
        if any("/api/kamera/sehen" in a for a in anfragen):
            raise AssertionError("Frage ging mit Kamerabild an Claude, obwohl nur Gesten an sind")
        schritt = "Sprachbefehl 'Auron, Gesten aus'"
        seite.wait_for_timeout(1500)
        chat_vorher = sum("/api/chat" in a for a in anfragen)
        seite.fill("#frage", "Auron, Gesten aus")
        seite.press("#frage", "Enter")
        seite.wait_for_function("!AuronGesten.info().an && document.getElementById('kamera').hidden", timeout=10000)
        if sum("/api/chat" in a for a in anfragen) != chat_vorher or "Gesten sind aus" not in seite.inner_text("#verlaufInnen"):
            raise AssertionError("'Gesten aus' ging an den Chat statt an die Gesten-Weiche")
        if fehler:
            raise AssertionError(f"JavaScript-Fehler: {fehler[0][:200]}")
        b.ok.append("Gesten (echtes MediaPipe, Ersatz-Kamera): lädt, höchstens 15/s, Pause bei unsichtbarer Seite, "
                    "kein Bild an Claude, 'Gesten aus' per Satz")
    except Exception as exc:  # noqa: BLE001
        try:
            seite.screenshot(path=str(bilder / "gesten_fehler.png"))
        except Exception:  # noqa: BLE001
            pass
        b.f("Gesten", f"MediaPipe, Schritt '{schritt}': {str(exc).splitlines()[0][:250]}")
    kontext.close()


def pruefe_protokoll(log: Path, b: Bericht) -> None:
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    zeilen = text.splitlines()
    gefunden = 0
    for i, z in enumerate(zeilen):
        if z.startswith("Traceback"):
            ende = next((j for j in range(i + 1, min(i + 60, len(zeilen))) if zeilen[j] and not zeilen[j].startswith(" ")), i + 1)
            letzte = zeilen[ende] if ende < len(zeilen) else ""
            if _cloud_grenze(letzte) or "ANTHROPIC_API_KEY" in letzte:
                b.h("Server", f"Traceback (erwartet ohne Schlüssel/Cloud): {letzte[:200]}")
            else:
                gefunden += 1
                b.f("Server", f"Traceback im Backend: {letzte[:300]}", auszug="\n".join(zeilen[max(i, ende - 8):ende + 1]))
    for z in zeilen:
        if "WARNUNG" in z or "[Fehler]" in z:
            b.zeile("Server-Warnungen", f"- {z[:200]}")
    if not gefunden:
        b.ok.append("Server-Protokoll ohne unerwartete Tracebacks")


# ------------------------------------------------------------------ Bericht

def bericht_schreiben(b: Bericht, ausgabe: Path, dauer: float, log: Path) -> None:
    jetzt = _dt.datetime.now().strftime("%d.%m.%Y %H:%M")
    zeilen = [f"# Cloud-Prüfstand Auron - {jetzt}", "",
              f"**Ergebnis:** {'FEHLER' if b.fehler else 'OK'} · {len(b.fehler)} Fehler · {len(b.hinweise)} Hinweise · "
              f"{len(b.ok)} Prüfungen bestanden · Dauer {dauer:.0f} s", ""]
    if b.fehler:
        zeilen += ["## Fehler", ""] + [f"- [{f['bereich']}] {f['text']}" for f in b.fehler] + [""]
    if b.hinweise:
        zeilen += ["## Hinweise (meist Grenzen der Cloud, kein Handlungsbedarf)", ""]
        zeilen += [f"- [{h['bereich']}] {h['text']}" for h in b.hinweise] + [""]
    zeilen += ["## Bestanden", ""] + [f"- {t}" for t in b.ok] + [""]
    for titel, inhalt in b.abschnitte.items():
        zeilen += [f"## {titel}", ""] + inhalt[:60] + [""]
    zeilen += ["## Nicht geprüft (gibt es in der Cloud nicht)", "",
               "Echte Modelle (Ollama/Claude), Sirs Vault, Mikrofon, Kamera, Lautsprecher, Haupt-PC, Mini-PC, Tunnel, "
               "Spotify, Gmail, Kalender. Dafür ist der Fehlerbericht vom PC da.", ""]
    (ausgabe / "bericht.md").write_text("\n".join(zeilen), encoding="utf-8")
    (ausgabe / "bericht.json").write_text(json.dumps({"fehler": b.fehler, "hinweise": b.hinweise, "ok": b.ok},
                                                     ensure_ascii=False, indent=2), encoding="utf-8")
    if log.exists():
        shutil.copy(log, ausgabe / "backend.log")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Cloud-Prüfstand für Auron")
    ap.add_argument("--ausgabe", default=str(Path(tempfile.gettempdir()) / "auron_pruefstand"))
    ap.add_argument("--ohne-browser", action="store_true")
    ap.add_argument("--suchmodell", default="e5-small", help="EMBEDDING_MODEL; 'aus' = Vault nicht einlesen")
    ap.add_argument("--behalten", action="store_true", help="Arbeitsordner nicht löschen (zum Nachsehen)")
    a = ap.parse_args(argv)

    beginn = time.time()
    ausgabe = Path(a.ausgabe)
    shutil.rmtree(ausgabe, ignore_errors=True)
    ausgabe.mkdir(parents=True)
    arbeit = Path(tempfile.mkdtemp(prefix="auron_arbeit_"))
    b = Bericht()
    proc = None
    log = arbeit / "backend.log"
    server = None
    try:
        pfade = arbeitsordner_bauen(arbeit)
        mit_mediapipe = not a.ohne_browser and mediapipe_bereitstellen(arbeit / "werkstatt", b)
        server, ollama_url = ersatz_ollama.starten()
        suchmodell = None if a.suchmodell == "aus" else a.suchmodell
        port = _freier_port()
        basis = f"http://127.0.0.1:{port}"
        proc = backend_starten(pfade, umgebung(pfade, ollama_url, suchmodell), port, log)
        print(f"[Prüfstand] Backend startet auf {basis} ...", flush=True)
        if not warten_auf(basis + "/api/health", 120, proc):
            b.f("Start", "Backend startet nicht (siehe backend.log)")
        else:
            b.ok.append("Backend gestartet, /api/health antwortet")
            if suchmodell:
                print("[Prüfstand] Test-Vault wird eingelesen ...", flush=True)
                pruefe_einlesen(basis, b)
            print("[Prüfstand] API ...", flush=True)
            pruefe_api(basis, b)
            print("[Prüfstand] Finanzen ...", flush=True)
            pruefe_finanzen(basis, b)
            print("[Prüfstand] Chat ...", flush=True)
            pruefe_chat(basis, b)
            pruefe_alexa(basis, b)
            pruefe_fehlerbericht(basis, b)
            if not a.ohne_browser:
                print("[Prüfstand] Browser ...", flush=True)
                pruefe_browser(basis, b, ausgabe, mit_mediapipe)
            b.zeile("Ersatz-KI", f"- {len(ersatz_ollama.ANFRAGEN)} Anfragen an das Ersatz-Modell (statt Ollama)")
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        if server:
            server.shutdown()
        pruefe_protokoll(log, b)
        bericht_schreiben(b, ausgabe, time.time() - beginn, log)
        if not a.behalten:
            shutil.rmtree(arbeit, ignore_errors=True)
    for f in b.fehler:
        print(f"[Prüfstand] FEHLER [{f['bereich']}] {f['text']}"[:500], flush=True)
    print(f"[Prüfstand] {'FEHLER' if b.fehler else 'OK'}: {len(b.fehler)} Fehler, {len(b.hinweise)} Hinweise, "
          f"{len(b.ok)} bestanden. Bericht: {ausgabe / 'bericht.md'}", flush=True)
    return 1 if b.fehler else 0


if __name__ == "__main__":
    sys.exit(main())

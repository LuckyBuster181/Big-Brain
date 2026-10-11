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


def _chromium() -> str | None:
    kandidaten = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))
    return kandidaten[-1] if kandidaten else None


def pruefe_browser(basis: str, b: Bericht, ausgabe: Path) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        b.h("Browser", "playwright nicht installiert - Browser-Prüfung übersprungen (pip install playwright)")
        return
    bilder = ausgabe / "bilder"
    bilder.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        start = {"headless": True, "args": ["--autoplay-policy=no-user-gesture-required", "--use-gl=swiftshader",
                                            "--enable-unsafe-swiftshader"]}
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
            pruefe_fehlerbericht(basis, b)
            if not a.ohne_browser:
                print("[Prüfstand] Browser ...", flush=True)
                pruefe_browser(basis, b, ausgabe)
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

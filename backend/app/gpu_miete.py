"""
GPU-Miete mit Selbstabschaltung (P24, 16.10.2026, Claude Code).

Auron mietet für eine Code-Aufgabe (meist nachts) kurz einen RunPod-Pod mit GPU, lässt ein lokales Ollama-
Code-Modell (Standard qwen3-coder:30b) dort rechnen und LÖSCHT den Pod danach IMMER (terminate, nie nur stoppen).
Anlass: Bei centron wurde ein nur ausgeschalteter Server 24 Stunden voll berechnet (27,54 EUR). Das darf nie wieder
passieren. Deshalb gibt es drei voneinander unabhängige Sicherungen gegen einen vergessenen Pod:

  1. finally-Block: Jede Miete (sitzung()) löscht den Pod im finally, mit Wiederholungen, und prüft danach über
     die API, dass er weg ist. Auch wenn der Start nur halb gelang (Antwort verloren, Pod aber angelegt), wird per
     Namen aufgeräumt. Schlägt das Löschen fehl: Alarm (Ampel rot, Fehlerbericht, Alexa), neue Mieten gesperrt.
  2. Notbremse im selben Prozess: Ein Zeitgeber löscht den Pod nach der erlaubten Laufzeit, auch wenn die Aufgabe
     hängt (kleinere Grenze aus Maximaldauer und Restbudget).
  3. Wächter (waechter_lauf, alle 10 Minuten auf dem Mini-PC über backend/gpu_waechter.py, außerdem einmal beim
     Backend-Start): listet ALLE Pods des Kontos und löscht jeden, der länger als die Maximaldauer existiert,
     nur gestoppt ist oder nicht von Auron gestartet wurde. Er braucht den Hauptablauf nicht.

Erreichbarkeit: RunPod-Proxy (https://<pod-id>-11434.proxy.runpod.net) statt Tailscale. Gründe: kein zusätzlicher
Schlüssel und keine Zusatzsoftware im Pod, läuft mit dem Standard-Image ollama/ollama, TLS inklusive, nichts zu
installieren oder zu verwalten, das den Start verlängert oder schiefgehen kann. Nachteile (ehrlich): Die Adresse ist
nur durch die zufällige Pod-ID geschützt (Ollama hat keine Anmeldung), und der Proxy bricht Anfragen ab, die in
100 Sekunden nicht anfangen zu antworten (Cloudflare). Dagegen: Das Modell wird schon beim Pod-Start geladen (nicht
über den Proxy), und Antworten werden gestreamt (llm/provider.py, Ziel mit "stream"). Es geht nur die Aufgabe selbst
in den Pod, nie ein Schlüssel. Tailscale wäre privater, ist aber mehr Technik, die ungetestet ausfallen kann.

Kosten: eigener Topf in EUR (Standard 40 EUR im Monat, GPU_MIETE_DECKEL_EUR), getrennt von den 20 $ (Auron-Anfragen)
und 10 $ (Code-Deckel). Verbrauch = Laufzeit mal Stundenpreis aus dem Journal (data/gpu_miete/log.jsonl), laufende
Pods zählen mit. Deckel erreicht: keine Miete mehr bis zum Monatswechsel. Die Grundgebühr des Network Volumes läuft
auch ohne Pod und ist NICHT im Deckel (Hinweis in der Kostenanzeige).

Erlaubt nur im Nachtfenster (Standard 03:00 bis 09:00) oder auf ausdrücklichen Befehl von Sir. Claude (API) wird hier
nie benutzt. Ohne RUNPOD_API_KEY in der Umgebung bleibt alles aus; Auron arbeitet wie bisher auf dem Haupt-PC.

Der Schlüssel kommt nur aus der Umgebung, wird nie geloggt und nie in Fehlermeldungen geschrieben und nie an den Pod
geschickt. Tests nutzen nur Ersatz-Objekte oder Stubs auf 127.0.0.1 (tests/testschutz.py, app/geraeteschutz.py).

UNGETESTET gegen das echte RunPod (Stand 16.10.2026): Aufbau der Anfragen nach der RunPod-Dokumentation
(rest.runpod.io/v1, POST/GET/DELETE /pods), aber nie mit echtem Schlüssel gelaufen. Das Start-Skript im Pod
(START_SKRIPT) ist ebenfalls nur gelesen, nicht ausgeführt. Erster echter Lauf: Sir, klein, mit offener RunPod-Konsole.
"""

from __future__ import annotations

import atexit
import contextlib
import datetime
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

import requests

from . import fehlerbericht, geraeteschutz

NAME_PRAEFIX = "auron-gpu-"
API_STANDARD = "https://rest.runpod.io/v1"
OLLAMA_PORT = 11434
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_POD_ID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
_NAME_ZEIT = re.compile(r"^" + re.escape(NAME_PRAEFIX) + r"(\d{8}T\d{6})Z")
_ZEIT_TEXT = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})")

# Läuft im Pod: Ollama starten, Modell holen (auf dem Volume meist schon da), laden und warm halten.
# Das Laden passiert hier und nicht über den Proxy (der bricht nach 100 s ab). Ungetestet.
START_SKRIPT = (
    'ollama serve & '
    'for i in $(seq 1 90); do ollama list >/dev/null 2>&1 && break; sleep 2; done; '
    'ollama pull "$GPU_MODELL"; '
    '(ollama run "$GPU_MODELL" "" >/dev/null 2>&1 &) ; '
    'wait'
)


class GpuMieteFehler(RuntimeError):
    """Die Miete ist fehlgeschlagen (Start, Warten). Der Pod wird trotzdem gelöscht."""


class GpuMieteGesperrt(GpuMieteFehler):
    """Eine Miete ist jetzt nicht erlaubt (kein Schlüssel, außerhalb der Nacht, Deckel, Alarm ...).
    still=True: der Normalfall ohne Schlüssel - nichts melden."""

    def __init__(self, text: str, still: bool = False) -> None:
        super().__init__(text)
        self.still = still


class GpuLoeschFehler(GpuMieteFehler):
    """Ein Pod konnte nicht gelöscht oder sein Fehlen nicht bestätigt werden. ALARM."""


class RunpodFehler(RuntimeError):
    """Antwort- oder Verbindungsfehler der RunPod-API (Text ist bereinigt, ohne Schlüssel)."""

    def __init__(self, text: str, status: int | None = None) -> None:
        super().__init__(text)
        self.status = status


# ------------------------------------------------------------------ Zeit (für Tests austauschbar)

def _mono() -> float:
    return time.monotonic()


def _schlafen(sekunden: float) -> None:
    time.sleep(sekunden)


def _jetzt() -> datetime.datetime:
    """Jetzt, mit Zeitzone (Ortszeit wie im übrigen Auron)."""
    try:
        from . import alltag  # noqa: PLC0415 - spät: der Wächter soll leicht bleiben

        return alltag.jetzt()
    except Exception:  # noqa: BLE001
        return datetime.datetime.now().astimezone()


# ------------------------------------------------------------------ Einstellungen (aus der Umgebung, zur Laufzeit)

def _zahl(name: str, standard: float) -> float:
    roh = (os.getenv(name) or "").strip().replace(",", ".")
    try:
        wert = float(roh) if roh else standard
    except ValueError:
        return standard
    return wert if wert > 0 else standard


def _text(name: str, standard: str) -> str:
    return (os.getenv(name) or "").strip() or standard


def schluessel_da() -> bool:
    return bool((os.getenv("RUNPOD_API_KEY") or "").strip())


def ist_aktiv() -> bool:
    """Schlüssel da und nicht mit GPU_MIETE_AUS=1 abgeschaltet."""
    aus = (os.getenv("GPU_MIETE_AUS") or "").strip().lower() in ("1", "ja", "true", "an")
    return schluessel_da() and not aus


def deckel_eur() -> float:
    return _zahl("GPU_MIETE_DECKEL_EUR", 40.0)


def max_dauer_s() -> float:
    return _zahl("GPU_MIETE_MAX_STUNDEN", 3.0) * 3600


def eur_pro_usd() -> float:
    return _zahl("GPU_MIETE_EUR_PRO_USD", 0.92)       # Annahme, in der .env anpassbar


def preis_fallback_usd_h() -> float:
    return _zahl("GPU_MIETE_PREIS_USD_STUNDE", 0.60)  # Annahme (großzügig), nur falls die API keinen Preis nennt


def fremde_loeschen() -> bool:
    return (os.getenv("GPU_MIETE_FREMDE_LOESCHEN") or "ja").strip().lower() not in ("nein", "0", "false", "aus")


def modell() -> str:
    return _text("GPU_MIETE_MODELL", "qwen3-coder:30b")


def gpu_typ() -> str:
    return _text("GPU_MIETE_GPU", "NVIDIA A40")


def _basis_url() -> str:
    """API-Adresse. Eine andere als die von RunPod gilt nur für 127.0.0.1 (Test-Stub) - sonst könnte eine
    falsch gesetzte Umgebungsvariable den Schlüssel an einen fremden Server schicken."""
    wunsch = (os.getenv("RUNPOD_API_URL") or "").strip().rstrip("/")
    if wunsch and (urlparse(wunsch).hostname or "").lower() in LOOPBACK:
        return wunsch
    return API_STANDARD


def proxy_url(pod_id: str) -> str:
    return f"https://{pod_id}-{OLLAMA_PORT}.proxy.runpod.net"


def _sauber(text: Any) -> str:
    """Fehlertext ohne Schlüssel und ohne lange Kennungen, begrenzt."""
    t = str(text or "")
    schluessel = (os.getenv("RUNPOD_API_KEY") or "").strip()
    if schluessel:
        t = t.replace(schluessel, "***")
    return fehlerbericht.saeubern(t)[:300]


# ------------------------------------------------------------------ Speicher (data/gpu_miete): Journal + Alarm

def ordner() -> Path:
    return Path(os.getenv("GPU_MIETE_PATH") or Path(__file__).resolve().parents[2] / "data" / "gpu_miete")


def _journal_pfad() -> Path:
    return ordner() / "log.jsonl"


def _alarm_pfad() -> Path:
    return ordner() / "alarm.json"


_datei_lock = threading.RLock()


def _journal() -> list[dict]:
    try:
        zeilen = _journal_pfad().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for z in zeilen:
        try:
            e = json.loads(z)
        except json.JSONDecodeError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def _anhaengen(eintrag: dict) -> None:
    """Journal nur anhängen (kein Lesen-Ändern-Schreiben): Backend und Wächter laufen als getrennte Prozesse."""
    with _datei_lock:
        p = _journal_pfad()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")


def _zeit_text(z: datetime.datetime) -> str:
    return z.astimezone().isoformat(timespec="seconds")


def _zeit_lesen(text: Any) -> datetime.datetime | None:
    try:
        z = datetime.datetime.fromisoformat(str(text))
    except ValueError:
        return None
    return z if z.tzinfo else z.astimezone()


def aktive_pods() -> dict[str, dict]:
    """Pods, für die das Journal einen Start, aber noch kein Ende kennt (id -> Start-Eintrag)."""
    start: dict[str, dict] = {}
    ende: set[str] = set()
    for e in _journal():
        pid = str(e.get("id") or "")
        if e.get("ereignis") == "start":
            start.setdefault(pid, e)
        elif e.get("ereignis") == "ende":
            ende.add(pid)
    return {k: v for k, v in start.items() if k not in ende}


def _ende_buchen(pod_id: str, status: str, jetzt: datetime.datetime | None = None) -> float:
    """Schließt einen Pod im Journal ab und gibt die Kosten (EUR) zurück. Zweimal buchen zählt nur einmal."""
    jetzt = jetzt or _jetzt()
    with _datei_lock:
        start = aktive_pods().get(pod_id)
        if not start:
            return 0.0
        beginn = _zeit_lesen(start.get("zeit")) or jetzt
        dauer = max(0.0, (jetzt - beginn).total_seconds())
        preis = float(start.get("preis_usd_h") or preis_fallback_usd_h())
        eur = dauer / 3600 * preis * eur_pro_usd()
        _anhaengen({"ereignis": "ende", "id": pod_id, "name": start.get("name"), "zeit": _zeit_text(jetzt),
                    "dauer_s": round(dauer), "kosten_eur": round(eur, 4), "status": status})
        return eur


def verbrauch_eur(jetzt: datetime.datetime | None = None) -> float:
    """GPU-Verbrauch dieses Monats in EUR: abgeschlossene Mieten plus bisher aufgelaufene Kosten laufender Pods."""
    jetzt = jetzt or _jetzt()
    monat = jetzt.strftime("%Y-%m")
    summe = 0.0
    gesehen: set[str] = set()
    for e in _journal():
        if e.get("ereignis") == "ende" and str(e.get("id")) not in gesehen:
            gesehen.add(str(e.get("id")))
            if str(e.get("zeit", "")).startswith(monat):
                summe += float(e.get("kosten_eur") or 0)
    for pid, s in aktive_pods().items():
        beginn = _zeit_lesen(s.get("zeit"))
        if beginn:
            h = max(0.0, (jetzt - beginn).total_seconds()) / 3600
            summe += h * float(s.get("preis_usd_h") or preis_fallback_usd_h()) * eur_pro_usd()
    return summe


# Alarm: bleibt stehen, bis ein Wächterlauf bestätigt, dass kein Pod mehr übrig ist.

def alarm_lesen() -> dict | None:
    try:
        d = json.loads(_alarm_pfad().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return d if isinstance(d, dict) and d.get("text") else None


def alarm_setzen(text: str, pods: list[str] | None = None) -> None:
    """Laute Meldung: Datei (Ampel rot, Alexa, Nachtbericht), Fehlerbericht und Konsole. Wirft nie."""
    text = _sauber(text)
    try:
        with _datei_lock:
            _alarm_pfad().parent.mkdir(parents=True, exist_ok=True)
            _alarm_pfad().write_text(json.dumps(
                {"zeit": _zeit_text(_jetzt()), "text": text, "pods": list(pods or [])}, ensure_ascii=False),
                encoding="utf-8")
    except OSError:
        pass
    meldung = f"FEHLER GPU-Miete: {text} - Bitte in der RunPod-Konsole nachsehen und den Pod von Hand löschen, Sir."
    fehlerbericht.merken("gpu_miete", meldung, "gpu_miete")
    print(meldung, flush=True)
    try:   # P24b: sofort über die eingerichteten Alarm-Wege melden (Alexa), nicht erst beim nächsten Prüflauf
        from . import alarm  # noqa: PLC0415

        alarm.pruefen_gpu()
    except Exception:  # noqa: BLE001
        pass


def alarm_loeschen() -> None:
    with contextlib.suppress(OSError):
        _alarm_pfad().unlink()


# ------------------------------------------------------------------ RunPod-API

class RunpodApi:
    """Dünner Zugang zur RunPod-REST-API. Der Schlüssel wird bei jedem Aufruf aus der Umgebung gelesen."""

    def __init__(self, schluessel: str | None = None) -> None:
        self._schluessel = schluessel

    def _anfrage(self, methode: str, pfad: str, body: dict | None = None, ok_404: bool = False) -> Any:
        schluessel = self._schluessel or (os.getenv("RUNPOD_API_KEY") or "").strip()
        if not schluessel:
            raise GpuMieteGesperrt("RUNPOD_API_KEY ist nicht gesetzt - GPU-Miete bleibt aus.", still=True)
        url = _basis_url() + pfad
        geraeteschutz.netz_pruefen(url, "RunPod-Aufruf")
        try:
            r = requests.request(methode, url, json=body, timeout=(5, 30),
                                 headers={"Authorization": f"Bearer {schluessel}"})
        except requests.exceptions.RequestException as exc:
            raise RunpodFehler(f"RunPod {methode} {pfad}: {type(exc).__name__}: {_sauber(exc)}") from None
        if r.status_code == 404 and ok_404:
            return None
        if r.status_code == 401:
            raise RunpodFehler(f"RunPod {methode} {pfad}: Schlüssel abgelehnt (HTTP 401).", 401)
        if r.status_code >= 400:
            raise RunpodFehler(f"RunPod {methode} {pfad}: HTTP {r.status_code}: {_sauber(r.text)}", r.status_code)
        if r.status_code == 204 or not (r.content or b"").strip():
            return {}
        try:
            return r.json()
        except ValueError:
            raise RunpodFehler(f"RunPod {methode} {pfad}: Antwort ist kein JSON.", r.status_code) from None

    def erstellen(self, body: dict) -> dict:
        d = self._anfrage("POST", "/pods", body)
        return d if isinstance(d, dict) else {}

    def liste(self) -> list[dict]:
        d = self._anfrage("GET", "/pods")
        if not isinstance(d, list):
            raise RunpodFehler("RunPod GET /pods: unerwartete Antwort (keine Liste).")
        return [p for p in d if isinstance(p, dict)]

    def holen(self, pod_id: str) -> dict | None:
        _id_pruefen(pod_id)
        d = self._anfrage("GET", f"/pods/{pod_id}", ok_404=True)
        return d if isinstance(d, dict) and d else None

    def loeschen(self, pod_id: str) -> None:
        """DELETE /pods/<id>. Gilt auch als gelungen, wenn es den Pod schon nicht mehr gibt (404)."""
        _id_pruefen(pod_id)
        self._anfrage("DELETE", f"/pods/{pod_id}", ok_404=True)


def _id_pruefen(pod_id: str) -> str:
    if not _POD_ID.match(str(pod_id or "")):
        raise RunpodFehler("Ungültige Pod-ID.")
    return str(pod_id)


def pod_body(name: str) -> dict:
    """Anfrage zum Anlegen des Pods. Auf dem Volume liegen die Modelle (OLLAMA_MODELS). Kein Schlüssel im Pod."""
    ziel_modell = modell()
    body: dict[str, Any] = {
        "name": name,
        "imageName": _text("GPU_MIETE_IMAGE", "ollama/ollama:latest"),
        "computeType": "GPU",
        "cloudType": _text("GPU_MIETE_CLOUD", "SECURE"),
        "gpuTypeIds": [gpu_typ()],
        "gpuCount": 1,
        "interruptible": False,
        "containerDiskInGb": int(_zahl("GPU_MIETE_CONTAINER_GB", 30)),
        "networkVolumeId": _text("GPU_MIETE_VOLUME_ID", ""),
        "volumeMountPath": "/workspace",
        "ports": [f"{OLLAMA_PORT}/http"],
        "env": {
            "OLLAMA_MODELS": "/workspace/ollama/models",
            "OLLAMA_HOST": f"0.0.0.0:{OLLAMA_PORT}",
            "OLLAMA_KEEP_ALIVE": "3h",
            "GPU_MODELL": ziel_modell,
        },
        "dockerEntrypoint": ["/bin/bash", "-c"],
        "dockerStartCmd": [START_SKRIPT],
    }
    zentrum = _text("GPU_MIETE_RECHENZENTRUM", "")
    if zentrum:
        body["dataCenterIds"] = [z.strip() for z in zentrum.split(",") if z.strip()]
    return body


def _preis_aus_pod(pod: dict) -> float:
    try:
        wert = float(pod.get("costPerHr"))
    except (TypeError, ValueError):
        return preis_fallback_usd_h()
    return wert if wert > 0 else preis_fallback_usd_h()


# ------------------------------------------------------------------ Nachtfenster und Erlaubnis

def _uhrzeit(text: str, standard: datetime.time) -> datetime.time:
    try:
        std, minute = (int(x) for x in (text or "").split(":", 1))
        return datetime.time(std, minute)
    except ValueError:
        return standard


def im_nachtfenster(jetzt: datetime.datetime | None = None) -> bool:
    jetzt = jetzt or _jetzt()
    von = _uhrzeit(os.getenv("GPU_MIETE_VON", ""), datetime.time(3, 0))
    bis = _uhrzeit(os.getenv("GPU_MIETE_BIS", ""), datetime.time(9, 0))
    t = jetzt.time().replace(tzinfo=None)
    return von <= t < bis if von < bis else (t >= von or t < bis)


MIN_LAUFZEIT_S = 20 * 60   # darunter lohnt keine Miete (Start allein dauert Minuten)


def pruefen_start(ausdruecklich: bool = False, jetzt: datetime.datetime | None = None) -> float:
    """Darf jetzt gemietet werden? Wirft GpuMieteGesperrt mit Grund. Rückgabe: erlaubte Laufzeit in Sekunden
    (kleinere Grenze aus Maximaldauer und Restbudget)."""
    jetzt = jetzt or _jetzt()
    if not schluessel_da():
        raise GpuMieteGesperrt("RUNPOD_API_KEY ist nicht gesetzt - GPU-Miete bleibt aus.", still=True)
    if not ist_aktiv():
        raise GpuMieteGesperrt("GPU-Miete ist mit GPU_MIETE_AUS abgeschaltet.", still=True)
    if not _text("GPU_MIETE_VOLUME_ID", ""):
        raise GpuMieteGesperrt("GPU_MIETE_VOLUME_ID fehlt (Network Volume für die Modelle) - keine Miete.")
    alarm = alarm_lesen()
    if alarm:
        raise GpuMieteGesperrt("Ein früherer Pod ist noch nicht als gelöscht bestätigt "
                               f"({alarm.get('text', '')[:120]}) - keine neue Miete, bis der Wächter Entwarnung gibt.")
    if not ausdruecklich and not im_nachtfenster(jetzt):
        raise GpuMieteGesperrt("Außerhalb des Nachtfensters und ohne ausdrücklichen Befehl von Sir - keine Miete.")
    rest = deckel_eur() - verbrauch_eur(jetzt)
    if rest <= 0:
        raise GpuMieteGesperrt(f"GPU-Deckel erreicht ({deckel_eur():.0f} EUR im Monat) - gesperrt bis zum Monatswechsel.")
    preis_h = preis_fallback_usd_h() * eur_pro_usd()
    erlaubt = min(max_dauer_s(), rest / preis_h * 3600)
    if erlaubt < MIN_LAUFZEIT_S:
        raise GpuMieteGesperrt(f"Nur noch {rest:.2f} EUR im GPU-Deckel - zu knapp für eine Miete, "
                               "gesperrt bis zum Monatswechsel.")
    return erlaubt


# ------------------------------------------------------------------ Pod-Verwaltung: Löschen und Bestätigen

LOESCH_VERSUCHE = 5
PAUSE_LOESCHEN_S = 2.0   # wird verdoppelt: 2, 4, 8, 16 s


def _pod_existiert(api: Any, pod_id: str) -> bool:
    """Wahrheit ist die Liste aller Pods (nicht GET /pods/<id>, dessen Verhalten nach dem Löschen nicht dokumentiert ist)."""
    for p in api.liste():
        if str(p.get("id")) == pod_id and str(p.get("desiredStatus", "")).upper() != "TERMINATED":
            return True
    return False


def loeschen_sicher(api: Any, pod_id: str) -> bool:
    """Pod löschen (terminate), mehrfach versuchen und über die API bestätigen, dass er nicht mehr existiert.
    True nur, wenn das Fehlen bestätigt ist. Wirft nie."""
    pause = PAUSE_LOESCHEN_S
    for versuch in range(1, LOESCH_VERSUCHE + 1):
        try:
            api.loeschen(pod_id)
            if not _pod_existiert(api, pod_id):
                return True
        except GpuMieteGesperrt:
            return False   # Schlüssel weg: nichts mehr zu machen
        except Exception as exc:  # noqa: BLE001 - jeder Fehler heißt: nochmal versuchen
            print(f"[GPU-Miete] Löschen von {pod_id}, Versuch {versuch}/{LOESCH_VERSUCHE}: {_sauber(exc)}", flush=True)
        if versuch < LOESCH_VERSUCHE:
            _schlafen(pause)
            pause *= 2
    return False


def _pods_mit_name(api: Any, name: str) -> list[str]:
    return [str(p.get("id")) for p in api.liste() if p.get("name") == name and _POD_ID.match(str(p.get("id")))]


def _neuer_name(jetzt: datetime.datetime | None = None) -> str:
    z = (jetzt or _jetzt()).astimezone(datetime.timezone.utc)
    return f"{NAME_PRAEFIX}{z.strftime('%Y%m%dT%H%M%S')}Z-{secrets.token_hex(2)}"


# ------------------------------------------------------------------ Miet-Sitzung

class Sitzung:
    """Was die Aufgabe von der Miete sieht: Ziel (Adresse, Modell) und die verbleibende Zeit."""

    def __init__(self, pod_id: str, name: str, url: str, modell_name: str, ablauf: float) -> None:
        self.pod_id, self.name, self.url, self.modell = pod_id, name, url, modell_name
        self._ablauf = ablauf
        self.abgelaufen = False

    def restzeit_s(self) -> float:
        return 0.0 if self.abgelaufen else max(0.0, self._ablauf - _mono())


_sitzung_lock = threading.Lock()
_aktuell: dict[str, Any] = {"lauf": None}


def laeuft() -> bool:
    return _sitzung_lock.locked()


def _ollama_pruefen(url: str) -> tuple[list[str] | None, list[str] | None]:
    """(Modelle auf dem Pod, geladene Modelle). None, wenn Ollama (noch) nicht antwortet."""
    geraeteschutz.netz_pruefen(url, "Ollama im Pod")
    try:
        r = requests.get(f"{url}/api/tags", timeout=10)
        r.raise_for_status()
        vorhanden = [str(m.get("name")) for m in (r.json().get("models") or [])]
    except (requests.exceptions.RequestException, ValueError):
        return None, None
    try:
        r = requests.get(f"{url}/api/ps", timeout=10)
        r.raise_for_status()
        geladen = [str(m.get("name")) for m in (r.json().get("models") or [])]
    except (requests.exceptions.RequestException, ValueError):
        geladen = []
    return vorhanden, geladen


def _modell_in(liste: list[str] | None, name: str) -> bool:
    return bool(liste) and any(x == name or x.split(":")[0] == name or x == f"{name}:latest" for x in liste or [])


class _Lauf:
    """Ein Mietvorgang. beenden() ist wiederholbar und löscht in jedem Fall."""

    def __init__(self, api: Any, erlaubt_s: float, ausdruecklich: bool) -> None:
        self.api, self.ausdruecklich = api, ausdruecklich
        self.erlaubt_s = erlaubt_s
        self.name = _neuer_name()
        self.pod_id: str | None = None
        self.start_versucht = False
        self.sitzung: Sitzung | None = None
        self._ablauf = 0.0
        self._beendet = False
        self._lock = threading.RLock()
        self._bremse: threading.Timer | None = None
        self.kosten_eur = 0.0

    # --- Start
    def starten(self) -> None:
        self.start_versucht = True
        try:
            pod = self.api.erstellen(pod_body(self.name))
        except GpuMieteGesperrt:
            raise
        except Exception as exc:  # noqa: BLE001
            raise GpuMieteFehler(f"Pod konnte nicht gestartet werden: {_sauber(exc)}") from exc
        pid = str(pod.get("id") or "")
        if not _POD_ID.match(pid):
            raise GpuMieteFehler("RunPod hat keine gültige Pod-ID geliefert.")
        self.pod_id = pid
        _anhaengen({"ereignis": "start", "id": pid, "name": self.name, "zeit": _zeit_text(_jetzt()),
                    "preis_usd_h": _preis_aus_pod(pod), "gpu": gpu_typ(), "modell": modell(),
                    "ausdruecklich": self.ausdruecklich})
        self._ablauf = _mono() + self.erlaubt_s
        self._bremse = threading.Timer(self.erlaubt_s, self._notbremse)
        self._bremse.daemon = True
        self._bremse.start()
        atexit.register(self._beenden_leise)

    # --- Warten, bis Ollama antwortet
    def warten(self) -> None:
        assert self.pod_id
        url = proxy_url(self.pod_id)
        frist = _mono() + _zahl("GPU_MIETE_START_TIMEOUT_S", 900)
        laden_frist: float | None = None
        laden_warten = _zahl("GPU_MIETE_LADEN_WARTEN_S", 180)
        ziel_modell = modell()
        while True:
            if _mono() >= frist:
                raise GpuMieteFehler(f"Ollama im Pod antwortet nicht (Zeitgrenze {_zahl('GPU_MIETE_START_TIMEOUT_S', 900):.0f} s).")
            pod = self.api.holen(self.pod_id)
            if pod is None:
                raise GpuMieteFehler("Der Pod ist kurz nach dem Start nicht mehr bei RunPod zu finden.")
            if str(pod.get("desiredStatus", "RUNNING")).upper() in ("EXITED", "TERMINATED"):
                raise GpuMieteFehler(f"Der Pod ist nach dem Start beendet worden (Status {pod.get('desiredStatus')}).")
            vorhanden, geladen = _ollama_pruefen(url)
            if _modell_in(vorhanden, ziel_modell):
                if _modell_in(geladen, ziel_modell):
                    break
                laden_frist = laden_frist or _mono() + laden_warten
                if _mono() >= laden_frist:
                    print("[GPU-Miete] Modell ist da, aber noch nicht geladen - die erste Anfrage lädt es.", flush=True)
                    break
            _schlafen(5)
        self.sitzung = Sitzung(self.pod_id, self.name, url, ziel_modell, self._ablauf)

    # --- Ende (immer)
    def _notbremse(self) -> None:
        if self.sitzung:
            self.sitzung.abgelaufen = True
        print("[GPU-Miete] Erlaubte Laufzeit erreicht - Notbremse löscht den Pod.", flush=True)
        with contextlib.suppress(GpuLoeschFehler):
            self.beenden()

    def _beenden_leise(self) -> None:
        with contextlib.suppress(Exception):
            self.beenden()

    def beenden(self) -> None:
        with self._lock:
            if self._beendet:
                return
            if self._bremse:
                self._bremse.cancel()
            ids: list[str] = []
            unklar = False
            if self.pod_id:
                ids.append(self.pod_id)
            elif self.start_versucht:
                # Antwort auf "Pod anlegen" ging verloren: der Pod kann trotzdem existieren -> per Namen suchen
                try:
                    ids = _pods_mit_name(self.api, self.name)
                except Exception:  # noqa: BLE001
                    unklar = True
            offen: list[str] = []
            for pid in ids:
                if loeschen_sicher(self.api, pid):
                    self.kosten_eur += _ende_buchen(pid, "geloescht")
                else:
                    offen.append(pid)
            if offen or unklar:
                if unklar:
                    alarm_setzen(f"Unklar, ob der Pod {self.name} existiert (RunPod nicht abfragbar) - bitte in der RunPod-Konsole prüfen.", [self.name])
                    raise GpuLoeschFehler(f"Pod {self.name} nicht bestätigt gelöscht.")
                alarm_setzen(f"Pod {', '.join(offen)} konnte nach {LOESCH_VERSUCHE} Versuchen nicht gelöscht werden "
                             "und läuft evtl. weiter (kostet Geld).", offen)
                raise GpuLoeschFehler(f"Pod {', '.join(offen)} nicht gelöscht.")
            self._beendet = True
            atexit.unregister(self._beenden_leise)


@contextlib.contextmanager
def sitzung(ausdruecklich: bool = False, api: Any = None) -> Iterator[Sitzung]:
    """Pod mieten, bis Ollama bereit ist, Ziel für llm/provider.py setzen - und am Ende den Pod IMMER löschen.

    Wirft GpuMieteGesperrt (nicht erlaubt), GpuMieteFehler (Start misslungen; Pod ist dann schon gelöscht) oder
    GpuLoeschFehler (Pod nicht bestätigt gelöscht: Alarm ist gesetzt)."""
    from llm import provider  # noqa: PLC0415

    erlaubt_s = pruefen_start(ausdruecklich)
    if not _sitzung_lock.acquire(blocking=False):
        raise GpuMieteGesperrt("Es läuft schon eine GPU-Miete.")
    lauf = _Lauf(api or RunpodApi(), erlaubt_s, ausdruecklich)
    _aktuell["lauf"] = lauf
    try:
        try:
            lauf.starten()
            lauf.warten()
            s = lauf.sitzung
            assert s is not None
            with provider.ziel_exklusiv(
                    name=f"GPU-Miete ({gpu_typ()})", url=s.url, modell=s.modell,
                    lese_zeit=int(_zahl("GPU_MIETE_TIMEOUT_S", 3600)), stream=True,
                    num_ctx=int(_zahl("GPU_MIETE_NUM_CTX", 32768))):
                yield s
        finally:
            lauf.beenden()
    finally:
        _aktuell["lauf"] = None
        _sitzung_lock.release()


# ------------------------------------------------------------------ Wächter

def _alter_s(pod: dict, start: dict | None, jetzt: datetime.datetime) -> float | None:
    """Wie lange gibt es den Pod? Älteste bekannte Quelle gewinnt: Name, Journal, lastStartedAt."""
    zeiten: list[datetime.datetime] = []
    m = _NAME_ZEIT.match(str(pod.get("name") or ""))
    if m:
        with contextlib.suppress(ValueError):
            zeiten.append(datetime.datetime.strptime(m.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=datetime.timezone.utc))
    if start:
        z = _zeit_lesen(start.get("zeit"))
        if z:
            zeiten.append(z)
    t = _ZEIT_TEXT.search(str(pod.get("lastStartedAt") or ""))
    if t:
        with contextlib.suppress(ValueError):
            zeiten.append(datetime.datetime.strptime(f"{t.group(1)} {t.group(2)}", "%Y-%m-%d %H:%M:%S")
                          .replace(tzinfo=datetime.timezone.utc))
    if not zeiten:
        return None
    return max(0.0, (jetzt - min(zeiten)).total_seconds())


def waechter_lauf(api: Any = None, jetzt: datetime.datetime | None = None) -> dict:
    """Sicherheitsnetz: alle Pods des Kontos prüfen und löschen, was nicht (mehr) da sein darf.

    Gelöscht wird jeder Pod, der (a) nicht von Auron gestartet wurde (Name ohne "auron-gpu-" und nicht im Journal,
    abschaltbar mit GPU_MIETE_FREMDE_LOESCHEN=nein), (b) nur gestoppt ist (wird weiter berechnet) oder (c) länger als
    die Maximaldauer existiert oder sein Alter unbekannt ist. Wirft nie. Rückgabe zum Anzeigen und Testen."""
    jetzt = jetzt or _jetzt()
    erg: dict[str, Any] = {"aktiv": schluessel_da(), "geprueft": 0, "geloescht": [], "fehler": [], "ok": True}
    if not schluessel_da():   # GPU_MIETE_AUS sperrt nur neue Mieten, der Wächter räumt weiter auf
        return erg
    api = api or RunpodApi()
    journal = aktive_pods()
    try:
        pods = api.liste()
    except Exception as exc:  # noqa: BLE001
        erg["ok"] = False
        erg["fehler"].append(f"Pods nicht abfragbar: {_sauber(exc)}")
        if journal:
            alarm_setzen("Wächter kann RunPod nicht abfragen, ein Pod läuft laut Protokoll noch: "
                         + ", ".join(journal), list(journal))
        else:
            fehlerbericht.merken("gpu_miete", f"FEHLER GPU-Wächter: RunPod nicht abfragbar ({_sauber(exc)})", "gpu_miete")
        return erg

    aktuell = _aktuell.get("lauf")
    alarm = alarm_lesen()
    markiert = set(alarm.get("pods") or []) if alarm else set()   # Pods, deren Löschen schon einmal scheiterte
    verbleibend: set[str] = set()
    offen: list[str] = []
    gesehen: set[str] = set()
    for p in pods:
        pid = str(p.get("id") or "")
        status = str(p.get("desiredStatus") or "").upper()
        if not _POD_ID.match(pid) or status == "TERMINATED":
            continue
        gesehen.add(pid)
        erg["geprueft"] += 1
        eigener = str(p.get("name") or "").startswith(NAME_PRAEFIX) or pid in journal
        alter = _alter_s(p, journal.get(pid), jetzt)
        grund = None
        if pid in markiert or str(p.get("name") or "") in markiert:
            grund = "Löschen war schon einmal fehlgeschlagen (Alarm)"
        elif not eigener:
            if fremde_loeschen():
                grund = "nicht von Auron gestartet"
        elif status != "RUNNING":
            grund = f"nur {status.lower() or 'unbekannt'} (wird weiter berechnet)"
        elif alter is None:
            grund = "Alter unbekannt"
        elif alter > max_dauer_s():
            grund = f"läuft seit {alter / 60:.0f} min (erlaubt {max_dauer_s() / 60:.0f} min)"
        if not grund:
            verbleibend.update({pid, str(p.get("name") or "")})
            continue
        # Läuft der Pod gerade in einer eigenen Sitzung, darf deren Notbremse zuerst löschen - der Wächter wartet nicht,
        # er löscht trotzdem, denn er gilt als unabhängiges Netz.
        if loeschen_sicher(api, pid):
            kosten = _ende_buchen(pid, "waechter")
            erg["geloescht"].append({"id": pid, "name": p.get("name"), "grund": grund, "kosten_eur": round(kosten, 4)})
            fehlerbericht.merken("gpu_miete", f"WARNUNG GPU-Wächter hat Pod {p.get('name') or pid} gelöscht: {grund}", "gpu_miete")
            print(f"[GPU-Wächter] Pod {p.get('name') or pid} gelöscht: {grund}", flush=True)
        else:
            offen.append(pid)
            verbleibend.update({pid, str(p.get("name") or "")})
    # Im Journal als laufend geführt, bei RunPod aber nicht mehr da (z.B. von Hand gelöscht): abschließen
    for pid, s in journal.items():
        beginn = _zeit_lesen(s.get("zeit"))
        jung = beginn is not None and (jetzt - beginn).total_seconds() < 120   # RunPods Liste kann kurz hinterherhinken
        laeuft_hier = bool(aktuell and aktuell.pod_id == pid and not aktuell._beendet)  # noqa: SLF001
        if pid not in gesehen and not jung and not laeuft_hier:
            _ende_buchen(pid, "verschwunden", jetzt)
    if offen:
        erg["ok"] = False
        erg["fehler"].append("nicht gelöscht: " + ", ".join(offen))
        alarm_setzen(f"Wächter konnte Pod {', '.join(offen)} nicht löschen.", offen)
    elif alarm and not (markiert & verbleibend):
        alarm_loeschen()   # Wächter hat bestätigt: die Pods aus dem Alarm sind weg
        print("[GPU-Wächter] Alarm aufgehoben: die gemeldeten Pods sind nicht mehr vorhanden.", flush=True)
    return erg


def start_pruefung() -> None:
    """Einmal beim Backend-Start (main.py), im Hintergrund. Ohne Schlüssel passiert nichts."""
    if not schluessel_da():
        return

    def _lauf() -> None:
        try:
            erg = waechter_lauf()
            if erg["geloescht"] or not erg["ok"]:
                print(f"[GPU-Miete] Start-Prüfung: {len(erg['geloescht'])} Pod(s) gelöscht, Fehler: {erg['fehler']}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"WARNUNG: GPU-Start-Prüfung fehlgeschlagen: {_sauber(exc)}", flush=True)

    threading.Thread(target=_lauf, name="gpu-start-pruefung", daemon=True).start()


# ------------------------------------------------------------------ Anzeige (Kosten, Ampel, Fehlerbericht, Alexa)

def volume_hinweis() -> str:
    gb = _zahl("GPU_MIETE_VOLUME_GB", 0.0)   # 0 = nicht eingetragen
    preis = _zahl("GPU_MIETE_VOLUME_PREIS_USD_GB_MONAT", 0.07)
    kern = "Das Network Volume kostet auch ohne Pod eine Grundgebühr und ist NICHT im GPU-Deckel"
    if gb:
        eur = gb * preis * eur_pro_usd()
        return f"{kern}: ca. {eur:.2f} EUR im Monat bei {gb:.0f} GB (Annahme {preis:.2f} $ je GB, in der RunPod-Konsole prüfen)."
    return f"{kern} (Größe in GPU_MIETE_VOLUME_GB eintragen, dann rechnet Auron die Grundgebühr aus; Preis in der RunPod-Konsole prüfen)."


def kosten_topf(jetzt: datetime.datetime | None = None) -> dict[str, Any]:
    """Kennzahlen des GPU-Topfes in EUR (Schätzung aus Laufzeit mal Stundenpreis, keine Abrechnung)."""
    jetzt = jetzt or _jetzt()
    rahmen = deckel_eur()
    ausgegeben = verbrauch_eur(jetzt)
    anteil = ausgegeben / rahmen * 100 if rahmen else 0.0
    ampel = "rot" if anteil >= 90 else ("gelb" if anteil >= 60 else "gruen")
    laufend = [{"id": pid, "name": s.get("name"), "seit": s.get("zeit")} for pid, s in aktive_pods().items()]
    return {
        "aktiv": ist_aktiv(), "monat": jetzt.strftime("%Y-%m"), "rahmen_eur": rahmen,
        "ausgegeben_eur": round(ausgegeben, 2), "rest_eur": round(rahmen - ausgegeben, 2),
        "anteil_prozent": round(anteil, 1), "ampel": ampel, "laufend": laufend,
        "alarm": alarm_lesen(), "volume_hinweis": volume_hinweis(),
        "hinweis": "Schätzung aus Laufzeit mal Stundenpreis (Wechselkurs und Preis ungeprüft), keine Abrechnung. "
                   "Den echten Stand zeigt die RunPod-Konsole.",
    }


def zeile(t: dict | None = None) -> str:
    """Eine Zeile für Chat und Briefing."""
    t = t or kosten_topf()

    def de(x: float, n: int = 2) -> str:
        return f"{x:.{n}f}".replace(".", ",")

    wort = {"gruen": "grün", "gelb": "gelb", "rot": "rot"}.get(t["ampel"], t["ampel"])
    return (f"GPU-Miete: {de(t['ausgegeben_eur'])} von {de(t['rahmen_eur'], 0)} EUR (Rest {de(t['rest_eur'])} EUR), "
            f"Ampel {wort}. {t['volume_hinweis']}")


def letzte_zeile() -> str:
    """Eine Zeile für den Nachtbericht: letzte beendete Miete und Monatsstand."""
    ende = [e for e in _journal() if e.get("ereignis") == "ende"]
    t = kosten_topf()
    stand = f"Monat: {t['ausgegeben_eur']:.2f} von {t['rahmen_eur']:.0f} EUR".replace(".", ",")
    if not ende:
        return f"GPU-Miete: keine beendete Miete im Protokoll. {stand}."
    e = ende[-1]
    eur = f"{float(e.get('kosten_eur') or 0):.2f}".replace(".", ",")
    return (f"GPU-Miete: Pod {e.get('name')} {float(e.get('dauer_s') or 0) / 60:.0f} min, ca. {eur} EUR, "
            f"Status {e.get('status')} (Pod gelöscht und bestätigt). {stand}.")


def sprach_hinweis() -> str | None:
    """Für Alexa: nur wenn etwas nicht stimmt (Alarm) oder gerade ein Pod läuft."""
    a = alarm_lesen()
    if a:
        return "Achtung Sir: Bei der GPU-Miete ist ein Pod nicht als gelöscht bestätigt. Bitte in der RunPod-Konsole nachsehen."
    if aktive_pods():
        return "Ein gemieteter GPU-Pod läuft gerade."
    return None


def bericht_zeilen() -> list[str]:
    """Abschnitt für den Fehlerbericht."""
    if not schluessel_da():
        return ["GPU-Miete aus (kein RUNPOD_API_KEY)."]
    t = kosten_topf()
    out = [f"- {zeile(t)}"]
    if t["laufend"]:
        out.append("- Laufende Pods laut Protokoll: " + ", ".join(f"{p['name']} seit {p['seit']}" for p in t["laufend"]))
    if t["alarm"]:
        out.append(f"- ALARM seit {t['alarm'].get('zeit')}: {t['alarm'].get('text')}")
    ende = [e for e in _journal() if e.get("ereignis") == "ende"][-5:]
    for e in ende:
        out.append(f"- Ende {e.get('zeit')}: {e.get('name')} {e.get('status')}, {e.get('dauer_s')} s, {e.get('kosten_eur')} EUR")
    return out


def status() -> dict[str, Any]:
    t = kosten_topf()
    t["laeuft"] = laeuft()
    t["fenster"] = {"von": os.getenv("GPU_MIETE_VON") or "03:00", "bis": os.getenv("GPU_MIETE_BIS") or "09:00",
                    "jetzt_erlaubt": im_nachtfenster()}
    t["max_stunden"] = max_dauer_s() / 3600
    t["gpu"] = gpu_typ()
    t["modell"] = modell()
    return t

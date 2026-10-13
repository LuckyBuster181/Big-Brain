"""
Austauschbarer LLM-Client für den KLASSISCHEN Chat-Modus (chat_service.ask /
ask_stream). Ziel (Wunsch von Sir, 22.09.2026): Jarvis unabhängiger von
bezahlter API machen, ohne den bestehenden, getesteten Claude-Weg umzubauen
oder zu gefährden.

Wie es funktioniert: OllamaClient bildet nur den schmalen Ausschnitt der
Anthropic-Schnittstelle nach, den chat_service.py tatsächlich benutzt -
client.messages.create(...) und client.messages.stream(...) als Kontext-
manager mit .text_stream und .get_final_message(). chat_service.py merkt vom
Austausch praktisch nichts.

Umschalten ausschließlich über die .env:
    LLM_PROVIDER=ollama    (Standard, wenn nicht gesetzt: "claude" - dann
                             unverändertes Verhalten, kein Unterschied zu vorher)
    OLLAMA_MODEL=llama3.1:8b   (Standard-Vorschlag für 8 GB VRAM, ungetestet -
                             qwen2.5:7b ist ein zweiter Kandidat fürs Deutsche,
                             vorher mit suchtest.bat/chattest.bat vergleichen)
    OLLAMA_URL=http://localhost:11434
    OLLAMA_TIMEOUT=180

WICHTIG: LLM_PROVIDER=ollama erst setzen, wenn Ollama installiert UND das
Modell mit "ollama pull <name>" heruntergeladen ist - sonst bricht der
klassische Modus mit einem Verbindungsfehler ab.

Bewusste Einschränkung: Der WERKZEUG-Modus (agent_service.py, Claude sucht
selbst im Vault über einen Tool-Call) bleibt bei Claude. Ein lokales Modell
müsste dafür zuverlässig Tool-Calls im Anthropic-Format liefern - eigenes,
größeres Vorhaben, noch nicht geprüft, ob sich der Aufwand lohnt.

ERWEITERUNG 03.10.2026 (Claude Cowork): Reihenfolge mehrerer Rechner. Steht in
data/ki_lokal.json (Pfad per KI_LOKAL_PATH) eine Liste "reihenfolge" und sind
OLLAMA_URL und OLLAMA_MODEL NICHT gesetzt, fragt Jarvis die Rechner der Reihe
nach: Test-PC, dann Haupt-PC, dann Mini-PC. Antwortet einer nicht (Verbindung
oder Fehlerantwort), kommt der nächste dran. Eine lange Antwort, die mitten im
Lesen abreißt (Zeitüberschreitung), wird NICHT woanders wiederholt. Ohne Datei
oder mit gesetzter OLLAMA_URL/OLLAMA_MODEL gilt wie bisher genau ein Rechner.
"url": "auto-hauptpc" nimmt die Adresse aus HAUPTPC_URL (der Haupt-PC bekommt
bei jedem Start eine andere Adresse). Anbieter einschalten: in den HUD-
Einstellungen bzw. data/einstellungen.json "ki_anbieter": "ollama" (-> LLM_PROVIDER).
Ollama-Antworten werden ohne "Nachdenken" angefordert (think=false), sonst
verbraucht ein Qwen-Modell seine Antwortlänge für versteckte Gedanken.

Kein Prompt-Caching bei Ollama (lokal ohnehin ohne laufende Kosten) - der
cache_control-Block aus chat_service.cache_system() wird beim Aufbereiten
für Ollama einfach zu reinem Text.

ERWEITERUNG 05.10.2026 (Claude Cowork, Entscheidung Sir): Tagbetrieb lokal, Claude nur als Rückfall.
- Tagsüber (tag=True: Chat, Smalltalk, Alltagsfunktionen) fragt Auron "reihenfolge_tag" aus
  data/ki_lokal.json (Haupt-PC -> Test-PC; der Mini-PC ist mit 4,6 Token/s nur noch nachts dabei).
- Steht dort "tag_rueckfall": "claude", springt Claude ein, wenn
  (a) kein lokaler Rechner antwortet (Verbindung, Fehlerantwort oder 60 s ohne erstes Wort) oder
  (b) die lokale Antwort klar unbrauchbar ist (leer, fremde Schrift, Endlosschleife, abgeschnitten,
      Verbindung mitten in der Antwort abgerissen) - pruefe_antwort().
  Jeder Rückfall ist sichtbar: TagClient.info sagt, wer geantwortet hat und warum
  (chat_service schickt das als Ereignis "ki" an Auron, Auron zeigt es unter der Antwort).
- Nachts (tag=False) gibt es NIE einen Rückfall auf Claude (Entscheidung Sir 04.10.2026, app/nacht_ki.py).
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import urlparse

import requests

OLLAMA_URL = (os.getenv("OLLAMA_URL") or "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
# Ollama läuft lokal, aber nicht beliebig schnell auf Consumer-Hardware -
# großzügiger Timeout, damit eine lange Antwort nicht mitten im Satz abbricht.
# 05.10.2026: tagsüber 60 s statt 180 s. Kommt so lange kein erstes Wort (Rechner hängt), ist der
# nächste Rechner bzw. Claude dran - Sir soll im Gespräch nicht drei Minuten warten.
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "60"))
# Modell nach der Antwort im Speicher halten (Standard von Ollama: 5 Minuten). Spart das
# Neuladen (ca. 20 s) bei der ersten Frage nach einer Pause.
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "60m")


# Nacht- und Hintergrundarbeit (tag=False): lange Aufträge brauchen ein größeres Gedächtnis (num_ctx) und mehr Zeit.
# Ollama-Standard ist 4096 Token: Auftrag + Vault-Ausschnitte + Systemtext + Antwort passen dann nicht hinein,
# das Modell schneidet vorne ab (Systemtext weg) oder hört mitten in der Antwort auf. 04.10.2026.
OLLAMA_NACHT_NUM_CTX = int(os.getenv("OLLAMA_NACHT_NUM_CTX", "12288"))
OLLAMA_NACHT_TIMEOUT = int(os.getenv("OLLAMA_NACHT_TIMEOUT", "1200"))

# Verbindungsaufbau bricht schnell ab (Rechner aus), das Lesen der Antwort darf lange dauern.
OLLAMA_CONNECT_TIMEOUT = float(os.getenv("OLLAMA_CONNECT_TIMEOUT", "3"))
DEFAULT_KI_LOKAL = Path(__file__).resolve().parents[2] / "data" / "ki_lokal.json"
_THINK_RE = re.compile(r"<think>.*?</think>", re.S)

# Welcher Rechner zuletzt geantwortet hat (für Anzeige und Protokoll).
letztes_ziel: dict[str, str] = {}

# Claude-Modell für den Rückfall, wenn der Aufrufer keins nennt (wie chat_service.DEFAULT_MODEL).
CLAUDE_STANDARD = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
# Unter diesem Monatsrest ($) springt Claude nicht mehr ein (wie ki_aufruf.MIN_REST_USD).
RUECKFALL_MIN_REST_USD = float(os.getenv("ALLTAG_MIN_REST_USD", "0.30"))


class LokalNichtErreichbar(RuntimeError):
    """Kein lokaler Rechner hat geantwortet (Verbindung, Fehlerantwort oder kein erstes Wort)."""


def _ki_lokal_pfad() -> Path:
    return Path(os.getenv("KI_LOKAL_PATH") or DEFAULT_KI_LOKAL)


def _hauptpc_ollama_url() -> str | None:
    host = urlparse(os.getenv("HAUPTPC_URL") or "").hostname
    return f"http://{host}:11434" if host else None


def ziele(tag: bool = False) -> list[dict[str, str]]:
    """Rechner in der Reihenfolge, in der gefragt wird. Jeder Eintrag: name, url, modell.
    tag=True (Sir sitzt gerade davor: Chat, Sprechen, Alltagsfunktionen): falls in der Datei
    "reihenfolge_tag" steht, gilt diese (z.B. Haupt-PC zuerst, weil schneller). Nachtarbeit
    und alles andere nutzt "reihenfolge"."""
    if not (os.getenv("OLLAMA_URL") or os.getenv("OLLAMA_MODEL")):
        try:
            daten = json.loads(_ki_lokal_pfad().read_text(encoding="utf-8"))
            roh = None
            if isinstance(daten, dict):
                roh = (daten.get("reihenfolge_tag") if tag else None) or daten.get("reihenfolge")
        except (OSError, json.JSONDecodeError):
            roh = None
        liste: list[dict[str, str]] = []
        for e in roh or []:
            if not isinstance(e, dict):
                continue
            url = str(e.get("url") or "").strip().rstrip("/")
            if url == "auto-hauptpc":
                url = _hauptpc_ollama_url() or ""
            modell = str(e.get("modell") or "").strip()
            if url and modell:
                liste.append({"name": str(e.get("name") or url), "url": url, "modell": modell})
        if liste:
            return liste
    return [{"name": "Ollama", "url": OLLAMA_URL, "modell": OLLAMA_MODEL}]


def provider_name() -> str:
    return (os.getenv("LLM_PROVIDER") or "claude").strip().lower()


def current_model_label(default_model: str, tag: bool = False) -> str:
    """Für Token-Protokoll und Anzeige: welches Modell tatsächlich lief."""
    return ziele(tag)[0]["modell"] if provider_name() == "ollama" else default_model


def tag_rueckfall() -> str | None:
    """05.10.2026: "claude", wenn Claude tagsüber einspringen darf (ki_lokal.json "tag_rueckfall",
    überschreibbar mit KI_TAG_RUECKFALL in der .env: "claude" oder "aus"). Sonst None."""
    wert = (os.getenv("KI_TAG_RUECKFALL") or "").strip().lower()
    if not wert:
        try:
            daten = json.loads(_ki_lokal_pfad().read_text(encoding="utf-8"))
            wert = str(daten.get("tag_rueckfall") or "").strip().lower() if isinstance(daten, dict) else ""
        except (OSError, json.JSONDecodeError):
            wert = ""
    return "claude" if wert == "claude" else None


def get_client(get_api_key: Callable[[], str], tag: bool = False, claude_modell: str | None = None,
               erzwinge_claude: bool = False, topf: str = "normal"):
    """Gibt den passenden Client zurück. Standard (LLM_PROVIDER nicht gesetzt
    oder "claude"): echter Anthropic-Client, unverändertes Verhalten.
    LLM_PROVIDER=ollama schaltet auf den lokalen Client um. get_api_key wird
    als Funktion übergeben (nicht importiert), damit dieses Modul nicht auf
    app.chat_service zurückverweisen muss (Ringimport).

    05.10.2026: tagsüber (tag=True) kommt ein TagClient: erst lokal, Claude nur als Rückfall
    (siehe Modulbeschreibung). erzwinge_claude=True (Knopf "Claude fragen" in Auron) fragt
    direkt Claude. Nachts (tag=False) bleibt es beim reinen OllamaClient - nie Claude."""
    if provider_name() == "ollama":
        if tag:
            return TagClient(get_api_key, claude_modell or CLAUDE_STANDARD, nur_claude=erzwinge_claude, topf=topf)
        return OllamaClient(tag)
    import anthropic  # nur hier importiert: im Ollama-Betrieb nicht nötig, dass es installiert ist

    return anthropic.Anthropic(api_key=get_api_key())


# ---------------------------------------------------------------------------
# Ollama-Client: bildet client.messages.create()/.stream() nach
# ---------------------------------------------------------------------------


class _Usage:
    def __init__(self, input_tokens: int = 0, output_tokens: int = 0, cache_read_input_tokens: int = 0) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Message:
    def __init__(self, text: str, usage: _Usage) -> None:
        self.content = [_TextBlock(text)]
        self.usage = usage
        self.stop_reason = "end_turn"


def _flatten_system(system: Any) -> str:
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "\n".join(block.get("text", "") for block in system if isinstance(block, dict))
    return "" if system is None else str(system)


def _flatten_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
        )
    return "" if content is None else str(content)


def _ollama_messages(system: Any, messages: list[dict]) -> list[dict]:
    out = [{"role": "system", "content": _flatten_system(system)}]
    for m in messages:
        out.append({"role": m["role"], "content": _flatten_content(m.get("content", ""))})
    return out


def _wrap_request_error(exc: Exception, alle: list[dict[str, str]] | None = None, sekunden: int | None = None,
                       klasse: type[RuntimeError] = RuntimeError) -> RuntimeError:
    namen = ", ".join(f"{z['name']} ({z['url']})" for z in (alle or ziele()))
    if isinstance(exc, requests.exceptions.ConnectionError):
        return klasse(
            f"Lokaler KI-Rechner nicht erreichbar: {namen}. Läuft der Ollama-Dienst? "
            f"(LLM_PROVIDER=ollama ist gesetzt.) Auf Claude umschalten: ki_anbieter in den Einstellungen auf 'claude'."
        )
    if isinstance(exc, requests.exceptions.Timeout):
        return klasse(f"Der lokale KI-Rechner hat nach {sekunden or OLLAMA_TIMEOUT}s nicht geantwortet ({namen}).")
    return klasse(f"Fehler bei der Anfrage an Ollama ({namen}): {exc}")


def _bereinigen(text: str) -> str:
    return _THINK_RE.sub("", text or "").strip()


def _agent(funktion: str, *args: Any) -> None:
    """10.10.2026: Meldung an die Agenten-Station (app/agenten.py). Darf nie stören."""
    try:
        from app import agenten  # noqa: PLC0415 - spät, damit provider ohne app/ testbar bleibt

        getattr(agenten, funktion)(*args)
    except Exception:  # noqa: BLE001
        pass


def _anfrage(payload: dict[str, Any], stream: bool, tag: bool = False) -> requests.Response:
    """Schickt die Anfrage an den ersten Rechner, der antwortet. Rückgabe: Antwortobjekt.
    Weiter zum nächsten Rechner nur bei Verbindungsfehler, Verbindungs-Zeitüberschreitung
    oder Fehlerantwort (z.B. Modell fehlt). Lese-Zeitüberschreitung bricht nachts ab (eine lange
    Antwort wird nicht woanders wiederholt); tagsüber (05.10.2026) heißt sie "Rechner hängt" -
    dann ist der nächste dran. Antwortet keiner: LokalNichtErreichbar."""
    alle = ziele(tag)
    letzter: Exception | None = None
    lese_zeit = OLLAMA_TIMEOUT if tag else OLLAMA_NACHT_TIMEOUT
    if not tag:
        payload = {**payload, "options": {**(payload.get("options") or {}), "num_ctx": OLLAMA_NACHT_NUM_CTX}}
    for z in alle:
        daten = {**payload, "model": z["modell"], "think": False, "keep_alive": OLLAMA_KEEP_ALIVE}
        _agent("ki_start", z.get("name", "lokal"), z.get("modell", ""), tag)
        try:
            for versuch in (daten, {k: v for k, v in daten.items() if k != "think"}):
                resp = requests.post(f"{z['url']}/api/chat", json=versuch,
                                     timeout=(OLLAMA_CONNECT_TIMEOUT, lese_zeit), stream=stream)
                try:
                    resp.raise_for_status()
                except requests.exceptions.HTTPError as exc:
                    # Ältere Ollama-Version kennt "think" nicht: einmal ohne wiederholen
                    if versuch is daten and getattr(resp, "status_code", 0) == 400:
                        resp.close()
                        continue
                    raise exc
                letztes_ziel.clear()
                letztes_ziel.update(z)
                return resp
        except requests.exceptions.ReadTimeout as exc:
            if not tag:
                raise _wrap_request_error(exc, alle, lese_zeit) from exc
            letzter = exc  # tagsüber: kein erstes Wort in lese_zeit Sekunden -> nächster Rechner
            _agent("ki_fehler", z.get("name", "lokal"), "hängt")
            continue
        except requests.exceptions.RequestException as exc:
            letzter = exc
            _agent("ki_fehler", z.get("name", "lokal"), exc.__class__.__name__)
            continue
    raise _wrap_request_error(letzter or requests.exceptions.ConnectionError(), alle, lese_zeit, LokalNichtErreichbar)


class _OllamaMessages:
    def __init__(self, tag: bool = False) -> None:
        self._tag = tag

    def create(self, *, model: str, max_tokens: int, system: Any, messages: list[dict]) -> _Message:
        payload = {
            "messages": _ollama_messages(system, messages),
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        start = time.time()
        resp = _anfrage(payload, stream=False, tag=self._tag)
        data = resp.json()
        _agent("ki_ende", letztes_ziel.get("name", "lokal"), letztes_ziel.get("modell", ""),
               data.get("eval_count"), time.time() - start)
        text = _bereinigen((data.get("message") or {}).get("content", ""))
        usage = _Usage(
            input_tokens=data.get("prompt_eval_count", 0) or 0,
            output_tokens=data.get("eval_count", 0) or 0,
        )
        msg = _Message(text, usage)
        if data.get("done_reason") == "length":  # Grenze num_predict erreicht = abgeschnitten
            msg.stop_reason = "max_tokens"
        return msg

    def stream(self, *, model: str, max_tokens: int, system: Any, messages: list[dict]) -> "_OllamaStream":
        return _OllamaStream(system, messages, max_tokens, self._tag)


class _OllamaStream:
    """Kontextmanager wie client.messages.stream() bei Anthropic: .text_stream
    zum Durchlaufen, danach .get_final_message() für Gesamttext und Usage."""

    def __init__(self, system: Any, messages: list[dict], max_tokens: int, tag: bool = False) -> None:
        self._tag = tag
        self._system = system
        self._messages = messages
        self._max_tokens = max_tokens
        self._response: requests.Response | None = None
        self._final_text = ""
        self._final_usage = _Usage()
        self.done_reason: str | None = None

    def __enter__(self) -> "_OllamaStream":
        payload = {
            "messages": _ollama_messages(self._system, self._messages),
            "stream": True,
            "options": {"num_predict": self._max_tokens},
        }
        self._start = time.time()
        self._response = _anfrage(payload, stream=True, tag=self._tag)
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if self._response is not None:
            self._response.close()
        return False

    @property
    def text_stream(self) -> Iterator[str]:
        assert self._response is not None
        try:
            for line in self._response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                piece = (chunk.get("message") or {}).get("content", "")
                if piece:
                    self._final_text += piece
                    yield piece
                if chunk.get("done"):
                    self.done_reason = chunk.get("done_reason")
                    self._final_usage = _Usage(
                        input_tokens=chunk.get("prompt_eval_count", 0) or 0,
                        output_tokens=chunk.get("eval_count", 0) or 0,
                    )
                    _agent("ki_ende", letztes_ziel.get("name", "lokal"), letztes_ziel.get("modell", ""),
                           chunk.get("eval_count"), time.time() - getattr(self, "_start", time.time()))
        except requests.exceptions.RequestException as exc:
            raise _wrap_request_error(exc) from exc

    def get_final_message(self) -> _Message:
        msg = _Message(self._final_text, self._final_usage)
        if self.done_reason == "length":
            msg.stop_reason = "max_tokens"
        return msg


class OllamaClient:
    def __init__(self, tag: bool = False) -> None:
        self.messages = _OllamaMessages(tag)


# ---------------------------------------------------------------------------
# Tagbetrieb (05.10.2026): erst lokal, Claude nur als Rückfall - und immer sichtbar
# ---------------------------------------------------------------------------

# Chinesisch, Japanisch, Koreanisch: Qwen rutscht bei langem Kontext manchmal in seine Heimatschrift.
_FREMDSCHRIFT_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")
_WORT_SCHLEIFE_RE = re.compile(r"\b(\w{2,})\b(?:\W+\1\b){7,}", re.I)
_SATZ_TRENNER_RE = re.compile(r"[.!?\n]+")


def pruefe_antwort(text: str, fertig: bool = True, done_reason: str | None = None) -> str | None:
    """Ist eine lokale Antwort klar unbrauchbar? Rückgabe: Grund in einfachen Worten oder None.
    Bewusst nur eindeutige Fälle (Entscheidung Sir 05.10.2026: automatisch nur bei klar kaputten
    Antworten, sonst entscheidet Sir per Knopf "Claude fragen"). Kostet nichts, prüft nur Text.
    fertig=False: Prüfung während des Streamens (nur Fremdschrift und Schleife)."""
    text = text or ""
    if len(_FREMDSCHRIFT_RE.findall(text)) >= 3:
        return "Antwort in fremder Schrift (chinesische Zeichen)"
    if _WORT_SCHLEIFE_RE.search(text):
        return "Antwort wiederholt sich (Endlosschleife)"
    saetze = [s.strip().lower() for s in _SATZ_TRENNER_RE.split(text) if len(s.strip()) >= 15]
    if saetze and max(saetze.count(s) for s in set(saetze)) >= 4:
        return "Antwort wiederholt sich (Endlosschleife)"
    if fertig and not _bereinigen(text):
        return "leere Antwort"
    if fertig and done_reason == "length":
        return "Antwort abgeschnitten"
    return None


class Ersetzen(str):
    """Markierung im text_stream: alles bisher Gestreamte verwerfen, gleich kommt Claudes Antwort.
    Ist ein str (leer), damit alte Aufrufer, die nur Text aneinanderhängen, nicht abstürzen."""

    def __new__(cls, grund: str) -> "Ersetzen":
        obj = super().__new__(cls, "")
        obj.grund = grund
        return obj


# P23 (13.10.2026): Code-Aufgaben haben einen eigenen Deckel; reicht er nicht, kein Rückfall auf Claude
# (und nie auf den normalen Topf). Die lokale KI wird dadurch nie gesperrt.
CODE_MIN_REST_USD = 0.20


def _rest_reicht(topf: str = "normal") -> bool:
    """Monatsrahmen für den Claude-Rückfall prüfen. Spät importiert (kein Ringimport), Fehler = erlaubt
    (beim Code-Topf: Fehler = gesperrt, harte Grenze)."""
    if topf == "code":
        try:
            from app import kosten  # noqa: PLC0415

            return kosten.code_rest() >= CODE_MIN_REST_USD
        except Exception:  # noqa: BLE001
            return False
    try:
        from app import kosten  # noqa: PLC0415

        return float(kosten.uebersicht()["rest_usd"]) >= RUECKFALL_MIN_REST_USD
    except Exception:  # noqa: BLE001 - Kostenübersicht darf den Rückfall nie blockieren
        return True


class TagClient:
    """Wie ein Anthropic-Client (messages.create / messages.stream), aber: erst die lokalen Rechner
    aus "reihenfolge_tag", Claude nur als Rückfall (falls "tag_rueckfall": "claude").
    Nach jeder Antwort steht in .info, wer geantwortet hat:
        {"quelle": "lokal"|"claude", "rechner": "Haupt-PC", "modell": "qwen3.5:9b",
         "rueckfall": bool, "grund": "..." (nur beim Rückfall)}"""

    def __init__(self, get_api_key: Callable[[], str], claude_modell: str, nur_claude: bool = False,
                 topf: str = "normal") -> None:
        self._get_api_key = get_api_key
        self.topf = topf
        self.claude_modell = claude_modell
        self.nur_claude = nur_claude
        self.info: dict[str, Any] = {}
        self.rueckfall_erlaubt = tag_rueckfall() == "claude"  # einmal je Anfrage lesen, nicht je Wort
        self.messages = _TagMessages(self)

    def claude(self):
        import anthropic  # noqa: PLC0415

        return anthropic.Anthropic(api_key=self._get_api_key())

    def vor_claude(self, grund: str | None) -> None:
        """Vor jedem Claude-Aufruf: Rahmen prüfen, Ziel für Protokoll und Anzeige merken."""
        if self.topf == "code" and not _rest_reicht("code"):
            raise RuntimeError(f"{grund or 'Lokale KI nicht verfügbar'} - und der Code-Deckel für Claude ist "
                               "fast aufgebraucht. Bitte Haupt-PC oder Test-PC einschalten, Sir.")
        if self.topf != "code" and not self.nur_claude and not _rest_reicht():
            raise RuntimeError(f"{grund or 'Lokale KI nicht verfügbar'} - und der Monatsrahmen für Claude ist "
                               "fast aufgebraucht. Bitte Haupt-PC oder Test-PC einschalten, Sir.")

        letztes_ziel.clear()
        letztes_ziel.update({"name": "Claude", "url": "", "modell": self.claude_modell})
        self.info = {"quelle": "claude", "rechner": "Claude", "modell": self.claude_modell,
                     "rueckfall": not self.nur_claude, "grund": grund or ("auf Wunsch" if self.nur_claude else "")}
        _agent("ki_start", "Claude", self.claude_modell, True)

    def lokal_gemerkt(self) -> None:
        self.info = {"quelle": "lokal", "rechner": letztes_ziel.get("name", "lokal"),
                     "modell": letztes_ziel.get("modell", ""), "rueckfall": False, "grund": ""}


class _TagMessages:
    def __init__(self, client: TagClient) -> None:
        self._c = client

    def create(self, *, model: str, max_tokens: int, system: Any, messages: list[dict], **rest: Any):
        c = self._c
        grund = None
        if not c.nur_claude:
            try:
                msg = OllamaClient(tag=True).messages.create(model=model, max_tokens=max_tokens, system=system,
                                                             messages=messages)
                grund = pruefe_antwort(msg.content[0].text if msg.content else "", True,
                                       "length" if msg.stop_reason == "max_tokens" else None)
                if not grund or not c.rueckfall_erlaubt:
                    c.lokal_gemerkt()
                    return msg
            except RuntimeError as exc:  # LokalNichtErreichbar oder Abbruch mitten in der Antwort
                if not c.rueckfall_erlaubt:
                    raise
                grund = "Lokale KI nicht erreichbar" if isinstance(exc, LokalNichtErreichbar) else f"Lokale KI abgebrochen ({exc})"
        c.vor_claude(grund)
        antwort = c.claude().messages.create(model=c.claude_modell, max_tokens=max_tokens, system=system,
                                             messages=messages, **rest)
        _agent("ki_ende", "Claude", c.claude_modell, None, None)
        return antwort

    def stream(self, *, model: str, max_tokens: int, system: Any, messages: list[dict], **rest: Any) -> "_TagStream":
        return _TagStream(self._c, model, max_tokens, system, messages, rest)


class _TagStream:
    """Kontextmanager wie client.messages.stream(). Fällt die lokale Antwort aus oder ist sie
    unbrauchbar, kommt im text_stream ein Ersetzen(grund) und danach Claudes Antwort."""

    def __init__(self, c: TagClient, model: str, max_tokens: int, system: Any, messages: list[dict],
                 rest: dict[str, Any]) -> None:
        self._c, self._model, self._max_tokens = c, model, max_tokens
        self._system, self._messages, self._rest = system, messages, rest
        self._lokal: _OllamaStream | None = None
        self._claude_cm = None
        self._claude = None
        self._grund: str | None = None

    def __enter__(self) -> "_TagStream":
        if not self._c.nur_claude:
            try:
                self._lokal = _OllamaStream(self._system, self._messages, self._max_tokens, tag=True).__enter__()
                self._c.lokal_gemerkt()
            except LokalNichtErreichbar:
                if not self._c.rueckfall_erlaubt:
                    raise
                self._grund = "Lokale KI nicht erreichbar"
        if self._lokal is None:
            self._claude_starten()
        return self

    def _claude_starten(self) -> None:
        self._c.vor_claude(self._grund)
        self._claude_cm = self._c.claude().messages.stream(
            model=self._c.claude_modell, max_tokens=self._max_tokens, system=self._system,
            messages=self._messages, **self._rest)
        self._claude = self._claude_cm.__enter__()

    def _lokal_schliessen(self) -> None:
        if self._lokal is not None:
            try:
                self._lokal.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass

    @property
    def text_stream(self) -> Iterator[str]:
        if self._lokal is not None and self._claude is None:
            text, grund = "", None
            try:
                for piece in self._lokal.text_stream:
                    text += piece
                    yield piece
                    if self._c.rueckfall_erlaubt:
                        grund = pruefe_antwort(text, fertig=False)
                        if grund:
                            break
                else:
                    grund = pruefe_antwort(text, True, self._lokal.done_reason)
            except RuntimeError as exc:
                if not self._c.rueckfall_erlaubt:
                    raise
                grund = f"Verbindung zur lokalen KI mitten in der Antwort abgerissen ({exc})"
            if not grund or not self._c.rueckfall_erlaubt:
                return
            self._grund = grund
            self._lokal_schliessen()
            self._lokal = None
            yield Ersetzen(grund)
            self._claude_starten()
        if self._claude is not None:
            yield from self._claude.text_stream
            _agent("ki_ende", "Claude", self._c.claude_modell, None, None)

    def get_final_message(self):
        if self._claude is not None:
            return self._claude.get_final_message()
        return self._lokal.get_final_message() if self._lokal is not None else _Message("", _Usage())

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self._lokal_schliessen()
        if self._claude_cm is not None:
            try:
                self._claude_cm.__exit__(exc_type, exc, traceback)
            except Exception:  # noqa: BLE001
                pass
        return False

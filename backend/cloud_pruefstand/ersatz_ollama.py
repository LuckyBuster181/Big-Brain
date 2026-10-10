"""
Ersatz-Ollama für den Cloud-Prüfstand (10.10.2026, Claude Code).

Spielt die wenigen Ollama-Adressen nach, die Jarvis benutzt (llm/provider.py, app/ki_status.py):
    GET  /api/tags, /api/ps, /api/version
    POST /api/chat      (mit und ohne stream), POST /api/generate
Antwortet immer fest und sofort, kostet nichts. Verlangt die Anfrage JSON, kommt "{}" zurück.
Jede Anfrage wird in ANFRAGEN gemerkt, damit der Prüfstand sehen kann, was Jarvis gefragt hat.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELL = "ersatz:1b"
ANTWORT = "Sir, das ist eine Testantwort vom Ersatz-Modell im Cloud-Prüfstand."
ANFRAGEN: list[dict] = []


def _antwort_fuer(nachrichten: list[dict]) -> str:
    text = " ".join(str(n.get("content", "")) for n in nachrichten).lower()
    if "json" in text:
        return "{}"
    if "du bist der sucher" in text:
        return "VAULT: Testnotiz gefunden (Ersatz-Modell).\nINTERNET: nicht gesucht\nLÜCKEN: keine"
    return ANTWORT


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # leise
        pass

    def _json(self, daten: dict, status: int = 200) -> None:
        roh = json.dumps(daten).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/tags":
            self._json({"models": [{"name": MODELL, "model": MODELL, "size": 1}]})
        elif self.path == "/api/ps":
            self._json({"models": [{"name": MODELL, "model": MODELL}]})
        elif self.path == "/api/version":
            self._json({"version": "0.0-ersatz"})
        else:
            self._json({"error": "unbekannt"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        laenge = int(self.headers.get("Content-Length") or 0)
        try:
            daten = json.loads(self.rfile.read(laenge) or b"{}")
        except json.JSONDecodeError:
            self._json({"error": "kein JSON"}, 400)
            return
        ANFRAGEN.append({"pfad": self.path, "daten": daten})
        if self.path == "/api/generate":
            self._json({"model": daten.get("model", MODELL), "done": True})
            return
        if self.path != "/api/chat":
            self._json({"error": "unbekannt"}, 404)
            return
        text = _antwort_fuer(daten.get("messages") or [])
        if not daten.get("stream"):
            self._json({"model": MODELL, "message": {"role": "assistant", "content": text}, "done": True,
                        "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 20})
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for wort in text.split(" "):
            zeile = {"model": MODELL, "message": {"role": "assistant", "content": wort + " "}, "done": False}
            self.wfile.write((json.dumps(zeile) + "\n").encode("utf-8"))
        ende = {"model": MODELL, "message": {"role": "assistant", "content": ""}, "done": True,
                "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 20}
        self.wfile.write((json.dumps(ende) + "\n").encode("utf-8"))


def starten(port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """Startet den Ersatz im Hintergrund. Rückgabe: (Server, URL)."""
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"

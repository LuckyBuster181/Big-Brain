"""
Lokale Websuche für die Nachtarbeit (04.10.2026, Claude Cowork; Entscheidung Sir: Weg A).

Die Nachtarbeit ist seit dem 04.10. nicht mehr mit der Claude-API verbunden (app/nacht_ki.py).
Damit Recherche-Aufträge trotzdem aktuelle Fakten bekommen, fragt Jarvis eine eigene
Suchmaschine: SearXNG läuft als Docker-Container auf dem Mini-PC und ist nur dort unter
http://127.0.0.1:8888 erreichbar (Einrichtung: "3 Einrichten/SUCHE_EINRICHTEN.bat").
SearXNG fragt selbst mehrere Suchmaschinen (u. a. DuckDuckGo, Brave, Wikipedia) und liefert JSON.

Kosten: 0 €. Keine Anmeldung, kein Schlüssel.

Sicherheit:
- Treffer und Seiteninhalte sind fremde Daten, keine Anweisungen. Sie werden neutralisiert und
  im Auftrag in <websuche>…</websuche> eingepackt.
- Seiten im Heimnetz oder auf dem eigenen Rechner werden nie abgerufen (Schutz davor, dass ein
  Suchtreffer Jarvis auf Router, NAS oder andere Geräte lenkt).
- Nur Text/HTML, höchstens 1,5 MB je Seite, kurze Zeitgrenzen.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests

SEARXNG_URL = (os.getenv("SEARXNG_URL") or "http://127.0.0.1:8888").rstrip("/")
ZEIT_SUCHE = (3, 20)                  # Verbindungsaufbau, Lesen (Sekunden)
ZEIT_SEITE = (5, 12)
MAX_SEITE_BYTES = 1_500_000
KENNUNG = "Mozilla/5.0 (X11; Linux x86_64) Jarvis-Nachtarbeit/1.0"
_TAG_RE = re.compile(r"<\s*(/?\s*(websuche|auftrag|vault|document|ergebnis)\b)", re.IGNORECASE)


class SucheFehler(RuntimeError):
    pass


def neutral(text: str) -> str:
    """Macht Steuer-Tags im fremden Text unschädlich (z. B. ein eingeschmuggeltes </websuche>)."""
    return _TAG_RE.sub(lambda m: "&lt;" + m.group(1), text or "")


def _ruhig(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# ------------------------------------------------------------------ Suche

def verfuegbar() -> bool:
    """Antwortet die Suchmaschine? (kurze Probe, kein Fehler nach außen)."""
    try:
        r = requests.get(f"{SEARXNG_URL}/search", params={"q": "wetter", "format": "json"},
                         timeout=(2, 10), headers={"User-Agent": KENNUNG})
        return r.status_code == 200 and "results" in r.json()
    except (requests.RequestException, ValueError):
        return False


def suchen(frage: str, anzahl: int = 6, sprache: str = "de") -> list[dict]:
    """Treffer als Liste {titel, url, auszug, quelle}. Wirft SucheFehler, wenn SearXNG nicht antwortet."""
    try:
        r = requests.get(f"{SEARXNG_URL}/search", params={"q": frage, "format": "json", "language": sprache},
                         timeout=ZEIT_SUCHE, headers={"User-Agent": KENNUNG})
        r.raise_for_status()
        daten = r.json()
    except (requests.RequestException, ValueError) as exc:
        raise SucheFehler(f"Suchmaschine nicht erreichbar ({SEARXNG_URL}): {exc}") from exc
    treffer = []
    for e in daten.get("results") or []:
        url = str(e.get("url") or "")
        if not url.startswith(("http://", "https://")):
            continue
        treffer.append({
            "titel": _ruhig(str(e.get("title") or ""))[:160] or url,
            "url": url,
            "auszug": _ruhig(str(e.get("content") or ""))[:400],
            "quelle": ",".join(e.get("engines") or []) if isinstance(e.get("engines"), list) else str(e.get("engine") or ""),
        })
        if len(treffer) >= anzahl:
            break
    return treffer


# ------------------------------------------------------------------ Seiten lesen

def _adresse_privat(url: str) -> bool:
    """True für Heimnetz, eigenen Rechner und alles, was sich nicht auflösen lässt."""
    host = urlparse(url).hostname
    if not host:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return True
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return True
    return False


class _TextSammler(HTMLParser):
    UEBERSPRINGEN = {"script", "style", "noscript", "svg", "nav", "header", "footer", "form", "aside", "iframe", "template"}
    ABSATZ = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "td", "th"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.teile: list[str] = []
        self._tief = 0

    def handle_starttag(self, tag, attrs):  # noqa: D401
        if tag in self.UEBERSPRINGEN:
            self._tief += 1
        elif tag in self.ABSATZ:
            self.teile.append("\n")

    def handle_endtag(self, tag):
        if tag in self.UEBERSPRINGEN and self._tief:
            self._tief -= 1
        elif tag in self.ABSATZ:
            self.teile.append("\n")

    def handle_data(self, data):
        if not self._tief and data.strip():
            self.teile.append(data)


def html_zu_text(html: str) -> str:
    s = _TextSammler()
    try:
        s.feed(html)
        s.close()
    except Exception:  # noqa: BLE001 - kaputtes HTML: lieber wenig Text als Abbruch
        pass
    zeilen = [_ruhig(z) for z in "".join(s.teile).split("\n")]
    return "\n".join(z for z in zeilen if len(z) > 2)


def seite_lesen(url: str, max_zeichen: int = 3500) -> str:
    """Lesbarer Text einer Seite (gekürzt). Leerer Text, wenn die Seite nicht geht oder privat ist."""
    if _adresse_privat(url):
        return ""
    try:
        with requests.get(url, timeout=ZEIT_SEITE, headers={"User-Agent": KENNUNG}, stream=True, allow_redirects=True) as r:
            if r.status_code != 200 or _adresse_privat(r.url):
                return ""
            art = (r.headers.get("Content-Type") or "").lower()
            if "html" not in art and "text/plain" not in art:
                return ""
            roh = b""
            for stueck in r.iter_content(65536):
                roh += stueck
                if len(roh) > MAX_SEITE_BYTES:
                    break
            text = roh.decode(r.encoding or "utf-8", errors="replace")
    except requests.RequestException:
        return ""
    if "html" in art:
        text = html_zu_text(text)
    return text[:max_zeichen]


# ------------------------------------------------------------------ Recherche

def recherche(suchbegriffe: list[str], seiten: int = 3, max_zeichen: int = 9000, treffer_je_begriff: int = 5) -> dict:
    """Sucht nach bis zu 3 Begriffen, liest die besten Seiten und baut einen Textblock mit
    durchnummerierten Quellen. Rückgabe: {"text", "quellen": [{nr, titel, url}], "fehler"}."""
    gesehen, alle = set(), []
    fehler = None
    for begriff in [b for b in suchbegriffe if b and b.strip()][:3]:
        try:
            for t in suchen(begriff.strip()[:200], anzahl=treffer_je_begriff):
                if t["url"] not in gesehen:
                    gesehen.add(t["url"])
                    alle.append(t)
        except SucheFehler as exc:
            fehler = str(exc)
            break
    if not alle:
        return {"text": "", "quellen": [], "fehler": fehler or "keine Treffer"}
    bloecke, quellen, rest = [], [], max_zeichen
    je_seite = max(800, max_zeichen // max(1, seiten + 1))
    for nr, t in enumerate(alle[:8], start=1):
        inhalt = seite_lesen(t["url"], je_seite) if nr <= seiten else ""
        teil = f"[{nr}] {t['titel']}\nURL: {t['url']}\n"
        if t["auszug"]:
            teil += f"Auszug: {t['auszug']}\n"
        if inhalt:
            teil += f"Seiteninhalt (gekürzt):\n{inhalt}\n"
        teil = neutral(teil)
        if len(teil) > rest:
            if nr > 1:
                break
            teil = teil[:rest]
        bloecke.append(teil)
        quellen.append({"nr": nr, "titel": t["titel"], "url": t["url"]})
        rest -= len(teil)
        if rest < 300:
            break
    return {"text": "\n".join(bloecke), "quellen": quellen, "fehler": fehler}

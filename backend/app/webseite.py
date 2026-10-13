"""
Webseite speichern (Zusatzfunktion Phase 2, 23.09.2026): Link rein, Jarvis
holt die Seite, macht daraus reinen Text und legt einen VORSCHLAG für eine
neue Entwurfs-Notiz an (app/vorschlaege.py). Sir übernimmt oder verwirft.

Keine Claude-Kosten: Abruf und Textauszug laufen lokal. Der Seiteninhalt ist
fremder Text - er landet mit status: entwurf und Quelle im Vault und wird von
Jarvis wie alle Notizen nur als Daten behandelt (Schutz vor Anweisungen in
Notizen, siehe chat_service).
"""

from __future__ import annotations

import datetime
import html
import re
import urllib.request
from html.parser import HTMLParser

from . import vorschlaege

ORDNER = "Wissen/10 - Webseiten Entwürfe"
MAX_BYTES = 3_000_000
MAX_TEXT = 20_000
TIMEOUT_S = 15
_URL = re.compile(r"^https?://[^\s/$.?#][^\s]*$", re.I)


class WebseitenFehler(ValueError):
    pass


class _Auszug(HTMLParser):
    """Sammelt Titel und sichtbaren Text, ohne Skripte, Stile, Navigation."""

    WEG = {"script", "style", "noscript", "nav", "footer", "header", "svg", "form", "aside", "iframe"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "pre", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.titel = ""
        self._im_titel = False
        self._weg = 0
        self.teile: list[str] = []

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        if tag in self.WEG:
            self._weg += 1
        elif tag == "title":
            self._im_titel = True
        elif tag in self.BLOCK:
            self.teile.append("\n")
        if tag in ("h1", "h2", "h3") and not self._weg:
            self.teile.append("\n## " if tag != "h1" else "\n# ")
        if tag == "li" and not self._weg:
            self.teile.append("- ")

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag in self.WEG and self._weg:
            self._weg -= 1
        elif tag == "title":
            self._im_titel = False
        elif tag in self.BLOCK:
            self.teile.append("\n")

    def handle_data(self, data):  # noqa: ANN001
        if self._im_titel:
            self.titel += data
        elif not self._weg:
            self.teile.append(data)


def text_auszug(roh_html: str) -> tuple[str, str]:
    p = _Auszug()
    p.feed(roh_html)
    text = html.unescape("".join(p.teile))
    zeilen = [re.sub(r"[ \t\xa0]+", " ", z).strip() for z in text.splitlines()]
    sauber, leer = [], 0
    for z in zeilen:
        if not z or z in ("#", "##", "-"):
            leer += 1
            if leer == 1 and sauber:
                sauber.append("")
            continue
        leer = 0
        sauber.append(z)
    return re.sub(r"\s+", " ", p.titel).strip(), "\n".join(sauber).strip()


def abrufen(url: str) -> str:
    if not _URL.match(url or ""):
        raise WebseitenFehler("Das ist keine gültige Webadresse (http/https).")
    anfrage = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Jarvis/1.0",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
        "Accept-Language": "de,en;q=0.7",
    })
    try:
        with urllib.request.urlopen(anfrage, timeout=TIMEOUT_S) as antwort:  # noqa: S310 - nur http/https geprüft
            art = antwort.headers.get("Content-Type", "")
            if "html" not in art and "text" not in art:
                raise WebseitenFehler(f"Keine Webseite, sondern {art or 'unbekannter Inhalt'}.")
            daten = antwort.read(MAX_BYTES + 1)
            zeichensatz = antwort.headers.get_content_charset() or "utf-8"
    except WebseitenFehler:
        raise
    except Exception as exc:  # noqa: BLE001
        raise WebseitenFehler(f"Seite nicht erreichbar: {exc}") from exc
    return daten[:MAX_BYTES].decode(zeichensatz, errors="replace")


def dateiname(titel: str, url: str) -> str:
    basis = re.sub(r'[<>:"/\\|?*\x00-\x1f#\[\]^]', "", titel or "").strip()
    if not basis:
        basis = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
    return re.sub(r"\s+", " ", basis)[:80].strip(" .") or "Webseite"


def als_vorschlag(url: str, roh_html: str | None = None) -> dict:
    roh = roh_html if roh_html is not None else abrufen(url)
    titel, text = text_auszug(roh)
    if len(text) < 80:
        raise WebseitenFehler("Auf der Seite steht kaum lesbarer Text (evtl. nur per JavaScript geladen).")
    gekuerzt = len(text) > MAX_TEXT
    heute = datetime.date.today().isoformat()
    inhalt = (
        f"Quelle: {url}\nAbgerufen: {heute} (automatisch von Auron, ungeprüft)\n\n"
        + text[:MAX_TEXT]
        + ("\n\n*[... gekürzt]*" if gekuerzt else "")
    )
    name = dateiname(titel, url)
    return vorschlaege.anlegen(
        inhalt,
        ziel=f"{ORDNER}/{name}.md",
        grund=f"Webseite gespeichert: {url}",
        quelle="webseite",
        titel=name,
    )

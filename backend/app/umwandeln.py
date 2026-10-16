"""
Dateien umwandeln (27.09.2026, Claude Cowork) - 0 Cent, alles lokal.

Quelle ist immer eine Datei in der Datei-Ablage (data/ablage - vom Handy mit
"Datei senden", vom HUD oder in den Ordner gelegt). Das Ergebnis landet
wieder in der Ablage (nichts wird überschrieben) und ist im HUD bzw. über
/api/ablage/datei?name=... herunterladbar.

Was geht:
    PDF  -> PNG / JPG (jede Seite ein Bild), TXT (Text herausziehen)
    Bild -> PNG / JPG / WEBP / GIF / BMP / PDF   (PNG, JPG, WEBP, GIF, BMP, TIFF)
    mehrere Bilder -> ein PDF ("die letzten 3 Bilder als PDF")
    DOCX/ODT/PPTX/XLSX -> PDF, nur wenn LibreOffice (soffice) installiert ist

Werkzeuge der Reihe nach: PyMuPDF (Paket "pymupdf"), sonst pdftoppm/pdftotext
(Ubuntu: poppler-utils), Bilder mit Pillow (schon in requirements.txt).

Chat (app/alltag.umwandel_absicht):
    "Wandle Rechnung.pdf in PNG um"  /  "Mach aus der letzten PDF Bilder"
    "Konvertiere foto.webp zu jpg"   /  "Die letzten 3 Bilder als PDF"
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import ablage

BILD = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
BUERO = {".docx", ".doc", ".odt", ".pptx", ".ppt", ".odp", ".xlsx", ".xls", ".ods", ".rtf"}
ZIELE = {"png", "jpg", "jpeg", "webp", "gif", "bmp", "pdf", "txt"}
DPI = int(os.getenv("UMWANDELN_DPI", "150"))
MAX_SEITEN = int(os.getenv("UMWANDELN_MAX_SEITEN", "40"))
PIL_FORMAT = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP", "gif": "GIF", "bmp": "BMP", "pdf": "PDF"}


class UmwandelFehler(ValueError):
    pass


def ziel_normal(ziel: str) -> str:
    z = (ziel or "").strip().lower().lstrip(".")
    z = {"jpeg": "jpg", "bild": "png", "bilder": "png", "text": "txt"}.get(z, z)
    if z not in ZIELE:
        raise UmwandelFehler(f"Zielformat {ziel!r} kann ich nicht. Möglich: {', '.join(sorted(ZIELE - {'jpeg'}))}.")
    return z


def quelle_finden(name: str | None, art: str | None = None, anzahl: int = 1) -> list[Path]:
    """Dateien in der Ablage: exakter Name, Teil des Namens, oder die neuesten (optional nur PDF/Bilder)."""
    alle = [ablage.ordner() / e["name"] for e in ablage.liste()]  # neueste zuerst
    if art == "pdf":
        alle = [p for p in alle if p.suffix.lower() == ".pdf"]
    elif art == "bild":
        alle = [p for p in alle if p.suffix.lower() in BILD]
    if name:
        n = name.strip().strip('"\'').lower()
        genau = [p for p in alle if p.name.lower() == n]
        if genau:
            return genau[:1]
        teil = [p for p in alle if n in p.name.lower() or p.stem.lower() in n]
        if teil:
            return teil[:1]
        raise UmwandelFehler(f'"{name}" liegt nicht in der Datei-Ablage, Sir.')
    if not alle:
        raise UmwandelFehler("In der Datei-Ablage liegt keine passende Datei, Sir. Schicken Sie sie mit \"Datei senden\".")
    return alle[:max(1, anzahl)]


def _ablegen(name: str, inhalt: bytes) -> str:
    return ablage.speichern(name, inhalt)["name"]


def _pdf_seiten_als_bilder(quelle: Path, ziel: str) -> list[str]:
    namen: list[str] = []
    try:
        import fitz  # PyMuPDF

        with fitz.open(quelle) as doc:
            if doc.page_count > MAX_SEITEN:
                raise UmwandelFehler(f"Die PDF hat {doc.page_count} Seiten - höchstens {MAX_SEITEN} auf einmal.")
            for i, seite in enumerate(doc, 1):
                pix = seite.get_pixmap(dpi=DPI)
                roh = pix.tobytes("png")
                namen.append(_ablegen(f"{quelle.stem}_seite-{i}.{ziel}", _bild_umrechnen(roh, ziel)))
        return namen
    except ImportError:
        pass
    if not shutil.which("pdftoppm"):
        raise UmwandelFehler("Zum Umwandeln von PDFs fehlt das Paket PyMuPDF. Einmal \"AURON STARTEN.bat\" "
                             "starten - die Datei installiert es auf dem Mini-PC nach.")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", str(DPI), "-png", "-l", str(MAX_SEITEN), str(quelle), f"{tmp}/s"],
                       check=True, capture_output=True, timeout=180)
        for i, p in enumerate(sorted(Path(tmp).glob("s*.png"), key=lambda x: int(re.findall(r"\d+", x.stem)[-1])), 1):
            namen.append(_ablegen(f"{quelle.stem}_seite-{i}.{ziel}", _bild_umrechnen(p.read_bytes(), ziel)))
    if not namen:
        raise UmwandelFehler("Die PDF enthielt keine lesbaren Seiten.")
    return namen


def _pdf_text(quelle: Path) -> str:
    try:
        import fitz

        with fitz.open(quelle) as doc:
            text = "\n\n".join(f"--- Seite {i} ---\n{s.get_text()}" for i, s in enumerate(doc, 1))
    except ImportError:
        if not shutil.which("pdftotext"):
            raise UmwandelFehler("Zum Lesen von PDFs fehlt PyMuPDF (einmal \"AURON STARTEN.bat\" starten).") from None
        r = subprocess.run(["pdftotext", "-layout", str(quelle), "-"], capture_output=True, timeout=120, check=True)
        text = r.stdout.decode("utf-8", errors="replace")
    if not text.strip() or not re.search(r"\w{3}", text):
        raise UmwandelFehler("Die PDF enthält keinen Text (wohl eingescannt). Texterkennung (OCR) kann ich noch nicht.")
    return _ablegen(f"{quelle.stem}.txt", text.encode("utf-8"))


def _bild_umrechnen(roh: bytes, ziel: str) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(roh)) as bild:
        bild.load()
        if ziel in ("jpg", "jpeg", "bmp", "pdf") and bild.mode not in ("RGB", "L"):
            hinten = Image.new("RGB", bild.size, (255, 255, 255))
            if bild.mode in ("RGBA", "LA", "P"):
                bild = bild.convert("RGBA")
                hinten.paste(bild, mask=bild.split()[-1])
            else:
                hinten.paste(bild.convert("RGB"))
            bild = hinten
        aus = io.BytesIO()
        opt = {"quality": 90} if ziel in ("jpg", "jpeg", "webp") else {}
        if ziel == "pdf":
            opt = {"resolution": 150.0}
        bild.save(aus, PIL_FORMAT[ziel], **opt)
        return aus.getvalue()


def bilder_zu_pdf(quellen: list[Path], name: str | None = None) -> str:
    from PIL import Image

    seiten = []
    for q in quellen:
        with Image.open(q) as b:
            b.load()
            seiten.append(b.convert("RGB"))
    if not seiten:
        raise UmwandelFehler("Keine Bilder gefunden.")
    aus = io.BytesIO()
    seiten[0].save(aus, "PDF", resolution=150.0, save_all=True, append_images=seiten[1:])
    return _ablegen(name or f"{quellen[0].stem}{'_und_weitere' if len(quellen) > 1 else ''}.pdf", aus.getvalue())


def _buero_zu_pdf(quelle: Path) -> str:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise UmwandelFehler("Für Word/Excel/PowerPoint nach PDF fehlt LibreOffice auf dem Mini-PC "
                             "(sudo apt install libreoffice-writer).")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, str(quelle)],
                       check=True, capture_output=True, timeout=180)
        pdf = next(Path(tmp).glob("*.pdf"), None)
        if pdf is None:
            raise UmwandelFehler("LibreOffice hat keine PDF erzeugt.")
        return _ablegen(f"{quelle.stem}.pdf", pdf.read_bytes())


def umwandeln(quelle: Path, ziel: str) -> list[str]:
    """Wandelt eine Ablage-Datei um. Rückgabe: Namen der neuen Dateien in der Ablage."""
    ziel = ziel_normal(ziel)
    endung = quelle.suffix.lower()
    try:
        if endung == ".pdf":
            if ziel == "txt":
                return [_pdf_text(quelle)]
            if ziel == "pdf":
                raise UmwandelFehler("Die Datei ist schon eine PDF, Sir.")
            return _pdf_seiten_als_bilder(quelle, ziel)
        if endung in BILD:
            if ziel == "txt":
                raise UmwandelFehler("Text aus Bildern (OCR) kann ich noch nicht, Sir. Für TikTok-Slides gibt es "
                                     "\"Text lesen\" auf der TikTok-Seite.")
            if ziel == "pdf":
                return [bilder_zu_pdf([quelle])]
            neu = f"{quelle.stem}.{ziel}"
            return [_ablegen(neu, _bild_umrechnen(quelle.read_bytes(), ziel))]
        if endung in BUERO and ziel == "pdf":
            return [_buero_zu_pdf(quelle)]
        if endung == ".heic":
            raise UmwandelFehler("HEIC (iPhone-Fotos) kann ich noch nicht. Am iPhone unter Kamera → Formate "
                                 "\"Maximale Kompatibilität\" wählen, dann kommt JPG.")
    except subprocess.CalledProcessError as exc:
        raise UmwandelFehler(f"Umwandeln fehlgeschlagen: {exc.stderr.decode('utf-8', 'replace')[:200]}") from exc
    except ablage.AblageFehler as exc:
        raise UmwandelFehler(str(exc)) from exc
    except OSError as exc:
        raise UmwandelFehler(f"Die Datei ließ sich nicht öffnen: {exc}") from exc
    raise UmwandelFehler(f"Von {endung or 'diesem Typ'} nach {ziel.upper()} kann ich nicht umwandeln, Sir.")


def antwort(a: dict) -> str:
    """Chat-Antwort zu einer erkannten Umwandel-Absicht."""
    ziel = ziel_normal(a["ziel"])
    anzahl = int(a.get("anzahl") or 1)
    if ziel == "pdf" and anzahl > 1:
        quellen = quelle_finden(a.get("datei"), "bild", anzahl)
        namen = [bilder_zu_pdf(list(reversed(quellen)))]
        von = f"{len(quellen)} Bildern"
    else:
        quelle = quelle_finden(a.get("datei"), a.get("typ"))[0]
        namen = umwandeln(quelle, ziel)
        von = f'"{quelle.name}"'
    zeilen = [f"Fertig, Sir: aus {von} {'ist' if len(namen) == 1 else 'sind'} {len(namen)} "
              f"{'Datei' if len(namen) == 1 else 'Dateien'} entstanden, alle in der Datei-Ablage:"]
    zeilen += [f"- [{n}](/api/ablage/datei?name={_url(n)})" for n in namen[:15]]
    if len(namen) > 15:
        zeilen.append(f"- … und {len(namen) - 15} weitere")
    zeilen.append("Kosten: 0 Cent.")
    return "\n".join(zeilen)


def _url(name: str) -> str:
    from urllib.parse import quote

    return quote(name)

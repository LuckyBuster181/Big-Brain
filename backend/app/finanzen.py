"""
Finanzen (11.10.2026, Claude Code) - Vault-Notiz P03, Phase 2, Weg A (Entscheidung Sir 11.10.2026): CSV-Export.

NUR LESEND. Kein Bank-Login, keine Zugangsdaten, keine Funktion, die Geld bewegt.

Ablauf:
- Sir legt die Exporte in data/finanzen/eingang/ (oder lädt sie im Bereich "Finanzen" bzw. in der Ablage hoch).
- einlesen(): erkennt das Format am Kopf der Datei (Volksbank oder Revolut, genau wie in P03 beschrieben), liest die
  Umsätze ein und verschiebt die Datei nach data/finanzen/eingelesen/. Unbekanntes Format: klare Meldung mit den ersten
  Spaltennamen, nichts raten, Datei bleibt liegen. In der Ablage werden nur Dateien angefasst, deren Kopf passt.
- Doppelte Umsätze (gleiches Datum, Betrag, Empfänger, Verwendungszweck) werden nur einmal gespeichert. Zwei gleiche
  Zeilen in EINER Datei (z.B. zwei Kaffees zum selben Preis am selben Tag) bleiben zwei Umsätze - erst eine zweite
  Datei mit denselben Zeilen zählt als doppelt.
- abos(): gleicher Empfänger (bei Lastschriften Gläubiger-ID + Mandatsreferenz), ähnlicher Betrag, regelmäßiger
  Abstand (monatlich, vierteljährlich, halbjährlich, jährlich) -> Betrag pro Monat und Jahr.
- kuendigung(): Weg erklären und Kündigungstext entwerfen (Vorlage, 0 €). Sir verschickt selbst.
- fuer_briefing(): einmal im Monat Abo-Übersicht und Erinnerung "Neue Kontoauszüge als CSV in die Ablage legen".

Daten nur lokal in data/finanzen/ (FINANZEN_PATH): nicht im Repo, nicht im Vault, nicht im Log - dieses Modul schreibt
keine Beträge, Namen oder Verwendungszwecke auf die Konsole (sonst landeten sie im Fehlerbericht).
IBANs werden nicht gespeichert (für die Auswertung nicht nötig).
Kosten: 0 € (keine KI-Aufrufe).
"""

from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import io
import json
import math
import os
import re
import shutil
import statistics
import threading
from pathlib import Path
from typing import Any

# ------------------------------------------------------------------ Formate (P03, geprüft an echten Exporten)

FORMATE: dict[str, dict[str, Any]] = {
    "volksbank": {
        "name": "Volksbank", "trenner": ";",
        "spalten": ["Bezeichnung Auftragskonto", "IBAN Auftragskonto", "BIC Auftragskonto", "Bankname Auftragskonto",
                    "Buchungstag", "Valutadatum", "Name Zahlungsbeteiligter", "IBAN Zahlungsbeteiligter",
                    "BIC (SWIFT-Code) Zahlungsbeteiligter", "Buchungstext", "Verwendungszweck", "Betrag", "Waehrung",
                    "Saldo nach Buchung", "Bemerkung", "Kategorie", "Gekennzeichneter Umsatz", "Glaeubiger ID",
                    "Mandatsreferenz"],
    },
    "revolut": {
        "name": "Revolut", "trenner": ",",
        "spalten": ["Art", "Produkt", "Datum des Beginns", "Datum des Abschlusses", "Beschreibung", "Betrag", "Gebühr",
                    "Währung", "Status", "Kontostand"],
    },
}

# Abstände in Tagen: (Name, Monate je Zahlung, kleinster und größter Abstand)
RHYTHMEN = [("monatlich", 1, 26, 35), ("vierteljährlich", 3, 84, 98), ("halbjährlich", 6, 175, 190),
            ("jährlich", 12, 350, 380)]
MAX_DATEI_BYTES = 10 * 1024 * 1024
ERINNERUNG = "Neue Kontoauszüge als CSV in die Ablage legen"

_lock = threading.Lock()


class FinanzFehler(ValueError):
    pass


# ------------------------------------------------------------------ Ordner und Speicher

def ordner() -> Path:
    p = Path(os.getenv("FINANZEN_PATH") or Path(__file__).resolve().parents[2] / "data" / "finanzen")
    for teil in ("eingang", "eingelesen"):
        (p / teil).mkdir(parents=True, exist_ok=True)
    return p


def _datei() -> Path:
    return ordner() / "umsaetze.json"


def laden() -> list[dict]:
    try:
        daten = json.loads(_datei().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return daten.get("umsaetze", []) if isinstance(daten, dict) else []


def _speichern(umsaetze: list[dict]) -> None:
    umsaetze.sort(key=lambda u: (u["datum"], u.get("bank", ""), u.get("schluessel", "")))
    ziel = _datei()
    tmp = ziel.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": 1, "umsaetze": umsaetze}, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, ziel)


# ------------------------------------------------------------------ Format erkennen und lesen

def _norm_kopf(spalten: list[str]) -> list[str]:
    return [s.strip().strip('"').strip().casefold() for s in spalten]


def _text(roh: bytes) -> str:
    try:
        return roh.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FinanzFehler("Die Datei ist kein UTF-8-Text (in Excel gespeichert?). Bitte den Original-Export "
                           "der Bank nehmen, Sir.") from exc


def erkennen(roh: bytes) -> str:
    """Bank am Kopf der Datei erkennen. Wirft FinanzFehler mit klarer Meldung, wenn das Format unbekannt ist."""
    text = _text(roh)
    erste = text.splitlines()[0] if text.strip() else ""
    if not erste:
        raise FinanzFehler("Die Datei ist leer, Sir.")
    for bank, f in FORMATE.items():
        kopf = next(csv.reader([erste], delimiter=f["trenner"]), [])
        if _norm_kopf(kopf) == _norm_kopf(f["spalten"]):
            return bank
    if "Ã" in erste:
        raise FinanzFehler("Die Datei wurde offenbar in Excel gespeichert (Umlaute kaputt, z. B. „GebÃ¼hr“). "
                           "Bitte die Original-CSV aus der App bzw. dem Online-Banking nehmen, nicht in Excel öffnen "
                           "und speichern, Sir.")
    trenner = ";" if erste.count(";") > erste.count(",") else ","
    spalten = [s.strip().strip('"') for s in next(csv.reader([erste], delimiter=trenner), [])][:6]
    raise FinanzFehler(f"Unbekanntes Format, Sir. Erste Spalten: {', '.join(spalten) or '(keine)'}. "
                       "Ich lese nur Volksbank- und Revolut-Exporte (CSV) - nichts geraten, die Datei bleibt liegen.")


def _betrag_de(wert: str) -> float:
    w = (wert or "").strip().replace(" ", "")
    if not w:
        raise ValueError("leer")
    return float(w.replace(".", "").replace(",", "."))


def _betrag_punkt(wert: str) -> float:
    w = (wert or "").strip()
    return float(w) if w else 0.0


def _schluessel(datum: str, betrag: float, empfaenger: str, zweck: str) -> str:
    norm = lambda t: re.sub(r"\s+", " ", (t or "").strip().casefold())  # noqa: E731
    roh = f"{datum}|{betrag:.2f}|{norm(empfaenger)}|{norm(zweck)}"
    return hashlib.sha1(roh.encode("utf-8")).hexdigest()[:16]


def _zeilen_volksbank(text: str) -> tuple[list[dict], int]:
    umsaetze, kaputt = [], 0
    for z in csv.DictReader(io.StringIO(text), delimiter=";"):
        try:
            datum = _dt.datetime.strptime((z.get("Buchungstag") or "").strip(), "%d.%m.%Y").date().isoformat()
            betrag = _betrag_de(z.get("Betrag", ""))
        except ValueError:
            kaputt += 1
            continue
        empfaenger = (z.get("Name Zahlungsbeteiligter") or "").strip()
        umsaetze.append({
            "bank": "volksbank", "konto": (z.get("Bezeichnung Auftragskonto") or "Volksbank").strip(),
            "datum": datum, "betrag": round(betrag, 2), "waehrung": (z.get("Waehrung") or "EUR").strip() or "EUR",
            "empfaenger": empfaenger, "zweck": (z.get("Verwendungszweck") or "").strip(),
            "art": (z.get("Buchungstext") or "").strip(),
            "glaeubiger_id": (z.get("Glaeubiger ID") or "").strip(),
            "mandatsreferenz": (z.get("Mandatsreferenz") or "").strip(),
            # Überweisung an das eigene Revolut-Konto ist keine Ausgabe (sonst doppelt gezählt)
            "intern": "revolut" in empfaenger.casefold(),
            "offen": False,
        })
    return umsaetze, kaputt


def _zeilen_revolut(text: str) -> tuple[list[dict], int]:
    umsaetze, kaputt = [], 0
    for z in csv.DictReader(io.StringIO(text), delimiter=","):
        if (z.get("Status") or "").strip().upper() == "STORNIERT":
            continue
        try:
            # Datum des Beginns: steht schon bei offenen Buchungen, bleibt beim Abschluss gleich (Dubletten-Erkennung)
            datum = _dt.datetime.strptime((z.get("Datum des Beginns") or "").strip()[:10], "%Y-%m-%d").date().isoformat()
            # P03: Gebühr steht getrennt und muss zum Betrag gerechnet werden; eine Gebühr kostet immer Geld
            betrag = _betrag_punkt(z.get("Betrag", "")) - abs(_betrag_punkt(z.get("Gebühr", "")))
        except ValueError:
            kaputt += 1
            continue
        art = (z.get("Art") or "").strip()
        produkt = (z.get("Produkt") or "").strip()
        umsaetze.append({
            "bank": "revolut", "konto": f"Revolut {produkt}".strip(),
            "datum": datum, "betrag": round(betrag, 2), "waehrung": (z.get("Währung") or "EUR").strip() or "EUR",
            "empfaenger": (z.get("Beschreibung") or "").strip(), "zweck": "", "art": art,
            "glaeubiger_id": "", "mandatsreferenz": "",
            # Aufladen vom eigenen Konto, Währungstausch und Sparkonto sind keine Ausgaben oder Einnahmen
            "intern": art.casefold() in ("einzahlung", "umtausch") or bool(produkt and produkt.casefold() != "giro"),
            "offen": not (z.get("Datum des Abschlusses") or "").strip(),
        })
    return umsaetze, kaputt


def lesen(roh: bytes) -> tuple[str, list[dict], int]:
    """(bank, umsaetze, fehlerhafte Zeilen). Gleiche Zeilen in einer Datei bekommen eine laufende Nummer."""
    bank = erkennen(roh)
    text = _text(roh)
    umsaetze, kaputt = (_zeilen_volksbank if bank == "volksbank" else _zeilen_revolut)(text)
    gezaehlt: dict[str, int] = {}
    for u in umsaetze:
        basis = _schluessel(u["datum"], u["betrag"], u["empfaenger"], u["zweck"])
        gezaehlt[basis] = gezaehlt.get(basis, 0) + 1
        u["schluessel"] = f"{basis}-{gezaehlt[basis]}"
    return bank, umsaetze, kaputt


# ------------------------------------------------------------------ Einlesen

def _ablage_ordner() -> Path | None:
    try:
        from . import ablage  # noqa: PLC0415

        return ablage.ordner()
    except Exception:  # noqa: BLE001
        return None


def einlesen() -> dict:
    """Alle Dateien aus eingang/ (und passende CSVs aus der Ablage) einlesen. Rückgabe für Sir und den Bereich."""
    o = ordner()
    kandidaten = [(p, "eingang") for p in sorted((o / "eingang").iterdir()) if p.is_file()]
    ablage = _ablage_ordner()
    if ablage and ablage.is_dir():
        kandidaten += [(p, "ablage") for p in sorted(ablage.iterdir()) if p.is_file() and p.suffix.lower() == ".csv"]
    ergebnis: dict[str, Any] = {"dateien": [], "meldungen": [], "neu": 0, "doppelt": 0}
    with _lock:
        alle = laden()
        bekannt = {u["schluessel"] for u in alle}
        for pfad, herkunft in kandidaten:
            name = pfad.name
            if pfad.suffix.lower() != ".csv":
                ergebnis["meldungen"].append(f"{name}: Nur CSV-Dateien, Sir (keine .xlsx). Bitte den CSV-Export nehmen.")
                continue
            try:
                if pfad.stat().st_size > MAX_DATEI_BYTES:
                    raise FinanzFehler("Datei größer als 10 MB - das ist kein Kontoauszug, Sir.")
                bank, umsaetze, kaputt = lesen(pfad.read_bytes())
            except FinanzFehler as exc:
                if herkunft == "eingang":   # in der Ablage liegen auch andere CSVs (z.B. Kurse) - die bleiben still liegen
                    ergebnis["meldungen"].append(f"{name}: {exc}")
                continue
            except OSError as exc:
                ergebnis["meldungen"].append(f"{name}: nicht lesbar ({type(exc).__name__}).")
                continue
            neu = [u for u in umsaetze if u["schluessel"] not in bekannt]
            jetzt = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
            for u in neu:
                u["datei"] = name
                u["eingelesen"] = jetzt
                bekannt.add(u["schluessel"])
            # offene Revolut-Buchung, die inzwischen abgeschlossen ist: Kennzeichen nachziehen
            fertig = {u["schluessel"] for u in umsaetze if not u.get("offen")}
            for u in alle:
                if u.get("offen") and u["schluessel"] in fertig:
                    u["offen"] = False
            alle.extend(neu)
            ziel = o / "eingelesen" / f"{_dt.datetime.now().strftime('%Y-%m-%d_%H%M%S')} {name}"
            shutil.move(str(pfad), str(ziel))
            eintrag = {"datei": name, "bank": FORMATE[bank]["name"], "neu": len(neu),
                       "doppelt": len(umsaetze) - len(neu), "kaputt": kaputt, "herkunft": herkunft}
            ergebnis["dateien"].append(eintrag)
            ergebnis["neu"] += eintrag["neu"]
            ergebnis["doppelt"] += eintrag["doppelt"]
            if kaputt:
                ergebnis["meldungen"].append(f"{name}: {kaputt} Zeile(n) ohne gültiges Datum oder Betrag übersprungen.")
        if ergebnis["dateien"]:
            _speichern(alle)
    ergebnis["text"] = _einlesen_text(ergebnis)
    return ergebnis


def _einlesen_text(e: dict) -> str:
    if not e["dateien"] and not e["meldungen"]:
        return ("Keine neuen Kontoauszüge gefunden, Sir. Bitte die CSV-Exporte in die Ablage oder in "
                "data/finanzen/eingang legen.")
    teile = [f"{d['bank']} ({d['datei']}): {d['neu']} neu, {d['doppelt']} schon bekannt" for d in e["dateien"]]
    kopf = f"Eingelesen, Sir: {e['neu']} neue Umsätze." if e["dateien"] else "Nichts eingelesen, Sir."
    return "\n".join([kopf, *[f"- {t}" for t in teile], *[f"- {m}" for m in e["meldungen"]]])


def speichern_eingang(name: str, inhalt: bytes) -> str:
    """Upload aus dem Bereich "Finanzen" in eingang/ legen (nur .csv, nichts überschreiben)."""
    from . import ablage  # noqa: PLC0415 - gleiche Namensregeln wie die Ablage

    try:
        name = ablage.sicherer_name(name)
    except ablage.AblageFehler as exc:
        raise FinanzFehler(str(exc)) from exc
    if Path(name).suffix.lower() != ".csv":
        raise FinanzFehler("Nur CSV-Dateien, Sir (keine .xlsx).")
    if not inhalt:
        raise FinanzFehler("Die Datei ist leer, Sir.")
    if len(inhalt) > MAX_DATEI_BYTES:
        raise FinanzFehler("Datei größer als 10 MB - das ist kein Kontoauszug, Sir.")
    ziel = ordner() / "eingang" / name
    n = 2
    while ziel.exists():
        ziel = ziel.with_name(f"{Path(name).stem} ({n}){Path(name).suffix}")
        n += 1
    ziel.write_bytes(inhalt)
    return ziel.name


# ------------------------------------------------------------------ Auswertung

def _heute() -> _dt.date:
    try:
        from . import alltag  # noqa: PLC0415

        return alltag.jetzt().date()
    except Exception:  # noqa: BLE001
        return _dt.date.today()


def _gruppe(u: dict) -> str:
    """Wer kassiert? Bei Lastschriften Gläubiger-ID + Mandatsreferenz (P03: sicherstes Merkmal), sonst der Name ohne
    Zahlen und Satzzeichen (z.B. 'NETFLIX.COM 4711' und 'Netflix.com 4712' sind derselbe Empfänger)."""
    if u.get("glaeubiger_id"):
        return f"gl:{u['glaeubiger_id']}|{u.get('mandatsreferenz', '')}"
    name = re.sub(r"[^a-zäöüß ]+", " ", (u.get("empfaenger") or "").casefold())
    return "name:" + re.sub(r"\s+", " ", name).strip()


def _ausgabe(u: dict) -> bool:
    return u["betrag"] < 0 and not u.get("intern") and (u.get("waehrung") or "EUR") == "EUR"


def abos(umsaetze: list[dict] | None = None, heute: _dt.date | None = None) -> list[dict]:
    """Regelmäßige Abbuchungen. Monatlich/vierteljährlich/halbjährlich: mindestens 3 Zahlungen,
    jährlich: 2 Zahlungen genügen (dann 'vermutlich', P03: jährliche Abos extra prüfen)."""
    heute = heute or _heute()
    gruppen: dict[str, list[dict]] = {}
    for u in umsaetze if umsaetze is not None else laden():
        if _ausgabe(u) and _gruppe(u) not in ("name:", "gl:|"):
            gruppen.setdefault(_gruppe(u), []).append(u)
    ergebnis = []
    for key, liste in gruppen.items():
        liste.sort(key=lambda u: u["datum"])
        tage = [_dt.date.fromisoformat(u["datum"]) for u in liste]
        abstaende = [(b - a).days for a, b in zip(tage, tage[1:]) if (b - a).days > 0]
        if not abstaende:
            continue
        mitte = statistics.median(abstaende)
        rhythmus = next((r for r in RHYTHMEN if r[2] <= mitte <= r[3]), None)
        if not rhythmus:
            continue
        name_r, monate, lo, hi = rhythmus
        if len(liste) < (2 if monate == 12 else 3):
            continue
        passend = sum(1 for a in abstaende if lo - 3 <= a <= hi + 3)
        if passend < math.ceil(len(abstaende) * 2 / 3):
            continue
        betraege = [abs(u["betrag"]) for u in liste]
        typisch = statistics.median(betraege)
        aehnlich = sum(1 for b in betraege if abs(b - typisch) <= max(1.0, typisch * 0.10))
        if aehnlich < max(2, math.ceil(len(betraege) * 2 / 3)):
            continue
        letzte = liste[-1]
        betrag = abs(letzte["betrag"])
        naechste = tage[-1] + _dt.timedelta(days=round(mitte))
        ergebnis.append({
            "id": hashlib.sha1(key.encode("utf-8")).hexdigest()[:12],
            "name": letzte["empfaenger"] or letzte.get("glaeubiger_id") or "unbekannt",
            "rhythmus": name_r, "betrag": round(betrag, 2),
            "pro_monat": round(betrag / monate, 2), "pro_jahr": round(betrag * 12 / monate, 2),
            "anzahl": len(liste), "erste": liste[0]["datum"], "letzte": letzte["datum"],
            "naechste": naechste.isoformat(), "konto": letzte.get("konto", ""), "bank": letzte.get("bank", ""),
            "glaeubiger_id": letzte.get("glaeubiger_id", ""), "mandatsreferenz": letzte.get("mandatsreferenz", ""),
            # länger als ein halber Abstand überfällig: vermutlich schon gekündigt
            "aktiv": heute <= naechste + _dt.timedelta(days=max(10, round(mitte / 2))),
            # P03: jährliche Abos extra prüfen - mit nur 2 Zahlungen immer "vermutlich", auch bei Lastschrift
            "sicher": "vermutlich" if monate == 12 and len(liste) < 3 else (
                "Lastschrift (Gläubiger-ID)" if key.startswith("gl:") else "nach Name"),
        })
    ergebnis.sort(key=lambda a: (not a["aktiv"], -a["pro_monat"]))
    return ergebnis


def monate(umsaetze: list[dict] | None = None, anzahl: int = 12, heute: _dt.date | None = None) -> list[dict]:
    """Ausgaben und Einnahmen je Monat (EUR, ohne Umbuchungen zwischen eigenen Konten), neuester zuerst."""
    heute = heute or _heute()
    summen: dict[str, dict] = {}
    for u in umsaetze if umsaetze is not None else laden():
        if u.get("intern") or (u.get("waehrung") or "EUR") != "EUR":
            continue
        m = summen.setdefault(u["datum"][:7], {"monat": u["datum"][:7], "ausgaben": 0.0, "einnahmen": 0.0, "anzahl": 0})
        m["ausgaben" if u["betrag"] < 0 else "einnahmen"] += abs(u["betrag"])
        m["anzahl"] += 1
    liste = []
    j, mo = heute.year, heute.month
    for _ in range(anzahl):
        key = f"{j:04d}-{mo:02d}"
        m = summen.get(key, {"monat": key, "ausgaben": 0.0, "einnahmen": 0.0, "anzahl": 0})
        liste.append({**m, "ausgaben": round(m["ausgaben"], 2), "einnahmen": round(m["einnahmen"], 2)})
        j, mo = (j - 1, 12) if mo == 1 else (j, mo - 1)
    return liste


def uebersicht() -> dict:
    alle = laden()
    a = abos(alle)
    aktiv = [x for x in a if x["aktiv"]]
    o = ordner()
    return {
        "monate": monate(alle), "abos": a,
        "abos_pro_monat": round(sum(x["pro_monat"] for x in aktiv), 2),
        "abos_pro_jahr": round(sum(x["pro_jahr"] for x in aktiv), 2),
        "anzahl_umsaetze": len(alle),
        "von": alle[0]["datum"] if alle else None, "bis": alle[-1]["datum"] if alle else None,
        "letzte_einlesung": max((u.get("eingelesen", "") for u in alle), default="") or None,
        "eingang_wartet": sum(1 for p in (o / "eingang").iterdir() if p.is_file()),
        "verlauf": [{k: u.get(k) for k in ("datum", "empfaenger", "betrag", "waehrung", "konto", "art", "intern", "offen")}
                    for u in alle[-40:]][::-1],
    }


def umsaetze_monat(monat: str | None = None, grenze: int = 300) -> list[dict]:
    if monat and not re.fullmatch(r"\d{4}-\d{2}", monat):
        raise FinanzFehler("Monat bitte als JJJJ-MM, Sir.")
    alle = [u for u in laden() if not monat or u["datum"].startswith(monat)]
    return [{k: u.get(k) for k in ("datum", "empfaenger", "zweck", "betrag", "waehrung", "konto", "art", "intern", "offen")}
            for u in alle[-grenze:]][::-1]


# ------------------------------------------------------------------ Kündigungshilfe

def kuendigung(abo_id: str) -> dict:
    """Weg erklären und Kündigungstext entwerfen (Vorlage, 0 €). Auron verschickt nichts."""
    abo = next((a for a in abos() if a["id"] == abo_id), None)
    if not abo:
        raise FinanzFehler("Dieses Abo kenne ich nicht (mehr), Sir.")
    ref = f" (Mandatsreferenz {abo['mandatsreferenz']})" if abo.get("mandatsreferenz") else ""
    wege = [
        "Auf der Website oder in der App des Anbieters nach „Verträge hier kündigen“ suchen. Seit 01.07.2022 muss es "
        "diesen Kündigungsbutton bei online abschließbaren Verträgen geben, die Kündigung muss ohne Login möglich sein.",
        "Gibt es keinen Button: die Kündigung unten per E-Mail oder Brief schicken, mit Kundennummer, falls vorhanden.",
        "Kündigungsfrist im Vertrag prüfen. Verträge ab 01.03.2022 sind nach der Mindestlaufzeit meist monatlich "
        "kündbar - im Einzelfall nachsehen.",
        "Bestätigung verlangen und speichern (Bildschirmfoto oder Mail) - das ist Ihr Nachweis.",
        "Lastschrift erst nach dem Vertragsende stoppen. Eine zurückgegebene Lastschrift ist keine Kündigung.",
    ]
    text = (f"Betreff: Kündigung meines Vertrags{ref}\n\n"
            "Sehr geehrte Damen und Herren,\n\n"
            f"hiermit kündige ich meinen Vertrag{ref} fristgerecht zum nächstmöglichen Zeitpunkt.\n"
            "Bitte bestätigen Sie mir die Kündigung und das Vertragsende schriftlich.\n"
            "Das SEPA-Lastschriftmandat widerrufe ich zum Vertragsende.\n\n"
            "Mit freundlichen Grüßen\n[Ihr Name]\n[Anschrift, Kundennummer]")
    return {"abo": abo, "wege": wege, "text": text,
            "hinweis": f"Für {abo['name']}. Sir verschickt selbst - Auron sendet nichts und bewegt kein Geld."}


# ------------------------------------------------------------------ Texte für Chat und Briefing

def _euro(x: float) -> str:
    return f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def abo_text(liste: list[dict] | None = None, max_zeilen: int = 15) -> str:
    liste = [a for a in (abos() if liste is None else liste) if a["aktiv"]]
    if not liste:
        if not laden():
            return "Noch keine Umsätze eingelesen, Sir. Bitte die CSV-Exporte in die Ablage legen."
        return "Keine regelmäßigen Abbuchungen erkannt, Sir."
    monat = sum(a["pro_monat"] for a in liste)
    zeilen = [f"{len(liste)} Abos, zusammen {_euro(monat)} im Monat bzw. {_euro(monat * 12)} im Jahr, Sir:"]
    for a in liste[:max_zeilen]:
        zeilen.append(f"- {a['name']}: {_euro(a['betrag'])} {a['rhythmus']} ({_euro(a['pro_jahr'])} im Jahr)"
                      + (" - vermutlich" if a["sicher"] == "vermutlich" else ""))
    if len(liste) > max_zeilen:
        zeilen.append(f"- … und {len(liste) - max_zeilen} weitere im Bereich Finanzen.")
    return "\n".join(zeilen)


def chat_text(aktion: str) -> str:
    if aktion == "einlesen":
        return einlesen()["text"]
    if aktion == "monat":
        m = monate(anzahl=2)
        return (f"Ausgaben diesen Monat bisher {_euro(m[0]['ausgaben'])}, letzten Monat {_euro(m[1]['ausgaben'])}, Sir "
                "(ohne Umbuchungen zwischen Ihren Konten).") if laden() else abo_text([])
    return abo_text()


def _briefing_datei() -> Path:
    return ordner() / "briefing.json"


def fuer_briefing(heute: _dt.date | None = None) -> str:
    """Einmal im Monat (erstes Briefing des Monats): Abo-Übersicht und Erinnerung. Sonst leer. 0 €."""
    heute = heute or _heute()
    monat = heute.strftime("%Y-%m")
    try:
        zuletzt = json.loads(_briefing_datei().read_text(encoding="utf-8")).get("monat")
    except (OSError, json.JSONDecodeError, AttributeError):
        zuletzt = None
    if zuletzt == monat:
        return ""
    with _lock:
        _briefing_datei().write_text(json.dumps({"monat": monat}), encoding="utf-8")
    return f"**Finanzen (einmal im Monat)**\n{abo_text()}\n\nErinnerung: {ERINNERUNG}, Sir."

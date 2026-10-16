"""
Wahl der Stimme (P05, 16.10.2026): Fish Audio, Piper oder Browser.

Einstellung "stimme_quelle" (Umgebung STIMME_QUELLE): "fish", "piper", "browser"
oder leer = automatisch. Automatisch heißt: bis 30.11.2026 Fish Audio (kostenlos
bis dahin), ab 01.12.2026 Piper - ohne dass Sir etwas umstellen muss.

Rückfall: gewählte Stimme -> Piper -> Browser. Wählt Sir ausdrücklich "browser",
verlässt kein Text den Rechner und es gibt keinen Rückfall auf Fish oder Piper.
Wählt Sir "piper", geht es bei einem Fehler nur noch auf den Browser.

Der Browser spricht selbst (Windows-Stimme im Browser). Der Server kann das nicht;
er meldet dann "Browser" (HTTP 503), und die Oberfläche nimmt ihre eigene Stimme.
"""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass, field

from . import piper_tts, sprache

UMSCHALTDATUM = datetime.date(2026, 12, 1)  # Fish Audio ist bis 30.11.2026 kostenlos
QUELLEN = ("fish", "piper", "browser")
NAMEN = {"fish": "Fish Audio", "piper": "Piper", "browser": "Browser-Stimme"}
MEDIENTYP = {"fish": "audio/mpeg", "piper": "audio/wav"}


class StimmeBrowser(RuntimeError):
    """Kein Server-Ton möglich (oder Browser gewählt) - die Oberfläche spricht selbst."""

    def __init__(self, grund: str, rueckfaelle: list[str] | None = None):
        super().__init__(grund)
        self.rueckfaelle = rueckfaelle or []


@dataclass
class Ergebnis:
    daten: bytes
    medientyp: str
    quelle: str
    rueckfaelle: list[str] = field(default_factory=list)  # z.B. ["fish: Fish Audio bremst gerade (429)."]


def eingestellt() -> str:
    """Was Sir eingestellt hat; leer = nichts (automatisch)."""
    wert = (os.getenv("STIMME_QUELLE") or "").strip().lower()
    return wert if wert in QUELLEN else ""


def gewaehlt(heute: datetime.date | None = None) -> str:
    wert = eingestellt()
    if wert:
        return wert
    return "piper" if (heute or datetime.date.today()) >= UMSCHALTDATUM else "fish"


def kette(heute: datetime.date | None = None, bevorzugt: str | None = None) -> list[str]:
    erste = bevorzugt if bevorzugt in QUELLEN else gewaehlt(heute)
    if erste == "browser":
        return ["browser"]
    if erste == "piper":
        return ["piper", "browser"]
    return [erste, "piper", "browser"]


def _bereit(quelle: str) -> bool:
    if quelle == "fish":
        return sprache.verfuegbar()
    if quelle == "piper":
        return piper_tts.verfuegbar()
    return True


def sprich(text: str, tempo: float = 1.0, bevorzugt: str | None = None, heute: datetime.date | None = None) -> Ergebnis:
    """Erste Stimme der Kette, die einen Ton liefert. Sonst StimmeBrowser."""
    rueckfaelle: list[str] = []
    for quelle in kette(heute, bevorzugt):
        if quelle == "browser":
            raise StimmeBrowser("Die Browser-Stimme spricht." if not rueckfaelle
                                else "Keine Server-Stimme möglich: " + " | ".join(rueckfaelle), rueckfaelle)
        if not _bereit(quelle):
            rueckfaelle.append(f"{NAMEN[quelle]}: nicht eingerichtet")
            continue
        try:
            if quelle == "fish":
                daten = sprache.sprich(text, tempo=tempo)
            else:
                daten = piper_tts.sprechen(sprache.aufbereiten(text), tempo=tempo)
        except (sprache.SpracheFehler, piper_tts.PiperFehler) as exc:
            rueckfaelle.append(f"{NAMEN[quelle]}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - Zeitüberschreitung u. ä.: nächste Stimme
            rueckfaelle.append(f"{NAMEN[quelle]}: {exc}")
            continue
        return Ergebnis(daten, MEDIENTYP[quelle], quelle, rueckfaelle)
    raise StimmeBrowser("Keine Stimme verfügbar.", rueckfaelle)  # nicht erreichbar, die Kette endet immer mit "browser"


def stand(heute: datetime.date | None = None) -> dict:
    """Für die Oberfläche: was gilt, welche Server-Stimme gerade spricht, was fehlt."""
    heute = heute or datetime.date.today()
    gewaehlte = gewaehlt(heute)
    ketten = kette(heute)
    aktuell = next((q for q in ketten if q != "browser" and _bereit(q)), "browser")
    return {
        "eingestellt": eingestellt(),
        "automatisch": not eingestellt(),
        "gewaehlt": gewaehlte,
        "kette": ketten,
        "quelle": aktuell,
        "name": NAMEN[aktuell],
        "umschaltdatum": UMSCHALTDATUM.isoformat(),
        "fish": {"verfuegbar": sprache.verfuegbar()},
        "piper": piper_tts.stand(),
    }

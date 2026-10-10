"""
Ampel für Jarvis' Hintergrund-Arbeiten (23.09.2026).

Idee aus Sir's TikTok-Sammlung ("Bot-Ampel", liambuilds.ai): jede Arbeit hat
eine Farbe, damit man auf einen Blick sieht, ob etwas läuft, etwas auf Sir
wartet oder etwas kaputt ist.

    gruen - läuft gerade
    gelb  - wartet auf Sir (Vorschläge freigeben, Links abrufen, Kosten knapp)
    rot   - letzter Lauf mit Fehler / Kostenrahmen überschritten
    grau  - ruht, alles in Ordnung

Liest nur vorhandene Zustände (reindex, Aufgaben-Loop, Studium, Prüfstand,
Marktdaten, Vorschläge, TikTok, Kosten) - keine Claude-Aufrufe, 0 Kosten.
Fällt ein Teil aus, zeigt er "grau / unbekannt" statt die ganze Ampel
abzubrechen.
"""

from __future__ import annotations

from typing import Any, Callable

FARBEN = ("rot", "gelb", "gruen", "grau")


def _eintrag(name: str, farbe: str, text: str, seite: str | None = None) -> dict:
    return {"name": name, "farbe": farbe, "text": text, "seite": seite}


def _lauf(name: str, st: dict, laeuft: str, seite: str | None = None) -> dict:
    """Gemeinsame Regel für Hintergrund-Läufe mit running/error/finished_at."""
    if st.get("running"):
        return _eintrag(name, "gruen", laeuft, seite)
    if st.get("error"):
        return _eintrag(name, "rot", f"Letzter Lauf mit Fehler: {str(st['error'])[:120]}", seite)
    ende = (st.get("finished_at") or "").replace("T", " ")[:16]
    return _eintrag(name, "grau", f"ruht (zuletzt {ende})" if ende else "ruht", seite)


def _reindex() -> dict:
    from . import reindex_service
    st = reindex_service.status()
    st = st.model_dump() if hasattr(st, "model_dump") else dict(st)
    return _lauf("Vault einlesen", st, "liest den Vault ein", "vault")


def _aufgaben_loop() -> dict:
    from . import aufgaben_loop
    return _lauf("Aufgaben-Loop", aufgaben_loop.status(), "arbeitet Wissenslücken ab", "jarvis")


def _studium() -> dict:
    from . import studium
    st = studium.status()
    thema = ((st.get("last_result") or {}).get("thema") or "").strip()
    return _lauf("Studium", st, "studiert" + (f" ({thema})" if thema else ""), "jarvis")


def _pruefstand() -> dict:
    from . import pruefstand
    return _lauf("Prüfstand", pruefstand.status(), "vergleicht Modelle", "labor")


def _marktdaten() -> dict:
    from . import marktdaten
    st = marktdaten.alle_laden_status()
    if st.get("running"):
        f = st.get("fortschritt") or {}
        return _eintrag("Marktdaten", "gruen", f"lädt {f.get('schritt', '?')} von {f.get('von', '?')}", "markt")
    if st.get("error"):
        return _eintrag("Marktdaten", "rot", f"Laden abgebrochen: {str(st['error'])[:120]}", "markt")
    fehler = [e for e in st.get("ergebnisse") or [] if isinstance(e, dict) and e.get("fehler")]
    if fehler:
        return _eintrag("Marktdaten", "gelb", f"{len(fehler)} Märkte ohne Daten beim letzten Laden", "markt")
    return _eintrag("Marktdaten", "grau", "ruht", "markt")


def _vorschlaege() -> dict:
    from . import vorschlaege
    n = len(vorschlaege.liste("offen"))
    if n:
        return _eintrag("Vorschläge", "gelb", f"{n} warten auf Ihre Freigabe", "jarvis")
    return _eintrag("Vorschläge", "grau", "nichts offen", "jarvis")


def _tiktok() -> dict:
    from . import tiktok
    liste = tiktok.liste()
    if any(e.get("status") == "laeuft" for e in liste):
        return _eintrag("TikTok", "gruen", "ruft ein Video ab", "tiktok")
    # verklebte Reste (repariert, ohne eigenen Link) zählen nicht - sie sind durch ihre Teile ersetzt
    offen = sum(1 for e in liste if e.get("status") in ("neu", "fehler")
                and not (e.get("repariert") and e.get("status") == "fehler"))
    geholt = sum(1 for e in liste if e.get("status") == "geholt")
    if offen or geholt:
        teile = [f"{offen} noch abzurufen"] if offen else []
        teile += [f"{geholt} noch nicht im Vault"] if geholt else []
        return _eintrag("TikTok", "gelb", ", ".join(teile), "tiktok")
    return _eintrag("TikTok", "grau", f"{len(liste)} Links, alle im Vault", "tiktok")


def _kosten() -> dict:
    from . import kosten
    u = kosten.uebersicht()
    text = f"{u['ausgegeben_usd']:.2f} $ von {u['rahmen_usd']:.0f} $ im Monat, Prognose {u['prognose_monatsende_usd']:.2f} $"
    farbe = {"rot": "rot", "gelb": "gelb"}.get(u.get("ampel"), "grau")
    return _eintrag("Kosten", farbe, text.replace(".", ","), "settings")


def _nachtarbeit() -> dict:
    from . import nachtarbeit
    st = nachtarbeit.status()
    letzter = st.get("last_result") or {}
    if letzter.get("uebersprungen"):
        return _eintrag("Nachtarbeit", "grau", f"letzte Nacht übersprungen: {letzter.get('grund', '')}", "jarvis")
    return _lauf("Nachtarbeit", st, "prüft Studium-Entwürfe", "jarvis")


TEILE: list[tuple[str, Callable[[], dict]]] = [
    ("Vault einlesen", _reindex),
    ("Aufgaben-Loop", _aufgaben_loop),
    ("Studium", _studium),
    ("Nachtarbeit", _nachtarbeit),
    ("Prüfstand", _pruefstand),
    ("Marktdaten", _marktdaten),
    ("Vorschläge", _vorschlaege),
    ("TikTok", _tiktok),
    ("Kosten", _kosten),
]


def uebersicht() -> dict[str, Any]:
    jobs = []
    for name, teil in TEILE:
        try:
            jobs.append(teil())
        except Exception as exc:  # noqa: BLE001 - ein kaputter Teil darf die Ampel nicht abschalten
            jobs.append(_eintrag(name, "grau", f"unbekannt ({type(exc).__name__})"))
    gesamt = next((f for f in FARBEN if any(j["farbe"] == f for j in jobs)), "grau")
    return {"gesamt": gesamt, "jobs": jobs}

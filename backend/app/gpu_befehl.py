"""
Chat-Befehle für die GPU-Miete (P24b, 16.10.2026, Claude Code). Ohne KI, 0 Cent.

  "GPU Status" / "Wie steht die GPU-Miete"     -> Stand, Deckel, laufender Pod, Alarm
  "GPU aufräumen" / "Pods aufräumen"            -> Wächter sofort: nicht erlaubte Pods im RunPod-Konto löschen
  "Code-Auftrag 7 auf die GPU"                  -> fragt nach ("ja", gilt 2 Minuten), mietet erst NACH dem Ja

Nur für Aufträge der Art "entwicklung". Das Mieten kostet Geld und läuft deshalb nie ohne ausdrückliches "ja".
Die Bestätigung gilt wie bei den PC-Befehlen (app/hauptpc.py) nur kurz und nur für diesen einen Auftrag.
"""

from __future__ import annotations

import re
import time
from typing import Any

BESTAETIGUNG_S = 120

_V = r"^\s*(?:(?:jarvis|auron)[,\s]+)?(?:bitte\s+)?"
_GPU = r"(?:gpu|g-?p-?u|gpu-?miete|gemieteten?\s+gpu)"

_STATUS = re.compile(
    _V + r"(?:(?:zeig\w*|nenn\w*|sag\w*|gib)\s+(?:mir\s+)?(?:den\s+|die\s+|das\s+)?)?(?:"
    + _GPU + r"[\s-]*(?:status|stand|kosten|deckel|verbrauch)|"
    r"wie\s+(?:steht|stehen)\s+(?:es\s+um\s+)?(?:die\s+|der\s+|den\s+)?" + _GPU + r"(?:\s+aus)?|"
    r"l[aä]uft\s+(?:gerade\s+)?(?:ein|noch\s+ein)\s+(?:gemieteter\s+)?(?:pod|" + _GPU + r")|"
    r"l[aä]uft\s+(?:gerade\s+)?(?:eine|noch\s+eine)\s+(?:gemietete\s+)?" + _GPU + r")\s*[?.!]*\s*$", re.I)

_AUFRAEUMEN = re.compile(
    _V + r"(?:" + _GPU + r"[\s-]*(?:aufr[aä]umen|aufger[aä]umt)|"
    r"(?:r[aä]um(?:e)?\s+)?(?:die\s+|alle\s+)?(?:gemieteten\s+)?pods?\s+auf|"
    r"l[oö]sch(?:e)?\s+(?:alle\s+|die\s+)?(?:gemieteten\s+)?pods?|"
    r"r[aä]um(?:e)?\s+(?:die\s+)?" + _GPU + r"\s+auf)\s*[?.!]*\s*$", re.I)

_AUFTRAG = re.compile(
    _V + r"(?:(?:starte|start|schick\w*|schieb\w*|lass|gib|mach\w*|führ\w*|fuehr\w*)\s+)?(?:den\s+|das\s+)?"
    r"(?:(?:code|entwicklungs)-?\s*)?(?:nacht)?auftrag\s+(?:nr\.?\s*|nummer\s+)?(?P<nr>\d{1,5})\s+"
    r"(?:(?:jetzt|sofort)\s+)?(?:(?:auf|mit|über|ueber)\s+(?:der|die|einer|eine)\s+)?" + _GPU
    + r"(?:\s+(?:laufen|rechnen|erledigen|machen|ausführen|ausfuehren))?(?:\s+(?:lassen|jetzt|sofort))*\s*[?.!]*\s*$", re.I)
_AUFTRAG2 = re.compile(
    _V + _GPU + r"[\s-]*(?:code-?)?auftrag\s+(?:nr\.?\s*|nummer\s+)?(?P<nr>\d{1,5})\s*[?.!]*\s*$", re.I)

_JA = re.compile(r"^\s*(?:ja|jawohl|mach(?:\s*das)?|ok(?:ay)?|bestätigt|bestaetigt|genau)\b[\s.!]*$", re.I)
_NEIN = re.compile(r"^\s*(?:nein|nee|abbrechen|lass(?:\s*es)?|doch\s*nicht|stopp)\b[\s.!]*$", re.I)

_wartend: dict[str, Any] = {}


def absicht(text: str) -> dict | None:
    """Erkennt GPU-Befehle. None = kein GPU-Befehl."""
    t = (text or "").strip()
    if not t or len(t) > 140:
        return None
    if _STATUS.match(t):
        return {"art": "gpu", "aktion": "status"}
    if _AUFRAEUMEN.match(t):
        return {"art": "gpu", "aktion": "aufraeumen"}
    m = _AUFTRAG.match(t) or _AUFTRAG2.match(t)
    if m:
        return {"art": "gpu", "aktion": "auftrag", "nr": int(m.group("nr"))}
    return None


def status_text() -> str:
    from . import gpu_miete

    if not gpu_miete.schluessel_da():
        return "Die GPU-Miete ist aus, Sir: Es gibt keinen RUNPOD_API_KEY in der .env."
    t = gpu_miete.kosten_topf()
    zeilen = [gpu_miete.zeile(t)]
    if t["alarm"]:
        zeilen.append(f"ACHTUNG, Sir: {t['alarm'].get('text')} Bitte in der RunPod-Konsole nachsehen.")
    if t["laufend"]:
        zeilen.append("Ein gemieteter Pod läuft laut Protokoll: " + ", ".join(p["name"] for p in t["laufend"]) + ".")
    else:
        zeilen.append("Es läuft gerade kein gemieteter Pod.")
    f = gpu_miete.status()["fenster"]
    zeilen.append(f"Nachtfenster {f['von']} bis {f['bis']}, jetzt {'erlaubt' if f['jetzt_erlaubt'] else 'nicht erlaubt'}.")
    return "\n\n".join(zeilen)


def _aufraeumen_text() -> str:
    from . import gpu_miete

    if not gpu_miete.schluessel_da():
        return "Die GPU-Miete ist aus, Sir: Es gibt keinen RUNPOD_API_KEY in der .env."
    e = gpu_miete.waechter_lauf()
    if not e["ok"]:
        return "Das Aufräumen hat Probleme gemeldet, Sir: " + "; ".join(e["fehler"]) + ". Bitte in der RunPod-Konsole nachsehen."
    if not e["geloescht"]:
        return f"Aufgeräumt, Sir. {e['geprueft']} Pod(s) im Konto geprüft, nichts musste gelöscht werden."
    namen = ", ".join(str(g["name"] or g["id"]) for g in e["geloescht"])
    return f"Aufgeräumt, Sir. Gelöscht: {namen}."


def ausfuehren(a: dict) -> str:
    """Chat-Antwort für eine erkannte GPU-Absicht."""
    from . import gpu_miete, nachtauftraege

    if a["aktion"] == "status":
        return status_text()
    if a["aktion"] == "aufraeumen":
        return _aufraeumen_text()
    try:
        auftrag = nachtauftraege.gpu_ausdruecklich_pruefen(a["nr"])
        if not gpu_miete.ist_aktiv():
            raise nachtauftraege.NachtauftragFehler("Die GPU-Miete ist aus (RUNPOD_API_KEY fehlt).")
        gpu_miete.pruefen_start(ausdruecklich=True)
    except nachtauftraege.NachtauftragFehler as exc:
        return f"Das geht nicht, Sir: {exc}"
    except gpu_miete.GpuMieteGesperrt as exc:
        return f"Das geht nicht, Sir: {exc}"
    preis = gpu_miete.preis_fallback_usd_h() * gpu_miete.eur_pro_usd()
    _wartend.clear()
    _wartend.update({"nr": auftrag["id"], "zeit": time.time()})
    return (f"Soll ich für Auftrag Nr. {auftrag['id']} \"{auftrag.get('titel')}\" jetzt eine GPU bei RunPod mieten, Sir? "
            f"Das kostet Geld, grob {preis:.2f} EUR pro Stunde (höchstens {gpu_miete.max_dauer_s() / 3600:.0f} Stunden), "
            f"der Pod wird danach gelöscht. Sagen Sie \"ja\" (gilt 2 Minuten).")


def bestaetigung(text: str) -> str | None:
    """Antwort auf die offene Rückfrage. None = keine offene Rückfrage (oder abgelaufen)."""
    if not _wartend:
        return None
    if time.time() - _wartend.get("zeit", 0) > BESTAETIGUNG_S:
        _wartend.clear()
        return None
    if _JA.match(text or ""):
        nr = _wartend.pop("nr")
        _wartend.clear()
        from . import nachtauftraege

        try:
            nachtauftraege.gpu_ausdruecklich_starten(nr)
        except nachtauftraege.NachtauftragFehler as exc:
            return f"Das ging nicht, Sir: {exc}"
        return (f"Verstanden, Sir. Auftrag Nr. {nr} läuft jetzt auf einer gemieteten GPU. Das dauert einige Minuten. "
                "Das Ergebnis steht danach im Nachtauftrag und im Vault, der Pod wird gelöscht. Fragen Sie jederzeit: \"GPU Status\".")
    if _NEIN.match(text or ""):
        _wartend.clear()
        return "In Ordnung, Sir. Es wird nichts gemietet."
    return None

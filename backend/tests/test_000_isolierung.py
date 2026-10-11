"""
Schutz der echten Daten beim Testen (23.09.2026).

Befund: Die Tests haben bisher in die ECHTEN Dateien unter data/ geschrieben
(z.B. 80 von 229 Einträgen in data/usage_log.jsonl waren Testeinträge mit
0,0 s Dauer). Diese Datei heißt bewusst test_000_..., damit unittest sie beim
"discover" zuerst importiert: Sie lenkt alle Datenpfade auf einen leeren
Temp-Ordner um, BEVOR ein Test läuft. Tests, die eigene Pfade setzen
(mock.patch.dict), bleiben davon unberührt.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="jarvis_tests_"))
atexit.register(shutil.rmtree, _TMP, ignore_errors=True)

UMLEITUNGEN = {
    "USAGE_LOG_PATH": _TMP / "usage_log.jsonl",
    "WISSENSLUECKEN_PATH": _TMP / "wissensluecken.jsonl",
    "AUFGABEN_LOOP_ERLEDIGT_PATH": _TMP / "aufgaben_loop_erledigt.jsonl",
    "STUDIUM_ERLEDIGT_PATH": _TMP / "studium_erledigt.jsonl",
    "PRUEFSTAND_PATH": _TMP / "pruefstand",
    "TIKTOK_PATH": _TMP / "tiktok",
    "TRADING_DATEN_PATH": _TMP / "trading",
    "ABLAGE_PATH": _TMP / "ablage",
    "EINSTELLUNGEN_PATH": _TMP / "einstellungen.json",
    "GESPRAECHE_PATH": _TMP / "gespraeche",
    "TESTFRAGEN_KANDIDATEN_PATH": _TMP / "testfragen_kandidaten.jsonl",
    "VORSCHLAEGE_PATH": _TMP / "vorschlaege.json",
    "PAPER_PATH": _TMP / "paper",
    "MARKT_DB_PATH": _TMP / "marktdaten.db",
    "DENKBLOCK_SICHERUNG_PATH": _TMP / "denkblock_sicherung",
    "GESAMTKARTE_ANTWORTEN_PATH": _TMP / "gesamtkarte_antworten.json",
    "GERAETE_PATH": _TMP / "geraete.json",
    "ZUGRIFFE_PATH": _TMP / "zugriffe.jsonl",
    "TAGEBUCH_PATH": _TMP / "tagebuch.json",
    "NACHTAUFTRAEGE_PATH": _TMP / "nachtauftraege.json",
    "TAGESFRAGEN_PATH": _TMP / "tagesfragen.json",
    "WERKSTATT_PATH": _TMP / "werkstatt",
    # 27.09.2026: Sicherungen von Mind Maps und Projekten
    "MINDMAP_SICHERUNG_PATH": _TMP / "mindmaps_sicherung",
    "PROJEKTE_SICHERUNG_PATH": _TMP / "projekte_sicherung",
    "KONTAKTE_PATH": _TMP / "kontakte.json",
    # 29.09.2026: Wissensimport (Stand, Quelltexte, Entwürfe)
    "WISSENSIMPORT_PATH": _TMP / "wissensimport",
    # 02.10.2026: Sprachmemos
    "SPRACHMEMOS_PATH": _TMP / "sprachmemos",
    # 03.10.2026: Ollama-Rechnerliste
    "KI_LOKAL_PATH": _TMP / "ki_lokal.json",
    # 10.10.2026: Suchindex, Nachtarbeit-Log, Sicherheitscheck und .env - Tests griffen sonst auf die
    # echten Dateien zu (Befund Cloud-Prüfstand: data/vector_db wurde beim Testlauf angelegt).
    "CHROMA_PATH": _TMP / "vector_db",
    "NACHTARBEIT_LOG_PATH": _TMP / "nachtarbeit_log.jsonl",
    "SICHERHEITSCHECK_PATH": _TMP / "sicherheitscheck_bericht.txt",
    "JARVIS_ENV_PATH": _TMP / ".env",
    "FEHLER_LOG_PATH": _TMP / "fehler_log.jsonl",
    # 11.10.2026: Finanzen (Umsätze, Eingang)
    "FINANZEN_PATH": _TMP / "finanzen",
}
for _name, _pfad in UMLEITUNGEN.items():
    os.environ[_name] = str(_pfad)

# 26.09.2026: in Tests keine 0-€-Nachtarbeiten (Vault einlesen, Pflegebericht) und
# keine Frage des Tages unter dem Briefing - beides würde echte Aufrufe auslösen.
os.environ["NACHTARBEIT_FREI"] = ""
os.environ["BRIEFING_TAGESFRAGE"] = "0"
os.environ["BRIEFING_FINANZEN"] = "0"   # 11.10.2026: Abo-Übersicht nur in den eigenen Tests (test_finanzen)


class Isolierung(unittest.TestCase):
    def test_datenpfade_zeigen_in_temp(self):
        for name in UMLEITUNGEN:
            self.assertTrue(os.environ[name].startswith(str(_TMP)), name)

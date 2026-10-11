"""PC-Agent am Haupt-PC (pc_agent_windows/jarvis_pc_agent.py) - 30.09.2026: Aktion "anzeige".

Läuft auch unter Linux: Windows-Teile werden ersetzt (keine echten Tasten, kein echtes TightVNC).
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

try:
    import testschutz  # noqa: F401  (Testmodus und Netz-Wächter)
except ImportError:
    from tests import testschutz  # noqa: F401

_PFAD = Path(__file__).resolve().parents[2] / "pc_agent_windows" / "jarvis_pc_agent.py"
if not _PFAD.exists():
    raise unittest.SkipTest("pc_agent_windows fehlt (nur auf Sirs PC, nicht im Repo)")
_spec = importlib.util.spec_from_file_location("jarvis_pc_agent", _PFAD)
agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agent)

TOKEN = "t" * 32


class Lauf:
    def __init__(self, code=0, aus="", fehler=""):
        self.returncode, self.stdout, self.stderr = code, aus, fehler


class Anzeige(unittest.TestCase):
    def setUp(self):
        for p in (mock.patch.object(agent, "_ist_windows", return_value=True),
                  mock.patch.object(agent, "_tvnserver", return_value=r"C:\TightVNC\tvnserver.exe")):
            p.start()
            self.addCleanup(p.stop)

    def test_ein_monitor(self):
        with mock.patch.object(agent.subprocess, "run", return_value=Lauf()) as lauf:
            r = agent.aktion_ausfuehren("anzeige", "2")
        self.assertTrue(r["ok"])
        self.assertEqual(lauf.call_args.args[0], [r"C:\TightVNC\tvnserver.exe", "-controlservice", "-sharedisplay", "2"])

    def test_beide_monitore(self):
        with mock.patch.object(agent.subprocess, "run", return_value=Lauf()) as lauf:
            r = agent.aktion_ausfuehren("anzeige", "Alle")
        self.assertTrue(r["ok"])
        self.assertEqual(lauf.call_args.args[0][1:], ["-controlservice", "-sharefull"])

    def test_nur_erlaubte_werte_kein_freier_befehl(self):
        with mock.patch.object(agent.subprocess, "run") as lauf:
            for boese in ("3", "1 & calc", "-sharefull", "", None):
                self.assertFalse(agent.aktion_ausfuehren("anzeige", boese)["ok"])
        lauf.assert_not_called()

    def test_tightvnc_lehnt_ab(self):
        with mock.patch.object(agent.subprocess, "run", return_value=Lauf(1, "", "Zugriff verweigert")):
            r = agent.aktion_ausfuehren("anzeige", "1")
        self.assertFalse(r["ok"])
        self.assertIn("Zugriff verweigert", r["meldung"])

    def test_ohne_tightvnc(self):
        with mock.patch.object(agent, "_tvnserver", return_value=None):
            r = agent.aktion_ausfuehren("anzeige", "1")
        self.assertFalse(r["ok"])
        self.assertIn("tvnserver.exe", r["meldung"])

    def test_haengt_nicht_ewig(self):
        with mock.patch.object(agent.subprocess, "run", side_effect=agent.subprocess.TimeoutExpired("x", 10)):
            self.assertFalse(agent.aktion_ausfuehren("anzeige", "1")["ok"])

    def test_steht_in_der_aktionsliste_und_neue_version(self):
        self.assertIn("anzeige", agent.FESTE_AKTIONEN)
        self.assertEqual(agent.VERSION, "1.1.0")


class UeberHttp(unittest.TestCase):
    """Echter kleiner Server: Token-Prüfung und Aktion 'anzeige' über das Netz."""

    def setUp(self):
        self.server = agent.server_bauen(TOKEN, 0, "127.0.0.1")
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        for p in (mock.patch.object(agent, "_ist_windows", return_value=True),
                  mock.patch.object(agent, "_tvnserver", return_value="tvn.exe"),
                  mock.patch.object(agent, "_protokoll")):
            p.start()
            self.addCleanup(p.stop)

    def _post(self, daten, token=TOKEN):
        req = urllib.request.Request(self.url + "/aktion", data=json.dumps(daten).encode(), method="POST",
                                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_anzeige_mit_token(self):
        with mock.patch.object(agent.subprocess, "run", return_value=Lauf()):
            code, d = self._post({"aktion": "anzeige", "ziel": "1"})
        self.assertEqual((code, d["ok"]), (200, True))

    def test_ohne_token_abgelehnt(self):
        with mock.patch.object(agent.subprocess, "run") as lauf:
            code, _ = self._post({"aktion": "anzeige", "ziel": "1"}, token="falsch" * 5)
        self.assertEqual(code, 401)
        lauf.assert_not_called()

    def test_ping_meldet_neue_version(self):
        with urllib.request.urlopen(self.url + "/ping", timeout=5) as r:
            self.assertEqual(json.loads(r.read())["agent_version"], "1.1.0")


class Befehle(unittest.TestCase):
    """11.10.2026 aus test_alltag_neu hierher verschoben - dort startet kein echter Agent mehr."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pcagent_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        p = mock.patch.object(agent, "HIER", self.tmp)
        p.start()
        self.addCleanup(p.stop)

    def test_agent_listen_nur_lokal(self):
        (self.tmp / "befehle.json").write_text(json.dumps({"x": {"titel": "X", "datei": "C:/a.exe"},
                                                           "y": {"titel": "Y", "datei": "C:/b.bat"}}), encoding="utf-8")
        self.assertEqual(list(agent.befehle()), ["y"])


if __name__ == "__main__":
    unittest.main()

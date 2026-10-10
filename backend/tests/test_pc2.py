"""Tests für PC 2: Agent (pc2_agent/jarvis_agent.py) und Anbindung (app/pc2.py).

Der Agent läuft hier echt als HTTP-Server in einem Thread - statt /proc und
/sys eines Linux-PCs liest er ein nachgebautes Verzeichnis (JARVIS_AGENT_ROOT).
So prüfen die Tests auch unter Windows den ganzen Weg Hub -> Agent.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

AGENT_ORDNER = Path(__file__).resolve().parents[2] / "pc2_agent"
sys.path.insert(0, str(AGENT_ORDNER))
import jarvis_agent  # noqa: E402

from app import pc2  # noqa: E402

TOKEN = "t" * 40


def fake_linux(root: Path, cpu_ticks: int = 1000, rx: int = 5000) -> None:
    """Minimales /proc, /sys und /etc wie auf einem Mini-PC mit 4 Kernen."""
    (root / "proc/sys/kernel").mkdir(parents=True, exist_ok=True)
    (root / "proc/net").mkdir(parents=True, exist_ok=True)
    (root / "etc").mkdir(exist_ok=True)
    zeilen = [f"cpu  {cpu_ticks} 0 {cpu_ticks} {cpu_ticks * 6} 0 0 0 0 0 0"]
    for k in range(4):
        zeilen.append(f"cpu{k} {cpu_ticks // 4 * (k + 1)} 0 100 {cpu_ticks} 0 0 0 0 0 0")
    zeilen.append("intr 1 2 3")
    (root / "proc/stat").write_text("\n".join(zeilen) + "\n")
    (root / "proc/meminfo").write_text(
        "MemTotal:       16000000 kB\nMemFree:         2000000 kB\nMemAvailable:    8000000 kB\n"
        "SwapTotal:       2000000 kB\nSwapFree:        1500000 kB\n"
    )
    (root / "proc/net/dev").write_text(
        "Inter-|   Receive\n face |bytes    packets\n"
        f"    lo: 999999 1 0 0 0 0 0 0 999999 1 0 0 0 0 0 0\n"
        f"enp0s25: {rx} 10 0 0 0 0 0 0 {rx // 2} 5 0 0 0 0 0 0\n"
    )
    (root / "proc/uptime").write_text("3725.50 10000.00\n")
    (root / "proc/loadavg").write_text("0.52 0.40 0.31 1/300 4242\n")
    (root / "proc/sys/kernel/osrelease").write_text("6.8.0-51-generic\n")
    (root / "proc/sys/kernel/hostname").write_text("mini-pc\n")
    (root / "etc/os-release").write_text('NAME="Linux Mint"\nPRETTY_NAME="Linux Mint 22.1"\n')
    (root / "proc/mounts").write_text("")
    hw = root / "sys/class/hwmon/hwmon0"
    hw.mkdir(parents=True, exist_ok=True)
    (hw / "name").write_text("coretemp\n")
    (hw / "temp1_input").write_text("47000\n")
    (hw / "temp2_input").write_text("52000\n")
    p = root / "proc/4242"
    p.mkdir(exist_ok=True)
    (p / "stat").write_text("4242 (python3 jarvis) S 1 1 1 0 -1 0 0 0 0 0 " + f"{cpu_ticks // 10} 5 0 0 20 0 1 0\n")
    (p / "statm").write_text("5000 2500 100 1 0 300 0\n")
    (p / "status").write_text("Name:\tpython3\nUid:\t1000\t1000\t1000\t1000\n")


class AgentMessenTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="pc2_root_"))
        fake_linux(self.root)
        self.env = mock.patch.dict(os.environ, {"JARVIS_AGENT_ROOT": str(self.root)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_cpu_auslastung_gesamt_und_kerne(self):
        vorher = jarvis_agent.cpu_zeiten()
        self.assertEqual(len(vorher), 5)  # gesamt + 4 Kerne
        fake_linux(self.root, cpu_ticks=2000)
        werte = jarvis_agent.auslastung(vorher, jarvis_agent.cpu_zeiten())
        # gesamt: busy 2000 von 8000 Ticks = 25 %
        self.assertAlmostEqual(werte[0], 25.0, places=1)
        for w in werte[1:]:
            self.assertGreaterEqual(w, 0)
            self.assertLessEqual(w, 100)

    def test_speicher_temperatur_system(self):
        m = jarvis_agent.speicher()
        self.assertEqual(m["prozent"], 50.0)
        self.assertEqual(m["swap_benutzt"], 500000 * 1024)
        self.assertEqual(jarvis_agent.temperatur(), 52.0)
        info = jarvis_agent.system_name()
        self.assertEqual(info, {"host": "mini-pc", "os": "Linux Mint 22.1", "kernel": "6.8.0-51-generic"})
        self.assertEqual(jarvis_agent.laufzeit_s(), 3725)
        self.assertEqual(jarvis_agent.last(), [0.52, 0.40, 0.31])

    def test_netz_ohne_loopback(self):
        self.assertEqual(jarvis_agent.netz_bytes(), (5000, 2500))

    def test_prozess_name_mit_leerzeichen(self):
        messer = jarvis_agent.ProzessMesser()
        erste = messer.messen(0, 4)
        self.assertEqual(erste[0]["name"], "python3 jarvis")
        self.assertEqual(erste[0]["uid"], 1000)
        fake_linux(self.root, cpu_ticks=2000)
        zweite = messer.messen(8000, 4)
        # 100 Ticks mehr von 8000 Gesamt-Ticks * 4 Kerne = 5 %
        self.assertAlmostEqual(zweite[0]["cpu"], 5.0, places=1)

    def test_fehlende_dateien_kein_absturz(self):
        leer = Path(tempfile.mkdtemp(prefix="pc2_leer_"))
        try:
            with mock.patch.dict(os.environ, {"JARVIS_AGENT_ROOT": str(leer)}):
                s = jarvis_agent.Sammler([])
                paket = s.messen()
                self.assertIsNone(paket["cpu"])
                self.assertIsNone(paket["speicher"])
                self.assertEqual(paket["prozesse"], [])
        finally:
            shutil.rmtree(leer, ignore_errors=True)

    def test_aktionen_nur_aus_liste(self):
        self.assertFalse(jarvis_agent.aktion_ausfuehren("rm -rf /", None, [])["ok"])
        self.assertFalse(jarvis_agent.aktion_ausfuehren("befehl:gibtsnicht", None, [])["ok"])
        r = jarvis_agent.aktion_ausfuehren("dienst_neustart", "sshd; reboot", ["ssh"])
        self.assertIn("nicht in der erlaubten Liste", r["meldung"])
        self.assertIn("geschützt", jarvis_agent.aktion_ausfuehren("prozess_beenden", 1, [])["meldung"])
        self.assertIn("Ungültige", jarvis_agent.aktion_ausfuehren("prozess_beenden", "abc", [])["meldung"])

    def test_befehle_json_nur_listen(self):
        datei = self.root / "befehle.json"
        datei.write_text(json.dumps({
            "gut": {"titel": "Gut", "befehl": ["echo", "hallo"]},
            "shell_string": {"titel": "Böse", "befehl": "echo hallo; reboot"},
        }), encoding="utf-8")
        with mock.patch.dict(os.environ, {"JARVIS_AGENT_BEFEHLE": str(datei)}):
            befehle = jarvis_agent.befehle_laden()
        self.assertEqual(list(befehle), ["gut"])

    def test_mitgelieferte_befehle_json_gueltig(self):
        with mock.patch.dict(os.environ, {"JARVIS_AGENT_BEFEHLE": str(AGENT_ORDNER / "befehle.json")}):
            self.assertGreaterEqual(len(jarvis_agent.befehle_laden()), 3)


class AgentServerTest(unittest.TestCase):
    """Echter Agent-Server + app.pc2 + FastAPI-Routen."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pc2_srv_"))
        fake_linux(cls.root)
        cls.env = mock.patch.dict(os.environ, {"JARVIS_AGENT_ROOT": str(cls.root)})
        cls.env.start()
        cls.server, cls.sammler = jarvis_agent.server_bauen(TOKEN, 0, "127.0.0.1", ["ssh"])
        cls.sammler.starten()
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.port}"

        from app import routes
        app = FastAPI()
        app.include_router(routes.router)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.sammler.stoppen()
        cls.server.shutdown()
        cls.server.server_close()
        cls.env.stop()
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self):
        self.pc2_env = mock.patch.dict(os.environ, {
            "PC2_URL": self.url, "PC2_TOKEN": TOKEN, "PC2_MAC": "00:23:24:aa:bb:cc", "PC2_VNC_PORT": "6080",
        })
        self.pc2_env.start()
        self.server.RequestHandlerClass.fehlversuche.clear()

    def tearDown(self):
        self.pc2_env.stop()

    def test_ping_ohne_token_status_nur_mit(self):
        self.assertEqual(httpx.get(self.url + "/ping").status_code, 200)
        self.assertEqual(httpx.get(self.url + "/status").status_code, 401)
        r = httpx.get(self.url + "/status", headers={"Authorization": "Bearer falsch"})
        self.assertEqual(r.status_code, 401)

    def test_sperre_nach_fehlversuchen(self):
        for _ in range(jarvis_agent.FEHLVERSUCHE_MAX):
            httpx.get(self.url + "/status", headers={"Authorization": "Bearer x"})
        r = httpx.get(self.url + "/status", headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(r.status_code, 429)  # auch der richtige Token wartet die Minute ab

    def test_status_ueber_hub(self):
        r = self.client.get("/api/pc2/status")
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["host"], "mini-pc")
        self.assertEqual(d["os"], "Linux Mint 22.1")
        self.assertIn("latenz_ms", d)
        self.assertEqual(d["dienste"][0]["name"], "ssh")
        self.assertNotIn(TOKEN, r.text)

    def test_konfig_ohne_token(self):
        d = self.client.get("/api/pc2/konfig").json()
        self.assertTrue(d["eingerichtet"])
        self.assertTrue(d["wecken_moeglich"])
        self.assertTrue(d["bildschirm_url"].startswith("http://127.0.0.1:6080/vnc.html?"))
        self.assertNotIn(TOKEN, json.dumps(d))

    def test_stream_liefert_pakete(self):
        # Der TestClient von Starlette puffert Streams bis zum Ende - ein endloser
        # Livestream wird deshalb direkt über den Generator geprüft.
        from app import routes
        antwort = routes.pc2_stream()
        self.assertEqual(antwort.media_type, "text/event-stream")
        gen = pc2.stream()
        pakete = []
        try:
            for stueck in gen:
                text = stueck.decode("utf-8")
                self.assertTrue(text.endswith("\n\n"))
                if text.startswith("data: "):
                    pakete.append(json.loads(text[6:]))
                if len(pakete) == 2:
                    break
        finally:
            gen.close()
        self.assertEqual(pakete[0]["host"], "mini-pc")
        self.assertGreater(pakete[1]["zeit"], pakete[0]["zeit"])  # jede Sekunde ein neues Paket

    def test_gefaehrliche_aktion_braucht_bestaetigung(self):
        r = self.client.post("/api/pc2/aktion", json={"aktion": "herunterfahren"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Bestätigung", r.json()["detail"])

    def test_unbekannte_aktion_abgelehnt(self):
        self.assertEqual(self.client.post("/api/pc2/aktion", json={"aktion": "rm -rf"}).status_code, 422)
        r = self.client.post("/api/pc2/aktion", json={"aktion": "befehl:gibtsnicht"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ok"])

    def test_aktionen_liste(self):
        d = self.client.get("/api/pc2/aktionen").json()
        self.assertIn("neustart", d["fest"])
        self.assertEqual(d["dienste"], ["ssh"])

    def test_falscher_token_klare_meldung(self):
        with mock.patch.dict(os.environ, {"PC2_TOKEN": "falsch"}):
            r = self.client.get("/api/pc2/status")
        self.assertEqual(r.status_code, 502)
        self.assertIn("Token", r.json()["detail"])

    def test_pc2_aus(self):
        with mock.patch.dict(os.environ, {"PC2_URL": "http://127.0.0.1:1"}):
            r = self.client.get("/api/pc2/status")
            self.assertEqual(r.status_code, 504)
            with self.client.stream("GET", "/api/pc2/stream") as s:
                text = s.read().decode("utf-8")
        self.assertIn("event: fehler", text)
        self.assertIn("nicht erreichbar", text)

    def test_nicht_eingerichtet(self):
        with mock.patch.dict(os.environ, {"PC2_URL": "", "PC2_TOKEN": ""}):
            self.assertFalse(self.client.get("/api/pc2/konfig").json()["eingerichtet"])
            self.assertEqual(self.client.get("/api/pc2/status").status_code, 409)


class WeckenTest(unittest.TestCase):
    def test_magic_packet_aufbau(self):
        p = pc2.magic_packet("00:23:24:AA:BB:CC")
        self.assertEqual(len(p), 102)
        self.assertEqual(p[:6], b"\xff" * 6)
        self.assertEqual(p[6:12], bytes.fromhex("002324aabbcc"))

    def test_ungueltige_mac(self):
        with self.assertRaises(pc2.Pc2Fehler):
            pc2.magic_packet("kaputt")

    def test_wecken_sendet(self):
        with mock.patch.dict(os.environ, {"PC2_MAC": "00-23-24-aa-bb-cc", "PC2_URL": "http://192.168.178.50:8765"}), \
             mock.patch("socket.socket") as sock:
            r = pc2.wecken()
        self.assertTrue(r["ok"])
        gesendet = sock.return_value.__enter__.return_value.sendto.call_args_list
        ziele = {c.args[1][0] for c in gesendet}
        self.assertEqual(ziele, {"255.255.255.255", "192.168.178.255"})


if __name__ == "__main__":
    unittest.main()

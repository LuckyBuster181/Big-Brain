"""P24b (16.10.2026): GPU per Chat und Alexa steuern, Fehler im ganzen System melden (Banner, Alexa-Alarm).

Kein Netz, kein RunPod, kein Amazon: Ersatz-Objekte und Stubs auf 127.0.0.1 (testschutz.stub_freigeben)."""

from __future__ import annotations

import datetime
import json
import os
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

try:
    import testschutz
except ImportError:
    from tests import testschutz

from app import alarm, alexa, alexa_alarm, ampel, chat_ablauf, gpu_befehl, gpu_miete, nachtauftraege
from app.schemas import ChatRequest

NUTZER = "amzn1.ask.account.AEXAMPLEUSERID0123456789"
SKILL = "amzn1.ask.skill.test-1234"
JETZT = datetime.datetime(2026, 10, 17, 4, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=2)))


def _intent(name: str, slots: dict | None = None, bestaetigung: str = "NONE") -> dict:
    req = {"requestId": "r1", "locale": "de-DE", "type": "IntentRequest", "timestamp": "2026-10-17T02:00:00Z",
           "intent": {"name": name, "confirmationStatus": bestaetigung,
                      "slots": {k: {"name": k, **v} for k, v in (slots or {}).items()}}}
    return {"version": "1.0", "session": {"new": True, "application": {"applicationId": SKILL}, "user": {"userId": NUTZER}},
            "context": {"System": {"application": {"applicationId": SKILL}, "user": {"userId": NUTZER}}}, "request": req}


def _sprache(a: dict) -> str:
    return a["response"].get("outputSpeech", {}).get("text", "")


class Basis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p24b_test_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        p = mock.patch.dict(os.environ, {
            "RUNPOD_API_KEY": "rpa_TESTSCHLUESSEL0123456789abcdefGEHEIM", "GPU_MIETE_VOLUME_ID": "vol123456",
            "GPU_MIETE_PATH": os.path.join(self.tmp, "gpu"), "FEHLER_LOG_PATH": os.path.join(self.tmp, "fehler.jsonl"),
            "NACHTAUFTRAEGE_PATH": os.path.join(self.tmp, "na.json"), "ALARM_PATH": os.path.join(self.tmp, "alarm.json"),
            "ALEXA_NUTZER_PATH": os.path.join(self.tmp, "nutzer.json"),
            "ALEXA_LOG_PATH": os.path.join(self.tmp, "alexa_log.jsonl"),
            "ALEXA_LETZTE_PATH": os.path.join(self.tmp, "alexa_letzte.json"),
        })
        p.start()
        self.addCleanup(p.stop)
        for n in ("GPU_MIETE_AUS", "GPU_MIETE_DECKEL_EUR", "ALEXA_NUTZER_ID", "ALEXA_ALARM_AUS"):
            os.environ.pop(n, None)
        for ziel, name, wert in ((gpu_miete, "_jetzt", lambda: JETZT),):
            s = mock.patch.object(ziel, name, wert)
            s.start()
            self.addCleanup(s.stop)
        gpu_befehl._wartend.clear()
        from app import fehlerbericht

        fehlerbericht._zuletzt_geschrieben.clear()  # noqa: SLF001

    def auftrag(self, art="entwicklung"):
        return nachtauftraege.anlegen(f"Bitte ein kleines {art}-Ding erledigen", art=art, pruefen=False)


class ChatBefehle(Basis):
    def test_erkennung(self):
        for t, aktion in (("GPU Status", "status"), ("Wie steht die GPU-Miete", "status"), ("GPU aufräumen", "aufraeumen"),
                          ("räum die Pods auf", "aufraeumen"), ("Code-Auftrag 7 auf die GPU", "auftrag"),
                          ("starte Auftrag 12 auf der GPU", "auftrag")):
            self.assertEqual(gpu_befehl.absicht(t)["aktion"], aktion, t)
        for t in ("Wie ist das Wetter", "Auftrag 7 anlegen", "Kostenstand", "Was kostet eine Grafikkarte"):
            self.assertIsNone(gpu_befehl.absicht(t), t)
        self.assertEqual(gpu_befehl.absicht("Code-Auftrag 7 auf die GPU")["nr"], 7)

    def test_status_ohne_schluessel_und_mit(self):
        del os.environ["RUNPOD_API_KEY"]
        self.assertIn("aus", gpu_befehl.status_text())
        os.environ["RUNPOD_API_KEY"] = "rpa_TESTSCHLUESSEL0123456789abcdefGEHEIM"
        t = gpu_befehl.status_text()
        self.assertIn("GPU-Miete: 0,00 von 40 EUR", t)
        self.assertIn("kein gemieteter Pod", t)
        self.assertNotIn("TESTSCHLUESSEL", t)
        gpu_miete.alarm_setzen("Pod abc nicht gelöscht", ["abc"])
        self.assertIn("ACHTUNG", gpu_befehl.status_text())

    def test_auftrag_fragt_nach_und_mietet_erst_nach_ja(self):
        code = self.auftrag()
        gestartet = []
        with mock.patch.object(nachtauftraege, "gpu_ausdruecklich_starten", side_effect=lambda nr: gestartet.append(nr) or {}):
            frage = gpu_befehl.ausfuehren(gpu_befehl.absicht(f"Code-Auftrag {code['id']} auf die GPU"))
            self.assertIn("Das kostet Geld", frage)
            self.assertIn('Sagen Sie "ja"', frage)
            self.assertEqual(gestartet, [])                        # noch nichts gemietet
            self.assertIsNone(gpu_befehl.bestaetigung("vielleicht"))   # keine Antwort auf die Frage: nichts passiert
            self.assertEqual(gestartet, [])
            self.assertIn("läuft jetzt auf einer gemieteten GPU", gpu_befehl.bestaetigung("ja"))
            self.assertEqual(gestartet, [code["id"]])
            self.assertIsNone(gpu_befehl.bestaetigung("ja"))      # Bestätigung ist verbraucht
            self.assertEqual(gestartet, [code["id"]])

    def test_nein_und_ablauf(self):
        code = self.auftrag()
        with mock.patch.object(nachtauftraege, "gpu_ausdruecklich_starten") as start:
            gpu_befehl.ausfuehren({"art": "gpu", "aktion": "auftrag", "nr": code["id"]})
            self.assertIn("nichts gemietet", gpu_befehl.bestaetigung("nein"))
            self.assertIsNone(gpu_befehl.bestaetigung("ja"))
            gpu_befehl.ausfuehren({"art": "gpu", "aktion": "auftrag", "nr": code["id"]})
            with mock.patch.object(gpu_befehl.time, "time", return_value=gpu_befehl._wartend["zeit"] + 121):  # noqa: SLF001
                self.assertIsNone(gpu_befehl.bestaetigung("ja"))
            start.assert_not_called()

    def test_ablehnungen_mit_grund(self):
        plan = self.auftrag("plan")
        self.assertIn("keine Code-Aufgabe", gpu_befehl.ausfuehren({"aktion": "auftrag", "nr": plan["id"]}))
        self.assertIn("gibt es nicht", gpu_befehl.ausfuehren({"aktion": "auftrag", "nr": 999}))
        code = self.auftrag()
        del os.environ["RUNPOD_API_KEY"]
        self.assertIn("aus", gpu_befehl.ausfuehren({"aktion": "auftrag", "nr": code["id"]}))
        os.environ["RUNPOD_API_KEY"] = "rpa_TESTSCHLUESSEL0123456789abcdefGEHEIM"
        os.environ["GPU_MIETE_DECKEL_EUR"] = "0.01"
        self.assertIn("zu knapp", gpu_befehl.ausfuehren({"aktion": "auftrag", "nr": code["id"]}))
        self.assertEqual(gpu_befehl._wartend, {})              # bei Ablehnung wird nichts vorgemerkt  # noqa: SLF001

    def test_aufraeumen_ruft_den_waechter(self):
        with mock.patch.object(gpu_miete, "waechter_lauf",
                               return_value={"ok": True, "geprueft": 2, "geloescht": [{"id": "p1", "name": "fremd"}], "fehler": []}):
            self.assertIn("Gelöscht: fremd", gpu_befehl.ausfuehren({"aktion": "aufraeumen"}))
        with mock.patch.object(gpu_miete, "waechter_lauf",
                               return_value={"ok": False, "geprueft": 1, "geloescht": [], "fehler": ["nicht gelöscht: p1"]}):
            self.assertIn("Probleme", gpu_befehl.ausfuehren({"aktion": "aufraeumen"}))

    def test_im_chat_ablauf(self):
        """Ganzer Weg: Nachricht -> Absicht -> Nachfrage -> "ja" -> Start (gemockt)."""
        code = self.auftrag()

        def chat(text):
            return "".join(e.get("text", "") for e in chat_ablauf._inner(ChatRequest(message=text), None, None))  # noqa: SLF001

        self.assertIn("GPU-Miete", chat("GPU Status"))
        with mock.patch.object(nachtauftraege, "gpu_ausdruecklich_starten", return_value={}) as start:
            self.assertIn("Das kostet Geld", chat(f"Code-Auftrag {code['id']} auf die GPU"))
            start.assert_not_called()
            self.assertIn("läuft jetzt", chat("ja"))
            start.assert_called_once_with(code["id"])


class StartBefehl(Basis):
    def test_gpu_ausdruecklich_starten_prueft_und_startet_thread(self):
        code, plan = self.auftrag(), self.auftrag("plan")
        with self.assertRaises(nachtauftraege.NachtauftragFehler):
            nachtauftraege.gpu_ausdruecklich_starten(plan["id"])
        gestartet = []
        with mock.patch.object(threading, "Thread", side_effect=lambda target, **kw: mock.Mock(start=lambda: gestartet.append(target))):
            erg = nachtauftraege.gpu_ausdruecklich_starten(code["id"])
        self.assertEqual((erg["gestartet"], erg["auftrag"]), (True, code["id"]))
        self.assertEqual(len(gestartet), 1)
        with mock.patch.object(gpu_miete, "laeuft", return_value=True), self.assertRaises(nachtauftraege.NachtauftragFehler):
            nachtauftraege.gpu_ausdruecklich_starten(code["id"])
        gpu_miete.alarm_setzen("alter Pod", ["x"])
        with self.assertRaises(nachtauftraege.NachtauftragFehler) as ctx:
            nachtauftraege.gpu_ausdruecklich_starten(code["id"])
        self.assertIn("nicht als gelöscht bestätigt", str(ctx.exception))


class AlexaSteuerung(Basis):
    def test_status_nennt_alle_roten_punkte(self):
        rot = {"gesamt": "rot", "jobs": [{"name": "Vault einlesen", "farbe": "rot", "text": "Letzter Lauf mit Fehler: Platte voll"},
                                         {"name": "Studium", "farbe": "gruen", "text": "studiert"}]}
        with mock.patch.object(ampel, "uebersicht", return_value=rot), \
                mock.patch("app.nachtarbeit.is_running", return_value=False), mock.patch("app.nachtarbeit.letzte_nacht", return_value=None), \
                mock.patch("app.kosten.uebersicht", return_value={"ausgegeben_usd": 1.0, "rahmen_usd": 20.0, "anteil_prozent": 5.0}):
            a = alexa.verarbeiten(_intent("StatusIntent"))
        s = _sprache(a)
        self.assertTrue(s.startswith("Achtung Sir, es gibt einen Fehler: Vault einlesen: Letzter Lauf mit Fehler: Platte voll."))
        self.assertNotIn("Sonst läuft alles", s)
        self.assertIn("Vault einlesen", a["response"]["card"]["content"])

    def test_status_alles_gut(self):
        gruen = {"gesamt": "grau", "jobs": [{"name": "Studium", "farbe": "grau", "text": "ruht"}]}
        with mock.patch.object(ampel, "uebersicht", return_value=gruen), \
                mock.patch("app.nachtarbeit.is_running", return_value=False), mock.patch("app.nachtarbeit.letzte_nacht", return_value=None), \
                mock.patch("app.kosten.uebersicht", return_value={"ausgegeben_usd": 1.0, "rahmen_usd": 20.0, "anteil_prozent": 5.0}):
            s = _sprache(alexa.verarbeiten(_intent("StatusIntent")))
        self.assertIn("Sonst läuft alles.", s)
        self.assertNotIn("Achtung", s)

    def test_gpu_auftrag_erst_nach_ja(self):
        code = self.auftrag()
        slot = {"nummer": {"value": str(code["id"])}}
        with mock.patch.object(nachtauftraege, "gpu_ausdruecklich_starten", return_value={}) as start:
            a = alexa.verarbeiten(_intent("GpuAuftragIntent", slot, "NONE"))
            self.assertEqual(a["response"]["directives"], [{"type": "Dialog.Delegate"}])   # Alexa fragt selbst nach
            start.assert_not_called()
            a = alexa.verarbeiten(_intent("GpuAuftragIntent", slot, "DENIED"))
            self.assertIn("nichts", _sprache(a).lower())
            start.assert_not_called()
            a = alexa.verarbeiten(_intent("GpuAuftragIntent", slot, "CONFIRMED"))
            start.assert_called_once_with(code["id"])
            self.assertIn("gemieteten GPU", _sprache(a))

    def test_gpu_auftrag_ohne_nummer_und_mit_fehler(self):
        a = alexa.verarbeiten(_intent("GpuAuftragIntent", {"nummer": {}}, "CONFIRMED"))
        self.assertEqual(a["response"]["directives"], [{"type": "Dialog.Delegate"}])
        a = alexa.verarbeiten(_intent("GpuAuftragIntent", {"nummer": {"value": "999"}}, "CONFIRMED"))
        self.assertIn("Das geht nicht", _sprache(a))

    def test_aktion_gpu_aufraeumen_in_der_whitelist(self):
        self.assertTrue(alexa.ALEXA_AKTIONEN["gpu_aufraeumen"]["aktiv"])
        gestartet = []
        with mock.patch.object(alexa.threading, "Thread", side_effect=lambda target, **kw: mock.Mock(start=lambda: gestartet.append(target))):
            antwort = alexa.aktion_ausfuehren("gpu_aufraeumen")
        self.assertIn("räume", antwort)
        self.assertEqual(gestartet, [gpu_miete.waechter_lauf])
        del os.environ["RUNPOD_API_KEY"]
        self.assertIn("geht gerade nicht", alexa.aktion_ausfuehren("gpu_aufraeumen"))

    def test_modell_passt_zum_code(self):
        modell = json.loads((Path(__file__).resolve().parents[1] / "alexa" / "interaktionsmodell_de.json").read_text(encoding="utf-8"))
        m = modell["interactionModel"]
        namen = {i["name"] for i in m["languageModel"]["intents"]}
        self.assertIn("GpuAuftragIntent", namen)
        self.assertIn("GpuAuftragIntent", {i["name"] for i in m["dialog"]["intents"]})
        prompts = {p["id"] for p in m["prompts"]}
        di = next(i for i in m["dialog"]["intents"] if i["name"] == "GpuAuftragIntent")
        self.assertTrue(di["confirmationRequired"])
        self.assertIn(di["prompts"]["confirmation"], prompts)
        self.assertIn(di["slots"][0]["prompts"]["elicitation"], prompts)
        intent = next(i for i in m["languageModel"]["intents"] if i["name"] == "GpuAuftragIntent")
        self.assertTrue(all("{nummer}" in s for s in intent["samples"]))

    def test_alexa_anfrage_lernt_die_kennung(self):
        self.assertIsNone(alexa_alarm.nutzer())
        alexa.verarbeiten(_intent("AMAZON.HelpIntent"))
        self.assertEqual(alexa_alarm.nutzer(), NUTZER)


class AlarmLogik(Basis):
    def setUp(self):
        super().setUp()
        self.gesendet: list[list[str]] = []
        self.klappt = True
        e = mock.patch.object(alexa_alarm, "eingerichtet", return_value=True)
        s = mock.patch.object(alexa_alarm, "senden", side_effect=lambda namen, jetzt=None: (self.gesendet.append(list(namen)) or self.klappt,
                                                                                            "ok" if self.klappt else "kaputt"))
        e.start(), s.start()
        self.addCleanup(e.stop)
        self.addCleanup(s.stop)

    def rot(self, *namen):
        return [{"name": n, "text": f"{n} kaputt"} for n in namen]

    def test_neu_rot_wird_genau_einmal_gemeldet(self):
        alarm.pruefen(self.rot("Vault einlesen"), jetzt=JETZT)
        alarm.pruefen(self.rot("Vault einlesen"), jetzt=JETZT + datetime.timedelta(minutes=5))
        alarm.pruefen(self.rot("Vault einlesen"), jetzt=JETZT + datetime.timedelta(hours=5))
        self.assertEqual(self.gesendet, [["Vault einlesen"]])

    def test_erinnerung_nach_sechs_stunden(self):
        alarm.pruefen(self.rot("Kosten"), jetzt=JETZT)
        alarm.pruefen(self.rot("Kosten"), jetzt=JETZT + datetime.timedelta(hours=6, minutes=1))
        self.assertEqual(self.gesendet, [["Kosten"], ["Kosten"]])

    def test_wieder_gut_und_dann_wieder_kaputt_meldet_neu(self):
        alarm.pruefen(self.rot("Studium"), jetzt=JETZT)
        alarm.pruefen([], jetzt=JETZT + datetime.timedelta(minutes=10))
        alarm.pruefen(self.rot("Studium"), jetzt=JETZT + datetime.timedelta(minutes=20))
        self.assertEqual(len(self.gesendet), 2)

    def test_mehrere_gleichzeitig_eine_meldung(self):
        alarm.pruefen(self.rot("Studium", "Kosten"), jetzt=JETZT)
        self.assertEqual(self.gesendet, [["Studium", "Kosten"]])

    def test_nur_neue_werden_nachgemeldet(self):
        alarm.pruefen(self.rot("Studium"), jetzt=JETZT)
        alarm.pruefen(self.rot("Studium", "Kosten"), jetzt=JETZT + datetime.timedelta(minutes=5))
        self.assertEqual(self.gesendet, [["Studium"], ["Kosten"]])

    def test_zustellung_scheitert_dann_nochmal_versuchen(self):
        self.klappt = False
        alarm.pruefen(self.rot("Studium"), jetzt=JETZT)
        self.klappt = True
        alarm.pruefen(self.rot("Studium"), jetzt=JETZT + datetime.timedelta(minutes=5))
        self.assertEqual(self.gesendet, [["Studium"], ["Studium"]])
        alarm.pruefen(self.rot("Studium"), jetzt=JETZT + datetime.timedelta(minutes=10))
        self.assertEqual(len(self.gesendet), 2)                 # jetzt zugestellt: Ruhe

    def test_ohne_kanal_wird_nichts_als_gemeldet_vermerkt(self):
        with mock.patch.object(alexa_alarm, "eingerichtet", return_value=False):
            r = alarm.pruefen(self.rot("Studium"), jetzt=JETZT)
        self.assertEqual(r["kanaele"], [])
        alarm.pruefen(self.rot("Studium"), jetzt=JETZT + datetime.timedelta(minutes=5))
        self.assertEqual(self.gesendet, [["Studium"]])          # sobald ein Kanal da ist, kommt die Meldung

    def test_bereich_fasst_fremden_zustand_nicht_an(self):
        alarm.pruefen(self.rot("Studium"), jetzt=JETZT)
        alarm.pruefen([], bereich=["GPU-Miete"], jetzt=JETZT + datetime.timedelta(minutes=5))   # GPU-Wächter
        alarm.pruefen(self.rot("Studium"), jetzt=JETZT + datetime.timedelta(minutes=10))
        self.assertEqual(self.gesendet, [["Studium"]])          # "Studium" wurde nicht vergessen

    def test_gpu_alarm_geht_sofort_raus_auch_ohne_backend_schleife(self):
        gpu_miete.alarm_setzen("Pod abc konnte nicht gelöscht werden", ["abc"])
        self.assertEqual(self.gesendet, [["GPU-Miete"]])
        gpu_miete.alarm_loeschen()
        alarm.pruefen_gpu()
        self.assertEqual(alarm._lesen(), {})                    # noqa: SLF001 - Entwarnung

    def test_pruefen_liest_die_ampel(self):
        with mock.patch.object(ampel, "uebersicht", return_value={"gesamt": "rot", "jobs": [
                {"name": "Marktdaten", "farbe": "rot", "text": "Laden abgebrochen"}, {"name": "TikTok", "farbe": "gelb", "text": "x"}]}):
            r = alarm.pruefen(jetzt=JETZT)
        self.assertEqual(r["gemeldet"], ["Marktdaten"])

    def test_fehler_in_der_ampel_wirft_nicht(self):
        with mock.patch.object(ampel, "uebersicht", side_effect=RuntimeError("kaputt")):
            r = alarm.pruefen(jetzt=JETZT)
        self.assertIn("fehler", r)

    def test_status_und_hintergrund(self):
        self.assertTrue(alarm.status()["alexa_eingerichtet"])
        os.environ["ALARM_AUS"] = "1"
        with mock.patch.object(alarm.threading, "Thread") as t:
            alarm.start_hintergrund()
        t.assert_not_called()
        del os.environ["ALARM_AUS"]
        with mock.patch.object(alarm.threading, "Thread") as t:
            alarm.start_hintergrund()
        t.assert_called_once()
        alarm.stoppen()


class AmazonStub(BaseHTTPRequestHandler):
    antworten: dict = {}
    anfragen: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        laenge = int(self.headers.get("Content-Length") or 0)
        roh = self.rfile.read(laenge).decode()
        ctype = self.headers.get("Content-Type", "")
        AmazonStub.anfragen.append({"pfad": self.path, "auth": self.headers.get("Authorization"),
                                    "body": json.loads(roh) if "json" in ctype else dict(p.split("=", 1) for p in roh.split("&"))})
        code, daten = AmazonStub.antworten.get(self.path, (404, {}))
        antwort = json.dumps(daten).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(antwort)))
        self.end_headers()
        self.wfile.write(antwort)


class AlexaBenachrichtigung(Basis):
    def setUp(self):
        super().setUp()
        AmazonStub.antworten = {"/token": (200, {"access_token": "TOKEN-GEHEIM-123", "expires_in": 3600}), "/event": (202, {})}
        AmazonStub.anfragen = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), AmazonStub)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        port = self.server.server_address[1]
        testschutz.stub_freigeben(self, port)
        os.environ.update({"ALEXA_ALARM_CLIENT_ID": "amzn1.application-oa2-client.test", "ALEXA_ALARM_CLIENT_SECRET": "SECRET-GEHEIM-456",
                           "ALEXA_ALARM_TOKEN_URL": f"http://127.0.0.1:{port}/token",
                           "ALEXA_ALARM_EVENT_URL": f"http://127.0.0.1:{port}/event", "ALEXA_NUTZER_ID": NUTZER})
        alexa_alarm._token.update(wert=None, bis=0.0)  # noqa: SLF001
        self.addCleanup(lambda: alexa_alarm._token.update(wert=None, bis=0.0))  # noqa: SLF001

    def test_einrichtung_wird_erkannt(self):
        self.assertTrue(alexa_alarm.eingerichtet())
        del os.environ["ALEXA_ALARM_CLIENT_SECRET"]
        self.assertFalse(alexa_alarm.eingerichtet())
        self.assertIn("ALEXA_ALARM_CLIENT_ID", alexa_alarm.fehlt())
        self.assertIn("Anfrage an den Alexa-Skill", (os.environ.pop("ALEXA_NUTZER_ID"), alexa_alarm.fehlt())[1])
        self.assertIn("nicht eingerichtet", alexa_alarm.senden(["Test"])[1])
        os.environ.update({"ALEXA_ALARM_CLIENT_SECRET": "x", "ALEXA_NUTZER_ID": NUTZER, "ALEXA_ALARM_AUS": "1"})
        self.assertFalse(alexa_alarm.eingerichtet())

    def test_senden_holt_token_und_schickt_ereignis(self):
        ok, text = alexa_alarm.senden(["GPU-Miete"], JETZT)
        self.assertTrue(ok, text)
        token, ereignis = AmazonStub.anfragen
        self.assertEqual(token["body"]["grant_type"], "client_credentials")
        self.assertEqual(token["body"]["scope"], "alexa%3A%3Aproactive_events" if "%3A" in token["body"]["scope"] else "alexa::proactive_events")
        self.assertEqual(ereignis["auth"], "Bearer TOKEN-GEHEIM-123")
        b = ereignis["body"]
        self.assertEqual(b["event"]["name"], "AMAZON.MessageAlert.Activated")
        self.assertEqual(b["event"]["payload"]["messageGroup"]["creator"]["name"], "Auron Alarm GPU-Miete")
        self.assertEqual(b["event"]["payload"]["state"], {"status": "UNREAD", "freshness": "NEW"})
        self.assertEqual(b["relevantAudience"], {"type": "Unicast", "payload": {"user": NUTZER}})
        self.assertTrue(b["timestamp"].endswith("Z") and b["expiryTime"].endswith("Z"))
        self.assertTrue(b["referenceId"].startswith("auron-"))
        self.assertGreater(b["expiryTime"], b["timestamp"])

    def test_token_wird_wiederverwendet(self):
        alexa_alarm.senden(["A"], JETZT)
        alexa_alarm.senden(["B"], JETZT)
        self.assertEqual([a["pfad"] for a in AmazonStub.anfragen], ["/token", "/event", "/event"])

    def test_absender_kurz_und_bei_mehreren_allgemein(self):
        self.assertEqual(alexa_alarm.absender_name(["A", "B"]), "Auron Alarm")
        self.assertLessEqual(len(alexa_alarm.absender_name(["x" * 100])), alexa_alarm.ABSENDER_MAX)

    def test_fehlerfaelle_ohne_geheimnisse_im_text(self):
        for code, wort in ((400, "lehnt"), (403, "Berechtigung"), (429, "zu viele"), (432, "limit"), (500, "Fehler bei Amazon")):
            AmazonStub.antworten["/event"] = (code, {"message": "SECRET-GEHEIM-456 TOKEN-GEHEIM-123"})
            ok, text = alexa_alarm.senden(["X"], JETZT)
            self.assertFalse(ok)
            self.assertIn(wort.lower(), text.lower())
            self.assertNotIn("SECRET-GEHEIM", text)
            self.assertNotIn("TOKEN-GEHEIM", text)
        AmazonStub.antworten["/event"] = (401, {})
        self.assertFalse(alexa_alarm.senden(["X"], JETZT)[0])
        self.assertIsNone(alexa_alarm._token["wert"])                        # noqa: SLF001 - neues Token beim nächsten Mal
        AmazonStub.antworten["/token"] = (400, {"error": "invalid_client"})
        ok, text = alexa_alarm.senden(["X"], JETZT)
        self.assertFalse(ok)
        self.assertIn("Client-ID und Secret prüfen", text)

    def test_fremde_adresse_wird_ignoriert(self):
        os.environ["ALEXA_ALARM_TOKEN_URL"] = "https://boese.example.org/token"
        self.assertEqual(alexa_alarm._loopback_oder(os.environ["ALEXA_ALARM_TOKEN_URL"], alexa_alarm.TOKEN_URL), alexa_alarm.TOKEN_URL)  # noqa: SLF001

    def test_endpunkt_je_region_und_stufe(self):
        for n in ("ALEXA_ALARM_EVENT_URL",):
            os.environ.pop(n)
        self.assertEqual(alexa_alarm._event_url(), "https://api.eu.amazonalexa.com/v1/proactiveEvents/stages/development")  # noqa: SLF001
        os.environ["ALEXA_ALARM_REGION"], os.environ["ALEXA_ALARM_STUFE"] = "NA", "live"
        self.assertEqual(alexa_alarm._event_url(), "https://api.amazonalexa.com/v1/proactiveEvents/")  # noqa: SLF001
        del os.environ["ALEXA_ALARM_REGION"], os.environ["ALEXA_ALARM_STUFE"]

    def test_routen(self):
        from app import routes

        self.assertTrue(routes.alarm_test()["gesendet"])
        self.assertTrue(routes.alarm_status()["alexa_eingerichtet"])

    def test_ohne_stub_freigabe_gesperrt(self):
        os.environ["ALEXA_ALARM_TOKEN_URL"] = "http://127.0.0.1:9/token"
        alexa_alarm._token.update(wert=None, bis=0.0)  # noqa: SLF001
        with self.assertRaises(testschutz.geraeteschutz.GeraetGesperrt):
            alexa_alarm._zugriffstoken()  # noqa: SLF001


class Banner(unittest.TestCase):
    def test_banner_liest_die_ampel_und_zeigt_rote_bereiche(self):
        html = (Path(__file__).resolve().parents[2] / "dashboard" / "auron.html").read_text(encoding="utf-8")
        for stueck in ('"/api/ampel"', "ampelRot", "ampelPruefen", 'j.farbe === "rot"'):
            self.assertIn(stueck, html)


if __name__ == "__main__":
    unittest.main()

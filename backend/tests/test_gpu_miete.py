"""P24 (16.10.2026): GPU-Miete mit Selbstabschaltung (app/gpu_miete.py).

Kein echter RunPod-Aufruf, kein Netz, nie ein echter Schlüssel: Die RunPod-API ist durch FakeApi ersetzt, die
Uhr durch eine falsche Uhr (keine echten Wartezeiten), der Pod-Zeitgeber durch FakeTimer. Der Test der echten
Anfrage-Klasse (RunpodApi) läuft gegen einen Stub auf 127.0.0.1 (testschutz.stub_freigeben).
Der Kern: In JEDEM Fehlerfall wird der Pod gelöscht oder es gibt einen lauten Alarm."""

from __future__ import annotations

import datetime
import json
import os
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest import mock

try:
    import testschutz
except ImportError:
    from tests import testschutz

from app import ampel, alexa, fehlerbericht, gpu_miete, kosten, nacht_ki, nachtauftraege, nachtbericht
from llm import provider

SCHLUESSEL = "rpa_TESTSCHLUESSEL0123456789abcdefGEHEIM"
ZONE = datetime.timezone(datetime.timedelta(hours=2))
NACHTS = datetime.datetime(2026, 10, 17, 4, 0, tzinfo=ZONE)
MODELL = "qwen3-coder:30b"


class Uhr:
    """Falsche Uhr: schlafen() verbraucht keine echte Zeit, sondern schiebt nur die Zeiger."""

    def __init__(self, jetzt: datetime.datetime = NACHTS) -> None:
        self.t = 1000.0
        self.zeit = jetzt
        self.pausen: list[float] = []

    def mono(self) -> float:
        return self.t

    def jetzt(self) -> datetime.datetime:
        return self.zeit

    def schlafen(self, s: float) -> None:
        self.pausen.append(s)
        self.vergehen(s)

    def vergehen(self, s: float) -> None:
        self.t += s
        self.zeit += datetime.timedelta(seconds=s)


class FakeTimer:
    instanzen: list["FakeTimer"] = []

    def __init__(self, interval, fn):
        self.interval, self.fn = interval, fn
        self.daemon = False
        self.abgebrochen = False
        FakeTimer.instanzen.append(self)

    def start(self):
        pass

    def cancel(self):
        self.abgebrochen = True


class FakeApi:
    """Ersatz für RunpodApi. Fehler lassen sich einzeln einschalten."""

    def __init__(self, uhr: Uhr | None = None) -> None:
        self.pods: dict[str, dict] = {}
        self.n = 0
        self.erstellt: list[dict] = []
        self.loesch_aufrufe: list[str] = []
        self.erstellen_fehler: Exception | None = None
        self.antwort_verloren = False
        self.loeschen_fehlt: float = 0           # so viele Lösch-Aufrufe schlagen zuerst fehl (inf = immer)
        self.loeschen_wirkungslos = False        # Aufruf meldet Erfolg, der Pod bleibt aber
        self.liste_fehler: Exception | None = None
        self.status_neu = "RUNNING"
        self.preis: Any = "0.40"
        self.uhr = uhr

    def erstellen(self, body: dict) -> dict:
        if self.erstellen_fehler:
            raise self.erstellen_fehler
        self.n += 1
        pid = f"pod{self.n:06d}xy"
        pod = {"id": pid, "name": body["name"], "desiredStatus": self.status_neu, "costPerHr": self.preis}
        self.pods[pid] = pod
        self.erstellt.append(body)
        if self.antwort_verloren:
            raise gpu_miete.RunpodFehler("Zeitüberschreitung bei POST /pods")
        return dict(pod)

    def liste(self) -> list[dict]:
        if self.liste_fehler:
            raise self.liste_fehler
        return [dict(p) for p in self.pods.values()]

    def holen(self, pod_id: str):
        p = self.pods.get(pod_id)
        return dict(p) if p else None

    def loeschen(self, pod_id: str) -> None:
        self.loesch_aufrufe.append(pod_id)
        if self.loeschen_fehlt > 0:
            self.loeschen_fehlt -= 1
            raise gpu_miete.RunpodFehler("RunPod DELETE: HTTP 500")
        if not self.loeschen_wirkungslos:
            self.pods.pop(pod_id, None)

    def fremd(self, name: str, status: str = "RUNNING", **mehr) -> str:
        self.n += 1
        pid = f"pod{self.n:06d}xy"
        self.pods[pid] = {"id": pid, "name": name, "desiredStatus": status, "costPerHr": "0.5", **mehr}
        return pid


class GpuTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gpu_miete_test_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        p = mock.patch.dict(os.environ, {
            "RUNPOD_API_KEY": SCHLUESSEL,
            "GPU_MIETE_VOLUME_ID": "vol123456",
            "GPU_MIETE_PATH": os.path.join(self.tmp, "gpu"),
            "FEHLER_LOG_PATH": os.path.join(self.tmp, "fehler.jsonl"),
        })
        p.start()
        self.addCleanup(p.stop)
        for name in ("GPU_MIETE_AUS", "GPU_MIETE_DECKEL_EUR", "GPU_MIETE_MAX_STUNDEN", "GPU_MIETE_FREMDE_LOESCHEN",
                     "GPU_MIETE_VON", "GPU_MIETE_BIS", "GPU_MIETE_MODELL", "GPU_MIETE_GPU", "RUNPOD_API_URL"):
            os.environ.pop(name, None)
        fehlerbericht._zuletzt_geschrieben.clear()   # gleiche Meldung nicht von einem früheren Test unterdrücken lassen  # noqa: SLF001
        self.uhr = Uhr()
        self.api = FakeApi(self.uhr)
        self.ollama = lambda url: ([MODELL], [MODELL])
        FakeTimer.instanzen = []
        for ziel, ersatz in ((gpu_miete, {"_mono": self.uhr.mono, "_schlafen": self.uhr.schlafen,
                                          "_jetzt": self.uhr.jetzt}),):
            for name, wert in ersatz.items():
                s = mock.patch.object(ziel, name, wert)
                s.start()
                self.addCleanup(s.stop)
        for ziel, name, wert in ((gpu_miete, "_ollama_pruefen", lambda url: self.ollama(url)),
                                 (gpu_miete.threading, "Timer", FakeTimer),
                                 (gpu_miete, "atexit", mock.Mock())):
            s = mock.patch.object(ziel, name, wert)
            s.start()
            self.addCleanup(s.stop)

    def fehlerbericht_texte(self) -> str:
        try:
            with open(os.environ["FEHLER_LOG_PATH"], encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def mieten(self, aufgabe=lambda s: None, **kw):
        with gpu_miete.sitzung(api=self.api, **kw) as s:
            return aufgabe(s)


class Schluessel(GpuTest):
    def test_ohne_schluessel_bleibt_alles_aus(self):
        del os.environ["RUNPOD_API_KEY"]
        self.assertFalse(gpu_miete.ist_aktiv())
        with self.assertRaises(gpu_miete.GpuMieteGesperrt) as ctx:
            self.mieten()
        self.assertTrue(ctx.exception.still)
        self.assertEqual(self.api.erstellt, [])
        erg = gpu_miete.waechter_lauf(self.api)          # Wächter tut ohne Schlüssel nichts
        self.assertEqual((erg["aktiv"], erg["geprueft"]), (False, 0))
        self.assertEqual(self.api.loesch_aufrufe, [])

    def test_schluessel_nie_im_pod_nie_in_meldungen(self):
        body = gpu_miete.pod_body("auron-gpu-x")
        self.assertNotIn(SCHLUESSEL, json.dumps(body))
        self.assertNotIn("RUNPOD", json.dumps(body))
        text = gpu_miete._sauber(f"HTTP 500 mit {SCHLUESSEL} im Text")  # noqa: SLF001
        self.assertNotIn(SCHLUESSEL, text)
        self.assertNotIn("TESTSCHLUESSEL", fehlerbericht.saeubern(f"Authorization: {SCHLUESSEL}"))
        self.assertNotIn("TESTSCHLUESSEL", fehlerbericht.saeubern(f"key rpa_TESTSCHLUESSEL0123 fehlt"))

    def test_nur_ein_loopback_api_ziel_wird_akzeptiert(self):
        os.environ["RUNPOD_API_URL"] = "https://boese.example.org/v1"
        self.assertEqual(gpu_miete._basis_url(), gpu_miete.API_STANDARD)  # noqa: SLF001
        os.environ["RUNPOD_API_URL"] = "http://127.0.0.1:9/v1"
        self.assertEqual(gpu_miete._basis_url(), "http://127.0.0.1:9/v1")  # noqa: SLF001


class Normalablauf(GpuTest):
    def test_pod_wird_gemietet_benutzt_und_geloescht(self):
        gesehen = {}

        def aufgabe(s):
            gesehen["ziel"] = provider.ziele(False)
            gesehen["tag"] = provider.ziele(True)
            self.uhr.vergehen(3600)   # eine Stunde Arbeit
            return "ergebnis"

        self.assertEqual(self.mieten(aufgabe), "ergebnis")
        b = self.api.erstellt[0]
        self.assertEqual(b["gpuTypeIds"], ["NVIDIA A40"])
        self.assertEqual(b["networkVolumeId"], "vol123456")
        self.assertEqual(b["env"]["OLLAMA_MODELS"], "/workspace/ollama/models")
        self.assertEqual(b["env"]["GPU_MODELL"], MODELL)
        self.assertEqual(b["ports"], ["11434/http"])
        self.assertFalse(b["interruptible"])
        self.assertTrue(b["name"].startswith("auron-gpu-"))
        # Während der Aufgabe: nur der Pod, mit Stream und langer Zeitgrenze; tagsüber unberührt
        z = gesehen["ziel"]
        self.assertEqual(len(z), 1)
        self.assertEqual(z[0]["modell"], MODELL)
        self.assertTrue(z[0]["url"].endswith("-11434.proxy.runpod.net"))
        self.assertEqual((z[0]["stream"], z[0]["lese_zeit"]), ("1", "3600"))
        self.assertNotIn("proxy.runpod.net", json.dumps(gesehen["tag"]))
        # Danach: Pod weg, Ziel zurückgesetzt, Kosten gebucht (1 h * 0,40 $ * 0,92)
        self.assertEqual(self.api.pods, {})
        self.assertNotIn("proxy.runpod.net", json.dumps(provider.ziele(False)))
        self.assertAlmostEqual(gpu_miete.verbrauch_eur(), 0.368, places=3)
        self.assertEqual(gpu_miete.aktive_pods(), {})
        self.assertIsNone(gpu_miete.alarm_lesen())
        self.assertIn("gelöscht und bestätigt", gpu_miete.letzte_zeile())

    def test_laufender_pod_zaehlt_im_verbrauch_mit(self):
        def aufgabe(s):
            self.uhr.vergehen(1800)
            self.assertAlmostEqual(gpu_miete.verbrauch_eur(), 0.184, places=3)
            self.assertTrue(gpu_miete.laeuft())
            self.assertEqual(ampel._gpu_miete()["farbe"], "gruen")  # noqa: SLF001

        self.mieten(aufgabe)
        self.assertFalse(gpu_miete.laeuft())

    def test_wartet_bis_modell_geladen(self):
        antworten = iter([(None, None), ([MODELL], []), ([MODELL], [MODELL])])
        self.ollama = lambda url: next(antworten)
        self.mieten()
        self.assertEqual(self.uhr.pausen[:2], [5, 5])   # zweimal gewartet, dann bereit
        self.assertEqual(self.api.pods, {})

    def test_modell_da_aber_nicht_geladen_laeuft_nach_wartezeit_trotzdem(self):
        self.ollama = lambda url: ([MODELL], [])
        self.mieten()
        self.assertEqual(self.api.pods, {})
        self.assertGreaterEqual(sum(self.uhr.pausen), 180)


class FehlerfaelleLoeschenImmer(GpuTest):
    """Der Kern des Auftrags: der Pod ist nach JEDEM Fehler weg."""

    def test_aufgabe_wirft_fehler(self):
        def aufgabe(s):
            raise ValueError("Modell hat Unsinn geliefert")

        with self.assertRaises(ValueError):
            self.mieten(aufgabe)
        self.assertEqual(self.api.pods, {})
        self.assertEqual(len(self.api.loesch_aufrufe), 1)
        self.assertIsNone(gpu_miete.alarm_lesen())

    def test_abbruch_per_tastatur_loescht_auch(self):
        def aufgabe(s):
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            self.mieten(aufgabe)
        self.assertEqual(self.api.pods, {})

    def test_start_schlaegt_fehl_ohne_pod(self):
        self.api.erstellen_fehler = gpu_miete.RunpodFehler("RunPod POST /pods: HTTP 400: keine GPU frei", 400)
        with self.assertRaises(gpu_miete.GpuMieteFehler) as ctx:
            self.mieten()
        self.assertNotIsInstance(ctx.exception, gpu_miete.GpuMieteGesperrt)
        self.assertIn("keine GPU frei", str(ctx.exception))
        self.assertEqual(self.api.pods, {})
        self.assertIsNone(gpu_miete.alarm_lesen())
        self.assertFalse(gpu_miete.laeuft())               # Sperre wieder frei

    def test_start_antwort_verloren_pod_wird_per_namen_geloescht(self):
        self.api.antwort_verloren = True    # RunPod hat den Pod angelegt, die Antwort kam aber nicht an
        with self.assertRaises(gpu_miete.GpuMieteFehler):
            self.mieten()
        self.assertEqual(self.api.n, 1)
        self.assertEqual(self.api.pods, {})  # trotzdem gelöscht
        self.assertIsNone(gpu_miete.alarm_lesen())

    def test_start_antwort_verloren_und_liste_geht_nicht_alarm(self):
        self.api.antwort_verloren = True
        self.api.liste_fehler = gpu_miete.RunpodFehler("RunPod GET /pods: HTTP 503")
        with self.assertRaises(gpu_miete.GpuLoeschFehler):
            self.mieten()
        self.assertIsNotNone(gpu_miete.alarm_lesen())      # unklar, ob der Pod läuft -> laut melden

    def test_ollama_antwortet_nie(self):
        self.ollama = lambda url: (None, None)
        with self.assertRaises(gpu_miete.GpuMieteFehler) as ctx:
            self.mieten()
        self.assertIn("antwortet nicht", str(ctx.exception))
        self.assertEqual(self.api.pods, {})
        self.assertGreaterEqual(sum(self.uhr.pausen), 900)   # Zeitgrenze (Standard 900 s) wurde abgewartet
        self.assertIsNone(gpu_miete.alarm_lesen())

    def test_pod_wird_beim_warten_beendet(self):
        def ollama(url):
            for p in self.api.pods.values():
                p["desiredStatus"] = "EXITED"
            return None, None

        self.ollama = ollama
        with self.assertRaises(gpu_miete.GpuMieteFehler) as ctx:
            self.mieten()
        self.assertIn("beendet", str(ctx.exception))
        self.assertEqual(self.api.pods, {})

    def test_loeschen_klappt_erst_beim_dritten_versuch(self):
        self.api.loeschen_fehlt = 2
        self.mieten()
        self.assertEqual(self.api.pods, {})
        self.assertEqual(len(self.api.loesch_aufrufe), 3)
        self.assertEqual(self.uhr.pausen[-2:], [2.0, 4.0])      # Wartezeit verdoppelt sich
        self.assertIsNone(gpu_miete.alarm_lesen())

    def test_loeschen_schlaegt_immer_fehl_alarm_ueberall(self):
        self.api.loeschen_fehlt = float("inf")
        with self.assertRaises(gpu_miete.GpuLoeschFehler):
            self.mieten()
        self.assertEqual(len(self.api.loesch_aufrufe), gpu_miete.LOESCH_VERSUCHE)
        pid = next(iter(self.api.pods))
        # Alarm in Datei, Ampel, Fehlerbericht, Alexa, Nachtbericht
        alarm = gpu_miete.alarm_lesen()
        self.assertIn(pid, alarm["pods"])
        a = ampel._gpu_miete()  # noqa: SLF001
        self.assertEqual(a["farbe"], "rot")
        self.assertIn("ALARM", a["text"])
        self.assertIn("GPU-Miete", ampel.uebersicht()["jobs"][-1]["name"])
        self.assertEqual(ampel.uebersicht()["gesamt"], "rot")
        self.assertIn("FEHLER GPU-Miete", self.fehlerbericht_texte())
        self.assertIn("nicht als gelöscht bestätigt", gpu_miete.sprach_hinweis())
        self.assertIn("nicht als gelöscht bestätigt", alexa._status()["sprache"])  # noqa: SLF001
        self.assertTrue(any("GPU-Miete" in p for p in nachtbericht.kurz()["punkte"]))
        self.assertIn("ALARM", "\n".join(gpu_miete.bericht_zeilen()))
        # Pod steht noch im Journal (Kosten laufen weiter in der Anzeige), neue Miete gesperrt
        self.assertIn(pid, gpu_miete.aktive_pods())
        with self.assertRaises(gpu_miete.GpuMieteGesperrt) as ctx:
            self.mieten()
        self.assertIn("nicht als gelöscht bestätigt", str(ctx.exception))
        # Der Wächter findet den Pod, löscht ihn und hebt den Alarm auf
        self.api.loeschen_fehlt = 0
        erg = gpu_miete.waechter_lauf(self.api)
        self.assertTrue(erg["ok"])
        self.assertEqual(self.api.pods, {})
        self.assertIsNone(gpu_miete.alarm_lesen())
        self.assertEqual(gpu_miete.aktive_pods(), {})
        self.mieten()                                        # und es geht wieder

    def test_loeschen_scheinbar_ok_pod_bleibt_in_der_liste(self):
        self.api.loeschen_wirkungslos = True
        with self.assertRaises(gpu_miete.GpuLoeschFehler):
            self.mieten()
        self.assertEqual(len(self.api.loesch_aufrufe), gpu_miete.LOESCH_VERSUCHE)  # Bestätigung fehlte -> weiter versucht
        self.assertIsNotNone(gpu_miete.alarm_lesen())

    def test_aufgabe_und_loeschen_scheitern_beide(self):
        self.api.loeschen_fehlt = float("inf")

        def aufgabe(s):
            raise ValueError("kaputt")

        with self.assertRaises(gpu_miete.GpuLoeschFehler) as ctx:      # das Laute gewinnt
            self.mieten(aufgabe)
        self.assertIsInstance(ctx.exception.__context__, ValueError)
        self.assertIsNotNone(gpu_miete.alarm_lesen())


class NotbremseUndGrenzen(GpuTest):
    def test_notbremse_loescht_waehrend_die_aufgabe_haengt(self):
        def aufgabe(s):
            timer = FakeTimer.instanzen[-1]
            self.assertAlmostEqual(timer.interval, 3 * 3600, delta=1)   # Standard 3 Stunden
            self.assertGreater(s.restzeit_s(), 0)
            timer.fn()                                                   # Zeit ist um
            self.assertEqual(self.api.pods, {})                          # Pod weg, obwohl die Aufgabe noch "läuft"
            self.assertEqual(s.restzeit_s(), 0)
            self.assertTrue(s.abgelaufen)

        self.mieten(aufgabe)
        self.assertEqual(len(self.api.loesch_aufrufe), 1)               # danach löscht der finally-Block nicht doppelt
        self.assertTrue(FakeTimer.instanzen[-1].abgebrochen)

    def test_maximaldauer_ist_einstellbar_und_begrenzt_durch_restbudget(self):
        os.environ["GPU_MIETE_MAX_STUNDEN"] = "1.5"
        self.assertAlmostEqual(gpu_miete.pruefen_start(), 1.5 * 3600, delta=1)
        os.environ["GPU_MIETE_MAX_STUNDEN"] = "3"
        os.environ["GPU_MIETE_DECKEL_EUR"] = "1"          # 1 EUR / (0,60 $ * 0,92) = ca. 1,8 h
        self.assertAlmostEqual(gpu_miete.pruefen_start(), 1 / (0.6 * 0.92) * 3600, delta=1)

    def test_nur_im_nachtfenster_oder_auf_befehl(self):
        for stunde, minute, erlaubt in ((2, 59, False), (3, 0, True), (8, 59, True), (9, 0, False), (14, 0, False)):
            self.uhr.zeit = NACHTS.replace(hour=stunde, minute=minute)
            if erlaubt:
                gpu_miete.pruefen_start()
            else:
                with self.assertRaises(gpu_miete.GpuMieteGesperrt, msg=f"{stunde}:{minute}"):
                    gpu_miete.pruefen_start()
                gpu_miete.pruefen_start(ausdruecklich=True)               # Befehl von Sir geht immer
        os.environ["GPU_MIETE_VON"], os.environ["GPU_MIETE_BIS"] = "22:00", "02:00"   # Fenster über Mitternacht
        self.uhr.zeit = NACHTS.replace(hour=23)
        gpu_miete.pruefen_start()
        self.uhr.zeit = NACHTS.replace(hour=12)
        with self.assertRaises(gpu_miete.GpuMieteGesperrt):
            gpu_miete.pruefen_start()

    def test_tagsueber_ohne_befehl_wird_nichts_angefasst(self):
        self.uhr.zeit = NACHTS.replace(hour=15)
        with self.assertRaises(gpu_miete.GpuMieteGesperrt):
            self.mieten()
        self.assertEqual((self.api.erstellt, self.api.loesch_aufrufe), ([], []))

    def test_volume_pflicht(self):
        del os.environ["GPU_MIETE_VOLUME_ID"]
        with self.assertRaises(gpu_miete.GpuMieteGesperrt) as ctx:
            self.mieten()
        self.assertIn("GPU_MIETE_VOLUME_ID", str(ctx.exception))

    def test_ausschalter(self):
        os.environ["GPU_MIETE_AUS"] = "1"
        self.assertFalse(gpu_miete.ist_aktiv())
        with self.assertRaises(gpu_miete.GpuMieteGesperrt):
            self.mieten()

    def test_nur_eine_miete_gleichzeitig(self):
        def aufgabe(s):
            with self.assertRaises(gpu_miete.GpuMieteGesperrt) as ctx:
                self.mieten()
            self.assertIn("läuft schon", str(ctx.exception))

        self.mieten(aufgabe)
        self.assertEqual(self.api.n, 1)


class Kostendeckel(GpuTest):
    def buche(self, eur: float, zeit: datetime.datetime):
        pid = f"alt{int(eur * 100)}{zeit.month:02d}"
        gpu_miete._anhaengen({"ereignis": "start", "id": pid, "name": "auron-gpu-alt", "zeit": zeit.isoformat(),  # noqa: SLF001
                              "preis_usd_h": 0.4})
        gpu_miete._anhaengen({"ereignis": "ende", "id": pid, "name": "auron-gpu-alt", "zeit": zeit.isoformat(),  # noqa: SLF001
                              "dauer_s": 3600, "kosten_eur": eur, "status": "geloescht"})

    def test_deckel_erreicht_sperrt_bis_monatswechsel(self):
        self.buche(25.0, NACHTS - datetime.timedelta(days=3))
        self.buche(15.0, NACHTS - datetime.timedelta(days=1))
        self.assertAlmostEqual(gpu_miete.verbrauch_eur(), 40.0, places=2)
        with self.assertRaises(gpu_miete.GpuMieteGesperrt) as ctx:
            self.mieten()
        self.assertIn("Deckel erreicht", str(ctx.exception))
        self.assertIn("Monatswechsel", str(ctx.exception))
        self.assertEqual(self.api.erstellt, [])
        t = gpu_miete.kosten_topf()
        self.assertEqual((t["ampel"], t["rest_eur"]), ("rot", 0.0))
        self.assertEqual(ampel._gpu_miete()["farbe"], "gelb")   # noqa: SLF001 - kein Alarm, aber gesperrt
        self.assertIn("Deckel erreicht", ampel._gpu_miete()["text"])  # noqa: SLF001
        # neuer Monat: wieder frei
        self.uhr.zeit = datetime.datetime(2026, 11, 2, 4, 0, tzinfo=ZONE)
        self.assertAlmostEqual(gpu_miete.verbrauch_eur(), 0.0)
        self.mieten()

    def test_vormonat_zaehlt_nicht(self):
        self.buche(39.0, datetime.datetime(2026, 9, 28, 4, 0, tzinfo=ZONE))
        self.assertEqual(gpu_miete.verbrauch_eur(), 0.0)
        self.mieten()

    def test_deckel_ist_einstellbar_und_zu_knapp_zaehlt_als_erreicht(self):
        os.environ["GPU_MIETE_DECKEL_EUR"] = "100"
        self.buche(60.0, NACHTS - datetime.timedelta(days=1))
        gpu_miete.pruefen_start()
        self.buche(39.9, NACHTS - datetime.timedelta(hours=5))     # Rest 0,10 EUR: keine 20 Minuten Laufzeit
        with self.assertRaises(gpu_miete.GpuMieteGesperrt) as ctx:
            gpu_miete.pruefen_start()
        self.assertIn("zu knapp", str(ctx.exception))

    def test_preis_aus_der_api_wird_benutzt(self):
        self.api.preis = "0.80"

        def aufgabe(s):
            self.uhr.vergehen(3600)

        self.mieten(aufgabe)
        self.assertAlmostEqual(gpu_miete.verbrauch_eur(), 0.8 * 0.92, places=3)

    def test_ohne_preis_von_der_api_gilt_die_annahme(self):
        self.api.preis = None

        def aufgabe(s):
            self.uhr.vergehen(3600)

        self.mieten(aufgabe)
        self.assertAlmostEqual(gpu_miete.verbrauch_eur(), 0.6 * 0.92, places=3)

    def test_anzeige_in_kosten_chat_und_hinweis_auf_volume(self):
        u = kosten.uebersicht(NACHTS.date(), [])
        self.assertEqual(u["gpu"]["rahmen_eur"], 40.0)
        zeilen = kosten.deckel_zeilen(u)
        self.assertEqual(len(zeilen), 3)
        self.assertIn("GPU-Miete: 0,00 von 40 EUR", zeilen[2])
        self.assertIn("Network Volume", zeilen[2])
        self.assertIn("GPU-Miete", kosten.chat_text(u))
        os.environ["GPU_MIETE_VOLUME_GB"] = "50"
        self.assertIn("ca. 3.22 EUR im Monat bei 50 GB", gpu_miete.volume_hinweis())
        del os.environ["RUNPOD_API_KEY"]                          # ohne Schlüssel keine dritte Zeile
        self.assertEqual(len(kosten.deckel_zeilen(kosten.uebersicht(NACHTS.date(), []))), 2)
        self.assertEqual(ampel._gpu_miete()["farbe"], "grau")     # noqa: SLF001


class Waechter(GpuTest):
    def name_von_vor(self, stunden: float) -> str:
        z = (self.uhr.zeit - datetime.timedelta(hours=stunden)).astimezone(datetime.timezone.utc)
        return f"auron-gpu-{z.strftime('%Y%m%dT%H%M%S')}Z-ab12"

    def test_loescht_zu_alten_eigenen_pod_und_laesst_jungen_in_ruhe(self):
        alt = self.api.fremd(self.name_von_vor(3.5))
        jung = self.api.fremd(self.name_von_vor(0.5))
        erg = gpu_miete.waechter_lauf(self.api)
        self.assertEqual([g["id"] for g in erg["geloescht"]], [alt])
        self.assertIn("min (erlaubt 180 min)", erg["geloescht"][0]["grund"])
        self.assertEqual(list(self.api.pods), [jung])
        self.assertTrue(erg["ok"])
        self.assertIn("GPU-Wächter hat Pod", self.fehlerbericht_texte())

    def test_maximaldauer_einstellbar(self):
        os.environ["GPU_MIETE_MAX_STUNDEN"] = "1"
        pid = self.api.fremd(self.name_von_vor(1.5))
        self.assertEqual([g["id"] for g in gpu_miete.waechter_lauf(self.api)["geloescht"]], [pid])

    def test_alter_aus_lastStartedAt_und_journal(self):
        a = self.api.fremd("auron-gpu-ohnezeit", lastStartedAt="2026-10-17 00:00:00.000 +0000 UTC")  # 02:00 vor jetzt(02:00Z)? -> 0 h
        b = self.api.fremd("auron-gpu-ohnezeit2", lastStartedAt="2026-10-16 20:00:00.000 +0000 UTC")  # 6 h alt
        erg = gpu_miete.waechter_lauf(self.api)
        self.assertEqual([g["id"] for g in erg["geloescht"]], [b])
        self.assertIn(a, self.api.pods)

    def test_alter_unbekannt_wird_geloescht(self):
        pid = self.api.fremd("auron-gpu-ohnezeit")
        erg = gpu_miete.waechter_lauf(self.api)
        self.assertEqual(erg["geloescht"][0]["grund"], "Alter unbekannt")
        self.assertNotIn(pid, self.api.pods)

    def test_fremde_pods_werden_geloescht_ausser_abgeschaltet(self):
        pid = self.api.fremd("mein-eigener-test-pod")
        erg = gpu_miete.waechter_lauf(self.api)
        self.assertEqual(erg["geloescht"][0]["grund"], "nicht von Auron gestartet")
        self.assertNotIn(pid, self.api.pods)
        pid = self.api.fremd("mein-eigener-test-pod")
        os.environ["GPU_MIETE_FREMDE_LOESCHEN"] = "nein"
        self.assertEqual(gpu_miete.waechter_lauf(self.api)["geloescht"], [])
        self.assertIn(pid, self.api.pods)

    def test_nur_gestoppter_eigener_pod_wird_geloescht(self):
        pid = self.api.fremd(self.name_von_vor(0.2), status="EXITED")
        erg = gpu_miete.waechter_lauf(self.api)
        self.assertIn("exited", erg["geloescht"][0]["grund"])
        self.assertNotIn(pid, self.api.pods)

    def test_beendete_pods_werden_ignoriert(self):
        self.api.fremd("irgendwer", status="TERMINATED")
        erg = gpu_miete.waechter_lauf(self.api)
        self.assertEqual((erg["geprueft"], erg["geloescht"], self.api.loesch_aufrufe), (0, [], []))

    def test_pod_im_journal_wird_auch_ohne_namenspraefix_erkannt(self):
        pid = self.api.fremd("umbenannt")
        gpu_miete._anhaengen({"ereignis": "start", "id": pid, "name": "x", "preis_usd_h": 0.4,  # noqa: SLF001
                              "zeit": (self.uhr.zeit - datetime.timedelta(hours=4)).isoformat()})
        erg = gpu_miete.waechter_lauf(self.api)
        self.assertIn("min (erlaubt", erg["geloescht"][0]["grund"])
        self.assertEqual(gpu_miete.aktive_pods(), {})
        self.assertAlmostEqual(gpu_miete.verbrauch_eur(), 4 * 0.4 * 0.92, places=2)   # Kosten gebucht

    def test_loeschen_schlaegt_fehl_alarm(self):
        self.api.fremd(self.name_von_vor(5))
        self.api.loeschen_fehlt = float("inf")
        erg = gpu_miete.waechter_lauf(self.api)
        self.assertFalse(erg["ok"])
        self.assertIsNotNone(gpu_miete.alarm_lesen())
        self.assertEqual(ampel._gpu_miete()["farbe"], "rot")   # noqa: SLF001

    def test_runpod_nicht_abfragbar(self):
        self.api.liste_fehler = gpu_miete.RunpodFehler("RunPod GET /pods: HTTP 503")
        erg = gpu_miete.waechter_lauf(self.api)
        self.assertFalse(erg["ok"])
        self.assertIsNone(gpu_miete.alarm_lesen())             # nichts bekannt, was läuft: nur Fehlerbericht
        self.assertIn("nicht abfragbar", self.fehlerbericht_texte())
        gpu_miete._anhaengen({"ereignis": "start", "id": "pod9", "name": "x", "zeit": self.uhr.zeit.isoformat(),  # noqa: SLF001
                              "preis_usd_h": 0.4})
        gpu_miete.waechter_lauf(self.api)
        self.assertIn("pod9", gpu_miete.alarm_lesen()["pods"])  # Journal kennt einen laufenden Pod: laut

    def test_journal_pod_der_bei_runpod_fehlt_wird_abgeschlossen(self):
        gpu_miete._anhaengen({"ereignis": "start", "id": "pod9", "name": "x", "preis_usd_h": 0.4,  # noqa: SLF001
                              "zeit": (self.uhr.zeit - datetime.timedelta(minutes=30)).isoformat()})
        gpu_miete.waechter_lauf(self.api)
        self.assertEqual(gpu_miete.aktive_pods(), {})
        # ein ganz frischer Eintrag (Liste kann hinterherhinken) wird nicht vorschnell abgeschlossen
        gpu_miete._anhaengen({"ereignis": "start", "id": "pod8", "name": "x", "preis_usd_h": 0.4,  # noqa: SLF001
                              "zeit": self.uhr.zeit.isoformat()})
        gpu_miete.waechter_lauf(self.api)
        self.assertIn("pod8", gpu_miete.aktive_pods())

    def test_waechter_arbeitet_auch_bei_gpu_miete_aus(self):
        os.environ["GPU_MIETE_AUS"] = "1"
        self.api.fremd(self.name_von_vor(9))
        self.assertEqual(len(gpu_miete.waechter_lauf(self.api)["geloescht"]), 1)

    def test_start_pruefung_beim_backend_start(self):
        with mock.patch.object(gpu_miete, "waechter_lauf", return_value={"geloescht": [], "ok": True, "fehler": []}) as w, \
                mock.patch.object(gpu_miete.threading, "Thread") as t:
            t.side_effect = lambda target, **kw: SimpleNamespace(start=target)
            gpu_miete.start_pruefung()
        w.assert_called_once()
        del os.environ["RUNPOD_API_KEY"]
        with mock.patch.object(gpu_miete.threading, "Thread") as t:
            gpu_miete.start_pruefung()
        t.assert_not_called()

    def test_cli_ohne_schluessel_tut_nichts(self):
        del os.environ["RUNPOD_API_KEY"]
        import importlib
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        try:
            waechter = importlib.import_module("gpu_waechter")
        finally:
            sys.path.pop(0)
        self.assertEqual(waechter.main(), 0)


class Stub(BaseHTTPRequestHandler):
    """Ersatz-RunPod auf 127.0.0.1. Antworten pro (Methode, Pfad) in `antworten`."""
    antworten: dict = {}
    anfragen: list = []

    def log_message(self, *a):
        pass

    def _tun(self):
        laenge = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(laenge).decode() if laenge else ""
        Stub.anfragen.append({"methode": self.command, "pfad": self.path, "auth": self.headers.get("Authorization"),
                              "body": json.loads(body) if body else None})
        code, daten = Stub.antworten.get((self.command, self.path), (404, {"error": "not found"}))
        roh = b"" if daten is None else json.dumps(daten).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    do_GET = do_POST = do_DELETE = _tun


class EchteApiKlasse(GpuTest):
    def setUp(self):
        super().setUp()
        Stub.antworten, Stub.anfragen = {}, []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        port = self.server.server_address[1]
        testschutz.stub_freigeben(self, port)
        os.environ["RUNPOD_API_URL"] = f"http://127.0.0.1:{port}"
        self.api_echt = gpu_miete.RunpodApi()

    def test_anfragen_haben_richtiges_format(self):
        Stub.antworten[("POST", "/pods")] = (201, {"id": "abc123def", "costPerHr": 0.4, "desiredStatus": "RUNNING"})
        Stub.antworten[("GET", "/pods")] = (200, [{"id": "abc123def", "name": "x", "desiredStatus": "RUNNING"}])
        Stub.antworten[("GET", "/pods/abc123def")] = (200, {"id": "abc123def"})
        Stub.antworten[("DELETE", "/pods/abc123def")] = (204, None)
        body = gpu_miete.pod_body("auron-gpu-test")
        self.assertEqual(self.api_echt.erstellen(body)["id"], "abc123def")
        self.assertEqual(self.api_echt.liste()[0]["id"], "abc123def")
        self.assertEqual(self.api_echt.holen("abc123def")["id"], "abc123def")
        self.assertIsNone(self.api_echt.loeschen("abc123def"))
        self.assertEqual([(a["methode"], a["pfad"]) for a in Stub.anfragen],
                         [("POST", "/pods"), ("GET", "/pods"), ("GET", "/pods/abc123def"), ("DELETE", "/pods/abc123def")])
        self.assertTrue(all(a["auth"] == f"Bearer {SCHLUESSEL}" for a in Stub.anfragen))
        self.assertEqual(Stub.anfragen[0]["body"]["name"], "auron-gpu-test")
        self.assertNotIn(SCHLUESSEL, json.dumps(Stub.anfragen[0]["body"]))   # der Schlüssel steht nur im Header

    def test_404_beim_loeschen_und_holen_gilt_als_weg(self):
        self.assertIsNone(self.api_echt.loeschen("abc123def"))
        self.assertIsNone(self.api_echt.holen("abc123def"))

    def test_fehlerantwort_ohne_schluessel_im_text(self):
        Stub.antworten[("GET", "/pods")] = (500, {"error": f"intern, Schlüssel war {SCHLUESSEL}"})
        with self.assertRaises(gpu_miete.RunpodFehler) as ctx:
            self.api_echt.liste()
        self.assertEqual(ctx.exception.status, 500)
        self.assertNotIn("TESTSCHLUESSEL", str(ctx.exception))
        Stub.antworten[("GET", "/pods")] = (401, {"error": "unauthorized"})
        with self.assertRaises(gpu_miete.RunpodFehler) as ctx:
            self.api_echt.liste()
        self.assertIn("Schlüssel abgelehnt", str(ctx.exception))

    def test_ungueltige_pod_id_wird_nicht_in_den_pfad_gesetzt(self):
        for schlecht in ("../abc", "a/b", "", "x" * 100, "abc def"):
            with self.assertRaises(gpu_miete.RunpodFehler):
                self.api_echt.loeschen(schlecht)
        self.assertEqual(Stub.anfragen, [])

    def test_ohne_stub_freigabe_im_testmodus_gesperrt(self):
        os.environ["RUNPOD_API_URL"] = "http://127.0.0.1:9"          # Port nicht freigegeben
        with self.assertRaises(testschutz.geraeteschutz.GeraetGesperrt):
            gpu_miete.RunpodApi().liste()

    def test_ohne_schluessel_kein_aufruf(self):
        del os.environ["RUNPOD_API_KEY"]
        with self.assertRaises(gpu_miete.GpuMieteGesperrt):
            self.api_echt.liste()
        self.assertEqual(Stub.anfragen, [])


class OllamaStub(BaseHTTPRequestHandler):
    anfragen: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        laenge = int(self.headers.get("Content-Length") or 0)
        OllamaStub.anfragen.append(json.loads(self.rfile.read(laenge).decode()))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for stueck in ({"message": {"content": "<think>hm</think>Hallo "}, "done": False},
                       {"message": {"content": "Welt"}, "done": False},
                       {"message": {"content": ""}, "done": True, "done_reason": "stop",
                        "prompt_eval_count": 12, "eval_count": 7}):
            self.wfile.write((json.dumps(stueck) + "\n").encode())
            self.wfile.flush()


class ProviderZielExklusiv(unittest.TestCase):
    def test_nur_im_block_nur_nachts_nur_in_diesem_thread(self):
        vorher = provider.ziele(False)
        with provider.ziel_exklusiv("Pod", "http://127.0.0.1:1/", "m:1b", lese_zeit=99, stream=True, num_ctx=4096):
            z = provider.ziele(False)
            self.assertEqual(z, [{"name": "Pod", "url": "http://127.0.0.1:1", "modell": "m:1b",
                                  "lese_zeit": "99", "stream": "1", "num_ctx": "4096"}])
            self.assertEqual(provider.ziele(True), vorher if False else provider.ziele(True))   # Tagbetrieb unberührt
            self.assertNotEqual(provider.ziele(True)[0]["name"], "Pod")
            anderer = []
            t = threading.Thread(target=lambda: anderer.append(provider.ziele(False)))
            t.start()
            t.join()
            self.assertEqual(anderer[0], vorher)                  # anderer Thread sieht den Pod nicht
        self.assertEqual(provider.ziele(False), vorher)

    def test_ziel_wird_auch_nach_fehler_zurueckgesetzt(self):
        vorher = provider.ziele(False)
        with self.assertRaises(ValueError):
            with provider.ziel_exklusiv("Pod", "http://127.0.0.1:1", "m"):
                raise ValueError()
        self.assertEqual(provider.ziele(False), vorher)

    def test_antwort_wird_gestreamt_und_zusammengesetzt(self):
        OllamaStub.anfragen = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), OllamaStub)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        with provider.ziel_exklusiv("Pod", f"http://127.0.0.1:{port}", MODELL, lese_zeit=30, stream=True, num_ctx=32768):
            msg = provider.OllamaClient(tag=False).messages.create(
                model="egal", max_tokens=100, system="s", messages=[{"role": "user", "content": "hi"}])
        self.assertEqual(msg.content[0].text, "Hallo Welt")            # <think> entfernt, Teile zusammengesetzt
        self.assertEqual((msg.usage.input_tokens, msg.usage.output_tokens), (12, 7))
        self.assertEqual(msg.stop_reason, "end_turn")
        a = OllamaStub.anfragen[0]
        self.assertTrue(a["stream"])
        self.assertEqual(a["model"], MODELL)
        self.assertEqual(a["options"]["num_ctx"], 32768)
        self.assertEqual(a["options"]["num_predict"], 100)
        self.assertFalse(a["think"])


# ---------------------------------------------------------------- Einbau in die Nachtaufträge

def _ki_antwort(text: str):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text, citations=None)],
                           usage=SimpleNamespace(input_tokens=100, output_tokens=50), stop_reason="end_turn")


class ErsatzKi(provider.OllamaClient):
    """Lokaler Ersatz-Client (nacht_ki.ist_lokal erkennt ihn). Merkt sich, wohin die Anfragen gegangen wären."""

    def __init__(self, ziele_log: list):
        super().__init__(tag=False)
        self.ziele_log = ziele_log
        self.messages = self

    def create(self, **kw):
        self.ziele_log.append(provider.ziele(False)[0]["name"])
        if "strenge Prüfer" in str(kw.get("system")):
            return _ki_antwort('{"urteil": "gut", "punkte": [], "zusammenfassung": "ok"}')
        return _ki_antwort("TITEL: Skript\nDATEI: a.py\n```python\nprint(1)\n```")


class NachtUmgebung(GpuTest):
    def setUp(self):
        super().setUp()
        self.vault = os.path.join(self.tmp, "vault")
        os.makedirs(self.vault)
        p = mock.patch.dict(os.environ, {
            "NACHTAUFTRAEGE_PATH": os.path.join(self.tmp, "na.json"), "WERKSTATT_PATH": os.path.join(self.tmp, "werkstatt"),
            "VAULT_PATH": self.vault, "USAGE_LOG_PATH": os.path.join(self.tmp, "usage.jsonl"),
            "NACHTARBEIT_LOG_PATH": os.path.join(self.tmp, "nacht.jsonl"),
        })
        p.start()
        self.addCleanup(p.stop)
        self.ziele_log: list[str] = []
        for ziel, name, wert in (
                (nachtauftraege, "_vault_kontext", mock.Mock(return_value="")),
                (nachtauftraege.websuche_lokal, "verfuegbar", mock.Mock(return_value=False)),
                (nachtauftraege, "schluss_fuer", mock.Mock(return_value=None)),
                (nacht_ki, "client", mock.Mock(side_effect=lambda: ErsatzKi(self.ziele_log))),
                (gpu_miete, "RunpodApi", mock.Mock(return_value=self.api))):
            s = mock.patch.object(ziel, name, wert)
            s.start()
            self.addCleanup(s.stop)

    def auftrag(self, art: str):
        return nachtauftraege.anlegen(f"Bitte ein kleines {art}-Ding erledigen", art=art, pruefen=False)


class Nachtlauf(NachtUmgebung):
    def test_code_auftrag_laeuft_auf_der_gpu_andere_nicht(self):
        code = self.auftrag("entwicklung")
        plan = self.auftrag("plan")
        e = nachtauftraege.nacht_abarbeiten(3.0)
        self.assertEqual(nachtauftraege.holen(code["id"])["status"], "fertig")
        self.assertEqual(nachtauftraege.holen(plan["id"])["status"], "fertig")
        self.assertIn("GPU-Miete (NVIDIA A40)", self.ziele_log)          # Code-Auftrag ging an den Pod
        self.assertIn("Ollama", self.ziele_log[-1])                       # danach der normale Rechner für den Plan
        self.assertEqual(self.api.pods, {})                               # Pod war schon vor dem Plan gelöscht
        texte = [z.get("status", "") for z in e["protokoll"]]
        self.assertTrue(any("Pod gelöscht und bestätigt" in t for t in texte))
        self.assertTrue(any("GPU-Miete:" in t for t in texte))
        self.assertEqual(e["ausgegeben_usd"], 0.0)                        # GPU läuft nicht über die Claude-Töpfe
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "werkstatt")))   # Code wie bisher in die Werkstatt

    def test_ohne_schluessel_unveraendert(self):
        del os.environ["RUNPOD_API_KEY"]
        code = self.auftrag("entwicklung")
        e = nachtauftraege.nacht_abarbeiten(3.0)
        self.assertEqual(nachtauftraege.holen(code["id"])["status"], "fertig")
        self.assertEqual(self.api.erstellt, [])
        self.assertFalse(any("GPU" in z.get("status", "") for z in e["protokoll"]))
        self.assertTrue(all("GPU" not in n for n in self.ziele_log))

    def test_tagsueber_laeuft_es_wie_bisher_mit_hinweis(self):
        self.uhr.zeit = NACHTS.replace(hour=14)
        code = self.auftrag("entwicklung")
        e = nachtauftraege.nacht_abarbeiten(3.0)
        self.assertEqual(nachtauftraege.holen(code["id"])["status"], "fertig")
        self.assertEqual(self.api.erstellt, [])
        self.assertTrue(any("GPU-Miete nicht genutzt" in z.get("status", "") for z in e["protokoll"]))

    def test_start_misslingt_code_laeuft_auf_dem_normalen_rechner(self):
        self.api.erstellen_fehler = gpu_miete.RunpodFehler("RunPod POST /pods: HTTP 400: keine GPU frei", 400)
        code = self.auftrag("entwicklung")
        e = nachtauftraege.nacht_abarbeiten(3.0)
        self.assertEqual(nachtauftraege.holen(code["id"])["status"], "fertig")
        self.assertTrue(any("GPU-Miete fehlgeschlagen" in z.get("status", "") for z in e["protokoll"]))
        self.assertNotIn("GPU-Miete (NVIDIA A40)", self.ziele_log)

    def test_loeschen_scheitert_laute_zeile_im_bericht_und_alarm(self):
        self.api.loeschen_fehlt = float("inf")
        code = self.auftrag("entwicklung")
        e = nachtauftraege.nacht_abarbeiten(3.0)
        laut = [z["status"] for z in e["protokoll"] if "ACHTUNG GPU-Miete" in z.get("status", "")]
        self.assertEqual(len(laut), 1)
        self.assertIn("RunPod-Konsole", laut[0])
        self.assertEqual(nachtauftraege.holen(code["id"])["status"], "fertig")   # die Arbeit selbst ist nicht verloren
        self.assertIsNotNone(gpu_miete.alarm_lesen())
        self.assertIn("ACHTUNG GPU-Miete", "\n".join(nachtauftraege.bericht_zeilen(e)))

    def test_deckel_erreicht_wird_laut_im_bericht_und_normal_weitergearbeitet(self):
        os.environ["GPU_MIETE_DECKEL_EUR"] = "1"
        gpu_miete._anhaengen({"ereignis": "start", "id": "alt1", "name": "n", "zeit": NACHTS.isoformat(), "preis_usd_h": 1})  # noqa: SLF001
        gpu_miete._anhaengen({"ereignis": "ende", "id": "alt1", "name": "n", "zeit": NACHTS.isoformat(), "kosten_eur": 5,  # noqa: SLF001
                              "dauer_s": 3600, "status": "geloescht"})
        code = self.auftrag("entwicklung")
        e = nachtauftraege.nacht_abarbeiten(3.0)
        self.assertTrue(any("Deckel erreicht" in z.get("status", "") for z in e["protokoll"]))
        self.assertEqual(self.api.erstellt, [])
        self.assertEqual(nachtauftraege.holen(code["id"])["status"], "fertig")

    def test_ausdruecklicher_befehl_geht_auch_tagsueber_nur_fuer_offene_code_auftraege(self):
        self.uhr.zeit = NACHTS.replace(hour=14)
        code = self.auftrag("entwicklung")
        plan = self.auftrag("plan")
        with self.assertRaises(nachtauftraege.NachtauftragFehler):
            nachtauftraege.gpu_ausdruecklich_pruefen(plan["id"])
        erg = nachtauftraege.gpu_ausdruecklich(code["id"], api=self.api)
        self.assertEqual(nachtauftraege.holen(code["id"])["status"], "fertig")
        self.assertIn("GPU-Miete (NVIDIA A40)", self.ziele_log)
        self.assertEqual(self.api.pods, {})
        self.assertTrue(any("Pod gelöscht" in z.get("status", "") for z in erg["protokoll"]))
        with self.assertRaises(nachtauftraege.NachtauftragFehler):         # schon fertig
            nachtauftraege.gpu_ausdruecklich_pruefen(code["id"])

    def test_gpu_zeit_fast_abgelaufen_beginnt_keinen_neuen_auftrag(self):
        a, b = self.auftrag("entwicklung"), self.auftrag("entwicklung")
        orig = nacht_ki.client.side_effect

        def client():
            self.uhr.vergehen(3 * 3600 - 300)          # nur noch 5 Minuten GPU-Zeit
            return orig()

        with mock.patch.object(nacht_ki, "client", side_effect=client):
            e = nachtauftraege.nacht_abarbeiten(3.0)
        self.assertEqual(nachtauftraege.holen(a["id"])["status"], "offen")
        self.assertEqual(nachtauftraege.holen(b["id"])["status"], "offen")
        self.assertTrue(any("GPU-Zeit fast abgelaufen" in z.get("status", "") for z in e["protokoll"]))
        self.assertEqual(self.api.pods, {})


class Routen(NachtUmgebung):
    """Die drei Adressen unter /api/gpu-miete (direkt aufgerufen, ohne Netz)."""

    def test_status_und_aufraeumen(self):
        from app import routes

        self.assertTrue(routes.gpu_miete_status()["aktiv"])
        self.api.fremd("fremd")
        with mock.patch.object(gpu_miete, "RunpodApi", return_value=self.api):
            erg = routes.gpu_miete_aufraeumen()
        self.assertEqual(len(erg["geloescht"]), 1)

    def test_befehl_prueft_vorher_und_startet_im_hintergrund(self):
        from fastapi import HTTPException

        from app import routes

        plan = self.auftrag("plan")
        code = self.auftrag("entwicklung")
        with self.assertRaises(HTTPException) as ctx:
            routes.gpu_miete_auftrag({"auftrag": plan["id"]})
        self.assertEqual(ctx.exception.status_code, 400)
        with self.assertRaises(HTTPException):
            routes.gpu_miete_auftrag({"auftrag": 999})
        del os.environ["RUNPOD_API_KEY"]
        with self.assertRaises(HTTPException) as ctx:
            routes.gpu_miete_auftrag({"auftrag": code["id"]})
        self.assertIn("aus", ctx.exception.detail)
        os.environ["RUNPOD_API_KEY"] = SCHLUESSEL
        gestartet = []
        with mock.patch.object(threading, "Thread", side_effect=lambda target, **kw: SimpleNamespace(
                start=lambda: gestartet.append(target))):
            antwort = routes.gpu_miete_auftrag({"auftrag": code["id"]})
        self.assertTrue(antwort["gestartet"])
        self.assertEqual(self.api.erstellt, [])          # erst der Hintergrund-Thread mietet
        gestartet[0]()                                    # Thread-Inhalt von Hand ausführen
        self.assertEqual(nachtauftraege.holen(code["id"])["status"], "fertig")
        self.assertEqual(self.api.pods, {})


class RoutenUndBericht(GpuTest):
    def test_fehlerbericht_enthaelt_abschnitt_ohne_schluessel(self):
        text = fehlerbericht.bericht()
        self.assertIn("GPU-Miete (RunPod)", text)
        self.assertNotIn("TESTSCHLUESSEL", text)

    def test_status_ohne_aufruf_bei_runpod(self):
        s = gpu_miete.status()
        self.assertTrue(s["aktiv"])
        self.assertEqual((s["gpu"], s["modell"], s["max_stunden"]), ("NVIDIA A40", MODELL, 3.0))
        self.assertEqual(self.api.liste(), [])
        self.assertEqual(self.api.erstellt, [])


if __name__ == "__main__":
    unittest.main()

"""Tests für den Alexa-Skill "frag Auron" (P19, 12.10.2026).

Ohne Netz: Die Zertifikatskette kommt aus einer eigenen Test-Wurzel (cryptography),
Laden und Wurzelliste werden ersetzt. Alle Auron-Funktionen sind Mocks.
"""

from __future__ import annotations

import base64
import datetime
import json
import os
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app import alexa, alexa_pruefung as ap, handy_zugang as hz

SKILL = "amzn1.ask.skill.test-1234"
KETTE_URL = "https://s3.amazonaws.com/echo.api/echo-api-cert-99.pem"
JETZT = datetime.datetime.now(datetime.timezone.utc)


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _ca(cn: str, schluessel, aussteller=None, aussteller_schluessel=None):
    pub = schluessel.public_key()
    b = (x509.CertificateBuilder().subject_name(_name(cn))
         .issuer_name(aussteller.subject if aussteller else _name(cn))
         .public_key(pub).serial_number(x509.random_serial_number())
         .not_valid_before(JETZT - datetime.timedelta(days=30))
         .not_valid_after(JETZT + datetime.timedelta(days=3650))
         .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
         .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                      data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                      crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
         .add_extension(x509.SubjectKeyIdentifier.from_public_key(pub), critical=False))
    if aussteller:
        b = b.add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(aussteller_schluessel.public_key()),
                            critical=False)
    return b.sign(aussteller_schluessel or schluessel, hashes.SHA256())


def _blatt(san: str, schluessel, aussteller, aussteller_schluessel, von=None, bis=None):
    pub = schluessel.public_key()
    return (x509.CertificateBuilder().subject_name(_name(san)).issuer_name(aussteller.subject)
            .public_key(pub).serial_number(x509.random_serial_number())
            .not_valid_before(von or JETZT - datetime.timedelta(days=1))
            .not_valid_after(bis or JETZT + datetime.timedelta(days=90))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(san)]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=True,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]),
                           critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(pub), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(aussteller_schluessel.public_key()),
                           critical=False)
            .sign(aussteller_schluessel, hashes.SHA256()))


def _pem(*certs) -> bytes:
    return b"".join(c.public_bytes(serialization.Encoding.PEM) for c in certs)


class _Pki:
    """Test-Wurzel -> Zwischenstelle -> Signaturzertifikat (wie bei Amazon)."""

    def __init__(self):
        self.wurzel_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.wurzel = _ca("Test Root", self.wurzel_key)
        self.zw_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.zw = _ca("Test Intermediate", self.zw_key, self.wurzel, self.wurzel_key)
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.blatt = _blatt("echo-api.amazon.com", self.key, self.zw, self.zw_key)

    def kette(self, blatt=None) -> bytes:
        return _pem(blatt or self.blatt, self.zw)

    def signieren(self, text: bytes, key=None) -> str:
        return base64.b64encode((key or self.key).sign(text, padding.PKCS1v15(), hashes.SHA256())).decode()


_PKI = _Pki()


def _anfrage(req: dict, zeit: datetime.datetime | None = None, skill: str = SKILL) -> dict:
    req = {"requestId": "r1", "locale": "de-DE",
           "timestamp": (zeit or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"), **req}
    return {"version": "1.0",
            "session": {"new": True, "application": {"applicationId": skill}, "user": {"userId": "u1"}},
            "context": {"System": {"application": {"applicationId": skill}, "user": {"userId": "u1"}}},
            "request": req}


def _intent(name: str, slots: dict | None = None, bestaetigung: str = "NONE", dialog: str | None = None) -> dict:
    req = {"type": "IntentRequest",
           "intent": {"name": name, "confirmationStatus": bestaetigung,
                      "slots": {k: {"name": k, **v} for k, v in (slots or {}).items()}}}
    if dialog:
        req["dialogState"] = dialog
    return _anfrage(req)


def _sprache(antwort: dict) -> str:
    return antwort["response"].get("outputSpeech", {}).get("text", "")


class _Basis(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ, {"ALEXA_AKTIV": "1", "ALEXA_SKILL_ID": SKILL, "ALEXA_NUTZER_ID": ""})
        p.start()
        self.addCleanup(p.stop)
        for name, wert in (("lader", lambda url: self.kette), ("wurzeln", lambda: [_PKI.wurzel])):
            q = mock.patch.object(ap, name, wert)
            q.start()
            self.addCleanup(q.stop)
        ap._cache.clear()
        self.kette = _PKI.kette()


# ------------------------------------------------------------------ Prüfung

class KetteUrl(unittest.TestCase):
    def test_gueltige_adressen(self):
        for url in ("https://s3.amazonaws.com/echo.api/echo-api-cert.pem",
                    "https://s3.amazonaws.com:443/echo.api/echo-api-cert.pem",
                    "HTTPS://s3.amazonaws.com/echo.api/../echo.api/echo-api-cert.pem",
                    "https://S3.AMAZONAWS.COM/echo.api/x.pem"):
            self.assertTrue(ap.kette_url_pruefen(url).startswith("https://s3.amazonaws.com/echo.api/"), url)

    def test_ungueltige_adressen(self):
        for url in ("http://s3.amazonaws.com/echo.api/echo-api-cert.pem",
                    "https://notamazon.com/echo.api/echo-api-cert.pem",
                    "https://s3.amazonaws.com/EcHo.aPi/echo-api-cert.pem",
                    "https://s3.amazonaws.com/invalid.path/echo-api-cert.pem",
                    "https://s3.amazonaws.com:563/echo.api/echo-api-cert.pem",
                    "https://s3.amazonaws.com/echo.api/../invalid.path/echo-api-cert.pem",
                    "https://s3.amazonaws.com/echo.api/%2e%2e/invalid/x.pem",
                    "", None):
            with self.assertRaises(ap.AlexaAbgelehnt, msg=url):
                ap.kette_url_pruefen(url)


class Signatur(_Basis):
    def _kopf(self, text: bytes, **anders) -> dict:
        kopf = {"SignatureCertChainUrl": KETTE_URL, "Signature-256": _PKI.signieren(text)}
        kopf.update(anders)
        return kopf

    def test_gueltig(self):
        text = b'{"a": 1}'
        ap.signatur_pruefen(self._kopf(text), text)

    def test_veraenderter_text(self):
        text = b'{"a": 1}'
        with self.assertRaises(ap.AlexaAbgelehnt):
            ap.signatur_pruefen(self._kopf(text), b'{"a": 2}')

    def test_fehlende_kopfzeilen(self):
        text = b"{}"
        for kopf in ({"SignatureCertChainUrl": KETTE_URL}, {"Signature-256": _PKI.signieren(text)},
                     {"SignatureCertChainUrl": KETTE_URL, "Signature-256": "kein base64 !!"}):
            with self.assertRaises(ap.AlexaAbgelehnt):
                ap.signatur_pruefen(kopf, text)

    def test_fremder_schluessel(self):
        text = b"{}"
        fremd = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with self.assertRaises(ap.AlexaAbgelehnt):
            ap.signatur_pruefen(self._kopf(text, **{"Signature-256": _PKI.signieren(text, fremd)}), text)

    def test_abgelaufenes_zertifikat(self):
        alt = _blatt("echo-api.amazon.com", _PKI.key, _PKI.zw, _PKI.zw_key,
                     von=JETZT - datetime.timedelta(days=100), bis=JETZT - datetime.timedelta(days=1))
        self.kette = _PKI.kette(alt)
        with self.assertRaises(ap.AlexaAbgelehnt):
            ap.signatur_pruefen(self._kopf(b"{}"), b"{}")

    def test_falscher_san(self):
        self.kette = _PKI.kette(_blatt("evil.example.com", _PKI.key, _PKI.zw, _PKI.zw_key))
        with self.assertRaises(ap.AlexaAbgelehnt):
            ap.signatur_pruefen(self._kopf(b"{}"), b"{}")

    def test_fremde_wurzel(self):
        fremd = _Pki()
        self.kette = fremd.kette()
        text = b"{}"
        with self.assertRaises(ap.AlexaAbgelehnt):
            ap.signatur_pruefen({"SignatureCertChainUrl": KETTE_URL, "Signature-256": fremd.signieren(text)}, text)

    def test_kette_nicht_ladbar(self):
        def kaputt(url):
            raise OSError("kein Netz")
        with mock.patch.object(ap, "lader", kaputt):
            with self.assertRaises(ap.AlexaAbgelehnt):
                ap.signatur_pruefen(self._kopf(b"{}"), b"{}")

    def test_kette_wird_zwischengespeichert(self):
        aufrufe = []
        with mock.patch.object(ap, "lader", lambda url: aufrufe.append(url) or self.kette):
            ap.signatur_pruefen(self._kopf(b"{}"), b"{}")
            ap.signatur_pruefen(self._kopf(b"{}"), b"{}")
        self.assertEqual(len(aufrufe), 1)


class Inhalt(_Basis):
    def test_gueltig(self):
        ap.inhalt_pruefen(_anfrage({"type": "LaunchRequest"}))

    def test_zeitstempel(self):
        jetzt = datetime.datetime.now(datetime.timezone.utc)
        ap.inhalt_pruefen(_anfrage({"type": "LaunchRequest"}, jetzt - datetime.timedelta(seconds=140)))
        for abstand in (-151, 151, 3600):
            with self.assertRaises(ap.AlexaAbgelehnt, msg=abstand):
                ap.inhalt_pruefen(_anfrage({"type": "LaunchRequest"}, jetzt - datetime.timedelta(seconds=abstand)))

    def test_falsche_skill_id(self):
        with self.assertRaises(ap.AlexaAbgelehnt):
            ap.inhalt_pruefen(_anfrage({"type": "LaunchRequest"}, skill="amzn1.ask.skill.fremd"))

    def test_ohne_skill_id_in_env_alles_zu(self):
        with mock.patch.dict(os.environ, {"ALEXA_SKILL_ID": ""}):
            with self.assertRaises(ap.AlexaAbgelehnt):
                ap.inhalt_pruefen(_anfrage({"type": "LaunchRequest"}, skill=""))

    def test_nutzer_id(self):
        with mock.patch.dict(os.environ, {"ALEXA_NUTZER_ID": "u1"}):
            ap.inhalt_pruefen(_anfrage({"type": "LaunchRequest"}))
        with mock.patch.dict(os.environ, {"ALEXA_NUTZER_ID": "jemand-anders"}):
            with self.assertRaises(ap.AlexaAbgelehnt):
                ap.inhalt_pruefen(_anfrage({"type": "LaunchRequest"}))

    def test_kein_alexa_format(self):
        for roh in ([], {}, {"request": "x"}, {"request": {"timestamp": "gestern"}}):
            with self.assertRaises(ap.AlexaAbgelehnt):
                ap.inhalt_pruefen(roh)


# ------------------------------------------------------------------ Route und Zugang

class Route(_Basis):
    def setUp(self):
        super().setUp()
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.routes import router

        app = FastAPI()
        app.middleware("http")(hz.middleware)
        app.include_router(router)
        # Absender wie über Funnel aus dem Internet (kein Tailnet, kein Code)
        self.client = TestClient(app, client=("203.0.113.7", 40000))
        q = mock.patch.dict(os.environ, {"JARVIS_HANDY_TOKEN": "abc123xyz789"})
        q.start()
        self.addCleanup(q.stop)

    def _senden(self, anfrage: dict, signieren: bool = True):
        text = json.dumps(anfrage).encode()
        kopf = {"Content-Type": "application/json", "SignatureCertChainUrl": KETTE_URL}
        if signieren:
            kopf["Signature-256"] = _PKI.signieren(text)
        return self.client.post("/api/alexa", content=text, headers=kopf)

    def test_launch(self):
        r = self._senden(_anfrage({"type": "LaunchRequest"}))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(_sprache(r.json()), "Auron hört, Sir.")
        self.assertFalse(r.json()["response"]["shouldEndSession"])

    def test_ohne_signatur_400(self):
        self.assertEqual(self._senden(_anfrage({"type": "LaunchRequest"}), signieren=False).status_code, 400)

    def test_falsche_skill_id_400(self):
        self.assertEqual(self._senden(_anfrage({"type": "LaunchRequest"}, skill="fremd")).status_code, 400)

    def test_kein_json_400(self):
        text = b"kein json"
        r = self.client.post("/api/alexa", content=text,
                             headers={"SignatureCertChainUrl": KETTE_URL, "Signature-256": _PKI.signieren(text)})
        self.assertEqual(r.status_code, 400)

    def test_zu_gross_400(self):
        r = self.client.post("/api/alexa", content=b"x" * (70 * 1024))
        self.assertEqual(r.status_code, 400)

    def test_ohne_alexa_aktiv_404(self):
        with mock.patch.dict(os.environ, {"ALEXA_AKTIV": ""}):
            self.assertEqual(self._senden(_anfrage({"type": "LaunchRequest"})).status_code, 404)

    def test_andere_pfade_bleiben_zu(self):
        self.assertIn(self.client.get("/api/alexa").status_code, (401, 403))
        self.assertIn(self.client.post("/api/alexa/x").status_code, (401, 403))
        self.assertIn(self.client.post("/api/chat", json={"message": "x"}).status_code, (401, 403))
        self.assertIn(self.client.get("/api/briefing").status_code, (401, 403))


class Zugang(unittest.TestCase):
    def test_nur_post_auf_genau_den_pfad(self):
        with mock.patch.dict(os.environ, {"JARVIS_HANDY_TOKEN": "abc123xyz789"}):
            r = hz.pruefen("203.0.113.7", "POST", "/api/alexa", None, None)
            self.assertTrue(r["erlaubt"])
            self.assertEqual(r["geraet_schluessel"], "")
            for methode, pfad in (("GET", "/api/alexa"), ("POST", "/api/alexa/"), ("POST", "/api/alexax"),
                                  ("POST", "/api/alexa/../reindex"), ("PUT", "/api/alexa")):
                self.assertFalse(hz.pruefen("203.0.113.7", methode, pfad, None, None)["erlaubt"], (methode, pfad))


# ------------------------------------------------------------------ Sprache

class Sprache(unittest.TestCase):
    def test_markdown_und_quellen_weg(self):
        t, gekuerzt = alexa.fuer_sprache("## Plan\n- **Dach** neu [1]\n- Fenster [2, 3] siehe [Link](https://x.de)")
        self.assertEqual(t, "Plan. Dach neu. Fenster siehe Link.")
        self.assertFalse(gekuerzt)

    def test_kuerzt_an_satzgrenze(self):
        text = " ".join(f"Das ist Satz Nummer {i} mit etwas Inhalt." for i in range(20))
        t, gekuerzt = alexa.fuer_sprache(text)
        self.assertTrue(gekuerzt)
        self.assertLessEqual(len(t), alexa.SPRACH_MAX_ZEICHEN)
        self.assertTrue(t.endswith("."))
        self.assertTrue(text.startswith(t))

    def test_erster_satz_bleibt_ganz(self):
        satz = "Ein sehr langer Satz " + "mit vielen Wörtern " * 30 + "endet hier."
        t, _ = alexa.fuer_sprache(satz + " Noch ein Satz.")
        self.assertEqual(t, satz)

    def test_antwortformat(self):
        a = alexa.antwort("Hallo, Sir.", "Karte")
        self.assertEqual(a["version"], "1.0")
        self.assertEqual(a["response"]["card"]["type"], "Simple")
        self.assertTrue(a["response"]["shouldEndSession"])


# ------------------------------------------------------------------ Intents

class Intents(unittest.TestCase):
    def test_vault_frage_lokal(self):
        r = SimpleNamespace(answer="Das Dach wird im Mai neu gedeckt [1], Sir.", used_vault=True,
                            sources=[SimpleNamespace(file_path="Projekte/Gartenhaus.md", heading_path="")],
                            ki={"quelle": "lokal"})
        with mock.patch("app.chat_service.ask", return_value=r) as ask:
            a = alexa.verarbeiten(_intent("VaultFrageIntent", {"frage": {"value": "dem gartenhaus"}}))
        self.assertEqual(ask.call_args.kwargs["laenge"], "sprache")
        self.assertEqual(ask.call_args.kwargs["log_modus"], "alexa")
        self.assertEqual(ask.call_args.kwargs["mode"], "klassisch")
        self.assertEqual(_sprache(a), "Das Dach wird im Mai neu gedeckt, Sir. Quelle: Gartenhaus.")
        self.assertIn("Quellen: Gartenhaus", a["response"]["card"]["content"])
        self.assertNotIn("Claude", a["response"]["card"]["content"])

    def test_vault_frage_claude_in_karte(self):
        r = SimpleNamespace(answer="Antwort, Sir.", used_vault=True,
                            sources=[SimpleNamespace(file_path="A.md", heading_path="")], ki={"quelle": "claude"})
        with mock.patch("app.chat_service.ask", return_value=r):
            a = alexa.verarbeiten(_intent("VaultFrageIntent", {"frage": {"value": "x"}}))
        self.assertIn("Claude", a["response"]["card"]["content"])

    def test_vault_frage_nichts_gefunden(self):
        r = SimpleNamespace(answer="Erfunden", used_vault=False, sources=[], ki={})
        with mock.patch("app.chat_service.ask", return_value=r):
            a = alexa.verarbeiten(_intent("VaultFrageIntent", {"frage": {"value": "x"}}))
        self.assertEqual(_sprache(a), "Dazu steht nichts im Vault, Sir.")

    def test_vault_frage_rahmen_erschoepft(self):
        with mock.patch("app.chat_service.ask", side_effect=RuntimeError("Der Monatsrahmen ist aufgebraucht, Sir")):
            a = alexa.verarbeiten(_intent("VaultFrageIntent", {"frage": {"value": "x"}}))
        self.assertIn("Monatsrahmen", _sprache(a))

    def test_vault_frage_ohne_text_fragt_nach(self):
        a = alexa.verarbeiten(_intent("VaultFrageIntent", {"frage": {}}))
        self.assertFalse(a["response"]["shouldEndSession"])

    def test_zeitbudget_und_letzte_antwort(self):
        def langsam(*a, **k):
            time.sleep(0.4)
            return SimpleNamespace(answer="Spät, aber da, Sir.", used_vault=True, sources=[], ki={})
        with mock.patch.object(alexa, "ZEITBUDGET_S", 0.05), mock.patch("app.chat_service.ask", side_effect=langsam):
            a = alexa.verarbeiten(_intent("VaultFrageIntent", {"frage": {"value": "x"}}))
            self.assertIn("dauert etwas länger", _sprache(a))
            pfad = Path(os.environ["ALEXA_LETZTE_PATH"])
            frist = time.time() + 5
            while time.time() < frist and "Spät" not in (pfad.read_text(encoding="utf-8") if pfad.exists() else ""):
                time.sleep(0.05)
        b = alexa.verarbeiten(_intent("LetzteAntwortIntent"))
        self.assertEqual(_sprache(b), "Spät, aber da, Sir.")

    def test_briefing_drei_punkte(self):
        text = "Guten Morgen, Sir.\n\n- Termin um 10 Uhr\n- Nachtarbeit fertig\n- Zwei Mails\n- Vierter Punkt"
        with mock.patch("app.briefing.hole", return_value={"text": text}):
            a = alexa.verarbeiten(_intent("BriefingIntent"))
        s = _sprache(a)
        self.assertTrue(s.startswith("Sir, Termin um 10 Uhr."))
        self.assertNotIn("Vierter", s)
        self.assertIn("Alexa-App", s)
        self.assertEqual(a["response"]["card"]["content"], text)

    def test_status(self):
        with mock.patch("app.nachtarbeit.is_running", return_value=False), \
             mock.patch("app.nachtarbeit.letzte_nacht",
                        return_value={"datum": "2026-10-12", "status": "durchgefuehrt", "kosten_usd": 0.0}), \
             mock.patch("app.kosten.uebersicht",
                        return_value={"ausgegeben_usd": 3.1, "rahmen_usd": 20.0, "anteil_prozent": 15.5}):
            a = alexa.verarbeiten(_intent("StatusIntent"))
        s = _sprache(a)
        self.assertIn("Die Nachtarbeit ruht.", s)
        self.assertIn("12.10.: durchgeführt", s)
        self.assertIn("3,10 von 20 Dollar", s)

    def test_termine(self):
        text = "Morgen haben Sie 4 Termine, Sir:\n\n- 09:00 Uhr: A\n- 10:00 Uhr: B\n- 11:00 Uhr: C\n- 12:00 Uhr: D"
        with mock.patch("app.termine.antwort_zeitraum", return_value=text) as az, \
             mock.patch("app.alltag.jetzt", return_value=datetime.datetime(2026, 10, 12, 9, 0)):
            a = alexa.verarbeiten(_intent("TermineIntent", {"tag": {"value": "2026-10-13"}}))
        self.assertEqual(az.call_args.args[:3], (datetime.date(2026, 10, 13), datetime.date(2026, 10, 13), "morgen"))
        self.assertEqual(_sprache(a), "Morgen haben Sie 4 Termine, Sir: 09:00 Uhr: A; 10:00 Uhr: B; 11:00 Uhr: C, "
                                      "und 1 weitere.")

    def test_zeitraum(self):
        heute = datetime.date(2026, 10, 12)
        self.assertEqual(alexa._zeitraum("", heute), (heute, heute, "heute"))
        self.assertEqual(alexa._zeitraum("2026-W42", heute)[:2], (datetime.date(2026, 10, 12), datetime.date(2026, 10, 18)))
        self.assertEqual(alexa._zeitraum("2026-W42-WE", heute)[:2], (datetime.date(2026, 10, 17), datetime.date(2026, 10, 18)))
        self.assertEqual(alexa._zeitraum("2026-11", heute)[:2], (datetime.date(2026, 11, 1), datetime.date(2026, 11, 30)))
        self.assertEqual(alexa._zeitraum("unsinn", heute), (heute, heute, "heute"))

    def test_merken_nur_nach_ja(self):
        with mock.patch("app.vorschlaege.anlegen", return_value={"id": "v1", "ziel": "Wissen/00 - Eingang/G.md"}) as an, \
             mock.patch("app.vorschlaege.uebernehmen") as ue:
            offen = alexa.verarbeiten(_intent("MerkenIntent", {"notiz": {"value": "milch kaufen"}}))
            nein = alexa.verarbeiten(_intent("MerkenIntent", {"notiz": {"value": "milch kaufen"}}, "DENIED"))
            an.assert_not_called()
            ja = alexa.verarbeiten(_intent("MerkenIntent", {"notiz": {"value": "milch kaufen"}}, "CONFIRMED"))
        self.assertEqual(offen["response"]["directives"], [{"type": "Dialog.Delegate"}])
        self.assertIn("Nichts geändert", _sprache(nein))
        an.assert_called_once_with("milch kaufen", quelle="alexa", grund="Alexa: Merk dir")
        ue.assert_called_once_with("v1")
        self.assertEqual(_sprache(ja), "Gemerkt, Sir.")

    def test_dialog_laeuft_noch(self):
        a = alexa.verarbeiten(_intent("MerkenIntent", {"notiz": {}}, dialog="STARTED"))
        self.assertEqual(a["response"]["directives"], [{"type": "Dialog.Delegate"}])

    def test_nachtauftrag(self):
        with mock.patch("app.nachtauftraege.anlegen", return_value={"id": 17}) as an:
            a = alexa.verarbeiten(_intent("NachtauftragIntent", {"auftrag": {"value": "solar recherche"}}, "CONFIRMED"))
        an.assert_called_once_with("solar recherche", quelle="alexa", pruefen=False)
        self.assertEqual(_sprache(a), "Auftrag 17 für die Nacht notiert, Sir.")

    def test_nachtauftrag_fehler_vorlesen(self):
        from app import nachtauftraege

        with mock.patch("app.nachtauftraege.anlegen", side_effect=nachtauftraege.NachtauftragFehler("Zu kurz, Sir.")):
            a = alexa.verarbeiten(_intent("NachtauftragIntent", {"auftrag": {"value": "x"}}, "CONFIRMED"))
        self.assertEqual(_sprache(a), "Zu kurz, Sir.")

    def test_unbekannter_intent_und_stop(self):
        self.assertIn("nicht", _sprache(alexa.verarbeiten(_intent("LoeschAllesIntent"))))
        self.assertEqual(_sprache(alexa.verarbeiten(_intent("AMAZON.StopIntent"))), "In Ordnung, Sir.")

    def test_fehler_wird_gesprochen_und_gemeldet(self):
        with mock.patch("app.kosten.uebersicht", side_effect=KeyError("kaputt")), \
             mock.patch("app.nachtarbeit.is_running", return_value=False), \
             mock.patch("app.nachtarbeit.letzte_nacht", return_value=None), \
             mock.patch("app.fehlerbericht.merken") as fb:
            a = alexa.verarbeiten(_intent("StatusIntent"))
        self.assertEqual(_sprache(a), alexa.FEHLER_SATZ)
        fb.assert_called_once()

    def test_protokoll_ohne_inhalt(self):
        pfad = Path(os.environ["ALEXA_LOG_PATH"])
        with mock.patch("app.vorschlaege.anlegen", return_value={"id": "v1", "ziel": "x.md"}), \
             mock.patch("app.vorschlaege.uebernehmen"):
            alexa.verarbeiten(_intent("MerkenIntent", {"notiz": {"value": "geheimer gedanke"}}, "CONFIRMED"))
        letzte = json.loads(pfad.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(letzte["intent"], "MerkenIntent")
        self.assertNotIn("geheim", pfad.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ Whitelist

def _aktion(aid: str | None, roh: str = "x", bestaetigung: str = "CONFIRMED") -> dict:
    slot = {"value": roh}
    if aid:
        slot["resolutions"] = {"resolutionsPerAuthority": [
            {"authority": "amzn1.er-authority.echo-sdk.test.AURON_AKTION", "status": {"code": "ER_SUCCESS_MATCH"},
             "values": [{"value": {"name": roh, "id": aid}}]}]}
    return _intent("AktionIntent", {"aktion": slot}, bestaetigung)


class Whitelist(unittest.TestCase):
    def test_whitelist_passt_zum_modell(self):
        modell = json.loads((Path(__file__).resolve().parents[1] / "alexa" / "interaktionsmodell_de.json")
                            .read_text(encoding="utf-8"))
        typen = {t["name"]: t for t in modell["interactionModel"]["languageModel"]["types"]}
        ids = {v["id"] for v in typen["AURON_AKTION"]["values"]}
        self.assertEqual(ids, set(alexa.ALEXA_AKTIONEN))
        aktiv = {k for k, v in alexa.ALEXA_AKTIONEN.items() if v["aktiv"]}
        self.assertEqual(aktiv, set(alexa._AUSFUEHRUNG))

    def test_nachtarbeit_starten(self):
        with mock.patch("app.nachtarbeit.start", return_value=(True, {})) as st:
            a = alexa.verarbeiten(_aktion("nachtarbeit_starten", "nachtarbeit"))
        st.assert_called_once()
        self.assertEqual(_sprache(a), "Die Nachtarbeit startet, Sir.")

    def test_laeuft_bereits(self):
        with mock.patch("app.reindex_service.start", return_value=(False, {})) as st:
            a = alexa.verarbeiten(_aktion("vault_einlesen", "vault neu einlesen"))
        st.assert_called_once_with(full=False)
        self.assertIn("läuft bereits", _sprache(a))

    def test_ohne_ja_nichts(self):
        with mock.patch("app.nachtarbeit.start") as st:
            alexa.verarbeiten(_aktion("nachtarbeit_starten", bestaetigung="NONE"))
            alexa.verarbeiten(_aktion("nachtarbeit_starten", bestaetigung="DENIED"))
        st.assert_not_called()

    def test_unbekannt_rohtext_und_inaktiv(self):
        with mock.patch("app.nachtarbeit.start") as st, mock.patch("app.reindex_service.start") as rs:
            a = alexa.verarbeiten(_aktion(None, "nachtarbeit_starten"))     # nur Rohtext, keine ID
            b = alexa.verarbeiten(_aktion("alles_loeschen", "alles löschen"))
            c = alexa.verarbeiten(_aktion("pruefen_hintergrund", "prüflauf"))
        st.assert_not_called()
        rs.assert_not_called()
        self.assertIn("kenne ich nicht", _sprache(a))
        self.assertIn("kenne ich nicht", _sprache(b))
        self.assertIn("noch nicht", _sprache(c))



class EchteAmazonKette(unittest.TestCase):
    """Echte (abgelaufene) Amazon-Kette echo-api-cert-12.pem, am 12.10.2026 von
    s3.amazonaws.com/echo.api/ geladen. Prüft, dass cryptography die Amazon-Kette mit den
    certifi-Wurzeln anerkennt - zum Zeitpunkt, als sie gültig war. Ohne Netz."""

    def test_amazon_kette_wird_anerkannt(self):
        pem = (Path(__file__).parent / "daten" / "alexa_echo_api_kette_2023.pem").read_bytes()
        certs = ap._zertifikate(pem)
        damals = datetime.datetime(2023, 6, 1, tzinfo=datetime.timezone.utc)
        blatt = ap.kette_pruefen(certs, damals)
        self.assertIn("echo-api.amazon.com", blatt.subject.rfc4514_string())
        with self.assertRaises(ap.AlexaAbgelehnt):
            ap.kette_pruefen(certs, JETZT)      # heute abgelaufen



class Diagnose(_Basis):
    """12.10.2026: Protokoll-Zusatz für die Fehlersuche am Echo (ohne Inhalte)."""

    def _letzte_zeile(self) -> dict:
        return json.loads(Path(os.environ["ALEXA_LOG_PATH"]).read_text(encoding="utf-8").splitlines()[-1])

    def test_diagnose_felder(self):
        anfrage = _intent("VaultFrageIntent", {"frage": {}})
        anfrage["context"]["Viewport"] = {"shape": "RECTANGLE"}
        alexa.verarbeiten(anfrage, pruef_ms=42)
        z = self._letzte_zeile()
        self.assertEqual(z["typ"], "IntentRequest")
        self.assertEqual(z["pruef_ms"], 42)
        self.assertTrue(z["bildschirm"])
        self.assertEqual(z["slots_leer"], ["frage"])
        self.assertFalse(z["dauert"])

    def test_zeitbudget_im_protokoll(self):
        def langsam(*a, **k):
            time.sleep(0.3)
            return SimpleNamespace(answer="x, Sir.", used_vault=True, sources=[], ki={})
        with mock.patch.object(alexa, "ZEITBUDGET_S", 0.05), mock.patch("app.chat_service.ask", side_effect=langsam):
            alexa.verarbeiten(_intent("VaultFrageIntent", {"frage": {"value": "geheim"}}))
        z = self._letzte_zeile()
        self.assertTrue(z["dauert"])
        self.assertFalse(z["bildschirm"])
        self.assertNotIn("geheim", json.dumps(z))
        time.sleep(0.4)  # Hintergrund-Arbeit fertig werden lassen

    def test_ablehnung_nur_mit_alexa_kopfzeile(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.routes import router

        app = FastAPI()
        app.include_router(router)
        c = TestClient(app)
        pfad = Path(os.environ["ALEXA_LOG_PATH"])
        vorher = len(pfad.read_text(encoding="utf-8").splitlines()) if pfad.exists() else 0
        c.post("/api/alexa", content=b"{}")                                          # Fremder ohne Kopfzeile
        self.assertEqual(len(pfad.read_text(encoding="utf-8").splitlines()) if pfad.exists() else 0, vorher)
        c.post("/api/alexa", content=b"{}", headers={"SignatureCertChainUrl": KETTE_URL})  # sieht aus wie Alexa
        z = self._letzte_zeile()
        self.assertEqual(z["ergebnis"], "abgelehnt")
        self.assertIn("Signature-256", z["grund"])

    def test_fehlerbericht_abschnitt(self):
        from app import fehlerbericht

        alexa.verarbeiten(_intent("AMAZON.StopIntent"))
        text = "\n".join(fehlerbericht._alexa())
        self.assertIn("AMAZON.StopIntent", text)
        self.assertIn("| Zeit | Intent |", text)


if __name__ == "__main__":
    unittest.main()

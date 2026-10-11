"""Tests für app/finanzen.py (11.10.2026). Nur erfundene Beispiel-Umsätze, ohne Netz, ohne KI.

Beispiel-CSVs: tests/daten/finanzen/ (Formate genau nach Vault-Notiz P03). Den Statuswert für offene Revolut-
Buchungen nennt P03 nicht ("AUSSTEHEND" ist erfunden) - der Code wertet nur STORNIERT und das leere
"Datum des Abschlusses" aus."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import finanzen

DATEN = Path(__file__).resolve().parent / "daten" / "finanzen"
VB = (DATEN / "volksbank_beispiel.csv").read_bytes()
RV = (DATEN / "revolut_beispiel.csv").read_bytes()
HEUTE = dt.date(2026, 10, 11)


def _u(datum, betrag, empfaenger, gl="", mandat="", intern=False, waehrung="EUR"):
    return {"datum": datum, "betrag": betrag, "empfaenger": empfaenger, "zweck": "", "glaeubiger_id": gl,
            "mandatsreferenz": mandat, "intern": intern, "waehrung": waehrung, "konto": "Test", "bank": "volksbank"}


class Umgebung(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="finanzen_"))
        self.p = mock.patch.dict(os.environ, {"FINANZEN_PATH": str(self.tmp / "finanzen"),
                                              "ABLAGE_PATH": str(self.tmp / "ablage")})
        self.p.start()
        self.eingang = finanzen.ordner() / "eingang"
        self.p_heute = mock.patch.object(finanzen, "_heute", return_value=HEUTE)
        self.p_heute.start()

    def tearDown(self):
        self.p_heute.stop()
        self.p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class Erkennen(unittest.TestCase):
    def test_beide_banken(self):
        self.assertEqual(finanzen.erkennen(VB), "volksbank")
        self.assertEqual(finanzen.erkennen(RV), "revolut")

    def test_unbekannt_nennt_die_ersten_spalten(self):
        with self.assertRaises(finanzen.FinanzFehler) as e:
            finanzen.erkennen("Datum;Empfänger;Betrag;Saldo\n01.01.2026;X;-1,00;5\n".encode("utf-8"))
        self.assertIn("Unbekanntes Format", str(e.exception))
        self.assertIn("Datum, Empfänger, Betrag, Saldo", str(e.exception))

    def test_excel_kopie_mit_kaputten_umlauten(self):
        kaputt = "Art,Produkt,Datum des Beginns,Datum des Abschlusses,Beschreibung,Betrag,GebÃ¼hr,WÃ¤hrung,Status,Kontostand\n"
        with self.assertRaises(finanzen.FinanzFehler) as e:
            finanzen.erkennen(kaputt.encode("utf-8"))
        self.assertIn("Excel", str(e.exception))

    def test_kein_utf8(self):
        with self.assertRaises(finanzen.FinanzFehler) as e:
            finanzen.erkennen("Art;Gebühr\n".encode("cp1252"))
        self.assertIn("UTF-8", str(e.exception))

    def test_leer(self):
        with self.assertRaises(finanzen.FinanzFehler):
            finanzen.erkennen(b"")


class Lesen(unittest.TestCase):
    def test_volksbank(self):
        bank, u, kaputt = finanzen.lesen(VB)
        self.assertEqual((bank, len(u), kaputt), ("volksbank", 15, 0))
        gehalt = next(x for x in u if x["empfaenger"].startswith("Arbeitgeber"))
        self.assertEqual(gehalt["betrag"], 2100.0)            # Tausenderpunkt und Komma
        netflix = next(x for x in u if x["glaeubiger_id"])
        self.assertEqual((netflix["datum"], netflix["betrag"], netflix["mandatsreferenz"]), ("2026-07-01", -13.99, "M-TEST-0001"))
        self.assertTrue(next(x for x in u if x["empfaenger"].startswith("Revolut"))["intern"])
        self.assertNotIn("DE000000000", json.dumps(u))        # keine IBANs gespeichert

    def test_revolut(self):
        bank, u, kaputt = finanzen.lesen(RV)
        self.assertEqual((bank, kaputt), ("revolut", 0))
        self.assertFalse(any(x["empfaenger"].startswith("Kino") for x in u))      # STORNIERT
        self.assertEqual(next(x for x in u if x["empfaenger"].startswith("Geldautomat"))["betrag"], -51.0)  # Gebühr
        self.assertTrue(next(x for x in u if x["empfaenger"].startswith("Restaurant"))["offen"])
        self.assertTrue(next(x for x in u if x["art"] == "Einzahlung")["intern"])
        self.assertTrue(next(x for x in u if x["art"] == "Zinsen")["intern"])      # Sparkonto
        baecker = [x["schluessel"] for x in u if x["empfaenger"].startswith("Baeckerei")]
        self.assertEqual(len(baecker), 2)                       # zwei echte Käufe bleiben zwei
        self.assertEqual(len(set(baecker)), 2)

    def test_kaputte_zeile_wird_gezaehlt(self):
        roh = VB.decode("utf-8-sig").splitlines()
        roh.append(roh[1].replace("01.07.2026", "kein Datum"))
        _, u, kaputt = finanzen.lesen("\n".join(roh).encode("utf-8"))
        self.assertEqual((len(u), kaputt), (15, 1))


class Einlesen(Umgebung):
    def test_einlesen_verschieben_und_dubletten(self):
        (self.eingang / "vb.csv").write_bytes(VB)
        (self.eingang / "rv.csv").write_bytes(RV)
        e = finanzen.einlesen()
        self.assertEqual(e["neu"], 15 + 10)
        self.assertEqual(list(self.eingang.iterdir()), [])
        self.assertEqual(len(list((finanzen.ordner() / "eingelesen").iterdir())), 2)
        (self.eingang / "vb_nochmal.csv").write_bytes(VB)       # gleicher Export noch einmal
        e2 = finanzen.einlesen()
        self.assertEqual((e2["neu"], e2["doppelt"]), (0, 15))
        self.assertEqual(len(finanzen.laden()), 25)

    def test_unbekannt_und_xlsx_bleiben_liegen(self):
        (self.eingang / "fremd.csv").write_bytes(b"Datum,Wert\n1,2\n")
        (self.eingang / "auszug.xlsx").write_bytes(b"PK\x03\x04")
        e = finanzen.einlesen()
        self.assertEqual(e["neu"], 0)
        self.assertEqual(sorted(p.name for p in self.eingang.iterdir()), ["auszug.xlsx", "fremd.csv"])
        text = " ".join(e["meldungen"])
        self.assertIn("Erste Spalten: Datum, Wert", text)
        self.assertIn("Nur CSV", text)

    def test_ablage_nur_bankdateien(self):
        ablage = Path(os.environ["ABLAGE_PATH"])
        ablage.mkdir(parents=True)
        (ablage / "kontoauszug.csv").write_bytes(VB)
        (ablage / "DAX.csv").write_bytes(b"Datum,Kurs\n")
        e = finanzen.einlesen()
        self.assertEqual(e["neu"], 15)
        self.assertEqual([p.name for p in ablage.iterdir()], ["DAX.csv"])    # fremde CSV still liegen gelassen
        self.assertEqual(e["meldungen"], [])

    def test_offene_buchung_wird_abgeschlossen(self):
        roh = RV.decode("utf-8")
        (self.eingang / "a.csv").write_text(roh, encoding="utf-8")
        finanzen.einlesen()
        fertig = roh.replace("2026-10-09 19:30:00,,", "2026-10-09 19:30:00,2026-10-10 06:00:00,")
        (self.eingang / "b.csv").write_text(fertig, encoding="utf-8")
        finanzen.einlesen()
        r = [u for u in finanzen.laden() if u["empfaenger"].startswith("Restaurant")]
        self.assertEqual(len(r), 1)
        self.assertFalse(r[0]["offen"])

    def test_nichts_landet_auf_der_konsole(self):
        (self.eingang / "vb.csv").write_bytes(VB)
        (self.eingang / "fremd.csv").write_bytes(b"Datum,Wert\n")
        aus = io.StringIO()
        with contextlib.redirect_stdout(aus), contextlib.redirect_stderr(aus):
            finanzen.einlesen()
            finanzen.uebersicht()
        self.assertEqual(aus.getvalue(), "")

    def test_hochladen_nur_csv(self):
        self.assertEqual(finanzen.speichern_eingang("..\\auszug.csv", VB), "auszug.csv")
        self.assertEqual(finanzen.speichern_eingang("auszug.csv", VB), "auszug (2).csv")
        for name in ("auszug.xlsx", "x.bat"):
            with self.assertRaises(finanzen.FinanzFehler):
                finanzen.speichern_eingang(name, VB)


class Abos(unittest.TestCase):
    def test_beispieldaten(self):
        _, vb, _ = finanzen.lesen(VB)
        _, rv, _ = finanzen.lesen(RV)
        a = {x["name"]: x for x in finanzen.abos(vb + rv, HEUTE)}
        self.assertEqual(set(a), {"Streamdienst Beispiel GmbH", "Fitness Beispiel", "Musikdienst Beispiel"})
        s = a["Streamdienst Beispiel GmbH"]
        self.assertEqual((s["rhythmus"], s["pro_monat"], s["pro_jahr"], s["sicher"]),
                         ("monatlich", 13.99, 167.88, "Lastschrift (Gläubiger-ID)"))
        self.assertEqual(s["naechste"], "2026-11-01")
        self.assertTrue(s["aktiv"])
        self.assertEqual(a["Musikdienst Beispiel"]["sicher"], "nach Name")

    def test_jaehrlich_vierteljaehrlich_und_beendet(self):
        u = [_u("2024-11-02", -89.0, "Versicherung X", gl="DE11ZZZ1", mandat="V1"),
             _u("2025-11-03", -92.5, "Versicherung X", gl="DE11ZZZ1", mandat="V1"),
             _u("2026-01-10", -30.0, "Verein"), _u("2026-04-10", -30.0, "Verein"), _u("2026-07-11", -30.0, "Verein"),
             _u("2026-01-05", -9.99, "Altes Abo"), _u("2026-02-05", -9.99, "Altes Abo"), _u("2026-03-05", -9.99, "Altes Abo")]
        a = {x["name"]: x for x in finanzen.abos(u, HEUTE)}
        self.assertEqual((a["Versicherung X"]["rhythmus"], a["Versicherung X"]["sicher"]), ("jährlich", "vermutlich"))
        self.assertEqual(a["Versicherung X"]["pro_monat"], round(92.5 / 12, 2))
        self.assertEqual(a["Verein"]["rhythmus"], "vierteljährlich")
        self.assertFalse(a["Altes Abo"]["aktiv"])

    def test_keine_abos(self):
        u = [_u("2026-08-01", -40.0, "Supermarkt"), _u("2026-08-08", -55.0, "Supermarkt"),   # wöchentlich
             _u("2026-08-15", -12.0, "Supermarkt"), _u("2026-08-22", -80.0, "Supermarkt"),
             _u("2026-07-01", -5.0, "Kiosk"), _u("2026-08-01", -48.0, "Kiosk"), _u("2026-09-01", -19.0, "Kiosk"),
             _u("2026-07-01", -200.0, "Revolut", intern=True), _u("2026-08-01", -200.0, "Revolut", intern=True),
             _u("2026-09-01", -200.0, "Revolut", intern=True),
             _u("2026-07-03", -9.0, "Ausland", waehrung="USD"), _u("2026-08-03", -9.0, "Ausland", waehrung="USD"),
             _u("2026-09-03", -9.0, "Ausland", waehrung="USD")]
        self.assertEqual(finanzen.abos(u, HEUTE), [])

    def test_preiserhoehung_bleibt_ein_abo(self):
        u = [_u("2026-06-01", -12.99, "Streamdienst"), _u("2026-07-01", -12.99, "Streamdienst"),
             _u("2026-08-01", -13.99, "Streamdienst"), _u("2026-09-01", -13.99, "Streamdienst")]
        a = finanzen.abos(u, HEUTE)
        self.assertEqual((len(a), a[0]["betrag"]), (1, 13.99))


class Auswertung(Umgebung):
    def test_monate_ohne_umbuchungen(self):
        (self.eingang / "vb.csv").write_bytes(VB)
        (self.eingang / "rv.csv").write_bytes(RV)
        finanzen.einlesen()
        okt = finanzen.monate(heute=HEUTE)[0]
        # Oktober: 13,99 + 29,90 (Volksbank) + 10,99 + 2x3,50 + 51,00 + 24,80 (Revolut); ohne 200 € an Revolut
        self.assertEqual(okt["monat"], "2026-10")
        self.assertEqual(okt["ausgaben"], round(13.99 + 29.90 + 10.99 + 7.0 + 51.0 + 24.80, 2))
        self.assertEqual(okt["einnahmen"], 2100.0)
        u = finanzen.uebersicht()
        self.assertEqual(u["anzahl_umsaetze"], 25)
        self.assertEqual(u["abos_pro_monat"], round(13.99 + 29.90 + 10.99, 2))
        self.assertEqual(u["eingang_wartet"], 0)

    def test_kuendigung(self):
        (self.eingang / "vb.csv").write_bytes(VB)
        finanzen.einlesen()
        abo = next(a for a in finanzen.abos() if a["mandatsreferenz"])
        k = finanzen.kuendigung(abo["id"])
        self.assertIn("Mandatsreferenz M-TEST-0001", k["text"])
        self.assertIn("nächstmöglichen Zeitpunkt", k["text"])
        self.assertIn("01.07.2022", " ".join(k["wege"]))
        self.assertIn("verschickt selbst", k["hinweis"])
        with self.assertRaises(finanzen.FinanzFehler):
            finanzen.kuendigung("gibtsnicht")

    def test_briefing_einmal_im_monat(self):
        t = finanzen.fuer_briefing(HEUTE)
        self.assertIn("Noch keine Umsätze eingelesen", t)
        self.assertIn(finanzen.ERINNERUNG, t)
        self.assertEqual(finanzen.fuer_briefing(HEUTE), "")
        (self.eingang / "vb.csv").write_bytes(VB)
        finanzen.einlesen()
        t = finanzen.fuer_briefing(dt.date(2026, 11, 2))
        self.assertIn("2 Abos, zusammen 43,89 € im Monat", t)

    def test_chat_texte(self):
        self.assertIn("Noch keine Umsätze", finanzen.chat_text("abos"))
        (self.eingang / "vb.csv").write_bytes(VB)
        self.assertIn("15 neue Umsätze", finanzen.chat_text("einlesen"))
        self.assertIn("Fitness Beispiel: 29,90 € monatlich", finanzen.chat_text("abos"))
        self.assertIn("Ausgaben diesen Monat bisher", finanzen.chat_text("monat"))


class Anbindung(Umgebung):
    """Chat-Befehle, Briefing und Adressen (11.10.2026)."""

    def test_chat_befehle_erkannt(self):
        from app import alltag
        f = lambda t: (lambda a: a and (a["art"], a.get("seite") if a["art"] == "hud" else a.get("aktion")))(alltag.absicht(t))  # noqa: E731
        self.assertEqual(f("Welche Abos habe ich?"), ("finanzen", "abos"))
        self.assertEqual(f("Auron, zeig mir meine Abos"), ("finanzen", "abos"))
        self.assertEqual(f("Kontoauszüge einlesen"), ("finanzen", "einlesen"))
        self.assertEqual(f("Lies die neuen Kontoauszüge ein"), ("finanzen", "einlesen"))
        self.assertEqual(f("Was habe ich diesen Monat ausgegeben?"), ("finanzen", "monat"))
        self.assertEqual(f("Zeig mir Finanzen"), ("hud", "finanzen"))
        self.assertEqual(f("Zeig mir den Markt"), ("hud", "markt"))          # alte Befehle unverändert
        self.assertEqual(alltag.absicht("Such im Internet nach Mietpreisen")["art"], "recherche")

    def test_chat_ausfuehrung(self):
        from app import chat_ablauf
        (self.eingang / "vb.csv").write_bytes(VB)
        self.assertIn("15 neue Umsätze", chat_ablauf._neue_art({"art": "finanzen", "aktion": "einlesen"}))  # noqa: SLF001
        self.assertIn("Streamdienst Beispiel GmbH", chat_ablauf._neue_art({"art": "finanzen", "aktion": "abos"}))  # noqa: SLF001

    def test_briefing_haengt_finanzen_an(self):
        from app import briefing, ki_aufruf
        with mock.patch.dict(os.environ, {"BRIEFING_FINANZEN": "1"}), \
                mock.patch.object(briefing, "mails_holen", return_value={"eingerichtet": False, "liste": []}), \
                mock.patch.object(briefing, "_angaben", return_value="Angaben"), \
                mock.patch.object(briefing, "_tagesfrage_zusatz", return_value=""), \
                mock.patch.object(ki_aufruf, "aufrufen", return_value={"text": "Guten Morgen, Sir.", "ki": {}}):
            erst = briefing.erzeugen("morgen")["text"]
            zweit = briefing.erzeugen("morgen")["text"]
        self.assertTrue(erst.startswith("Guten Morgen, Sir."))
        self.assertIn(finanzen.ERINNERUNG, erst)
        self.assertEqual(zweit, "Guten Morgen, Sir.")      # nur einmal im Monat

    def test_briefing_aus(self):
        from app import briefing
        with mock.patch.dict(os.environ, {"BRIEFING_FINANZEN": "0"}):
            self.assertEqual(briefing._finanzen_zusatz(), "")  # noqa: SLF001

    def test_adressen(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app import routes
        app = FastAPI()
        app.include_router(routes.router)
        c = TestClient(app)
        self.assertEqual(c.get("/api/finanzen").json()["anzahl_umsaetze"], 0)
        r = c.post("/api/finanzen/hochladen?name=auszug.csv", content=VB)
        self.assertEqual((r.status_code, r.json()["neu"], r.json()["gespeichert"]), (200, 15, "auszug.csv"))
        self.assertEqual(c.post("/api/finanzen/hochladen?name=auszug.xlsx", content=VB).status_code, 400)
        self.assertEqual(c.post("/api/finanzen/einlesen").json()["neu"], 0)
        self.assertEqual(len(c.get("/api/finanzen/umsaetze?monat=2026-10").json()), 4)   # Volksbank, Oktober
        self.assertEqual(c.get("/api/finanzen/umsaetze?monat=Oktober").status_code, 400)
        abo = c.get("/api/finanzen").json()["abos"][0]
        self.assertIn("Kündigung", c.get(f"/api/finanzen/kuendigung?abo={abo['id']}").json()["text"])
        self.assertEqual(c.get("/api/finanzen/kuendigung?abo=gibtsnicht").status_code, 404)


if __name__ == "__main__":
    unittest.main()

"""Tests für app/kalender.py - ICS auswerten ohne Netz.

Ausfuehren:
    python -m unittest tests.test_kalender
"""

from __future__ import annotations

import unittest
from unittest import mock
from datetime import datetime, timedelta

from dateutil import tz

from app import kalender

ZONE = kalender.ZEITZONE


def _ics(inhalt: str) -> str:
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + inhalt + "END:VCALENDAR\r\n"


def _stempel(versatz_tage: int, stunde: int = 9, minute: int = 0) -> str:
    d = datetime.now(ZONE) + timedelta(days=versatz_tage)
    return d.replace(hour=stunde, minute=minute, second=0, microsecond=0).strftime("%Y%m%dT%H%M%S")


class IcsZerlegen(unittest.TestCase):
    def test_einzeltermin_mit_ort(self):
        text = _ics(
            "BEGIN:VEVENT\r\nUID:a1\r\n"
            f"DTSTART;TZID=Europe/Berlin:{_stempel(2, 9)}\r\n"
            f"DTEND;TZID=Europe/Berlin:{_stempel(2, 17)}\r\n"
            "SUMMARY:Assessment KHS Ausbildung\r\nLOCATION:KHS GmbH\r\nEND:VEVENT\r\n"
        )
        d = kalender.abrufen(text)
        self.assertEqual(len(d["termine"]), 1)
        self.assertEqual(d["termine"][0]["titel"], "Assessment KHS Ausbildung")
        self.assertEqual(d["termine"][0]["ort"], "KHS GmbH")
        self.assertIn("T09:00", d["termine"][0]["start"])

    def test_gefaltete_zeile_wird_zusammengesetzt(self):
        text = _ics(
            "BEGIN:VEVENT\r\nUID:a2\r\n"
            f"DTSTART;TZID=Europe/Berlin:{_stempel(1)}\r\n"
            "SUMMARY:Ein sehr langer Termin\r\n title der umgebrochen wurde\r\n"
            "END:VEVENT\r\n"
        )
        d = kalender.abrufen(text)
        self.assertEqual(d["termine"][0]["titel"], "Ein sehr langer Termintitle der umgebrochen wurde")

    def test_ganztaegiger_termin(self):
        tag = (datetime.now(ZONE) + timedelta(days=10)).strftime("%Y%m%d")
        text = _ics(
            "BEGIN:VEVENT\r\nUID:a3\r\n"
            f"DTSTART;VALUE=DATE:{tag}\r\n"
            "SUMMARY:Fiona Geburtstag\r\nEND:VEVENT\r\n"
        )
        d = kalender.abrufen(text)
        self.assertEqual(d["termine"][0]["start"], f"{tag[:4]}-{tag[4:6]}-{tag[6:]}")

    def test_utc_wird_nach_berlin_umgerechnet(self):
        d = datetime.now(tz.UTC) + timedelta(days=3)
        roh = d.replace(hour=6, minute=0, second=0, microsecond=0)
        text = _ics(
            "BEGIN:VEVENT\r\nUID:a4\r\n"
            f"DTSTART:{roh.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            "SUMMARY:UTC-Termin\r\nEND:VEVENT\r\n"
        )
        erwartet = roh.astimezone(ZONE).strftime("%H:%M")
        self.assertIn(erwartet, kalender.abrufen(text)["termine"][0]["start"])

    def test_vtimezone_block_wird_uebersprungen(self):
        text = _ics(
            "BEGIN:VTIMEZONE\r\nTZID:Europe/Berlin\r\nBEGIN:DAYLIGHT\r\n"
            "DTSTART:19700329T020000\r\nEND:DAYLIGHT\r\nEND:VTIMEZONE\r\n"
            "BEGIN:VEVENT\r\nUID:a5\r\n"
            f"DTSTART;TZID=Europe/Berlin:{_stempel(1)}\r\nSUMMARY:Echt\r\nEND:VEVENT\r\n"
        )
        d = kalender.abrufen(text)
        self.assertEqual([t["titel"] for t in d["termine"]], ["Echt"])


class Wiederholungen(unittest.TestCase):
    def test_woechentliche_serie_wird_ausgerollt(self):
        text = _ics(
            "BEGIN:VEVENT\r\nUID:b1\r\n"
            f"DTSTART;TZID=Europe/Berlin:{_stempel(1, 7)}\r\n"
            f"DTEND;TZID=Europe/Berlin:{_stempel(1, 17, 30)}\r\n"
            "RRULE:FREQ=WEEKLY;COUNT=6\r\nSUMMARY:Arbeit\r\nEND:VEVENT\r\n"
        )
        d = kalender.abrufen(text)
        self.assertEqual(len(d["termine"]), 6)
        self.assertTrue(all(t["titel"] == "Arbeit" for t in d["termine"]))
        self.assertTrue(all(t["ende"].endswith("17:30") for t in d["termine"]))

    def test_exdate_faellt_weg(self):
        start = _stempel(1, 7)
        zweiter = (datetime.strptime(start, "%Y%m%dT%H%M%S") + timedelta(days=7)).strftime("%Y%m%dT%H%M%S")
        text = _ics(
            "BEGIN:VEVENT\r\nUID:b2\r\n"
            f"DTSTART;TZID=Europe/Berlin:{start}\r\n"
            "RRULE:FREQ=WEEKLY;COUNT=3\r\n"
            f"EXDATE;TZID=Europe/Berlin:{zweiter}\r\n"
            "SUMMARY:Arbeit\r\nEND:VEVENT\r\n"
        )
        self.assertEqual(len(kalender.abrufen(text)["termine"]), 2)

    def test_einzeln_geaenderter_termin_steht_nicht_doppelt(self):
        start = _stempel(1, 7)
        zweiter_dt = datetime.strptime(start, "%Y%m%dT%H%M%S") + timedelta(days=7)
        zweiter = zweiter_dt.strftime("%Y%m%dT%H%M%S")
        verschoben = zweiter_dt.replace(hour=10).strftime("%Y%m%dT%H%M%S")
        text = _ics(
            "BEGIN:VEVENT\r\nUID:b3\r\n"
            f"DTSTART;TZID=Europe/Berlin:{start}\r\n"
            "RRULE:FREQ=WEEKLY;COUNT=3\r\nSUMMARY:Arbeit\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:b3\r\n"
            f"RECURRENCE-ID;TZID=Europe/Berlin:{zweiter}\r\n"
            f"DTSTART;TZID=Europe/Berlin:{verschoben}\r\n"
            "SUMMARY:Arbeit (spaeter)\r\nEND:VEVENT\r\n"
        )
        d = kalender.abrufen(text)
        self.assertEqual(len(d["termine"]), 3)
        self.assertEqual(sum(1 for t in d["termine"] if t["titel"] == "Arbeit (spaeter)"), 1)

    def test_abgesagter_termin_faellt_weg(self):
        text = _ics(
            "BEGIN:VEVENT\r\nUID:b4\r\n"
            f"DTSTART;TZID=Europe/Berlin:{_stempel(1)}\r\n"
            "STATUS:CANCELLED\r\nSUMMARY:Abgesagt\r\nEND:VEVENT\r\n"
        )
        self.assertEqual(kalender.abrufen(text)["termine"], [])

    def test_kaputte_regel_kippt_den_rest_nicht(self):
        text = _ics(
            "BEGIN:VEVENT\r\nUID:c1\r\n"
            f"DTSTART;TZID=Europe/Berlin:{_stempel(1)}\r\n"
            "RRULE:FREQ=UNSINN\r\nSUMMARY:Kaputt\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:c2\r\n"
            f"DTSTART;TZID=Europe/Berlin:{_stempel(2)}\r\nSUMMARY:Heil\r\nEND:VEVENT\r\n"
        )
        self.assertEqual([t["titel"] for t in kalender.abrufen(text)["termine"]], ["Heil"])


class Zeitfenster(unittest.TestCase):
    def test_weit_entfernte_termine_fallen_weg(self):
        text = _ics(
            "BEGIN:VEVENT\r\nUID:d1\r\n"
            f"DTSTART;TZID=Europe/Berlin:{_stempel(400)}\r\nSUMMARY:Weit weg\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:d2\r\n"
            f"DTSTART;TZID=Europe/Berlin:{_stempel(-90)}\r\nSUMMARY:Lange her\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:d3\r\n"
            f"DTSTART;TZID=Europe/Berlin:{_stempel(5)}\r\nSUMMARY:Passt\r\nEND:VEVENT\r\n"
        )
        self.assertEqual([t["titel"] for t in kalender.abrufen(text)["termine"]], ["Passt"])

    def test_sortierung_nach_startzeit(self):
        text = _ics(
            "BEGIN:VEVENT\r\nUID:e1\r\n"
            f"DTSTART;TZID=Europe/Berlin:{_stempel(9)}\r\nSUMMARY:Spaeter\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:e2\r\n"
            f"DTSTART;TZID=Europe/Berlin:{_stempel(2)}\r\nSUMMARY:Frueher\r\nEND:VEVENT\r\n"
        )
        self.assertEqual([t["titel"] for t in kalender.abrufen(text)["termine"]], ["Frueher", "Spaeter"])


class Konfiguration(unittest.TestCase):
    def test_ohne_adresse_klare_meldung(self):
        alt = kalender.os.environ.pop("KALENDER_ICS_URL", None)
        try:
            with self.assertRaises(kalender.KalenderFehler):
                kalender.abrufen()
        finally:
            if alt is not None:
                kalender.os.environ["KALENDER_ICS_URL"] = alt

    def test_adresse_taucht_in_keiner_meldung_auf(self):
        # 11.10.2026: kein echter Abruf mehr (Testschutz) - der Fehler enthält die Adresse, die Meldung nicht
        url = "https://calendar.google.com/calendar/ical/geheim/private-xyz/basic.ics"
        kalender.os.environ["KALENDER_ICS_URL"] = url
        fehler = kalender.requests.ConnectionError(f"Max retries exceeded with url: {url}")
        try:
            with mock.patch.object(kalender.requests, "get", side_effect=fehler), \
                    self.assertRaises(kalender.KalenderFehler) as ctx:
                kalender.abrufen()
            self.assertNotIn("private-xyz", str(ctx.exception))
        finally:
            kalender.os.environ.pop("KALENDER_ICS_URL", None)


if __name__ == "__main__":
    unittest.main()


class Feiertage(unittest.TestCase):
    def test_standardadresse_ist_gesetzt(self):
        alt = kalender.os.environ.pop("FEIERTAGE_ICS_URL", None)
        try:
            self.assertIn("holiday", kalender.feiertage_url())
        finally:
            if alt is not None:
                kalender.os.environ["FEIERTAGE_ICS_URL"] = alt

    def test_abschaltbar(self):
        alt = kalender.os.environ.get("FEIERTAGE_ICS_URL")
        kalender.os.environ["FEIERTAGE_ICS_URL"] = "aus"
        try:
            self.assertEqual(kalender.feiertage_url(), "")
        finally:
            if alt is None:
                kalender.os.environ.pop("FEIERTAGE_ICS_URL", None)
            else:
                kalender.os.environ["FEIERTAGE_ICS_URL"] = alt

    def test_termine_tragen_eine_kategorie(self):
        text = _ics(
            "BEGIN:VEVENT\r\nUID:f1\r\n"
            f"DTSTART;TZID=Europe/Berlin:{_stempel(2)}\r\nSUMMARY:Test\r\nEND:VEVENT\r\n"
        )
        d = kalender.abrufen(text)
        self.assertEqual(d["termine"][0]["kategorie"], "termin")
        self.assertFalse(d["feiertage"])

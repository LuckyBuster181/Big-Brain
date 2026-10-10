"""Tests für die Spotify-Befehlserkennung (app/spotify.py).

Kein Netz, kein Spotify-Konto nötig - geprüft wird nur die Wortmuster-Logik
und dass ausfuehren() die richtigen Funktionen ruft.

Lauf: python -m unittest tests.test_spotify   (im Ordner backend)
"""

from __future__ import annotations

import unittest
from unittest import mock

from app import sonos, spotify


class TestErkennung(unittest.TestCase):
    def pruefe(self, satz: str, aktion: str, wert=None):
        ergebnis = spotify.erkenne_befehl(satz)
        self.assertIsNotNone(ergebnis, f"nicht erkannt: {satz!r}")
        self.assertEqual(ergebnis["aktion"], aktion, f"falsche Aktion bei {satz!r}")
        if wert is not None:
            self.assertEqual(ergebnis["wert"], wert, f"falscher Wert bei {satz!r}")

    def test_lautstaerke_relativ(self):
        for satz in ["leiser", "Leiser bitte", "mach leiser", "Jarvis, mach mal leiser", "musik leiser", "etwas leiser"]:
            self.pruefe(satz, "leiser")
        for satz in ["lauter", "mach die lauter", "Jarvis mach mal lauter"]:
            self.pruefe(satz, "lauter")

    def test_lautstaerke_absolut(self):
        self.pruefe("Lautstärke 30", "lautstaerke", "30")
        self.pruefe("lautstärke auf 55 %", "lautstaerke", "55")
        self.pruefe("stell die Lautstaerke auf 5", "lautstaerke", "5")
        self.pruefe("mach die musik auf 40", "lautstaerke", "40")

    def test_transport(self):
        for satz in ["stopp", "stop", "Pause", "musik aus", "mach die musik aus"]:
            self.pruefe(satz, "pause")
        for satz in ["weiter", "spiel weiter", "play", "musik an", "fortsetzen"]:
            self.pruefe(satz, "weiter")
        for satz in ["nächstes", "nächstes lied", "naechstes lied", "skip", "lied wechseln", "song weiter"]:
            self.pruefe(satz, "naechstes")
        for satz in ["vorheriges lied", "zurück", "letztes lied"]:
            self.pruefe(satz, "vorheriges")

    def test_was_laeuft(self):
        for satz in ["was läuft", "was läuft gerade?", "welches lied läuft", "was höre ich gerade"]:
            self.pruefe(satz, "was_laeuft")

    def test_zufall(self):
        self.pruefe("shuffle an", "zufall_an")
        self.pruefe("zufall aus", "zufall_aus")

    def test_spielen_mit_suchbegriff(self):
        self.pruefe("spiel Bohemian Rhapsody", "spielen", "bohemian rhapsody")
        self.pruefe("Jarvis, spiel mir mal Rammstein", "spielen", "rammstein")
        self.pruefe("leg mal Daft Punk auf", "spielen", "daft punk")

    def test_kein_befehl(self):
        for satz in ["", "   ", "was steht heute an", "erklär mir RSI", "wie geht es dir"]:
            self.assertIsNone(spotify.erkenne_befehl(satz), f"fälschlich als Befehl erkannt: {satz!r}")

    def test_spiel_weiter_ist_kein_suchbegriff(self):
        """Gefahr: 'spiel weiter' darf nicht als Suche nach 'weiter' enden."""
        self.pruefe("spiel weiter", "weiter")


class TestAusfuehren(unittest.TestCase):
    def test_pause_ruft_pause(self):
        with mock.patch.object(spotify, "pause") as p:
            antwort = spotify.ausfuehren({"aktion": "pause", "wert": None})
        p.assert_called_once()
        self.assertIn("Sir", antwort)

    def test_leiser_senkt_um_schritt(self):
        with mock.patch.object(spotify, "lautstaerke_aendern", return_value=40) as f:
            antwort = spotify.ausfuehren({"aktion": "leiser", "wert": None})
        f.assert_called_once_with(-spotify.LAUTSTAERKE_SCHRITT)
        self.assertIn("40", antwort)

    def test_lautstaerke_absolut(self):
        with mock.patch.object(spotify, "lautstaerke_setzen", return_value=30) as f:
            spotify.ausfuehren({"aktion": "lautstaerke", "wert": "30"})
        f.assert_called_once_with(30)

    def test_spielen_gibt_titel_zurueck(self):
        with mock.patch.object(
            spotify, "suchen_und_spielen", return_value={"art": "titel", "titel": "Enter Sandman", "kuenstler": "Metallica"}
        ):
            antwort = spotify.ausfuehren({"aktion": "spielen", "wert": "enter sandman"})
        self.assertIn("Enter Sandman", antwort)
        self.assertIn("Metallica", antwort)

    def test_was_laeuft_ohne_musik(self):
        with mock.patch.object(spotify, "laeuft_gerade", return_value={"spielt": False}):
            antwort = spotify.ausfuehren({"aktion": "was_laeuft", "wert": None})
        self.assertIn("nichts", antwort.lower())

    def test_unbekannte_aktion_wirft(self):
        with self.assertRaises(spotify.SpotifyFehler):
            spotify.ausfuehren({"aktion": "quatsch", "wert": None})


class TestEinrichtung(unittest.TestCase):
    def test_nicht_eingerichtet_ohne_env(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(spotify.ist_eingerichtet())
            self.assertFalse(spotify.stand()["eingerichtet"])

    def test_login_url_enthaelt_rechte(self):
        with mock.patch.dict("os.environ", {"SPOTIFY_CLIENT_ID": "abc"}, clear=True):
            url = spotify.login_url()
        self.assertIn("client_id=abc", url)
        self.assertIn("user-modify-playback-state", url)

    def test_login_url_ohne_id_wirft(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(spotify.SpotifyFehler):
                spotify.login_url()


class TestSonos(unittest.TestCase):
    BOXEN = [{"name": "Schlafzimmer", "ip": "192.168.1.40"}, {"name": "Wohnzimmer", "ip": "192.168.1.41"}]

    def test_findet_exakten_namen(self):
        with mock.patch.object(sonos, "boxen", return_value=self.BOXEN):
            self.assertEqual(sonos.finde("Schlafzimmer")["ip"], "192.168.1.40")
            self.assertEqual(sonos.finde("wohnzimmer")["ip"], "192.168.1.41")

    def test_findet_gruppe(self):
        """Spotify nennt Gruppen oft 'Schlafzimmer + 1'."""
        with mock.patch.object(sonos, "boxen", return_value=self.BOXEN):
            self.assertEqual(sonos.finde("Schlafzimmer + 1")["ip"], "192.168.1.40")

    def test_unbekanntes_geraet(self):
        with mock.patch.object(sonos, "boxen", return_value=self.BOXEN):
            self.assertIsNone(sonos.finde("Handy von Max"))
            self.assertIsNone(sonos.finde(""))

    def test_feste_ips_aus_env(self):
        with mock.patch.dict("os.environ", {"SONOS_IPS": "192.168.1.40, 192.168.1.41"}, clear=True):
            self.assertEqual(sonos._feste_ips(), ["192.168.1.40", "192.168.1.41"])
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(sonos._feste_ips(), [])


class TestLautstaerkeUeberSonos(unittest.TestCase):
    def setUp(self):
        # Der Namens-Zwischenspeicher darf nicht von Test zu Test lecken.
        spotify._name_cache = ("", 0.0)

    PAAR = [{"name": "Schlafzimmer", "ip": "10.0.0.5"}, {"name": "Schlafzimmer", "ip": "10.0.0.6"}]

    def test_leiser_regelt_beide_boxen(self):
        """Stereopaar: ein Befehl darf nicht nur eine Box treffen."""
        with mock.patch.object(spotify, "_geraetename", return_value="Schlafzimmer"), \
             mock.patch.object(spotify.sonos, "alle_mit_namen", return_value=self.PAAR), \
             mock.patch.object(spotify.sonos, "lautstaerke_lesen", return_value=40), \
             mock.patch.object(spotify.sonos, "lautstaerke_setzen_alle", return_value=30) as setzen:
            self.assertEqual(spotify.lautstaerke_aendern(-10), 30)
        setzen.assert_called_once_with(self.PAAR, 30)

    def test_absolut_nutzt_box_direkt(self):
        with mock.patch.object(spotify, "_ruf", side_effect=spotify.SpotifyFehler("403")), \
             mock.patch.object(spotify, "_geraetename", return_value="Schlafzimmer"), \
             mock.patch.object(spotify.sonos, "alle_mit_namen", return_value=self.PAAR), \
             mock.patch.object(spotify.sonos, "lautstaerke_setzen_alle", return_value=25) as setzen:
            self.assertEqual(spotify.lautstaerke_setzen(25), 25)
        setzen.assert_called_once_with(self.PAAR, 25)

    def test_ohne_box_bleibt_der_fehler(self):
        with mock.patch.object(spotify, "_ruf", side_effect=spotify.SpotifyFehler("403")), \
             mock.patch.object(spotify, "_geraetename", return_value="Handy"), \
             mock.patch.object(spotify.sonos, "alle_mit_namen", return_value=[]), \
             mock.patch.object(spotify.sonos, "finde", return_value=None):
            with self.assertRaises(spotify.SpotifyFehler):
                spotify.lautstaerke_setzen(25)


    def test_geraetename_nimmt_player_zuerst(self):
        """Anzeige und Steuerung müssen dasselbe Gerät meinen."""
        with mock.patch.object(spotify, "_ruf", return_value={"device": {"name": "Schlafzimmer"}}):
            self.assertEqual(spotify._geraetename(), "Schlafzimmer")

    def test_geraetename_faellt_auf_liste_zurueck(self):
        with mock.patch.object(spotify, "_ruf", return_value=None), \
             mock.patch.object(spotify, "_aktives_geraet", return_value={"name": "Wohnzimmer"}):
            self.assertEqual(spotify._geraetename(), "Wohnzimmer")

    def test_name_wird_zwischengespeichert(self):
        """Ohne Zwischenspeicher löst jeder Reglerschritt eine Spotify-Anfrage aus."""
        with mock.patch.object(spotify, "_ruf", return_value={"device": {"name": "Schlafzimmer"}}) as ruf:
            spotify._geraetename()
            spotify._geraetename()
        self.assertEqual(ruf.call_count, 1)

    def test_schneller_weg_geht_direkt_an_die_box(self):
        """Der Regler darf nicht über Spotify laufen."""
        with mock.patch.object(spotify, "_geraetename", return_value="Schlafzimmer"), \
             mock.patch.object(spotify.sonos, "alle_mit_namen", return_value=self.PAAR), \
             mock.patch.object(spotify.sonos, "lautstaerke_setzen_alle", return_value=42) as setzen, \
             mock.patch.object(spotify, "_ruf") as ruf:
            self.assertEqual(spotify.lautstaerke_schnell(42), 42)
        setzen.assert_called_once_with(self.PAAR, 42)
        ruf.assert_not_called()

    def test_skip_geht_lokal_an_die_box(self):
        """Weiter/Zurück dürfen nicht über Spotify laufen - dort kommt 403."""
        with mock.patch.object(spotify, "_geraetename", return_value="Schlafzimmer"), \
             mock.patch.object(spotify.sonos, "alle_mit_namen", return_value=self.PAAR), \
             mock.patch.object(spotify.sonos, "transport") as trans, \
             mock.patch.object(spotify, "_ruf") as ruf:
            spotify.naechstes()
        trans.assert_called_once_with("10.0.0.5", "Next")
        ruf.assert_not_called()

    def test_skip_faellt_auf_spotify_zurueck(self):
        """Ohne Sonos-Box (Handy, PC) muss der alte Weg bleiben."""
        with mock.patch.object(spotify, "_geraetename", return_value="Handy"), \
             mock.patch.object(spotify.sonos, "alle_mit_namen", return_value=[]), \
             mock.patch.object(spotify, "_ruf") as ruf:
            spotify.naechstes()
        ruf.assert_called_once_with("POST", "/me/player/next")


if __name__ == "__main__":
    unittest.main()

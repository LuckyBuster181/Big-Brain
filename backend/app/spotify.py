"""Spotify-Steuerung für Jarvis.

Steuert das Gerät, auf dem Spotify gerade spielt - also auch die Sonos-Boxen
über Spotify Connect. Braucht ein Spotify-Premium-Konto; ohne Premium lehnt
Spotify jeden Steuerbefehl mit 403 ab.

Zugangsdaten in der .env:
    SPOTIFY_CLIENT_ID=...
    SPOTIFY_CLIENT_SECRET=...
    SPOTIFY_REFRESH_TOKEN=...      (kommt aus /api/spotify/login, einmalig)
    SPOTIFY_STANDARD_GERAET=...    (optional, Name der Box, z.B. "Zimmer")

Absichtlich ohne Zusatzpakete (kein spotipy): `requests` ist im venv schon da,
und wir brauchen genau eine Handvoll Aufrufe.

Wichtig für die Kosten: Die Befehlserkennung in erkenne_befehl() arbeitet mit
festen Wortmustern und OHNE Claude. "leiser", "nächstes Lied", "stopp" kosten
damit 0 Tokens. Nur wenn kein Muster passt, entscheidet der Aufrufer, ob die
Frage ans Modell geht.
"""

from __future__ import annotations

import base64
import os
import re
import threading
import time
from urllib.parse import urlencode

import requests

from . import sonos

API = "https://api.spotify.com/v1"
AUTH = "https://accounts.spotify.com"
TIMEOUT = 8
# Ohne diese Rechte geht keine Steuerung. user-read-playback-state zum Lesen,
# user-modify-playback-state zum Steuern, user-read-currently-playing für
# "was läuft gerade".
SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing"
LAUTSTAERKE_SCHRITT = 10

_sperre = threading.Lock()
_token: str | None = None
_token_bis = 0.0


class SpotifyFehler(RuntimeError):
    """Abruf oder Steuerbefehl fehlgeschlagen (ohne Zugangsdaten zu nennen)."""


# ---------------------------------------------------------------- Zugangsdaten

def _wert(name: str) -> str:
    return (os.getenv(name) or "").strip().strip('"').strip("'")


def client_id() -> str:
    return _wert("SPOTIFY_CLIENT_ID")


def client_secret() -> str:
    return _wert("SPOTIFY_CLIENT_SECRET")


def refresh_token() -> str:
    return _wert("SPOTIFY_REFRESH_TOKEN")


def redirect_uri() -> str:
    return _wert("SPOTIFY_REDIRECT_URI") or "http://127.0.0.1:8000/api/spotify/callback"


def standard_geraet() -> str:
    return _wert("SPOTIFY_STANDARD_GERAET")


def ist_eingerichtet() -> bool:
    return bool(client_id() and client_secret() and refresh_token())


def _basic_auth() -> str:
    roh = f"{client_id()}:{client_secret()}".encode()
    return "Basic " + base64.b64encode(roh).decode()


# ------------------------------------------------------- Einmalige Anmeldung

def login_url() -> str:
    """Adresse, die Sir einmal im Browser öffnet, um Jarvis freizugeben."""
    if not client_id():
        raise SpotifyFehler("SPOTIFY_CLIENT_ID fehlt in der .env.")
    return AUTH + "/authorize?" + urlencode(
        {
            "client_id": client_id(),
            "response_type": "code",
            "redirect_uri": redirect_uri(),
            "scope": SCOPES,
            "show_dialog": "true",
        }
    )


def code_einloesen(code: str) -> str:
    """Tauscht den Code aus der Rückleitung gegen den Erneuerungs-Schlüssel."""
    antwort = requests.post(
        AUTH + "/api/token",
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri()},
        headers={"Authorization": _basic_auth()},
        timeout=TIMEOUT,
    )
    if antwort.status_code != 200:
        raise SpotifyFehler(f"Spotify lehnte den Code ab (HTTP {antwort.status_code}).")
    daten = antwort.json()
    neuer = daten.get("refresh_token")
    if not neuer:
        raise SpotifyFehler("Spotify lieferte keinen refresh_token.")
    return neuer


# ------------------------------------------------------------------- Aufrufe

def _access_token() -> str:
    """Kurzlebiges Zugangsticket, wird gecacht bis kurz vor Ablauf."""
    global _token, _token_bis
    with _sperre:
        if _token and time.time() < _token_bis:
            return _token
        if not ist_eingerichtet():
            raise SpotifyFehler(
                "Spotify ist nicht eingerichtet. SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET "
                "und SPOTIFY_REFRESH_TOKEN in die .env eintragen."
            )
        antwort = requests.post(
            AUTH + "/api/token",
            data={"grant_type": "refresh_token", "refresh_token": refresh_token()},
            headers={"Authorization": _basic_auth()},
            timeout=TIMEOUT,
        )
        if antwort.status_code != 200:
            raise SpotifyFehler(
                f"Spotify-Anmeldung fehlgeschlagen (HTTP {antwort.status_code}). "
                "Vermutlich ist der SPOTIFY_REFRESH_TOKEN ungültig - neu anmelden über /api/spotify/login."
            )
        daten = antwort.json()
        _token = daten.get("access_token", "")
        _token_bis = time.time() + max(60, int(daten.get("expires_in", 3600)) - 60)
        if not _token:
            raise SpotifyFehler("Spotify lieferte kein access_token.")
        return _token


def _ruf(methode: str, pfad: str, **kw) -> dict | None:
    antwort = requests.request(
        methode,
        API + pfad,
        headers={"Authorization": f"Bearer {_access_token()}"},
        timeout=TIMEOUT,
        **kw,
    )
    if antwort.status_code == 204:
        return None
    if antwort.status_code == 403:
        raise SpotifyFehler(
            "Spotify hat den Befehl abgelehnt (403). Häufigste Ursachen: kein Premium, "
            "oder das aktive Gerät nimmt diesen Befehl nicht an (bei Sonos oft die Lautstärke)."
        )
    if antwort.status_code == 404:
        raise SpotifyFehler("Kein aktives Spotify-Gerät. Einmal kurz Musik starten, dann klappt es.")
    if antwort.status_code == 429:
        raise SpotifyFehler("Zu viele Anfragen an Spotify. Kurz warten.")
    if antwort.status_code >= 400:
        raise SpotifyFehler(f"Spotify antwortete mit HTTP {antwort.status_code}.")
    if not antwort.content:
        return None
    try:
        return antwort.json()
    except ValueError:
        return None


# ---------------------------------------------------------------- Bausteine

def geraete() -> list[dict]:
    daten = _ruf("GET", "/me/player/devices") or {}
    return daten.get("devices", [])


def _aktives_geraet() -> dict | None:
    liste = geraete()
    for g in liste:
        if g.get("is_active"):
            return g
    name = standard_geraet().lower()
    if name:
        for g in liste:
            if name in (g.get("name") or "").lower():
                return g
    return liste[0] if liste else None


def laeuft_gerade() -> dict:
    """Titel, Künstler, Gerät und Lautstärke - oder {'spielt': False}."""
    daten = _ruf("GET", "/me/player")
    if not daten or not daten.get("item"):
        return {"spielt": False}
    item = daten["item"]
    geraet = daten.get("device") or {}
    laut = geraet.get("volume_percent")
    # Sonos meldet über Spotify oft 0 - dann den echten Wert bei der Box holen.
    if not laut:
        box = sonos.finde(geraet.get("name", ""))
        if box:
            try:
                laut = sonos.lautstaerke_lesen(box["ip"])
            except sonos.SonosFehler:
                pass
    return {
        "spielt": bool(daten.get("is_playing")),
        "titel": item.get("name", ""),
        "kuenstler": ", ".join(a.get("name", "") for a in item.get("artists", [])),
        "album": (item.get("album") or {}).get("name", ""),
        "geraet": geraet.get("name", ""),
        "lautstaerke": laut,
    }


def _sonos_transport(aktion: str) -> bool:
    """Versucht den Befehl lokal an der Box. True, wenn es geklappt hat.

    Sonos lehnt Weiter/Zurück/Pause über Spotify mit 403 ab, genau wie die
    Lautstärke (21.09.2026 am echten Gerät gesehen). Bei einem Paar reicht
    ein Befehl an eine Box - beide spielen dasselbe."""
    for box in sonos.alle_mit_namen(_geraetename()):
        try:
            sonos.transport(box["ip"], aktion)
            return True
        except sonos.SonosFehler:
            continue
    return False


def abspielen() -> None:
    if not _sonos_transport("Play"):
        _ruf("PUT", "/me/player/play")


def pause() -> None:
    if not _sonos_transport("Pause"):
        _ruf("PUT", "/me/player/pause")


def naechstes() -> None:
    if not _sonos_transport("Next"):
        _ruf("POST", "/me/player/next")


def vorheriges() -> None:
    if not _sonos_transport("Previous"):
        _ruf("POST", "/me/player/previous")


def zufall(an: bool) -> None:
    _ruf("PUT", f"/me/player/shuffle?state={'true' if an else 'false'}")


_name_cache: tuple[str, float] = ("", 0.0)
NAME_CACHE_S = 15


def _geraetename(cache_ok: bool = True) -> str:
    """Name des Geräts, auf dem gerade wirklich gespielt wird.

    Zuerst /me/player - das ist die Quelle, die auch laeuft_gerade() benutzt.
    Nur wenn dort nichts steht, die Geräteliste. Beide Wege auseinander laufen
    zu lassen war der Fehler vom 21.09.2026: die Anzeige fand die Sonos-Box,
    das Setzen der Lautstärke nicht."""
    global _name_cache
    if cache_ok and _name_cache[0] and time.time() - _name_cache[1] < NAME_CACHE_S:
        return _name_cache[0]
    try:
        daten = _ruf("GET", "/me/player") or {}
        name = ((daten.get("device") or {}).get("name") or "").strip()
        if name:
            _name_cache = (name, time.time())
            return name
    except SpotifyFehler:
        pass
    name = ((_aktives_geraet() or {}).get("name") or "").strip()
    if name:
        _name_cache = (name, time.time())
    return name


def _sonos_box() -> dict | None:
    """Die Sonos-Box zum gerade spielenden Gerät, falls es eine ist."""
    return sonos.finde(_geraetename())


def _sonos_boxen() -> list[dict]:
    """Alle Boxen zum gerade spielenden Gerät (Stereopaar: zwei Stück)."""
    return sonos.alle_mit_namen(_geraetename())


def lautstaerke_setzen(prozent: int) -> int:
    """Erst über Spotify, bei Ablehnung direkt über die Sonos-Box.

    Hintergrund: Sonos lehnt den Lautstärke-Befehl über Spotify mit HTTP 403
    ab (am 21.09.2026 am echten Konto gesehen). Der lokale Weg über Port 1400
    funktioniert dort, braucht aber den PC im selben WLAN."""
    prozent = max(0, min(100, int(prozent)))
    gefunden = _sonos_boxen()
    box = gefunden[0] if gefunden else None
    if gefunden:
        # Sonos zuerst, und zwar ALLE gleichnamigen Boxen - sonst wird nur
        # die halbe Anlage leiser.
        try:
            return sonos.lautstaerke_setzen_alle(gefunden, prozent)
        except sonos.SonosFehler:
            pass  # unten über Spotify versuchen
    try:
        _ruf("PUT", f"/me/player/volume?volume_percent={prozent}")
        return prozent
    except SpotifyFehler as exc:
        if box:
            raise SpotifyFehler(
                f"Weder die Box {box['name']} noch Spotify haben die Lautstärke angenommen: {exc}"
            ) from exc
        raise


def lautstaerke_aendern(delta: int) -> int:
    """Relativ lauter/leiser. Fragt den aktuellen Wert zuerst bei der Box ab,
    weil Spotify für Sonos oft 0 meldet."""
    gefunden = _sonos_boxen()
    if gefunden:
        try:
            jetzt = sonos.lautstaerke_lesen(gefunden[0]["ip"])
            return sonos.lautstaerke_setzen_alle(gefunden, jetzt + delta)
        except sonos.SonosFehler:
            pass  # unten weiter über Spotify versuchen
    aktuell = (_aktives_geraet() or {}).get("volume_percent")
    if aktuell is None:
        raise SpotifyFehler("Das aktive Gerät meldet keine Lautstärke - bitte eine Zahl nennen, z.B. 'Lautstärke 30'.")
    return lautstaerke_setzen(int(aktuell) + delta)


def suchen_und_spielen(begriff: str) -> dict:
    """Sucht Titel/Album/Künstler/Playlist und startet den besten Treffer."""
    begriff = begriff.strip()
    if not begriff:
        raise SpotifyFehler("Kein Suchbegriff angegeben.")
    treffer = _ruf(
        "GET", "/search", params={"q": begriff, "type": "track,album,artist,playlist", "limit": 1, "market": "from_token"}
    ) or {}

    spuren = (treffer.get("tracks") or {}).get("items") or []
    if spuren:
        spur = spuren[0]
        _ruf("PUT", "/me/player/play", json={"uris": [spur["uri"]]})
        return {
            "art": "titel",
            "titel": spur.get("name", ""),
            "kuenstler": ", ".join(a.get("name", "") for a in spur.get("artists", [])),
        }

    for schluessel, art in (("albums", "album"), ("playlists", "playlist"), ("artists", "künstler")):
        posten = (treffer.get(schluessel) or {}).get("items") or []
        if posten:
            eintrag = posten[0]
            _ruf("PUT", "/me/player/play", json={"context_uri": eintrag["uri"]})
            return {"art": art, "titel": eintrag.get("name", ""), "kuenstler": ""}

    raise SpotifyFehler(f"Nichts gefunden zu \"{begriff}\".")


# ------------------------------------------------- Befehlserkennung (ohne KI)

# Reihenfolge zählt: "spiel ..." steht bewusst hinten, damit "spiel weiter"
# nicht als Suchbegriff "weiter" endet.
_MUSTER: list[tuple[str, str]] = [
    (r"^(?:musik\s+)?(?:mach(?:\s+(?:mal|die|es))?\s+)?leiser$|^(?:etwas\s+)?leiser(?:\s+bitte)?$", "leiser"),
    (r"^(?:musik\s+)?(?:mach(?:\s+(?:mal|die|es))?\s+)?lauter$|^(?:etwas\s+)?lauter(?:\s+bitte)?$", "lauter"),
    (r"^(?:stell\s+die\s+)?lautst(?:ä|ae)rke\s+(?:auf\s+)?(\d{1,3})\s*%?$", "lautstaerke"),
    (r"^(?:mach\s+)?(?:die\s+)?musik\s+(?:auf\s+)?(\d{1,3})\s*%?$", "lautstaerke"),
    (r"^(?:stopp?|stop|pause|halt an|anhalten|musik aus|mach die musik aus)$", "pause"),
    (r"^(?:weiter|spiel weiter|weiterspielen|fortsetzen|play|musik an|mach die musik an)$", "weiter"),
    (r"^(?:n(?:ä|ae)chstes?(?:\s+lied|\s+titel|\s+song)?|skip|(?:lied|song|titel)\s+(?:wechseln|weiter)|weiter zum n(?:ä|ae)chsten)$", "naechstes"),
    (r"^(?:vorheriges?(?:\s+lied|\s+titel|\s+song)?|zur(?:ü|ue)ck|nochmal von vorne|letztes lied)$", "vorheriges"),
    (r"^(?:was l(?:ä|ae)uft(?:\s+gerade)?|welches lied l(?:ä|ae)uft|was h(?:ö|oe)re ich(?:\s+gerade)?)\??$", "was_laeuft"),
    (r"^(?:zufall|shuffle|zufallswiedergabe)\s*(?:an|ein)$", "zufall_an"),
    (r"^(?:zufall|shuffle|zufallswiedergabe)\s*aus$", "zufall_aus"),
    (r"^(?:spiel(?:e)?|leg(?:\s+mal)?|h(?:ö|oe)r(?:\s+mal)?)\s+(?:mir\s+)?(?:mal\s+)?(.+?)(?:\s+(?:ab|an|auf))?$", "spielen"),
]


def erkenne_befehl(text: str) -> dict | None:
    """Erkennt einen Musikbefehl im Satz. Gibt None zurück, wenn keiner passt.

    Kostet nichts - reine Wortmuster, kein Claude-Aufruf."""
    satz = (text or "").strip().lower()
    satz = re.sub(r"^(?:jarvis|hey jarvis|javis)[\s,:.]+", "", satz)
    satz = satz.strip().rstrip(".!")
    satz = re.sub(r"\s+", " ", satz)
    satz = re.sub(r"\s+bitte$", "", satz)
    if not satz:
        return None
    for muster, aktion in _MUSTER:
        treffer = re.match(muster, satz)
        if treffer:
            wert = treffer.group(1) if treffer.groups() else None
            return {"aktion": aktion, "wert": wert}
    return None


def ausfuehren(befehl: dict) -> str:
    """Führt einen erkannten Befehl aus und gibt eine kurze Rückmeldung."""
    aktion = befehl.get("aktion")
    wert = befehl.get("wert")

    if aktion == "leiser":
        return f"Lautstärke auf {lautstaerke_aendern(-LAUTSTAERKE_SCHRITT)} Prozent, Sir."
    if aktion == "lauter":
        return f"Lautstärke auf {lautstaerke_aendern(LAUTSTAERKE_SCHRITT)} Prozent, Sir."
    if aktion == "lautstaerke":
        return f"Lautstärke auf {lautstaerke_setzen(int(wert))} Prozent, Sir."
    if aktion == "pause":
        pause()
        return "Angehalten, Sir."
    if aktion == "weiter":
        abspielen()
        return "Läuft weiter, Sir."
    if aktion == "naechstes":
        naechstes()
        return "Nächster Titel, Sir."
    if aktion == "vorheriges":
        vorheriges()
        return "Vorheriger Titel, Sir."
    if aktion == "zufall_an":
        zufall(True)
        return "Zufallswiedergabe an, Sir."
    if aktion == "zufall_aus":
        zufall(False)
        return "Zufallswiedergabe aus, Sir."
    if aktion == "was_laeuft":
        stand = laeuft_gerade()
        if not stand.get("spielt") and not stand.get("titel"):
            return "Gerade läuft nichts, Sir."
        return f"{stand['titel']} von {stand['kuenstler']}, Sir - auf {stand['geraet'] or 'unbekanntem Gerät'}."
    if aktion == "spielen":
        ergebnis = suchen_und_spielen(wert or "")
        if ergebnis["kuenstler"]:
            return f"{ergebnis['titel']} von {ergebnis['kuenstler']} läuft, Sir."
        return f"{ergebnis['art'].capitalize()} {ergebnis['titel']} läuft, Sir."

    raise SpotifyFehler(f"Unbekannter Befehl: {aktion}")


def stand() -> dict:
    """Für das HUD: ist Spotify eingerichtet, und was läuft gerade."""
    if not ist_eingerichtet():
        return {
            "eingerichtet": False,
            "hinweis": "SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET und SPOTIFY_REFRESH_TOKEN fehlen in der .env.",
        }
    try:
        return {"eingerichtet": True, **laeuft_gerade()}
    except SpotifyFehler as exc:
        return {"eingerichtet": True, "fehler": str(exc)}


def lautstaerke_schnell(prozent: int) -> int:
    """Nur für den Regler im HUD: kürzester Weg zur Box.

    Kein Spotify-Aufruf, wenn die Box schon bekannt ist - sonst ruckelt der
    Regler, weil jeder Schritt eine Internetanfrage auslöst. Fällt auf den
    normalen Weg zurück, wenn keine Sonos-Box im Spiel ist."""
    prozent = max(0, min(100, int(prozent)))
    gefunden = _sonos_boxen()
    if gefunden:
        try:
            return sonos.lautstaerke_setzen_alle(gefunden, prozent)
        except sonos.SonosFehler:
            pass
    return lautstaerke_setzen(prozent)

"""
Prüfung eingehender Alexa-Anfragen (P19, 12.10.2026, Claude Code).

Der Endpunkt POST /api/alexa ist über den Funnel-Knoten "auron-alexa" aus dem Internet
erreichbar. Sein einziger Schutz ist diese Prüfung (Amazon-Vorgaben für Custom Skills):
  1. SignatureCertChainUrl: https, Host s3.amazonaws.com, Pfad beginnt mit /echo.api/, Port nur 443.
  2. Zertifikatskette laden: Signaturzertifikat gültig, SAN echo-api.amazon.com, Kette bis zu
     einer vertrauenswürdigen Wurzel (certifi). Geprüft mit cryptography.x509.verification;
     am 12.10. mit echten (älteren) Amazon-Ketten erfolgreich getestet.
  3. Signature-256: RSA PKCS#1 v1.5 / SHA-256 über den ROHEN Anfrage-Text.
  4. Zeitstempel höchstens 150 s von jetzt entfernt.
  5. Skill-ID gleich ALEXA_SKILL_ID aus der .env (optional Nutzer-ID gleich ALEXA_NUTZER_ID).
Jeder Fehler -> AlexaAbgelehnt (Route antwortet mit 400). Die Absenderadresse spielt keine Rolle.
"""

from __future__ import annotations

import base64
import datetime
import os
import posixpath
import re
import threading
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

ERLAUBTER_HOST = "s3.amazonaws.com"
PFAD_ANFANG = "/echo.api/"
SAN_NAME = "echo-api.amazon.com"
MAX_ABWEICHUNG_S = 150
LADEN_TIMEOUT_S = 2.0
MAX_KETTE_BYTES = 64 * 1024

_PEM_RE = re.compile(rb"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", re.S)


class AlexaAbgelehnt(Exception):
    """Anfrage stammt nicht nachweislich von Alexa für Sirs Skill."""


def ist_aktiv() -> bool:
    return (os.getenv("ALEXA_AKTIV") or "").strip() == "1"


def skill_id() -> str:
    return (os.getenv("ALEXA_SKILL_ID") or "").strip()


def nutzer_id() -> str:
    return (os.getenv("ALEXA_NUTZER_ID") or "").strip()


# ------------------------------------------------------------------ 1. Adresse der Kette

def kette_url_pruefen(url: str | None) -> str:
    """Prüft SignatureCertChainUrl nach Amazon-Vorgabe, gibt die normalisierte Adresse zurück."""
    if not url:
        raise AlexaAbgelehnt("SignatureCertChainUrl fehlt")
    teile = urlsplit(url.strip())
    if teile.scheme.lower() != "https":
        raise AlexaAbgelehnt("Kette nicht über https")
    if (teile.hostname or "").lower() != ERLAUBTER_HOST:
        raise AlexaAbgelehnt("Kette von falschem Host")
    try:
        port = teile.port
    except ValueError as exc:
        raise AlexaAbgelehnt("Kette mit ungültigem Port") from exc
    if port not in (None, 443):
        raise AlexaAbgelehnt("Kette mit falschem Port")
    roh = unquote(teile.path or "")
    pfad = posixpath.normpath(roh) if roh else ""
    if roh.endswith("/") and not pfad.endswith("/"):
        pfad += "/"
    if not pfad.startswith(PFAD_ANFANG):  # Groß/klein beachten (Amazon-Vorgabe)
        raise AlexaAbgelehnt("Kette mit falschem Pfad")
    return f"https://{ERLAUBTER_HOST}{pfad}"


# ------------------------------------------------------------------ 2. Kette laden und prüfen

def _laden(url: str) -> bytes:
    """Lädt die Zertifikatskette (PEM). Eigene Funktion, damit Tests sie ersetzen können."""
    import requests

    antwort = requests.get(url, timeout=LADEN_TIMEOUT_S)
    antwort.raise_for_status()
    if len(antwort.content) > MAX_KETTE_BYTES:
        raise AlexaAbgelehnt("Kette zu groß")
    return antwort.content


lader: Callable[[str], bytes] = _laden

_cache: dict[str, tuple[bytes, datetime.datetime]] = {}
_cache_sperre = threading.Lock()


def _wurzeln() -> list:
    """Vertrauenswürdige Wurzelzertifikate (certifi). Tests ersetzen diese Funktion."""
    import certifi
    from cryptography import x509

    with open(certifi.where(), "rb") as fh:
        return x509.load_pem_x509_certificates(fh.read())


wurzeln: Callable[[], list] = _wurzeln


def _zertifikate(pem: bytes) -> list:
    """PEM-Blöcke einzeln laden. Nicht lesbare Zwischenzertifikate werden übersprungen
    (Amazon liefert ein altes Starfield-Querzertifikat mit, das cryptography beanstandet)."""
    import warnings

    from cryptography import x509

    certs = []
    for block in _PEM_RE.findall(pem):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                certs.append(x509.load_pem_x509_certificate(block))
        except ValueError:
            continue
    if not certs:
        raise AlexaAbgelehnt("Keine lesbare Zertifikatskette")
    return certs


def _kette_holen(url: str, jetzt: datetime.datetime) -> list:
    with _cache_sperre:
        treffer = _cache.get(url)
    if treffer and treffer[1] > jetzt:
        return _zertifikate(treffer[0])
    try:
        pem = lader(url)
    except AlexaAbgelehnt:
        raise
    except Exception as exc:  # noqa: BLE001 - Netz, HTTP-Fehler
        raise AlexaAbgelehnt(f"Kette nicht ladbar: {type(exc).__name__}") from exc
    certs = _zertifikate(pem)
    with _cache_sperre:
        _cache[url] = (pem, certs[0].not_valid_after_utc)
    return certs


def kette_pruefen(certs: list, jetzt: datetime.datetime):
    """Signaturzertifikat gültig, SAN echo-api.amazon.com, Kette bis zu einer Wurzel.
    Gibt das Signaturzertifikat zurück."""
    from cryptography.x509.verification import DNSName, PolicyBuilder, Store, VerificationError

    blatt = certs[0]
    if not (blatt.not_valid_before_utc <= jetzt <= blatt.not_valid_after_utc):
        raise AlexaAbgelehnt("Signaturzertifikat abgelaufen oder noch nicht gültig")
    try:
        pruefer = (PolicyBuilder().store(Store(wurzeln())).time(jetzt.replace(tzinfo=None))
                   .build_server_verifier(DNSName(SAN_NAME)))
        pruefer.verify(blatt, certs[1:])
    except VerificationError as exc:
        raise AlexaAbgelehnt(f"Zertifikatskette ungültig: {exc}") from exc
    except ValueError as exc:
        raise AlexaAbgelehnt(f"Zertifikat nicht prüfbar: {exc}") from exc
    return blatt


# ------------------------------------------------------------------ 3. Signatur

def signatur_pruefen(kopf: dict[str, str], rohtext: bytes, jetzt: datetime.datetime | None = None) -> None:
    """Prüft Signatur-Kopfzeilen und Signatur über den rohen Text. Wirft AlexaAbgelehnt."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    jetzt = jetzt or datetime.datetime.now(datetime.timezone.utc)
    kopf = {k.lower(): v for k, v in kopf.items()}
    url = kette_url_pruefen(kopf.get("signaturecertchainurl"))
    signatur_b64 = (kopf.get("signature-256") or "").strip()
    if not signatur_b64:
        raise AlexaAbgelehnt("Signature-256 fehlt")
    try:
        signatur = base64.b64decode(signatur_b64, validate=True)
    except ValueError as exc:
        raise AlexaAbgelehnt("Signature-256 ist kein Base64") from exc
    blatt = kette_pruefen(_kette_holen(url, jetzt), jetzt)
    try:
        blatt.public_key().verify(signatur, rohtext, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as exc:
        raise AlexaAbgelehnt("Signatur passt nicht zum Text") from exc
    except (TypeError, AttributeError) as exc:  # kein RSA-Schlüssel
        raise AlexaAbgelehnt("Signaturschlüssel nicht unterstützt") from exc


# ------------------------------------------------------------------ 4./5. Inhalt

def _zeit(text: str) -> datetime.datetime:
    t = datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def inhalt_pruefen(anfrage: Any, jetzt: datetime.datetime | None = None) -> None:
    """Zeitstempel und Skill-ID (und optional Nutzer-ID). Wirft AlexaAbgelehnt."""
    jetzt = jetzt or datetime.datetime.now(datetime.timezone.utc)
    if not isinstance(anfrage, dict) or not isinstance(anfrage.get("request"), dict):
        raise AlexaAbgelehnt("Kein Alexa-Format")
    try:
        zeit = _zeit(anfrage["request"].get("timestamp"))
    except (TypeError, ValueError) as exc:
        raise AlexaAbgelehnt("Zeitstempel fehlt oder ist ungültig") from exc
    if abs((jetzt - zeit).total_seconds()) > MAX_ABWEICHUNG_S:
        raise AlexaAbgelehnt("Zeitstempel zu alt oder in der Zukunft")
    system = ((anfrage.get("context") or {}).get("System") or {})
    app_id = ((system.get("application") or {}).get("applicationId")
              or ((anfrage.get("session") or {}).get("application") or {}).get("applicationId") or "")
    erwartet = skill_id()
    if not erwartet or app_id != erwartet:
        raise AlexaAbgelehnt("Falsche oder fehlende Skill-ID")
    nutzer = nutzer_id()
    if nutzer:
        tatsaechlich = ((system.get("user") or {}).get("userId")
                        or ((anfrage.get("session") or {}).get("user") or {}).get("userId") or "")
        if tatsaechlich != nutzer:
            raise AlexaAbgelehnt("Falsche Nutzer-ID")

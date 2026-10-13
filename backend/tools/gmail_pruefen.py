"""Gmail-Zugang prüfen (25.09.2026): liest die .env, meldet sich an und zeigt
die Zahl ungelesener Mails plus die drei neuesten Betreffzeilen.
Markiert NICHTS als gelesen. Aufruf über GMAIL_APP_PASSWORT_SETZEN.bat."""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from tools.gmail_login import ENV, env_lesen  # noqa: E402


def main() -> int:
    for name, wert in env_lesen(ENV).items():
        os.environ.setdefault(name, wert)
    from app import gmail  # erst nach dem Laden der .env

    if not gmail.ist_eingerichtet():
        print("Gmail ist nicht eingerichtet: GMAIL_ADRESSE oder GMAIL_APP_PASSWORT fehlt in der .env.")
        return 1
    try:
        mails = gmail.ungelesene()
    except gmail.GmailFehler as fehler:
        print(f"FEHLER: {fehler}")
        return 1
    weg = "App-Passwort (IMAP)" if gmail.imap_aktiv() else "Google-Zugang (OAuth)"
    print(f"Anmeldung OK über {weg}. Ungelesen nach Auron-Suche: {len(mails)}")
    for m in mails[:3]:
        print(f"  - {m['von'][:40]} | {m['betreff'][:60]}")
    print("Nichts wurde als gelesen markiert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

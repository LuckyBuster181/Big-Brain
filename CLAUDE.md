# Auron / Jarvis - Anweisung fuer Claude Code

- Besitzer ist Sir. Immer mit Sir ansprechen. Deutsch, kurz, direkt, sachlich, einfache Sprache, keine Emojis, kein Lob.
- Dieses Repo ist nur eine Arbeitskopie. Die Originale liegen auf Sirs PC in C:\Users\maxi1\Documents\KI\Jarvis. Vault, data, .env, Modelle und Tools sind absichtlich NICHT im Repo.
- Aufbau: backend\app = FastAPI-Backend, backend\llm = Anbindung Ollama und Claude, backend\tests = Tests, dashboard = Oberflaeche auron.html, werkstatt = Seiten und 3D-Universum, 1 Starten = Startdateien.
- Tests im Ordner backend: python -m unittest discover -s tests -p "test_*.py". Nie pytest. In der Cloud sind PyPI, HuggingFace und npm gesperrt: fuer Tests Stub-Module fuer anthropic und chromadb anlegen, nichts davon ins Repo.
- Nie .env oder Schluessel lesen, schreiben oder committen.
- Kein Shell-Zugriff auf Sirs PC. Befehle fuer den PC nur als .bat, die Sir selbst startet. .bat und .ps1 nur ASCII. JARVIS STARTEN.bat behaelt LF-Zeilenenden.
- Python geaendert = NEUSTART noetig. Nur HTML oder JS geaendert = Strg+F5.
- Kosten: Rahmen fuer Claude-Anfragen von Jarvis selbst ist 10 EUR im Monat. Tag laeuft lokal, Claude nur als Rueckfall. Nachtarbeit nie mit Claude.
- Kleine Schritte, nichts Ungetestetes stapeln. Ungetestetes klar als ungetestet kennzeichnen. Nichts erfinden.
- Jede Commit-Nachricht auf Deutsch: was geaendert, ob getestet, was Sir am PC tun muss. Aenderungen direkt ins Repo pushen. Sir holt sie selbst auf den PC.

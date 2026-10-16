# Auron / Jarvis - Anweisung fuer Claude Code

- Besitzer ist Sir. Immer mit Sir ansprechen. Deutsch, kurz, direkt, sachlich, einfache Sprache, keine Emojis, kein Lob.
- Dieses Repo ist nur eine Arbeitskopie. Die Originale liegen auf Sirs PC in C:\Users\maxi1\Documents\KI\Jarvis. Vault, data, .env, Modelle und Tools sind absichtlich NICHT im Repo.
- Aufbau: backend\app = FastAPI-Backend, backend\llm = Anbindung Ollama und Claude, backend\tests = Tests, dashboard = Oberflaeche auron.html, werkstatt = Seiten und 3D-Universum, 1 Starten = Startdateien.
- Tests im Ordner backend: python -m unittest discover -s tests -p "test_*.py". Nie pytest. Pakete in eine venv ausserhalb des Repos installieren (pip install -r backend/requirements.txt), am 10.10.2026 waren PyPI und HuggingFace erreichbar. Falls gesperrt: Stub-Module fuer anthropic und chromadb anlegen, nichts davon ins Repo.
- Tests steuern nie echte Geraete und gehen nie ins Netz (Vorfall 11.10.2026: Test startete Sirs PC neu). Testmodus AURON_TESTMODUS=1 und Netz-Waechter in backend\tests\testschutz.py, Sperre im App-Code in backend\app\geraeteschutz.py. Geraete nur ueber Test-Stubs auf 127.0.0.1 (testschutz.stub_freigeben), sonst Mocks. Nie den echten PC-Agenten im Test starten.
- Vor jeder Lieferung an Sir: Tests UND Cloud-Pruefstand (im Ordner backend: python -m cloud_pruefstand.lauf --ausgabe <Ordner>, dazu pip install playwright; Chromium liegt in der Cloud unter /opt/pw-browsers). Echtes Backend mit Ersatz-KI und Test-Vault, Auron im Browser. Fertig heisst: beides ohne Fehler und GitHub Actions gruen. Ergebnis kurz an Sir.
- Sir holt Aenderungen mit "1 Starten/REPO HOLEN.bat" (Repo -> Jarvis-Ordner) und laedt eigene mit REPO HOCHLADEN.bat hoch. Bei Problemen am PC: Sir startet "1 Starten/FEHLERBERICHT SENDEN.bat", dann berichte/fehlerbericht.md aus main lesen (git fetch origin main), nicht raten.
- Nie .env oder Schluessel lesen, schreiben oder committen.
- Kein Shell-Zugriff auf Sirs PC. Befehle fuer den PC nur als .bat, die Sir selbst startet. .bat und .ps1 nur ASCII. JARVIS STARTEN.bat behaelt LF-Zeilenenden.
- Python geaendert = NEUSTART noetig. Nur HTML oder JS geaendert = Strg+F5.
- Kosten: Rahmen fuer Claude-Anfragen von Auron selbst ist 20 $ im Monat, dazu ein eigener Code-Deckel von 10 $ fuer selbst ausgeloeste Code-Aufgaben (Modus "code-...", nachts nie Claude). Tag laeuft lokal, Claude nur als Rueckfall. Nachtarbeit nie mit Claude.
  Dritter Topf (P24): gemietete GPU bei RunPod, eigener Deckel in EUR (Standard 40 EUR im Monat, `GPU_MIETE_DECKEL_EUR`), nur nachts oder auf Befehl von Sir, der Pod wird IMMER gelöscht (`backend/app/gpu_miete.py`, Wächter `backend/gpu_waechter.py`). Anleitung: `projekt-aufgaben/UEBERGABE P24.md`. Tests dürfen RunPod nie echt aufrufen.
- Kleine Schritte, nichts Ungetestetes stapeln. Ungetestetes klar als ungetestet kennzeichnen. Nichts erfinden.
- Jede Commit-Nachricht auf Deutsch: was geaendert, ob getestet, was Sir am PC tun muss. Aenderungen direkt ins Repo pushen. Sir holt sie selbst auf den PC.
- Gesamtkarte: massgeblich ist data\gesamtkarte.json auf Sirs PC (nicht im Repo, per Syncthing abgeglichen). backend\app\gesamtkarte.json ist nur der Startwert fuer den ersten Start; Aenderungen dort erreichen Sir nicht mehr. Karte aendert Claude im Projekt direkt in data.
- Offene, zurueckgestellte Punkte stehen in OFFEN.md. Zu Beginn kurz pruefen und Sir fragen.

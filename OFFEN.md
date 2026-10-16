# Offene Punkte (Stand 11.10.2026)

Von Sir zurueckgestellt ("machen wir wann anders"). Naechste Sitzung: Sir fragen, ob jetzt dran.

1. **pc_agent_windows und pc2_agent ins Repo aufnehmen**
   - Liegen nur auf Sirs PC. Tests dafuer werden in der Cloud und auf GitHub uebersprungen.
   - Noetig: REPO HOCHLADEN.bat muss die Ordner mitnehmen. Die .bat ist nicht im Repo,
     Sir muss sie einmal hochladen, dann anpassen.

2. **Direkt auf main pushen statt Pull Request**
   - Spart Sir den Merge auf GitHub, er startet nur noch REPO HOLEN.bat.
   - Seit 10.10.2026 prueft GitHub jede Aenderung automatisch (Tests + Pruefstand).
   - Nachteil: Sir sieht Aenderungen nicht mehr vorher. Erst nach ausdruecklichem Ja von Sir.

3. **Gesten: naechste Schritte** (Stand 15.10.2026, erster Schritt fertig)
   - Erst am PC testen: Schwellen und Glaettung in werkstatt/gesten/gesten.js (EINSTELLUNG) mit Sirs Webcam.
   - Wunsch Sir 16.10.: ganzen PC steuern, nicht nur Auron. Geht nicht aus dem Browser heraus (Browser darf die
     Windows-Maus nicht bewegen). Braucht ein eigenes kleines Programm auf dem PC (Kamera + Maus), Start per .bat.
   - Gesten so, wie ein Mensch es intuitiv macht (Wischen, Greifen, Scrollen); Vorbilder Meta Quest / Apple Vision.
   - Wunsch Sir 16.10.: ganze Hand wischen (z. B. Fenster/Bereich wechseln). Erst wenn der Klick am PC sicher geht.
   - Idee Sir: Auron auf der Meta Quest (VR-Brille, WebXR im Quest-Browser). Eigenes Projekt, spaeter.

4. **GPU-Miete (P24): erster echter Lauf** (Stand 16.10.2026, Code gebaut, nie gegen echtes RunPod gelaufen)
   - Sir: RunPod-Konto, Network Volume, Schluessel in die .env, Waechter auf dem Mini-PC einrichten, kleiner Testlauf mit offener
     RunPod-Konsole. Ablauf in `projekt-aufgaben/UEBERGABE P24.md`.
   - Danach pruefen: Feldnamen der RunPod-Antworten, Vorladen des Modells im Pod, Image auf feste Version setzen.
   - P24b: Alexa-Alarm (Benachrichtigung statt Erinnerung, Amazon erlaubt keine neue Erinnerung von aussen) ungetestet; Skill-Manifest,
     Zugangsdaten und Test in `projekt-aufgaben/UEBERGABE P24b.md`. Unklar: ob de-DE und Entwicklungsmodus das Ereignis zustellen.
   - Offene Fragen an Sir: GPU-Deckel (40 EUR oder 40 $, harte Obergrenze 60 EUR?), Modell (70B oder bei qwen3-coder:30b bleiben).

5. **Piper-Stimme auf dem Mini-PC (P05)** (Stand 16.10.2026, gebaut, am Mini-PC ungetestet)
   - Sir: REPO HOLEN, JARVIS STARTEN, `PIPER MINI-PC.bat` (1 = Einrichten, 2 = Messen), Berichte an Claude. Ablauf in
     `projekt-aufgaben/UEBERGABE P05.md`. Frist: Fish Audio kostenlos bis 30.11.2026, ab 01.12. ist Piper automatisch Standard.
   - Danach entscheiden: Qualitaet high oder medium (nach Hoerprobe und Messung). In `dashboard/auron.html` zeigt die Statuszeile
     weiter "Fish Audio", auch wenn Piper spricht (auron.html auf Sirs PC neuer, deshalb nicht angefasst).

## Erledigt am 10.10.2026 (zur Einordnung)
- Sucher und Schreiber (Agenten-Station, Chat-Befehl "Such und schreib: ...").
- REPO HOLEN.bat (unter Windows erfolgreich gelaufen).
- Cloud-Pruefstand, GitHub Actions, Fehlerbericht (FEHLERBERICHT SENDEN.bat, unter Windows noch nicht benutzt).
- Behoben: Tests griffen auf echte Daten zu, Chat blieb ohne Claude stumm, Gespraeche beim falschen Tag (UTC).
- Nur gesehen: iss.glb fehlt im Repo (> 5 MB?), Frage des Tages nutzt Claude Haiku direkt (gewollt, ca. 0,1 Cent/Tag).

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
   - Spaeter: ganzen Windows-Bildschirm steuern (ueber den PC-Agenten), Scrollen per Geste.

## Erledigt am 10.10.2026 (zur Einordnung)
- Sucher und Schreiber (Agenten-Station, Chat-Befehl "Such und schreib: ...").
- REPO HOLEN.bat (unter Windows erfolgreich gelaufen).
- Cloud-Pruefstand, GitHub Actions, Fehlerbericht (FEHLERBERICHT SENDEN.bat, unter Windows noch nicht benutzt).
- Behoben: Tests griffen auf echte Daten zu, Chat blieb ohne Claude stumm, Gespraeche beim falschen Tag (UTC).
- Nur gesehen: iss.glb fehlt im Repo (> 5 MB?), Frage des Tages nutzt Claude Haiku direkt (gewollt, ca. 0,1 Cent/Tag).

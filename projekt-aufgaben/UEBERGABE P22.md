# Übergabe P22 an den PC (13.10.2026): Stufen im PC-Agenten

`pc_agent_windows\jarvis_pc_agent.py` liegt nicht im Repo (OFFEN.md, Punkt 1), nur auf Sirs PC. Claude Code
in der Cloud konnte ihn deshalb nicht ändern. Stattdessen liegt die ganze Stufen-Logik als getestetes Modul im Repo:

- `pc_agent_windows/agent_stufen.py` (nur Standardbibliothek)
- `pc_agent_windows/befehle_standard.json` (die sechs Stufe-1-Befehle, relative Pfade)
- `pc_befehle/*.bat` (die sechs Befehle, nicht interaktiv)
- Tests: `backend/tests/test_p22_stufen.py`

Der Agent muss das Modul nur noch einbinden. Das macht Claude im Projekt am PC (oder Sir lässt es dort tun).
**Solange das nicht passiert ist, gilt die Stufen-Sperre nur im Backend (erste Sperre), nicht im Agenten.**

## Einbinden in jarvis_pc_agent.py (ungetestet am PC)

1. `import agent_stufen` (liegt im selben Ordner). `VERSION = "1.2.0"`, damit `pc_agent_aktualisieren.ps1`
   den Agenten neu startet.
2. In der Verarbeitung von `POST /aktion`, ganz am Anfang (vor jeder Ausführung):
   ```python
   erlaubt, meldung, st = agent_stufen.freigabe(name, daten.get("bestaetigt") is True)
   if not erlaubt:
       protokoll(agent_stufen.protokoll_zeile(st, name, ziel, absender, "abgelehnt: " + meldung))
       return {"ok": False, "meldung": meldung}
   ```
   Unbekannte Aktionen und Stufe 3 bleiben damit abgelehnt, Stufe 2 nur mit `"bestaetigt": true`.
3. Nach der Ausführung die Protokollzeile mit Stufe schreiben:
   `agent_stufen.protokoll_zeile(st, name, ziel, absender, "ok" oder Fehlertext)` nach `agent_protokoll.txt`
   (ersetzt das bisherige Format; Absender = Client-IP).
4. Aktion `befehl` (Stufe 1): statt des bisherigen Starts
   ```python
   liste = agent_stufen.befehle_laden(JARVIS_ORDNER, HIER / "befehle.json", HIER / "befehle_standard.json")
   ok, meldung, _ = agent_stufen.befehl_starten(ziel, liste, JARVIS_ORDNER / "data" / "befehle")
   return {"ok": ok, "meldung": meldung}
   ```
   `JARVIS_ORDNER` = Elternordner von `pc_agent_windows`. Die Sperre (ein Befehl gleichzeitig), das Zeitlimit und
   die Ausgabe nach `data\befehle\<name>_<Datum>.txt` sind im Modul. Die lokale `befehle.json` gilt weiter, wenn sie
   Einträge enthält (und kann nur am PC geändert werden); sonst gilt die Standardliste.
5. `GET /aktionen`: zusätzlich `"stufen": agent_stufen.aktionen_mit_stufe()` ausgeben.
6. Neuer Endpunkt `GET /befehl_bericht?name=pruefen` (Stufe 0, nur lesen, mit Token wie alle anderen):
   `return agent_stufen.bericht(name, JARVIS_ORDNER / "data" / "befehle")`
7. Meldung beim Herunterfahren: `agent_stufen.HERUNTERFAHREN_NACHRICHT` ("Auron: Herunterfahren in 60 Sekunden")
   statt des alten Texts; beim Neustart `agent_stufen.NEUSTART_NACHRICHT`.
8. In `backend/tests/test_pc_agent.py` (läuft nur am PC): Test `VERSION == "1.2.0"` nachziehen, plus je ein Test
   „Stufe 2 ohne `bestaetigt` wird vom Agenten abgelehnt“.

## Am PC prüfen

`REPO HOLEN.bat`, danach `JARVIS STARTEN.bat`. Im Chat „Backup starten“, dann „Wie war das Backup?“. Bericht
liegt unter `data\befehle\`. Nicht testen: Herunterfahren, Neustart.

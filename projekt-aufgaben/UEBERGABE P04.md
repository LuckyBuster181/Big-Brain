# Übergabe P04 an den PC (16.10.2026): Lokale Spracherkennung (faster-whisper) auf dem Mini-PC

Ziel: Die Spracheingabe in Auron kann auf Wunsch über Whisper auf dem Mini-PC laufen statt über den Browser. Beim Browser
geht das Audio an Google oder Microsoft, mit Whisper bleibt es im Heimnetz. Das Weckwort („Immer ansprechbar“) bleibt beim Browser.

**Stand: gebaut und getestet. In der Cloud lief alles echt, aber ungetestet auf dem Mini-PC:**
- echtes faster-whisper (Modelle base und small);
- eine Aufnahme aus Auron im Browser (Ersatz-Mikrofon mit einer Piper-Ansage) bis zum erkannten Text;
- das Einrichtungsskript mit einer venv ohne pip.

## Befund unterwegs

- `stt.py` läuft unter Linux unverändert: Aufnahme in einen Temp-Ordner, Threads über `WHISPER_THREADS` (Standard 2).
  Das Modell lädt faster-whisper beim ersten Mal in den Cache des Benutzers (`~/.cache/huggingface`, oder `WHISPER_MODELLORDNER`).
- **Echter Fehler gefunden:** Die neueste faster-whisper (1.2.1) läuft nicht mit dem neuesten Paket `av` (19): „unexpected keyword
  argument metadata_errors“. Das .bat installiert deshalb `av<19`, und Auron meldet den Fehler sonst klar.
- Der Mini-PC hat Python 3.14.7 und eine venv ohne pip. Das Skript nimmt dann uv (wie bei Piper). Alle Pakete gibt es für 3.14.
- Standardmodell jetzt **base** (vorher small). small ist wählbar.

## Was neu ist

- `1 Starten/WHISPER MINI-PC.bat` + `whisper_mini_einrichten.sh` (per ssh):
  1 = einrichten mit base, 2 = einrichten mit small, 3 = messen (base und small), 4 = Spracherkennung lokal,
  5 = zurück auf Browser, 6 = Stand. Einrichten installiert `faster-whisper` und `av<19` in die venv und lädt das Modell.
  Dann startet es den Dienst „jarvis“ neu (über `jarvis_mini.sh neustart`, das JARVIS STARTEN.bat auf den Mini-PC legt) und stellt
  das Modell im Backend ein.
  Logdatei: `data\whisper_mini_bericht.txt` (wird fortgeschrieben, nicht überschrieben).
- `backend/whisper_messung.py`: Dauer der Erkennung für 5 und 10 Sekunden Sprache, je 3 Läufe, dazu der grob gezählte Anteil
  richtig erkannter Wörter. Die Sprachproben macht Piper (P05 muss eingerichtet sein). Ergebnis in der Logdatei und in `data\whisper_messung.txt`.
- `dashboard/auron.html`: Der Mikrofon-Knopf nimmt Whisper, wenn im Backend „Spracherkennung: lokal“ eingestellt und faster-whisper
  installiert ist. Er nimmt auf, bis 1,2 s Stille ist (höchstens 15 s), schickt die Aufnahme an `/api/sprache/erkennen` und fragt dann.
  Geht Whisper schief, hört beim nächsten Mal wieder der Browser zu. Die Statuszeile „Stimme“ zeigt jetzt auch „Piper“ (Rest aus P05).
- Einstellung: im .bat (Taste 4/5) oder im alten HUD unter Einstellungen, „Spracherkennung“. Gilt sofort, ohne Neustart.

## Was Sir tun muss

1. `REPO HOLEN.bat`, danach `JARVIS STARTEN.bat` (neuer Code auf den Mini-PC), im Browser Strg+F5.
2. `1 Starten\WHISPER MINI-PC.bat`, Taste **1** (base). Dauert einige Minuten, das Modell hat ca. 150 MB.
3. Gleiches .bat, Taste **3** (Messen). Vorher muss Piper eingerichtet sein (`PIPER MINI-PC.bat` Taste 1).
4. Gleiches .bat, Taste **4** (lokal einschalten). Dann in Auron auf den Mikrofon-Knopf: Der Hinweis zeigt „Ich höre zu (lokal), Sir …“.
5. `data\whisper_mini_bericht.txt` an Claude geben.
Gefällt die Erkennung nicht: Taste 2 (small) oder Taste 5 (zurück auf Browser).

## Gemessen in der Cloud-VM (nicht der Mini-PC; Piper-Ansage, 2 Threads)

| Modell | Laden | 5 s Sprache | 10 s Sprache (12 s Probe) | Wörter richtig |
|---|---|---|---|---|
| base | 3 s | 1,4 s | 1,4 s | ca. 83–92 % |
| small | 11 s | 3,0 s | 3,6 s | ca. 90–94 % |

Der Mini-PC (i5, 4. Generation) ist deutlich langsamer. **Erwartung, nicht gemessen:** base wird dort einige Sekunden brauchen,
small spürbar länger. Die Messung am Mini-PC (Schritt 3) entscheidet. Auffällig: „Sir“ wird oft als „Sie“ erkannt.
Eine 15 s lange Aufnahme, in der derselbe Satz fünfmal wiederholt wurde, brauchte 10 s statt gut 1 s: Whisper rechnet bei
Wiederholungen mehrfach nach. Das liegt am Inhalt, nicht an der Aufnahme aus dem Browser (webm), und kommt bei normaler Sprache kaum vor.

## Grenzen

- Der Dienst wird über `~/jarvis-umzug/jarvis_mini.sh neustart` neu gestartet. Fehlt die Datei oder fehlt das Recht, steht im
  Bericht „Bitte JARVIS STARTEN.bat starten“.
- Das Modell lädt beim ersten Mal von HuggingFace, der Mini-PC braucht dafür Internet. Läuft der Dienst unter einem anderen
  Benutzer als `max1`, lädt er das Modell beim ersten Satz noch einmal (eigener Cache). Abhilfe: `WHISPER_MODELLORDNER` in der .env.
- faster-whisper steht nicht in `backend/requirements.txt` (wie Piper), es kommt nur über das .bat in die venv des Mini-PCs.

## Technisch (für Claude im Projekt)

- Neu: `1 Starten/WHISPER MINI-PC.bat`, `1 Starten/whisper_mini_einrichten.sh`, `backend/whisper_messung.py`,
  `backend/tests/test_whisper_mini.py` (14 Tests mit Stub für faster-whisper und Piper).
- Geändert: `backend/app/stt.py` (Standard base, `WHISPER_MODELLORDNER`, `vorladen()`, `bereit`, Meldung zu `av`, Hinweis je
  Betriebssystem), `dashboard/auron.html` (Mikrofon lokal, Statuszeile Stimme), `backend/tests/test_phase3.py` (Hinweis je Betriebssystem).

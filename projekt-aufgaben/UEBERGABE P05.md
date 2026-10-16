# Übergabe P05 an den PC (16.10.2026): Piper als lokale Stimme auf dem Mini-PC

Ziel: Fish Audio ist nur bis 30.11.2026 kostenlos. Ab 01.12.2026 spricht Auron automatisch mit Piper (läuft auf dem
Mini-PC, nichts verlässt den Rechner), wenn Sir nichts anderes eingestellt hat.

**Stand: gebaut und mit Stubs getestet. Das Python-Paket und die Stimmen habe ich in der Cloud mit einer echten Stimme
geprüft (Sprechen, Einmal-Laden, Einrichtungsskript, Messskript). Am Mini-PC selbst ungetestet.**

## Was neu ist

- `backend/app/piper_tts.py`: Linux nutzt das Python-Paket `piper-tts`. Die Stimme wird einmal geladen und bleibt im Speicher
  (kein Programmstart je Satz). Windows behält `piper.exe`. Fehlt die `.onnx.json`, sagt Auron es klar. Threads begrenzt
  (`PIPER_THREADS`, Standard 2).
- `backend/app/stimme.py` (neu): Wahl der Stimme. Einstellung „Vorlesen über“: **Automatisch / Fish Audio / Piper / Browser**.
  - Rückfall: gewählte Stimme, dann Piper, dann Browser. Wählt Sir ausdrücklich „Browser“, geht kein Text nach außen.
    Wählt Sir „Piper“, geht es bei einem Fehler nur noch auf den Browser.
  - **Automatisch**: bis 30.11.2026 Fish Audio, ab 01.12.2026 Piper.
- `POST /api/sprache` entscheidet jetzt selbst (MP3 von Fish, WAV von Piper). Auron, Handy und HUD bekommen dadurch Piper und
  den Rückfall, ohne dass dort etwas geändert werden muss. Antwortet der Server mit 503, spricht der Browser.
- HUD (`dashboard/index.html`): Einstellung „Vorlesen über“ speichert im Backend und gilt sofort.
  `dashboard/auron.html` habe ich **nicht** angefasst (auf Ihrem PC neuer als im Repo). Dort steht in der Statuszeile weiter
  „Fish Audio“, auch wenn Piper spricht. Das ist nur die Anzeige.
- `1 Starten/PIPER MINI-PC.bat` + `piper_mini_einrichten.sh`: Einrichtung und Messung per ssh. `backend/stimme_messung.py`: Messung.

## Was Sir tun muss

1. `REPO HOLEN.bat`, danach `AURON STARTEN.bat` (bringt den neuen Code auf den Mini-PC, startet neu). Strg+F5 im Browser.
2. `1 Starten\PIPER MINI-PC.bat`, Taste **1** (Einrichten). Es installiert `piper-tts` in die venv des Mini-PCs, lädt die Stimmen
   `de_DE-thorsten-high` und `-medium` nach `tools/piper` (falls dort nicht schon vorhanden, ca. 190 MB), erzeugt einen Probesatz
   und schreibt `data\piper_mini_bericht.txt`. Hörproben: `data\piper_probe_high.wav` und `piper_probe_medium.wav`.
   Das Skript findet den Projektordner und die venv über den Dienst „jarvis“; findet es sie nicht, steht es im Bericht.
3. `AURON STARTEN.bat` noch einmal (das Backend lädt die Stimme dann beim Start vor).
4. `1 Starten\PIPER MINI-PC.bat`, Taste **2** (Messen, einige Minuten). Ergebnis: `data\stimme_messung.txt`:
   Zeit bis der Ton fertig ist (Satz mit 80 Zeichen, je 5 Läufe) für Fish Audio, Piper high, Piper medium, dazu 20 Sätze
   hintereinander auf Fehler. Fish Audio wird nur gemessen, wenn `FISH_API_KEY` gesetzt ist (25 kurze Sätze, kostenlos).
5. Einstellungen, „Vorlesen über“: nach den Hörproben und der Messung wählen. Wer nichts einstellt, bekommt ab 01.12. Piper.
6. `data\piper_mini_bericht.txt` und `data\stimme_messung.txt` an Claude geben.

## Was ich gemessen habe (Cloud-VM, nicht der Mini-PC)

Satz mit 80 Zeichen, Piper im Speicher gehalten: **medium ca. 0,4 s, high ca. 2,2 s**; Laden der Stimme einmalig 2 bis 4 s;
20 Sätze hintereinander ohne Fehler. Fish Audio braucht nach früherer Messung ca. 1 s + 0,035 s je Zeichen, also rund 3,8 s
für 80 Zeichen. Der Mini-PC (i5, 4. Generation) ist langsamer als diese VM. **Erwartung (nicht gemessen):** „high“ klingt besser,
braucht auf dem Mini-PC aber wahrscheinlich mehrere Sekunden je Satz. Die echte Messung entscheidet. Piper-Qualität umstellen:
Einstellung `piper_qualitaet` (`high` oder `medium`, Umgebung `PIPER_QUALITAET`).

## Grenzen

- Piper liefert die Sprachdatei am Stück. „Zeit bis zum ersten Ton“ ist deshalb die Zeit bis zum fertigen Ton.
- Das Paket `piper-tts` steht nicht in `backend/requirements.txt` (sonst müssten es Windows-PC und die Tests mit installieren).
  Es wird nur vom `.bat` in die venv des Mini-PCs gebracht.
- Windows-PC: Dort ändert sich nichts außer der Wahl im HUD. `piper.exe` läuft weiter wie bisher.

## Technisch (für Claude im Projekt)

- Neu: `app/stimme.py`, `stimme_messung.py`, `1 Starten/PIPER MINI-PC.bat`, `1 Starten/piper_mini_einrichten.sh`,
  `tests/test_piper_linux.py` (39 Tests: Pfadwahl je Betriebssystem, Stimme nur einmal geladen, Rückfall, Umschaltung am 01.12.,
  Einstellung, Schnittstelle, Messbericht).
- Geändert: `app/piper_tts.py`, `app/routes.py` (`/api/sprache`, `/api/sprache/status`), `app/schemas.py` (`quelle`),
  `app/einstellungen.py` (`stimme_quelle`, `piper_qualitaet`), `main.py` (Piper beim Start vorladen, nicht im Testmodus),
  `dashboard/index.html`, `tests/test_phase3.py` (Piper-Test braucht jetzt die `.onnx.json`).
- Messwerte der Cloud-VM stammen aus `stimme_messung.py` mit `piper-tts` 1.8.0.

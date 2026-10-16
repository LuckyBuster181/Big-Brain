# Übergabe P24 an den PC (16.10.2026): Gemietete GPU mit Selbstabschaltung (RunPod)

Auron kann für eine Code-Aufgabe kurz einen RunPod-Pod mit GPU mieten, die Aufgabe mit einem lokalen Ollama-Code-Modell
(`qwen3-coder:30b`) rechnen lassen und den Pod danach **immer löschen** (terminate, nicht stoppen). Hintergrund: Bei centron
wurde ein nur ausgeschalteter Server 24 Stunden voll berechnet (27,54 EUR).

**Stand: ungetestet gegen das echte RunPod.** Alle 66 neuen Tests (`backend/tests/test_gpu_miete.py`) laufen nur gegen
Ersatz-Objekte. Der Aufbau der RunPod-Anfragen folgt der RunPod-Dokumentation (`rest.runpod.io/v1`), das Start-Skript im Pod
ist nur gelesen, nicht ausgeführt. Der erste echte Lauf kommt von Sir, klein, mit offener RunPod-Konsole.

## Was passiert

1. Nachtarbeit (Timer 03:00) findet offene Nachtaufträge der Art **entwicklung** (Code). Nur wenn `RUNPOD_API_KEY` gesetzt
   ist, im Nachtfenster 03:00 bis 09:00 und unter dem GPU-Deckel, mietet Auron einen Pod (A40, 48 GB, Volume angehängt).
2. Im Pod startet Ollama, holt das Modell (liegt nach dem ersten Mal auf dem Volume) und lädt es. Auron wartet (Zeitgrenze
   15 Minuten), bis es antwortet.
3. Die Aufträge laufen über die vorhandene Ollama-Anbindung (`llm/provider.py`), Ergebnis und Code-Entwürfe landen wie bisher im
   Vault und in `werkstatt`. Die übrigen Aufträge der Nacht laufen danach wie bisher auf dem Haupt-PC.
4. Im `finally`-Block wird der Pod gelöscht: bis zu 5 Versuche mit wachsender Pause, danach Kontrolle über die Pod-Liste, dass er weg
   ist. Gelingt das nicht: Ampel rot, Eintrag im Fehlerbericht, Hinweis in Alexa („Status“), Zeile oben im Nachtbericht, und neue
   Mieten sind gesperrt, bis der Wächter Entwarnung gibt.
5. Ohne Schlüssel, außerhalb der Nacht, bei erreichtem Deckel oder bei Fehlern in der Miete arbeitet Auron wie bisher auf dem
   Haupt-PC. Claude (API) wird dafür nie benutzt.

## Drei Sicherungen gegen einen vergessenen Pod

| Sicherung | Wo | Wann |
|---|---|---|
| `finally` mit Wiederholung und Bestätigung | `app/gpu_miete.py` (`sitzung`) | bei jeder Miete, auch bei Fehlern und bei Abbruch; auch wenn die Antwort auf „Pod anlegen“ verloren ging (dann Suche nach dem Pod-Namen) |
| Notbremse (Zeitgeber im selben Prozess) | `app/gpu_miete.py` | nach der erlaubten Laufzeit (kleinere Grenze aus Maximaldauer und Restbudget), auch wenn die Aufgabe hängt |
| **Wächter** | `backend/gpu_waechter.py`, alle 10 Minuten auf dem Mini-PC, außerdem einmal beim Backend-Start | listet ALLE Pods im Konto, unabhängig vom Hauptablauf |

**Achtung: Der Wächter löscht jeden Pod im Konto, der nicht von Auron stammt** (Name nicht `auron-gpu-...`, nicht im Protokoll),
dazu jeden Pod, der länger als die Maximaldauer läuft, nur gestoppt ist oder dessen Alter unbekannt ist. Das war ausdrücklich so
gewünscht. Wer in demselben RunPod-Konto eigene Pods hat, verliert sie. Entweder ein eigenes RunPod-Konto (oder eigenen
API-Schlüssel) nur für Auron benutzen oder `GPU_MIETE_FREMDE_LOESCHEN=nein` setzen (dann gelten nur noch Maximaldauer und
„gestoppt“ für Auron-Pods). Ein Pod, der nur gestoppt ist, wird weiter berechnet, deshalb wird auch er gelöscht.

## Erreichbarkeit: RunPod-Proxy statt Tailscale (Begründung)

- Proxy: `https://<pod-id>-11434.proxy.runpod.net`. Kein zusätzlicher Schlüssel, keine Zusatzsoftware im Pod, läuft mit dem
  Standard-Image `ollama/ollama`, TLS inklusive. Wenig, das beim Start schiefgehen kann.
- Tailscale wäre privater, braucht aber eine Installation im Pod bei jedem Start, einen weiteren Schlüssel in der Umgebung und ein
  Gerät mehr im Tailnet. Mehr Technik, die ungetestet ausfallen kann, und jeder Fehler dort verlängert die Mietzeit.
- Preis dafür, ehrlich: Ollama hat keine Anmeldung, die Adresse ist nur durch die zufällige Pod-ID geschützt. Der Pod lebt nur
  kurz. Es geht nur der Auftragstext in den Pod, nie ein Schlüssel. **Keine Geheimnisse in Code-Aufträge schreiben.**
- Der Proxy bricht Anfragen ab, die nach 100 Sekunden noch nicht zu antworten beginnen. Deshalb wird das Modell schon beim
  Pod-Start geladen (nicht über den Proxy) und Antworten werden gestreamt (`provider.ziel_exklusiv(..., stream=True)`).
  Quelle: RunPods eigener Hinweis zum Proxy, Cloudflare-Grenze 100 s.

## Was Sir am PC tun muss

### 1. RunPod vorbereiten (Bezeichnungen in der Konsole können abweichen)

1. Konto mit Guthaben. **Auto-Aufladen aus lassen** und nur so viel einzahlen, wie du verlieren willst (zusätzliche Bremse).
2. **Network Volume** anlegen (Storage): Rechenzentrum wählen, in dem die **A40** verfügbar ist, Größe ca. **50 GB** (das Modell hat
   rund 19 GB). Name z. B. `auron-modelle`. Die **Volume-ID** und das **Rechenzentrum** (z. B. `EU-RO-1`) notieren.
   Das Volume kostet auch ohne Pod eine Grundgebühr (laut meiner Annahme ca. 0,07 $ je GB und Monat, also bei 50 GB rund 3 $;
   in der Konsole prüfen). Diese Grundgebühr ist NICHT im GPU-Deckel.
3. **API-Schlüssel** erzeugen (Settings, API Keys). Nur für Auron, den Schlüssel nirgends sonst hinschreiben.

### 2. In die `.env` (Jarvis-Ordner, nur am PC bzw. Mini-PC, nie ins Repo)

```
RUNPOD_API_KEY=...                  # der Schlüssel; fehlt er, bleibt die GPU-Miete aus
GPU_MIETE_VOLUME_ID=...             # Pflicht
GPU_MIETE_RECHENZENTRUM=EU-RO-1     # das Rechenzentrum des Volumes (sonst sucht RunPod überall)
GPU_MIETE_VOLUME_GB=50              # nur für die Anzeige der Grundgebühr
# Alles Weitere ist optional (Standardwerte in Klammern):
GPU_MIETE_GPU=NVIDIA A40            # (NVIDIA A40)
GPU_MIETE_MODELL=qwen3-coder:30b    # (qwen3-coder:30b)
GPU_MIETE_DECKEL_EUR=40             # Monatsdeckel in EUR (40)
GPU_MIETE_MAX_STUNDEN=3             # längste Laufzeit eines Pods (3)
GPU_MIETE_VON=03:00                 # Nachtfenster (03:00 bis 09:00)
GPU_MIETE_BIS=09:00
GPU_MIETE_FREMDE_LOESCHEN=ja        # Wächter löscht fremde Pods (ja)
GPU_MIETE_TIMEOUT_S=3600            # Lese-Zeitgrenze je Antwortstück vom Pod (3600)
GPU_MIETE_START_TIMEOUT_S=900       # Wartezeit auf Ollama im Pod (900); beim ERSTEN Mal 1800 setzen
GPU_MIETE_NUM_CTX=32768             # Kontextlänge im Pod (32768)
GPU_MIETE_PREIS_USD_STUNDE=0.60     # Annahme, falls RunPod keinen Preis meldet (0,60)
GPU_MIETE_EUR_PRO_USD=0.92          # Wechselkurs-Annahme für die Kostenanzeige (0,92)
GPU_MIETE_IMAGE=ollama/ollama:latest  # besser auf eine feste Version setzen, sobald der erste Lauf geklappt hat
```

Der erste Pod-Start lädt das Modell (ca. 19 GB) auf das Volume und dauert deutlich länger als spätere. Dafür
`GPU_MIETE_START_TIMEOUT_S=1800` setzen. Für sehr lange Läufe ohne GPU gilt weiter `OLLAMA_NACHT_TIMEOUT` (Sekunden, Standard 1200).

### 3. Einspielen und neu starten

1. `REPO HOLEN.bat`, danach Backend **neu starten** (Python wurde geändert).
2. Auf dem **Mini-PC** den Wächter einrichten (einmal): `sudo bash "1 Starten/gpu_waechter_einrichten.sh"`.
   Prüfen: `systemctl list-timers auron-gpu-waechter.timer` und `sudo systemctl start auron-gpu-waechter.service && journalctl -u auron-gpu-waechter.service -n 20 --no-pager`.
   Erwartet: „0 Pod(s) geprüft“. Abbauen: `--entfernen`.
3. Die Nachtarbeit läuft dort, wo der Timer `jarvis-nachtarbeit.timer` ist (Mini-PC). Dort muss auch die `.env` mit dem Schlüssel liegen.

### 4. Testen (klein, mit offener RunPod-Konsole)

1. `1 Starten/GPU MIETE.bat`, Taste **1**: Stand. Erwartet `AKTIV=True`, Deckel 40 EUR, Ampel grün. (Ruft RunPod nicht auf.)
2. Taste **2** (Wächter jetzt): Erwartet `GEPRUEFT=0`, wenn nichts läuft. Das beweist, dass der Schlüssel gültig ist.
3. Kleinen Code-Nachtauftrag anlegen (Art `entwicklung`, z. B. „Schreibe eine Funktion, die eine Liste sortiert, mit unittest“).
4. `GPU MIETE.bat`, Taste **3**, Nummer des Auftrags. In der RunPod-Konsole sehen: Pod `auron-gpu-...` erscheint, läuft einige Minuten,
   **verschwindet wieder**. Danach Nachtauftrag und Vault-Notiz prüfen, Kostenanzeige (Chat: „Kostenstand“) prüfen.
5. Erst wenn das sauber klappt, über Nacht laufen lassen. Am Morgen die RunPod-Konsole ansehen: es darf **kein** Pod stehen.

Wenn etwas anders läuft als hier steht: `FEHLERBERICHT SENDEN.bat`, dann liest Claude den Abschnitt „GPU-Miete (RunPod)“.

## Kostendeckel (eigener Topf, in EUR)

- Getrennt von den 20 $ (Auron-Anfragen) und den 10 $ (Code-Deckel). Standard 40 EUR im Monat (`GPU_MIETE_DECKEL_EUR`).
- Verbrauch = Laufzeit mal Stundenpreis. Der Preis kommt aus der Antwort von RunPod (`costPerHr`), sonst gilt die Annahme
  `GPU_MIETE_PREIS_USD_STUNDE`. Umgerechnet mit `GPU_MIETE_EUR_PRO_USD`. Das ist eine **Schätzung**, die RunPod-Konsole zeigt den
  echten Stand. Laufende Pods zählen mit.
- Deckel erreicht: keine Miete mehr bis zum Monatswechsel, laute Zeile im Nachtbericht, Ampel „GPU-Miete“ gelb.
- Zu sehen im Chat („Kostenstand“, dritte Zeile), im Abend-Briefing, in der Kosten-Station von Auron, bei `GET /api/kosten`
  (Feld `gpu`) und `GET /api/gpu-miete/status`. Dort steht auch der Hinweis auf die Grundgebühr des Volumes.

## Pod notfalls von Hand löschen

1. In der RunPod-Konsole unter **Pods** den Pod `auron-gpu-...` suchen.
2. **Terminate** wählen (nicht „Stop“!). Ein nur gestoppter Pod wird weiter berechnet (Festplatte), das war der centron-Fehler.
3. Danach `GPU MIETE.bat`, Taste **2**: Der Wächter läuft, bestätigt, dass nichts mehr da ist, und hebt den Alarm auf.
   Solange der Alarm steht (Ampel rot), mietet Auron nichts.
4. Notfalls auch: Guthaben in RunPod auf 0 lassen bzw. den API-Schlüssel in den Settings löschen.

## Was neu ist (für Claude im Projekt)

- `backend/app/gpu_miete.py` (neu): Schlüssel nur aus der Umgebung, RunPod-Anfragen, `sitzung()`, Notbremse, Wächter, Journal
  unter `data/gpu_miete/` (`log.jsonl` nur anhängen, `alarm.json`), Kostentopf, Anzeige.
- `backend/gpu_waechter.py`, `1 Starten/gpu_waechter_einrichten.sh`, `1 Starten/GPU MIETE.bat` + `gpu_miete.ps1` (neu).
- `backend/llm/provider.py`: `ziel_exklusiv()` (nur Pod, nur nachts, nur im aufrufenden Thread), Ziel mit eigener Zeitgrenze,
  `num_ctx` und Stream. Ohne diesen Block ändert sich nichts.
- `backend/app/nachtauftraege.py`: `nacht_abarbeiten` aufgeteilt (`_abarbeiten`), `code_auf_gpu`, `gpu_ausdruecklich`.
- `kosten.py`, `ampel.py`, `alexa.py`, `nachtbericht.py`, `fehlerbericht.py`, `routes.py`, `main.py`, `dashboard/auron.html`: Anzeige und Anbindung.
- Tests: `backend/tests/test_gpu_miete.py`; `test_000_isolierung.py` lenkt `GPU_MIETE_PATH` um und entfernt `RUNPOD_API_KEY` aus der
  Testumgebung. Zusätzlich sperrt `geraeteschutz.netz_pruefen` im Testmodus jeden RunPod-Aufruf, der nicht an einen freigegebenen
  Stub auf 127.0.0.1 geht.

## Offene Punkte / bewusst nicht gebaut

- Nicht gegen echtes RunPod getestet (siehe oben): Feldnamen der Antworten (`costPerHr`, `desiredStatus`, `lastStartedAt`),
  `ollama run "<modell>" ""` zum Vorladen im Start-Skript, Verhalten von `GET /pods` nach dem Löschen.
- Kein Knopf in Auron für „diesen Auftrag auf die GPU“. Der ausdrückliche Befehl geht über `GPU MIETE.bat` (Taste 3) bzw.
  `POST /api/gpu-miete/auftrag`.
- Läuft das Backend auf einem anderen Rechner als der Wächter (je eigener `data`-Ordner), kennt der Wächter das Journal des
  anderen nicht. Er erkennt Auron-Pods dann am Namen und am Alter im Namen, kann aber deren Kosten nicht verbuchen.
- Wechselkurs und Preis sind Annahmen. Nachsehen und in der `.env` anpassen.

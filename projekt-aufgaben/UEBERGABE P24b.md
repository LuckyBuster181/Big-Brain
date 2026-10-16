# Übergabe P24b an den PC (16.10.2026): GPU per Chat und Alexa steuern, Fehler melden (Banner, Alexa-Alarm)

Wunsch Sir 16.10.: Auron soll die GPU-Miete steuern können, den Status sagen und warnen, wenn irgendwo im ganzen System etwas
nicht geht. Warnung als echter Alarm über Alexa, „ähnlich wie eine Terminerinnerung“.

**Stand: gebaut und mit Ersatz-Objekten getestet. Der Alexa-Alarm ist ungetestet gegen das echte Amazon.**

## Wichtig vorab: Was Amazon erlaubt (nachgelesen am 16.10.2026)

- Eine **echte Erinnerung wie bei einem Termin** (Reminders-API) kann ein Skill **nur innerhalb einer Sitzung anlegen**, also wenn
  du gerade mit dem Skill sprichst. Außerhalb davon geht nur Ändern und Löschen. Auron kann sich nachts deshalb **keine neue
  Erinnerung anlegen**. Das ist eine Grenze von Amazon, nicht von Auron.
- Möglich ist eine **Benachrichtigung** (Proactive Events, Ereignis „Nachrichten-Hinweis“). Das Echo zeigt den **gelben Ring**.
  Auf Nachfrage („Alexa, Benachrichtigungen“) sagt es: „Du hast 1 neue ungelesene Nachricht von Auron Alarm GPU-Miete“.
  Frei wählbar ist nur dieser Absendername, einen ganzen Satz Text gibt es nicht. Die Einzelheiten nennt dann
  „Computer, frag Agent Auron nach dem Status“ (siehe unten) und der Banner in Auron.
- **Unsicher:** Aus der Amazon-Dokumentation geht nicht eindeutig hervor, ob dieses Ereignis für Deutsch (de-DE) angeboten wird
  und ob ein Skill im Entwicklungsmodus die Benachrichtigung auf deinem Echo auslöst. Das zeigt erst der Test (Schritt 5).
  Geht es nicht, sagt der Test, was Amazon antwortet (z. B. HTTP 400 oder 403). Dann nehmen wir einen anderen Weg
  (z. B. Telegram oder eine Ansage über die Sonos-Box; beides ist nicht gebaut).

## Was neu ist

1. **Chat-Befehle** (ohne KI, 0 Cent): „GPU Status“, „GPU aufräumen“ (Wächter sofort), „Code-Auftrag 7 auf die GPU“. Der letzte
   fragt nach und mietet **erst nach „ja“** (gilt 2 Minuten), weil es Geld kostet.
2. **Alexa:**
   - „Computer, frag Agent Auron nach dem Status“ nennt jetzt zuerst **alle roten Bereiche der Ampel** („Achtung Sir, es gibt
     2 Fehler: …“), sonst „Sonst läuft alles.“. Ein laufender GPU-Pod wird genannt. Die Einzelheiten stehen auch in der Alexa-App.
   - Neuer Befehl „Code-Auftrag 7 auf die GPU“ (Alexa fragt vorher: „Für Auftrag 7 jetzt eine GPU bei RunPod mieten? Das kostet
     Geld. Richtig?“). Neue Aktion „GPU aufräumen“ in der Whitelist.
   - Dafür muss das **Interaktionsmodell neu hochgeladen** werden (Schritt 1).
3. **Banner in Auron:** Ist ein Bereich der Ampel rot, steht oben ein rotes Banner mit dem Bereich und dem Grund
   (Vault einlesen, Aufgaben-Loop, Studium, Nachtarbeit, Kosten, GPU-Miete, …). Es prüft jede Minute. Der Prüfstand testet es.
4. **Alarm** (`backend/app/alarm.py`): Alle 5 Minuten prüft das Backend die Ampel. Wird ein Bereich **neu rot**, geht **eine**
   Meldung raus (Alexa-Benachrichtigung, sofern eingerichtet; immer auch in den Fehlerbericht). Bleibt er rot, kommt nach
   6 Stunden eine Erinnerung. Wird er wieder grün, ist alles vergessen. Der **GPU-Alarm** (Pod nicht gelöscht) geht
   sofort raus und zusätzlich vom Wächter auf dem Mini-PC, auch wenn das Backend aus ist.
   Ist kein Weg eingerichtet, versucht Auron es beim nächsten Lauf wieder.

## Was Sir tun muss

Alles ab Schritt 2 betrifft nur den Alexa-Alarm. Banner, Chat-Befehle und der erweiterte Status laufen nach `REPO HOLEN.bat`
und Neustart auch ohne.

### 0. Einspielen
`REPO HOLEN.bat`, Backend **neu starten** (Python geändert), im Browser Strg+F5 (HTML geändert).

### 1. Alexa-Modell neu hochladen
Alexa-Developer-Konsole, Skill „Agent Auron“, Build, **JSON-Editor**: Inhalt von `backend/alexa/interaktionsmodell_de.json`
einfügen, speichern, **Modell bauen**. (Neu: `GpuAuftragIntent`, mehr Sätze für den Status, Aktion „gpu aufräumen“.)
Danach im Simulator oder am Echo testen: „Computer, frag Agent Auron nach dem Status“.

### 2. Skill-Manifest: Benachrichtigungen erlauben
In der Developer-Konsole (oder per ASK-CLI) im **Skill-Manifest** ergänzen. Beispiel nach der Amazon-Dokumentation, die genauen
Feldnamen kann ich von hier aus nicht prüfen:

```json
"permissions": [ { "name": "alexa::devices:all:notifications:write" } ],
"events": {
  "publications": [ { "eventName": "AMAZON.MessageAlert.Activated" } ],
  "endpoint": { "uri": "<die Funnel-Adresse des Skills, wie beim bisherigen Endpunkt, endet auf /api/alexa>" }
}
```
Dann Skill speichern und das Modell erneut bauen.

### 3. Zugangsdaten in die `.env` (nur am PC bzw. Mini-PC, nie ins Repo)
In der Developer-Konsole beim Skill unter **Berechtigungen** (Permissions) gibt es die Zugangsdaten des Skills
(Client-ID und Client-Secret, „Alexa Skill Messaging“, Login with Amazon). Eintragen:

```
ALEXA_ALARM_CLIENT_ID=...
ALEXA_ALARM_CLIENT_SECRET=...
ALEXA_ALARM_REGION=EU              # (EU, Standard) oder NA / FE
ALEXA_ALARM_STUFE=development      # (development, solange der Skill im Entwicklungsmodus ist) oder live
ALEXA_NUTZER_ID=amzn1.ask.account....   # optional: deine Alexa-Kennung; sonst lernt Auron sie aus deiner ersten Anfrage
ALARM_INTERVALL_MIN=5              # (5) wie oft die Ampel geprüft wird
ALARM_WIEDERHOLUNG_STUNDEN=6       # (6) Erinnerung bei lange rotem Bereich
# Ausschalten: ALARM_AUS=1 (alles) oder ALEXA_ALARM_AUS=1 (nur der Alexa-Weg)
```
Neustart des Backends.

### 4. In der Alexa-App erlauben
Alexa-App, Skills, „Agent Auron“, Einstellungen: **Benachrichtigungen erlauben** (Berechtigung des Skills annehmen).

### 5. Testen
1. Eine Anfrage an den Skill sprechen („Computer, frag Agent Auron nach dem Status“), damit Auron deine Kennung kennt
   (nicht nötig, wenn `ALEXA_NUTZER_ID` in der `.env` steht).
2. `1 Starten/GPU MIETE.bat`, Taste **4** (Alexa-Alarm testen). Es zeigt, was noch fehlt, und schickt eine Test-Benachrichtigung.
3. Erwartet: `GESENDET=True`, am Echo der **gelbe Ring**, „Alexa, Benachrichtigungen“ nennt „Auron Alarm Test“.
4. Bei `GESENDET=False` steht der Grund da (z. B. „Amazon lehnt die Angaben ab“ = vermutlich Ereignis oder Sprache nicht
   erlaubt; „Berechtigung fehlt“ = Schritt 2 oder 4 fehlt; „Client-ID und Secret prüfen“ = Schritt 3). Schick mir den Text
   oder `FEHLERBERICHT SENDEN.bat`.

## Grenzen (ehrlich)

- **Ist das Backend selbst aus**, meldet es nichts. Das sieht nur der Banner am PC („Keine Verbindung zum Mini-PC“). Der GPU-Wächter
  auf dem Mini-PC läuft unabhängig und meldet einen GPU-Alarm trotzdem.
- Alexa-Benachrichtigungen sind **Hinweise**, keine Weckruf-Erinnerung. Das Echo wird nicht laut, es leuchtet gelb. Amazon begrenzt
  die Zahl der Benachrichtigungen je Kunde und Tag (für Live-Skills; die Zahl nennt Amazon nicht).
- Eine echte Erinnerung ließe sich nur anlegen, wenn du gerade mit dem Skill sprichst (z. B. „Erinnere mich in 10 Minuten an …“
  als neuer Wunsch). Das ist nicht gebaut.

## Technisch (für Claude im Projekt)

- Neu: `backend/app/gpu_befehl.py`, `alarm.py`, `alexa_alarm.py`; Tests `backend/tests/test_p24b.py` (Stub auf 127.0.0.1 für
  Login with Amazon und Proactive Events, `ALEXA_ALARM_TOKEN_URL`/`ALEXA_ALARM_EVENT_URL` gelten nur für 127.0.0.1).
- Geändert: `alexa.py` (Status, `GpuAuftragIntent`, Aktion `gpu_aufraeumen`, Kennung lernen), `alexa/interaktionsmodell_de.json`,
  `alltag.py` und `chat_ablauf.py` (Befehle, „ja“), `nachtauftraege.py` (`gpu_ausdruecklich_starten`), `routes.py`
  (`/api/alarm/status`, `/api/alarm/test`), `main.py` (Hintergrundprüfung), `gpu_waechter.py`, `gpu_miete.py` (Alarm sofort),
  `dashboard/auron.html` (Banner), `cloud_pruefstand/lauf.py` (Banner-Prüfung), `1 Starten/GPU MIETE.bat` + `gpu_miete.ps1`.
- Quellen: Amazon „Reminders REST API Reference“ (Anlegen nur im Skill-Kontext), „Proactive Events API“ und „Schemas for
  proactive events“ (`AMAZON.MessageAlert.Activated`: Absendername, Anzahl, Status; keine freie Textzeile).

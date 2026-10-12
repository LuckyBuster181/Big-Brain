---
typ: projekt-aufgabe
nummer: P19
titel: Alexa-Skill „frag Auron“
phase: 9 (Zuhause und Geräte)
fuer: Claude Code
status: offen
erstellt: 2026-10-12
quelle: Gespräch mit Sir am 12.10.2026 (Frage 31 der Gesamtkarte: ja)
kosten: laufend 0 €, Ausnahme Vault-Antworten, bei denen Claude einspringt
---

# P19 – Alexa-Skill „frag Auron“

## Ziel

Sir spricht über seinen Echo Dot (2. Gen) mit Auron: **„Computer, frag Auron …“**.
Dafür entsteht ein eigener Custom Skill in der Amazon Developer Console, nur im
Entwicklungsmodus („Development“), **nicht veröffentlicht**. Ein Skill im
Entwicklungsmodus läuft auf jedem Echo, der mit Sirs Amazon-Konto verbunden ist und
auf Deutsch eingestellt ist, also auch auf dem alten Echo Dot 2. Gen.

Auron läuft auf dem Mini-PC (immer an). Der Skill ruft einen neuen Endpunkt im
Auron-Backend auf, prüft dort die Anfrage und leitet sie an die **bestehenden**
Funktionen weiter. Neue Fachlogik entsteht nur, wo es keine gibt.

## Festlegungen von Sir (12.10.2026)

- Weckwort ist bei Sir bereits „Computer“. Aufrufname des Skills: „Auron“.
- Licht und Sonos laufen schon über bestehende Alexa-Skills. Die bleiben unangetastet.
- Sieben Fähigkeiten (Teil D): Vault-Frage, Briefing, „Merk dir …“, Status, Termine,
  Nachtauftrag, feste Aktionen.
- Aktionen per Stimme **nur aus einer festen Whitelist im Code** (Teil E). Kein neuer
  oder ungeprüfter Code auf Zuruf, kein „schreib und führ aus“. Entspricht Sirs
  Ausführungsregel (nur geprüfte .bat/Abläufe, Entscheidung 10.10.).
- **Bewusst nicht** über den Sprachweg: keine Trades, keine Käufe, kein Mailversand,
  kein Löschen. Grund: Fehlauslösung per Stimme ist zu leicht.
- Antworten so kurz, dass Alexa sie in ca. 8–10 Sekunden vorliest. Kurz halten,
  **nicht mitten im Satz abschneiden**.
- Getrennt halten (nur Hinweis, nicht Teil des Skills): Der große PC lässt sich über
  eine IKEA-Steckdose per Alexa einschalten (Steckdose + BIOS „bei Stromzufuhr
  einschalten“). Das läuft komplett über Sirs bestehendes Alexa-System, **nicht** über
  den Auron-Skill. Claude Code baut dafür nichts.

## Regeln für Claude Code

1. CLAUDE.md im Repo gilt vollständig. Besonders: Tests nur in der Cloud bzw. mit
   Stubs, **nie auf dem Haupt-PC** (Regel 12, Vorfall 11.10.). Kein Test spricht mit
   Amazon, Tailscale oder einem echten Gerät. Netz-Wächter `tests/testschutz.py` gilt.
2. `.env` nie lesen oder schreiben. Neue Einstellungen trägt Sir selbst ein (Teil H).
3. Kleine Schritte. Reihenfolge: Teil C (Endpunkt + Signaturprüfung + Tests), dann
   Teil D Intent für Intent, jeweils mit Tests. Nichts Ungetestetes stapeln.
4. Neue Python-Pakete vermeiden. `cryptography` (für die Signaturprüfung) und
   `requests` stehen schon in `backend/requirements.txt`.
5. Kein Push direkt auf `main` (Sir 11.10.). Pull Request, Commit-Nachricht auf
   Deutsch: was geändert, ob getestet, was Sir am PC tun muss.
6. Vor der Lieferung: alle Tests und Cloud-Prüfstand ohne Fehler, GitHub Actions grün.

---

## Teil A – Erreichbarkeit (zwei Wege, Sir entscheidet nach dem Test)

### Was Amazon verlangt (laut Amazon-Dokumentation, geprüft 12.10.)

- Endpunkt per HTTPS auf **Port 443**, aus dem Internet erreichbar.
- Zertifikat einer von Amazon anerkannten Zertifizierungsstelle; der Hostname muss
  im Zertifikat (SAN) stehen. Let's-Encrypt-Zertifikate gelten als anerkannt.
- Jede Anfrage prüfen: Signatur (`SignatureCertChainUrl`, `Signature-256`) und
  Zeitstempel (höchstens 150 Sekunden Abweichung). Bei Fehler: HTTP 400.
- Antwortzeit knapp halten. Amazon nennt auf der Endpunkt-Seite keine feste Grenze;
  in der Praxis gelten ca. 8 Sekunden. **Auron plant mit 6 Sekunden** (Teil D,
  Zeitbudget).

### Wichtiger Befund zum bestehenden Tunnel

Die Adresse `https://auron.tailc68142.ts.net` läuft über **`tailscale serve`**. Das ist
nur im eigenen Tailnet erreichbar (Handy, PCs), **nicht für Amazon**. Für Amazon muss
**Tailscale Funnel** eingeschaltet werden (öffentlich).

Funnel geht nur auf den Ports 443, 8443 und 10000. Alexa verlangt 443. Laut
Tailscale-Dokumentation ist ein Port mit Funnel **komplett öffentlich**; Serve und
Funnel gehen nicht gleichzeitig auf demselben Port. Würde man Funnel auf dem
bestehenden Knoten `auron` einschalten, wäre die ganze Auron-Oberfläche
(`/auron`, Handy-Zugang) aus dem Internet erreichbar. Geschützt wäre sie dann nur
noch durch den Zugangscode in `app/handy_zugang.py`. **Das ist keine gute Idee.**

Deshalb: **eigener, zweiter Tailscale-Knoten nur für Alexa.**

### Weg A (bevorzugt): Amazon → Funnel-Knoten „auron-alexa“ → Auron

```
Echo Dot → Amazon → https://auron-alexa.tailc68142.ts.net/api/alexa   (Funnel, öffentlich, Port 443)
                    → Mini-PC 127.0.0.1:8000/api/alexa                   (nur dieser Pfad)
Handy    → https://auron.tailc68142.ts.net/auron                      (wie bisher, nur Tailnet)
```

1. Auf dem Mini-PC einen zweiten `tailscaled` starten (eigener Zustandsordner, eigener
   Socket, `--tun=userspace-networking`, Hostname `auron-alexa`), als systemd-Dienst
   `tailscaled-alexa`. Alternative, falls Docker auf dem Mini-PC läuft: Container
   `tailscale/tailscale` mit `TS_USERSPACE=true`, `network_mode: host`.
   Ob Docker auf dem Mini-PC installiert ist, ist **ungeprüft**.
2. Funnel nur für den einen Pfad:
   `tailscale --socket=<socket von auron-alexa> funnel --bg --set-path=/api/alexa http://127.0.0.1:8000/api/alexa`
   Genaues Pfad-Verhalten von `--set-path` (wird der Pfad an das Ziel angehängt oder
   ersetzt?) nach dem Einrichten mit `curl` prüfen, nicht raten.
3. In der Tailnet-Richtlinie (Tailscale-Admin, „Access Controls“) braucht der Knoten
   das Attribut `funnel`. Tailscale bietet das beim ersten `funnel`-Befehl selbst an.
4. Prüfschritt Erreichbarkeit (von außerhalb des Tailnets, z. B. Handy im Mobilfunk mit
   Tailscale **aus**):
   - `https://auron-alexa.tailc68142.ts.net/` → darf **nichts** von Auron zeigen (404).
   - `https://auron-alexa.tailc68142.ts.net/auron` → 404.
   - `POST https://auron-alexa.tailc68142.ts.net/api/alexa` ohne Signatur → **400**.
5. **Prüfschritt Zertifikat:** In der Developer Console Endpunkt eintragen (Teil B,
   Schritt 6) und im Simulator „Computer, öffne Auron“ testen. Kommt eine Antwort,
   akzeptiert Amazon das Zertifikat. Kommt „Es gab ein Problem mit der Antwort des
   angeforderten Skills“ und im Auron-Log **keine** Anfrage, liegt es am Zertifikat
   oder an der Erreichbarkeit → Weg B prüfen.

Für Claude Code: Das Einrichtungsskript für den Mini-PC als
`1 Starten/alexa_tunnel_einrichten.sh` (ASCII, LF), Sir startet es auf dem Mini-PC
selbst. Claude Code führt es nie aus.

Hinweis zur Middleware: Anfragen über Funnel kommen bei uvicorn von `127.0.0.1` an.
Ob Tailscale dabei `X-Forwarded-For` setzt, ist ungeprüft. Der Alexa-Endpunkt darf
sich deshalb **nie** auf die Absenderadresse verlassen, nur auf die Signaturprüfung.
Andere Pfade sind über `auron-alexa` gar nicht erreichbar (Schritt 2).

### Weg B (Rückfall, nur wenn Amazon das Zertifikat ablehnt): Skill → Lambda → Tunnel

Ehrliche Einordnung: Lambda löst **nur** ein Zertifikatsproblem. Auch die Lambda-Funktion
läuft im öffentlichen Internet und braucht den öffentlichen Funnel-Knoten aus Weg A.
Da Tailscale Let's-Encrypt-Zertifikate nutzt, ist Weg B voraussichtlich nicht nötig.

```
Echo Dot → Amazon → Lambda (dünner Weiterleiter) → https://auron-alexa.tailc68142.ts.net/api/alexa
```

- **Variante B1 (einfacher): „Alexa-hosted (Python)“** beim Anlegen des Skills
  wählen. Amazon stellt die Lambda-Funktion selbst, kein eigenes AWS-Konto nötig.
  Laut Amazon „unbegrenzt kostenlose Lambda-Anfragen“ für Alexa-hosted Skills → 0 €.
- **Variante B2: eigenes AWS-Konto**, Lambda in `eu-west-1` (Irland), Auslöser
  „Alexa Skills Kit“ mit Skill-ID-Prüfung. Kostenloses Kontingent: 1 Mio. Anfragen
  und 400.000 GB-Sekunden im Monat, laut Sekundärquellen dauerhaft. Achtung:
  AWS-Konten, die nach dem 15.07.2025 angelegt wurden, laufen über ein neues
  Guthaben-Modell. Vor dem Anlegen auf der offiziellen AWS-Preisseite prüfen.
  Sir braucht wenige hundert Anfragen im Monat → **0 €**.
- Die Lambda-Funktion (ca. 30 Zeilen Python) macht nur: Anfrage-Text unverändert per
  HTTPS an Auron weiterreichen, dazu Kopfzeile `X-Auron-Weiterleiter` mit HMAC-SHA256
  über den Text (Schlüssel `ALEXA_WEITERLEITER_SCHLUESSEL`, steht in der Lambda und
  in Sirs `.env`), Antwort unverändert zurückgeben, Zeitlimit 6 s.
- Auron akzeptiert dann **entweder** eine gültige Alexa-Signatur **oder** einen
  gültigen HMAC. Zeitstempel- und Skill-ID-Prüfung gelten in beiden Fällen.
- Claude Code baut die HMAC-Prüfung erst, wenn Sir sich für Weg B entscheidet.

---

## Teil B – Schritte in der Developer Console (macht Sir, Claude Code beschreibt)

1. `https://developer.amazon.com/alexa/console/ask` öffnen, mit **demselben
   Amazon-Konto** anmelden, mit dem der Echo Dot verbunden ist.
2. „Skill erstellen“: Name „Auron“, Sprache **Deutsch (DE)**, Typ **Custom**,
   Hosting **„Provision your own“** (Weg A) bzw. „Alexa-hosted (Python)“ (Weg B1),
   Vorlage „Start from Scratch“.
3. „Invocations → Skill Invocation Name“: `auron`.
   **Ungeprüft:** Amazon erlaubt einwortige Aufrufnamen eigentlich nur für Marken
   bzw. im Deutschen für zusammengesetzte Wörter. Ob die Console das im
   Entwicklungsmodus trotzdem baut, zeigt der Build (Schritt 5). Wenn nicht,
   Ausweichnamen in dieser Reihenfolge: „auron zentrale“, „mein auron“.
4. „Interaction Model → JSON Editor“: Modell aus Teil C1 einfügen, „Save“.
5. „Build Skill“. Fehler im JSON zeigt die Console sofort an.
6. „Endpoint“: HTTPS, „Default Region“:
   `https://auron-alexa.tailc68142.ts.net/api/alexa`,
   Zertifikat: „My development endpoint has a certificate from a trusted certificate
   authority“. Speichern.
7. Skill-ID oben kopieren (`amzn1.ask.skill....`) und in Sirs `.env` eintragen
   (Teil H). Erst danach antwortet Auron.
8. Reiter „Test“: „Skill testing is enabled in: **Development**“ einstellen.
   Ab jetzt ist der Skill auf Sirs Echo-Geräten verfügbar. Nicht veröffentlichen,
   keine Zertifizierung einreichen.
9. Echo Dot: in der Alexa-App prüfen, dass die Gerätesprache **Deutsch** ist.

---

## Teil C – Backend in Auron

### C1. Interaktionsmodell (für Teil B, Schritt 4)

Claude Code legt es als `backend/alexa/interaktionsmodell_de.json` ins Repo, damit es
versioniert ist. Grundgerüst (vollständig, Claude Code darf Beispielsätze ergänzen):

```json
{
  "interactionModel": {
    "languageModel": {
      "invocationName": "auron",
      "intents": [
        {"name": "VaultFrageIntent",
         "slots": [{"name": "frage", "type": "AMAZON.SearchQuery"}],
         "samples": ["nach {frage}", "was {frage}", "wie {frage}", "wann {frage}", "wo {frage}",
                     "wer {frage}", "warum {frage}", "welche {frage}", "ob {frage}", "zu {frage}"]},
        {"name": "BriefingIntent", "slots": [],
         "samples": ["das briefing", "lies mir das briefing vor", "was steht im briefing",
                     "was ist heute wichtig", "was gibt es neues"]},
        {"name": "MerkenIntent",
         "slots": [{"name": "notiz", "type": "AMAZON.SearchQuery"}],
         "samples": ["merk dir {notiz}", "merke dir {notiz}", "notiere {notiz}", "schreib auf {notiz}"]},
        {"name": "StatusIntent", "slots": [],
         "samples": ["status", "wie ist der status", "läuft die nachtarbeit", "was hat die nacht gebracht",
                     "wie viel ist vom rahmen verbraucht", "wie stehen die kosten"]},
        {"name": "TermineIntent",
         "slots": [{"name": "tag", "type": "AMAZON.DATE"}],
         "samples": ["was steht {tag} an", "welche termine habe ich {tag}", "termine {tag}",
                     "was habe ich {tag}", "was steht an", "welche termine habe ich"]},
        {"name": "NachtauftragIntent",
         "slots": [{"name": "auftrag", "type": "AMAZON.SearchQuery"}],
         "samples": ["nimm {auftrag} in die nachtarbeit auf", "nachtauftrag {auftrag}",
                     "für die nachtarbeit {auftrag}"]},
        {"name": "AktionIntent",
         "slots": [{"name": "aktion", "type": "AURON_AKTION"}],
         "samples": ["starte {aktion}", "{aktion} starten", "führe {aktion} aus", "{aktion}"]},
        {"name": "LetzteAntwortIntent", "slots": [],
         "samples": ["nach der letzten antwort", "die letzte antwort", "ist die antwort fertig"]},
        {"name": "AMAZON.HelpIntent", "samples": []},
        {"name": "AMAZON.StopIntent", "samples": []},
        {"name": "AMAZON.CancelIntent", "samples": []},
        {"name": "AMAZON.NavigateHomeIntent", "samples": []},
        {"name": "AMAZON.FallbackIntent", "samples": []}
      ],
      "types": [
        {"name": "AURON_AKTION", "values": [
          {"id": "nachtarbeit_starten", "name": {"value": "nachtarbeit",
            "synonyms": ["die nachtarbeit", "nachtschicht"]}},
          {"id": "vault_einlesen", "name": {"value": "vault neu einlesen",
            "synonyms": ["vault einlesen", "den vault neu einlesen", "neu einlesen"]}},
          {"id": "pruefen_hintergrund", "name": {"value": "prüflauf",
            "synonyms": ["den prüflauf", "inhaltsprüfung", "die inhaltsprüfung"]}}
        ]}
      ]
    },
    "dialog": {
      "delegationStrategy": "ALWAYS",
      "intents": [
        {"name": "MerkenIntent", "confirmationRequired": true,
         "prompts": {"confirmation": "Confirm.Intent.Merken"},
         "slots": [{"name": "notiz", "type": "AMAZON.SearchQuery", "elicitationRequired": true,
                    "confirmationRequired": false, "prompts": {"elicitation": "Elicit.Slot.Merken.notiz"}}]},
        {"name": "NachtauftragIntent", "confirmationRequired": true,
         "prompts": {"confirmation": "Confirm.Intent.Nachtauftrag"},
         "slots": [{"name": "auftrag", "type": "AMAZON.SearchQuery", "elicitationRequired": true,
                    "confirmationRequired": false, "prompts": {"elicitation": "Elicit.Slot.Nachtauftrag.auftrag"}}]},
        {"name": "AktionIntent", "confirmationRequired": true,
         "prompts": {"confirmation": "Confirm.Intent.Aktion"},
         "slots": [{"name": "aktion", "type": "AURON_AKTION", "elicitationRequired": true,
                    "confirmationRequired": false, "prompts": {"elicitation": "Elicit.Slot.Aktion.aktion"}}]}
      ]
    },
    "prompts": [
      {"id": "Confirm.Intent.Merken", "variations": [{"type": "PlainText", "value": "Soll ich mir merken: {notiz}?"}]},
      {"id": "Elicit.Slot.Merken.notiz", "variations": [{"type": "PlainText", "value": "Was soll ich mir merken, Sir?"}]},
      {"id": "Confirm.Intent.Nachtauftrag", "variations": [{"type": "PlainText", "value": "Für die Nachtarbeit: {auftrag}. Richtig?"}]},
      {"id": "Elicit.Slot.Nachtauftrag.auftrag", "variations": [{"type": "PlainText", "value": "Welcher Auftrag für die Nacht, Sir?"}]},
      {"id": "Confirm.Intent.Aktion", "variations": [{"type": "PlainText", "value": "{aktion} jetzt starten?"}]},
      {"id": "Elicit.Slot.Aktion.aktion", "variations": [{"type": "PlainText", "value": "Welche Aktion, Sir?"}]}
    ]
  }
}
```

Hinweise dazu:
- `AMAZON.SearchQuery` gibt es auf Deutsch. Jede Beispielzeile braucht ein
  Trägerwort („nach“, „was“ …), nur der Platzhalter allein ist nicht erlaubt, und nur
  ein SearchQuery-Platzhalter je Intent. Folge: Bei „frag Auron, was steht im Plan
  zum Gartenhaus“ kommt nur „steht im Plan zum Gartenhaus“ an. Für die Vault-Suche
  reicht das (Inhaltswörter).
- Bestätigung („Soll ich mir merken …?“) fragt Alexa selbst (Dialog-Delegation).
  Auron handelt nur bei `intent.confirmationStatus == "CONFIRMED"`.
- Das Modell ist gegen die Console **ungeprüft**. Der JSON-Editor meldet Fehler
  sofort; dann anpassen und die Änderung im Repo nachziehen.

### C2. Neue Dateien und Änderungen

| Datei | Inhalt |
|---|---|
| `backend/app/alexa_pruefung.py` (neu) | Signatur-, Zeitstempel- und Skill-ID-Prüfung (C3) |
| `backend/app/alexa.py` (neu) | Intent-Routing, Antwortaufbau, Kürzen, Whitelist `ALEXA_AKTIONEN` (Teil D/E) |
| `backend/app/routes.py` | Route `POST /api/alexa` |
| `backend/app/handy_zugang.py` | Ausnahme nur für `POST /api/alexa` (C4) |
| `backend/app/kosten.py` | `FUNKTIONEN["alexa"] = "Alexa"`, damit Alexa-Kosten in der Kosten-Karte eigen erscheinen |
| `backend/alexa/interaktionsmodell_de.json` (neu) | Modell aus C1 |
| `backend/tests/test_alexa.py` (neu) | Tests (Teil F1) |
| `backend/cloud_pruefstand/…` | eine Prüfung: `POST /api/alexa` ohne Signatur → 400 |
| `1 Starten/alexa_tunnel_einrichten.sh` (neu) | Einrichtung Funnel-Knoten (Teil A) |

### C3. Route und Prüfung

```
POST /api/alexa
```

Ablauf je Anfrage, in dieser Reihenfolge:

1. `ALEXA_AKTIV` nicht `1` → **404** (Endpunkt ist ohne Sirs Freigabe aus).
2. Rohen Text lesen (`await request.body()`), **vor** jedem JSON-Parsen. Größe
   begrenzen (z. B. 64 KB, sonst 400).
3. Signatur prüfen (`alexa_pruefung.signatur_pruefen(kopfzeilen, rohtext)`):
   - `SignatureCertChainUrl` normalisieren (`..` auflösen). Pflicht: Schema `https`,
     Host `s3.amazonaws.com` (Groß/klein egal), Pfad beginnt mit `/echo.api/`
     (Groß/klein **beachten**), Port nur 443 oder keiner.
   - Zertifikatskette von dieser Adresse laden (Zeitlimit 2 s), im Speicher je URL
     zwischenspeichern bis zum Ablauf des Zertifikats. Laden als eigene Funktion,
     damit Tests sie ersetzen können.
   - Signaturzertifikat: gültig (nicht abgelaufen, nicht vor `not_valid_before`),
     SAN enthält `echo-api.amazon.com`, Kette führt zu einer vertrauenswürdigen
     Wurzel (Zertifikatsliste aus `certifi`). Umsetzung mit
     `cryptography.x509.verification` (`PolicyBuilder`, `Store`).
     **Ungeprüft:** ob der dortige Server-Prüfer die Amazon-Kette wegen der
     Schlüsselverwendung (EKU) ablehnt. Wenn ja, Kette und SAN von Hand prüfen.
     Klärt sich beim ersten Simulator-Test.
   - `Signature-256` Base64-dekodieren und mit dem öffentlichen Schlüssel
     (RSA, PKCS#1 v1.5, SHA-256) gegen den **rohen** Text prüfen.
   - Jeder Fehler → **400**, Grund nur ins Log, nicht in die Antwort.
4. JSON parsen. `request.timestamp` höchstens **150 s** von jetzt entfernt → sonst 400.
5. `session.application.applicationId` (bzw. `context.System.application.applicationId`)
   muss gleich `ALEXA_SKILL_ID` sein → sonst 400.
   Optional: Ist `ALEXA_NUTZER_ID` gesetzt, muss `context.System.user.userId` passen.
6. Erst jetzt an `alexa.verarbeiten(anfrage)` weitergeben.
7. Antwort immer im Alexa-Format:

```json
{"version": "1.0",
 "response": {
   "outputSpeech": {"type": "PlainText", "text": "…"},
   "card": {"type": "Simple", "title": "Auron", "content": "… volle Antwort und Quellen …"},
   "shouldEndSession": true}}
```

Die Karte erscheint in der Alexa-App. Dort stehen volle Antwort, alle Quellen und bei
Claude-Antworten die Kosten.

### C4. Zugangsschutz (Middleware)

`app/handy_zugang.py` lässt heute nur lokale Anfragen, Tailnet-Geräte und Anfragen mit
Zugangscode durch. Amazon hat nichts davon. Deshalb in `middleware` **eine** Ausnahme:
Methode `POST` und Pfad genau `/api/alexa` → durchlassen, der Schutz liegt dann
vollständig in C3. Nicht über die Liste `ERLAUBT` lösen (die verlangt den
Zugangscode). Kommentar mit Datum und Grund dazuschreiben. Test: `GET /api/alexa`
und jeder andere Pfad bleiben ohne Code gesperrt.

### C5. Protokoll

Jede Anfrage eine Zeile in `data/alexa_log.jsonl`: Zeit, Intent, Ergebnis
(ok/abgelehnt/fehler), Dauer in ms, ob Claude beteiligt war, Kosten in USD.
**Keine** Inhalte (Fragen, Notizen) ins Protokoll. Fehler zusätzlich über
`app/fehlerbericht.py`, damit sie im FEHLERBERICHT landen.

---

## Teil D – Fähigkeiten (Intents) und Routing zu den bestehenden Funktionen

Allgemein für alle Intents:

- **Zeitbudget 6 s.** Was länger dauern kann, läuft in einem Hintergrund-Thread mit
  Zeitlimit. Ist es nach 6 s nicht fertig: Antwort „Das dauert etwas länger, Sir.
  Fragen Sie gleich: Computer, frag Auron nach der letzten Antwort.“ Das Ergebnis
  wird in `data/alexa_letzte_antwort.json` abgelegt (Zeit, Intent, Text, Quellen,
  höchstens 30 Minuten gültig) und mit `LetzteAntwortIntent` vorgelesen.
- **Sprechlänge:** Konstante `SPRACH_MAX_ZEICHEN = 220` (ca. 8–10 s). Zu lange Texte
  werden **an der letzten Satzgrenze** davor beendet, nie mitten im Satz, danach
  „Mehr steht in der Alexa-App.“ Volle Antwort immer in die Karte. Kein Markdown,
  keine Listenzeichen, keine Links im gesprochenen Text (Funktion `fuer_sprache()`).
  Wert nach dem ersten Echo-Test mit Sir anpassen.
- Anrede „Sir“ in jeder gesprochenen Antwort.
- Jede Ausnahme → gesprochene Kurzmeldung „Da ist etwas schiefgegangen, Sir. Der
  Fehler steht im Fehlerbericht.“, nie ein Absturz ohne Antwort.

| Nr. | Intent | Bestehende Funktion | Kosten |
|---|---|---|---|
| 1 | VaultFrageIntent | `chat_service.ask(frage, laenge="kurz")` | 0 € lokal; **Claude-Rückfall kostet** |
| 2 | BriefingIntent | `briefing.hole()` | 0 € (lokal, Zwischenspeicher) |
| 3 | MerkenIntent | `vorschlaege.anlegen()` + `vorschlaege.uebernehmen()` | 0 € |
| 4 | StatusIntent | `nachtarbeit.is_running()`, `nachtarbeit.letzte_nacht()`, `kosten.uebersicht()` | 0 € |
| 5 | TermineIntent | `termine.antwort_zeitraum()` | 0 € |
| 6 | NachtauftragIntent | `nachtauftraege.anlegen(..., quelle="alexa", pruefen=False)` | 0 € |
| 7 | AktionIntent | nur Whitelist `ALEXA_AKTIONEN` (Teil E) | 0 € |

### D1. Vault-Frage

- `chat_service.ask(frage, laenge="kurz")` (normaler Vault-Modus, nicht Werkzeug-Modus).
  Zusätzlicher Hinweis an das Modell: „Die Antwort wird vorgelesen. Höchstens zwei bis
  drei kurze Sätze, keine Listen, kein Markdown. Nenne am Ende die wichtigste Quelle
  mit Notiznamen.“ Lieber über einen vorhandenen Parameter oder eine kleine Ergänzung
  in `chat_service` lösen als den Systemtext zu kopieren.
- `used_vault == False` → „Dazu steht nichts im Vault, Sir.“ Nichts erfinden.
- Gesprochen: Antwort + „Quelle: <Notizname>“ (erste Quelle). Karte: alle Quellen.
- **Kosten:** Tagsüber antwortet das lokale Modell (0 €). Schafft es das nicht, springt
  nach der bestehenden Regel (`tag_rueckfall` in `data\ki_lokal.json`) **Claude** ein.
  Das kostet Geld aus dem **Rahmen von 20 $ im Monat** (Entscheidung 11.10.), grob
  ca. 0,5 Cent je Frage (Sonnet). Vorher `ki_aufruf.rest_pruefen()` – ist der Rahmen
  erschöpft, kein Claude, sondern „Der Kostenrahmen ist erschöpft, Sir.“
  Nutzung mit Modus `alexa` loggen. Bei Claude-Antworten steht in der Karte
  „Antwort von Claude, ca. X Cent“.
- Hinweis: Im Code steht als Rahmen noch `KOSTEN_RAHMEN_USD` mit Standard 30 $
  (`app/kosten.py`). Angleichen ist ein eigener offener Punkt der Gesamtkarte
  („Rahmen 20 $ im Code prüfen“), **nicht** Teil von P19.

### D2. Briefing vorlesen

- `briefing.hole()` nutzt den Zwischenspeicher, kostet dann nichts. Ist keiner da,
  erzeugt es ein neues Briefing (lokal) → kann länger als 6 s dauern → Mechanismus
  „letzte Antwort“.
- Aus dem Text die **drei wichtigsten Punkte** ohne KI herausziehen (erste
  Aufzählungspunkte bzw. erste Sätze), durch `fuer_sprache()`. Ganzes Briefing in die
  Karte.

### D3. „Merk dir …“

- Alexa fragt selbst nach („Soll ich mir merken: …?“). Nur bei `CONFIRMED`:
  `vorschlaege.anlegen(text, quelle="alexa")`, danach sofort
  `vorschlaege.uebernehmen(id)`. Ziel ist der Standard
  `Wissen/00 - Eingang/Gemerkt von Jarvis.md`. Das „Ja“ am Echo ersetzt den Klick
  „Übernehmen“; die bestehende Regel „erst nach Ja schreiben“ bleibt damit erfüllt.
- Antwort: „Gemerkt, Sir.“ 0 €.

### D4. Status

Kurzer Satz aus drei Teilen, ohne KI:
- Nachtarbeit: `nachtarbeit.is_running()` → „Die Nachtarbeit läuft gerade.“ oder
  „Die Nachtarbeit ruht.“
- Letzte Nacht: `nachtarbeit.letzte_nacht()` → Datum, Status, Kosten.
  Optional Anzahl fertiger Nachtaufträge aus `nachtauftraege.liste()`.
- Kosten: `kosten.uebersicht()` → „Vom Rahmen sind 3,10 von 20 Dollar verbraucht,
  16 Prozent.“ (Zahlen nur Beispiel.)

### D5. Termine

- Slot `tag` (AMAZON.DATE) liefert z. B. `2026-10-13`. Fehlt er: heute. Wochen- oder
  Monatsangaben (`2026-W42`, `2026-10`) als Zeitraum auflösen, sonst heute.
- `termine.antwort_zeitraum(von, bis, name)` mit `name` = „heute“, „morgen“ oder Datum.
  Ist der Kalender nicht eingerichtet, kommt der vorhandene Hinweistext.
- Mehr als drei Termine: drei vorlesen, „und N weitere“, alle in die Karte.

### D6. Nachtauftrag

- Nur bei `CONFIRMED`: `nachtauftraege.anlegen(text, quelle="alexa", pruefen=False)`
  → landet in `data\nachtauftraege.json`, Status „offen“. `pruefen=False`, weil die
  Klarheitsprüfung mit dem lokalen Modell das Zeitbudget sprengen kann.
- Antwort: „Auftrag <Nr> für die Nacht notiert, Sir.“ 0 €.
- Fehler aus `NachtauftragFehler` (zu kurz, zu lang) vorlesen.

### D7. Feste Aktionen

Siehe Teil E. Nur bei `CONFIRMED`, nur mit aufgelöster Slot-ID
(`resolutions…values[0].value.id`), nie mit dem gesprochenen Rohtext.

### D8. Eingebaute Intents

- `LaunchRequest` („Computer, öffne Auron“): „Auron hört, Sir.“ Sitzung offen,
  Nachfrage „Was kann ich tun?“.
- `AMAZON.HelpIntent`: ein Satz mit drei Beispielen.
- `AMAZON.StopIntent` / `CancelIntent`: „In Ordnung, Sir.“ Sitzung beenden.
- `AMAZON.FallbackIntent`: „Das kann ich per Sprache nicht, Sir.“
- `SessionEndedRequest`: nur protokollieren, leere Antwort.

---

## Teil E – Aktions-Whitelist

In `backend/app/alexa.py` als Konstante, oben in der Datei:

```python
# Aktionen, die Sir per Stimme auslösen darf (Entscheidung Sir 12.10.2026, P19).
# NUR fest hinterlegte, vorab geprüfte Abläufe. Kein freier Code, kein "schreib und führ aus",
# nichts löschen, keine Trades, Käufe oder Mails (Fehlauslösung per Stimme ist zu leicht).
# Neue Aktion = Eintrag hier + Wert im Slot-Typ AURON_AKTION (interaktionsmodell_de.json)
# + Test in tests/test_alexa.py. Sonst nichts. Die ID im Slot muss genau einem Schlüssel entsprechen.
ALEXA_AKTIONEN: dict[str, dict] = {
    "nachtarbeit_starten": {
        "name": "Nachtarbeit",
        "aktiv": True,
        "ausfuehren": "nachtarbeit.start",         # prüft selbst Monats-Limit und Kostenrahmen
        "antwort": "Die Nachtarbeit startet, Sir.",
    },
    "vault_einlesen": {
        "name": "Vault neu einlesen",
        "aktiv": True,
        "ausfuehren": "reindex_service.start",      # full=False: nur Änderungen
        "antwort": "Der Vault wird neu eingelesen, Sir.",
    },
    "pruefen_hintergrund": {
        "name": "Prüflauf",
        "aktiv": False,  # siehe Hinweis unten
        "ausfuehren": None,
        "antwort": "Den Prüflauf kann ich per Sprache noch nicht starten, Sir.",
    },
}
```

- Ausführung über eine feste Zuordnung Schlüssel → Funktion im Code, **kein**
  `getattr`/`eval` mit Text aus der Anfrage.
- Läuft der Ablauf schon (`start()` liefert `False`): „Läuft bereits, Sir.“
- Unbekannte ID oder `aktiv: False` → vorgegebene Antwort, nichts ausführen.
- **Hinweis Prüflauf (INHALT_PRUEFEN_HINTERGRUND):** Die .bat liegt auf dem Haupt-PC
  (`2 Testen und Pruefen`), Auron läuft auf dem Mini-PC. Ein Weg dorthin ginge nur
  über den PC-Agenten (Port 8766, feste Aktionsliste), der Code dafür
  (`pc_agent_windows`) liegt noch nicht im Repo (OFFEN.md Punkt 1, Sir hat am 11.10.
  zugestimmt). Außerdem ist der Haupt-PC nachts oft aus. Deshalb in Stufe 1 **aus**.
  Stufe 2 (eigene Aufgabe): feste Aktion `inhalt_pruefen` im PC-Agenten, dann hier
  `aktiv: True`.

---

## Teil F – Test-Checkliste

### F1. Automatische Tests (Claude Code, nur Cloud/Stubs, nie Haupt-PC)

`backend/tests/test_alexa.py`, ohne Netz (Netz-Wächter aktiv). Für die Signatur ein
**eigenes Test-Zertifikat** mit `cryptography` erzeugen (Test-Wurzel → Signaturzertifikat
mit SAN `echo-api.amazon.com`), Ladefunktion und Wurzelliste im Test ersetzen.

- [ ] Gültige Signatur, gültiger Zeitstempel, richtige Skill-ID → 200.
- [ ] Falsche Signatur, fehlende Kopfzeilen, veränderter Text → 400.
- [ ] Zertifikats-URL: `http`, anderer Host, Pfad `/ECHO.API/`, Port 563, `..` im Pfad → 400.
- [ ] Zertifikat abgelaufen, falscher SAN, fremde Wurzel → 400.
- [ ] Zeitstempel 151 s alt bzw. in der Zukunft → 400.
- [ ] Falsche Skill-ID → 400.
- [ ] `ALEXA_AKTIV` nicht gesetzt → 404.
- [ ] Middleware: `POST /api/alexa` ohne Code erreicht die Route; `GET /api/alexa`,
      `/auron`, `/api/chat` ohne Code bleiben gesperrt.
- [ ] Jeder Intent mit Mocks der bestehenden Funktionen, Antwort im Alexa-Format.
- [ ] Merken, Nachtauftrag, Aktion: ohne `CONFIRMED` passiert nichts; bei `DENIED`
      „In Ordnung, Sir.“
- [ ] Whitelist: unbekannte ID, Rohtext statt ID, `aktiv: False` → nichts ausgeführt.
- [ ] `fuer_sprache()`: höchstens `SPRACH_MAX_ZEICHEN`, endet an Satzgrenze, kein Markdown.
- [ ] Zeitbudget: langsamer Mock (> 6 s, per künstlicher Uhr) → Antwort „dauert länger“,
      danach liefert `LetzteAntwortIntent` das Ergebnis.
- [ ] Vault-Frage: `used_vault == False` → „Dazu steht nichts im Vault“;
      Rahmen erschöpft → kein Claude-Aufruf.
- [ ] Protokollzeile ohne Inhalte.
- [ ] Gesamtlauf: `python -m unittest discover -s tests -p "test_*.py"` grün,
      Cloud-Prüfstand 0 Fehler, GitHub Actions grün.

### F2. Simulator in der Developer Console (Sir, nach REPO HOLEN und Neustart)

- [ ] „öffne auron“ → „Auron hört, Sir.“ (zugleich Prüfschritt Zertifikat, Teil A)
- [ ] „frag auron nach dem gartenhaus“ → kurze Antwort mit Quelle
- [ ] „frag auron das briefing“
- [ ] „sag auron merk dir test von alexa“ → Nachfrage → „ja“ → Eintrag in
      `Wissen/00 - Eingang/Gemerkt von Jarvis.md` prüfen, danach Testeintrag selbst entfernen
- [ ] „frag auron status“
- [ ] „frag auron was steht morgen an“
- [ ] „sag auron nimm test für die nacht in die nachtarbeit auf“ → „ja“ → Auftrag in
      der Liste, danach im HUD verwerfen
- [ ] „sag auron vault neu einlesen starten“ → „ja“ → Ampel „Vault einlesen“ läuft
- [ ] „sag auron lösche alles“ → nichts passiert (Fallback)
- [ ] Im Reiter „Test“ die JSON-Antwort ansehen: Karte vorhanden, Text kurz

### F3. Echter Echo Dot 2. Gen (Sir)

- [ ] Gleiche Sätze wie F2, beginnend mit „Computer, …“.
- [ ] Länge der Antworten angenehm? Sonst `SPRACH_MAX_ZEICHEN` anpassen lassen.
- [ ] Zwei Fragen hintereinander, einmal mit langer Frage (Zeitbudget, „letzte Antwort“).
- [ ] Licht- und Sonos-Befehle funktionieren unverändert.
- [ ] Alexa-App: Karten mit Quellen sichtbar.

---

## Teil G – Kosten

| Posten | Kosten |
|---|---|
| Amazon Developer Konto, Skill im Entwicklungsmodus | 0 € |
| Tailscale Funnel (Weg A) | 0 € im bestehenden Tarif (ungeprüft, falls Sir einen Bezahltarif hat) |
| Lambda (nur Weg B): Alexa-hosted bzw. AWS Free Tier | 0 € (siehe Teil A) |
| Briefing, Merken, Status, Termine, Nachtauftrag, Aktionen | 0 € |
| Vault-Frage, lokales Modell | 0 € |
| **Vault-Frage, wenn Claude einspringt** | **ca. 0,5 Cent je Frage, aus dem 20-$-Rahmen** |

## Teil H – Was Sir am PC tun muss (nach dem Bau)

1. Pull Request mergen, `1 Starten/REPO HOLEN.bat`.
2. In der `.env` selbst eintragen (Claude liest die `.env` nie):
   `ALEXA_AKTIV=1`, `ALEXA_SKILL_ID=amzn1.ask.skill.…` (aus Teil B, Schritt 7),
   optional `ALEXA_NUTZER_ID=…` (steht nach dem ersten Test in der JSON-Anfrage im Simulator).
3. **Neustart nötig** (Python geändert): `1 Starten\JARVIS STARTEN.bat`.
4. Auf dem Mini-PC `alexa_tunnel_einrichten.sh` starten (Teil A, Weg A).
5. Developer Console einrichten (Teil B), dann F2 und F3.
6. Ergebnis an Claude melden. Bei Problemen `1 Starten/FEHLERBERICHT SENDEN.bat`.

## Abnahme (fertig heißt)

- Alle Tests und Cloud-Prüfstand ohne Fehler, GitHub Actions grün.
- F2 und F3 bei Sir erfolgreich.
- Von außen ist über `auron-alexa` nur `POST /api/alexa` erreichbar, nichts anderes.
- Gesamtkarte: Punkt „Alexa-Skill „frag Auron“ (P19)“ auf „fertig“, Übersicht der
  Projekt-Aufgaben aktualisiert.

## Offen und ungeprüft

- Einwortiger Aufrufname „auron“ (Teil B, Schritt 3).
- Zertifikatsprüfung der Amazon-Kette mit `cryptography.x509.verification` (C3).
- Genaue Zeitgrenze von Alexa (Planung mit 6 s).
- Verhalten von `tailscale funnel --set-path` und ob `X-Forwarded-For` gesetzt wird.
- Zweiter `tailscaled` bzw. Docker auf dem Mini-PC.
- Kostenloses AWS-Kontingent für neue Konten (nur Weg B2).
- Prüflauf per Stimme erst nach PC-Agent-Aktion (Stufe 2).

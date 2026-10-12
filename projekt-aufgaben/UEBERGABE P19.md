# Übergabe P19 an den PC (12.10.2026)

Claude Code in der Cloud hat keinen Zugriff auf den Vault und auf `data\`. Diese drei
Schritte macht Claude im Projekt auf Sirs PC (oder Sir selbst).

## 1. P19 in den Vault

- Datei `P19 - Alexa-Skill „frag Auron“.md` aus diesem Ordner nach
  `Wissen\14 - Projekt-Aufgaben\` kopieren.
- Dateiname: Windows erlaubt kein `"`. Deshalb typografische Anführungszeichen „…“.
- Form mit einer bestehenden P-Notiz (z. B. P18) vergleichen und angleichen
  (Frontmatter-Felder, Überschriften). Die Cloud-Fassung ist ohne Vorlage geschrieben,
  der Inhalt ist vollständig.
- Danach die Datei im Vault nachlesen und mit der Fassung im Repo vergleichen.

## 2. Übersicht der Projekt-Aufgaben

Neue Zeile in der Übersicht in `Wissen\14 - Projekt-Aufgaben\`, im Stil der vorhandenen:

- P19 · Alexa-Skill „frag Auron“ · Phase 9 · offen · für Claude Code · 12.10.2026 ·
  laufend 0 €, außer Claude-Rückfall bei Vault-Fragen

## 3. `data\gesamtkarte.json`

Dieselben Änderungen wie im Artifact „Auron Gesamtkarte“ (Version vom 12.10., 19:30):

- Punkt `fragen.31-alexa-skill`: `"stand": "ok"`, neu
  `"antwort": "Ja (Sir 12.10.). P19 ist geschrieben."`
- Punkt `p9.alexa`, im Text: „Nächster Schritt: P19.“ → „Umsetzung: P19 (geschrieben 12.10.).“
- Punkt `offenc.alexa`, im Text: „Bau als P19 offen (Frage 31).“ → „P19 geschrieben 12.10. (Frage 31: ja).“
- Neuer Punkt unter `p9`, direkt nach `p9.alexa`:

```json
{"id": "p9.p19", "titel": "Alexa-Skill „frag Auron“ (P19)", "stand": "plan", "wer": "Sir → Claude Code",
 "text": "P19 geschrieben 12.10. Eigener Skill im Entwicklungsmodus, Aufruf „Computer, frag Auron …“. Sieben Fähigkeiten: Vault-Frage, Briefing, „Merk dir“, Status, Termine, Nachtauftrag, feste Aktionen nur aus einer Whitelist im Code. Nicht per Sprache: Trades, Käufe, Mails, Löschen. Erreichbarkeit: eigener Funnel-Knoten „auron-alexa“ nur für /api/alexa (der bestehende Tunnel ist nur im Tailnet erreichbar); Rückfall Lambda. Laufend 0 €, außer wenn Claude bei Vault-Fragen einspringt (20-$-Rahmen)."}
```

Nach dem Speichern: JSON-Gültigkeit prüfen, Syncthing abwarten (20–60 s), Seite
„Karte“ im HUD neu laden (Strg+F5).


## Nachtrag 12.10.2026, 23:10 (Stand nach dem Echo-Test)

Gleiche Änderungen wie im Artifact „Auron Gesamtkarte“ (Version 17). In `data\gesamtkarte.json`
die Punkte mit diesen IDs **ganz ersetzen** bzw. neu einfügen. Der Neu-Punkt aus Teil 3 oben
(`p9.p19`) wird dabei überschrieben.

**Ersetzen** (gleiche ID suchen, ganzen Punkt austauschen):

```json
{
 "id": "p9.p19",
 "titel": "Alexa-Skill „Agent Auron“ (P19)",
 "stand": "test",
 "wer": "Sir → Claude Code",
 "text": "Gebaut von Claude Code 12.10. (PR #9–#12). Aufruf „Computer, frag Agent Auron …“ (Amazon verlangt zwei Wörter). Tunnel „auron-alexa“ (Funnel nur /api/alexa) läuft, von außen geprüft. Simulator: Start, Status, Termine, Merk dir, Vault-Frage ok. Echo Dot: läuft, nur die Vault-Frage („nach dem Fahrradladen“) noch nicht – in der Alexa-App geht sie. Diagnose-Protokoll in PR #12, Ursache am 13.10. klären. Laufend 0 €, außer wenn Claude bei Vault-Fragen einspringt."
}
```

```json
{
 "id": "p9.alexa",
 "titel": "Alexa Echo Dot (2. Gen)",
 "stand": "test",
 "text": "Sir 11.10.: Auron über Alexa. Geklärt 12.10.: eigener Skill „frag Auron“ im Entwicklungsmodus auf Sirs Echo möglich, Weckwort „Computer“ ist bei Sir schon eingestellt. Fremdsoftware auf dem Echo: kein offizieller Weg. Licht und Sonos laufen bereits über Skills. Umsetzung: P19, läuft seit 12.10. abends am Echo (Vault-Frage dort noch offen)."
}
```

```json
{
 "id": "p3.weckwort-jarvis",
 "titel": "Sprachaktivierung „Auron“",
 "stand": "ok",
 "text": "Sir 12.10.: Am PC funktioniert „Auron, …“ bereits. Alexa (P19) ist für das Bett, wenn der PC aus ist."
}
```

```json
{
 "id": "p6.windows-steuern",
 "titel": "Komplette PC-Steuerung",
 "stand": "sir",
 "text": "Sir 12.10.: großer Wunsch – Auron soll den PC komplett steuern können. Heute nur feste Liste über den PC-Agenten. Komplett hieße: Programme bedienen, Dateien, Terminal, Browser. Ändert die Ausführungsregel vom 10.10.; hängt eng mit Freigabe-Stufen zusammen.",
 "frage": "Was genau soll Auron am PC dürfen (Programme bedienen, Dateien, Terminal, Browser, nie: …), und auf welchen Rechnern?",
 "wer": "Sir"
}
```

**Neu als ersten Unterpunkt von `vorschlag` einfügen:**

```json
{
 "id": "vorschlag.usejarvis",
 "titel": "Ideen aus Usejarvis (12.10.)",
 "stand": "plan",
 "text": "Sir und Claude haben am 12.10. die Doku von usejarvis.dev (26 Seiten) durchgesehen. Sir hat entschieden:",
 "kinder": [
  {
   "id": "vorschlag.usejarvis.zusagen",
   "titel": "Zusagen erkennen",
   "stand": "plan",
   "text": "Sir: ja. „Mach ich morgen“ aus den Gesprächen erkennen (nachts, lokal, 0 €) und im Briefing nachhaken."
  },
  {
   "id": "vorschlag.usejarvis.stillstand",
   "titel": "Stillstand nach 1 Woche ansprechen",
   "stand": "plan",
   "text": "Sir: ja. Steht ein Punkt eine Woche still, spricht Auron ihn an."
  },
  {
   "id": "vorschlag.usejarvis.selbst",
   "titel": "Selbst-Unterbrechung verhindern",
   "stand": "plan",
   "text": "Sir: ja, gehört fest eingebaut. Sagt Auron selbst „Auron“/„Jarvis“, hört das Mikrofon in dem Moment weg."
  },
  {
   "id": "vorschlag.usejarvis.profil",
   "titel": "Profil über das Fragenkonzept",
   "stand": "plan",
   "text": "Sir: ja, wollte er schon länger. Aufbauend auf dem Fragenkatalog."
  },
  {
   "id": "vorschlag.usejarvis.ohne-neustart",
   "titel": "Einstellungen ohne Neustart",
   "stand": "plan",
   "text": "Sir: ja, „super“. Änderungen sollen sofort gelten statt erst nach JARVIS STARTEN."
  },
  {
   "id": "vorschlag.usejarvis.termin15",
   "titel": "Hinweis 15 Minuten vor Termin",
   "stand": "plan",
   "text": "Sir: ja, wie ein Kalender."
  },
  {
   "id": "vorschlag.usejarvis.freigabe",
   "titel": "Freigabe-Stufen, Notaus, Protokoll",
   "stand": "idee",
   "text": "Sir: darüber nachdenken. Voraussetzung für eine sichere komplette PC-Steuerung."
  },
  {
   "id": "vorschlag.usejarvis.telegram",
   "titel": "Telegram als Push-Kanal",
   "stand": "idee",
   "text": "Sir: könnte man machen, Telegram ist vorhanden."
  },
  {
   "id": "vorschlag.usejarvis.geraete",
   "titel": "Geräte einzeln sperren",
   "stand": "idee",
   "text": "Noch nicht besprochen."
  },
  {
   "id": "vorschlag.usejarvis.nicht",
   "titel": "Weckwort, „Wartet auf Sie“",
   "stand": "nein",
   "text": "Sir: nicht nötig – Weckwort am PC gibt es, offene Punkte nennt das Briefing."
  }
 ]
}
```

**Neu als erste zwei Unterpunkte von `entsch` einfügen:**

```json
[{"id": "entsch.1210-alexa-name", "titel": "12.10. Aufruf „Agent Auron“", "stand": "ok", "text": "Amazon lehnt einwortige Aufrufnamen ab. Sir wählt „agent auron“: „Computer, frag Agent Auron …“."},
 {"id": "entsch.1210-usejarvis", "titel": "12.10. Ideen aus Usejarvis", "stand": "ok", "text": "Ja: Zusagen erkennen, Stillstand nach 1 Woche, Selbst-Unterbrechung verhindern, Profil, Einstellungen ohne Neustart, Termin-Hinweis 15 Min. Nachdenken: Freigabe-Stufen. Wunsch: komplette PC-Steuerung."}]
```

Danach JSON-Gültigkeit prüfen, Syncthing abwarten, im HUD die Seite „Karte“ neu laden (Strg+F5).

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

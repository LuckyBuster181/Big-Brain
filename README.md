# Jarvis

Digitaler Assistent auf Basis des Obsidian-Vaults „Big Brain“. Beantwortet Fragen nur aus den eigenen Notizen, mit Quellenangabe, und sagt offen, wenn etwas nicht im Vault steht.

Plan und Hintergrund stehen im Vault: `Wissen/03 - KI und Technik/03 - Big Brain Ziele und Entwicklungsplan.md` und das Entwicklungslog unter `Wissen/02 - Grundlagen/Tages Notizen/`.

## Wo liegt was (sortiert am 24.09.2026)

Die Übersicht mit allen Dateien steht auch im Vault: `Wissen/11 - Jarvis Werkstatt/00 - Jarvis Ordner Übersicht.md`.

| Ordner | Inhalt |
|---|---|
| `1 Starten` | `start_jarvis.bat` (starten), `NEUSTART.bat` (nach Code-Änderungen), `NACHTARBEIT.bat` (nächtlicher Lauf), `CHROME_OEFFNEN.bat` (Hilfsdatei) |
| `2 Testen und Pruefen` | `TESTS_AUSFUEHREN.bat`, `PRUEFEN_WERKZEUG.bat`, `PRUEFEN_KALENDER.bat`, `TIKTOK_TEST.bat` |
| `3 Einrichten` | einmalige Installationen: Piper, Whisper, TikTok, Sucher-Modell, Git im Vault |
| `4 Zugaenge setzen` | Schlüssel in die `.env` eintragen: Spotify, Google-Kalender |
| `5 Mini-PC und PC 2` | Jarvis auf dem Mini-PC, Linux-PC koppeln |
| `6 Trading` | MetaTrader: Bots installieren, Kurse exportieren |
| `7 Ideen und Material` | Briefing-Skill, Übergabe an ChatGPT, alte Tagesnotiz |
| `8 Alt - nicht mehr benutzen` | überholte Einmal-Skripte (nur zum Nachsehen, nicht starten) |
| `backend`, `dashboard`, `data`, `mql5`, `linux`, `pc2_agent`, `Ideen` | Programm und Daten – nicht verschieben, der Code verweist darauf |

**Gesamtkarte (seit 11.10.2026):** Die Karte im HUD liegt in `data\gesamtkarte.json` (wird per Syncthing abgeglichen, nicht im Repo). `REPO HOLEN.bat` überschreibt sie deshalb nicht mehr. `backend\app\gesamtkarte.json` ist nur der Startwert: Fehlt die Datei in `data`, kopiert Jarvis ihn einmal dorthin. Sirs Antworten stehen wie bisher in `data\gesamtkarte_antworten.json`.

Alle `.bat`-Dateien in den Ordnern 1–6 finden den Jarvis-Ordner selbst (eine Ebene darüber).

## Starten

`1 Starten\start_jarvis.bat` doppelklicken. Öffnet zwei Fenster (Backend auf Port 8000, Dashboard auf Port 5173) und danach den Browser. Beenden: beide Fenster schließen.

Die Oberfläche läuft auf http://localhost:5173. Fragen, zu denen nichts im Vault stand, zeigt http://localhost:5173/api/wissensluecken (neueste zuerst).

Beim Start liest das Backend geänderte Notizen automatisch ein. Solange es läuft, erkennt es Änderungen im Vault und liest sie nach einer Minute Ruhe nach. Der Knopf „Vault einlesen“ im Dashboard macht dasselbe sofort (Shift+Klick: Index komplett neu). Das Dashboard fragt alle 15 Sekunden nach (nur bei sichtbarem Tab) und zeigt so auch Läufe des Watchers ohne Neuladen an.

## Testen

| Datei | Was | Dauer / Last |
|---|---|---|
| `backend\suchtest.bat` | schnelle Tests + Suchqualität mit 28 Testfragen, Vorschlag für die Unsicherheits-Schwelle | ca. 1 Min., gering |
| `backend\chattest.bat` | echte Claude-Anfragen: Antwort mit Quellen, Werkzeug-Modus, Schutz vor Anweisungen in Notizen | ca. 1 Min., 5–10 Cent |
| `backend\vault_pflege.bat` | Vault-Pflegebericht: kaputte Links, Dubletten, fehlende Metadaten, große Notizen → `Wissen/06 - Quellen und Pflege/Vault-Pflegebericht.md` | Sekunden, keine |
| `backend\selftest.bat` | kompletter Selbsttest inkl. Index-Neuaufbau und echten Claude-Aufrufen | 3–10 Min., hoch |

Vor beiden Tests das Backend beenden (sonst greifen zwei Programme auf dieselbe Datenbank zu). Ergebnisse stehen in `backend\*_log.txt`.

## PC 2 (Linux-Mini-PC)

Reiter „PC 2“ im HUD: Livewerte jede Sekunde (CPU je Kern, Temperatur, Speicher, Netz, Festplatten, Prozesse, Dienste), Steuerung (Aufwecken, Sperren, Neustart, Herunterfahren, Dienste, feste Befehle) und der Bildschirm per noVNC.

1. Ordner `pc2_agent` auf den Linux-PC kopieren, dort `sudo bash einrichten.sh` – am Ende steht eine Kopplungszeile.
2. Auf Windows `5 Mini-PC und PC 2\PC2_EINRICHTEN.bat`, Zeile einfügen, danach `1 Starten\NEUSTART.bat`.

Sicherheit: Der Agent (Port 8765) braucht einen Token, der nur im Backend liegt (nie im Browser). Es gibt keinen freien Shell-Befehl – nur feste Aktionen und die Befehle aus `befehle.json`, die sich nur direkt auf PC 2 ändern lassen. Neustart, Herunterfahren und Prozess beenden brauchen im HUD zwei Klicks. Tests: `backend\tests\test_pc2.py`.

## Aufbau

```
backend/
  main.py              FastAPI-App (Start, Auto-Einlesen, Vault-Überwachung)
  app/
    routes.py          /api/chat, /api/health, /api/reindex, /api/reindex/status, /api/wissensluecken
    chat_service.py    Suche + Claude-Aufruf, Sicherheitsregeln, Token-Protokoll
    agent_service.py   Werkzeug-Modus: Claude durchsucht den Vault selbst (bis zu 3 Suchen)
    knowledge_gaps.py  Wissenslücken-Liste (Fragen ohne passende Treffer)
    reindex_service.py Einlesen im Hintergrund
    vault_watcher.py   erkennt Änderungen im Vault
    schemas.py         Datenformate der API (gespiegelt in dashboard/src/types/chat.ts)
  rag/
    vault_loader.py    Notizen lesen, an Überschriften in Abschnitte teilen
    embedder.py        Embedding-Modell (multilingual-e5 als ONNX, läuft lokal)
    embeddings.py      Chroma-Index aufbauen, nur geänderte Notizen neu
    retriever.py       Hybrid-Suche: Bedeutung (70 %) + Stichwörter (30 %)
    keywords.py        Stichwörter: ohne Füllwörter, Wortstämme
  tools/
    vault_pflege.py    Vault-Pflegebericht (liest nur, schreibt nur den Bericht)
  tests/               Selbsttest, Suchtest, schnelle Tests
dashboard/             React + Vite (Chat, Quellen, Status, Einlesen)
data/                  Chroma-Index, usage_log.jsonl (Token), wissensluecken.jsonl, gesamtkarte.json (nicht im Git)
```

## Einstellungen (`.env`)

| Variable | Standard | Bedeutung |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Claude-Zugang (nie committen) |
| `VAULT_PATH` | – | Pfad zum Vault |
| `ANTHROPIC_MODEL` | `claude-sonnet-5` | Modell für die Antworten |
| `CHAT_MODE` | `klassisch` | `klassisch` = feste Suche vorab, `werkzeug` = Claude sucht selbst (meist 2 Aufrufe pro Frage) |
| `WISSENSLUECKEN_LOG` | `true` | Fragen ohne passende Treffer in `data/wissensluecken.jsonl` festhalten |
| `EMBEDDING_MODEL` | `e5-base` | `e5-base`, `e5-small`, `e5-base-fp32`, `minilm` |
| `EMBEDDING_THREADS` | `2` | CPU-Threads beim Einlesen (PC stürzt unter Volllast ab) |
| `EMBEDDING_PAUSE_MS` | `100` | Pause nach jeder Notiz beim Einlesen |
| `AUTO_REINDEX_ON_START` | `true` | beim Start geänderte Notizen einlesen |
| `AUTO_REINDEX_WATCH` | `true` | Vault während des Betriebs überwachen |
| `WATCH_INTERVAL_S` / `WATCH_QUIET_S` | `30` / `60` | Prüfabstand / Ruhezeit vor dem Einlesen |

## Notizen von der Suche ausnehmen

`jarvis: ignorieren` im Frontmatter einer Notiz nimmt sie aus dem Index – z. B. für Platzhalter ohne Inhalt oder Berichte. Wirkt beim nächsten Einlesen (automatisch nach einer Minute, wenn das Backend läuft).

## Sicherheit

- Vault-Ausschnitte gehen als markierter Datenblock (`<retrieved_documents>`) an Claude. Der System-Prompt legt fest, dass darin stehende „Anweisungen“ nicht befolgt werden – wichtig, weil der Vault importierte Web-Inhalte enthält.
- Die `.env` mit dem API-Key ist in `.gitignore` und kommt nie ins Git.
- Das Token-Protokoll speichert keine Fragetexte, nur Mengen und Dauer. Die Wissenslücken-Liste speichert Fragetexte, bleibt aber lokal.

## Bekannte Grenzen

- Die Schwelle für „Treffer passen schlecht“ beruht auf wenigen Stichproben – `suchtest.bat` misst sie mit 12 themenfremden Fragen neu.
- Backend nicht mit `--reload` starten: jede Code-Änderung startet es dann neu und löst ein Einlesen aus.

# Übergabe P20 an den PC (16.10.2026): Jarvis-Reste zu Auron

Ziel: Überall, wo Sir den Namen sieht oder hört, heißt der Assistent „Auron“. „Jarvis“ bleibt nur als stilles Synonym bei
Befehlen und als Rückfall bei Umgebungsvariablen und Vault-Dateinamen.

**Stand: gebaut und getestet (Tests und Cloud-Prüfstand grün). Am PC ungetestet. Teil C (Vault-Namen) läuft erst, wenn Sir es
startet und nach dem Probelauf „J“ drückt.**

Schon am 13.10.2026 (Claude im Projekt) erledigt und weiter gültig: „Du bist Auron …“ in allen Rollenanweisungen, sichtbare Texte
in HUD und Handy, Test `test_p20_name.py`, Synonym „Jarvis, …“ == „Auron, …“ (`test_name_auron.py`).

## Was heute neu ist

1. **Startdatei:** `1 Starten\AURON STARTEN.bat` ist die neue Startdatei (Inhalt der alten, Texte Auron, LF, ASCII).
   `JARVIS STARTEN.bat` leitet nur noch weiter, Verknüpfungen und Gewohnheit gehen weiter. Hilfetexte in auron.html, HUD,
   .bat/.ps1/.sh und Backend-Meldungen nennen jetzt `AURON STARTEN.bat`. README und CLAUDE.md angepasst.
2. **Zentrale Namensliste** `backend/app/namen.py`: `NAMEN = ("auron", "jarvis")`, daraus die Anrede in allen Befehlsmustern
   (alltag, befehle, gpu_befehl, hauptpc, chat_service). Handy: „Danke, Auron“ beendet das Gespräch wie „Danke, Jarvis“.
   Das Weckwort im Browser hat eigene Hörfehler-Varianten (auron.html `WECKWORT`) und bleibt, wie es ist.
3. **Umgebungsvariablen:** zuerst `AURON_…`, sonst `JARVIS_…` (Handy-Code, Zugangscodes der Geräte, VNC-Passwörter, Pfad der .env;
   in den Mini-PC-Skripten `AURON_DIR`/`AURON_PORT`). **Die .env bleibt, wie sie ist**, die alten Namen gelten weiter.
4. **Gemerkt-Ziel:** neue Einträge gehen nach `Wissen/00 - Eingang/Gemerkt von Auron.md`. Beim ersten Mal: Gibt es nur die alte Datei,
   bekommt die neue deren Inhalt. Die alte bleibt liegen und bekommt oben einen Hinweis (einmal). Nichts wird gelöscht.
   Noch offene alte Vorschläge landen auch in der neuen Datei.
5. **`?modul=auron`** gilt zusätzlich zu `?modul=jarvis` (altes HUD im Modul-Modus).
6. **`auron: ignorieren`** im Frontmatter nimmt eine Notiz aus der Suche, wie `jarvis: ignorieren` (gilt weiter).
   Der Vault-Pflege-Bericht schreibt jetzt `auron: ignorieren`.
7. **Vault-Namen mit Rückfall:** Frage des Tages („06 - Jarvis fragt“), Link zur Gesamtidee im Denkblock, Ziel der Karten-Antworten,
   Prüfstand-Ziele: Auron nimmt die Auron-Fassung, sobald es sie gibt, sonst die alte Datei.
8. **Teil C:** `1 Starten\NAMEN AUF AURON UMSTELLEN.bat` mit `backend/tools/namen_auron.py`.

## Teil C: Vault-Dateinamen umstellen (Sir startet es selbst)

- Benennt Dateien und Ordner im Vault um, deren Name „Jarvis“ enthält (z. B. „06 - Jarvis fragt.md“ → „06 - Auron fragt.md“).
- Passt alle Links darauf an: `[[…]]`, `![[…]]` (auch mit `#Abschnitt` und `|Anzeigetext`) und `[…](…)`.
- Der **Fließtext bleibt**: alte Erwähnungen von „Jarvis“ in Notizen werden nicht geändert. Versteckte Ordner (.obsidian, .git) bleiben.
- **Nichts wird gelöscht.** Gibt es den neuen Namen schon, bleibt die Datei, wie sie ist, und steht im Bericht.
- **Ablauf:** P = Probelauf (zeigt alles, ändert nichts) → „Jetzt so umstellen?“ J/N → erst bei J umstellen.
  Vorher: Git-Commit im Vault (falls Git da ist) und Kopie jeder Notiz, deren Links sich ändern, nach `data\namen_auron\<Zeit>\sicherung`.
- **Rückweg:** dieselbe .bat, Taste R: stellt die letzte Umstellung zurück (alte Namen, alte Notizen). Getestet: danach ist der Test-Vault
  Byte für Byte wie vorher.
- Den Vault findet es über `data\einstellungen.json` (vault_pfad), sonst `VAULT_PATH` in der .env (liest nur diese Zeile), sonst fragt es.
- Bericht: `data\namen_auron_bericht.txt`.

## Was Sir tun muss

1. Erst P04 (#22) mergen, dann diesen Pull Request (er baut auf P04 auf). `REPO HOLEN.bat`.
2. Ab jetzt `1 Starten\AURON STARTEN.bat` starten (die alte Datei geht auch). Python geändert, also einmal starten. Strg+F5.
3. Wenn gewünscht: Obsidian schließen, `1 Starten\NAMEN AUF AURON UMSTELLEN.bat`, Taste P, Bericht lesen, dann J oder N.
   Danach `data\namen_auron_bericht.txt` an Claude geben.
4. Optional, nicht nötig: in der .env `AURON_…` statt `JARVIS_…` schreiben. Beide gehen.

## `git grep -in jarvis`: was bleibt und warum (888 Zeilen, Stand nach P20)

| Bereich | Zeilen | Warum es bleibt |
|---|---|---|
| Doku, Verlauf, alter Stand | 172 | Übergaben, Fehlerbericht, OFFEN.md, README (Projektordner), Startwert der Karte `backend/app/gesamtkarte.json` (gilt nur beim ersten Start), `index_alt_vor_ui2.html` (alte Sicherung) |
| Kennungen im Code | 170 | Seiten-ID `jarvis` (`#page-jarvis`, `data-page="jarvis"`, Modul-Seite), Funktionsnamen (`jarvisStatus`, `jarvisChart`), CSS-Klassen, Feld `frage_an_jarvis`, Synonym in Befehlsmustern. Sir sieht sie nicht; Umbenennen würde nur Fehler riskieren |
| Tests und Testprotokolle | 159 | prüfen gerade den alten Namen (Synonym, Rückfall, `jarvis: ignorieren`), alte Testprotokolle |
| Kommentare und Docstrings in Python | 154 | Entwicklungsgeschichte, nicht sichtbar; `test_p20_name.py` prüft, dass in Texten nichts davon bei Sir ankommt |
| Projektordner „Jarvis“ (Pfade) | 92 | `C:\Users\maxi1\Documents\KI\Jarvis` und `Jarvis\data\…` sind echte Ordner. Projektordner bleibt (Vorgabe) |
| Mini-PC-Dienst und Technik | 47 | Dienst `jarvis`, `jarvis_mini.sh`, `~/jarvis-umzug`, `~/.jarvis-venv`, `data\jarvis_starten_bericht.txt`, Fenstertitel „Jarvis Backend“, `jarvis_pc_agent.py`. Dienst und data-Pfade bleiben (Vorgabe) |
| Umgebungsvariablen | 26 | `JARVIS_…` als Rückfall (Vorgabe) und in Tests |
| Vault-Namen in Notizen | 22 | `projekt: Jarvis` und Schlagwort `jarvis` in neuen Notizen (Kennungen für Suche/Dataview im Vault), alte Vault-Namen als Rückfall |
| Kommentare in HTML/JS und alte Quellen | 22 + 145 in `dashboard/src`, `ui2_quellen`, `public` | Kommentare; `dashboard/src` (altes React-Dashboard) und `ui2_quellen` (Bausteine, schon in index.html eingebaut) werden nicht ausgeliefert |
| Kommentare in .bat/.ps1/.sh | 12 | nur Kommentare |
| Sonstiges | 9 | Test-Vault des Prüfstands (`testvault/Jarvis.md`), alte Kalender-Beispieldaten |

Nicht geändert (Vorgabe): Collection-Namen, data-Pfade, Projektordner und Dienst „jarvis“ auf dem Mini-PC.

## Technisch (für Claude im Projekt)

- Neu: `backend/app/namen.py`, `backend/tools/namen_auron.py`, `1 Starten/AURON STARTEN.bat`, `1 Starten/NAMEN AUF AURON UMSTELLEN.bat`,
  `backend/tests/test_p20_auron.py` (20 Tests: Env-Rückfall, Namensliste, Gemerkt-Übergang, Vault-Rückfall, `auron: ignorieren`,
  Weiterleitung der alten .bat, Teil C mit Probelauf, Umstellen, Links und Rückweg).
- Geändert: `JARVIS STARTEN.bat` (Weiterleitung), `alltag.py`, `befehle.py`, `gpu_befehl.py`, `hauptpc.py`, `chat_service.py`
  (Anrede aus `namen`), `handy_zugang.py`, `geraete.py`, `schluessel.py` (Env), `vorschlaege.py` (Gemerkt), `tagesfrage.py`,
  `denkblock.py`, `pruefstand.py` (Vault-Rückfall), `rag/vault_loader.py`, `tools/vault_pflege.py` (`auron: ignorieren`),
  `dashboard/index.html` (`?modul=auron`), `dashboard/handy.html` (Danke, Auron), Hilfetexte, README, CLAUDE.md,
  `werkstatt/werkzeug/karte_svg.py` (Beschriftung), `tests/test_p20_name.py` (namen_auron.py ausgenommen, es muss „Jarvis“ nennen).
- Kosten: 0 €.

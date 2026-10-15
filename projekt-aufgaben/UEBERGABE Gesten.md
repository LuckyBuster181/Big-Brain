# Übergabe Gesten (Stand 15.10.2026, 23 Uhr)

## Stand
- **PR #16 (gemergt):** Gesten in Auron. Knopf „Gesten“ oder „Auron, Gesten an/aus“. Erkennung lokal im Browser
  (MediaPipe 0.10.35, Apache-2.0), kein Claude, 0 €. Sir am PC: läuft, Punkt bewegt sich, **Klick ging nicht,
  Punkt hing manchmal**.
- **PR #17 (offen, GitHub grün):** Punkt folgt den Fingerknöcheln statt der Fingerspitze (wie bei der Meta Quest), Klick ab
  Pinch-Abstand 0,40 statt 0,33, der Punkt schrumpft beim Zusammendrücken, das Kamerafenster zeigt „Pinch: 0,xx“.
  Mit Sirs Webcam noch ungetestet.

## Code
| Datei | Inhalt |
|---|---|
| `werkstatt/gesten/gesten.js` | ganze Gesten-Logik, Schwellen oben in `EINSTELLUNG` |
| `dashboard/auron.html` | Knopf, Sprachbefehl (`GESTEN_BEFEHL`), Anzeige, geteilter Kamerastrom, `zurueckOderSchliessen()` |
| `werkstatt/GESTEN_HOLEN.bat` | lädt MediaPipe und das Handmodell nach `werkstatt/lib/mediapipe` (nicht im Repo) |
| `backend/cloud_pruefstand/lauf.py` | Prüfung mit künstlicher Hand, echtem MediaPipe und echten Handfotos |
| `backend/tests/test_gesten.py` | gleicht .bat und Prüfstand ab |

## Morgen (ab 14 Uhr, nach dem Zurücksetzen des Limits)
1. Sir: PR #17 mergen, REPO HOLEN.bat, Strg+F5. Klick testen. Falls kein Klick: Zahl „Pinch: 0,xx“ beim
   Zusammendrücken melden, dann `pinchAn` danach einstellen.
2. Danach neues Projekt **ganzen PC per Hand steuern**. Der Browser darf die Windows-Maus nicht bewegen, deshalb wird es
   ein eigenes kleines Programm auf dem PC (Kamera + Maus, Start per .bat, Aus-Schalter). Gesten so, wie ein
   Mensch es intuitiv macht: zeigen, greifen (Pinch) = Klick, Pinch halten und ziehen = Ziehen oder Scrollen,
   ganze Hand wischen = Fenster wechseln. Die Nacht-Recherche unten vorher lesen.
3. Später: Auron auf der Meta Quest (Browser der Quest, WebXR). Eigenes Projekt.

## Text für die Tagesnotiz (15.10.2026)
> Auron kann jetzt Gesten (Webcam, lokal, 0 €): Knopf „Gesten“ oder „Auron, Gesten an“. Erster Test am PC: Punkt
> bewegt sich, Klick ging noch nicht. Fix nach Quest-Art liegt als PR #17 bereit (Knöchel statt Fingerspitze,
> Klick leichter). Morgen: Klick testen, dann ganzen PC per Hand steuern (eigenes Programm). Idee: Auron auf der Quest.

## Nachtauftrag (zu Auron sagen oder schreiben, läuft nachts nur lokal, 0 €)
> Auron, heute Nacht: recherchiere, wie Handgesten-Steuerung für einen Windows-PC mit Webcam intuitiv
> funktioniert. Vergleiche Meta Quest (Hand-Tracking, Pinch, Zeigestrahl), Apple Vision Pro (Blick und Pinch) und
> fertige Open-Source-Programme für Windows mit MediaPipe (Maus per Hand). Welche Gesten nutzen sie für Klick,
> Rechtsklick, Ziehen, Scrollen, Fenster wechseln und Abbrechen? Wie verhindern sie Fehlklicks (Halten, Schwellen,
> Glättung)? Welche Python-Bibliotheken steuern unter Windows die Maus, und mit welchen Lizenzen? Ergebnis als
> kurze Tabelle mit Empfehlung für Auron.

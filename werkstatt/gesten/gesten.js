/* Gesten für Auron (15.10.2026, Claude Code) - Handtracking über die Webcam, komplett lokal im Browser.
   Erkennung: MediaPipe Hand Landmarker (@mediapipe/tasks-vision 0.10.35, Lizenz Apache-2.0, Modell
   hand_landmarker.task float16/1, Apache-2.0). Die Dateien liegen NICHT im Repo, sondern in werkstatt/lib/mediapipe
   und kommen einmalig über werkstatt/GESTEN_HOLEN.bat. Kein Bild verlässt den PC, kein Claude, keine Kosten.

   Gesten (erster Schritt, nur die Auron-Seite, nicht der Windows-Bildschirm):
   - Hand bewegen     = Zeiger (sichtbarer Punkt). 16.10.2026 (Sir: "klickt nicht, hängt manchmal", "wie bei Meta Quest"):
                        Der Punkt folgt jetzt den Fingerknöcheln statt der Zeigefingerspitze. Die Knöchel bewegen sich beim
                        Pinch kaum, deshalb muss der Punkt nicht mehr anhalten (das war das "Hängen"). Der innere Punkt
                        schrumpft, je näher Daumen und Zeigefinger kommen (wie bei der Quest).
   - Daumen + Zeigefinger zusammen (Pinch) = Klick an der Stelle des Punktes (auch in Bereichsfenstern)
   - Offene Hand ca. 1 s halten = Zurück/Schließen (Ring um den Punkt zeigt den Fortschritt)
   Leistung: höchstens 15 Auswertungen pro Sekunde, Pause, solange die Seite unsichtbar ist.

   auron.html bindet die Datei ein und ruft AuronGesten.einrichten(), .starten(video), .stoppen() auf.
   Die Schwellen stehen in EINSTELLUNG. UNGETESTET AM GERÄT: Schwellen, Glättung und Treffsicherheit mit Sirs Webcam. */
(function () {
  "use strict";
  const VERSION = "0.10.35";
  const ORDNER = "/werkstatt/lib/mediapipe";
  const DATEIEN = { bibliothek: ORDNER + "/vision_bundle.mjs", wasm: ORDNER + "/wasm", modell: ORDNER + "/hand_landmarker.task" };
  const EINSTELLUNG = {
    maxProSekunde: 15,     // Auswertungen je Sekunde (Obergrenze)
    rand: 0.2,             // so viel vom Kamerabild je Seite zählt nicht (kleine Handbewegung = ganze Seite)
    pinchAn: 0.4,          // Abstand Daumen-Zeigefinger / Handgröße: darunter = zusammen (16.10.: vorher 0,33, zu streng)
    pinchAus: 0.55,        // darüber = wieder offen (Abstand zu pinchAn verhindert Flattern)
    pinchSkala: 0.9,       // ab hier schrumpft der Punkt sichtbar (Rückmeldung wie bei der Quest)
    faustGrenze: 0.25,     // Zeigefingerspitze näher am Grundgelenk (je Handgröße) = Faust, nie Klick (Faust-Foto: 0,19)
    pinchBilder: 2,        // so viele Auswertungen in Folge zusammen, dann erst Klick (gegen Fehlklicks)
    klickPause: 400,       // ms zwischen zwei Klicks
    offenHalten: 1000,     // ms offene Hand halten = Zurück
    handWeg: 600,          // ms ohne Hand, dann verschwindet der Punkt
    glaettung: { min: 1.2, beta: 0.01, d: 1.0 },   // One-Euro-Filter (Pixel)
    fehlerGrenze: 5        // so viele Fehler in Folge, dann stoppt das Modul mit Meldung
  };

  /* ---------------- Reine Rechnungen (ohne Seite, im Prüfstand getestet) ---------------- */
  // Punkte: 21 Handpunkte {x, y, z}, x/y von 0 bis 1 im Kamerabild. 0 Handgelenk, 4 Daumenspitze, 8 Zeigefingerspitze.
  const SPITZEN = [8, 12, 16, 20], MITTELGELENKE = [6, 10, 14, 18];
  function abstand(a, b, seitenverhaeltnis) {
    const s = seitenverhaeltnis || 1;
    return Math.hypot((a.x - b.x) * s, a.y - b.y);
  }
  function handgroesse(p, s) { return Math.max(1e-6, abstand(p[0], p[9], s)); }   // Handgelenk bis Mittelfinger-Grundgelenk
  function pinchVerhaeltnis(p, s) { return abstand(p[4], p[8], s) / handgroesse(p, s); }
  function fingerGestreckt(p, s) {
    return SPITZEN.map((spitze, i) => abstand(p[spitze], p[0], s) > abstand(p[MITTELGELENKE[i]], p[0], s) * 1.15);
  }
  function daumenGestreckt(p, s) { return abstand(p[4], p[17], s) > abstand(p[2], p[17], s) * 1.25; }
  function offeneHand(p, s) {
    return fingerGestreckt(p, s).every(Boolean) && daumenGestreckt(p, s) && pinchVerhaeltnis(p, s) > EINSTELLUNG.pinchAus;
  }
  // 15.10.2026: Bei einer Faust liegt der Daumen auch auf dem Zeigefinger (Abstand wie beim Pinch). Geprüft an
  // MediaPipe-Testfotos: Faust 0,19, Zeigen 0,86, offene Hand 1,14 (Zeigefingerspitze bis Grundgelenk / Handgröße).
  function faust(p, s) { return abstand(p[8], p[5], s) / handgroesse(p, s) < EINSTELLUNG.faustGrenze; }
  // Ankerpunkt für den Zeiger: Mitte der vier Fingerknöchel (5, 9, 13, 17), bleibt beim Pinch fast still
  function knoechel(p) {
    return { x: (p[5].x + p[9].x + p[13].x + p[17].x) / 4, y: (p[5].y + p[9].y + p[13].y + p[17].y) / 4 };
  }
  function einordnen(p, s) {
    const f = faust(p, s);
    return { faust: f, pinch: f ? Infinity : pinchVerhaeltnis(p, s), offen: !f && offeneHand(p, s) };
  }
  // Kamerabild ist gespiegelt angezeigt (wie ein Spiegel): rechts im Bild = links auf dem Schirm.
  function aufSchirm(punkt, breite, hoehe, rand) {
    const r = rand == null ? EINSTELLUNG.rand : rand;
    const nx = Math.min(1, Math.max(0, (1 - punkt.x - r) / (1 - 2 * r)));
    const ny = Math.min(1, Math.max(0, (punkt.y - r) / (1 - 2 * r)));
    return { x: nx * (breite - 1), y: ny * (hoehe - 1) };
  }
  function EinEuro(min, beta, d) {
    this.min = min; this.beta = beta; this.d = d; this.x = null; this.dx = 0; this.t = null;
  }
  function alpha(cutoff, dt) { const tau = 1 / (2 * Math.PI * cutoff); return 1 / (1 + tau / dt); }
  EinEuro.prototype.filtern = function (wert, t) {
    if (this.x == null || this.t == null || t <= this.t) { this.x = wert; this.dx = 0; this.t = t; return wert; }
    const dt = Math.min(1, (t - this.t) / 1000); this.t = t;
    const dx = (wert - this.x) / dt;
    this.dx += alpha(this.d, dt) * (dx - this.dx);
    this.x += alpha(this.min + this.beta * Math.abs(this.dx), dt) * (wert - this.x);
    return this.x;
  };
  EinEuro.prototype.leeren = function () { this.x = null; this.dx = 0; this.t = null; };

  /* ---------------- Zustand ---------------- */
  const z = {
    an: false, token: 0, landmarker: null, laden: null, rechner: "", video: null, uhr: 0, pause: false, dauer: 0, anzahl: 0,
    letzteAuswertung: -1e9, letzteBildzeit: -1, zeiten: [], fehlerInFolge: 0,
    hand: false, zuletztHand: -1e9, x: null, y: null, pinch: false, pinchZaehler: 0, letzterKlick: -1e9,
    offenSeit: null, offenErledigt: false, geste: "–", anzeigeZuletzt: 0
  };
  const fx = new EinEuro(EINSTELLUNG.glaettung.min, EINSTELLUNG.glaettung.beta, EINSTELLUNG.glaettung.d);
  const fy = new EinEuro(EINSTELLUNG.glaettung.min, EINSTELLUNG.glaettung.beta, EINSTELLUNG.glaettung.d);
  let haken = { zurueck: () => "", anzeige: () => {}, fehler: () => {} };

  /* ---------------- Zeiger (Punkt) ---------------- */
  let zeiger = null;
  function zeigerBauen() {
    if (zeiger) return zeiger;
    const stil = document.createElement("style");
    stil.textContent =
      ".gesten-zeiger{position:fixed;left:0;top:0;width:34px;height:34px;margin:-17px 0 0 -17px;z-index:2147483646;pointer-events:none;" +
      "border-radius:50%;display:grid;place-items:center;opacity:0;transition:opacity .2s,width .12s,height .12s,margin .12s;" +
      "background:conic-gradient(var(--metall,#d0d5de) calc(var(--halten,0)*1turn),transparent 0);will-change:transform}" +
      ".gesten-zeiger::after{content:'';width:16px;height:16px;border-radius:50%;background:var(--glut,#b8333a);" +
      "border:2px solid var(--kugel-licht,#fff);box-shadow:0 0 14px var(--glut,#b8333a)}" +
      ".gesten-zeiger::after{transform:scale(calc(1 - var(--pinch,0)*.5));transition:transform .08s}" +
      ".gesten-zeiger.da{opacity:.95}.gesten-zeiger.ueber::after{width:22px;height:22px}" +
      ".gesten-zeiger.zu::after{background:var(--metall,#d0d5de)}" +
      ".gesten-zeiger.klick::after{box-shadow:0 0 0 10px color-mix(in srgb,var(--metall,#d0d5de) 35%,transparent)}";
    document.head.appendChild(stil);
    zeiger = document.createElement("div");
    zeiger.className = "gesten-zeiger"; zeiger.id = "gestenZeiger"; zeiger.setAttribute("aria-hidden", "true");
    document.body.appendChild(zeiger);
    return zeiger;
  }
  function zeigerZeichnen(sichtbar, ueber, halten, pinch) {
    const el = zeigerBauen();
    el.classList.toggle("da", !!sichtbar);
    if (!sichtbar) return;
    el.style.transform = "translate(" + Math.round(z.x) + "px," + Math.round(z.y) + "px)";
    el.style.setProperty("--halten", String(halten || 0));
    el.style.setProperty("--pinch", (pinch || 0).toFixed(2));
    el.classList.toggle("ueber", !!ueber);
    el.classList.toggle("zu", z.pinch);
  }

  /* ---------------- Ziel unter dem Punkt (auch in Fenstern derselben Seite) ---------------- */
  function zielAn(x, y) {
    let doc = document, el = doc.elementFromPoint(x, y), ix = x, iy = y;
    for (let tiefe = 0; el && el.tagName === "IFRAME" && tiefe < 3; tiefe++) {
      let innen = null;
      try { innen = el.contentDocument; } catch (e) { innen = null; }   // fremde Seite: nicht hineinklicken
      if (!innen) break;
      const r = el.getBoundingClientRect();
      ix -= r.left + el.clientLeft; iy -= r.top + el.clientTop;
      const t = innen.elementFromPoint(ix, iy);
      if (!t) break;
      doc = innen; el = t;
    }
    return { el, doc, x: ix, y: iy };
  }
  const KLICKBAR = "button, a[href], input, textarea, select, summary, label, [role=button], [tabindex]:not([tabindex='-1'])";
  function klickbar(el) { return el && el.closest ? el.closest(KLICKBAR) : null; }
  function name(el) {
    if (!el) return "";
    const t = (el.getAttribute("aria-label") || el.getAttribute("title") || el.textContent || "").replace(/\s+/g, " ").trim();
    return t.length > 28 ? t.slice(0, 27) + "…" : t;
  }
  function klicken(x, y) {
    const ziel = zielAn(x, y);
    if (!ziel.el) return "";
    const fenster = ziel.doc.defaultView || window;
    const basis = { bubbles: true, cancelable: true, composed: true, view: fenster, clientX: ziel.x, clientY: ziel.y, button: 0 };
    const zeigerArt = { pointerId: 1, pointerType: "mouse", isPrimary: true };
    const PE = fenster.PointerEvent || fenster.MouseEvent, ME = fenster.MouseEvent;
    ziel.el.dispatchEvent(new PE("pointerdown", Object.assign({ buttons: 1 }, basis, zeigerArt)));
    ziel.el.dispatchEvent(new ME("mousedown", Object.assign({ buttons: 1 }, basis)));
    const k = klickbar(ziel.el);
    if (k && typeof k.focus === "function") { try { k.focus({ preventScroll: true }); } catch (e) {} }
    ziel.el.dispatchEvent(new PE("pointerup", Object.assign({ buttons: 0 }, basis, zeigerArt)));
    ziel.el.dispatchEvent(new ME("mouseup", Object.assign({ buttons: 0 }, basis)));
    ziel.el.dispatchEvent(new ME("click", Object.assign({ buttons: 0, detail: 1 }, basis)));
    return name(k || ziel.el) || ziel.el.tagName.toLowerCase();
  }

  /* ---------------- Eine Auswertung verarbeiten ---------------- */
  function gesteMerken(t) { z.geste = t; anzeigen(true); }
  function handWeg(jetzt) {
    z.hand = false; z.pinch = false; z.abstand = null; z.pinchZaehler = 0; z.offenSeit = null; z.offenErledigt = false;
    if (jetzt - z.zuletztHand > EINSTELLUNG.handWeg) { zeigerZeichnen(false); fx.leeren(); fy.leeren(); z.x = z.y = null; }
  }
  // punkte = 21 Handpunkte oder null (keine Hand); jetzt = Zeit in ms; seiten = Breite/Höhe des Kamerabilds
  function verarbeiten(punkte, jetzt, seiten) {
    if (!punkte || punkte.length < 21) { handWeg(jetzt); anzeigen(false); return; }
    const s = seiten || 16 / 9;
    z.hand = true; z.zuletztHand = jetzt;
    const art = einordnen(punkte, s), v = art.pinch, offen = art.offen;
    z.abstand = v;
    const roh = aufSchirm(knoechel(punkte), window.innerWidth, window.innerHeight);
    z.x = fx.filtern(roh.x, jetzt); z.y = fy.filtern(roh.y, jetzt);
    // Pinch = Klick (einmal je Zusammenführen)
    if (!z.pinch) {
      if (v < EINSTELLUNG.pinchAn) {
        if (++z.pinchZaehler >= EINSTELLUNG.pinchBilder) {
          z.pinch = true; z.pinchZaehler = 0;
          if (jetzt - z.letzterKlick >= EINSTELLUNG.klickPause) {
            z.letzterKlick = jetzt;
            let was = "";
            try { was = klicken(z.x, z.y); } catch (e) { was = ""; }
            const el = zeigerBauen(); el.classList.add("klick"); setTimeout(() => el.classList.remove("klick"), 220);
            gesteMerken(was ? "Klick: " + was : "Klick (nichts getroffen)");
          }
        }
      } else z.pinchZaehler = 0;
    } else if (v > EINSTELLUNG.pinchAus) z.pinch = false;
    // Offene Hand halten = Zurück/Schließen (erst wieder nach Schließen der Hand)
    let halten = 0;
    if (offen && !z.pinch) {
      if (z.offenSeit == null) z.offenSeit = jetzt;
      halten = z.offenErledigt ? 0 : Math.min(1, (jetzt - z.offenSeit) / EINSTELLUNG.offenHalten);
      if (!z.offenErledigt && halten >= 1) {
        z.offenErledigt = true; halten = 0;
        let was = "";
        try { was = haken.zurueck() || ""; } catch (e) { was = ""; }
        gesteMerken(was ? "Zurück: " + was : "Zurück (nichts offen)");
      }
    } else { z.offenSeit = null; z.offenErledigt = false; }
    let ueber = false;
    try { ueber = !!klickbar(zielAn(z.x, z.y).el); } catch (e) { ueber = false; }
    const E = EINSTELLUNG, pinch = z.pinch ? 1 : Math.min(1, Math.max(0, (E.pinchSkala - v) / (E.pinchSkala - E.pinchAn)));
    zeigerZeichnen(true, ueber, halten, pinch);
    anzeigen(false);
  }

  /* ---------------- Anzeige ---------------- */
  function rate(jetzt) {
    const t = jetzt == null ? performance.now() : jetzt;
    while (z.zeiten.length && t - z.zeiten[0] > 1000) z.zeiten.shift();
    return z.zeiten.length;
  }
  function info() {
    return { an: z.an, pause: z.pause, hand: z.hand, proSekunde: z.an && !z.pause ? rate() : 0, geste: z.geste,
      laedt: !!z.laden && !z.landmarker, rechner: z.rechner, msJeAuswertung: Math.round(z.dauer), gesamt: z.anzahl, abstand: z.abstand, klickUnter: EINSTELLUNG.pinchAn, version: VERSION };
  }
  function anzeigen(sofort) {
    const t = performance.now();
    if (!sofort && t - z.anzeigeZuletzt < 250) return;
    z.anzeigeZuletzt = t;
    try { haken.anzeige(info()); } catch (e) {}
  }

  /* ---------------- MediaPipe laden ---------------- */
  async function vorhanden(adresse) {
    try { const r = await fetch(adresse, { method: "HEAD", cache: "no-store" }); return r.ok; } catch (e) { return false; }
  }
  async function landmarkerLaden() {
    if (z.landmarker) return z.landmarker;
    if (z.laden) return z.laden;
    z.laden = (async () => {
      const fehlt = [];
      for (const a of [DATEIEN.bibliothek, DATEIEN.modell, DATEIEN.wasm + "/vision_wasm_internal.wasm"]) if (!(await vorhanden(a))) fehlt.push(a.split("/").pop());
      if (fehlt.length) throw new Error("Die Gesten-Dateien fehlen (" + fehlt.join(", ") + "). Bitte einmal werkstatt\\GESTEN_HOLEN.bat starten, dann Strg+F5.");
      // Über einen Blob laden: so stört es nicht, wenn Windows .mjs mit falschem Dateityp ausliefert
      const r = await fetch(DATEIEN.bibliothek);
      if (!r.ok) throw new Error("MediaPipe lässt sich nicht laden (Status " + r.status + ").");
      const quelle = (await r.text()).replace(/\/\/# sourceMappingURL=.*$/m, "");
      const url = URL.createObjectURL(new Blob([quelle], { type: "text/javascript" }));
      let mp;
      try { mp = await import(url); } finally { URL.revokeObjectURL(url); }
      const dateien = await mp.FilesetResolver.forVisionTasks(DATEIEN.wasm);
      const optionen = (delegate) => ({ baseOptions: { modelAssetPath: DATEIEN.modell, delegate }, runningMode: "VIDEO", numHands: 1,
        minHandDetectionConfidence: 0.6, minHandPresenceConfidence: 0.6, minTrackingConfidence: 0.5 });
      try { z.landmarker = await mp.HandLandmarker.createFromOptions(dateien, optionen("GPU")); z.rechner = "GPU"; }
      catch (e) { z.landmarker = await mp.HandLandmarker.createFromOptions(dateien, optionen("CPU")); z.rechner = "CPU"; }   // ohne Grafikkarte
      return z.landmarker;
    })();
    try { return await z.laden; } catch (e) { z.laden = null; throw e; }
  }

  /* ---------------- Schleife (höchstens 15 je Sekunde, Pause bei unsichtbarer Seite) ----------------
     Nach jeder Auswertung mindestens so lange Pause, wie sie gedauert hat: auf einem langsamen Rechner (ohne
     Grafikkarte) belegt die Erkennung so höchstens die Hälfte der Zeit, die Seite bleibt bedienbar. */
  function planen() {
    clearTimeout(z.uhr); z.uhr = 0;
    if (!z.an || z.pause) return;
    const abstand = 1000 / EINSTELLUNG.maxProSekunde;
    z.uhr = setTimeout(schritt, Math.max(4, z.letzteAuswertung + abstand - performance.now(), Math.min(500, z.dauer)));
  }
  function schritt() {
    z.uhr = 0;
    if (!z.an || z.pause) return;
    const v = z.video, jetzt = performance.now();
    if (jetzt - z.letzteAuswertung < 1000 / EINSTELLUNG.maxProSekunde) { planen(); return; }
    if (v && v.readyState >= 2 && v.videoWidth && v.currentTime !== z.letzteBildzeit) {
      z.letzteAuswertung = jetzt; z.letzteBildzeit = v.currentTime;
      try {
        const erg = z.landmarker.detectForVideo(v, jetzt);
        const d = performance.now() - jetzt;   // die erste Auswertung wärmt nur auf (langsam), zählt nicht
        if (z.anzahl++ > 0) z.dauer = z.dauer ? z.dauer * 0.8 + d * 0.2 : d;
        z.fehlerInFolge = 0; z.zeiten.push(jetzt);
        verarbeiten(erg && erg.landmarks && erg.landmarks[0] ? erg.landmarks[0] : null, jetzt, v.videoWidth / v.videoHeight);
      } catch (e) {
        if (++z.fehlerInFolge >= EINSTELLUNG.fehlerGrenze) {
          stoppen();
          try { haken.fehler("Die Gesten-Erkennung ist ausgefallen (" + ((e && e.message) || e) + "). Gesten sind aus, Sir."); } catch (x) {}
          return;
        }
      }
    }
    planen();
  }
  function sichtbarkeit() {
    if (!z.an) return;
    z.pause = document.visibilityState === "hidden";
    if (z.pause) { clearTimeout(z.uhr); z.uhr = 0; z.zeiten = []; handWeg(1e12); }
    else planen();
    anzeigen(true);
  }
  document.addEventListener("visibilitychange", sichtbarkeit);

  /* ---------------- Schnittstelle für auron.html ---------------- */
  function einrichten(h) { haken = Object.assign({}, haken, h || {}); zeigerBauen(); }
  async function starten(video) {
    if (z.an) return;
    const mein = ++z.token;
    z.video = video; z.geste = "–"; anzeigen(true);
    await landmarkerLaden();
    if (mein !== z.token) return;   // inzwischen wieder ausgeschaltet
    z.an = true; z.fehlerInFolge = 0; z.zeiten = []; z.letzteAuswertung = -1e9; z.letzteBildzeit = -1; z.dauer = 0; z.anzahl = 0;
    z.pause = document.visibilityState === "hidden";
    planen(); anzeigen(true);
  }
  function stoppen() {
    z.token++; z.an = false; z.pause = false; clearTimeout(z.uhr); z.uhr = 0; z.zeiten = [];
    handWeg(1e12); z.video = null; anzeigen(true);
  }
  window.AuronGesten = {
    VERSION, EINSTELLUNG, einrichten, starten, stoppen, verarbeiten, info,
    rechnen: { abstand, knoechel, pinchVerhaeltnis, fingerGestreckt, daumenGestreckt, offeneHand, faust, einordnen, aufSchirm, EinEuro }
  };
})();

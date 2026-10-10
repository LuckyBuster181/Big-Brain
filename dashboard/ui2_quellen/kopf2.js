  function kopfPunkte(anzahl, mitLinien) {
    /* KI-Frau aus Licht (Wunsch Sir, 27.09.2026): weiche weibliche Züge, lange wellige Haare aus
       Lichtfäden, mandelförmige Augen ohne Leuchtpupillen, volle Lippen. Keine echte Person als Vorlage.
       Typen (aB): 1 Haut, 1.3 Lippen, 2 Augen, 3 Haare (aM = Position im Strang 0..1). */
    const L = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
    const ell = (p, c, r) => { const x = (p[0] - c[0]) / r[0], y = (p[1] - c[1]) / r[1], z = (p[2] - c[2]) / r[2];
      const k0 = Math.hypot(x, y, z), k1 = Math.hypot(x / r[0], y / r[1], z / r[2]); return k1 < 1e-6 ? -Math.min(...r) : k0 * (k0 - 1) / k1; };
    const kapsel = (p, a, b, r) => { const pa = [0, 1, 2].map((i) => p[i] - a[i]), ba = [0, 1, 2].map((i) => b[i] - a[i]);
      const h2 = Math.max(0, Math.min(1, (pa[0] * ba[0] + pa[1] * ba[1] + pa[2] * ba[2]) / (ba[0] * ba[0] + ba[1] * ba[1] + ba[2] * ba[2])));
      return Math.hypot(pa[0] - ba[0] * h2, pa[1] - ba[1] * h2, pa[2] - ba[2] * h2) - r; };
    const smin = (a, b, k) => { const h2 = Math.max(k - Math.abs(a - b), 0) / k; return Math.min(a, b) - h2 * h2 * k * 0.25; };
    const smax = (a, b, k) => -smin(-a, -b, k);
    const sdf = (p) => {
      let d = ell(p, [0, 0.2, -0.06], [0.68, 0.82, 0.8]);                    // Schädel
      d = smin(d, ell(p, [0, -0.22, 0.12], [0.45, 0.6, 0.56]), 0.22);         // Gesicht, schmal
      d = smin(d, ell(p, [0, -0.55, 0.14], [0.33, 0.24, 0.42]), 0.18);        // Kiefer, weich
      d = smin(d, ell(p, [0, -0.73, 0.33], [0.14, 0.1, 0.14]), 0.1);          // Kinn, klein
      for (const sx of [1, -1]) {
        d = smin(d, ell(p, [0.33 * sx, -0.05, 0.44], [0.15, 0.1, 0.16]), 0.12); // Wangenknochen, hoch und weich
        d = smin(d, ell(p, [0.21 * sx, 0.25, 0.62], [0.13, 0.02, 0.05]), 0.04); // Brauen, schmal
        d = smax(d, -(L(p, [0.2 * sx, 0.08, 0.72]) - 0.1), 0.06);               // Augenhöhlen, flach
        d = smin(d, L(p, [0.2 * sx, 0.075, 0.635]) - 0.08, 0.03);               // Augäpfel
        d = smin(d, L(p, [0.05 * sx, -0.25, 0.74]) - 0.04, 0.03);               // Nasenflügel, zierlich
      }
      d = smin(d, ell(p, [0, 0.26, 0.56], [0.4, 0.06, 0.12]), 0.08);          // Stirn
      d = smin(d, kapsel(p, [0, 0.06, 0.66], [0, -0.19, 0.8], 0.035), 0.05);  // Nasenrücken, schmal
      d = smin(d, L(p, [0, -0.21, 0.79]) - 0.055, 0.04);                     // Nasenspitze
      d = smin(d, ell(p, [0, -0.4, 0.72], [0.14, 0.045, 0.07]), 0.035);      // Oberlippe, voll
      d = smin(d, ell(p, [0, -0.485, 0.71], [0.13, 0.055, 0.07]), 0.035);    // Unterlippe, voll
      d = smax(d, -ell(p, [0, -0.44, 0.78], [0.13, 0.007, 0.08]), 0.01);     // Mundspalt
      d = smin(d, ell(p, [0, -1.06, -0.05], [0.22, 0.5, 0.24]), 0.18);        // Hals, schlank
      d = smin(d, ell(p, [0, -1.62, -0.1], [0.92, 0.26, 0.4]), 0.3);          // Schultern
      return d;
    };
    let seed = 11;
    const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    const flaeche = (o, dir) => {
      if (sdf(o) > 0) return null;
      let t = 0; const schritt = 0.025;
      while (t < 1.8) { if (sdf([o[0] + dir[0] * (t + schritt), o[1] + dir[1] * (t + schritt), o[2] + dir[2] * (t + schritt)]) > 0) break; t += schritt; }
      if (t >= 1.8) return null;
      let a = t, b = t + schritt;
      for (let i = 0; i < 16; i++) { const m = (a + b) / 2; if (sdf([o[0] + dir[0] * m, o[1] + dir[1] * m, o[2] + dir[2] * m]) > 0) b = m; else a = m; }
      return [o[0] + dir[0] * a, o[1] + dir[1] * a, o[2] + dir[2] * a];
    };
    const vorn = (x, y) => {
      let z = 1.3; while (z > -0.2) { if (sdf([x, y, z]) < 0) break; z -= 0.02; }
      if (z <= -0.2) return null;
      let a = z, b = z + 0.02;
      for (let i = 0; i < 12; i++) { const m = (a + b) / 2; if (sdf([x, y, m]) < 0) a = m; else b = m; }
      return [x, y, a];
    };
    const pts = [], mund = [], hell = [], nor = [], saat = [];
    const normale = (p) => { const e = 0.008, g = [0, 1, 2].map((i) => { const a = p.slice(), b = p.slice(); a[i] += e; b[i] -= e; return sdf(a) - sdf(b); });
      const l = Math.hypot(g[0], g[1], g[2]) || 1; return [g[0] / l, g[1] / l, g[2] / l]; };
    const add = (p, b, m, nn) => {
      if (m === undefined) {
        const y = p[1], z = p[2];
        m = y > -0.92 && y < -0.44 ? Math.min(1, (-0.44 - y) / 0.08) * Math.max(0, Math.min(1, (z - 0.1) / 0.3)) : 0;
      }
      pts.push(p[0], p[1], p[2]); mund.push(m); hell.push(b); saat.push(rand());
      nn = nn || normale(p); nor.push(nn[0], nn[1], nn[2]);
    };
    const ziel = (anteil) => mund.length + Math.round(anzahl * anteil);

    // 1) Gesicht (vorne dichter), Hinterkopf nur dünn - dort liegen die Haare
    const kopfZiel = ziel(mitLinien ? 0.2 : 0.36);
    let versuche = 0;
    while (mund.length < kopfZiel && versuche < anzahl * 8) {
      versuche++;
      const u = rand() * 2 - 1, w = rand() * Math.PI * 2, s2 = Math.sqrt(1 - u * u);
      const dir = [s2 * Math.cos(w), u, s2 * Math.sin(w)];
      if (dir[2] < 0.1 && rand() < 0.8) continue;
      const p = flaeche([0, -0.12, 0.08], dir);
      if (p && p[1] > -0.95) add(p, 1);
    }
    if (mitLinien) {                                   // Scan-Linien über das Gesicht
      const linien = 40, pro = Math.round(anzahl * 0.16 / linien);
      for (let i = 0; i < linien; i++) {
        const y = 0.55 - (1.4 * i) / (linien - 1);
        for (let j = 0; j < pro; j++) { const p = vorn(-0.55 + 1.1 * (j + rand() * 0.15) / pro, y); if (p && p[2] > 0.2) add(p, 1); }
      }
    }
    // 2) Hals und Schultern als feine Ringe
    const ringe = 22, proRing = Math.round(anzahl * 0.12 / ringe);
    for (let i = 0; i < ringe; i++) {
      const y = -1.85 + (0.95 * i) / (ringe - 1);
      for (let j = 0; j < proRing; j++) {
        const w = (j / proRing) * Math.PI * 2;
        const p = flaeche([0, y, -0.06], [Math.sin(w), 0, Math.cos(w)]);
        if (p) add(p, 1);
      }
    }
    // 3) Lippen dichter, rosé
    for (let i = 0; i < Math.round(anzahl * 0.025); i++) {
      const x = (rand() * 2 - 1) * 0.14, y = -0.36 - rand() * 0.18;
      const ov = (x / 0.14) ** 2 + ((y + 0.44) / 0.085) ** 2;
      if (ov > 1) continue;
      const p = vorn(x, y); if (p) add([p[0], p[1], p[2] + 0.004], 1.3);
    }
    // 4) Augen: Mandelform, Iris als feiner Ring, Wimpern-Schwung außen - nichts leuchtet grell
    for (const sx of [1, -1]) {
      const cx = 0.2 * sx, cy = 0.075;
      for (let i = 0; i < 90; i++) {
        const t = (i / 90) * Math.PI * 2, oben = Math.sin(t) > 0;
        const x = cx + 0.1 * Math.cos(t), y = cy + (oben ? 0.048 : 0.03) * Math.sin(t) + (oben ? 0.006 * Math.cos(t) * sx : 0);
        const p = vorn(x, y); if (p) add([p[0], p[1], p[2] + 0.01], 2, 0, [0, 0, 1]);
      }
      for (let i = 0; i < 40; i++) {
        const t = (i / 40) * Math.PI * 2, p = vorn(cx + 0.032 * Math.cos(t), cy + 0.032 * Math.sin(t));
        if (p) add([p[0], p[1], p[2] + 0.012], 2, 0, [0, 0, 1]);
      }
      for (let i = 0; i < 14; i++) {                  // Wimpern-Schwung
        const t = i / 13, x = cx + sx * (0.1 + 0.05 * t), y = cy + 0.01 + 0.035 * t * t;
        const p = vorn(cx + sx * 0.095, cy); if (p) add([x, y, p[2] - 0.02 * t], 2, 0, [0, 0, 1]);
      }
    }
    // 5) Brauen als feiner Bogen in Haarfarbe
    for (const sx of [1, -1]) for (let i = 0; i < 50; i++) {
      const t = i / 49, x = sx * (0.1 + 0.2 * t), y = 0.2 + 0.05 * Math.sin(Math.PI * Math.min(1, t * 1.2)) - 0.02 * t;
      const p = vorn(x, y); if (p) add([p[0], p[1], p[2] + 0.008], 3, 0, [0, 0, 1]);
    }
    // 6) Haare: lange, wellige Lichtfäden mit Mittelscheitel, rahmen das Gesicht, fallen über die Schultern
    const proStrang = 56, straenge = Math.max(40, Math.round(anzahl * 0.42 / proStrang));
    const mitte = [0, 0.15, -0.06];
    for (let s = 0; s < straenge; s++) {
      // Wurzel: Oberkopf, Seiten, Hinterkopf; vorne nur am Haaransatz
      let wurzel = null, n0 = null;
      for (let v = 0; v < 30 && !wurzel; v++) {
        const w = rand() * Math.PI * 2, u = 0.1 + rand() * 0.9;
        const d = [Math.cos(w) * Math.sqrt(1 - u * u), u, Math.sin(w) * Math.sqrt(1 - u * u)];
        if (d[2] > 0.25 && d[1] < 0.72) continue;      // Stirn und Gesicht frei lassen
        if (d[2] < -0.2 && d[1] < -0.1) continue;
        const p = flaeche(mitte, d); if (p) { wurzel = p; n0 = d; }
      }
      if (!wurzel) continue;
      const seite = Math.abs(wurzel[0]) < 0.03 ? (rand() < 0.5 ? -1 : 1) : Math.sign(wurzel[0]);
      const laenge = 2.0 + rand() * 0.7, schritt = laenge / proStrang;
      const phase = rand() * 6.28, welle = 0.035 + rand() * 0.03;
      let pos = wurzel.map((x, i) => x + n0[i] * 0.025);
      let dir = [n0[0] * 0.6 + seite * 0.5, n0[1] * 0.4, n0[2] * 0.6];
      for (let i = 0; i < proStrang; i++) {
        const u = i / (proStrang - 1);
        const g = Math.min(1, 0.25 + u * 1.6);            // Schwerkraft zieht nach unten
        dir = [dir[0] * (1 - g * 0.35), dir[1] * (1 - g * 0.35) - g * 0.35, dir[2] * (1 - g * 0.35)];
        const dl = Math.hypot(...dir) || 1; dir = dir.map((x) => x / dl);
        pos = pos.map((x, k) => x + dir[k] * schritt);
        // nicht in Kopf, Hals oder Schultern
        let d = sdf(pos);
        for (let k = 0; k < 4 && d < 0.035; k++) { const nn = normale(pos); pos = pos.map((x, j) => x + nn[j] * (0.035 - d)); d = sdf(pos); }
        // Gesicht frei halten: vor dem Gesicht nach außen schieben
        if (pos[2] > 0.0 && pos[1] < 0.42 && pos[1] > -1.0 && Math.abs(pos[0]) < 0.53) pos[0] = Math.sign(pos[0] || seite) * (0.53 + rand() * 0.02);
        const quer = Math.sin(u * 11 + phase) * welle * Math.min(1, u * 3);   // Wellen wie gelockte lange Haare
        const p = [pos[0] + quer * Math.sign(pos[0] || 1) * 0.7 + (rand() - 0.5) * 0.012, pos[1] + (rand() - 0.5) * 0.012, pos[2] + quer * 0.7 + (rand() - 0.5) * 0.012];
        const nh = [p[0] - mitte[0], p[1] - mitte[1] * 0.3, p[2] - mitte[2]], lh = Math.hypot(...nh) || 1;
        add(p, 3, u, nh.map((x) => x / lh));
      }
    }
    // 7) Vorhang-Pony: Strähnen vom Scheitel seitlich am Gesicht vorbei (wie in den Vorlagen)
    const pony = Math.round(straenge * 0.22);
    for (let s = 0; s < pony; s++) {
      const seite = s % 2 ? 1 : -1, x0 = seite * (0.03 + rand() * 0.12);
      const start = flaeche(mitte, [x0 * 1.5, 0.75, 0.62]); if (!start) continue;
      const phase = rand() * 6.28;
      for (let i = 0; i < proStrang; i++) {
        const u = i / (proStrang - 1);
        // Bogen: über die Stirn nach außen, an der Schläfe vorbei, am Kinn entlang nach unten
        const bx = seite * (Math.abs(x0) + 0.5 * Math.sin(Math.min(1, u * 1.8) * Math.PI / 2)) + seite * 0.04 * Math.sin(u * 9 + phase);
        const by = start[1] - u * 1.9 + 0.08 * Math.sin(u * Math.PI);
        let bz = start[2] + 0.04 - u * 0.35;
        let p = [bx, by, bz];
        const fz = vorn(Math.max(-0.6, Math.min(0.6, bx)), by);
        if (fz && p[2] < fz[2] + 0.04) p[2] = fz[2] + 0.04;
        if (p[2] > 0 && p[1] < 0.42 && p[1] > -1.0 && Math.abs(p[0]) < 0.53) p[0] = seite * (0.53 + rand() * 0.02);
        p = [p[0] + (rand() - 0.5) * 0.012, p[1] + (rand() - 0.5) * 0.012, p[2] + (rand() - 0.5) * 0.012];
        add(p, 3, u * 0.8, [seite * 0.4, 0.2, 0.9]);
      }
    }
    return { pos: new Float32Array(pts), mund: new Float32Array(mund), hell: new Float32Array(hell),
             nor: new Float32Array(nor), saat: new Float32Array(saat), n: mund.length };
  }

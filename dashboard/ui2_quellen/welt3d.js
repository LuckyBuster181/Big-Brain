  /* ---------------------------------------------------------------- WebGL: Universum und Kopf (Fassung 2)
     Wünsche Sir 26.09. spät: Schwarzes Loch realistischer, farbiger (Jarvis-Farben), mehr Bewegung;
     Kopf mit echtem Gesicht und als Partikel-Schwarm, der im Leerlauf zerfließt. */
  const QUAL = {
    niedrig: { skala: 0.45, okt: 3, punkte: 5000, teilchen: 1200 },
    mittel: { skala: 0.7, okt: 4, punkte: 11000, teilchen: 2600 },
    hoch: { skala: 1, okt: 5, punkte: 20000, teilchen: 5000 },
  };
  const VS_FLAECHE = "attribute vec2 p; void main(){ gl_Position = vec4(p, 0.0, 1.0); }";
  const FS_WELT = `precision highp float;
uniform vec2 uRes; uniform float uT, uE, uLoch, uOkt; uniform vec3 uCol;
float h(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float n(vec2 p){ vec2 i = floor(p), f = fract(p); f = f*f*(3.0-2.0*f);
  return mix(mix(h(i), h(i+vec2(1.0,0.0)), f.x), mix(h(i+vec2(0.0,1.0)), h(i+vec2(1.0,1.0)), f.x), f.y); }
float fbm(vec2 p){ float s = 0.0, a = 0.5; for (int i = 0; i < 6; i++){ if (float(i) >= uOkt) break; s += a*n(p); p = p*2.03 + 7.1; a *= 0.5; } return s; }
vec3 sterne(vec2 p){ vec3 c = vec3(0.0);
  for (int k = 0; k < 2; k++){ float sk = k == 0 ? 90.0 : 190.0; vec2 g = floor(p*sk), f = fract(p*sk) - 0.5; float r = h(g + float(k)*17.0);
    if (r > 0.982){ float tw = 0.55 + 0.45*sin(uT*(1.0 + r*3.0) + r*80.0); c += mix(vec3(0.7,0.85,1.0), vec3(1.0,0.85,0.6), fract(r*37.0)) * smoothstep(0.13, 0.0, length(f)) * tw * (k == 0 ? 1.0 : 0.6); } }
  return c; }
vec3 galaxie(vec2 p){ vec2 q = vec2(p.x, p.y*2.4); float r = length(q); float a = atan(q.y, q.x);
  float sp = a*2.0 + log(r + 0.001)*4.2 - uT*0.06; float arm = pow(0.5 + 0.5*cos(sp), 2.5);
  float staub = fbm(q*3.2 + vec2(uT*0.012, 0.0)); float dicht = exp(-r*1.4);
  vec3 c = mix(uCol*vec3(0.55,0.75,1.0), vec3(1.0,0.74,0.38), exp(-r*2.0));
  return c * dicht * (0.14 + arm*0.8) * (0.45 + 0.9*staub); }
/* Temperatur der Scheibe: innen weiss-cyan, Mitte gold, aussen tief orange */
vec3 glut(float x){ vec3 heiss = mix(vec3(1.0), uCol, 0.35); vec3 gold = vec3(1.0, 0.72, 0.28); vec3 rand = vec3(0.85, 0.28, 0.08);
  return x < 0.5 ? mix(heiss, gold, x*2.0) : mix(gold, rand, (x-0.5)*2.0); }
float scheibe(vec2 dp, float rs, out vec3 farbe){
  float dr = length(dp), da = atan(dp.y, dp.x);
  float innen = rs*2.3, aussen = rs*9.0;
  if (dr < innen*0.92 || dr > aussen*1.1) { farbe = vec3(0.0); return 0.0; }
  float x = clamp((dr - innen)/(aussen - innen), 0.0, 1.0);
  float om = pow(innen/dr, 1.5);                       /* Kepler: innen schneller */
  float wink = da + uT*(0.55 + uE*0.8)*om*2.2;
  float streif = fbm(vec2(wink*5.0, log(dr)*26.0)) * 0.7 + fbm(vec2(wink*13.0, log(dr)*60.0)) * 0.5;
  float kante = smoothstep(innen*0.92, innen*1.08, dr) * (1.0 - smoothstep(aussen*0.6, aussen*1.1, dr));
  float strahl = pow(1.0 + 0.75*cos(da + 0.35), 2.2);  /* Doppler: eine Seite heller */
  farbe = glut(x) * mix(vec3(0.75,0.9,1.15), vec3(1.15,0.95,0.8), 0.5 + 0.5*cos(da + 0.35 + 3.14159));
  return kante * (0.25 + streif) * strahl * pow(1.0 - x, 1.6) * 2.4 * (1.0 + uE*1.4);
}
void main(){
  vec2 uv = (gl_FragCoord.xy - 0.5*uRes) / uRes.y; uv.y -= 0.04;
  uv *= 1.0 - 0.04*uE*uLoch;                            /* beim Sprechen leicht heranzoomen */
  float rs = 0.052 * uLoch;
  float r = length(uv); vec2 dir = uv / max(r, 0.0001);
  float bend = uLoch > 0.0 ? rs*rs*3.2/max(r, rs*0.7) : 0.0;
  vec2 luv = uv - dir*bend;
  vec3 col = sterne(luv*1.1) + galaxie(luv*0.9)*(uLoch + uE*0.2*uLoch);
  col += vec3(0.012,0.018,0.04)*fbm(luv*1.6 + 11.0) + uCol*(0.02 + 0.05*(1.0-uLoch))*fbm(luv*3.0 - uT*0.02);
  if (uLoch < 0.5) col += uCol * 0.09 * exp(-pow(length(uv*vec2(0.8,1.0)) / 0.55, 2.0)) * (1.0 + uE);
  if (uLoch > 0.0){
    float schatten = smoothstep(rs*1.02, rs*0.94, r);
    vec3 f1, f2, f3;
    float vorn = scheibe(vec2(uv.x, uv.y/0.13), rs, f1);                       /* direkte Scheibe */
    float oben = scheibe(vec2(uv.x*0.98, (uv.y - rs*0.18)/0.82), rs*0.72, f2)  /* Rückseite, über das Loch gebogen */
               * smoothstep(-rs*0.1, rs*0.5, uv.y);
    float unten = scheibe(vec2(uv.x*0.98, (uv.y + rs*0.12)/0.7), rs*0.62, f3) * smoothstep(rs*0.1, -rs*0.6, uv.y) * 0.35;
    float foton = exp(-pow((r - rs*1.08)/(rs*0.045), 2.0)) * 1.4 + exp(-pow((r - rs*1.2)/(rs*0.16), 2.0)) * 0.35;
    col *= 1.0 - schatten;
    float davor = step(uv.y, 0.0);
    col += (f2*oben + f3*unten) * (1.0 - schatten);
    col += f1*vorn * mix(1.0 - schatten, 1.0, davor);
    col += mix(vec3(1.0), uCol, 0.4) * foton * (1.0 + uE*1.2) * (1.0 - schatten*0.6);
    col += uCol * 0.05 * exp(-r*7.0) * (1.0 + uE*2.0);
  }
  col = 1.0 - exp(-col*1.3);
  gl_FragColor = vec4(pow(col, vec3(0.95)), 1.0);
}`;
  /* Teilchen, die ins Schwarze Loch gezogen werden (spiralförmig, innen schneller) */
  const VS_TEIL = `attribute vec4 aD; uniform float uT, uE, uAsp, uRs, uGr; varying float vH; varying float vX;
void main(){ float r0 = aD.x, a0 = aD.y, sp = aD.z, ph = aD.w;
  float leben = fract(uT*sp*(1.0 + uE*0.8) + ph);
  float innen = uRs*2.2; float r = mix(r0, innen, pow(leben, 1.7));
  float a = a0 + uT*0.35*pow(uRs*3.0/r, 1.5) + leben*5.0;
  vec2 uv = vec2(cos(a)*r, sin(a)*r*0.13);
  float hinten = step(0.0, uv.y) * step(length(uv), uRs*1.05);
  uv.y += 0.04;
  gl_Position = vec4(uv.x*2.0/uAsp, uv.y*2.0, 0.0, 1.0);
  vX = clamp((r - innen)/(r0 - innen + 0.0001), 0.0, 1.0);
  vH = (1.0 - hinten) * smoothstep(0.0, 0.08, leben) * smoothstep(1.0, 0.9, leben) * (0.35 + 0.9*(1.0 - vX));
  gl_PointSize = uGr * (0.8 + 1.6*(1.0 - vX));
}`;
  const FS_TEIL = `precision highp float; uniform vec3 uCol; varying float vH; varying float vX;
void main(){ float d = length(gl_PointCoord - 0.5); if (d > 0.5) discard;
  vec3 c = mix(mix(vec3(1.0), uCol, 0.4), vec3(1.0, 0.7, 0.3), vX);
  gl_FragColor = vec4(c * vH * smoothstep(0.5, 0.0, d), 1.0); }`;
  const VS_KOPF = `attribute vec3 aP; attribute float aM; attribute float aB; attribute vec3 aN; attribute float aS;
uniform float uT, uE, uYaw, uPitch, uAsp, uGr, uZ;
varying float vA; varying float vB;
vec3 dreh(vec3 p, float cy, float sy, float cp, float sp){ p = vec3(cy*p.x + sy*p.z, p.y, -sy*p.x + cy*p.z); return vec3(p.x, cp*p.y - sp*p.z, sp*p.y + cp*p.z); }
void main(){ vec3 p = aP; p.y -= aM*uE*0.1; p.z -= aM*uE*0.02;
  p *= 1.0 + 0.008*sin(uT*1.6);
  vec3 wob = vec3(sin(uT*0.7 + aS*40.0), sin(uT*0.9 + aS*57.0), cos(uT*0.8 + aS*33.0));
  float zerf = uZ * aS;
  p += wob * (0.008 + 0.03*uE*aM + 0.45*zerf) + vec3(0.0, zerf*0.9*fract(uT*0.03 + aS), 0.0);
  float cy = cos(uYaw), sy = sin(uYaw), cp = cos(uPitch), sp = sin(uPitch);
  p = dreh(p, cy, sy, cp, sp); vec3 nn = normalize(dreh(aN, cy, sy, cp, sp));
  float z = 3.6 - p.z; vec2 s = p.xy * 1.75 / z; s.y += 0.16;
  gl_Position = vec4(s.x/uAsp, s.y, 0.0, 1.0);
  float licht = max(dot(nn, normalize(vec3(-0.45, 0.35, 0.85))), 0.0);
  float rand = pow(1.0 - abs(nn.z), 2.5);
  vA = (0.16 + 0.7*licht + 0.5*rand) * (0.45 + 0.55*smoothstep(-0.9, 0.9, p.z)) * (1.0 - 0.55*zerf); vB = aB;
  gl_PointSize = uGr * (0.6 + 0.7*vA) * (aB > 1.5 ? 1.7 : 1.0) * (1.0 + zerf*0.8);
}`;
  const FS_KOPF = `precision highp float; uniform vec3 uCol; uniform float uT, uE; uniform vec2 uRes; varying float vA; varying float vB;
void main(){ vec2 c = gl_PointCoord - 0.5; float d = length(c); if (d > 0.5) discard;
  float a = smoothstep(0.5, 0.0, d);
  float scan = 1.0 + 0.8*exp(-pow(mod(gl_FragCoord.y - uT*140.0, uRes.y*1.3) - uRes.y*0.5, 2.0)/900.0);
  vec3 col = uCol * vA * 1.7 * (vB > 1.5 ? 1.8 + uE*2.0 : 1.0) * scan;
  gl_FragColor = vec4(col * a * (0.55 + 0.45*vA), a); }`;

  function kopfPunkte(anzahl) {
    const L = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
    const ell = (p, c, r) => { const x = (p[0] - c[0]) / r[0], y = (p[1] - c[1]) / r[1], z = (p[2] - c[2]) / r[2];
      const k0 = Math.hypot(x, y, z), k1 = Math.hypot(x / r[0], y / r[1], z / r[2]); return k1 < 1e-6 ? -Math.min(...r) : k0 * (k0 - 1) / k1; };
    const kapsel = (p, a, b, r) => { const pa = [0, 1, 2].map((i) => p[i] - a[i]), ba = [0, 1, 2].map((i) => b[i] - a[i]);
      const h2 = Math.max(0, Math.min(1, (pa[0] * ba[0] + pa[1] * ba[1] + pa[2] * ba[2]) / (ba[0] * ba[0] + ba[1] * ba[1] + ba[2] * ba[2])));
      return Math.hypot(pa[0] - ba[0] * h2, pa[1] - ba[1] * h2, pa[2] - ba[2] * h2) - r; };
    const smin = (a, b, k) => { const h2 = Math.max(k - Math.abs(a - b), 0) / k; return Math.min(a, b) - h2 * h2 * k * 0.25; };
    const smax = (a, b, k) => -smin(-a, -b, k);
    const sdf = (p) => {
      let d = ell(p, [0, 0.2, -0.05], [0.72, 0.84, 0.84]);                  // Schädel
      d = smin(d, ell(p, [0, -0.25, 0.12], [0.5, 0.62, 0.6]), 0.22);         // Gesicht
      d = smin(d, ell(p, [0, -0.58, 0.12], [0.42, 0.26, 0.48]), 0.16);       // Kiefer
      d = smin(d, ell(p, [0, -0.74, 0.36], [0.2, 0.14, 0.2]), 0.1);          // Kinn
      for (const sx of [1, -1]) {
        d = smin(d, ell(p, [0.38 * sx, -0.1, 0.46], [0.16, 0.1, 0.18]), 0.1);  // Wangenknochen
        d = smin(d, ell(p, [0.72 * sx, -0.02, -0.02], [0.06, 0.19, 0.11]), 0.05); // Ohren
        d = smin(d, ell(p, [0.24 * sx, 0.22, 0.68], [0.16, 0.035, 0.06]), 0.04); // Augenbrauen
        d = smax(d, -(L(p, [0.24 * sx, 0.08, 0.74]) - 0.12), 0.05);          // Augenhöhlen
        d = smin(d, L(p, [0.24 * sx, 0.075, 0.66]) - 0.085, 0.02);           // Augäpfel
        d = smin(d, L(p, [0.07 * sx, -0.27, 0.76]) - 0.055, 0.03);           // Nasenflügel
      }
      d = smin(d, ell(p, [0, 0.24, 0.6], [0.46, 0.07, 0.14]), 0.08);         // Stirnwulst
      d = smin(d, kapsel(p, [0, 0.08, 0.66], [0, -0.2, 0.84], 0.05), 0.06);  // Nasenrücken
      d = smin(d, L(p, [0, -0.22, 0.83]) - 0.072, 0.04);                     // Nasenspitze
      d = smin(d, ell(p, [0, -0.42, 0.73], [0.17, 0.04, 0.06]), 0.03);       // Oberlippe
      d = smin(d, ell(p, [0, -0.5, 0.72], [0.15, 0.045, 0.06]), 0.03);       // Unterlippe
      d = smax(d, -ell(p, [0, -0.455, 0.79], [0.16, 0.008, 0.08]), 0.01);    // Mundspalt
      d = smin(d, ell(p, [0, -1.08, -0.06], [0.3, 0.52, 0.3]), 0.2);         // Hals
      d = smin(d, ell(p, [0, -1.66, -0.1], [1.05, 0.3, 0.45]), 0.3);         // Schultern
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
    const pts = [], mund = [], hell = [], nor = [], saat = [];
    const normale = (p) => { const e = 0.008, g = [0, 1, 2].map((i) => { const a = p.slice(), b = p.slice(); a[i] += e; b[i] -= e; return sdf(a) - sdf(b); });
      const l = Math.hypot(g[0], g[1], g[2]) || 1; return [g[0] / l, g[1] / l, g[2] / l]; };
    const add = (p, b) => {
      const y = p[1], z = p[2];
      const m = y > -0.92 && y < -0.455 ? Math.min(1, (-0.455 - y) / 0.08) * Math.max(0, Math.min(1, (z - 0.1) / 0.3)) : 0;
      pts.push(p[0], p[1], p[2]); mund.push(m); hell.push(b); saat.push(rand());
      const nn = b > 1.5 ? [0, 0, 1] : normale(p); nor.push(nn[0], nn[1], nn[2]);
    };
    // 1) Gesicht und Kopf: zufällige Richtungen vom Kopfinneren, vorne doppelt so dicht
    const kopfZiel = Math.round(anzahl * 0.72);
    let versuche = 0;
    while (mund.length < kopfZiel && versuche < anzahl * 6) {
      versuche++;
      const u = rand() * 2 - 1, w = rand() * Math.PI * 2, s2 = Math.sqrt(1 - u * u);
      const dir = [s2 * Math.cos(w), u, s2 * Math.sin(w)];
      if (dir[2] < 0 && rand() < 0.5) continue;
      const p = flaeche([0, -0.12, 0.08], dir);
      if (p && p[1] > -0.95) add(p, 1);
    }
    // 2) Hals und Schultern als Ringe (Hologramm-Linien)
    const ringe = 26, proRing = Math.round(anzahl * 0.22 / ringe);
    for (let i = 0; i < ringe; i++) {
      const y = -1.9 + (1.0 * i) / (ringe - 1);
      for (let j = 0; j < proRing; j++) {
        const w = (j / proRing) * Math.PI * 2;
        const p = flaeche([0, y, -0.08], [Math.sin(w), 0, Math.cos(w)]);
        if (p) add(p, 1);
      }
    }
    // 3) Pupillen, leuchten
    for (const sx of [0.24, -0.24]) for (let i = 0; i < 40; i++) {
      const u = rand() * Math.PI * 2, r = Math.sqrt(rand()) * 0.03;
      add([sx + Math.cos(u) * r, 0.075 + Math.sin(u) * r, 0.748], 2);
    }
    return { pos: new Float32Array(pts), mund: new Float32Array(mund), hell: new Float32Array(hell),
             nor: new Float32Array(nor), saat: new Float32Array(saat), n: mund.length };
  }

  function Welt(canvas) {
    const gl = canvas.getContext("webgl", { antialias: false, alpha: false, premultipliedAlpha: false, preserveDrawingBuffer: false });
    if (!gl) return null;
    const prog = (vs, fs) => {
      const mk = (t, s) => { const x = gl.createShader(t); gl.shaderSource(x, s); gl.compileShader(x);
        if (!gl.getShaderParameter(x, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(x)); return x; };
      const p = gl.createProgram(); gl.attachShader(p, mk(gl.VERTEX_SHADER, vs)); gl.attachShader(p, mk(gl.FRAGMENT_SHADER, fs));
      gl.linkProgram(p); if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p)); return p;
    };
    const pw = prog(VS_FLAECHE, FS_WELT), pk = prog(VS_KOPF, FS_KOPF), pt = prog(VS_TEIL, FS_TEIL);
    const puffer = (d) => { const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, d, gl.STATIC_DRAW); return b; };
    const quad = puffer(new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]));
    const U = (p, n) => gl.getUniformLocation(p, n);
    const q = () => QUAL[S.jvQualitaet] || QUAL.mittel;
    let kopf = null, kopfQ = null, bK = {};
    function kopfBauen() {
      if (kopfQ === S.jvQualitaet) return;
      kopfQ = S.jvQualitaet; kopf = kopfPunkte(q().punkte);
      bK = { aP: puffer(kopf.pos), aM: puffer(kopf.mund), aB: puffer(kopf.hell), aN: puffer(kopf.nor), aS: puffer(kopf.saat) };
    }
    let teilQ = null, bT = null, nT = 0;
    function teilchenBauen() {
      if (teilQ === S.jvQualitaet) return;
      teilQ = S.jvQualitaet; nT = q().teilchen;
      const d = new Float32Array(nT * 4);
      for (let i = 0; i < nT; i++) {
        d[i * 4] = 0.052 * (4 + Math.pow(Math.random(), 0.7) * 26);   // Startradius (in rs-Einheiten * 0.052)
        d[i * 4 + 1] = Math.random() * Math.PI * 2;
        d[i * 4 + 2] = 0.02 + Math.random() * 0.06;                    // Tempo
        d[i * 4 + 3] = Math.random();
      }
      bT = puffer(d);
    }
    const maus = { x: 0, y: 0 };
    window.addEventListener("mousemove", (e) => { maus.x = e.clientX / window.innerWidth - 0.5; maus.y = e.clientY / window.innerHeight - 0.5; });
    const blick = { yaw: 0, pitch: 0 };
    const farbe = [0.22, 0.88, 1.0];
    return {
      zeichnen(t, e, zielFarbe, zerfall) {
        const qq = q(), dpr = Math.min(window.devicePixelRatio || 1, 1.5);
        const w = Math.max(2, Math.round(canvas.clientWidth * dpr * qq.skala)), h = Math.max(2, Math.round(canvas.clientHeight * dpr * qq.skala));
        if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
        for (let i = 0; i < 3; i++) farbe[i] += (zielFarbe[i] - farbe[i]) * 0.06;
        gl.viewport(0, 0, w, h);
        const kopfModus = S.jvKoerper === "kopf";
        gl.disable(gl.BLEND);
        gl.useProgram(pw);
        gl.bindBuffer(gl.ARRAY_BUFFER, quad);
        const lp = gl.getAttribLocation(pw, "p"); gl.enableVertexAttribArray(lp); gl.vertexAttribPointer(lp, 2, gl.FLOAT, false, 0, 0);
        gl.uniform2f(U(pw, "uRes"), w, h); gl.uniform1f(U(pw, "uT"), t); gl.uniform1f(U(pw, "uE"), e);
        gl.uniform1f(U(pw, "uLoch"), kopfModus ? 0.0 : 1.0); gl.uniform1f(U(pw, "uOkt"), qq.okt);
        gl.uniform3fv(U(pw, "uCol"), farbe);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
        gl.disableVertexAttribArray(lp);
        gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
        if (!kopfModus) {
          teilchenBauen();
          gl.blendFunc(gl.ONE, gl.ONE);
          gl.useProgram(pt);
          const la = gl.getAttribLocation(pt, "aD"); gl.bindBuffer(gl.ARRAY_BUFFER, bT); gl.enableVertexAttribArray(la); gl.vertexAttribPointer(la, 4, gl.FLOAT, false, 0, 0);
          gl.uniform1f(U(pt, "uT"), t); gl.uniform1f(U(pt, "uE"), e); gl.uniform1f(U(pt, "uAsp"), w / h);
          gl.uniform1f(U(pt, "uRs"), 0.052); gl.uniform1f(U(pt, "uGr"), Math.max(1.2, h / 520)); gl.uniform3fv(U(pt, "uCol"), farbe);
          gl.drawArrays(gl.POINTS, 0, nT);
          gl.disableVertexAttribArray(la);
          gl.disable(gl.BLEND);
          return;
        }
        kopfBauen();
        blick.yaw += ((maus.x * 0.9 + Math.sin(t * 0.22) * 0.45) - blick.yaw) * 0.04;
        blick.pitch += ((maus.y * 0.35 - 0.05 + Math.sin(t * 0.31) * 0.04) - blick.pitch) * 0.04;
        gl.useProgram(pk);
        const ls = Object.entries({ aP: 3, aM: 1, aB: 1, aN: 3, aS: 1 }).map(([name, n]) => {
          const l = gl.getAttribLocation(pk, name); gl.bindBuffer(gl.ARRAY_BUFFER, bK[name]); gl.enableVertexAttribArray(l); gl.vertexAttribPointer(l, n, gl.FLOAT, false, 0, 0); return l; });
        gl.uniform1f(U(pk, "uT"), t); gl.uniform1f(U(pk, "uE"), e); gl.uniform1f(U(pk, "uYaw"), blick.yaw); gl.uniform1f(U(pk, "uPitch"), blick.pitch);
        gl.uniform1f(U(pk, "uAsp"), w / h); gl.uniform1f(U(pk, "uGr"), Math.max(1.4, h / 420) * (S.jvQualitaet === "hoch" ? 1 : 1.3));
        gl.uniform1f(U(pk, "uZ"), zerfall || 0);
        gl.uniform3fv(U(pk, "uCol"), farbe); gl.uniform2f(U(pk, "uRes"), w, h);
        gl.drawArrays(gl.POINTS, 0, kopf.n);
        ls.forEach((l) => gl.disableVertexAttribArray(l));
        gl.disable(gl.BLEND);
      },
    };
  }


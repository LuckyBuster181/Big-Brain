
/* ============================================================ Oberfläche 2.0 (26.09.2026)
   Entscheidungen von Sir: Seitenleiste links (nach Häufigkeit sortiert, einklappbar),
   Jarvis-Seite mit Vollbild zuerst (Schwarzes Loch + Galaxie ODER Hologramm-Kopf,
   umschaltbar), Arbeitsmodus mit Status-Kacheln und Inhalten je Tageszeit (Briefing
   immer dabei), Farbe nach Zustand, Mund/Leuchten spricht mit, Vault-Quellen kreisen
   als Karten. Im Vollbild hört Jarvis dauerhaft zu. Töne: Start, Zuhören, Weltraum.
   Qualität Niedrig/Mittel/Hoch je Gerät (Einstellungen > Darstellung). Name änderbar.
   Das 3D ist reines WebGL ohne fremde Bibliothek - läuft auch ohne Internet. */
(function oberflaeche2() {
  const LS = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* privat */ } },
  };
  const STD2 = { jvKoerper: "universum", jvQualitaet: "mittel", tonStart: true, tonZuhoeren: true, tonAmbiente: true, jvStart: "voll", jvScheibe: "gold", jvKopfStil: "weich" };
  Object.keys(STD2).forEach((k) => { if (S[k] === undefined) S[k] = STD2[k]; });

  /* ---------------------------------------------------------------- Kopfhöhe für Leiste/Vollbild */
  function kopfMessen() {
    const h = document.querySelector("header");
    if (h) document.documentElement.style.setProperty("--kopf-h", h.offsetHeight + "px");
  }
  kopfMessen();
  window.addEventListener("resize", kopfMessen);

  /* ---------------------------------------------------------------- Seitenleiste */
  const leiste = $("seitenleiste");
  const navEl = leiste.querySelector("nav");
  const knoepfe = [...navEl.querySelectorAll("button[data-page]")];
  const reihenfolge = knoepfe.map((b) => b.dataset.page);
  const zaehler = LS.get("hud.seitenZaehler", {});
  const summe = Object.values(zaehler).reduce((a, b) => a + b, 0);
  const haeufig = summe >= 10
    ? reihenfolge.filter((p) => (zaehler[p] || 0) > 0).sort((a, b) => (zaehler[b] || 0) - (zaehler[a] || 0)).slice(0, 5)
    : ["jarvis", "markt", "nacht", "alltag", "denkblock"];
  navEl.innerHTML = "";
  const gruppe = (t) => { const d = document.createElement("div"); d.className = "nav-gruppe"; d.textContent = t; navEl.appendChild(d); };
  gruppe("Häufig");
  haeufig.forEach((p) => { const b = knoepfe.find((x) => x.dataset.page === p); if (b) navEl.appendChild(b); });
  gruppe("Weitere");
  reihenfolge.filter((p) => !haeufig.includes(p)).forEach((p) => navEl.appendChild(knoepfe.find((x) => x.dataset.page === p)));
  knoepfe.forEach((b) => b.addEventListener("click", () => {
    zaehler[b.dataset.page] = (zaehler[b.dataset.page] || 0) + 1;
    LS.set("hud.seitenZaehler", zaehler);
  }));
  const zuStart = LS.get("hud.leisteZu", window.innerWidth < 1150);
  document.body.classList.toggle("leiste-zu", !!zuStart);
  function leisteSetzen(zu) {
    document.body.classList.toggle("leiste-zu", zu);
    LS.set("hud.leisteZu", zu);
    const box = document.getElementById("setLeisteZu"); if (box) box.checked = zu;
    setTimeout(() => window.dispatchEvent(new Event("resize")), 260);
  }
  $("leisteKnopf").addEventListener("click", () => leisteSetzen(!document.body.classList.contains("leiste-zu")));

  /* ---------------------------------------------------------------- Töne (WebAudio, keine Dateien) */
  let AC = null;
  function ac() {
    if (!AC) AC = new (window.AudioContext || window.webkitAudioContext)();
    if (AC.state === "suspended") AC.resume();
    return AC;
  }
  function ton(art) {
    if (art === "start" ? S.tonStart === false : S.tonZuhoeren === false) return;
    try {
      const c = ac(); if (c.state !== "running") return;
      const t = c.currentTime, o = c.createOscillator(), g = c.createGain();
      o.connect(g); g.connect(c.destination);
      if (art === "start") {
        o.type = "sine"; o.frequency.setValueAtTime(96, t); o.frequency.exponentialRampToValueAtTime(40, t + 1.8);
        g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.2, t + 0.1); g.gain.exponentialRampToValueAtTime(0.0001, t + 2.4);
        o.start(t); o.stop(t + 2.5);
        const o2 = c.createOscillator(), g2 = c.createGain();
        o2.type = "triangle"; o2.frequency.setValueAtTime(520, t + 0.15); o2.frequency.exponentialRampToValueAtTime(1040, t + 1.1);
        g2.gain.setValueAtTime(0.0001, t); g2.gain.exponentialRampToValueAtTime(0.025, t + 0.35); g2.gain.exponentialRampToValueAtTime(0.0001, t + 1.6);
        o2.connect(g2); g2.connect(c.destination); o2.start(t); o2.stop(t + 1.7);
      } else {
        const an = art !== "aus";
        o.type = "sine"; o.frequency.setValueAtTime(an ? 620 : 900, t); o.frequency.exponentialRampToValueAtTime(an ? 980 : 540, t + 0.12);
        g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.07, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.2);
        o.start(t); o.stop(t + 0.22);
      }
    } catch (e) { /* ohne Ton weiter */ }
  }
  let startTonGespielt = false;
  function startTon() { if (startTonGespielt) return; startTonGespielt = true; setTimeout(() => ton("start"), 60); }
  const bootKnopf = document.getElementById("bootStart");
  if (bootKnopf) bootKnopf.addEventListener("click", () => { try { ac(); } catch (e) {} startTon(); });
  document.addEventListener("pointerdown", () => { try { ac(); } catch (e) {} startTon(); if (JV.aktiv) ambientAn(); }, { once: true });

  const JV = { aktiv: false, modus: "voll", zustand: "", letzter: "", spricht: false, pegel: 0, fehlerBis: 0, amb: null,
               altWach: null, wachUeber: false, karten: [], welt: null };

  function ambientAn() {
    if (!S.tonAmbiente || JV.amb || !JV.aktiv) return;
    try {
      const c = ac(); if (c.state !== "running") return;
      const len = 2 * c.sampleRate, buf = c.createBuffer(1, len, c.sampleRate), d = buf.getChannelData(0);
      let letzt = 0;
      for (let i = 0; i < len; i++) { letzt = (letzt + 0.02 * (Math.random() * 2 - 1)) / 1.02; d[i] = letzt * 3.5; }
      const src = c.createBufferSource(); src.buffer = buf; src.loop = true;
      const lp = c.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 360;
      const lfo = c.createOscillator(); lfo.frequency.value = 0.06; const lg = c.createGain(); lg.gain.value = 140;
      lfo.connect(lg); lg.connect(lp.frequency);
      const osc = c.createOscillator(); osc.frequency.value = 46; const og = c.createGain(); og.gain.value = 0.25;
      const g = c.createGain(); g.gain.value = 0.0001;
      src.connect(lp); lp.connect(g); osc.connect(og); og.connect(g); g.connect(c.destination);
      src.start(); osc.start(); lfo.start();
      g.gain.exponentialRampToValueAtTime(0.045, c.currentTime + 2.5);
      JV.amb = { src, osc, lfo, g };
    } catch (e) { JV.amb = null; }
  }
  function ambientAus() {
    if (!JV.amb) return;
    const a = JV.amb; JV.amb = null;
    try { const c = ac(); a.g.gain.cancelScheduledValues(c.currentTime); a.g.gain.setTargetAtTime(0.0001, c.currentTime, 0.3); } catch (e) {}
    setTimeout(() => { try { a.src.stop(); a.osc.stop(); a.lfo.stop(); } catch (e) {} }, 1400);
  }

  /* ---------------------------------------------------------------- Name überall + Weckwort */
  function nameUeberall() {
    const n = String(S.assistent || "Jarvis").trim() || "Jarvis";
    const jb = navEl.querySelector('button[data-page="jarvis"]');
    if (jb) { jb.querySelector("span").textContent = n; jb.title = n; }
    $("jvName").textContent = n.toUpperCase();
    const esc2 = n.toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    try {
      WECKWORT = new RegExp("(?:^|\\s)(" + esc2 + "|jarvis|javis|jarwis|dschawis|tschawis|jervis|charvis)(?=$|[\\s,.:!?-])[\\s,.:!?-]*", "i");
    } catch (e) { /* alter Ausdruck bleibt */ }
    $("jvHinweis").textContent = `Ich höre zu – sagen Sie „${n} …“. Leertaste oder Mikro-Knopf: sofort zuhören · A = Arbeitsmodus`;
  }
  const namenAlt = namenAnwenden;
  namenAnwenden = function () { namenAlt(); nameUeberall(); };
  nameUeberall();

  /* ---------------------------------------------------------------- Zustände abgreifen */
  const FARBEN = { "": [0.22, 0.88, 1.0], hoert: [0.3, 1.0, 0.92], denkt: [1.0, 0.76, 0.28], spricht: [0.3, 1.0, 0.62], fehler: [1.0, 0.33, 0.42] };
  const STATUS = { "": "Bereit", hoert: "Ich höre", denkt: "Denke nach", spricht: "Spreche", fehler: "Fehler" };
  function aktuellerZustand() { return Date.now() < JV.fehlerBis ? "fehler" : (JV.spricht ? "spricht" : JV.zustand); }
  function farbeCss() { const f = FARBEN[aktuellerZustand()] || FARBEN[""]; return `rgb(${f.map((x) => Math.round(x * 255)).join(",")})`; }
  function statusZeigen() {
    const z = aktuellerZustand();
    $("jvStatus").textContent = STATUS[z] || "Bereit";
    $("jvVoll").style.setProperty("--jv-farbe", farbeCss());
    $("jvMikro").classList.toggle("an", z === "hoert");
  }
  const orbZustandAlt = orbZustand;
  orbZustand = function (z, text) {
    orbZustandAlt(z, text);
    if (text && /nicht|Nichts|Fehler|Mikrofon|kann keine/.test(text)) hinweisZeigen(text);
    if (z === "hoert" && JV.letzter !== "hoert") ton("an");
    if (JV.letzter === "hoert" && z !== "hoert") ton("aus");
    JV.letzter = z; JV.zustand = z;
    statusZeigen();
  };
  /* Mikrofon sauber übergeben (Fix 27.09.2026, "er hört mich nicht"): Chrome erlaubt nur EINE Spracherkennung
     gleichzeitig. Im Vollbild läuft das Weckwort-Hören dauerhaft - vor dem gezielten Zuhören muss es erst
     wirklich beendet sein, sonst bricht die neue Erkennung sofort ab. */
  const orbZuhoerenAlt = orbZuhoeren;
  orbZuhoeren = function () {
    const w = orb.wach;
    if (S.sttModus !== "lokal" && w && orb.laeuft) {
      let los = false;
      const weiter = () => { if (los) return; los = true; orb.laeuft = false; setTimeout(orbZuhoerenAlt, 150); };
      orb.pause = true; w.onend = weiter;
      try { w.abort(); } catch (e) { weiter(); }
      setTimeout(weiter, 900);   // falls "onend" ausbleibt
      return;
    }
    return orbZuhoerenAlt();
  };
  // Meldungen (z. B. "Mikrofon nicht erlaubt", "Nichts gehört") auch im Vollbild zeigen
  let hinweisUhr = null;
  function hinweisZeigen(text) {
    if (!text || !JV.aktiv) return;
    const el = $("jvHinweis"); el.textContent = text; el.classList.add("meldung");
    clearTimeout(hinweisUhr); hinweisUhr = setTimeout(() => { el.classList.remove("meldung"); nameUeberall(); }, 6000);
  }
  const orbFragenAlt = orbFragen;
  orbFragen = function (frage) {
    if (JV.aktiv && String(frage || "").trim()) ton("an");
    $("jvAntwort").textContent = "";
    return orbFragenAlt(frage);
  };
  const sprichtAlt = sprichtAnzeige;
  sprichtAnzeige = function (an) {
    sprichtAlt(an);
    JV.spricht = !!an;
    if (an) pegelVerbinden();
    if (JV.amb) { try { const c = ac(); JV.amb.g.gain.setTargetAtTime(an ? 0.012 : 0.045, c.currentTime, 0.4); } catch (e) {} }
    statusZeigen();
  };
  function pegelVerbinden() {
    try {
      if (typeof fishAudio === "undefined" || !fishAudio || fishAudio._jv) return;
      const c = ac(); if (c.state !== "running") return;
      const src = c.createMediaElementSource(fishAudio), an = c.createAnalyser();
      an.fftSize = 512; src.connect(an); an.connect(c.destination);
      fishAudio._jv = { an, puf: new Uint8Array(an.fftSize) };
    } catch (e) { /* dann geschätzter Pegel */ }
  }
  function pegelMessen(t) {
    let ziel = 0;
    try {
      if (typeof fishAudio !== "undefined" && fishAudio && fishAudio._jv && !fishAudio.paused) {
        const { an, puf } = fishAudio._jv;
        an.getByteTimeDomainData(puf);
        let s = 0; for (let i = 0; i < puf.length; i++) { const x = (puf[i] - 128) / 128; s += x * x; }
        ziel = Math.min(1, Math.sqrt(s / puf.length) * 4.5);
      } else if (JV.spricht) {
        ziel = 0.35 + 0.35 * Math.abs(Math.sin(t * 9.1)) * (0.6 + 0.4 * Math.sin(t * 2.3));
      } else if (aktuellerZustand() === "denkt") ziel = 0.18 + 0.08 * Math.sin(t * 3);
    } catch (e) { ziel = 0; }
    JV.pegel += (ziel - JV.pegel) * 0.25;
    return JV.pegel;
  }
  // Text aus der Sprach-Blase ins Vollbild spiegeln (die Blase selbst ist im Vollbild versteckt)
  const spiegel = (von, nach) => new MutationObserver(() => {
    $(nach).textContent = $(von).textContent;
    if (nach === "jvAntwort") {
      $(nach).scrollTop = $(nach).scrollHeight;
      if (/^Fehler:/.test($(von).textContent)) { JV.fehlerBis = Date.now() + 5000; statusZeigen(); }
    }
  }).observe($(von), { childList: true, characterData: true, subtree: true });
  spiegel("orbDu", "jvDu"); spiegel("orbAntwort", "jvAntwort");

  /* ---------------------------------------------------------------- Vault-Quellen als kreisende Karten */
  window.addEventListener("jarvis-quellen", (e) => {
    const liste = (e.detail || []).slice(0, 7);
    const box = $("jvKarten");
    JV.karten.forEach((k) => k.el.remove());
    JV.karten = liste.map((q, i) => {
      const el = document.createElement("div");
      el.className = "jv-karte";
      const name = String(q.file_path || q.titel || q.title || "Notiz").replace(/\.md$/, "").split("/").pop();
      const ordner = String(q.file_path || "").split("/").slice(-2, -1)[0] || "Vault";
      el.innerHTML = `<small>${esc(ordner)}</small>${esc(name)}`;
      box.appendChild(el);
      return { el, w: (i / Math.max(1, liste.length)) * Math.PI * 2, geb: performance.now() };
    });
  });
  function kartenBewegen(t, w, h) {
    const cx = w / 2, cy = h * 0.44, rx = Math.min(w * 0.36, 520), ry = Math.min(h * 0.2, 170);
    JV.karten = JV.karten.filter((k) => {
      const alter = (performance.now() - k.geb) / 1000;
      if (alter > 16) { k.el.remove(); return false; }
      const a = k.w + t * 0.28, tiefe = Math.sin(a);
      const x = cx + Math.cos(a) * rx, y = cy + tiefe * ry;
      const s = 0.78 + 0.28 * (tiefe + 1) / 2;
      const deck = Math.min(1, alter * 2) * Math.min(1, (16 - alter) / 2) * (0.45 + 0.55 * (tiefe + 1) / 2);
      k.el.style.transform = `translate(${x}px, ${y}px) translate(-50%,-50%) scale(${s.toFixed(3)})`;
      k.el.style.opacity = deck.toFixed(3);
      k.el.style.zIndex = tiefe > 0 ? 2 : 0;
      return true;
    });
  }

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
uniform vec2 uRes; uniform float uT, uE, uLoch, uOkt, uBunt; uniform vec3 uCol;
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
vec3 glutGold(float x){ vec3 heiss = mix(vec3(1.0), uCol, 0.35); vec3 gold = vec3(1.0, 0.72, 0.28); vec3 rand = vec3(0.85, 0.28, 0.08);
  return x < 0.5 ? mix(heiss, gold, x*2.0) : mix(gold, rand, (x-0.5)*2.0); }
vec3 glutBunt(float x){ vec3 weiss = mix(vec3(0.9, 1.0, 1.1), uCol, 0.25); vec3 tuerkis = uCol * 1.15; vec3 gold = vec3(1.0, 0.7, 0.26); vec3 rand = vec3(0.75, 0.22, 0.42);
  return x < 0.22 ? mix(weiss, tuerkis, x/0.22) : x < 0.6 ? mix(tuerkis, gold, (x-0.22)/0.38) : mix(gold, rand, (x-0.6)/0.4); }
vec3 glut(float x){ return mix(glutGold(x), glutBunt(x), uBunt); }
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
uniform float uT, uE, uYaw, uPitch, uAsp, uGr, uZ, uVor;
varying float vA; varying float vB; varying float vH; varying float vF; varying float vU;
vec3 dreh(vec3 p, float cy, float sy, float cp, float sp){ p = vec3(cy*p.x + sy*p.z, p.y, -sy*p.x + cy*p.z); return vec3(p.x, cp*p.y - sp*p.z, sp*p.y + cp*p.z); }
void main(){ float haar = step(2.5, aB); vec3 p = aP;
  float mm = aM * (1.0 - haar);
  p.y -= mm*uE*0.1; p.z -= mm*uE*0.02;
  p *= 1.0 + 0.008*sin(uT*1.6);
  p += haar * aM*aM * vec3(0.05*sin(uT*0.8 + aS*6.28 + aM*2.5), 0.01*sin(uT*1.1 + aS*4.0), 0.035*cos(uT*0.6 + aS*5.0 + aM*2.0));
  vec3 wob = vec3(sin(uT*0.7 + aS*40.0), sin(uT*0.9 + aS*57.0), cos(uT*0.8 + aS*33.0));
  float zerf = uZ * aS;
  p += wob * (0.006 + 0.03*uE*mm + 0.45*zerf) + vec3(0.0, zerf*0.9*fract(uT*0.03 + aS), 0.0);
  float cy = cos(uYaw), sy = sin(uYaw), cp = cos(uPitch), sp = sin(uPitch);
  p = dreh(p, cy, sy, cp, sp); vec3 nn = normalize(dreh(aN, cy, sy, cp, sp));
  float z = 3.6 - p.z; vec2 s = p.xy * 1.75 / z; s.y += 0.16;
  gl_Position = vec4(s.x/uAsp, s.y, 0.0, 1.0);
  float licht = max(dot(nn, normalize(vec3(-0.5, 0.45, 0.74))), 0.0);
  float rand = pow(1.0 - abs(nn.z), 3.0);
  float vor = smoothstep(0.6, 0.86, aP.z) * step(-0.8, aP.y) * (1.0 - haar);
  vH = aP.y; vF = rand; vU = aM;
  float basis = haar > 0.5 ? 0.75 + 0.6*licht + 0.25*rand : 0.32 + 0.85*licht + 0.45*rand;
  vA = (basis + 0.75*vor*uVor) * (0.5 + 0.5*smoothstep(-0.9, 0.9, p.z)) * (1.0 - 0.55*zerf); vB = aB;
  gl_PointSize = uGr * (0.6 + 0.6*vA) * (haar > 0.5 ? 1.05 : 1.0) * (1.0 + zerf*0.8);
}`;

  /* Atom: leuchtender Kern, drei Elektronenbahnen, Elektronen mit Schweif, feine Wolke (Wunsch Sir, 27.09.2026) */
  const VS_ATOM = `attribute vec3 aP; attribute vec2 aT;
uniform float uT, uE, uW, uYaw, uPitch, uAsp, uGr;
varying float vA; varying float vTyp;
vec3 dreh(vec3 p, float cy, float sy, float cp, float sp){ p = vec3(cy*p.x + sy*p.z, p.y, -sy*p.x + cy*p.z); return vec3(p.x, cp*p.y - sp*p.z, sp*p.y + cp*p.z); }
vec3 bahn(float k, float w){
  float kipp = 1.2566; float r = k*1.0472 + 0.35;
  vec3 p = vec3(cos(w), sin(w)*cos(kipp), sin(w)*sin(kipp)) * 1.08;
  return vec3(cos(r)*p.x - sin(r)*p.y, sin(r)*p.x + cos(r)*p.y, p.z);
}
void main(){
  float typ = aT.x, z0 = aT.y; vec3 p; float a; float gr;
  if (typ < 0.5) {            // Kern
    float puls = 1.0 + 0.07*sin(uT*2.2 + z0*6.28) + uE*0.35;
    p = aP * puls; float r = length(aP) / 0.24;
    a = 0.45 + 1.1*(1.0 - r) + 0.25*sin(uT*3.0 + z0*40.0); gr = 1.5 + 2.5*step(0.93, z0)*(1.0 - r);
  } else if (typ < 1.5) {     // Bahn
    p = bahn(aP.x, aP.y + uT*0.04) * (1.0 + 0.004*sin(uT*2.0 + z0*50.0));
    a = 0.38 + 0.12*sin(uT*1.5 + aP.y*6.0); gr = 1.25;
  } else if (typ < 2.5) {     // Elektron mit Schweif
    p = bahn(aP.x, uW + aP.y - aP.z);
    float f = exp(-aP.z*5.0); a = 0.3 + 1.6*f; gr = 1.2 + 3.4*f;
  } else {                    // Wolke
    p = aP + 0.05*vec3(sin(uT*0.3 + z0*20.0), cos(uT*0.25 + z0*17.0), sin(uT*0.2 + z0*13.0));
    a = 0.1 + 0.06*sin(uT + z0*30.0); gr = 0.8;
  }
  float cy = cos(uYaw), sy = sin(uYaw), cp = cos(uPitch), sp = sin(uPitch);
  p = dreh(p, cy, sy, cp, sp);
  float z = 3.4 - p.z; vec2 s = p.xy * 1.9 / z; s.y += 0.06;
  gl_Position = vec4(s.x/uAsp, s.y, 0.0, 1.0);
  vA = a * (0.6 + 0.4*smoothstep(-1.2, 1.2, p.z)); vTyp = typ;
  gl_PointSize = uGr * gr * (3.4 / z);
}`;
  const FS_ATOM = `precision highp float; uniform vec3 uCol; uniform float uE; varying float vA; varying float vTyp;
void main(){ vec2 c = gl_PointCoord - 0.5; float d = length(c); if (d > 0.5) discard;
  float a = smoothstep(0.5, 0.0, d);
  vec3 col = vTyp < 0.5 ? mix(vec3(1.0, 0.78, 0.4), vec3(1.0, 0.97, 0.88), clamp(vA - 0.4, 0.0, 1.0))
           : vTyp < 1.5 ? mix(uCol, vec3(0.55, 0.6, 1.0), 0.3)
           : vTyp < 2.5 ? mix(vec3(0.95, 1.0, 1.0), uCol, 0.35)
           : mix(uCol, vec3(0.75, 0.55, 1.0), 0.5);
  gl_FragColor = vec4(col * vA * a * 1.4, a); }`;
  function atomPunkte(anzahl) {
    const pos = [], typ = [];
    const add = (x, y, z, t) => { pos.push(x, y, z); typ.push(t, Math.random()); };
    const nKern = Math.round(anzahl * 0.22), nBahn = Math.round(anzahl * 0.1), nWolke = Math.round(anzahl * 0.06);
    for (let i = 0; i < nKern; i++) {           // Kern: dichte Kugel, Rand betont
      const u = Math.random() * 2 - 1, w = Math.random() * Math.PI * 2, s2 = Math.sqrt(1 - u * u), r = 0.24 * Math.pow(Math.random(), 0.35);
      add(s2 * Math.cos(w) * r, u * r, s2 * Math.sin(w) * r, 0);
    }
    for (let k = 0; k < 3; k++) for (let i = 0; i < nBahn; i++) add(k, (i / nBahn) * Math.PI * 2, 0, 1);
    for (let k = 0; k < 3; k++) for (const phase of [0, Math.PI]) for (let j = 0; j < 70; j++) add(k, phase + k * 0.9, j * 0.012, 2);
    for (let i = 0; i < nWolke; i++) {
      const u = Math.random() * 2 - 1, w = Math.random() * Math.PI * 2, s2 = Math.sqrt(1 - u * u), r = 0.35 + 1.1 * Math.random();
      add(s2 * Math.cos(w) * r, u * r, s2 * Math.sin(w) * r, 3);
    }
    return { pos: new Float32Array(pos), typ: new Float32Array(typ), n: typ.length / 2 };
  }
  const FS_KOPF = `precision highp float; uniform vec3 uCol; uniform float uT, uE; uniform vec2 uRes; varying float vA; varying float vB; varying float vH; varying float vF; varying float vU;
void main(){ vec2 c = gl_PointCoord - 0.5; float d = length(c); if (d > 0.5) discard;
  float a = smoothstep(0.5, 0.0, d);
  vec3 col;
  if (vB > 2.5) {             // Haare: Champagner-Gold am Ansatz, Perlmutt in der Mitte, Türkis-Flieder an den Spitzen, Lichtpuls läuft herunter
    col = mix(vec3(1.0, 0.72, 0.36), vec3(1.0, 0.86, 0.58), smoothstep(0.0, 0.6, vU));
    col = mix(col, vec3(1.0, 0.94, 0.8), smoothstep(0.6, 0.9, vU));
    col = mix(col, vec3(0.7, 0.88, 1.0), smoothstep(0.88, 1.0, vU) * 0.6);
    float puls = exp(-pow(fract(vU*1.4 - uT*0.16 + vF*0.3) - 0.5, 2.0)*70.0);
    col *= 0.75 + 0.9*puls;
  } else if (vB > 1.5) {      // Augen: sanftes Türkis
    col = vec3(0.5, 0.9, 1.0) * 1.15;
  } else if (vB > 1.2) {      // Lippen: Rosé
    col = vec3(1.0, 0.58, 0.7);
  } else {                    // Haut: Perlmutt mit türkisem Rand
    col = mix(vec3(0.95, 0.96, 1.0), vec3(0.45, 0.85, 1.0), clamp(vF, 0.0, 1.0)*0.7) * 1.2;
    col = mix(col, vec3(1.0, 0.8, 0.85), 0.12);
  }
  col = mix(col, uCol, vB > 2.5 ? 0.04 : 0.12);
  float scan = 1.0 + 0.35*exp(-pow(mod(gl_FragCoord.y - uT*110.0, uRes.y*1.3) - uRes.y*0.5, 2.0)/900.0);
  col *= vA * 1.75 * (1.0 + uE*0.5) * scan;
  gl_FragColor = vec4(col * a * (0.55 + 0.45*vA), a); }`;

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
    const kopfZiel = ziel(mitLinien ? 0.16 : 0.3);
    let versuche = 0;
    while (mund.length < kopfZiel && versuche < anzahl * 8) {
      versuche++;
      const u = rand() * 2 - 1, w = rand() * Math.PI * 2, s2 = Math.sqrt(1 - u * u);
      const dir = [s2 * Math.cos(w), u, s2 * Math.sin(w)];
      if (dir[2] < 0.1 && rand() < 0.8) continue;
      const p = flaeche([0, -0.12, 0.08], dir);
      if (p && p[1] > -0.95) add(p, 1);
    }
    for (let i = 0; i < Math.round(anzahl * 0.1); i++) {   // Gesicht vorne zusätzlich füllen (weich und hell)
      const x = (rand() * 2 - 1) * 0.46, y = 0.45 - rand() * 1.25;
      if ((x / 0.46) ** 2 + ((y + 0.17) / 0.66) ** 2 > 1) continue;
      const p = vorn(x, y); if (p && p[2] > 0.25) add(p, 1);
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
    const proStrang = 64, straenge = Math.max(50, Math.round(anzahl * 0.5 / proStrang));
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
      const phase = rand() * 6.28, welle = 0.06 + rand() * 0.05;
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
        if (pos[2] > 0.0 && pos[1] < 0.42 && pos[1] > -1.0 && Math.abs(pos[0]) < 0.53) pos[0] = Math.sign(pos[0] || seite) * (0.54 + rand() * 0.07);
        const quer = Math.sin(u * 8 + phase) * welle * Math.min(1, u * 2.5);   // Wellen wie gelockte lange Haare
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
        if (p[2] > 0 && p[1] < 0.42 && p[1] > -1.0 && Math.abs(p[0]) < 0.53) p[0] = seite * (0.54 + rand() * 0.06);
        p = [p[0] + (rand() - 0.5) * 0.012, p[1] + (rand() - 0.5) * 0.012, p[2] + (rand() - 0.5) * 0.012];
        add(p, 3, u * 0.8, [seite * 0.4, 0.2, 0.9]);
      }
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
    const pw = prog(VS_FLAECHE, FS_WELT), pk = prog(VS_KOPF, FS_KOPF), pt = prog(VS_TEIL, FS_TEIL), pa = prog(VS_ATOM, FS_ATOM);
    const puffer = (d) => { const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, d, gl.STATIC_DRAW); return b; };
    const quad = puffer(new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]));
    const U = (p, n) => gl.getUniformLocation(p, n);
    const q = () => QUAL[S.jvQualitaet] || QUAL.mittel;
    let kopf = null, kopfQ = null, bK = {};
    function kopfBauen() {
      const k = S.jvQualitaet + "|" + S.jvKopfStil;
      if (kopfQ === k) return;
      kopfQ = k; kopf = kopfPunkte(q().punkte, S.jvKopfStil === "scan");
      bK = { aP: puffer(kopf.pos), aM: puffer(kopf.mund), aB: puffer(kopf.hell), aN: puffer(kopf.nor), aS: puffer(kopf.saat) };
    }
    let atom = null, atomQ = null, bA = {}, atomW = 0, atomZuletzt = 0;
    function atomBauen() {
      if (atomQ === S.jvQualitaet) return;
      atomQ = S.jvQualitaet; atom = atomPunkte(q().punkte);
      bA = { aP: puffer(atom.pos), aT: puffer(atom.typ) };
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
        const kopfModus = S.jvKoerper === "kopf", atomModus = S.jvKoerper === "atom";
        gl.disable(gl.BLEND);
        gl.useProgram(pw);
        gl.bindBuffer(gl.ARRAY_BUFFER, quad);
        const lp = gl.getAttribLocation(pw, "p"); gl.enableVertexAttribArray(lp); gl.vertexAttribPointer(lp, 2, gl.FLOAT, false, 0, 0);
        gl.uniform2f(U(pw, "uRes"), w, h); gl.uniform1f(U(pw, "uT"), t); gl.uniform1f(U(pw, "uE"), e);
        gl.uniform1f(U(pw, "uLoch"), (kopfModus || atomModus) ? 0.0 : 1.0); gl.uniform1f(U(pw, "uOkt"), qq.okt);
        gl.uniform3fv(U(pw, "uCol"), farbe); gl.uniform1f(U(pw, "uBunt"), S.jvScheibe === "jarvis" ? 1.0 : 0.0);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
        gl.disableVertexAttribArray(lp);
        gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
        if (atomModus) {
          atomBauen();
          const dt = atomZuletzt ? Math.min(0.1, t - atomZuletzt) : 0; atomZuletzt = t;
          atomW += dt * (0.9 + e * 2.2);                                   // Elektronen werden beim Sprechen schneller
          blick.yaw += ((maus.x * 0.7 + t * 0.12) - blick.yaw) * 0.03;
          blick.pitch += ((maus.y * 0.3 + 0.25 * Math.sin(t * 0.17)) - blick.pitch) * 0.03;
          gl.blendFunc(gl.ONE, gl.ONE);
          gl.useProgram(pa);
          const ls = Object.entries({ aP: 3, aT: 2 }).map(([name, n]) => {
            const l = gl.getAttribLocation(pa, name); gl.bindBuffer(gl.ARRAY_BUFFER, bA[name]); gl.enableVertexAttribArray(l); gl.vertexAttribPointer(l, n, gl.FLOAT, false, 0, 0); return l; });
          gl.uniform1f(U(pa, "uT"), t); gl.uniform1f(U(pa, "uE"), e); gl.uniform1f(U(pa, "uW"), atomW);
          gl.uniform1f(U(pa, "uYaw"), blick.yaw); gl.uniform1f(U(pa, "uPitch"), blick.pitch);
          gl.uniform1f(U(pa, "uAsp"), w / h); gl.uniform1f(U(pa, "uGr"), Math.max(1.4, h / 380));
          gl.uniform3fv(U(pa, "uCol"), farbe);
          gl.drawArrays(gl.POINTS, 0, atom.n);
          ls.forEach((l) => gl.disableVertexAttribArray(l));
          gl.disable(gl.BLEND);
          return;
        }
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
        gl.uniform1f(U(pk, "uT"), t); gl.uniform1f(U(pk, "uE"), e); gl.uniform1f(U(pk, "uYaw"), blick.yaw); gl.uniform1f(U(pk, "uVor"), S.jvKopfStil === "scan" ? 1.0 : 0.0); gl.uniform1f(U(pk, "uPitch"), blick.pitch);
        gl.uniform1f(U(pk, "uAsp"), w / h); gl.uniform1f(U(pk, "uGr"), Math.max(1.4, h / 420) * (S.jvQualitaet === "hoch" ? 1 : 1.3));
        gl.uniform1f(U(pk, "uZ"), zerfall || 0);
        gl.uniform3fv(U(pk, "uCol"), farbe); gl.uniform2f(U(pk, "uRes"), w, h);
        gl.drawArrays(gl.POINTS, 0, kopf.n);
        ls.forEach((l) => gl.disableVertexAttribArray(l));
        gl.disable(gl.BLEND);
      },
    };
  }

  /* ---------------------------------------------------------------- Vollbild steuern */
  let rafId = null;
  function schleife(ms) {
    rafId = null;
    if (!JV.aktiv) return;
    const t = ms / 1000, e = pegelMessen(t);
    // Partikel-Schwarm: nach 25 s ohne Gespräch zerfließt der Kopf, bei Aktivität formt er sich neu
    if (aktuellerZustand() || JV.spricht) JV.aktivZuletzt = ms;
    const zerfZiel = (ms - (JV.aktivZuletzt || 0)) > 25000 ? 1 : 0;
    JV.zerfall = (JV.zerfall || 0) + (zerfZiel - (JV.zerfall || 0)) * (zerfZiel ? 0.004 : 0.06);
    if (JV.welt && !document.hidden) {
      try { JV.welt.zeichnen(t, e, FARBEN[aktuellerZustand()] || FARBEN[""], JV.zerfall); }
      catch (err) { JV.welt = null; $("jvKeinGL").hidden = false; console.warn("3D aus:", err); }
    }
    kartenBewegen(t, $("jvVoll").clientWidth, $("jvVoll").clientHeight);
    rafId = requestAnimationFrame(schleife);
  }
  const KOERPER = ["universum", "kopf", "atom"], KOERPER_NAME = { universum: "Universum", kopf: "Kopf", atom: "Atom" };
  function koerperText() { $("jvKoerper").textContent = KOERPER_NAME[S.jvKoerper] || "Universum"; }
  function tonText() { $("jvTon").textContent = S.tonAmbiente ? "Ton an" : "Ton aus"; }
  function vollStart() {
    if (JV.aktiv) return;
    JV.aktiv = true;
    document.body.classList.add("jv-voll-an");
    kopfMessen();
    if (!JV.welt) {
      try { JV.welt = Welt($("jvCanvas")); } catch (err) { JV.welt = null; console.warn("3D:", err); }
      $("jvKeinGL").hidden = !!JV.welt;
    }
    koerperText(); tonText(); statusZeigen();
    // Immer zuhören, solange das Vollbild offen ist (Entscheidung Sir)
    if (!JV.wachUeber) { JV.altWach = !!S.wach; JV.wachUeber = true; }
    S.wach = true; orb.pause = false;
    try { wachStarten(); } catch (e) { /* Browser ohne Spracherkennung */ }
    ambientAn();
    if (!rafId) rafId = requestAnimationFrame(schleife);
  }
  function vollStop() {
    if (!JV.aktiv) return;
    JV.aktiv = false;
    document.body.classList.remove("jv-voll-an");
    if (JV.wachUeber) {
      S.wach = JV.altWach; JV.wachUeber = false;
      if (!S.wach) { try { wachStoppen(); $("orbBox").classList.remove("wach"); } catch (e) {} }
    }
    ambientAus();
    JV.karten.forEach((k) => k.el.remove()); JV.karten = [];
  }
  const speichernAlt = einstellungenSpeichernLokal;
  einstellungenSpeichernLokal = function () {
    if (!JV.wachUeber) return speichernAlt();
    const w = S.wach; S.wach = JV.altWach; speichernAlt(); S.wach = w;
  };
  $("setWach").addEventListener("change", () => { if (JV.wachUeber) { JV.altWach = $("setWach").checked; S.wach = true; wachStarten(); } });

  function jarvisSeiteAktiv() { return $("page-jarvis").classList.contains("active"); }
  function anzeigen() { (jarvisSeiteAktiv() && JV.modus === "voll") ? vollStart() : vollStop(); if (jarvisSeiteAktiv() && JV.modus === "arbeit") statusLaden(); }
  let warAktiv = jarvisSeiteAktiv();
  new MutationObserver(() => {
    const jetzt = jarvisSeiteAktiv();
    if (jetzt && !warAktiv) JV.modus = S.jvStart === "voll" ? "voll" : "arbeit";  // Standard: Vollbild zuerst (Sir)
    warAktiv = jetzt;
    anzeigen();
  }).observe($("page-jarvis"), { attributes: true, attributeFilter: ["class"] });
  function modus(m) { JV.modus = m; anzeigen(); }
  // Klassische Ansicht (alte Jarvis-Seite, Wunsch Sir: als Option behalten): ohne Status/Jetzt-Karten
  function klassischAnwenden() { document.body.classList.toggle("jv-klassisch", S.jvStart === "klassisch"); }
  klassischAnwenden();
  (function vollChip() {
    const c = document.createElement("span");
    c.className = "chip"; c.id = "jvZuVoll2"; c.title = "Vollbild (Taste V)"; c.textContent = "Vollbild";
    const ziel = $("modusKlassisch").parentNode; ziel.insertBefore(c, ziel.firstChild);
    c.addEventListener("click", () => modus("voll"));
  })();
  ["mousemove", "keydown", "pointerdown"].forEach((ev) => document.addEventListener(ev, () => { if (JV.aktiv) JV.aktivZuletzt = performance.now(); }, { passive: true }));
  $("jvArbeit").addEventListener("click", () => modus("arbeit"));
  $("jvZuVoll").addEventListener("click", () => modus("voll"));
  $("jvKoerper").addEventListener("click", () => { S.jvKoerper = KOERPER[(KOERPER.indexOf(S.jvKoerper) + 1) % KOERPER.length]; einstellungenSpeichernLokal(); koerperText(); darstellungFuellen(); });
  $("jvTon").addEventListener("click", () => { S.tonAmbiente = !S.tonAmbiente; einstellungenSpeichernLokal(); tonText(); S.tonAmbiente ? ambientAn() : ambientAus(); darstellungFuellen(); });
  $("jvMikro").addEventListener("click", () => {
    try { ac(); } catch (e) {}
    if (orb.zustand === "hoert" && orb.einmal) { orb.einmal.stop(); return; }
    orbZuhoeren();
  });
  $("jvText").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && $("jvText").value.trim()) { const t = $("jvText").value.trim(); $("jvText").value = ""; orbFragen(t); }
    e.stopPropagation();
  });
  document.addEventListener("keydown", (e) => {
    if (!JV.aktiv || e.target.closest("input, textarea, select")) return;
    if (e.code === "Space") { e.preventDefault(); $("jvMikro").click(); }
    else if (e.key === "a" || e.key === "A") modus("arbeit");
  });
  document.addEventListener("keydown", (e) => {
    if (!jarvisSeiteAktiv() || JV.aktiv || e.target.closest("input, textarea, select")) return;
    if (e.key === "v" || e.key === "V") modus("voll");
  });

  /* ---------------------------------------------------------------- Arbeitsmodus: Status + Jetzt */
  const euro = (usd) => (usd === null || usd === undefined) ? "–" : Number(usd).toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " $";
  async function statusLaden() {
    const ok = (p) => fetch(p).then((r) => r.ok ? r.json() : null).catch(() => null);
    const [health, kosten, nacht, vor] = await Promise.all([ok("/api/health"), ok("/api/kosten"), ok("/api/nachtauftraege"), ok("/api/vorschlaege")]);
    const setz = (id, text, klasse) => { $(id).textContent = text; if (klasse !== undefined) $(id).parentNode.className = "jv-kachel " + klasse; };
    if (health) { setz("kMini", "online", "gut"); $("kMiniText").textContent = (health.chunk_count || 0).toLocaleString("de-DE") + " Abschnitte"; }
    else { setz("kMini", "nicht erreichbar", "schlecht"); $("kMiniText").textContent = "JARVIS STARTEN.bat"; }
    if (kosten) {
      setz("kHeute", euro(kosten.heute_usd), kosten.heute_usd > 0.33 ? "warn" : "gut");
      $("kMonat").textContent = "Monat " + euro(kosten.ausgegeben_usd) + " von " + euro(kosten.rahmen_usd);
    }
    if (nacht) {
      $("kNacht").textContent = nacht.laeuft ? "läuft gerade" : (nacht.naechster_lauf || "täglich 03:00");
      const geplant = (nacht.auftraege || []).filter((a) => a.status === "offen").length;
      $("kNachtText").textContent = geplant ? geplant + " Auftrag/Aufträge geplant" : "keine Aufträge geplant";
      const rf = (nacht.auftraege || []).filter((a) => a.status === "rueckfrage" || a.status === "vorschlag").length;
      const v = Array.isArray(vor) ? vor.length : ((vor && vor.vorschlaege) || []).length;
      setz("kOffen", String(rf + v), rf + v ? "warn" : "gut");
      $("kOffenText").textContent = `${v} Vorschläge · ${rf} Nachtfragen`;
      JV.nacht = nacht;
    }
    jetztZeigen();
  }
  function tageszeit() { const h = new Date().getHours(); return h >= 5 && h < 11 ? "morgen" : h >= 11 && h < 17 ? "tag" : h >= 17 && h < 23 ? "abend" : "nacht"; }
  const TITEL = { morgen: "Guten Morgen", tag: "Tagsüber", abend: "Guten Abend", nacht: "Späte Stunde" };
  function chip(text, aktion) { return `<span class="chip" data-jetzt="${esc(aktion)}">${esc(text)}</span>`; }
  function jetztZeigen() {
    const z = tageszeit(), n = S.nutzer || "Sir";
    $("jvJetztTitel").textContent = TITEL[z] + ", " + n;
    $("jvJetztZeit").textContent = new Date().toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
    const bl = [];
    bl.push(`<div class="jetzt-block"><h3>Briefing</h3><div class="hint" style="margin-bottom:6px">${z === "abend" || z === "nacht" ? "Tagesbilanz und Plan für morgen" : "Stand und Plan für heute"} (ca. 1–3 Cent, gilt 10 Minuten).</div>${chip("Briefing holen", "briefing")}</div>`);
    const fertig = ((JV.nacht && JV.nacht.auftraege) || []).filter((a) => a.status === "fertig").slice(0, 3);
    if (z === "morgen") {
      bl.push(`<div class="jetzt-block"><h3>Aus der Nacht</h3>${fertig.length ? fertig.map((a) => `<div class="hint">• ${esc(a.titel)} – Opus: ${esc((a.ergebnis || {}).urteil || "?")}</div>`).join("") : '<div class="hint">Noch keine Ergebnisse.</div>'}<div style="margin-top:6px">${chip("Seite Nacht", "seite:nacht")}</div></div>`);
      bl.push(`<div class="jetzt-block"><h3>Frage des Tages</h3><div class="hint" id="jvTf">lädt …</div></div>`);
    } else if (z === "tag") {
      bl.push(`<div class="jetzt-block"><h3>Schnell</h3><div class="jetzt-chips">${chip("Wie steht Gold?", "frage:Wie steht Gold?")}${chip("Wie läuft mein Trading?", "frage:Wie läuft mein Trading?")}${chip("Markt", "seite:markt")}${chip("Denkblock", "seite:denkblock")}${chip("Was steht heute Nacht an?", "frage:Was steht heute Nacht an?")}</div></div>`);
    } else {
      bl.push(`<div class="jetzt-block"><h3>Für heute Nacht</h3><div class="row" style="gap:6px"><input type="text" id="jvNachtText" placeholder="z. B. Recherchiere …" style="flex:1;min-width:0">${chip("Eintragen", "nacht")}</div><div class="hint" id="jvNachtMeldung" style="margin-top:4px"></div></div>`);
      bl.push(`<div class="jetzt-block"><h3>Tag abschließen</h3><div class="jetzt-chips">${chip("Tagesnotiz aus den Chats", "tagesnotiz")}${chip("Frage des Tages", "seite:nacht")}</div></div>`);
    }
    $("jvJetztInhalt").innerHTML = bl.join("");
    if (z === "morgen") fetch("/api/tagesfrage").then((r) => r.json()).then((d) => { const el = document.getElementById("jvTf"); if (el) el.innerHTML = esc(d.frage) + (d.antwort ? "<br><i>Beantwortet.</i>" : "<br>Antwort im Chat: „Antwort: …“"); }).catch(() => {});
  }
  $("jvJetztInhalt").addEventListener("click", async (ev) => {
    const c = ev.target.closest("[data-jetzt]"); if (!c) return;
    const a = c.dataset.jetzt;
    if (a === "briefing") briefingHolen();
    else if (a === "tagesnotiz") { const b = document.getElementById("tagesnotizBtn"); if (b) b.click(); }
    else if (a.startsWith("seite:")) { const b = document.querySelector(`nav button[data-page="${a.slice(6)}"]`); if (b) b.click(); }
    else if (a.startsWith("frage:")) { $("chatInput").value = a.slice(6); ask(); }
    else if (a === "nacht") {
      const t = ($("jvNachtText").value || "").trim(); if (t.length < 5) return;
      try { const r = await jsonSenden("/api/nachtauftraege", "POST", { text: t });
        $("jvNachtText").value = ""; $("jvNachtMeldung").textContent = r.status === "rueckfrage" ? "Rückfragen dazu stehen auf der Seite Nacht." : `Nr. ${r.id} läuft heute Nacht.`; statusLaden(); }
      catch (e) { $("jvNachtMeldung").innerHTML = '<span class="err">' + esc(e.message) + "</span>"; }
    }
  });
  setInterval(() => { if (jarvisSeiteAktiv() && JV.modus === "arbeit" && !document.hidden) statusLaden(); }, 60000);

  /* ---------------------------------------------------------------- Einstellungen: Kategorien */
  const seite = $("page-settings"), altGrid = seite.querySelector(".grid");
  const karten = [...altGrid.children];
  const karteNach = (titel) => karten.find((k) => { const h2 = k.querySelector("h2"); return h2 && h2.textContent.trim().startsWith(titel); });
  const darst = document.createElement("div");
  darst.className = "card";
  darst.innerHTML = `<h2>Jarvis im Vollbild</h2>
    <div class="set-zeile"><span>Körper<small>Was im Vollbild zu sehen ist</small></span><select id="setKoerper"><option value="universum">Schwarzes Loch + Galaxie</option><option value="kopf">Hologramm-Kopf</option><option value="atom">Atom</option></select></div>
    <div class="set-zeile"><span>Farbe Schwarzes Loch<small>Gold wie im Film oder Jarvis-Türkis</small></span><select id="setScheibe"><option value="gold">Gold / Weiß</option><option value="jarvis">Jarvis-Farben (Türkis)</option></select></div>
    <div class="set-zeile"><span>Kopf-Stil<small>Weich oder wie ein 3D-Scan mit Linien</small></span><select id="setKopfStil"><option value="weich">Weich</option><option value="scan">Scan-Linien</option></select></div>
    <div class="set-zeile"><span>Jarvis-Seite öffnet mit<small>Vollbild, Arbeitsmodus oder die alte Ansicht</small></span><select id="setJvStart"><option value="voll">Vollbild</option><option value="arbeit">Arbeitsmodus</option><option value="klassisch">Klassisch (alte Seite)</option></select></div>
    <div class="set-zeile"><span>Qualität auf diesem Gerät<small>Niedrig schont Laptop und Akku</small></span><select id="setQualitaet"><option value="niedrig">Niedrig</option><option value="mittel">Mittel</option><option value="hoch">Hoch</option></select></div>
    <label class="row"><input type="checkbox" id="setTonStart" style="width:auto"> <span>Start-Ton beim Öffnen</span></label>
    <label class="row"><input type="checkbox" id="setTonZuhoeren" style="width:auto"> <span>Ton, wenn Jarvis anfängt/aufhört zuzuhören</span></label>
    <label class="row"><input type="checkbox" id="setTonAmbiente" style="width:auto"> <span>Weltraum-Ambiente im Vollbild (sehr leise)</span></label>
    <label class="row"><input type="checkbox" id="setLeisteZu" style="width:auto"> <span>Seitenleiste eingeklappt (nur Symbole)</span></label>
    <div class="hint" style="margin-top:8px">Im Vollbild hört Jarvis dauerhaft auf seinen Namen (Chrome/Edge, die Erkennung läuft über den Dienst des Browsers). Leertaste = sofort zuhören, A = Arbeitsmodus, V = zurück ins Vollbild.</div>`;
  const allgemeinZusatz = document.createElement("div");
  // Ladebildschirm und Effekte gehören zur Darstellung
  ["setBoot", "setEffekte"].forEach((id) => { const l = $(id) && $(id).closest("label"); if (l) darst.appendChild(l); });
  // Kurs-Intervall gehört zum Markt
  const kurseKarte = karteNach("Kurse");
  const intervall = $("setKursIntervall");
  if (kurseKarte && intervall) {
    const lab = intervall.previousElementSibling;
    if (lab && lab.tagName === "LABEL") kurseKarte.appendChild(lab);
    kurseKarte.appendChild(intervall);
  }
  const KAT = [
    ["allgemein", "Allgemein", ["Namen und Start"]],
    ["darstellung", "Darstellung", ["Farben", darst]],
    ["stimme", "Stimme & Sprache", ["Sprache"]],
    ["jarvis", "Jarvis & Vault", ["Jarvis und Ordner"]],
    ["markt", "Markt & Wetter", ["Kurse", "Wetter"]],
    ["kosten", "Kosten & Zugänge", ["Kosten", "API-Schl"]],
  ];
  const layout = document.createElement("div");
  layout.className = "set-layout";
  const menue = document.createElement("div"); menue.className = "set-menue";
  const inhalt = document.createElement("div"); inhalt.className = "set-inhalt";
  menue.innerHTML = '<input type="search" id="setSuche" placeholder="Einstellung suchen …">';
  const benutzt = new Set();
  KAT.forEach(([id, titel, teile]) => {
    const panel = document.createElement("div"); panel.className = "set-panel"; panel.dataset.kat = id;
    panel.innerHTML = `<h1>${esc(titel)}</h1>`;
    teile.forEach((t) => { const k = typeof t === "string" ? karteNach(t) : t; if (k) { panel.appendChild(k); benutzt.add(k); } });
    inhalt.appendChild(panel);
    const b = document.createElement("button"); b.type = "button"; b.dataset.kat = id;
    b.innerHTML = `${esc(titel)}<small>${panel.querySelectorAll(".card").length}</small>`;
    menue.appendChild(b);
  });
  const rest = karten.filter((k) => !benutzt.has(k));
  if (rest.length) {
    const panel = document.createElement("div"); panel.className = "set-panel"; panel.dataset.kat = "weitere";
    panel.innerHTML = "<h1>Weitere</h1>"; rest.forEach((k) => panel.appendChild(k)); inhalt.appendChild(panel);
    const b = document.createElement("button"); b.type = "button"; b.dataset.kat = "weitere"; b.textContent = "Weitere"; menue.appendChild(b);
  }
  layout.appendChild(menue); layout.appendChild(inhalt);
  altGrid.replaceWith(layout);
  function katZeigen(id) {
    layout.classList.remove("set-suche"); $("setSuche").value = "";
    inhalt.querySelectorAll(".set-panel").forEach((p) => p.classList.toggle("active", p.dataset.kat === id));
    menue.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.kat === id));
    inhalt.querySelectorAll(".card").forEach((c) => c.classList.remove("versteckt"));
    LS.set("hud.setKat", id);
  }
  menue.addEventListener("click", (e) => { const b = e.target.closest("button[data-kat]"); if (b) katZeigen(b.dataset.kat); });
  $("setSuche").addEventListener("input", () => {
    const qtext = $("setSuche").value.trim().toLowerCase();
    if (!qtext) { katZeigen(LS.get("hud.setKat", "allgemein")); return; }
    layout.classList.add("set-suche");
    menue.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
    inhalt.querySelectorAll(".card").forEach((c) => c.classList.toggle("versteckt", !c.textContent.toLowerCase().includes(qtext)));
  });
  katZeigen(LS.get("hud.setKat", "allgemein"));

  function darstellungFuellen() {
    $("setJvStart").value = S.jvStart || "voll";
    $("setKoerper").value = S.jvKoerper; $("setQualitaet").value = S.jvQualitaet; $("setScheibe").value = S.jvScheibe || "gold"; $("setKopfStil").value = S.jvKopfStil || "weich";
    $("setTonStart").checked = S.tonStart !== false; $("setTonZuhoeren").checked = S.tonZuhoeren !== false;
    $("setTonAmbiente").checked = !!S.tonAmbiente; $("setLeisteZu").checked = document.body.classList.contains("leiste-zu");
  }
  darstellungFuellen();
  $("setJvStart").addEventListener("change", () => { S.jvStart = $("setJvStart").value; einstellungenSpeichernLokal(); klassischAnwenden(); });
  $("setKoerper").addEventListener("change", () => { S.jvKoerper = $("setKoerper").value; einstellungenSpeichernLokal(); koerperText(); });
  $("setScheibe").addEventListener("change", () => { S.jvScheibe = $("setScheibe").value; einstellungenSpeichernLokal(); });
  $("setKopfStil").addEventListener("change", () => { S.jvKopfStil = $("setKopfStil").value; einstellungenSpeichernLokal(); });
  $("setQualitaet").addEventListener("change", () => { S.jvQualitaet = $("setQualitaet").value; einstellungenSpeichernLokal(); });
  [["setTonStart", "tonStart"], ["setTonZuhoeren", "tonZuhoeren"], ["setTonAmbiente", "tonAmbiente"]].forEach(([id, k]) =>
    $(id).addEventListener("change", () => { S[k] = $(id).checked; einstellungenSpeichernLokal(); tonText(); if (k === "tonAmbiente") (S[k] ? ambientAn() : ambientAus()); }));
  $("setLeisteZu").addEventListener("change", () => leisteSetzen($("setLeisteZu").checked));

  /* ---------------------------------------------------------------- Stile zum Umschalten (Wunsch Sir: mehrere)
     Zukunft und Retro bleiben, neu: Weltraum-Glas und Minimal-Modern. */
  const STILE = [["zukunft", "Zukunft", "Hologramm, Türkis und Gold"], ["glas", "Glas", "Weltraum-Glas: Universum, mattes Glas, viel Luft"],
                 ["minimal", "Minimal", "Minimal-Modern: ruhig, schlicht, schnell"], ["retro", "Retro", "Retro 80/90: Bernstein-Monitor"]];
  $("stilWahl").innerHTML = STILE.map(([k, t]) => `<button data-stil="${k}">${t}</button>`).join("");
  $("setStil").innerHTML = STILE.map(([k, t, b]) => `<option value="${k}">${t} – ${b}</option>`).join("");
  const stilAlt = stilAnwenden;
  stilAnwenden = function () {
    stilAlt();
    const st = S.stil || "zukunft";
    document.body.classList.toggle("glas", st === "glas");
    document.body.classList.toggle("minimal", st === "minimal");
    document.querySelectorAll("#stilWahl button").forEach((b) => b.classList.toggle("active", b.dataset.stil === st));
    const a = document.getElementById("setStil"); if (a) a.value = st;
    kopfMessen();
  };
  stilAnwenden();

  anzeigen();
  window.JV = JV;  // zum Nachsehen in der Browser-Konsole
})();

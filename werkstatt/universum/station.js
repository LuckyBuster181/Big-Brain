"use strict";
/* station.js (04.10.2026, Claude): Auron Station im Universum.
   - eigener kleiner GLB-Leser (kein GLTFLoader noetig): iss.glb, planet_a.glb, planet_b.glb aus modelle/
   - Station kreist um die Erde, 8 Module im Ring (je eine Station von Auron), leuchten, wenn sie laufen
   - zwei erfundene Planeten (Nova, Rubra) mit selbst erzeugter Oberflaeche
   Wird von universum_3d.html aufgerufen (aufbauen, leeren, schritt, bild, ziele, fahre, status).
   05.10.2026: Termin-Lichter - die Termine der naechsten 7 Tage (aus /api/kalender) kreisen als kleine Lichter um das
   Kalender-Modul. Heute rot, morgen silbern, spaeter matt, Feiertage golden; je spaeter, desto weiter aussen und langsamer.
   Klick auf ein Licht fliegt hin, Knopf "Kalender oeffnen" oeffnet in Auron die Seite Heute.
   Nicht massstabsgetreu: Die Station ist stark vergroessert, sonst waere sie unsichtbar. */
const AuronStation = (function () {
  const MODULE = [
    { id: "minipc", name: "Mini-PC", seite: "geraete" },
    { id: "hauptpc", name: "Haupt-PC", seite: "geraete" },
    { id: "testpc", name: "Test-PC", seite: "geraete" },
    { id: "nachtarbeit", name: "Nachtarbeit", seite: "nacht" },
    { id: "vault", name: "Gedächtnis", seite: "vault" },
    { id: "kalender", name: "Kalender", seite: "alltag" },
    { id: "trading", name: "Markt", seite: "markt" },
    { id: "kosten", name: "Kosten", seite: "settings" },
    { id: "agenten", name: "Agenten", seite: "agenten" }   // 10.10.2026: Agenten-Station
  ];
  const SP = new URLSearchParams(location.search);
  const L = parseFloat(SP.get("stationsgroesse")) || 7.0e5;   // Meter, laengste Seite der Station (echt ca. 109 m)
  const BAHN = 7.7e6;                                          // Meter vom Erdmittelpunkt
  const UMLAUF = 420;                                          // Sekunden fuer eine Runde (bewusst langsam)
  const RING = 0.74;                                           // Ringradius in Stationslaengen
  const EIN = [1.9, 0.30, 0.36], AUS = [0.16, 0.17, 0.20];

  let wurzel = null, st = null, module = [], planeten = [], erde = null, sonne = null, winkel = 0.6, offen = null;
  let nahFlag = false, loch = null, ringSaturn = null, lochZeit = 0;
  let termine = [], terminPhase = 0, terminUhr = null;
  const TERMIN_TAGE = 7, TERMIN_MAX = 8;
  let an = {}; { const q = SP.get("an"); const alle = q === null; for (const m of MODULE) an[m.id] = alle || q.split(",").includes(m.id); }
  const sichtbarBis = 3e9;
  const meldung = txt => { try { console.log("[station] " + txt); } catch (e) {} };

  // ---------------- GLB-Leser ----------------
  async function glbLaden(url, opt) {
    opt = Object.assign({ metall: 0.35, selbst: 0.28 }, opt || {});
    const r = await fetch(url); if (!r.ok) throw new Error(url + ": HTTP " + r.status);
    const buf = await r.arrayBuffer(), dv = new DataView(buf);
    if (dv.getUint32(0, true) !== 0x46546C67) throw new Error(url + ": keine GLB-Datei");
    let off = 12, json = null, bin = null;
    while (off + 8 <= buf.byteLength) {
      const len = dv.getUint32(off, true), typ = dv.getUint32(off + 4, true); off += 8;
      if (typ === 0x4E4F534A) json = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, off, len)));
      else if (typ === 0x004E4942) bin = buf.slice(off, off + len);
      off += len;
    }
    if (!json || !bin) throw new Error(url + ": GLB unvollstaendig");
    const KOMP = { 5120: Int8Array, 5121: Uint8Array, 5122: Int16Array, 5123: Uint16Array, 5125: Uint32Array, 5126: Float32Array };
    const ANZ = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4 };
    function lies(ai) {
      const a = json.accessors[ai], v = json.bufferViews[a.bufferView], C = KOMP[a.componentType], n = ANZ[a.type], b = C.BYTES_PER_ELEMENT;
      const start = (v.byteOffset || 0) + (a.byteOffset || 0), stride = v.byteStride || n * b;
      if (stride === n * b) return new C(bin.slice(start, start + a.count * n * b));
      const out = new C(a.count * n);
      for (let i = 0; i < a.count; i++) { const e = new C(bin.slice(start + i * stride, start + i * stride + n * b)); for (let k = 0; k < n; k++) out[i * n + k] = e[k]; }
      return out;
    }
    const texCache = {};
    async function textur(ti) {
      if (texCache[ti]) return texCache[ti];
      const tx = json.textures[ti], im = json.images[tx.source], v = json.bufferViews[im.bufferView];
      const blob = new Blob([bin.slice(v.byteOffset || 0, (v.byteOffset || 0) + v.byteLength)], { type: im.mimeType || "image/png" });
      const bmp = await createImageBitmap(blob);
      const t = new THREE.Texture(bmp); t.flipY = false; t.wrapS = t.wrapT = THREE.RepeatWrapping;
      t.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy()); t.needsUpdate = true;
      return (texCache[ti] = t);
    }
    async function material(mi) {
      const m = (json.materials || [])[mi] || {}, p = m.pbrMetallicRoughness || {}, o = {};
      o.roughness = p.roughnessFactor !== undefined ? p.roughnessFactor : 1;
      o.metalness = (p.metallicFactor !== undefined ? p.metallicFactor : 1) * opt.metall;
      if (p.baseColorFactor) o.color = new THREE.Color(p.baseColorFactor[0], p.baseColorFactor[1], p.baseColorFactor[2]);
      if (p.baseColorTexture) o.map = await textur(p.baseColorTexture.index);
      if (p.metallicRoughnessTexture) { const t = await textur(p.metallicRoughnessTexture.index); o.metalnessMap = t; o.roughnessMap = t; }
      if (m.normalTexture) o.normalMap = await textur(m.normalTexture.index);
      if (m.alphaMode === "MASK") o.alphaTest = m.alphaCutoff !== undefined ? m.alphaCutoff : 0.5;
      if (m.alphaMode === "BLEND") { o.transparent = true; }
      if (m.doubleSided) o.side = THREE.DoubleSide;
      const mat = new THREE.MeshStandardMaterial(o);
      if (o.map && opt.selbst) { mat.emissive = new THREE.Color(opt.selbst, opt.selbst, opt.selbst); mat.emissiveMap = o.map; }
      return mat;
    }
    const matCache = {};
    const meshen = [];
    for (let mi = 0; mi < (json.meshes || []).length; mi++) {
      const liste = [];
      for (const pr of json.meshes[mi].primitives) {
        if (pr.mode !== undefined && pr.mode !== 4) continue;
        const geo = new THREE.BufferGeometry(), at = pr.attributes;
        geo.setAttribute("position", new THREE.BufferAttribute(lies(at.POSITION), 3));
        if (at.NORMAL !== undefined) geo.setAttribute("normal", new THREE.BufferAttribute(lies(at.NORMAL), 3)); else geo.computeVertexNormals();
        if (at.TEXCOORD_0 !== undefined) geo.setAttribute("uv", new THREE.BufferAttribute(lies(at.TEXCOORD_0), 2));
        if (pr.indices !== undefined) { let ix = lies(pr.indices); if (ix instanceof Uint8Array) ix = Uint16Array.from(ix); geo.setIndex(new THREE.BufferAttribute(ix, 1)); }
        geo.computeBoundingSphere();
        const key = pr.material === undefined ? -1 : pr.material;
        if (!matCache[key]) matCache[key] = key < 0 ? new THREE.MeshStandardMaterial({ color: 0xcccccc, roughness: 0.8 }) : await material(key);
        const mesh = new THREE.Mesh(geo, matCache[key]); mesh.frustumCulled = false; liste.push(mesh);
      }
      meshen.push(liste);
    }
    function knoten(ni) {
      const n = json.nodes[ni], g = new THREE.Group(); g.name = n.name || "";
      if (n.matrix) new THREE.Matrix4().fromArray(n.matrix).decompose(g.position, g.quaternion, g.scale);
      else { if (n.translation) g.position.fromArray(n.translation); if (n.rotation) g.quaternion.fromArray(n.rotation); if (n.scale) g.scale.fromArray(n.scale); }
      if (n.mesh !== undefined) for (const m of meshen[n.mesh]) g.add(m.clone());
      for (const c of n.children || []) g.add(knoten(c));
      return g;
    }
    const szenenKnoten = json.scenes[json.scene || 0].nodes, innen = new THREE.Group();
    for (const ni of szenenKnoten) innen.add(knoten(ni));
    // in die Mitte und auf Kantenlaenge 1 bringen
    innen.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(innen, true), mitte = box.getCenter(new THREE.Vector3()), gr = box.getSize(new THREE.Vector3());
    const m = Math.max(gr.x, gr.y, gr.z) || 1;
    innen.position.sub(mitte);
    const huelle = new THREE.Group(); huelle.add(innen); huelle.scale.setScalar(1 / m);
    huelle.userData.groesse = gr.clone().divideScalar(m);
    return huelle;
  }

  // ---------------- Oberflaeche fuer die erfundenen Planeten ----------------
  function hash(x, y, z, s) { let h = Math.imul(x | 0, 374761393) ^ Math.imul(y | 0, 668265263) ^ Math.imul(z | 0, 2147483647) ^ Math.imul(s | 0, 1274126177);
    h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967296; }
  function wert(x, y, z, s) { const xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z), fx = x - xi, fy = y - yi, fz = z - zi;
    const u = fx * fx * (3 - 2 * fx), v = fy * fy * (3 - 2 * fy), w = fz * fz * (3 - 2 * fz), h = (a, b, c) => hash(xi + a, yi + b, zi + c, s);
    const l = (a, b, t) => a + (b - a) * t;
    return l(l(l(h(0, 0, 0), h(1, 0, 0), u), l(h(0, 1, 0), h(1, 1, 0), u), v), l(l(h(0, 0, 1), h(1, 0, 1), u), l(h(0, 1, 1), h(1, 1, 1), u), v), w); }
  function fbm(x, y, z, s, n) { let sum = 0, a = 0.5, f = 1, norm = 0; for (let i = 0; i < n; i++) { sum += a * wert(x * f, y * f, z * f, s + i); norm += a; a *= 0.5; f *= 2.03; } return sum / norm; }
  const mischen = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
  function planetTextur(art, samen, breite) {
    const B = breite || 768, H = B / 2, c = document.createElement("canvas"); c.width = B; c.height = H;
    const ctx = c.getContext("2d"), img = ctx.createImageData(B, H), d = img.data;
    for (let j = 0; j < H; j++) {
      const lat = (0.5 - (j + 0.5) / H) * Math.PI, cl = Math.cos(lat), sl = Math.sin(lat);
      for (let i = 0; i < B; i++) {
        const lon = ((i + 0.5) / B) * Math.PI * 2, x = Math.cos(lon) * cl, z = Math.sin(lon) * cl, y = sl;
        let col;
        if (art === "ozean") {
          const h = fbm(x * 2.2 + 5, y * 2.2, z * 2.2, samen, 6);
          const wolke = fbm(x * 3.0 + 9, y * 5.5, z * 3.0, samen + 40, 5);
          if (h < 0.50) col = mischen([0.02, 0.10, 0.27], [0.06, 0.36, 0.52], Math.min(1, Math.max(0, (h - 0.32) / 0.18)));
          else if (h < 0.53) col = [0.78, 0.72, 0.52];
          else col = mischen([0.18, 0.40, 0.17], [0.46, 0.38, 0.27], Math.min(1, Math.max(0, (h - 0.53) / 0.14)));
          const pol = Math.max(0, (Math.abs(y) - 0.84) / 0.12); col = mischen(col, [0.94, 0.96, 1], Math.min(1, pol * 1.3));
          const wk = Math.min(1, Math.max(0, (wolke - 0.52) / 0.18)); col = mischen(col, [1, 1, 1], wk * 0.85);
        } else {
          const h = fbm(x * 2.6, y * 2.6 + 3, z * 2.6, samen, 6), band = fbm(x * 1.2, y * 9.0, z * 1.2, samen + 20, 4);
          col = mischen([0.45, 0.17, 0.08], [0.82, 0.48, 0.25], Math.min(1, Math.max(0, h * 1.5 - 0.15)));
          col = mischen(col, [0.30, 0.10, 0.07], Math.min(1, Math.max(0, (band - 0.5) * 1.4)) * 0.5);
          const krater = Math.max(0, (fbm(x * 7, y * 7, z * 7, samen + 70, 3) - 0.62) * 4); col = mischen(col, [0.2, 0.08, 0.06], Math.min(1, krater) * 0.5);
          const pol = Math.max(0, (Math.abs(y) - 0.88) / 0.08); col = mischen(col, [0.92, 0.9, 0.88], Math.min(1, pol * 1.4));
        }
        const k = (j * B + i) * 4; d[k] = Math.round(col[0] * 255); d[k + 1] = Math.round(col[1] * 255); d[k + 2] = Math.round(col[2] * 255); d[k + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    const t = new THREE.CanvasTexture(c); t.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy()); return t;
  }
  const ATM_VS = `
#include <common>
#include <logdepthbuf_pars_vertex>
varying vec3 vN; varying vec3 vV;
void main(){ vec4 mv = modelViewMatrix * vec4(position, 1.0); vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz);
  gl_Position = projectionMatrix * mv;
  #include <logdepthbuf_vertex>
}`;
  const ATM_FS = `
#include <logdepthbuf_pars_fragment>
varying vec3 vN; varying vec3 vV; uniform vec3 uFarbe; uniform float uA;
void main(){ float f = pow(1.0 - max(dot(normalize(vN), normalize(vV)), 0.0), 2.6);
  gl_FragColor = vec4(uFarbe, f * uA);
  #include <logdepthbuf_fragment>
}`;

  // ---------------- Station aufbauen ----------------
  function ersatzHuelle() { // falls iss.glb nicht laedt: einfache Station
    const g = new THREE.Group(), grau = new THREE.MeshStandardMaterial({ color: 0xb5bac4, metalness: 0.4, roughness: 0.5, emissive: 0x202328 });
    const kern = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.5, 16), grau); kern.rotation.z = Math.PI / 2; g.add(kern);
    for (const s of [-1, 1]) for (const z of [-1, 1]) { const p = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.004, 0.14), new THREE.MeshStandardMaterial({ color: 0x1c3358, emissive: 0x0a1428, metalness: 0.3, roughness: 0.4 })); p.position.set(s * 0.32, 0, z * 0.1); g.add(p); }
    return g;
  }
  function podBauen(m, i) {
    const phi = i / MODULE.length * Math.PI * 2 + 0.2, lokal = new THREE.Vector3(Math.cos(phi) * RING, 0, Math.sin(phi) * RING);
    const tang = new THREE.Vector3(-Math.sin(phi), 0, Math.cos(phi)), q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), tang);
    const gruppe = new THREE.Group(); gruppe.position.copy(lokal); gruppe.quaternion.copy(q);
    const metall = new THREE.MeshStandardMaterial({ color: 0xaeb4be, metalness: 0.45, roughness: 0.42, emissive: 0x191c22 });
    const koerper = new THREE.Mesh(new THREE.CylinderGeometry(0.034, 0.034, 0.12, 24), metall);
    const bandMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(...AUS), toneMapped: false });
    const band = new THREE.Mesh(new THREE.CylinderGeometry(0.0355, 0.0355, 0.03, 24), bandMat);
    const kappe = new THREE.SphereGeometry(0.034, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2);
    const k1 = new THREE.Mesh(kappe, metall); k1.position.y = 0.06; const k2 = new THREE.Mesh(kappe, metall); k2.position.y = -0.06; k2.rotation.x = Math.PI;
    gruppe.add(koerper, band, k1, k2);
    for (const e of [-1, 1]) { const ring = new THREE.Mesh(new THREE.TorusGeometry(0.0365, 0.0032, 8, 28), metall); ring.rotation.x = Math.PI / 2; ring.position.y = e * 0.042; gruppe.add(ring); }
    return { gruppe, lokal, band: bandMat };
  }
  function stationBauen() {
    wurzel = new THREE.Group(); wurzel.visible = false; szene.add(wurzel);
    const rad = new THREE.Group(); wurzel.add(rad);
    // Ring und Streben
    const pts = []; for (let i = 0; i <= 96; i++) { const a = i / 96 * Math.PI * 2; pts.push(new THREE.Vector3(Math.cos(a) * RING, 0, Math.sin(a) * RING)); }
    wurzel.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: 0x8c929c, transparent: true, opacity: 0.55 })));
    st = { id: "station", name: "Auron Station", art: "station", pos: [0, 0, 0], r: L / 2, rSicht: L * 0.45, masse: 0, daten: { name: "Auron Station" }, marke: null, tourId: null };
    module = MODULE.map((m, i) => {
      const p = podBauen(m, i); wurzel.add(p.gruppe);
      const sl = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0), p.lokal.clone().multiplyScalar(0.93)]), new THREE.LineBasicMaterial({ color: 0x6f757e, transparent: true, opacity: 0.7 }));
      wurzel.add(sl);
      return { id: m.id, seite: m.seite, name: m.name, art: "modul", pos: [0, 0, 0], r: L * 0.06, rSicht: L * 0.06, masse: 0, daten: { name: m.name }, marke: null, lokal: p.lokal, band: p.band, tourId: m.id, gruppe: p.gruppe };
    });
    modelleLaden();
    statusAnwenden();
    termineLaden();
    clearInterval(terminUhr); terminUhr = setInterval(termineLaden, 10 * 60 * 1000);
  }
  async function modelleLaden() {
    try {
      const iss = await glbLaden("modelle/iss.glb");
      if (!wurzel) return; wurzel.add(iss); meldung("ISS geladen");
    } catch (e) { meldung("ISS-Modell fehlt (" + e.message + "), Ersatzstation"); if (wurzel) wurzel.add(ersatzHuelle()); }
  }
  function statusAnwenden() {
    for (const m of module) { const f = an[m.id] ? EIN : AUS; m.band.color.setRGB(f[0], f[1], f[2]); m.laeuft = !!an[m.id]; }
  }

  // ---------------- Termin-Lichter (05.10.2026) ----------------
  const WT = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];
  function tagIso(d) { return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); }
  function termineEntfernen() {
    for (const t of termine) { if (t.mesh && t.mesh.parent) t.mesh.parent.remove(t.mesh); if (t.mesh) t.mesh.geometry.dispose(); if (t.marke) t.marke.remove(); }
    termine = [];
  }
  function termineBauen(liste) {
    termineEntfernen();
    const kal = module.find(m => m.id === "kalender");
    if (!wurzel || !kal) return;
    const heute = new Date(); heute.setHours(0, 0, 0, 0);
    const kommend = (liste || []).map(t => {
      const s = String(t.start || ""), d = new Date(s.slice(0, 10) + "T00:00:00");
      const tage = Math.round((d - heute) / 864e5);
      return { t, s, tage };
    }).filter(x => x.tage >= 0 && x.tage < TERMIN_TAGE && !(x.tage === 0 && x.s.length > 10 && new Date(x.s) < new Date(Date.now() - 36e5)))
      .sort((a, b) => a.s.localeCompare(b.s)).slice(0, TERMIN_MAX);
    kommend.forEach((x, i) => {
      const fei = x.t.kategorie === "feiertag";
      const f = fei ? [1.7, 1.2, 0.4] : x.tage === 0 ? EIN : x.tage === 1 ? [1.5, 1.55, 1.65] : [0.55, 0.6, 0.72];
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(x.tage === 0 ? 0.0095 : 0.0075, 14, 10),
        new THREE.MeshBasicMaterial({ color: new THREE.Color(f[0], f[1], f[2]), toneMapped: false }));
      wurzel.add(mesh);
      const tag = x.tage === 0 ? "Heute" : x.tage === 1 ? "Morgen" : WT[new Date(x.s.slice(0, 10) + "T12:00:00").getDay()];
      const uhr = x.s.length > 10 ? " " + x.s.slice(11, 16) : "";
      const name = tag + uhr + " · " + (fei ? "Feiertag: " : "") + String(x.t.titel || "Termin");
      termine.push({ id: "termin-" + i, name, art: "termin", pos: [0, 0, 0], r: L * 0.008, rSicht: L * 0.035, masse: 0,
        daten: { name }, marke: null, mesh, seite: "alltag", laeuft: true, tage: x.tage,
        basis: i / Math.max(1, kommend.length) * Math.PI * 2, radius: 0.12 + 0.012 * Math.min(x.tage, 6), lokal: new THREE.Vector3(), kal });
    });
    if (typeof listeBauen === "function") { try { listeBauen(); } catch (e) {} }
    meldung(termine.length + " Termin-Lichter am Kalender");
  }
  async function termineLaden() {
    try {
      const r = await fetch("/api/kalender", { cache: "no-store" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const d = await r.json();
      termineBauen(d.termine || []);
    } catch (e) { meldung("Termine nicht geladen (" + e.message + ")"); }
  }
  function terminLage(t) {   // Kreisbahn um das Kalender-Modul, leicht geneigt, aeussere langsamer
    const a = t.basis + terminPhase / (1 + t.tage * 0.35);
    t.lokal.copy(t.kal.lokal).add(new THREE.Vector3(Math.cos(a) * t.radius, Math.sin(a) * t.radius * 0.42, Math.sin(a) * t.radius * 0.9));
    t.mesh.position.copy(t.lokal);
  }

  // ---------------- erfundene Planeten ----------------
  const PLANETEN = [
    { name: "Nova", datei: "planet_a.glb", art: "ozean", r: 9.2e6, ae: 2.35, psi: 1.1, samen: 3, atm: [0.35, 0.62, 1.0], drehen: 0.02 },
    { name: "Rubra", datei: "planet_b.glb", art: "wueste", r: 6.1e6, ae: 3.45, psi: 3.4, samen: 17, atm: [1.0, 0.55, 0.32], drehen: 0.014 }
  ];
  function planetenBauen() {
    const mars = koerperObjekte.find(k => k.daten.name === "Mars"), ref = erde;
    if (!sonne || !ref) return;
    const rel = sub(ref.pos, sonne.pos), vel = ref.daten.v ? sub(ref.daten.v, sonne.daten.v || [0, 0, 0]) : [0, 0, 1];
    const u = new THREE.Vector3(...rel).normalize(), n = new THREE.Vector3().crossVectors(u, new THREE.Vector3(...vel)).normalize(), w = new THREE.Vector3().crossVectors(n, u);
    for (const p of PLANETEN) {
      const dir = u.clone().multiplyScalar(Math.cos(p.psi)).add(w.clone().multiplyScalar(Math.sin(p.psi))).multiplyScalar(p.ae * AE);
      const o = { name: p.name, art: "fiktiv", pos: [sonne.pos[0] + dir.x, sonne.pos[1] + dir.y, sonne.pos[2] + dir.z], r: p.r, rSicht: p.r, masse: 0, daten: { name: p.name }, marke: null, p, huelle: null, atm: null };
      const gruppe = new THREE.Group(); gruppe.visible = false; szene.add(gruppe); o.gruppe = gruppe;
      const tex = planetTextur(p.art, p.samen);
      glbLaden("modelle/" + p.datei, { metall: 0, selbst: 0 }).then(h => {
        h.traverse(ob => { if (ob.isMesh) { ob.material = new THREE.MeshStandardMaterial({ map: tex, roughness: p.art === "ozean" ? 0.55 : 0.9, metalness: 0, emissive: new THREE.Color(0.02, 0.02, 0.02), emissiveMap: tex }); ob.material.emissive.setScalar(0.05); } });
        h.scale.multiplyScalar(2); gruppe.add(h); o.huelle = h; meldung("Planet " + p.name + " geladen");
      }).catch(e => { meldung("Planet " + p.name + ": " + e.message + " - Ersatzkugel");
        const k = new THREE.Mesh(KUGEL, new THREE.MeshStandardMaterial({ map: tex, roughness: 0.8 })); gruppe.add(k); o.huelle = k; });
      const atm = new THREE.Mesh(new THREE.SphereGeometry(1.05, 48, 24), new THREE.ShaderMaterial({ uniforms: { uFarbe: { value: new THREE.Color(...p.atm) }, uA: { value: 1.0 } },
        vertexShader: ATM_VS, fragmentShader: ATM_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
      atm.frustumCulled = false; gruppe.add(atm); o.atm = atm;
      planeten.push(o);
    }
  }

  function erdeVerschoenern() { // Erde bekommt dieselbe Art Oberflaeche wie Nova (Kontinente, Wolken, Polkappen)
    try {
      const m = erde.mesh.material, tex = planetTextur("ozean", 8, 1024);
      m.map = tex; m.color.setRGB(1, 1, 1); m.roughness = 0.6; m.emissive.setRGB(0.03, 0.03, 0.04);
      m.onBeforeCompile = () => {}; m.customProgramCacheKey = () => "erdetex"; m.needsUpdate = true;
    } catch (e) { meldung("Erde nicht verschoenert: " + e.message); }
  }

  // ---------------- Riesen-Schwarzes-Loch (TON 618) und Saturnringe ----------------
  const RS = 1.95e14;                       // Radius des Ereignishorizonts in Metern (66 Mrd. Sonnenmassen -> ca. 1300 AE)
  const LOCH_ABSTAND = 10.4e9 * 9.4607e15;  // ca. 10,4 Mrd. Lichtjahre (Laufzeitentfernung)
  const DISK_VS = `
#include <common>
#include <logdepthbuf_pars_vertex>
varying vec2 vP;
void main(){ vP = position.xy; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  #include <logdepthbuf_vertex>
}`;
  const DISK_FS = `
#include <logdepthbuf_pars_fragment>
varying vec2 vP; uniform float uZeit; uniform float uIn; uniform float uAus;
void main(){
  float r = length(vP); float t = clamp((r - uIn) / (uAus - uIn), 0.0, 1.0); float a = atan(vP.y, vP.x);
  float band = 0.62 + 0.38 * sin(a * 2.0 + log(r) * 11.0 - uZeit * 0.9);
  band *= 0.8 + 0.2 * sin(a * 7.0 - log(r) * 23.0 - uZeit * 1.7);
  float dop = 1.0 + 0.55 * sin(a + 0.6);
  float glut = pow(1.0 - t, 2.4);
  vec3 heiss = vec3(1.0, 0.93, 0.78), mittel = vec3(1.0, 0.52, 0.14), kuehl = vec3(0.55, 0.10, 0.04);
  vec3 c = mix(heiss, mittel, smoothstep(0.0, 0.35, t)); c = mix(c, kuehl, smoothstep(0.3, 1.0, t));
  float alpha = smoothstep(0.0, 0.04, t) * (1.0 - smoothstep(0.7, 1.0, t));
  gl_FragColor = vec4(c * (0.25 + 2.6 * glut) * band * dop, alpha * 0.95);
  #include <logdepthbuf_fragment>
}`;
  const HALO_FS = `
#include <logdepthbuf_pars_fragment>
varying vec2 vP;
void main(){ float r = length(vP); float g = exp(-pow((r - 1.07) / 0.045, 2.0)) * 2.4 + exp(-pow((r - 1.07) / 0.22, 2.0)) * 0.35;
  gl_FragColor = vec4(vec3(1.0, 0.78, 0.5) * g, clamp(g, 0.0, 1.0));
  #include <logdepthbuf_fragment>
}`;
  function lochBauen() {
    const dir = new THREE.Vector3(0.55, 0.30, -0.78).normalize();   // Richtung frei gewaehlt, Entfernung echt
    const gruppe = new THREE.Group(); gruppe.visible = false; szene.add(gruppe);
    gruppe.add(new THREE.Mesh(new THREE.SphereGeometry(1, 48, 24), new THREE.MeshBasicMaterial({ color: 0x000000 })));
    const neig = new THREE.Group(); neig.rotation.set(0.32, 0, 0.14); gruppe.add(neig);
    const mat = new THREE.ShaderMaterial({ uniforms: { uZeit: { value: 0 }, uIn: { value: 1.5 }, uAus: { value: 7.5 } },
      vertexShader: DISK_VS, fragmentShader: DISK_FS, transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending });
    const scheibe = new THREE.Mesh(new THREE.RingGeometry(1.5, 7.5, 192, 6), mat); scheibe.rotation.x = -Math.PI / 2; scheibe.frustumCulled = false; neig.add(scheibe);
    const halo = new THREE.Mesh(new THREE.RingGeometry(0.95, 1.6, 128, 2), new THREE.ShaderMaterial({ vertexShader: DISK_VS, fragmentShader: HALO_FS,
      transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending }));
    halo.frustumCulled = false; halo.visible = false; szene.add(halo);
    const glut = leuchtPunkt([1.0, 0.62, 0.3], true); szene.add(glut);
    loch = { name: "TON 618", art: "riesenloch", pos: [sonne.pos[0] + dir.x * LOCH_ABSTAND, sonne.pos[1] + dir.y * LOCH_ABSTAND, sonne.pos[2] + dir.z * LOCH_ABSTAND],
      r: RS, rSicht: RS * 3.5, masse: 66e9 * 1.989e30, daten: { name: "TON 618" }, marke: null, gruppe, scheibe: mat, halo, glut };
  }
  function saturnRingBauen() {
    const sat = koerperObjekte.find(k => k.daten.name === "Saturn"); if (!sat) return;
    const geo = new THREE.RingGeometry(1.24, 2.27, 160, 1), pos = geo.attributes.position, uv = geo.attributes.uv;
    for (let i = 0; i < pos.count; i++) uv.setXY(i, (Math.hypot(pos.getX(i), pos.getY(i)) - 1.24) / (2.27 - 1.24), 0.5);
    const c = document.createElement("canvas"); c.width = 1024; c.height = 4; const x = c.getContext("2d"), img = x.createImageData(1024, 4);
    for (let i = 0; i < 1024; i++) {
      const t = i / 1023; let a, h = 0.82 + 0.18 * Math.sin(i * 0.9) * Math.sin(i * 0.23);
      if (t < 0.10) a = 0.10 + 0.5 * t; else if (t < 0.52) a = 0.80; else if (t < 0.58) a = 0.05; else if (t < 0.94) a = 0.62; else a = Math.max(0, (1 - t) / 0.06) * 0.5;
      a *= 0.75 + 0.25 * Math.sin(i * 0.55 + Math.sin(i * 0.07) * 4);
      for (let j = 0; j < 4; j++) { const k = (j * 1024 + i) * 4; img.data[k] = 224 * h; img.data[k + 1] = 204 * h; img.data[k + 2] = 168 * h; img.data[k + 3] = Math.max(0, Math.min(1, a)) * 255; }
    }
    x.putImageData(img, 0, 0);
    const tex = new THREE.CanvasTexture(c);
    const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ map: tex, transparent: true, side: THREE.DoubleSide, depthWrite: false, roughness: 0.9, metalness: 0,
      emissive: new THREE.Color(0.22, 0.2, 0.17), emissiveMap: tex }));
    m.rotation.x = -Math.PI / 2; m.frustumCulled = false;
    const w = new THREE.Group(); w.rotation.set(0.47, 0, 0.25); w.add(m); szene.add(w);
    ringSaturn = { wrapper: w, sat };
  }

  // ---------------- Bahn und Bild ----------------
  const bU = new THREE.Vector3(), bW = new THREE.Vector3(), nOrbit = new THREE.Vector3(0.28, 0.9, 0.33).normalize();
  bU.crossVectors(nOrbit, new THREE.Vector3(1, 0, 0)).normalize(); bW.crossVectors(nOrbit, bU).normalize();
  const qStation = new THREE.Quaternion(), tmp = new THREE.Vector3();
  function schritt(dt) {
    lochZeit += dt; if (loch) loch.scheibe.uniforms.uZeit.value = lochZeit;
    if (!st || !erde) return;
    winkel += dt * Math.PI * 2 / UMLAUF;
    const c = Math.cos(winkel), s = Math.sin(winkel);
    const rad = new THREE.Vector3().copy(bU).multiplyScalar(c).addScaledVector(bW, s);                 // nach aussen
    const tang = new THREE.Vector3().copy(bU).multiplyScalar(-s).addScaledVector(bW, c);               // Flugrichtung
    st.pos = [erde.pos[0] + rad.x * BAHN, erde.pos[1] + rad.y * BAHN, erde.pos[2] + rad.z * BAHN];
    const z = new THREE.Vector3().crossVectors(tang, rad).normalize();
    qStation.setFromRotationMatrix(new THREE.Matrix4().makeBasis(tang, rad, z));
    for (const m of module) { tmp.copy(m.lokal).multiplyScalar(L).applyQuaternion(qStation); m.pos = [st.pos[0] + tmp.x, st.pos[1] + tmp.y, st.pos[2] + tmp.z]; }
    terminPhase += dt * 0.35;
    for (const t of termine) { terminLage(t); tmp.copy(t.lokal).multiplyScalar(L).applyQuaternion(qStation); t.pos = [st.pos[0] + tmp.x, st.pos[1] + tmp.y, st.pos[2] + tmp.z]; }
    for (const p of planeten) if (p.huelle) p.huelle.rotation.y += dt * p.p.drehen;
  }
  function bild(kp, kandidaten, orte) {
    if (!st) return;
    const rel = sub(st.pos, kp), d = Math.max(laenge(rel), 1);
    const sichtbar = d < sichtbarBis; wurzel.visible = sichtbar; if (!sichtbar) nahFlag = false;
    if (sichtbar) {
      wurzel.position.set(rel[0] * S, rel[1] * S, rel[2] * S); wurzel.quaternion.copy(qStation); wurzel.scale.setScalar(L * S);
      const nah = d < L * 22;                                                  // Module einzeln beschriften, wenn man nah genug ist
      nahFlag = nah;
      const istSt = ziel && ziel.obj === st;
      const sp = aufBildschirm(rel);
      if (nah) {
        if (st.marke) st.marke.style.display = "none";
        for (const m of module) {
          const r = sub(m.pos, kp), s = aufBildschirm(r), istZ = ziel && ziel.obj === m;
          if (s) { orte.push({ x: s[0], y: s[1], z: { art: "koerper", obj: m } });
            kandidaten.push({ o: m, x: s[0], y: s[1], prio: (istZ ? 1e9 : 0) + 4e3, ziel: istZ }); }
          else if (m.marke) m.marke.style.display = "none";
        }
        for (const t of termine) {   // Termin-Lichter beschriften (unter den Modulen)
          const s = aufBildschirm(sub(t.pos, kp)), istZ = ziel && ziel.obj === t;
          if (s) { orte.push({ x: s[0], y: s[1], z: { art: "koerper", obj: t } });
            kandidaten.push({ o: t, x: s[0], y: s[1], prio: (istZ ? 1e9 : 0) + 3e3 - t.tage, ziel: istZ }); }
          else if (t.marke) t.marke.style.display = "none";
        }
      } else {
        for (const m of module) if (m.marke) m.marke.style.display = "none";
        for (const t of termine) if (t.marke) t.marke.style.display = "none";
        if (sp) { orte.push({ x: sp[0], y: sp[1], z: { art: "koerper", obj: st } });
          kandidaten.push({ o: st, x: sp[0], y: sp[1], prio: (istSt ? 1e9 : 0) + 6e3, ziel: istSt }); }
      }
    } else { if (st.marke) st.marke.style.display = "none"; for (const m of module) if (m.marke) m.marke.style.display = "none";
      for (const t of termine) if (t.marke) t.marke.style.display = "none"; }
    for (const p of planeten) {
      const r = sub(p.pos, kp), dd = Math.max(laenge(r), 1), istZ = ziel && ziel.obj === p;
      const sicht = dd < 2e13 && (dd < 40 * AE || istZ);
      p.gruppe.visible = sicht;
      if (!sicht) { if (p.marke) p.marke.style.display = "none"; continue; }
      const rv = Math.max(p.rSicht, dd * 1.6 * renderer.getPixelRatio() / pxProEinheit);
      p.gruppe.position.set(r[0] * S, r[1] * S, r[2] * S); p.gruppe.scale.setScalar(rv * S);
      const s = aufBildschirm(r);
      if (s) { orte.push({ x: s[0], y: s[1], z: { art: "koerper", obj: p } });
        if (istZ || dd < 8 * AE) kandidaten.push({ o: p, x: s[0], y: s[1], prio: (istZ ? 1e9 : 0) + 2e3, ziel: istZ }); else if (p.marke) p.marke.style.display = "none"; }
      else if (p.marke) p.marke.style.display = "none";
    }
    // Saturnringe
    if (ringSaturn) { const m = ringSaturn.sat.mesh; ringSaturn.wrapper.visible = m.visible;
      if (m.visible) { ringSaturn.wrapper.position.copy(m.position); ringSaturn.wrapper.scale.copy(m.scale); } }
    // Riesen-Schwarzes-Loch
    if (loch) {
      const r = sub(loch.pos, kp), d = Math.max(laenge(r), 1), ratio = renderer.getPixelRatio(), istZ = ziel && ziel.obj === loch;
      const px = 7.5 * RS * pxProEinheit / d / ratio, gross = px > 2.5;
      loch.gruppe.visible = gross; loch.halo.visible = gross;
      if (gross) {
        loch.gruppe.position.set(r[0] * S, r[1] * S, r[2] * S); loch.gruppe.scale.setScalar(RS * S);
        loch.halo.position.copy(loch.gruppe.position); loch.halo.scale.setScalar(RS * S); loch.halo.lookAt(0, 0, 0);
      }
      loch.glut.visible = px < 70;
      if (loch.glut.visible) { loch.glut.position.set(r[0] * S, r[1] * S, r[2] * S);
        loch.glut.material.uniforms.uGr.value = Math.min(Math.max(26 * ratio, px * ratio * 1.2), MAX_PUNKT);
        loch.glut.material.uniforms.uA.value = 0.9 * Math.min(1, Math.max(0.15, 1 - (px - 8) / 60)); }
      const s = aufBildschirm(r);
      if (s) { orte.push({ x: s[0], y: s[1], z: { art: "koerper", obj: loch } });
        if (istZ || px > 14) kandidaten.push({ o: loch, x: s[0], y: s[1], prio: (istZ ? 1e9 : 0) + 5e3, ziel: istZ }); else if (loch.marke) loch.marke.style.display = "none"; }
      else if (loch.marke) loch.marke.style.display = "none";
    }
    knopfPruefen();
  }

  // ---------------- Anbindung ----------------
  function aufbauen(d) {
    leeren();
    erde = koerperObjekte.find(k => k.daten.name === "Earth" || k.daten.name === "Erde") || null;
    sonne = koerperObjekte.find(k => k.art === "star") || null;
    if (!erde) { meldung("keine Erde in der Szene - keine Station"); return; }
    stationBauen();
    if (!SP.get("ohneplaneten")) { planetenBauen(); erdeVerschoenern(); }
    try { saturnRingBauen(); if (sonne && !SP.get("ohneloch")) lochBauen(); } catch (e) { meldung("Ringe/Loch: " + e.message); }
    schritt(0);
  }
  function leeren() {
    termineEntfernen(); clearInterval(terminUhr); terminUhr = null;
    if (wurzel) { szene.remove(wurzel); wurzel.traverse(o => { if (o.geometry) o.geometry.dispose(); }); }
    for (const p of planeten) szene.remove(p.gruppe);
    if (loch) { szene.remove(loch.gruppe); szene.remove(loch.halo); szene.remove(loch.glut); loch = null; }
    if (ringSaturn) { szene.remove(ringSaturn.wrapper); ringSaturn = null; }
    wurzel = null; st = null; module = []; planeten = []; erde = null; sonne = null;
    const b = document.getElementById("oeffnen"); if (b) b.style.display = "none";
  }
  function ziele() { return st ? [st, ...module, ...termine, ...planeten, ...(loch ? [loch] : [])] : []; }
  function fahre(id) { // von Auron: Tour-Station anfliegen
    if (!st) return false;
    let o = null;
    if (id === "jarvis") o = st;
    else if (id === "uebersicht") { if (!fahre._n) { fahre._n = 1; universumZeigen(id); return true; } o = st; }
    else o = module.find(m => m.id === id);
    if (!o) return false;
    fliegen({ art: "koerper", obj: o, tourId: id }); return true;
  }
  function status(neu) { if (neu && typeof neu === "object") { for (const k of Object.keys(an)) if (k in neu) an[k] = !!neu[k]; statusAnwenden(); } }
  function knopfPruefen() {
    let b = document.getElementById("oeffnen");
    if (!b) { b = document.createElement("button"); b.id = "oeffnen"; b.type = "button"; document.body.appendChild(b);
      b.onclick = () => { if (!offen) return;
        if (window.parent !== window) window.parent.postMessage({ auron: "oeffne", id: offen.id, seite: offen.seite, name: offen.name }, "*");
        else meldung("Öffnen: " + offen.name + " (" + offen.seite + ")"); }; }
    const z = ziel && ziel.obj && (ziel.obj.art === "modul" || ziel.obj.art === "termin") ? ziel.obj : null;
    if (z !== offen) { offen = z; if (z) b.textContent = z.art === "termin" ? "Kalender öffnen" : z.name + " öffnen" + (z.laeuft ? "" : " (ruht)"); }
    b.style.display = z && !flug ? "block" : "none";
  }
  return { aufbauen, leeren, schritt, bild, ziele, fahre, status, nah: () => nahFlag, glbLaden, termineBauen, termineLaden,
    intern: () => ({ st, module, planeten, an, erde, termine }) };
})();

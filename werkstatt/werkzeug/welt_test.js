const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader','--ignore-gpu-blocklist'] });
  const fehler = [];
  const p = await b.newPage({ viewport: {width: +(process.env.B||1280), height: +(process.env.H||760)} });
  p.on('console', m => { if (m.type()==='error' || m.type()==='warning') fehler.push(m.type()+': '+m.text().slice(0,300)); });
  p.on('pageerror', e => fehler.push('pageerror: '+e.message));
  const t0 = Date.now();
  await p.goto('file://' + __dirname + '/welt_3d.html' + (process.env.Q ? '?q='+process.env.Q : ''));
  await p.waitForFunction(() => window.__welt || (window.__fehler && window.__fehler.length), null, {timeout: 300000});
  console.log('geladen nach', (Date.now()-t0)/1000, 's');
  console.log(JSON.stringify(await p.evaluate(() => { const s = window.__welt; if(!s) return window.__fehler; return {quelle:s.quelle, stufe:s.stufe, gitter:s.gitter, ecken:s.ecken, aufbauMs:s.aufbauMs, hMitte:s.hoehe(0,0), hNord:s.hoehe(0,-3000)}; })));
  const ansichten = (process.argv[2] || 'uebersicht:12,uebersicht:18.75,uebersicht:23,baum:12,kueste:18.75').split(',');
  for (const a of ansichten) {
    const [ansicht, st] = a.split(':');
    await p.evaluate(([ansicht, st]) => {
      const w = window.__welt, sel = document.getElementById('licht'); sel.value = st; sel.dispatchEvent(new Event('change'));
      const T = THREE;
      if (ansicht === 'baum') { const z = w.zielFuer('jarvis'); w.kamera.position.copy(z.pos); w.steuerung.target.copy(z.ziel); }
      else if (ansicht === 'kueste') { w.kamera.position.set(-5200, 420, -1200); w.steuerung.target.set(-2400, 60, -2600); }
      else if (ansicht === 'gehirn') { w.kamera.position.set(-2800, 900, -1500); w.steuerung.target.set(w.ORTE.vault.x, 40, w.ORTE.vault.z); }
      else if (ansicht === 'sued') { w.kamera.position.set(800, 700, 6200); w.steuerung.target.set(0, 150, 0); }
      else { w.kamera.position.set(1200, 4600, 10400); w.steuerung.target.set(600, 150, -200); }
      w.steuerung.update();
    }, [ansicht, st]);
    await p.waitForTimeout(6000);
    await p.screenshot({ timeout: 400000, path: __dirname + `/w_${ansicht}_${st}.png` });
    console.log('bild', ansicht, st, 'fps', await p.evaluate(()=>window.__fps));
  }
  console.log('FEHLER:', fehler.slice(0,20).join('\n'));
  await b.close();
})();

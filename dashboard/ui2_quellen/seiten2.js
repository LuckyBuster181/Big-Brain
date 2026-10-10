
/* ================================================================== Seiten 2.0 (27.09.2026)
   Wünsche von Sir: Weltraum-Glas als Standard auf allen Seiten, Seitenköpfe,
   Markt = Kachel-Übersicht UND Trading-Ansicht (umschaltbar), Alltag = Kachel-Dashboard.
   Alles läuft im Browser, keine Claude-Kosten. */
;(function seiten2() {
  const LS2 = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* privat */ } },
  };
  const seiteZeigen = (name) => { const b = document.querySelector(`nav button[data-page="${name}"]`); if (b) b.click(); };
  const seiteAktiv = (name) => { const p = document.getElementById("page-" + name); return !!(p && p.classList.contains("active")); };
  const zahl = (v, n) => (v === null || v === undefined || Number.isNaN(v)) ? "–" : fmtNum(v, n);

  /* ---------------------------------------------------------------- 1) Glas einmalig als Standard */
  if (!LS2.get("hud.glasStandard", false)) {
    S.stil = "glas"; LS2.set("hud.glasStandard", true);
    try { einstellungenSpeichernLokal(); } catch (e) { /* egal */ }
    try { stilAnwenden(); } catch (e) { /* egal */ }
  }

  /* ---------------------------------------------------------------- 2) Seitenköpfe für die übrigen Seiten */
  const KOEPFE = {
    vault: ["Gedächtnis", "Was Jarvis aus dem Vault weiß und wie gut er sucht"],
    labor: ["Labor", "Trading-Sandbox, Paper-Trading und Prüfstand"],
    tiktok: ["TikTok", "Gelernte Videos und Ideen"],
    denkblock: ["Denkblock", "Gedanken sammeln, ordnen, weiterdenken"],
    nacht: ["Nacht", "Aufträge für die Nachtarbeit und die Frage des Tages"],
    karte: ["Karte", "Wie die Notizen im Vault zusammenhängen"],
    pc2: ["PC 2", "Mini-PC: Last, Dienste und Zustand"],
    geraete: ["Geräte", "PCs, Laptop und Handy im Netz"],
    settings: ["Einstellungen", "Alles an einem Ort, nach Bereichen sortiert"],
  };
  Object.entries(KOEPFE).forEach(([id, [titel, unter]]) => {
    const sec = document.getElementById("page-" + id);
    if (!sec || sec.querySelector(":scope > .seiten-kopf")) return;
    const k = document.createElement("div");
    k.className = "seiten-kopf";
    k.innerHTML = `<div><h1>${esc(titel)}</h1><div class="unter">${esc(unter)}</div></div>`;
    sec.insertBefore(k, sec.firstChild);
  });

  /* ---------------------------------------------------------------- 3) Markt */
  const mk = { modus: LS2.get("hud.mkModus", "kacheln"), spark: {}, laeuft: 0, warte: [] };
  const GRUPPEN_LIVE = [["krypto", "Krypto"], ["metall", "Metalle"], ["devisen", "Devisen"]];
  const SPARK_ART = { "1h": ["1m", 61], "24h": ["1h", 25], "7d": ["4h", 43], "30d": ["1d", 31], "1y": ["1w", 53] };

  function sparkSvg(werte) {
    if (!werte || werte.length < 2) return "";
    const min = Math.min(...werte), max = Math.max(...werte), sp = (max - min) || 1;
    const B = 200, H = 44;
    const pkt = werte.map((v, i) => [(i / (werte.length - 1)) * B, H - 4 - ((v - min) / sp) * (H - 8)]);
    const linie = pkt.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    const farbe = werte[werte.length - 1] > werte[0] ? "#5fe3ad" : werte[werte.length - 1] < werte[0] ? "#ff8a96" : "#7fd8ff";
    return `<svg viewBox="0 0 ${B} ${H}" preserveAspectRatio="none"><path d="${linie} L${B} ${H} L0 ${H} Z" fill="${farbe}" fill-opacity=".1"/><path d="${linie}" fill="none" stroke="${farbe}" stroke-width="1.6" vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg>`;
  }
  // höchstens 3 Abrufe gleichzeitig, damit weder Binance noch der Mini-PC ins Schwitzen kommt
  function holen(schluessel, url, umwandeln) {
    const c = mk.spark[schluessel];
    if (c && (c.werte || c.laedt) && Date.now() - c.zeit < 5 * 60 * 1000) return;
    mk.spark[schluessel] = { laedt: true, zeit: Date.now() };
    mk.warte.push(async () => {
      try { mk.spark[schluessel] = { werte: umwandeln(await json(url)), zeit: Date.now() }; }
      catch (e) { mk.spark[schluessel] = { werte: null, zeit: Date.now() }; }
      kachelnZeichnen();
    });
    pumpe();
  }
  function pumpe() {
    while (mk.laeuft < 3 && mk.warte.length) {
      const job = mk.warte.shift(); mk.laeuft++;
      job().finally(() => { mk.laeuft--; pumpe(); });
    }
  }
  const pille = (c) => `<span class="mk-pille ${cls(c)}">${c === undefined || c === null ? "–" : pct(c)}</span>`;
  const suche = () => ($("search").value || "").trim().toLowerCase();

  function kachelnZeichnen() {
    const box = $("mkKacheln");
    if (!box || mk.modus !== "kacheln") return;
    const q = suche();
    let html = "";
    if (jm.ansicht === "alle") {
      const passt = (m) => !q || m.symbol.toLowerCase().includes(q) || String(m.name).toLowerCase().includes(q);
      MARKT_REIHE.forEach(([markt, titel]) => {
        const liste = (jm.daten || []).filter((m) => m.markt === markt && passt(m));
        if (!liste.length) return;
        html += `<div class="mk-gruppe-titel">${esc(titel)}</div><div class="mk-raster">` + liste.map((m) => {
          const sch = "A:" + m.symbol;
          if (m.kurs !== null) holen(sch, `/api/markt/kerzen?symbol=${encodeURIComponent(m.symbol)}&intervall=1d&anzahl=30`, (d) => (d.kerzen || []).map((k) => k.close));
          const sp = mk.spark[sch];
          return `<div class="mk-kachel" data-alle="${esc(m.symbol)}">
            <div class="kz"><span class="sym">${esc(m.symbol)}</span>${pille(m.veraenderung_prozent)}</div>
            <div class="name">${esc(m.name)}</div>
            <div class="preis">${m.kurs === null ? '<span class="hint">nicht geladen</span>' : price(m.kurs)}</div>
            ${sp && sp.werte ? sparkSvg(sp.werte) : `<div class="leer">${m.kurs === null ? "„Alle Märkte laden“ drücken" : "30 Tage …"}</div>`}
          </div>`;
        }).join("") + "</div>";
      });
      if (!html) html = '<div class="hint">Keine Märkte gefunden. Oben „Alle Märkte laden“ drücken.</div>';
    } else {
      const liste = assets.filter((a) => !q || a.sym.toLowerCase().includes(q) || a.name.toLowerCase().includes(q));
      const [iv, n] = SPARK_ART[periodKey] || SPARK_ART["24h"];
      GRUPPEN_LIVE.forEach(([art, titel]) => {
        const teil = liste.filter((a) => a.kind === art);
        if (!teil.length) return;
        html += `<div class="mk-gruppe-titel">${titel}</div><div class="mk-raster">` + teil.map((a) => {
          const sch = a.key + "|" + periodKey;
          if (a.kind === "krypto") holen(sch, `https://data-api.binance.vision/api/v3/klines?symbol=${a.key}&interval=${iv}&limit=${n}`, (k) => k.map((x) => +x[4]));
          const sp = mk.spark[sch];
          const leer = a.kind === "metall" ? "nur aktueller Preis" : a.kind === "devisen" ? "EZB-Tageskurs" : "lädt …";
          return `<div class="mk-kachel" data-key="${esc(a.key)}">
            <div class="kz"><span class="sym">${esc(a.sym)}</span>${pille(a.chg[periodKey])}</div>
            <div class="name">${esc(a.name)}</div>
            <div class="preis">${price(a.price)}<small>${esc(a.unit || "")}</small></div>
            ${sp && sp.werte ? sparkSvg(sp.werte) : `<div class="leer">${leer}</div>`}
          </div>`;
        }).join("") + "</div>";
      });
      if (!html) html = assets.length ? '<div class="hint">Nichts gefunden.</div>' : '<div class="hint">Kurse laden …</div>';
    }
    box.innerHTML = html;
    const stand = new Date().toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
    $("mkUnter").textContent = (jm.ansicht === "alle" ? "Alle Märkte · Kerzen vom Mini-PC" : "Live-Kurse · Krypto, Metalle, Devisen") + " · Stand " + stand + " Uhr";
  }
  $("mkKacheln").addEventListener("click", (ev) => {
    const k = ev.target.closest(".mk-kachel"); if (!k) return;
    modusSetzen("trading");
    if (k.dataset.alle) { jm.symbol = k.dataset.alle; alleZeichnen(); jarvisChart(); }
    else select(k.dataset.key);
  });

  function detailZeichnen() {
    const box = $("mkDetail"); if (!box) return;
    if (jm.ansicht === "alle") {
      const m = (jm.daten || []).find((x) => x.symbol === jm.symbol);
      box.innerHTML = m ? `<div class="sym" style="font-size:18px;font-weight:600">${esc(m.symbol)}</div><div class="hint">${esc(m.name)}</div>
        <div class="mk-preis-gross">${m.kurs === null ? "–" : price(m.kurs)}</div><div style="margin-top:6px">${pille(m.veraenderung_prozent)}</div>`
        : '<div class="hint">Links einen Markt wählen.</div>';
      return;
    }
    const a = assets.find((x) => x.key === selected);
    if (!a) { box.innerHTML = '<div class="hint">Links einen Markt wählen.</div>'; return; }
    const wert = (t, v) => `<div><span>${t}</span><b>${v}</b></div>`;
    box.innerHTML = `<div class="sym" style="font-size:18px;font-weight:600">${esc(a.sym)}</div><div class="hint">${esc(a.name)}</div>
      <div class="mk-preis-gross">${price(a.price)} <span class="hint" style="font-size:13px">${esc(a.unit || "")}</span></div>
      <div style="margin-top:6px">${pille(a.chg[periodKey])} <span class="hint">über ${esc((PERIODS.find((p) => p.key === periodKey) || {}).label || "")}</span></div>
      <div class="mk-werte">
        ${wert("Hoch 24 Std", a.hoch ? price(a.hoch) : "–")}${wert("Tief 24 Std", a.tief ? price(a.tief) : "–")}
        ${wert("24 Std", pct(a.chg["24h"]))}${wert("Quelle", a.kind === "krypto" ? "Binance" : a.kind === "metall" ? "gold-api" : "EZB")}
      </div>
      <div class="row" style="gap:6px; margin-top:12px"><span class="chip" id="mkFragen" title="Bereitet eine Frage an Jarvis vor. Gesendet wird erst mit Enter (normale Fragekosten).">Jarvis fragen</span></div>`;
    $("mkFragen").addEventListener("click", () => {
      seiteZeigen("jarvis");
      setTimeout(() => {
        const t = `Wie schätzt du ${a.name} (${a.sym}) gerade ein? Kurs ${price(a.price)} ${a.unit || ""}, ${pct(a.chg["24h"])} in 24 Stunden.`;
        if (JV.aktiv && $("jvText")) { $("jvText").value = t; $("jvText").focus(); }
        else { $("chatInput").value = t; $("chatInput").focus(); }
      }, 200);
    });
  }

  function modusSetzen(m) {
    mk.modus = m; LS2.set("hud.mkModus", m);
    document.querySelectorAll("#mkModus [data-mk]").forEach((b) => b.classList.toggle("active", b.dataset.mk === m));
    $("mkKacheln").hidden = m !== "kacheln";
    $("mkTrading").hidden = m !== "trading";
    if (m === "kacheln") kachelnZeichnen();
    else {
      detailZeichnen();
      if (jm.ansicht === "alle") { if (jm.symbol) jarvisChart(); } else drawChart();
      setTimeout(() => window.dispatchEvent(new Event("resize")), 60);
    }
  }
  $("mkModus").addEventListener("click", (ev) => { const b = ev.target.closest("[data-mk]"); if (b) modusSetzen(b.dataset.mk); });
  document.addEventListener("keydown", (e) => {
    if (!seiteAktiv("markt") || e.target.closest("input, textarea, select") || e.ctrlKey || e.metaKey) return;
    if (e.key === "t" || e.key === "T") modusSetzen(mk.modus === "kacheln" ? "trading" : "kacheln");
  });
  // Chart füllt die Karte (statt fester 420 px)
  new ResizeObserver(() => {
    const el = $("chart");
    if (typeof chart !== "undefined" && chart && el.clientHeight > 120) chart.applyOptions({ height: el.clientHeight, width: el.clientWidth });
  }).observe($("chart"));

  // bestehende Markt-Funktionen erweitern, nicht ersetzen
  const renderAlt = render;
  render = function () { renderAlt(); kachelnZeichnen(); if (mk.modus === "trading") detailZeichnen(); };
  const alleAlt = alleZeichnen;
  alleZeichnen = async function () { await alleAlt(); kachelnZeichnen(); if (mk.modus === "trading") detailZeichnen(); };
  const ansichtAlt = marktAnsichtSetzen;
  marktAnsichtSetzen = function (a) {
    ansichtAlt(a);
    $("alleLadenBox").style.display = a === "alle" ? "" : "none";
    kachelnZeichnen(); detailZeichnen();
  };
  $("search").addEventListener("input", () => kachelnZeichnen());
  $("periods").addEventListener("click", () => setTimeout(kachelnZeichnen, 50));
  $("alleLadenBox").style.display = jm.ansicht === "alle" ? "" : "none";
  modusSetzen(mk.modus);

  /* ---------------------------------------------------------------- 4) Alltag */
  function kw(d) {
    const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    const tag = t.getUTCDay() || 7; t.setUTCDate(t.getUTCDate() + 4 - tag);
    return Math.ceil(((t - new Date(Date.UTC(t.getUTCFullYear(), 0, 1))) / 864e5 + 1) / 7);
  }
  function uhrZeigen() {
    const d = new Date(), h = d.getHours();
    const gruss = h < 5 ? "Gute Nacht" : h < 11 ? "Guten Morgen" : h < 17 ? "Guten Tag" : h < 22 ? "Guten Abend" : "Gute Nacht";
    $("alHallo").textContent = gruss + ", " + (S.nutzer || "Sir");
    $("alDatum").textContent = d.toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long" }) + " · KW " + kw(d);
    $("alUhr").textContent = d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  }
  uhrZeigen(); setInterval(uhrZeigen, 15000);

  function bisText(start, ende) {
    const jetzt = Date.now(), s = new Date(start).getTime(), e = ende ? new Date(ende).getTime() : s;
    if (s <= jetzt && jetzt <= e) return "läuft gerade";
    const min = Math.round((s - jetzt) / 60000);
    if (min < 60) return "in " + Math.max(1, min) + " Min";
    if (min < 24 * 60) return "in " + Math.floor(min / 60) + " Std " + (min % 60 ? (min % 60) + " Min" : "");
    const tage = Math.round(min / 1440);
    return tage === 1 ? "morgen" : "in " + tage + " Tagen";
  }
  function tageText(iso) {
    const h = new Date(); h.setHours(0, 0, 0, 0);
    const d = new Date(iso + "T00:00:00"), n = Math.round((d - h) / 864e5);
    return n <= 0 ? "heute" : n === 1 ? "morgen" : "in " + n + " Tagen";
  }
  const ganzTag = (e) => String(e.start || "").length <= 10;
  drawUpcoming = function () {
    const jetzt = new Date().toISOString();
    const next = (events.termine || []).filter((e) => (e.ende || e.start) >= jetzt).slice(0, 7);
    if (!next.length) { $("calList").innerHTML = '<div class="hint">Keine Termine in Sicht, Sir.</div>'; return; }
    const [erst, ...rest] = next;
    const d0 = new Date(erst.start);
    const wann = d0.toLocaleDateString("de-DE", { weekday: "long", day: "2-digit", month: "2-digit" }) + (ganzTag(erst) ? " · ganztägig" : " · " + erst.start.slice(11, 16) + " Uhr");
    $("calList").innerHTML = `<div class="al-termin-gross"><div class="wann">${esc(wann)}</div><div class="titel">${esc(erst.titel || "Termin")}</div>
        ${erst.ort ? `<div class="ort">${esc(erst.ort)}</div>` : ""}<span class="bis">${esc(ganzTag(erst) ? tageText(erst.start) : bisText(erst.start, erst.ende))}</span></div>` +
      rest.map((e) => {
        const d = new Date(e.start);
        return `<div class="al-termin"><div class="al-datum"><b>${d.getDate()}</b><span>${d.toLocaleDateString("de-DE", { weekday: "short" }).replace(".", "")}</span></div>
          <div class="t"><div>${esc(e.titel || "Termin")}</div><small>${ganzTag(e) ? "ganztägig" : e.start.slice(11, 16) + " Uhr"}${e.ort ? " · " + esc(e.ort) : ""}</small></div></div>`;
      }).join("");
  };
  try { if (events && events.termine) drawUpcoming(); } catch (e) { /* Kalender kommt noch */ }

  async function wartetLaden() {
    const punkte = [];
    try {
      const f = await json("/api/tagesfrage");
      if (f && f.frage && !f.antwort) punkte.push({ text: "Frage des Tages: " + f.frage, knopf: "Beantworten", ziel: "nacht" });
    } catch (e) { /* Backend alt */ }
    try {
      const d = await json("/api/nachtauftraege");
      const liste = d.auftraege || [];
      liste.filter((a) => a.status === "rueckfrage").forEach((a) => punkte.push({ text: "Rückfrage zu „" + a.titel + "“: " + (a.rueckfragen || [])[0], knopf: "Antworten", ziel: "nacht" }));
      liste.filter((a) => a.status === "vorschlag").forEach((a) => punkte.push({ text: "Vorschlag für heute Nacht: „" + a.titel + "“", knopf: "Ansehen", ziel: "nacht" }));
      const gestern = Date.now() - 30 * 3600 * 1000;
      liste.filter((a) => a.status === "fertig" && new Date(a.geaendert).getTime() > gestern)
        .forEach((a) => punkte.push({ text: "Fertig in der Nacht: „" + a.titel + "“" + (a.ergebnis && a.ergebnis.urteil ? " (Prüfung: " + a.ergebnis.urteil + ")" : ""), knopf: "Lesen", ziel: "nacht", ok: true }));
      if (d.naechster_lauf) punkte.push({ text: "Nächste Nachtarbeit: " + d.naechster_lauf, ok: true });
    } catch (e) { /* Backend alt */ }
    $("alWartet").innerHTML = punkte.length ? punkte.map((p) => `<div class="al-punkt"><i class="${p.ok ? "ok" : ""}"></i><div>${esc(p.text)}${p.knopf ? `<br><span class="chip" data-ziel="${p.ziel}">${esc(p.knopf)}</span>` : ""}</div></div>`).join("")
      : '<div class="hint">Nichts offen, Sir.</div>';
    $("alWartet").classList.remove("hint");
  }
  $("alWartet").addEventListener("click", (ev) => { const c = ev.target.closest("[data-ziel]"); if (c) seiteZeigen(c.dataset.ziel); });
  wartetLaden(); setInterval(wartetLaden, 5 * 60 * 1000);
  document.querySelector('nav button[data-page="alltag"]').addEventListener("click", () => { uhrZeigen(); wartetLaden(); });
})();

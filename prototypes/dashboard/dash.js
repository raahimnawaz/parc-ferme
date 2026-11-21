(() => {
  const D = JSON.parse(document.getElementById('data').textContent);
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const N = D.n, DX = D.dx, L = D.L;
  const X = Float64Array.from({ length: N }, (_, i) => i * DX);
  const SEC = ['#ef3b36', '#2fa4ff', '#ffd12e'];
  const NEUTRAL = '#4a4a50';
  const AX = 40; // width of every chart's right-hand value axis, so all plots share one x-to-pixel mapping
  const DATA_FONT = '"DM Mono", ui-monospace, Menlo, monospace';
  const uiFont = () => getComputedStyle(document.body).fontFamily;
  const FONTS = ['garamond', 'newsreader', 'spectral', 'source'];
  const order = [...$('#selA').options].map(o => o.value);
  const state = { ws: 'lap', a: order[0], b: order[1], lap: 'fastest', sim: false, type: 'garamond', x0: 0, x1: L, cur: null, ref: null, map: 'gain' };

  // ---------- state in the URL ----------
  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    if (p.get('ws')) state.ws = p.get('ws');
    if (D.cars[p.get('a')]) state.a = p.get('a');
    if (D.cars[p.get('b')]) state.b = p.get('b');
    if (['fastest', 'typical'].includes(p.get('lap'))) state.lap = p.get('lap');
    state.sim = p.get('sim') === '1';
    if (FONTS.includes(p.get('type'))) state.type = p.get('type');
  }
  function writeHash() {
    const p = new URLSearchParams({ ws: state.ws, a: state.a, b: state.b, lap: state.lap, sim: state.sim ? '1' : '0', type: state.type });
    history.replaceState(null, '', '#' + p.toString());
  }

  // ---------- colours: each car keeps its team colour; a clash falls back to white ----------
  const rgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
  const lum = h => {
    const c = rgb(h).map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  };
  const mix = (h, t) => '#' + rgb(h).map(v => Math.round(v + (255 - v) * t).toString(16).padStart(2, '0')).join('');
  const lift = h => { let c = h, t = 0; while (lum(c) < 0.17 && t < 0.6) { t += 0.08; c = mix(h, t); } return c; };
  const far = (a, b) => { const x = rgb(a), y = rgb(b); return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]); };
  const alpha = (h, a) => { const [r, g, b] = rgb(h); return `rgba(${r},${g},${b},${a})`; };
  function colours() {
    const A = D.cars[state.a], B = D.cars[state.b];
    const ca = lift(A.colour);
    let cb = lift(B.colour);
    if (A.team === B.team || far(ca, cb) < 110) cb = '#e6e6ea';
    return [ca, cb];
  }

  // ---------- data ----------
  const lapOf = c => D.cars[c][state.lap];
  const chan = (c, k) => { const a = lapOf(c).ch[k]; return k === 't' ? a.map(v => v / 1000) : k === 'rpm' ? a.map(v => v * 10) : a.slice(); };
  const at = (arr, x) => { const f = Math.min(Math.max(x / DX, 0), N - 1), i = Math.floor(f), j = Math.min(i + 1, N - 1); return arr[i] + (arr[j] - arr[i]) * (f - i); };
  const tAt = (side, x) => x >= L - 1e-6 ? lapOf(side === 'A' ? state.a : state.b).time : at(cache[side].t, x);
  let cache = {};

  // ---------- channels ----------
  const PANELS = [
    { id: 'v', name: 'Speed', unit: 'km/h', h: 150, key: 'v', sim: 'v', fmt: v => v.toFixed(0) },
    { id: 'dt', name: 'Time gap', unit: 's', h: 104, delta: true },
    { id: 'thr', name: 'Throttle', unit: '%', h: 64, key: 'thr', sim: 'thr', fmt: v => v.toFixed(0) },
    { id: 'brk', name: 'Brake', unit: '', h: 42, key: 'brk' },
    { id: 'gear', name: 'Gear', unit: '', h: 64, key: 'gear', fmt: v => v.toFixed(0) },
    { id: 'rpm', name: 'Engine speed', unit: 'rpm', h: 64, key: 'rpm', fmt: v => (v / 1000).toFixed(1) + 'k' },
    { id: 'ers', name: 'ERS power', unit: 'kW, sim', h: 78, simOnly: true },
    { id: 'soc', name: 'Battery', unit: 'MJ, sim', h: 56, simOnly: true },
  ];
  const traces = $('#traces');
  const rows = {};
  function row(cls) {
    const r = document.createElement('div'); r.className = 'tr-row ' + (cls || '');
    const lg = document.createElement('div'); lg.className = 'lg';
    const pl = document.createElement('div'); pl.className = 'plot';
    r.append(lg, pl); traces.append(r);
    return { r, lg, pl };
  }
  const stripe = row('stripe');
  PANELS.forEach(p => { rows[p.id] = row(); });
  const charts = {};

  let W = 600;
  const PW = () => W - AX;
  const span = () => state.x1 - state.x0;
  const sx = x => (x - state.x0) / span() * PW();

  // ---------- circuit stripe: sectors, corners and straight-mode zones on the same x as the charts ----------
  function drawStripe() {
    const h = 42, w = PW();
    let s = `<svg height="${h}" viewBox="0 0 ${W} ${h}">`;
    D.sectors.forEach((sec, k) => {
      const a = Math.max(sx(sec.x0), 0), b = Math.min(sx(sec.x1), w);
      if (b <= a) return;
      s += `<rect class="stripe-sec" data-k="${k}" x="${a}" y="14" width="${b - a}" height="24" fill="transparent"/>`;
      s += `<rect x="${a}" y="19" width="${b - a}" height="2" fill="${SEC[k]}" pointer-events="none"/>`;
      const label = `Sector ${sec.k} · Turns ${sec.corners[0]}–${sec.corners[sec.corners.length - 1]}`;
      if (b - a > label.length * 6.6 + 16) s += `<text class="stripe-lab" x="${a + 6}" y="35" style="fill:${SEC[k]}">${label}</text>`;
      else if (b - a > 26) s += `<text class="stripe-lab" x="${a + 6}" y="35" style="fill:${SEC[k]}">S${sec.k}</text>`;
    });
    D.zones.forEach(([z0, z1]) => {
      (z1 > z0 ? [[z0, z1]] : [[z0, L], [0, z1]]).forEach(([a, b]) => {
        const p = Math.max(sx(a), 0), q = Math.min(sx(b), w);
        if (q > p) s += `<line x1="${p}" x2="${q}" y1="24.5" y2="24.5" stroke="#2ecc71" stroke-width="1" stroke-dasharray="3 2"><title>Straight-mode zone</title></line>`;
      });
    });
    D.corners.forEach(c => {
      const x = sx(c.x);
      if (x < -4 || x > w + 4) return;
      s += `<line x1="${x}" x2="${x}" y1="12" y2="19" stroke="#55555c"/>`;
      s += `<text class="corner-lab" data-zoom="${c.x}" x="${x}" y="9" text-anchor="middle">${c.n}</text>`;
    });
    stripe.pl.innerHTML = s + '</svg>';
    stripe.lg.innerHTML = `<div class="lg-h">Distance<small>m</small></div><div class="lg-v"><b data-v="X">—</b></div><div class="lg-note" data-v="XN"></div>`;
  }

  // ---------- charts (uPlot) ----------
  const axisY = (extra = {}) => ({
    side: 1, size: AX, gap: 6, stroke: '#6b6b6b', font: `10.5px ${DATA_FONT}`, ticks: { show: false },
    grid: { stroke: 'rgba(255,255,255,0.06)', width: 1 }, ...extra,
  });
  const axisX = show => show
    ? { stroke: '#6b6b6b', font: `10.5px ${DATA_FONT}`, size: 24, gap: 4, ticks: { show: false }, grid: { show: false },
        values: (u, vals) => vals.map(v => v >= 1000 ? (v / 1000).toFixed(v % 1000 ? 1 : 0) + ' km' : v + ' m') }
    : { show: false };
  const line = (stroke, extra = {}) => ({ stroke, width: 1.25, points: { show: false }, ...extra });

  function series(p, ca, cb) {
    const A = cache.A, B = cache.B, S = cache.S;
    if (p.delta) {
      const dt = cache.dt;
      return {
        data: [X, dt.map(v => Math.max(v, 0)), dt.map(v => Math.min(v, 0)), dt],
        series: [{}, line('transparent', { width: 0, fill: alpha(ca, 0.2), fillTo: 0 }),
          line('transparent', { width: 0, fill: alpha(cb, 0.2), fillTo: 0 }), line('#ffffff')],
        y: { range: (u, mn, mx) => { const m = Math.max(Math.abs(mn), Math.abs(mx), 0.05) * 1.15; return [-m, m]; } },
      };
    }
    if (p.id === 'brk') {
      const lane = (v, lo, hi) => v.map(b => b > 5 ? lo + (hi - lo) * (state.lap === 'typical' ? b / 100 : 1) : lo);
      const st = uPlot.paths.stepped({ align: 1 });
      return {
        data: [X, lane(A.brk, 0.55, 1), lane(B.brk, 0, 0.45)],
        series: [{}, line(ca, { width: 0, fill: ca, fillTo: 0.55, paths: st }), line(cb, { width: 0, fill: cb, fillTo: 0, paths: st })],
        y: { range: [0, 1] }, axis: { values: u => [], grid: { show: false } },
      };
    }
    if (p.id === 'ers') {
      return {
        data: [X, S.dep, S.reg.map(v => -v)],
        series: [{}, line('#7cc4ff', { width: 1, fill: alpha('#7cc4ff', 0.35), fillTo: 0 }), line('#c084fc', { width: 1, fill: alpha('#c084fc', 0.35), fillTo: 0 })],
        y: { range: [-380, 380] },
      };
    }
    if (p.id === 'soc') return { data: [X, S.soc], series: [{}, line('#e6e6ea')], y: { range: (u, mn, mx) => [0, Math.max(0.5, mx * 1.12)] } };
    const step = p.id === 'gear' ? uPlot.paths.stepped({ align: 1 }) : undefined;
    const data = [X, B[p.key], A[p.key]];
    const ser = [{}, line(cb, step ? { paths: step } : {}), line(ca, step ? { paths: step } : {})];
    if (state.sim && p.sim && S) { data.push(S[p.sim]); ser.push(line('#8a8a92', { width: 1, dash: [4, 3] })); }
    const y = p.id === 'thr' ? { range: [-4, 104] } : p.id === 'gear' ? { range: [0.5, 8.5] } : {};
    const axis = p.id === 'gear' ? { splits: () => [2, 4, 6, 8] } : p.id === 'rpm' ? { values: (u, v) => v.map(t => t / 1000 + 'k') } : {};
    return { data, series: ser, y, axis };
  }

  function drawExtras(u, p) {
    const ctx = u.ctx, { left, top, width, height } = u.bbox, dpr = devicePixelRatio || 1;
    ctx.save();
    ctx.lineWidth = dpr;
    D.sectors.slice(1).forEach(sec => {
      const x = Math.round(u.valToPos(sec.x0, 'x', true)) + 0.5;
      if (x > left && x < left + width) { ctx.strokeStyle = 'rgba(255,255,255,0.13)'; ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, top + height); ctx.stroke(); }
    });
    if (state.ref != null) {
      const x = Math.round(u.valToPos(state.ref, 'x', true)) + 0.5;
      if (x >= left && x <= left + width) { ctx.strokeStyle = '#ff2a1f'; ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, top + height); ctx.stroke(); }
    }
    const note = p.delta ? [`${D.cars[state.a].last} ahead`, `${D.cars[state.b].last} ahead`] : p.id === 'ers' ? ['deploy', 'harvest'] : null;
    if (note) {
      ctx.fillStyle = '#6b6b6b'; ctx.font = `italic ${13.5 * dpr}px ${uiFont()}`;
      ctx.fillText(note[0] + ' ↑', left + 7 * dpr, top + 15 * dpr);
      ctx.fillText(note[1] + ' ↓', left + 7 * dpr, top + height - 7 * dpr);
    }
    ctx.restore();
  }

  function buildCharts() {
    Object.values(charts).forEach(u => u.destroy());
    for (const k in charts) delete charts[k];
    const [ca, cb] = [cache.ca, cache.cb];
    const shown = PANELS.filter(p => !p.simOnly || (state.sim && cache.S));
    PANELS.forEach(p => { rows[p.id].r.hidden = !shown.includes(p); });
    shown.forEach((p, k) => {
      const last = k === shown.length - 1;
      const cfg = series(p, ca, cb);
      let down = null;
      const u = new uPlot({
        width: W, height: p.h + (last ? 24 : 0), padding: [6, 0, 2, 0],
        cursor: {
          sync: { key: 'lap', setSeries: false }, drag: { x: true, y: false, setScale: false }, points: { show: false }, y: false,
          bind: { dblclick: () => () => { zoomTo(0, L); return null; } },
        },
        select: { show: true },
        legend: { show: false },
        scales: { x: { time: false, range: () => [state.x0, state.x1] }, y: cfg.y || {} },
        axes: [axisX(last), axisY(cfg.axis || {})],
        series: cfg.series,
        hooks: {
          setSelect: [v => {
            const w = v.select.width;
            if (w > 8) zoomTo(v.posToVal(v.select.left, 'x'), v.posToVal(v.select.left + w, 'x'));
            v.setSelect({ left: 0, width: 0, top: 0, height: 0 }, false);
          }],
          setCursor: [v => { const l = v.cursor.left; state.cur = l == null || l < 0 ? null : v.posToVal(l, 'x'); onCursor(); }],
          draw: [v => drawExtras(v, p)],
        },
      }, cfg.data, rows[p.id].pl);
      u.over.addEventListener('mousedown', e => { down = e.clientX; });
      u.over.addEventListener('click', e => {
        if (down == null || Math.abs(e.clientX - down) > 4) return;
        const x = u.posToVal(e.offsetX, 'x');
        state.ref = state.ref != null && Math.abs(u.valToPos(state.ref, 'x') - e.offsetX) < 6 ? null : x;
        lastCur = null; Object.values(charts).forEach(c => c.redraw(false)); drawMap(); onCursor(); drawWindow();
      });
      charts[p.id] = u;
      rows[p.id].lg.innerHTML = legendHtml(p, ca, cb);
    });
  }

  function legendHtml(p, ca, cb) {
    let v;
    if (p.delta) v = `<div class="lg-v"><b data-v="D">—</b></div><div class="lg-note">${esc(D.cars[state.b].last)} behind ${esc(D.cars[state.a].last)} if positive</div>`;
    else if (p.id === 'ers') v = `<div class="lg-v"><span><b data-v="E">—</b></span></div><div class="lg-note">model estimate, ${esc(D.cars[state.a].team)}</div>`;
    else if (p.id === 'soc') v = `<div class="lg-v"><span><b data-v="Q">—</b></span></div><div class="lg-note">model estimate, above the lap's low</div>`;
    else {
      v = `<div class="lg-v"><span><i style="background:${ca}"></i><b data-v="A">—</b></span><span><i style="background:${cb}"></i><b data-v="B">—</b></span>`;
      if (state.sim && p.sim && cache.S) v += `<span class="sim"><i></i><b data-v="S">—</b></span>`;
      v += '</div>';
    }
    return `<div class="lg-h">${p.name}${p.unit ? `<small>${p.unit}</small>` : ''}</div>${v}`;
  }

  // ---------- read-outs at the cursor ----------
  const nearCorner = x => D.corners.reduce((b, c) => Math.abs(c.x - x) < Math.abs(b.x - x) ? c : b, D.corners[0]);
  const sectorOf = x => D.sectors.find(s => x >= s.x0 && x < s.x1) || D.sectors[0];
  function onCursor() {
    const x = state.cur;
    const put = (R, k, txt) => { const el = R.querySelector(`[data-v="${k}"]`); if (el) el.textContent = txt; };
    const dot = $('#mapDot');
    if (x == null) {
      $$('#traces [data-v]').forEach(el => { el.textContent = el.dataset.v === 'XN' ? '' : '—'; });
      if (dot) dot.setAttribute('visibility', 'hidden');
      return;
    }
    const c = nearCorner(x), sec = sectorOf(x);
    put(stripe.lg, 'X', Math.round(x).toLocaleString('en-GB'));
    put(stripe.lg, 'XN', `Sector ${sec.k}` + (Math.abs(c.x - x) < 160 ? ` · Turn ${c.n}` : ''));
    PANELS.forEach(p => {
      const R = rows[p.id];
      if (R.r.hidden) return;
      const lg = R.lg;
      if (p.delta) { const d = at(cache.dt, x); put(lg, 'D', `${d > 0 ? '+' : d < 0 ? '−' : ''}${Math.abs(d).toFixed(3)} s`); }
      else if (p.id === 'brk') { const f = v => state.lap === 'typical' ? `${Math.round(v)}%` : (v > 50 ? 'On' : 'Off'); put(lg, 'A', f(at(cache.A.brk, x))); put(lg, 'B', f(at(cache.B.brk, x))); }
      else if (p.id === 'ers') { const dep = at(cache.S.dep, x), reg = at(cache.S.reg, x); put(lg, 'E', dep > 1 ? `+${dep.toFixed(0)} deploy` : reg > 1 ? `−${reg.toFixed(0)} harvest` : '0'); }
      else if (p.id === 'soc') put(lg, 'Q', at(cache.S.soc, x).toFixed(2));
      else {
        const i = Math.round(x / DX);
        put(lg, 'A', p.fmt(p.id === 'gear' ? cache.A.gear[i] : at(cache.A[p.key], x)));
        put(lg, 'B', p.fmt(p.id === 'gear' ? cache.B.gear[i] : at(cache.B[p.key], x)));
        if (cache.S && p.sim) put(lg, 'S', p.fmt(at(cache.S[p.sim], x)));
      }
    });
    if (dot) { const i = mapIndex(x); dot.setAttribute('cx', D.map.x[i]); dot.setAttribute('cy', D.map.y[i]); dot.setAttribute('visibility', 'visible'); }
    drawWindow();
  }

  // ---------- track map ----------
  const MX = D.map.x, MY = D.map.y, NM = MX.length;
  const mapIndex = x => Math.round((((x % L) + L) % L) / L * NM) % NM;
  const bx = [...MX, ...D.map.corners.map(c => c.lx)], by = [...MY, ...D.map.corners.map(c => c.ly)];
  const mx0 = Math.min(...bx), mx1 = Math.max(...bx), my0 = Math.min(...by), my1 = Math.max(...by);
  const mspan = Math.max(mx1 - mx0, my1 - my0), mpad = mspan * 0.05;
  const SW = mspan / 110;
  const subPath = (xa, xb) => {
    const ia = mapIndex(xa), ib = mapIndex(xb);
    const n = ((ib - ia + NM) % NM) || NM;
    let d = '';
    for (let k = 0; k <= n; k++) { const i = (ia + k) % NM; d += (k ? 'L' : 'M') + MX[i].toFixed(1) + ',' + MY[i].toFixed(1); }
    return d;
  };
  const fullPath = subPath(0, L - 1e-6) + 'Z';
  const mapEl = $('#map');
  mapEl.setAttribute('viewBox', `${(mx0 - mpad).toFixed(0)} ${(my0 - mpad).toFixed(0)} ${(mx1 - mx0 + 2 * mpad).toFixed(0)} ${(my1 - my0 + 2 * mpad).toFixed(0)}`);
  mapEl.classList.add('map');
  function drawMap() {
    const [ca, cb] = [cache.ca, cache.cb], A = D.cars[state.a], B = D.cars[state.b];
    let s = `<path class="base" d="${fullPath}" stroke-width="${(SW * 3.2).toFixed(1)}"/>`;
    if (state.x0 > 0 || state.x1 < L) s += `<path class="win" d="${subPath(state.x0, state.x1)}" stroke-width="${(SW * 5).toFixed(1)}" stroke-opacity=".2"/>`;
    let legend = '';
    if (state.map === 'gain') {
      const K = 25; let wa = 0, wb = 0;
      for (let k = 0; k < K; k++) {
        const xa = k * L / K, xb = (k + 1) * L / K;
        const diff = (tAt('B', xb) - tAt('B', xa)) - (tAt('A', xb) - tAt('A', xa));
        const col = Math.abs(diff) < 0.004 ? NEUTRAL : diff > 0 ? ca : cb;
        if (diff >= 0.004) wa++; else if (diff <= -0.004) wb++;
        const who = Math.abs(diff) < 0.004 ? 'Level' : `${diff > 0 ? A.last : B.last} faster by ${Math.abs(diff).toFixed(3)} s`;
        s += `<path class="seg-path" d="${subPath(xa, xb)}" stroke="${col}" stroke-width="${SW.toFixed(1)}" data-v="${esc(who)}" data-l="Mini-sector ${k + 1} of ${K} · ${Math.round(xa)}–${Math.round(xb)} m"/>`;
      }
      legend = `<span><i style="background:${ca}"></i>${esc(A.last)} faster in ${wa}</span><span><i style="background:${cb}"></i>${esc(B.last)} faster in ${wb}</span><span><i style="background:${NEUTRAL}"></i>level</span><span class="dim">of 25 mini-sectors</span>`;
    } else {
      D.sectors.forEach((sec, k) => { s += `<path class="seg-path" d="${subPath(sec.x0, sec.x1)}" stroke="${SEC[k]}" stroke-width="${SW.toFixed(1)}" data-v="Sector ${sec.k}" data-l="Turns ${sec.corners[0]}–${sec.corners[sec.corners.length - 1]}"/>`; });
      legend = D.sectors.map((sec, k) => `<span><i style="background:${SEC[k]}"></i>Sector ${sec.k}</span>`).join('');
    }
    const fs = (mspan / 32).toFixed(1);
    D.map.corners.forEach(c => { s += `<text class="cl" x="${c.lx.toFixed(1)}" y="${c.ly.toFixed(1)}" font-size="${fs}" data-zoom="${D.corners.find(k => k.n === c.number).x}">${esc(c.label)}</text>`; });
    const st = D.map.lines[0];
    s += `<line x1="${(st.x - SW * 3 * st.nx).toFixed(1)}" y1="${(st.y - SW * 3 * st.ny).toFixed(1)}" x2="${(st.x + SW * 3 * st.nx).toFixed(1)}" y2="${(st.y + SW * 3 * st.ny).toFixed(1)}" stroke="#fff" stroke-width="${(SW * 0.8).toFixed(1)}"/>`;
    if (state.ref != null) { const i = mapIndex(state.ref); s += `<circle class="rdot" cx="${MX[i]}" cy="${MY[i]}" r="${(SW * 1.9).toFixed(1)}" stroke-width="${(SW * 0.7).toFixed(1)}"/>`; }
    s += `<circle class="dot" id="mapDot" r="${(SW * 2.1).toFixed(1)}" stroke-width="${(SW * 0.8).toFixed(1)}" visibility="hidden"/>`;
    mapEl.innerHTML = s;
    $('#mapLegend').innerHTML = legend;
  }
  mapEl.addEventListener('pointermove', e => {
    const pt = mapEl.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
    const p = pt.matrixTransform(mapEl.getScreenCTM().inverse());
    let best = 0, bd = Infinity;
    for (let i = 0; i < NM; i++) { const d = (MX[i] - p.x) ** 2 + (MY[i] - p.y) ** 2; if (d < bd) { bd = d; best = i; } }
    if (Math.sqrt(bd) > mspan * 0.06) return;
    state.cur = best / NM * L; onCursor();
    const u = charts.v;
    if (u && state.cur >= state.x0 && state.cur <= state.x1) u.setCursor({ left: u.valToPos(state.cur, 'x'), top: 10 });
  });
  mapEl.addEventListener('pointerleave', () => { state.cur = null; onCursor(); });

  // ---------- lap summary ----------
  const fmtLap = t => `${Math.floor(t / 60)}:${(t % 60).toFixed(3).padStart(6, '0')}`;
  function drawSummary() {
    const A = D.cars[state.a], B = D.cars[state.b], la = lapOf(state.a), lb = lapOf(state.b);
    const typical = state.lap === 'typical';
    const cls = (car, v, k) => {
      if (typical) return '';
      const best = k == null ? D.best.lap : D.best.s[k], pb = k == null ? car.pb_lap : car.pb[k];
      return Math.abs(v - best) < 5e-4 ? 'pp' : pb != null && Math.abs(v - pb) < 5e-4 ? 'pg' : '';
    };
    const delta = (a, b, nd) => { const d = b - a; return `<td class="${d > 0 ? '' : 'neg'}">${d > 0 ? '+' : d < 0 ? '−' : ''}${Math.abs(d).toFixed(nd)}</td>`; };
    const share = (arr, f) => arr.filter(f).length / arr.length * 100;
    const sec = k => la.s[k] == null || lb.s[k] == null
      ? `<tr><td>Sector ${k + 1}</td><td>${la.s[k] == null ? '—' : la.s[k].toFixed(3)}</td><td>${lb.s[k] == null ? '—' : lb.s[k].toFixed(3)}</td><td>—</td></tr>`
      : `<tr><td>Sector ${k + 1}</td><td class="${cls(A, la.s[k], k)}">${la.s[k].toFixed(3)}</td><td class="${cls(B, lb.s[k], k)}">${lb.s[k].toFixed(3)}</td>${delta(la.s[k], lb.s[k], 3)}</tr>`;
    const topA = Math.max(...cache.A.v), topB = Math.max(...cache.B.v);
    const ftA = share(cache.A.thr, v => v >= 98), ftB = share(cache.B.thr, v => v >= 98);
    $('#summary').innerHTML = `<thead><tr><th></th><th><i class="sw" style="background:${cache.ca};margin-right:6px;vertical-align:middle"></i>${esc(A.last)}</th><th><i class="sw" style="background:${cache.cb};margin-right:6px;vertical-align:middle"></i>${esc(B.last)}</th><th>Δ</th></tr></thead><tbody>
      <tr><td>Lap</td><td class="${cls(A, la.time)}">${fmtLap(la.time)}</td><td class="${cls(B, lb.time)}">${fmtLap(lb.time)}</td>${delta(la.time, lb.time, 3)}</tr>
      ${sec(0)}${sec(1)}${sec(2)}
      ${la.st && lb.st ? `<tr><td>Speed trap, km/h</td><td>${la.st.toFixed(0)}</td><td>${lb.st.toFixed(0)}</td>${delta(la.st, lb.st, 0)}</tr>` : ''}
      <tr><td>Top speed, km/h</td><td>${topA}</td><td>${topB}</td>${delta(topA, topB, 0)}</tr>
      <tr><td>Full throttle, % of lap</td><td>${ftA.toFixed(0)}</td><td>${ftB.toFixed(0)}</td>${delta(ftA, ftB, 0)}</tr></tbody>`;
    $('#lapNote').textContent = typical ? `median of ${la.laps} and ${lb.laps} green laps` : `lap ${la.lap} and lap ${lb.lap}`;
    $('#sumLegend').hidden = typical;
    const note = $('#sumNote'), adjA = D.adjusted[state.a], adjB = D.adjusted[state.b];
    note.hidden = !typical;
    if (typical) {
      const g = adjA && adjB ? adjB[0] - adjA[0] : null;
      note.innerHTML = 'Raw medians, not adjusted for tyres, fuel or traffic.' + (g == null ? '' :
        ` With those taken out, ${esc(B.last)} was <b>${g >= 0 ? '+' : '−'}${Math.abs(g).toFixed(2)} ± ${Math.hypot(adjA[1], adjB[1]).toFixed(2)} s</b> a lap against ${esc(A.last)} (race pace).`);
    }
  }

  // ---------- the stretch between the reference cursor and the cursor ----------
  let lastCur = null;
  function drawWindow() {
    const el = $('#window');
    $('#clearRef').hidden = state.ref == null;
    if (state.ref == null) { el.className = 'dim'; el.innerHTML = 'Click the traces to drop a reference cursor (red); the stretch between it and the cursor is measured here.'; return; }
    if (state.cur != null) lastCur = state.cur;
    const other = lastCur ?? state.x1;
    const a = Math.min(state.ref, other), b = Math.max(state.ref, other);
    if (b - a < DX) { el.innerHTML = 'Move the cursor away from the reference cursor to measure a stretch.'; return; }
    const A = D.cars[state.a], B = D.cars[state.b];
    const ta = tAt('A', b) - tAt('A', a), tb = tAt('B', b) - tAt('B', a), d = tb - ta;
    const idx = []; for (let i = Math.ceil(a / DX); i <= Math.floor(b / DX); i++) idx.push(i);
    const minv = arr => Math.min(...idx.map(i => arr[i])), ft = arr => idx.filter(i => arr[i] >= 98).length / idx.length * 100;
    const who = Math.abs(d) < 0.0005 ? 'Level' : `${esc((d > 0 ? A : B).last)} faster by ${Math.abs(d).toFixed(3)} s`;
    el.className = '';
    el.innerHTML = `<div class="dim">${Math.round(a).toLocaleString('en-GB')}–${Math.round(b).toLocaleString('en-GB')} m · ${Math.round(b - a)} m</div><div class="big">${who}</div>
      <table><tr><td></td><td>${esc(A.last)}</td><td>${esc(B.last)}</td></tr>
      <tr><td>Time, s</td><td>${ta.toFixed(3)}</td><td>${tb.toFixed(3)}</td></tr>
      <tr><td>Average speed, km/h</td><td>${((b - a) / ta * 3.6).toFixed(1)}</td><td>${((b - a) / tb * 3.6).toFixed(1)}</td></tr>
      <tr><td>Lowest speed, km/h</td><td>${minv(cache.A.v)}</td><td>${minv(cache.B.v)}</td></tr>
      <tr><td>Full throttle, %</td><td>${ft(cache.A.thr).toFixed(0)}</td><td>${ft(cache.B.thr).toFixed(0)}</td></tr></table>`;
  }
  $('#clearRef').addEventListener('click', () => { state.ref = null; lastCur = null; Object.values(charts).forEach(c => c.redraw(false)); drawMap(); onCursor(); drawWindow(); });

  // ---------- zoom: every chart, the stripe and the map share one window ----------
  const zoomEl = $('#zoom');
  zoomEl.innerHTML = [['Lap', 0, L], ...D.sectors.map(s => [`S${s.k}`, s.x0, s.x1])].map(([n, a, b]) => `<button data-a="${a}" data-b="${b}">${n}</button>`).join('')
    + '<span class="sep"></span>' + D.corners.map(c => `<button data-zoom="${c.x}" title="Zoom to Turn ${c.n}">T${c.n}</button>`).join('');
  function zoomTo(a, b) {
    state.x0 = Math.max(0, a); state.x1 = Math.min(L, b);
    Object.values(charts).forEach(u => u.setScale('x', { min: state.x0, max: state.x1 }));
    drawStripe(); drawMap(); syncZoomButtons(); onCursor();
  }
  document.addEventListener('click', e => {
    const z = e.target.closest('[data-zoom]');
    if (z) { const x = +z.dataset.zoom; zoomTo(x - 280, x + 280); return; }
    const r = e.target.closest('[data-a]');
    if (r) { zoomTo(+r.dataset.a, +r.dataset.b); return; }
    const sec = e.target.closest('.stripe-sec');
    if (sec) { const s = D.sectors[+sec.dataset.k]; zoomTo(s.x0, s.x1); }
  });
  function syncZoomButtons() {
    $$('#zoom button').forEach(b => {
      const on = b.dataset.a != null ? Math.abs(+b.dataset.a - state.x0) < 1 && Math.abs(+b.dataset.b - state.x1) < 1
        : Math.abs(+b.dataset.zoom - 280 - state.x0) < 1;
      b.classList.toggle('on', on);
    });
  }

  // ---------- controls ----------
  $('#selA').addEventListener('change', e => { state.a = e.target.value; render(); });
  $('#selB').addEventListener('change', e => { state.b = e.target.value; render(); });
  $$('[data-lap]').forEach(b => b.addEventListener('click', () => { state.lap = b.dataset.lap; $$('[data-lap]').forEach(x => x.classList.toggle('on', x === b)); render(); }));
  $('#simOn').addEventListener('change', e => { state.sim = e.target.checked; render(); });
  function applyType() { document.documentElement.dataset.font = state.type; $('#selType').value = state.type; }
  $('#selType').addEventListener('change', e => {
    state.type = e.target.value; applyType(); writeHash();
    document.fonts.ready.then(() => { if (!$('#ws-lap').hidden) render(); });
  });
  $$('[data-map]').forEach(b => b.addEventListener('click', () => { state.map = b.dataset.map; $$('[data-map]').forEach(x => x.classList.toggle('on', x === b)); drawMap(); onCursor(); }));
  function showWs(ws) {
    state.ws = ws;
    $$('.ws-tabs button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.ws === ws)));
    $$('.ws').forEach(s => { s.hidden = s.id !== 'ws-' + ws; });
    if (ws === 'lap') render(); else writeHash();
  }
  $$('.ws-tabs button').forEach(b => b.addEventListener('click', () => showWs(b.dataset.ws)));

  // ---------- render ----------
  function render() {
    if ($('#ws-lap').hidden) return;
    W = Math.max(stripe.pl.clientWidth, 240);
    const [ca, cb] = colours();
    cache = { A: {}, B: {}, ca, cb };
    ['t', 'v', 'thr', 'brk', 'gear', 'rpm'].forEach(k => { cache.A[k] = chan(state.a, k); cache.B[k] = chan(state.b, k); });
    cache.dt = cache.B.t.map((t, i) => t - cache.A.t[i]);
    const sim = D.sims[D.cars[state.a].team];
    cache.S = sim ? Object.fromEntries(Object.entries(sim.ch).map(([k, a]) => [k, k === 't' ? a.map(v => v / 1000) : k === 'soc' ? a.map(v => v / 100) : a])) : null;
    $('#swA').style.background = ca; $('#swB').style.background = cb;
    drawStripe(); buildCharts(); drawMap(); drawSummary(); onCursor(); drawWindow(); syncZoomButtons(); writeHash();
  }
  let rt;
  addEventListener('resize', () => {
    clearTimeout(rt);
    rt = setTimeout(() => {
      if ($('#ws-lap').hidden) return;
      W = Math.max(stripe.pl.clientWidth, 240);
      PANELS.forEach((p, k) => { const u = charts[p.id]; if (u) u.setSize({ width: W, height: u.height }); });
      drawStripe();
    }, 120);
  });

  // ---------- tooltips for marks outside the traces ----------
  const tip = $('#tip');
  document.addEventListener('pointermove', e => {
    const el = e.target.closest && e.target.closest('[data-v][data-l]');
    if (!el || el.closest('#traces')) { tip.hidden = true; return; }
    tip.replaceChildren();
    const v = document.createElement('b'); v.textContent = el.dataset.v;
    const l = document.createElement('span'); l.textContent = el.dataset.l;
    tip.append(v, l); tip.hidden = false;
    const r = tip.getBoundingClientRect();
    let x = e.clientX + 14, y = e.clientY + 14;
    if (x + r.width > innerWidth - 8) x = e.clientX - r.width - 14;
    if (y + r.height > innerHeight - 8) y = e.clientY - r.height - 14;
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
  });

  readHash();
  applyType();
  $('#selA').value = state.a; $('#selB').value = state.b; $('#simOn').checked = state.sim;
  $$('[data-lap]').forEach(x => x.classList.toggle('on', x.dataset.lap === state.lap));
  showWs(state.ws);
  // the axes are drawn on canvas, so redraw once the web fonts have arrived
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { if (!$('#ws-lap').hidden) render(); });
})();

(() => {
  const D = JSON.parse(document.getElementById('data').textContent);
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const N = D.n, DX = D.dx, L = D.L;
  const SEC = ['#ef3b36', '#2fa4ff', '#ffd12e'];
  const NEUTRAL = '#55555e';
  const order = [...$('#selA').options].map(o => o.value);
  const state = { ws: 'lap', a: order[0], b: order[1], lap: 'fastest', sim: false, x0: 0, x1: L, cur: null, ref: null, map: 'gain' };

  // ---------- state in the URL, so a view can be shared ----------
  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    if (p.get('ws')) state.ws = p.get('ws');
    if (D.cars[p.get('a')]) state.a = p.get('a');
    if (D.cars[p.get('b')]) state.b = p.get('b');
    if (['fastest', 'typical'].includes(p.get('lap'))) state.lap = p.get('lap');
    state.sim = p.get('sim') === '1';
  }
  function writeHash() {
    const p = new URLSearchParams({ ws: state.ws, a: state.a, b: state.b, lap: state.lap, sim: state.sim ? '1' : '0' });
    history.replaceState(null, '', '#' + p.toString());
  }

  // ---------- colours: each car keeps its team colour everywhere; a clash falls back to white ----------
  const rgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
  const lum = h => {
    const c = rgb(h).map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  };
  const mix = (h, t) => '#' + rgb(h).map(v => Math.round(v + (255 - v) * t).toString(16).padStart(2, '0')).join('');
  const lift = h => { let c = h, t = 0; while (lum(c) < 0.17 && t < 0.6) { t += 0.08; c = mix(h, t); } return c; };
  const far = (a, b) => { const x = rgb(a), y = rgb(b); return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]); };
  function colours() {
    const A = D.cars[state.a], B = D.cars[state.b];
    const ca = lift(A.colour);
    let cb = lift(B.colour);
    if (A.team === B.team || far(ca, cb) < 110) cb = '#e6e6ea';
    return [ca, cb];
  }

  // ---------- data ----------
  const lapOf = c => D.cars[c][state.lap];
  const chan = (c, k) => { const a = lapOf(c).ch[k]; return k === 't' ? a.map(v => v / 1000) : k === 'rpm' ? a.map(v => v * 10) : a; };
  const at = (arr, x) => { const f = Math.min(Math.max(x / DX, 0), N - 1), i = Math.floor(f), j = Math.min(i + 1, N - 1); return arr[i] + (arr[j] - arr[i]) * (f - i); };
  const tAt = (side, x) => x >= L - 1e-6 ? lapOf(side === 'A' ? state.a : state.b).time : at(cache[side].t, x);
  let cache = {};

  // ---------- trace panels ----------
  const PANELS = [
    { id: 'v', name: 'Speed', unit: 'km/h', h: 150, key: 'v', auto: true, sim: 'v', fmt: v => v.toFixed(0) },
    { id: 'dt', name: 'Time gap', unit: 's', h: 104, delta: true },
    { id: 'thr', name: 'Throttle', unit: '%', h: 62, key: 'thr', lo: 0, hi: 100, sim: 'thr', fmt: v => v.toFixed(0) },
    { id: 'brk', name: 'Brake', unit: '', h: 40, key: 'brk', lanes: true },
    { id: 'gear', name: 'Gear', unit: '', h: 62, key: 'gear', lo: 1, hi: 8, step: true, fmt: v => v.toFixed(0) },
    { id: 'rpm', name: 'Engine speed', unit: 'rpm', h: 62, key: 'rpm', auto: true, fmt: v => (v / 1000).toFixed(1) + 'k' },
    { id: 'ers', name: 'ERS power', unit: 'kW · sim', h: 78, simOnly: true },
    { id: 'soc', name: 'Battery', unit: 'MJ · sim', h: 56, simOnly: true },
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
  const axis = row('axis');
  const overlay = document.createElement('div'); overlay.className = 'overlay';
  const cursor = document.createElement('div'); cursor.className = 'cursor'; cursor.hidden = true;
  const refc = document.createElement('div'); refc.className = 'refc'; refc.hidden = true;
  const brush = document.createElement('div'); brush.className = 'brush'; brush.hidden = true;
  overlay.append(cursor, refc, brush); traces.append(overlay);

  let W = 600;
  const span = () => state.x1 - state.x0;
  const sx = x => (x - state.x0) / span() * W;
  const visible = () => [Math.max(0, Math.floor(state.x0 / DX) - 1), Math.min(N - 1, Math.ceil(state.x1 / DX) + 1)];
  const nice = (lo, hi, n = 3) => {
    const raw = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw);
    const out = []; for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  };
  const path = (vals, sy, i0, i1, step) => {
    let d = '';
    for (let i = i0; i <= i1; i++) {
      const x = sx(i * DX).toFixed(1), y = sy(vals[i]).toFixed(1);
      if (!d) d = `M${x},${y}`; else if (step) d += `H${x}V${y}`; else d += `L${x},${y}`;
    }
    return d;
  };

  function drawStripe() {
    const h = 44;
    let s = `<svg height="${h}" viewBox="0 0 ${W} ${h}">`;
    D.sectors.forEach((sec, k) => {
      const a = Math.max(sx(sec.x0), 0), b = Math.min(sx(sec.x1), W);
      if (b <= a) return;
      s += `<rect class="stripe-sec" data-k="${k}" x="${a}" y="14" width="${b - a}" height="22" fill="transparent"/>`;
      s += `<rect x="${a}" y="19" width="${b - a}" height="2" fill="${SEC[k]}" pointer-events="none"/>`;
      if (b - a > 80) s += `<text class="stripe-lab" x="${a + 6}" y="35" fill="${SEC[k]}" style="fill:${SEC[k]}">S${sec.k}  T${sec.corners[0]}–${sec.corners[sec.corners.length - 1]}</text>`;
    });
    D.zones.forEach(([z0, z1]) => {
      (z1 > z0 ? [[z0, z1]] : [[z0, L], [0, z1]]).forEach(([a, b]) => {
        const p = Math.max(sx(a), 0), q = Math.min(sx(b), W);
        if (q > p) s += `<line x1="${p}" x2="${q}" y1="24.5" y2="24.5" stroke="#2ecc71" stroke-width="1" stroke-dasharray="3 2"><title>Straight-mode zone</title></line>`;
      });
    });
    D.corners.forEach(c => {
      const x = sx(c.x);
      if (x < -4 || x > W + 4) return;
      s += `<line x1="${x}" x2="${x}" y1="12" y2="19" stroke="#6b6b74"/>`;
      s += `<text class="corner-lab" data-zoom="${c.x}" x="${x}" y="9" text-anchor="middle">${c.n}</text>`;
    });
    stripe.pl.innerHTML = s + '</svg>';
    stripe.lg.innerHTML = `<div class="lg-h">Distance<small>m</small></div><div class="lg-v"><b data-v="X">—</b></div><div class="lg-note" data-v="XN"></div>`;
  }

  function drawPanel(p) {
    const R = rows[p.id];
    const show = !p.simOnly || (state.sim && cache.S);
    R.r.hidden = !show;
    if (!show) return;
    const [ca, cb] = [cache.ca, cache.cb];
    const h = p.h, pad = 7, [i0, i1] = visible();
    let lo, hi;
    if (p.delta) {
      let m = 0.05; for (let i = i0; i <= i1; i++) m = Math.max(m, Math.abs(cache.dt[i]));
      lo = -m * 1.15; hi = m * 1.15;
    } else if (p.id === 'ers') { lo = -380; hi = 380; }
    else if (p.id === 'soc') { let m = 0.5; for (let i = i0; i <= i1; i++) m = Math.max(m, cache.S.soc[i]); lo = 0; hi = m * 1.12; }
    else if (p.auto) {
      const arrs = [cache.A[p.key], cache.B[p.key]];
      if (state.sim && p.sim && cache.S) arrs.push(cache.S[p.sim]);
      let mn = Infinity, mx = -Infinity;
      arrs.forEach(a => { for (let i = i0; i <= i1; i++) { mn = Math.min(mn, a[i]); mx = Math.max(mx, a[i]); } });
      const pv = (mx - mn) * 0.08 || 1; lo = mn - pv; hi = mx + pv;
    } else { lo = p.lo; hi = p.hi; }
    const sy = v => pad + (1 - (v - lo) / (hi - lo)) * (h - 2 * pad);
    let s = `<svg height="${h}" viewBox="0 0 ${W} ${h}">`;
    if (!p.lanes) nice(lo, hi, p.id === 'gear' ? 3 : 3).forEach(t => {
      const y = sy(t).toFixed(1);
      s += `<line class="${t === 0 ? 'zero' : 'gridl'}" x1="0" x2="${W}" y1="${y}" y2="${y}"/>`;
      s += `<text class="tick" x="${W - 4}" y="${(+y - 3).toFixed(1)}" text-anchor="end">${p.id === 'rpm' ? (t / 1000) + 'k' : t}</text>`;
    });
    D.sectors.slice(1).forEach(sec => { const x = sx(sec.x0); if (x > 0 && x < W) s += `<line class="secline" x1="${x}" x2="${x}" y1="0" y2="${h}"/>`; });
    if (p.delta) {
      const z = sy(0), d = path(cache.dt, sy, i0, i1);
      const first = sx(i0 * DX).toFixed(1), last = sx(i1 * DX).toFixed(1);
      const area = `${d}L${last},${z}L${first},${z}Z`;
      s += `<defs><clipPath id="cpa"><rect x="0" y="0" width="${W}" height="${z}"/></clipPath><clipPath id="cpb"><rect x="0" y="${z}" width="${W}" height="${h}"/></clipPath></defs>`;
      s += `<path d="${area}" fill="${ca}" fill-opacity=".22" clip-path="url(#cpa)"/><path d="${area}" fill="${cb}" fill-opacity=".22" clip-path="url(#cpb)"/>`;
      s += `<path class="ln gap" d="${d}"/>`;
      s += `<text class="tick" x="6" y="${pad + 9}">${esc(D.cars[state.a].last)} ahead ↑</text><text class="tick" x="6" y="${h - pad - 2}">${esc(D.cars[state.b].last)} ahead ↓</text>`;
    } else if (p.lanes) {
      [['A', ca, pad, h / 2 - 2], ['B', cb, h / 2 + 2, h - pad]].forEach(([side, col, y0, y1]) => {
        const v = cache[side].brk;
        let i = i0;
        while (i <= i1) {
          if (v[i] > 5) {
            let j = i; while (j + 1 <= i1 && Math.abs(v[j + 1] - v[i]) < 15 && v[j + 1] > 5) j++;
            const a = sx(i * DX - DX / 2), b = sx(j * DX + DX / 2);
            s += `<rect x="${a.toFixed(1)}" y="${y0}" width="${Math.max(b - a, 1).toFixed(1)}" height="${y1 - y0}" fill="${col}" fill-opacity="${(0.25 + 0.75 * v[i] / 100).toFixed(2)}"/>`;
            i = j + 1;
          } else i++;
        }
      });
    } else if (p.id === 'ers') {
      const S = cache.S, z = sy(0);
      const dep = path(S.dep, sy, i0, i1), reg = path(S.reg.map(v => -v), sy, i0, i1);
      const first = sx(i0 * DX).toFixed(1), last = sx(i1 * DX).toFixed(1);
      s += `<path d="${dep}L${last},${z}L${first},${z}Z" fill="#7cc4ff" fill-opacity=".55"/><path d="${reg}L${last},${z}L${first},${z}Z" fill="#c084fc" fill-opacity=".55"/>`;
      s += `<line class="zero" x1="0" x2="${W}" y1="${z}" y2="${z}"/>`;
      s += `<text class="tick" x="6" y="${pad + 9}">deploy ↑</text><text class="tick" x="6" y="${h - pad - 2}">harvest ↓</text>`;
    } else if (p.id === 'soc') {
      s += `<path class="ln" stroke="#e6e6ea" d="${path(cache.S.soc, sy, i0, i1)}"/>`;
    } else {
      if (state.sim && p.sim && cache.S) s += `<path class="ln sim" d="${path(cache.S[p.sim], sy, i0, i1)}"/>`;
      s += `<path class="ln" stroke="${cb}" d="${path(cache.B[p.key], sy, i0, i1, p.step)}"/>`;
      s += `<path class="ln" stroke="${ca}" d="${path(cache.A[p.key], sy, i0, i1, p.step)}"/>`;
    }
    R.pl.innerHTML = s + '</svg>';
    let v = '';
    if (p.delta) v = `<div class="lg-v"><b data-v="D">—</b></div><div class="lg-note">${esc(D.cars[state.b].last)} behind ${esc(D.cars[state.a].last)} if positive</div>`;
    else if (p.id === 'ers') v = `<div class="lg-v"><span><b data-v="E">—</b></span></div><div class="lg-note">model estimate, ${esc(D.cars[state.a].team)}</div>`;
    else if (p.id === 'soc') v = `<div class="lg-v"><span><b data-v="Q">—</b></span></div><div class="lg-note">model estimate, charge above the lap's low</div>`;
    else {
      v = `<div class="lg-v"><span><i style="background:${ca}"></i><b data-v="A">—</b></span><span><i style="background:${cb}"></i><b data-v="B">—</b></span>`;
      if (state.sim && p.sim && cache.S) v += `<span class="sim"><i></i><b data-v="S">—</b></span>`;
      v += '</div>';
    }
    R.lg.innerHTML = `<div class="lg-h">${p.name}<small>${p.unit}</small></div>${v}`;
  }

  function drawAxis() {
    let s = `<svg height="22" viewBox="0 0 ${W} 22">`;
    nice(state.x0, state.x1, Math.max(3, Math.round(W / 110))).forEach(t => {
      const x = sx(t);
      if (x < 0 || x > W) return;
      s += `<line x1="${x}" x2="${x}" y1="0" y2="4" stroke="#3a3a42"/><text class="tick" x="${x}" y="15" text-anchor="middle">${t >= 1000 ? (t / 1000).toFixed(t % 1000 ? 1 : 0) + ' km' : t + ' m'}</text>`;
    });
    axis.pl.innerHTML = s + '</svg>';
    axis.lg.innerHTML = '';
  }

  function layout() {
    const first = rows.v.r, last = axis.r;
    overlay.style.left = stripe.pl.offsetLeft + 'px';
    overlay.style.top = first.offsetTop + 'px';
    overlay.style.height = (last.offsetTop - first.offsetTop) + 'px';
    overlay.style.width = W + 'px';
  }

  // ---------- cursor read-outs: every channel's value at the cursor, ATLAS-style ----------
  const nearCorner = x => D.corners.reduce((b, c) => Math.abs(c.x - x) < Math.abs(b.x - x) ? c : b, D.corners[0]);
  const sectorOf = x => D.sectors.find(s => x >= s.x0 && x < s.x1) || D.sectors[0];
  function setText(sel, txt) { $$(sel, traces).forEach(el => { el.textContent = txt; }); }
  function updateCursor() {
    const x = state.cur;
    cursor.hidden = x == null || x < state.x0 || x > state.x1;
    refc.hidden = state.ref == null || state.ref < state.x0 || state.ref > state.x1;
    if (state.ref != null) refc.style.left = sx(state.ref) + 'px';
    const dot = $('#mapDot');
    if (x == null) {
      ['[data-v="X"]', '[data-v="A"]', '[data-v="B"]', '[data-v="S"]', '[data-v="D"]', '[data-v="E"]', '[data-v="Q"]'].forEach(s => setText(s, '—'));
      setText('[data-v="XN"]', '');
      if (dot) dot.setAttribute('visibility', 'hidden');
      return;
    }
    cursor.style.left = sx(x) + 'px';
    const c = nearCorner(x), sec = sectorOf(x);
    setText('[data-v="X"]', Math.round(x).toLocaleString('en-GB'));
    setText('[data-v="XN"]', `S${sec.k}` + (Math.abs(c.x - x) < 160 ? ` · Turn ${c.n}` : ''));
    PANELS.forEach(p => {
      const R = rows[p.id];
      if (R.r.hidden) return;
      const put = (k, txt) => { const el = R.lg.querySelector(`[data-v="${k}"]`); if (el) el.textContent = txt; };
      if (p.delta) {
        const d = at(cache.dt, x);
        put('D', `${d > 0 ? '+' : d < 0 ? '−' : ''}${Math.abs(d).toFixed(3)} s`);
      } else if (p.id === 'brk') {
        const f = v => state.lap === 'typical' ? `${Math.round(v)}%` : (v > 50 ? 'on' : 'off');
        put('A', f(at(cache.A.brk, x))); put('B', f(at(cache.B.brk, x)));
      } else if (p.id === 'ers') {
        const dep = at(cache.S.dep, x), reg = at(cache.S.reg, x);
        put('E', dep > 1 ? `+${dep.toFixed(0)} deploy` : reg > 1 ? `−${reg.toFixed(0)} harvest` : '0');
      } else if (p.id === 'soc') put('Q', at(cache.S.soc, x).toFixed(2));
      else {
        const f = p.fmt;
        put('A', f(p.step ? cache.A[p.key][Math.round(x / DX)] : at(cache.A[p.key], x)));
        put('B', f(p.step ? cache.B[p.key][Math.round(x / DX)] : at(cache.B[p.key], x)));
        if (cache.S && p.sim) put('S', f(at(cache.S[p.sim], x)));
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
    if (state.x0 > 0 || state.x1 < L) s += `<path class="win" d="${subPath(state.x0, state.x1)}" stroke-width="${(SW * 5).toFixed(1)}" stroke-opacity=".22"/>`;
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
      legend = `<span><i style="background:${ca}"></i>${esc(A.last)} faster  ${wa}</span><span><i style="background:${cb}"></i>${esc(B.last)} faster  ${wb}</span><span><i style="background:${NEUTRAL}"></i>level</span><span class="dim">of 25 mini-sectors</span>`;
    } else {
      D.sectors.forEach((sec, k) => { s += `<path class="seg-path" d="${subPath(sec.x0, sec.x1)}" stroke="${SEC[k]}" stroke-width="${SW.toFixed(1)}" data-v="Sector ${sec.k}" data-l="Turns ${sec.corners[0]}–${sec.corners[sec.corners.length - 1]}"/>`; });
      legend = D.sectors.map((sec, k) => `<span><i style="background:${SEC[k]}"></i>S${sec.k}</span>`).join('');
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
    state.cur = best / NM * L; updateCursor();
  });
  mapEl.addEventListener('pointerleave', () => { state.cur = null; updateCursor(); });

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
    const delta = (a, b, nd, unit) => { const d = b - a; return `<td class="${d > 0 ? 'pos' : 'neg'}">${d > 0 ? '+' : d < 0 ? '−' : ''}${Math.abs(d).toFixed(nd)}${unit}</td>`; };
    const share = (arr, f) => arr.filter(f).length / arr.length * 100;
    const rowsHtml = [
      `<tr><td>Lap</td><td class="${cls(A, la.time)}">${fmtLap(la.time)}</td><td class="${cls(B, lb.time)}">${fmtLap(lb.time)}</td>${delta(la.time, lb.time, 3, '')}</tr>`,
      ...[0, 1, 2].map(k => la.s[k] == null || lb.s[k] == null
        ? `<tr><td>Sector ${k + 1}</td><td>${la.s[k] == null ? '—' : la.s[k].toFixed(3)}</td><td>${lb.s[k] == null ? '—' : lb.s[k].toFixed(3)}</td><td>—</td></tr>`
        : `<tr><td>Sector ${k + 1}</td><td class="${cls(A, la.s[k], k)}">${la.s[k].toFixed(3)}</td><td class="${cls(B, lb.s[k], k)}">${lb.s[k].toFixed(3)}</td>${delta(la.s[k], lb.s[k], 3, '')}</tr>`),
      la.st && lb.st ? `<tr><td>Speed trap, km/h</td><td>${la.st.toFixed(0)}</td><td>${lb.st.toFixed(0)}</td>${delta(la.st, lb.st, 0, '')}</tr>` : '',
      `<tr><td>Top speed, km/h</td><td>${Math.max(...cache.A.v)}</td><td>${Math.max(...cache.B.v)}</td>${delta(Math.max(...cache.A.v), Math.max(...cache.B.v), 0, '')}</tr>`,
      `<tr><td>Full throttle, % of lap</td><td>${share(cache.A.thr, v => v >= 98).toFixed(0)}</td><td>${share(cache.B.thr, v => v >= 98).toFixed(0)}</td>${delta(share(cache.A.thr, v => v >= 98), share(cache.B.thr, v => v >= 98), 0, '')}</tr>`,
    ].join('');
    $('#summary').innerHTML = `<thead><tr><th></th><th><i class="sw" style="background:${cache.ca};width:8px;height:8px;margin-right:5px"></i>${esc(A.last)}</th><th><i class="sw" style="background:${cache.cb};width:8px;height:8px;margin-right:5px"></i>${esc(B.last)}</th><th>Δ</th></tr></thead><tbody>${rowsHtml}</tbody>`;
    $('#lapNote').textContent = typical ? `median of ${la.laps} and ${lb.laps} green laps` : `lap ${la.lap} vs lap ${lb.lap}`;
    $('#sumLegend').hidden = typical;
    const note = $('#sumNote'), adjA = D.adjusted[state.a], adjB = D.adjusted[state.b];
    note.hidden = !typical;
    if (typical) {
      const g = adjA && adjB ? adjB[0] - adjA[0] : null;
      note.innerHTML = `Raw medians, not adjusted for tyres, fuel or traffic.` + (g == null ? '' :
        ` With those taken out, ${esc(B.last)} was <b>${g >= 0 ? '+' : '−'}${Math.abs(g).toFixed(2)} ± ${Math.hypot(adjA[1], adjB[1]).toFixed(2)} s</b> a lap against ${esc(A.last)} (Race pace).`);
    }
  }

  // ---------- the stretch between the reference cursor and the cursor ----------
  let lastCur = null;
  function drawWindow() {
    const el = $('#window');
    $('#clearRef').hidden = state.ref == null;
    if (state.ref == null) { el.innerHTML = 'Click the traces to drop a reference cursor <b style="color:var(--red2)">R</b>; the stretch between it and the cursor is analysed here.'; el.className = 'dim'; return; }
    if (state.cur != null) lastCur = state.cur;
    const other = lastCur ?? state.x1;
    const a = Math.min(state.ref, other), b = Math.max(state.ref, other);
    if (b - a < DX) { el.innerHTML = 'Move the cursor away from <b style="color:var(--red2)">R</b> to measure a stretch.'; return; }
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
  $('#clearRef').addEventListener('click', () => { state.ref = null; lastCur = null; drawMap(); updateCursor(); drawWindow(); });

  // ---------- zoom ----------
  const ZOOMS = [['Lap', 0, L], ...D.sectors.map(s => [`S${s.k}`, s.x0, s.x1])];
  const zoomEl = $('#zoom');
  zoomEl.innerHTML = ZOOMS.map(([n, a, b]) => `<button data-a="${a}" data-b="${b}">${n}</button>`).join('') + '<span class="sep"></span>' +
    D.corners.map(c => `<button data-zoom="${c.x}" title="Zoom to Turn ${c.n}">T${c.n}</button>`).join('');
  function zoomTo(a, b) { state.x0 = Math.max(0, a); state.x1 = Math.min(L, b); render(); }
  function zoomCorner(x) { zoomTo(x - 280, x + 280); }
  document.addEventListener('click', e => {
    const z = e.target.closest('[data-zoom]');
    if (z) { zoomCorner(+z.dataset.zoom); return; }
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

  // ---------- pointer: hover reads values, drag zooms, click drops the reference cursor ----------
  let drag = null;
  const xOf = px => state.x0 + px / W * span();
  overlay.addEventListener('pointerdown', e => { overlay.setPointerCapture(e.pointerId); drag = { px: e.offsetX, moved: false }; });
  overlay.addEventListener('pointermove', e => {
    if (drag && Math.abs(e.offsetX - drag.px) > 6) drag.moved = true;
    if (drag && drag.moved) { brush.hidden = false; brush.style.left = Math.min(e.offsetX, drag.px) + 'px'; brush.style.width = Math.abs(e.offsetX - drag.px) + 'px'; }
    state.cur = Math.min(Math.max(xOf(e.offsetX), 0), L - 1); updateCursor();
  });
  overlay.addEventListener('pointerup', e => {
    if (!drag) return;
    if (drag.moved) {
      const a = xOf(Math.min(e.offsetX, drag.px)), b = xOf(Math.max(e.offsetX, drag.px));
      if (b - a > 40) zoomTo(a, b);
    } else {
      const x = xOf(e.offsetX);
      state.ref = state.ref != null && Math.abs(sx(state.ref) - e.offsetX) < 6 ? null : x;
      lastCur = null; drawMap(); updateCursor(); drawWindow();
    }
    brush.hidden = true; drag = null;
  });
  overlay.addEventListener('dblclick', () => zoomTo(0, L));
  overlay.addEventListener('pointerleave', () => { if (!drag) { state.cur = null; updateCursor(); } });

  // ---------- controls ----------
  $('#selA').value = state.a; $('#selB').value = state.b;
  $('#selA').addEventListener('change', e => { state.a = e.target.value; render(); });
  $('#selB').addEventListener('change', e => { state.b = e.target.value; render(); });
  $$('[data-lap]').forEach(b => b.addEventListener('click', () => { state.lap = b.dataset.lap; $$('[data-lap]').forEach(x => x.classList.toggle('on', x === b)); render(); }));
  $$('[data-lap]').forEach(x => x.classList.toggle('on', x.dataset.lap === state.lap));
  $('#simOn').checked = state.sim;
  $('#simOn').addEventListener('change', e => { state.sim = e.target.checked; render(); });
  $$('[data-map]').forEach(b => b.addEventListener('click', () => { state.map = b.dataset.map; $$('[data-map]').forEach(x => x.classList.toggle('on', x === b)); drawMap(); updateCursor(); }));
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
    W = Math.max(stripe.pl.clientWidth, 200);
    const [ca, cb] = colours();
    cache = { A: {}, B: {}, ca, cb };
    ['t', 'v', 'thr', 'brk', 'gear', 'rpm'].forEach(k => { cache.A[k] = chan(state.a, k); cache.B[k] = chan(state.b, k); });
    cache.dt = cache.B.t.map((t, i) => t - cache.A.t[i]);
    const sim = D.sims[D.cars[state.a].team];
    cache.S = sim ? Object.fromEntries(Object.entries(sim.ch).map(([k, a]) => [k, k === 't' ? a.map(v => v / 1000) : k === 'soc' ? a.map(v => v / 100) : a])) : null;
    $('#swA').style.background = ca; $('#swB').style.background = cb;
    drawStripe(); PANELS.forEach(drawPanel); drawAxis(); layout(); drawMap(); drawSummary();
    updateCursor(); drawWindow(); syncZoomButtons(); writeHash();
  }
  let rt;
  addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(render, 120); });

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
  $('#selA').value = state.a; $('#selB').value = state.b; $('#simOn').checked = state.sim;
  $$('[data-lap]').forEach(x => x.classList.toggle('on', x.dataset.lap === state.lap));
  showWs(state.ws);
})();

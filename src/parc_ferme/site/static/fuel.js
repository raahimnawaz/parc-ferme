// The selection sets the fuel counter's origin. A lap zoom changes only the visible window.
function createFuelWorkspace(D, { axisX, axisY, line, lift, alpha }) {
  const el = id => document.getElementById(id);
  const ws = el('ws-state'), driver = el('s5-driver'), zoom = el('s5-lap'), strip = el('s5-stints');
  const kg = v => v == null ? '—' : v.toFixed(2) + ' kg';
  const gps = v => v == null ? '—' : v.toFixed(1) + ' g/s';
  const gText = v => v == null ? '—' : v.toFixed(2) + ' g';
  const interval = (a, digits, unit) => a ? a[1].toFixed(digits) + ' ' + unit + ' (' +
    a[0].toFixed(digits) + '–' + a[2].toFixed(digits) + ')' : '—';
  let first, last, scope, lapNumber, charts = [], drag = null;
  const laps = () => D.stateFit.drivers[driver.value] || [];
  function selectRange(lo, hi, name) {
    first = lo; last = hi; scope = name; lapNumber = null;
    draw();
  }
  function fullRace() {
    const rows = laps();
    if (rows.length) selectRange(1, rows.at(-1).lap, 'Full race');
  }
  function openLap(n) {
    if (n >= first && n <= last && laps().some(r => r.lap === n)) {
      lapNumber = n;
      draw();
    }
  }
  function positionBar(lo, hi, end) {
    const bar = strip.querySelector('.s5-selection-bar');
    bar.style.left = (lo-1)/end*100 + '%';
    bar.style.width = (hi-lo+1)/end*100 + '%';
  }
  function timeline(rows) {
    const end = rows.at(-1).lap, stints = [];
    for (const row of rows) {
      const prev = stints.at(-1);
      if (prev && prev.stint === row.stint) prev.last = row.lap;
      else stints.push({ stint: row.stint, compound: row.compound, first: prev ? prev.last+1 : 1, last: row.lap });
    }
    strip.replaceChildren();
    for (const stint of stints) {
      const name = stint.stint == null ? 'Recorded laps' : 'Stint ' + stint.stint;
      const btn = document.createElement('button');
      btn.textContent = name + (stint.compound ? ' · ' + stint.compound.toLowerCase() : '');
      btn.title = btn.textContent + ' · laps ' + stint.first + '–' + stint.last;
      btn.setAttribute('aria-label', btn.title);
      btn.setAttribute('aria-pressed', String(scope === name));
      btn.style.flexGrow = stint.last-stint.first+1;
      btn.onclick = () => selectRange(stint.first, stint.last, name);
      strip.append(btn);
    }
    const bar = document.createElement('i');
    bar.className = 's5-selection-bar'; strip.append(bar);
    positionBar(first, last, end);
  }
  function stripLap(x) {
    const box = strip.getBoundingClientRect(), end = laps().at(-1).lap;
    return Math.max(1, Math.min(end, 1 + Math.floor((x-box.left)/box.width*end)));
  }
  strip.onpointerdown = e => {
    if (e.button !== 0) return;
    drag = { x: e.clientX, start: stripLap(e.clientX), moved: false };
    e.target.setPointerCapture(e.pointerId);
  };
  strip.onpointermove = e => {
    if (!drag || Math.abs(e.clientX-drag.x) < 5 && !drag.moved) return;
    drag.moved = true;
    const n = stripLap(e.clientX);
    positionBar(Math.min(n, drag.start), Math.max(n, drag.start), laps().at(-1).lap);
  };
  strip.onpointercancel = () => { drag = null; positionBar(first, last, laps().at(-1).lap); };
  strip.onpointerup = e => {
    const d = drag; drag = null;
    if (d?.moved) {
      const n = stripLap(e.clientX);
      // The browser can also dispatch a click to the stint button after releasing the drag.
      const suppress = ev => ev.stopImmediatePropagation();
      strip.addEventListener('click', suppress, true);
      const lo = Math.min(n, d.start), hi = Math.max(n, d.start);
      selectRange(lo, hi, 'Selected laps');
      // A replaced pointer target can suppress that click altogether.
      setTimeout(() => strip.removeEventListener('click', suppress, true), 0);
    }
  };

  function profile(row) {
    if (!row.profile || !row.duration_ms) return null;
    const sec = row.duration_ms/1000, p = row.profile, used = [0];
    for (const mg of p.mg) used.push(used.at(-1) + mg/1e6);
    return { sec, used, missing: new Set(p.missing) };
  }
  function lapAt(p, time) {
    const i = Math.min(Math.max(0, Math.floor(time)), p.used.length-2);
    const width = Math.min(1, p.sec-i);
    const fraction = Math.min(1, Math.max(0, (time-i)/width));
    const delta = p.used[i+1] - p.used[i];
    return { used: p.used[i]+fraction*delta, rate: p.missing.has(i) ? null : 1000*delta/width };
  }
  function draw() {
    if (ws.hidden) return;
    const rows = laps();
    if (!rows.length) return;
    if (first == null) { fullRace(); return; }
    charts.forEach(u => u.destroy()); charts = [];
    const colour = lift(D.cars[driver.value]?.colour || '#9cbce0');
    ws.style.setProperty('--s5-team', colour);
    const selected = rows.filter(r => r.lap >= first && r.lap <= last);
    const byLap = new Map(selected.map(r => [r.lap, r]));
    const focused = byLap.get(lapNumber);
    const one = focused || (first === last ? byLap.get(first) : null);
    const end = rows.at(-1).lap, span = last-first+1;
    timeline(rows);
    const raceBtn = el('s5-race');
    raceBtn.classList.toggle('on', scope === 'Full race' && !focused);
    raceBtn.setAttribute('aria-pressed', String(scope === 'Full race' && !focused));
    zoom.replaceChildren(new Option('All selected laps', ''), ...selected.map(r => new Option('Lap ' + r.lap, r.lap)));
    zoom.value = focused ? focused.lap : '';
    const scopeText = scope + ' · laps ' + first + '–' + last;
    el('s5-selection').textContent = scopeText + ' of ' + end + (focused ? ' · viewing lap ' + focused.lap : '');
    el('s5-origin').textContent = 'From the start of lap ' + first;
    el('s5-rate-note').textContent = one ? 'One-second means · gaps indicate missing inputs' :
      'Lap means · click a trace to inspect a lap';
    const green = rows.filter(r => r.phase === 'green' && r.burn).map(r => r.burn[1]).sort((a,b) => a-b);
    const typical = green.length ? (green[Math.floor(green.length/2)]+green[Math.floor((green.length-1)/2)])/2 : null;
    el('s5-typical').textContent = typical == null ? '' : driver.value + ' typical green lap · ' + kg(typical);

    const before = new Map(), profiles = new Map();
    let total = 0, covered = 0, knownSeconds = 0, timedKg = 0;
    for (const r of selected) {
      before.set(r.lap, total);
      if (!r.burn) continue;
      covered++; total += r.burn[1];
      profiles.set(r.lap, profile(r));
      if (r.duration_ms) { knownSeconds += r.duration_ms/1000; timedKg += r.burn[1]; }
    }
    // At an unsupported lap, the subtotal still includes any earlier covered laps in the selection.
    const subtotal = r => before.get(r.lap) > 0 || selected.some(l => l.lap <= r.lap && l.burn) ? before.get(r.lap) : null;
    const partial = covered < span;
    const usedLabel = partial ? 'Fuel used on covered laps' : 'Fuel used so far';
    el('s5-used-label').textContent = usedLabel;
    el('s5-coverage').textContent = covered + ' of ' + span + ' laps with a fuel estimate';
    let lastTable = null;
    function table(r) {
      if (lastTable === r) return;
      lastTable = r;
      const tr = document.createElement('tr');
      const fields = r ? [r.lap + ' · ' + (r.status || r.phase), interval(r.burn, 2, 'kg'),
        interval(r.gain_ms, 1, 'ms'), r.start_gain_s == null ? '—' : r.start_gain_s.toFixed(3) + ' s'] :
        ['No recorded lap', '—', '—', '—'];
      fields.forEach((v,i) => { const td = tr.insertCell(); td.textContent = v; if (i) td.className = 'n'; });
      el('s5-lap-values').replaceChildren(tr);
    }
    function rest() {
      const r = one || selected.at(-1);
      el('s5-at').textContent = one ? 'End of lap ' + one.lap : scopeText;
      el('s5-used').textContent = kg(one ? (one.burn ? before.get(one.lap)+one.burn[1] : subtotal(one)) : (covered ? total : null));
      el('s5-rate-label').textContent = 'Mean burn rate';
      el('s5-rate').textContent = gps(one ? (one.burn && one.duration_ms ? 1e6*one.burn[1]/one.duration_ms : null) :
        (knownSeconds ? 1000*timedKg/knownSeconds : null));
      el('s5-lap-label').textContent = one ? 'Fuel this lap' : 'Typical green lap';
      el('s5-lap-used').textContent = one ? kg(one.burn?.[1]) :
        kg(typical);
      el('s5-g-label').textContent = 'Longitudinal G';
      el('s5-g').textContent = 'Hover trace';
      table(r);
    }
    rest();

    // Each plot uses elapsed seconds when inspecting one lap. On the overview lap N ends at x=N.
    const used = [[], []], rate = [[], []], acc = [[], [], [], []], bridges = [];
    function point(data, x, y) {
      if (data[0].at(-1) === x) data[1][data[1].length-1] = y;
      else { data[0].push(x); data[1].push(y); }
    }
    function bin(data, a, b, v) {
      point(data, a, v); point(data, b - Math.min(1e-7, (b-a)/2), v);
    }
    const seconds = r => r?.duration_ms/1000 || r?.trace?.ms.at(-1)/1000 || 1;
    const xOf = (r,t) => one ? t : r.lap-1 + t/seconds(r);
    for (let n = one?.lap ?? first; n <= (one?.lap ?? last); n++) {
      const r = byLap.get(n), p = profiles.get(n);
      const lo = one ? 0 : n-1, hi = one ? seconds(r) : n;
      if (r?.burn) {
        const base = before.get(n);
        if (p) {
          p.used.forEach((v,i) => point(used, xOf(r,Math.min(i,p.sec)), base+v));
        } else if (!one) {
          point(used, lo, base); point(used, hi, base+r.burn[1]);
        }
        if (one && p) {
          for (let i=0; i<p.used.length-1; i++) bin(rate, i, Math.min(i+1,p.sec), lapAt(p,i).rate);
        } else if (!one && r.duration_ms) bin(rate, lo, hi, 1000*r.burn[1]/seconds(r));
      } else { point(used, (lo+hi)/2, null); bin(rate, lo, hi, null); }
      if (!r?.trace) { acc[0].push((lo+hi)/2); acc.slice(1).forEach(a => a.push(null)); continue; }
      const tr = r.trace;
      tr.ms.forEach((ms,i) => {
        const g = tr.cg[i] == null ? null : tr.cg[i]/100;
        const rad = g == null ? 0 : D.stateFit.phases[g<0 ? 'deceleration' : 'acceleration'].radius_g;
        acc[0].push(xOf(r,ms/1000));
        acc[1].push(g == null ? null : g+rad); acc[2].push(g == null ? null : g-rad); acc[3].push(g);
      });
      for (const [i,j,control] of tr.bridges || []) {
        bridges.push({ x0:xOf(r,tr.ms[i]/1000), x1:xOf(r,tr.ms[j]/1000), g0:tr.cg[i]/100, g1:tr.cg[j]/100, control });
      }
    }
    const domain = one ? [0,seconds(one)] : [first-1,last];
    function inspect(x) {
      const n = one?.lap ?? Math.min(last, Math.max(first, Math.ceil(x)));
      const r = byLap.get(n);
      if (!r) { rest(); return; }
      const t = one ? x : (x-n+1)*seconds(r), p = profiles.get(n);
      const f = p ? lapAt(p,t) : null;
      const corner = r.corner_ms?.findIndex(v => Math.abs(v/1000-t) <= 1);
      el('s5-at').textContent = 'Lap ' + n + ' · ' + Math.max(0,t).toFixed(1) + ' s' +
        (corner >= 0 ? ' · T' + D.corners[corner].n : '');
      el('s5-used').textContent = kg(f ? before.get(n)+f.used : r.burn ? null : subtotal(r));
      el('s5-rate-label').textContent = one ? 'Burn rate · 1 s mean' : 'Burn rate · lap mean';
      el('s5-rate').textContent = gps(one ? f?.rate : (r.burn && r.duration_ms ? 1000*r.burn[1]/seconds(r) : null));
      el('s5-lap-label').textContent = 'Used this lap so far';
      el('s5-lap-used').textContent = kg(f?.used);
      const tr = r.trace, ms = t*1000;
      const gap = tr?.bridges?.find(([a,b]) => ms > tr.ms[a] && ms < tr.ms[b]);
      let g = null;
      if (gap) {
        const [i,j,control] = gap, q = (ms-tr.ms[i])/(tr.ms[j]-tr.ms[i]);
        g = curveG(tr.cg[i]/100, control, tr.cg[j]/100, q);
      }
      if (tr && !gap && ms >= tr.ms[0] && ms <= tr.ms.at(-1)) {
        const i = tr.ms.findIndex(v => v >= ms);
        const near = i>0 && ms-tr.ms[i-1] < tr.ms[i]-ms ? i-1 : i;
        if (tr.cg[near] != null && (tr.ms[i] === ms || (i > 0 && tr.cg[i-1] != null && tr.cg[i] != null)))
          g = tr.cg[near]/100;
      }
      el('s5-g-label').textContent = gap ? 'Estimated G · ' + ((tr.ms[gap[1]]-tr.ms[gap[0]])/1000).toFixed(2)+' s gap' :
        'Longitudinal G';
      el('s5-g').textContent = gText(g); table(r);
    }
    function plot(id, data, series, extra={}) {
      const target = el(id);
      target.replaceChildren();
      if (!data[1].some(v => v != null)) {
        target.textContent = id === 's5-accel-chart' ? 'Insufficient speed data.' : 'Fuel profile unavailable.';
        return;
      }
      const chart = new uPlot({
        width: Math.max(240,target.clientWidth), height: id === 's5-accel-chart' ? 148 : 125,
        padding: [10,0,0,14], scales: { x: {time:false,range:domain} }, legend:{show:false},
        cursor: {sync:{key:'fuel-workspace',setSeries:false}, y:false, drag:{x:false,y:false}, points:{show:false}},
        axes:[{...axisX(true),values:(_,xs) => xs.map(v => one ? v+' s' : Number.isInteger(v) && v>=first ? 'L'+v : '')},axisY()],
        series, ...extra,
      },data,target);
      const pos = e => Math.min(domain[1],Math.max(domain[0],chart.posToVal(e.clientX-chart.over.getBoundingClientRect().left,'x')));
      chart.over.onpointermove = e => inspect(pos(e));
      chart.over.onpointerleave = rest;
      if (!one) chart.over.onclick = e => openLap(Math.max(first,Math.ceil(pos(e))));
      charts.push(chart);
    }
    function marks(u, fuelChart) {
      const ctx = u.ctx, dpr = devicePixelRatio || 1;
      ctx.save();
      ctx.beginPath(); ctx.rect(u.bbox.left,u.bbox.top,u.bbox.width,u.bbox.height); ctx.clip();
      if (fuelChart && one?.corner_ms) {
        ctx.font = (10*dpr)+'px monospace'; ctx.fillStyle = '#888'; let previous = -Infinity;
        one.corner_ms.forEach((v,i) => {
          const x = u.valToPos(v/1000,'x',true), label = 'T'+D.corners[i].n;
          if (x-previous < 26*dpr) return;
          ctx.fillText(label,x,u.bbox.top+10*dpr); previous=x;
        });
      } else if (!fuelChart) {
        ctx.strokeStyle = alpha(colour,.72); ctx.lineWidth = 1.8*dpr; ctx.setLineDash([4*dpr,3*dpr]);
        for (const {x0,x1,g0,g1,control} of bridges) {
          const a = u.valToPos(x0,'x',true), b = u.valToPos(x1,'x',true);
          ctx.beginPath(); ctx.moveTo(a,u.valToPos(g0,'y',true));
          ctx.quadraticCurveTo((a+b)/2,u.valToPos(control,'y',true),b,u.valToPos(g1,'y',true));
          ctx.stroke();
        }
      }
      ctx.restore();
    }
    const stroke = line(colour,{width:1.5});
    plot('s5-fuel-chart',used,[{},stroke],{hooks:{draw:[u => marks(u,true)]}});
    plot('s5-rate-chart',rate,[{},stroke]);
    function curveG(g0, control, g1, q) {
      return (1-q)**2*g0 + 2*q*(1-q)*control + q*q*g1;
    }
    const peaks = [];
    for (const {g0,g1,control} of bridges) {
      const q = (g0-control)/(g0-2*control+g1);
      if (q > 0 && q < 1) peaks.push(curveG(g0,control,g1,q));
    }
    const gScale = peaks.length ? {range: (_, min, max) =>
      uPlot.rangeNum(Math.min(min,...peaks), Math.max(max,...peaks), .1, true)} : {};
    plot('s5-accel-chart',acc,[{},line('transparent'),line('transparent'),stroke],{
      scales:{x:{time:false,range:domain}, y:gScale},
      bands:[{series:[1,2],fill:alpha(colour,.17)}], hooks:{draw:[u => marks(u,false)]},
    });
  }
  driver.onchange = fullRace;
  el('s5-race').onclick = fullRace;
  zoom.onchange = () => { lapNumber = zoom.value ? Number(zoom.value) : null; draw(); };
  return draw;
}

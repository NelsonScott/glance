/* Glance dashboard — live data layer for the Claude Design shell.
   Fetches /all from the feed service and renders each tile using the
   design's existing CSS classes. Also owns scaling, clock, and intro. */
(() => {
  const qs = (s) => document.querySelector(s);
  const pad = (n) => String(n).padStart(2, '0');
  const cap = (s) => s ? s[0].toUpperCase() + s.slice(1) : s;

  /* ---------- scale stage to fit any screen ---------- */
  const stage = qs('#stage');
  function fit() {
    const w = innerWidth, h = innerHeight;
    if (!w || !h) return requestAnimationFrame(fit);
    stage.style.transform = `translate(-50%,-50%) scale(${Math.min(w / 1920, h / 1080)})`;
  }
  addEventListener('resize', fit); addEventListener('load', fit); fit();

  /* ---------- intro animation ---------- */
  const grid = qs('.grid');
  function intro() {
    if (grid.dataset.done) return; grid.dataset.done = '1';
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    grid.querySelectorAll('.tile').forEach(t => t.classList.add('intro'));
    requestAnimationFrame(() => requestAnimationFrame(() => grid.classList.add('ready')));
  }
  intro();

  /* ---------- clock / date / greeting ---------- */
  function tickClock() {
    const now = new Date();
    const t = now.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
    const [time, ap] = t.split(' ');
    qs('#clk-time').textContent = time;
    qs('#clk-ap').textContent = ap || '';
    const hr = now.getHours();
    qs('#greet').textContent = hr < 5 ? 'Late night' : hr < 12 ? 'Good morning'
      : hr < 17 ? 'Good afternoon' : hr < 21 ? 'Good evening' : 'Good night';
    qs('#date').textContent = now.toLocaleDateString('en-US', { weekday: 'long' }) + ' · ' +
      now.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
  }
  tickClock(); setInterval(tickClock, 1000);

  /* ---------- live cam: rotation + clickable dots ---------- */
  let CAMS = [];                         // filled from /cams: only streams that are live right now
  const CAM_ROTATE_MS = 15 * 60 * 1000;  // every 15 min
  const CAM_CHECK_MS = 15 * 60 * 1000;   // re-ask which cams are up
  let camIdx = 0, camTimer = null;
  function showCam(i) {
    const frame = qs('#cam-frame');
    if (!CAMS.length) {                  // nothing live: a calm tile, not a YouTube error
      frame.removeAttribute('src'); frame.style.display = 'none';
      qs('#cam-place').innerHTML = 'Cams offline<small>checking again in 15 min</small>';
      return;
    }
    frame.style.display = '';
    camIdx = (i + CAMS.length) % CAMS.length;
    const c = CAMS[camIdx];
    const src = `https://www.youtube.com/embed/${c.id}?autoplay=1&mute=1&playsinline=1&rel=0`;
    if (frame.getAttribute('src') !== src) frame.src = src;
    qs('#cam-place').innerHTML = `${c.label}<small>${c.sub}</small>`;
    document.querySelectorAll('#rotor-dots i').forEach((d, n) => d.classList.toggle('on', n === camIdx));
  }
  function resetCamTimer() { clearInterval(camTimer); camTimer = setInterval(() => showCam(camIdx + 1), CAM_ROTATE_MS); }
  async function loadCams() {
    let next = CAMS;
    try { next = (await (await fetch('/cams', { cache: 'no-store' })).json()).cams || []; } catch (e) { /* keep what we have */ }
    const current = CAMS[camIdx] && CAMS[camIdx].id;
    CAMS = next;
    qs('#rotor-dots').innerHTML = CAMS.map((c, n) =>
      `<i data-i="${n}" title="${c.label}" style="width:11px;height:11px;margin-left:7px;cursor:pointer"></i>`).join('');
    qs('#rotor-dots').querySelectorAll('i').forEach(d =>
      d.addEventListener('click', () => { showCam(+d.dataset.i); resetCamTimer(); }));
    const keep = CAMS.findIndex(c => c.id === current);   // stay on the same cam if it is still up
    showCam(keep >= 0 ? keep : 0);
  }
  loadCams().then(resetCamTimer); setInterval(loadCams, CAM_CHECK_MS);

  /* ---------- helpers ---------- */
  const fmtT = (hhmm) => { const [h, m] = (hhmm || '0:0').split(':').map(Number);
    return `${(h % 12) || 12}:${pad(m)}${h < 12 ? 'a' : 'p'}`; };
  const dayName = (d) => new Date(d + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short' });
  const splitAP = (s) => { const m = (s || '').match(/(\d+:\d+)\s*(am|pm|a|p)?/i);
    return m ? { n: m[1], ap: (m[2] || '').replace(/m$/i, '') } : { n: s || '', ap: '' }; };
  function wxIcon(c) {
    if (c <= 1) return { id: 'i-sun', color: 'var(--c-amber)' };
    if (c === 2) return { id: 'i-partly', color: 'var(--ink-dim)' };
    if (c === 3 || c === 45 || c === 48) return { id: 'i-cloud', color: 'var(--ink-dim)' };
    if (c >= 71 && c <= 77) return { id: 'i-cloud', color: 'var(--c-cyan)' };
    return { id: 'i-rain', color: 'var(--c-cyan)' };
  }
  const svg = (id) => `<svg class="icon" viewBox="0 0 24 24"><use href="#${id}"/></svg>`;

  /* ---------- renderers ---------- */
  function renderWeather(wx, aq) {
    if (!wx) return;
    const ic = wxIcon(wx.code);
    const stat = (icon, v, k) => `<div class="wx-stat">${svg(icon)}<div><div class="v">${v}</div><div class="k">${k}</div></div></div>`;
    const fc = (wx.forecast || []).slice(1, 4).map(   // today is already the big number; show the next three
      d => `<div class="fc"><span class="d">${dayName(d.date)}</span>` +
      `<svg class="icon" viewBox="0 0 24 24" style="color:${wxIcon(d.code).color}"><use href="#${wxIcon(d.code).id}"/></svg>` +
      `<div class="t"><span class="hi">${d.max}°</span><span class="lo">${d.min}°</span></div></div>`).join('');
    const aqi = aq ? aq.aqi : '–', aqcat = aq ? aq.category : '';
    qs('.wthr .wx-main').innerHTML = `
      <div class="wx-now">
        <div class="wx-cond"><svg class="icon" viewBox="0 0 24 24" style="color:${ic.color}"><use href="#${ic.id}"/></svg>
          <div class="wx-temp">${wx.temp}<span class="deg">°F</span></div></div>
        <div class="wx-desc">${wx.desc}</div>
        <div class="wx-feels">Feels like ${wx.feels}° · High ${wx.high}° / Low ${wx.low}°</div>
      </div>
      <div class="wx-fc">${fc}</div>`;
  }

  function renderNext(ne) {
    if (!ne) return;
    const e = ne.event;
    if (!e) { qs('.next .nu-event').innerHTML = '<div class="nu-title">Nothing scheduled</div>';
      qs('#nu-modes').innerHTML = ''; qs('#nu-eta').textContent = ''; return; }
    qs('#nu-when').textContent = e.when || '';
    qs('.next .nu-title').textContent = e.summary || '';
    qs('.next .nu-meta').textContent = /^\s*-?\d+[°.]/.test(e.location || '') ? '' : (e.location || '');   // raw coordinates are noise
    const mu = e.mins_until;
    qs('#nu-eta').textContent = mu == null ? '' : mu >= 60 ? `in ${Math.floor(mu / 60)}h ${mu % 60}m` : `in ${mu}m`;
    const modes = ne.modes || [];
    if (!modes.length) {
      qs('#nu-modes').innerHTML = `<div class="nu-meta" style="opacity:.6">${e.location ? 'no route found for this place' : 'no commute needed'}</div>`;
      return;
    }
    qs('#nu-modes').innerHTML = modes.map(m => {
      const cls = m.color === 'green' ? 'ok' : m.color === 'yellow' ? 'warn' : 'late';
      const icon = /train/i.test(m.mode) ? 'i-train' : /uber|car/i.test(m.mode) ? 'i-car' : 'i-bike';
      const name = m.mode.replace(/[^A-Za-z -]/g, '').trim();
      const lk = cls === 'ok' ? 'comfortable' : cls === 'warn' ? 'leave soon' : 'leave now';
      return `<div class="mode ${cls}">${svg(icon).replace('class="icon"', 'class="icon mi"')}` +
        `<span class="mname">${name}</span><span class="mride">${m.mins} min ride</span>` +
        `<span class="mleave"><span class="lv">leave ${m.leave_by}</span><span class="lk">${lk}</span></span></div>`;
    }).join('');
  }

  function renderL(lt) {
    if (!lt) return;
    const mins = lt.manhattan || [];
    qs('#l-next').textContent = mins[0] != null ? mins[0] : '–';
    qs('#l-rest').innerHTML = mins.slice(1, 4).map(m => `<span class="pill">${m}<small> min</small></span>`).join('');
  }

  function renderFerry(fe) {
    const fn = (fe && fe.north_williamsburg) || {};
    const sched = fn.scheduled || [], lastDest = fn.last_dest || {};
    const pick = (d) => sched.filter(s => s.dest === d).slice(0, 2).map(s => s.time).join('  ·  ');
    const row = (arrow, dest, times, last) => times
      ? `<div style="display:flex;align-items:baseline;gap:12px;padding:4px 0">
           <span style="min-width:96px;color:var(--c-cyan);font-weight:700;font-size:16px">${arrow} ${dest}</span>
           <span style="font-family:'JetBrains Mono',monospace;font-size:19px;font-weight:600;font-variant-numeric:tabular-nums">${times}</span>
           ${last ? `<span style="margin-left:auto;font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:0.06em;text-transform:uppercase;color:var(--ink-faint)">last <span style="font-size:14px;font-weight:700;color:var(--c-cyan)">${last}</span></span>` : ''}</div>`
      : '';
    qs('.ferr .fr-body').innerHTML =
      `<div style="display:flex;flex-direction:column;justify-content:center;flex:1">
         ${row('↓', 'Wall St', pick('Wall St'), lastDest['Wall St'])}
         ${row('↑', 'E 34 St', pick('E 34 St'), lastDest['E 34 St'])}
       </div>`;
  }

  function renderBike(cb) {
    const sts = (cb && cb.stations) || [];
    qs('.bike .cb-row').innerHTML = sts.map(s =>
      `<div class="cb-st"><div class="cb-name">${s.name}<small>${s.dist} mi</small></div>
        <div class="cb-counts">
          <div class="cb-c ${s.bikes <= 2 ? 'low' : ''}"><span class="n">${s.bikes}</span><span class="l">Bikes</span></div>
          <div class="cb-c ebk"><span class="n">${svg('i-bolt')}${s.ebikes}</span><span class="l">E-bikes</span></div>
          <div class="cb-c ${s.docks <= 5 ? 'low' : ''}"><span class="n">${s.docks}</span><span class="l">Docks</span></div>
        </div></div>`).join('');
  }

  function renderNitehawk(nh) {
    const films = ((nh && nh.films) || []).slice(0, 3);
    qs('.nite .rows').innerHTML = films.length ? films.map(f =>
      `<div class="row"><div class="title">${f.title}</div><div class="times">` +
      (f.showtimes || []).map(s => `<span${s.status === 'sold_out' ? ' style="opacity:.4;text-decoration:line-through"' : ''}>${s.time}</span>`).join('') +
      `</div></div>`).join('') : '<div class="row"><div class="title">No showtimes left today</div></div>';
  }

  function renderComedy(cm) {
    const rows = [];
    ((cm && cm.venues) || []).forEach(v => (v.shows || []).forEach(s => rows.push({ title: s.title, venue: v.venue, time: s.time })));
    qs('.cmdy .rows').innerHTML = rows.length ? rows.slice(0, 4).map(r =>
      `<div class="row"><div class="title">${r.title}<small>${r.venue}</small></div><div class="times"><span>${r.time}</span></div></div>`).join('')
      : '<div class="row"><div class="title">No shows tonight</div></div>';
  }

  const CAT = { game: '--c-blue', comedy: '--c-yellow', music: '--c-pink', theatre: '--c-violet', film: '--c-indigo', seasonal: '--c-green' };
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  function renderWeek(wk) {
    const picks = (wk && wk.picks) || [];
    qs('#wk-list').innerHTML = picks.length ? picks.map(p =>
      `<div class="wk${p.hot ? ' hot' : ''}" style="--cat:var(${CAT[p.category] || '--c-amber'})">` +
      `<div class="wk-when"><b>${esc(p.day)}</b><span>${esc(p.time)}</span></div>` +
      `<div class="wk-body"><div class="wk-title">${esc(p.title)}</div><div class="wk-sub"><b>${esc(p.venue)}</b> · ${esc(p.why)}</div></div>` +
      `<div class="wk-side">${p.price_from != null ? `<span class="wk-price">$${esc(p.price_from)}+</span>` : ''}` +
      `${p.tag ? `<span class="wk-tag">${esc(p.tag)}</span>` : ''}</div></div>`).join('')
      : '<div class="wk-empty">No picks yet this week</div>';
  }

  /* ---------- fetch loop ---------- */
  async function refresh() {
    try {
      const d = await (await fetch('/all', { cache: 'no-store' })).json();
      renderWeather(d.weather, d.airquality);
      renderNext(d.nextevent);
      renderL(d.ltrain);
      renderFerry(d.ferry);
      renderBike(d.citibike);
      renderNitehawk(d.nitehawk);
      renderComedy(d.comedy);
      renderWeek(d.picks);
    } catch (e) { console.warn('refresh failed', e); }
  }
  refresh();
  setInterval(refresh, 60000);

  /* ---------- Esc closes the window, only when the Vicinae launcher opened us (?kiosk=1) ---------- */
  // Kiosk Chrome ignores Esc/F11. window.close() is allowed here because the kiosk window
  // has a single history entry; a normal browser tab without ?kiosk=1 is left alone.
  if (new URLSearchParams(location.search).has('kiosk')) {
    addEventListener('keydown', (e) => { if (e.key === 'Escape') window.close(); });
  }
})();

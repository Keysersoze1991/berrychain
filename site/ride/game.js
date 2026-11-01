/* MTB Crazy: a side-on mountain-bike stunt racer. The page: drawing, input, menus, best times and the
   record board. The physics and the courses live in engine.js (window.MTB), shared with the referee. */
'use strict';
(function () {
  const { TICK, WR, FRAME, HEAD_UP, HEAD_R, BIT, TIERS, LEVELS, genLevel, newRun, frameUp, step, encodeLog } = window.MTB;
  // the record board on seed1 (berrychain/ride.py); nothing leaves this page until you claim a record
  const API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://localhost:8806' : 'https://seed1.berrychain.link';
  let records = [];
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  // ---------- rendering ----------
  const stage = document.getElementById('stage'), canvas = document.getElementById('game'), ctx = canvas.getContext('2d');
  let W = 960, H = 540, DPR = 1, zoom = 1;
  function resize() {
    const r = stage.getBoundingClientRect(); DPR = Math.min(2, window.devicePixelRatio || 1);
    W = Math.max(320, Math.round(r.width)); H = Math.max(180, Math.round(r.height));
    canvas.width = Math.round(W * DPR); canvas.height = Math.round(H * DPR);
    zoom = Math.max(0.55, Math.min(1.15, W / 960));
  }
  window.addEventListener('resize', resize); resize();

  // parallax scenery, fixed per level so it never flickers
  function scenery(seed) {
    let s = seed >>> 0; const rnd = () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
    const far = [], near = [], trees = [];
    for (let i = 0; i <= 40; i++) far.push({ x: i * 160, y: 120 + rnd() * 110 });
    for (let i = 0; i <= 60; i++) near.push({ x: i * 110, y: 200 + rnd() * 90 });
    for (let i = 0; i < 420; i++) trees.push({ x: rnd() * 16000, h: 26 + rnd() * 30, k: rnd() < 0.5 });
    return { far, near, trees, farW: 40 * 160, nearW: 60 * 110 };
  }
  const SCENES = LEVELS.map((_, i) => scenery(0xB3 + i * 7919));
  const PALETTES = [['#6fb7e6', '#bfe1f5', '#e8f3e4'], ['#5aa3d9', '#b7d9ee', '#e3efe0'], ['#4f8fc4', '#a9cfe6', '#dbe8dc'], ['#4a6e8f', '#8fb0c4', '#cfd8d2']];
  const cam = { x: 0, y: 0 };
  let penny = false; try { penny = localStorage.getItem('mtbcrazy.penny') === '1'; } catch (e) { }   // the look only: the physics are the same bike, so times stay comparable

  function draw(run, alpha) {
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    // sky
    const pal = PALETTES[run ? Math.floor(LEVELS.indexOf(run.level) / 5) : 0];
    const sky = ctx.createLinearGradient(0, 0, 0, H); sky.addColorStop(0, pal[0]); sky.addColorStop(0.65, pal[1]); sky.addColorStop(1, pal[2]);
    ctx.fillStyle = sky; ctx.fillRect(0, 0, W, H);
    if (!run) return;
    const lv = run.level, sc = SCENES[LEVELS.indexOf(lv)];
    const mx = (run.rear.x + run.front.x) / 2, my = (run.rear.y + run.front.y) / 2;
    const vx = ((run.rear.x - run.rear.px) + (run.front.x - run.front.px)) / 2;
    const tx = mx - (W / zoom) * 0.38 + vx * 10, ty = my - (H / zoom) * 0.58;
    if (cam.init !== lv) { cam.x = tx; cam.y = ty; cam.init = lv; }
    cam.x += (tx - cam.x) * 0.12; cam.y += (ty - cam.y) * 0.08;
    // mountains (parallax)
    ridge(sc.far, sc.farW, 0.25, '#9fc3dd', 0.35);
    ridge(sc.near, sc.nearW, 0.5, '#6f9a86', 0.55);
    ctx.save(); ctx.scale(zoom, zoom); ctx.translate(-cam.x, -cam.y);
    // trees behind the track
    if (sc.placed !== lv) { sc.placed = lv; sc.treeY = sc.trees.map(t => { const x = (t.x % (lv.length + 800)) - 300; return [x, groundY(lv, x)]; }); }
    const left = cam.x - 80, right = cam.x + W / zoom + 80;
    for (let i = 0; i < sc.trees.length; i++) { const [x, gy] = sc.treeY[i]; if (gy == null || x < left || x > right) continue; tree(x, gy, sc.trees[i].h, sc.trees[i].k); }
    // ground fill (non-loop points) and loops as ribbons
    for (const c of lv.chunks) {
      const g = c.filter(p => !p.l && !p.d); if (g.length < 2) continue;
      ctx.beginPath(); ctx.moveTo(g[0].x, g[0].y); for (const p of g) ctx.lineTo(p.x, p.y);
      ctx.lineTo(g[g.length - 1].x, lv.deathY + 600); ctx.lineTo(g[0].x, lv.deathY + 600); ctx.closePath();
      ctx.fillStyle = '#7a5a3c'; ctx.fill();
      ctx.beginPath(); ctx.moveTo(g[0].x, g[0].y); for (const p of g) ctx.lineTo(p.x, p.y);
      ctx.lineWidth = 7; ctx.strokeStyle = '#4f9a4a'; ctx.lineJoin = 'round'; ctx.stroke();
      ctx.lineWidth = 2; ctx.strokeStyle = '#a3d37a'; ctx.stroke();
      // loops
      let i = 0; while (i < c.length) { if (!c[i].l && !c[i].d) { i++; continue; } let j = i; while (j < c.length && (c[j].l || c[j].d)) j++; const s = Math.max(0, i - 1), e = Math.min(c.length - 1, j);
        ctx.beginPath(); ctx.moveTo(c[s].x, c[s].y); for (let k = s + 1; k <= e; k++) ctx.lineTo(c[k].x, c[k].y);
        ctx.lineWidth = 12; ctx.strokeStyle = '#8a6a48'; ctx.lineCap = 'round'; ctx.stroke(); ctx.lineWidth = 4; ctx.strokeStyle = '#d9b27a'; ctx.stroke(); i = j; }
    }
    // checkpoints and finish
    for (let i = 1; i < lv.checkpoints.length; i++) flag(lv.checkpoints[i].x, lv.checkpoints[i].y, '#f0c453', i <= run.cpIndex);
    flag(lv.finishX, groundY(lv, lv.finishX) ?? 0, '#c2382b', run.finished, true);
    // start gate
    ctx.strokeStyle = '#8a6a48'; ctx.lineWidth = 6; ctx.beginPath(); ctx.moveTo(190, 0); ctx.lineTo(190, -110); ctx.lineTo(330, -110); ctx.lineTo(330, 0); ctx.stroke();
    ctx.fillStyle = '#f6f0e3'; ctx.font = '700 22px Fraunces, Georgia, serif'; ctx.textAlign = 'center'; ctx.fillText('MTB CRAZY', 260, -118);
    // bike
    bike(run);
    ctx.restore();
    if (run.toast && run.toast.t > 0) {
      const a = Math.min(1, run.toast.t / 20); ctx.globalAlpha = a; ctx.fillStyle = run.toast.text === 'Crash!' ? '#c2382b' : '#f0c453';
      ctx.font = '700 ' + Math.round(34 * zoom + 10) + 'px Fraunces, Georgia, serif'; ctx.textAlign = 'center'; ctx.lineWidth = 4; ctx.strokeStyle = 'rgba(12,31,51,.6)';
      ctx.strokeText(run.toast.text, W / 2, H * 0.3); ctx.fillText(run.toast.text, W / 2, H * 0.3); ctx.globalAlpha = 1; run.toast.t--;
    }
    // crash flash
    if (run.flash > 0) { ctx.fillStyle = 'rgba(194,56,43,' + (run.flash / 12 * 0.35) + ')'; ctx.fillRect(0, 0, W, H); run.flash--; }
  }
  function ridge(pts, width, par, colour, yfrac) {
    const off = (cam.x * zoom * par) % width; const base = H * yfrac + (-cam.y * zoom * par * 0.15);
    ctx.fillStyle = colour; ctx.beginPath(); ctx.moveTo(-10, H + 10);
    for (let rep = -1; rep <= Math.ceil(W / width) + 1; rep++) for (const p of pts) ctx.lineTo(p.x + rep * width - off, base + (p.y - 200) * 0.9);
    ctx.lineTo(W + 10, H + 10); ctx.closePath(); ctx.fill();
  }
  function groundY(lv, x) {
    for (const c of lv.chunks) { const g = c.filter(p => !p.l && !p.d); for (let i = 1; i < g.length; i++) { if (x >= g[i - 1].x && x <= g[i].x) { const t = (x - g[i - 1].x) / ((g[i].x - g[i - 1].x) || 1); return g[i - 1].y + (g[i].y - g[i - 1].y) * t; } } }
    return null;
  }
  function tree(x, gy, h, conifer) {
    ctx.fillStyle = '#5b4330'; ctx.fillRect(x - 2, gy - h * 0.4, 4, h * 0.4);
    ctx.fillStyle = conifer ? '#2f6b3f' : '#4a8f52';
    if (conifer) { ctx.beginPath(); ctx.moveTo(x, gy - h); ctx.lineTo(x - h * 0.32, gy - h * 0.3); ctx.lineTo(x + h * 0.32, gy - h * 0.3); ctx.closePath(); ctx.fill(); }
    else { ctx.beginPath(); ctx.arc(x, gy - h * 0.62, h * 0.32, 0, Math.PI * 2); ctx.fill(); }
  }
  function flag(x, y, colour, taken, big) {
    ctx.strokeStyle = '#3b2a1a'; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x, y - (big ? 96 : 64)); ctx.stroke();
    ctx.fillStyle = taken ? '#4f9a4a' : colour; ctx.beginPath(); ctx.moveTo(x, y - (big ? 96 : 64)); ctx.lineTo(x + (big ? 42 : 30), y - (big ? 82 : 55)); ctx.lineTo(x, y - (big ? 68 : 46)); ctx.closePath(); ctx.fill();
    if (big) { ctx.fillStyle = '#f6f0e3'; for (let i = 0; i < 3; i++) for (let j = 0; j < 2; j++) if ((i + j) % 2 === 0) ctx.fillRect(x + 6 + i * 10, y - 92 + j * 8 + i * 3, 8, 7); }
  }
  function wheelAt(x, y, rad, spin) {
    ctx.save(); ctx.translate(x, y); ctx.rotate(spin);
    ctx.lineWidth = rad > 20 ? 5 : 4; ctx.strokeStyle = '#1b2430'; ctx.beginPath(); ctx.arc(0, 0, rad, 0, Math.PI * 2); ctx.stroke();
    ctx.lineWidth = 1.5; ctx.strokeStyle = '#c9c9c9'; const n = rad > 20 ? 12 : 6; for (let i = 0; i < n; i++) { const a = i * Math.PI * 2 / n; ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(Math.cos(a) * (rad - 2), Math.sin(a) * (rad - 2)); ctx.stroke(); }
    ctx.fillStyle = '#5a5a5a'; ctx.beginPath(); ctx.arc(0, 0, 3, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
  }
  function jollyRoger(x0, y0, x1, y1) {   // a pole from (x0,y0) to (x1,y1) with the flag at the top, in bike space (y up)
    ctx.strokeStyle = '#1b2430'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
    ctx.fillStyle = '#1b2430'; ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x1 - 20, y1 - 6); ctx.lineTo(x1, y1 - 12); ctx.closePath(); ctx.fill();
    ctx.fillStyle = '#f6f0e3'; ctx.beginPath(); ctx.arc(x1 - 9, y1 - 6, 2.2, 0, Math.PI * 2); ctx.fill(); ctx.fillRect(x1 - 13, y1 - 9.5, 8, 1); ctx.fillRect(x1 - 9.5, y1 - 12, 1, 6);
  }
  function pirateRider(hipX, hipY, shX, shY, kneeX, kneeY, pedX, pedY, elbX, elbY, barX, barY) {   // bike space, y up
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.strokeStyle = '#f6f0e3'; ctx.lineWidth = 7; ctx.beginPath(); ctx.moveTo(hipX, hipY); ctx.lineTo(shX, shY); ctx.stroke();                                   // shirt
    ctx.strokeStyle = '#c2382b'; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(hipX, hipY); ctx.lineTo(shX, shY); ctx.stroke(); ctx.setLineDash([]);         // stripes
    ctx.strokeStyle = '#2b5a8a'; ctx.lineWidth = 5.5; ctx.beginPath(); ctx.moveTo(hipX, hipY); ctx.lineTo(kneeX, kneeY); ctx.lineTo(pedX, pedY); ctx.stroke();      // leg
    ctx.strokeStyle = '#e8c9a0'; ctx.lineWidth = 4.5; ctx.beginPath(); ctx.moveTo(shX, shY); ctx.lineTo(elbX, elbY); ctx.lineTo(barX, barY); ctx.stroke();          // arm
    const hx = shX + 3, hy = shY + 11;
    ctx.fillStyle = '#e8c9a0'; ctx.beginPath(); ctx.arc(hx, hy, 7, 0, Math.PI * 2); ctx.fill();                                                                     // face
    ctx.fillStyle = '#1b2430'; ctx.beginPath(); ctx.moveTo(hx - 13, hy + 4); ctx.lineTo(hx + 14, hy + 4); ctx.lineTo(hx + 9, hy + 13); ctx.lineTo(hx - 9, hy + 13); ctx.closePath(); ctx.fill(); // tricorn
    ctx.strokeStyle = '#f0c453'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(hx - 12, hy + 5); ctx.lineTo(hx + 13, hy + 5); ctx.stroke();                     // gold trim
    ctx.fillStyle = '#f6f0e3'; ctx.beginPath(); ctx.arc(hx + 1, hy + 9, 2, 0, Math.PI * 2); ctx.fill();                                                           // skull on the hat
    ctx.fillStyle = '#1b2430'; ctx.beginPath(); ctx.arc(hx + 4, hy + 1, 2.4, 0, Math.PI * 2); ctx.fill();                                                         // eyepatch
    ctx.strokeStyle = '#1b2430'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(hx - 7, hy + 3); ctx.lineTo(hx + 7, hy - 1); ctx.stroke();                         // its strap
  }
  function bike(run) {
    const r = run.rear, fw = run.front, f = frameUp(run);
    if (run.crashed) { ctx.globalAlpha = 0.45; }
    const lean = (run.lastMask & BIT.FWD ? 1 : 0) - (run.lastMask & BIT.BACK ? 1 : 0);
    ctx.save(); ctx.translate(r.x, r.y); ctx.transform(f.ux, f.uy, f.upx, f.upy, 0, 0); // x along the frame, y up; wheels touch the ground at y = -WR
    if (penny) {
      // penny-farthing: a small trailing wheel and a tall front wheel, both still touching where the real wheels do
      const BR = 27, SR = 8;
      wheelAt(0, SR - WR, SR, r.spin); wheelAt(FRAME, BR - WR, BR, fw.spin * WR / BR);
      ctx.lineWidth = 4.5; ctx.strokeStyle = '#1b2430'; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      ctx.beginPath(); ctx.moveTo(0, SR - WR); ctx.quadraticCurveTo(FRAME - 34, 30, FRAME - 6, 46); ctx.lineTo(FRAME, BR - WR); ctx.stroke();       // backbone and fork
      ctx.lineWidth = 1.5; ctx.strokeStyle = '#f0c453'; ctx.beginPath(); ctx.moveTo(0, SR - WR); ctx.quadraticCurveTo(FRAME - 34, 30, FRAME - 6, 46); ctx.stroke();
      ctx.strokeStyle = '#1b2430'; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(FRAME - 6, 46); ctx.lineTo(FRAME + 4, 48); ctx.lineTo(FRAME + 14, 46); ctx.stroke();   // bars
      ctx.beginPath(); ctx.moveTo(FRAME - 14, 46); ctx.lineTo(FRAME - 2, 48); ctx.stroke();                                                                           // saddle
      ctx.fillStyle = '#1b2430'; ctx.beginPath(); ctx.arc(FRAME, BR - WR, 4, 0, Math.PI * 2); ctx.fill();                                                              // crank on the big hub
      jollyRoger(FRAME - 14, 46, FRAME - 24, 70);
      const hipX = FRAME - 10 - lean * 3, hipY = 50, shX = FRAME - 1 + lean * 5, shY = 74;
      pirateRider(hipX, hipY, shX, shY, FRAME - 4, 30, FRAME + Math.cos(fw.spin * WR / BR) * 9, BR - WR + Math.sin(fw.spin * WR / BR) * 9, FRAME + 10, 58, FRAME + 12, 47);
    } else {
      wheelAt(0, 0, WR, r.spin); wheelAt(FRAME, 0, WR, fw.spin);
      ctx.lineWidth = 4.5; ctx.strokeStyle = '#1b2430'; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(22, 26); ctx.lineTo(44, 30); ctx.lineTo(FRAME, 0); ctx.moveTo(22, 26); ctx.lineTo(30, 4); ctx.lineTo(44, 30); ctx.moveTo(30, 4); ctx.lineTo(0, 0); ctx.stroke();
      ctx.lineWidth = 1.5; ctx.strokeStyle = '#f0c453'; ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(22, 26); ctx.lineTo(44, 30); ctx.lineTo(FRAME, 0); ctx.stroke();   // gold pinstripe
      jollyRoger(18, 36, 14, 62);
      ctx.strokeStyle = '#1b2430'; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(44, 30); ctx.lineTo(48, 42); ctx.lineTo(56, 42); ctx.stroke(); // bars
      ctx.beginPath(); ctx.moveTo(22, 26); ctx.lineTo(16, 34); ctx.lineTo(24, 36); ctx.stroke(); // saddle post
      ctx.fillStyle = '#1b2430'; ctx.beginPath(); ctx.arc(30, 4, 4, 0, Math.PI * 2); ctx.fill(); // crank
      const hipX = 18 - lean * 4, hipY = 36, shX = 36 + lean * 5, shY = 62;
      pirateRider(hipX, hipY, shX, shY, 26, 14, 30 + Math.cos(r.spin) * 7, 4 + Math.sin(r.spin) * 7, 50, 48, 55, 43);
    }
    ctx.restore(); ctx.globalAlpha = 1;
  }

  // ---------- input ----------
  let held = 0;
  const KEYS = { ArrowUp: BIT.PEDAL, KeyW: BIT.PEDAL, ArrowDown: BIT.BRAKE, KeyS: BIT.BRAKE, ArrowLeft: BIT.BACK, KeyA: BIT.BACK, ArrowRight: BIT.FWD, KeyD: BIT.FWD, ShiftLeft: BIT.SPRINT, ShiftRight: BIT.SPRINT, Space: BIT.SPRINT };
  window.addEventListener('keydown', e => {
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;   // typing a record claim
    if (e.code in KEYS) { held |= KEYS[e.code]; e.preventDefault(); }
    if (e.code === 'KeyR' && run && !run.finished) startLevel(LEVELS.indexOf(run.level));
    if (e.code === 'Escape') showMenu();
    if ((e.code === 'Enter' || e.code === 'Space') && !document.getElementById('panel-done').hidden) next();
  });
  window.addEventListener('keyup', e => { if (e.code in KEYS) held &= ~KEYS[e.code]; });
  window.addEventListener('blur', () => { held = 0; });
  const touch = document.getElementById('touch');
  for (const b of touch.querySelectorAll('.tbtn')) {
    const bit = +b.dataset.bit;
    const down = e => { e.preventDefault(); held |= bit; b.classList.add('down'); };
    const up = e => { e.preventDefault(); held &= ~bit; b.classList.remove('down'); };
    b.addEventListener('pointerdown', down); b.addEventListener('pointerup', up); b.addEventListener('pointercancel', up); b.addEventListener('pointerleave', up);
  }
  if (window.matchMedia('(pointer: coarse)').matches) touch.hidden = false;

  // ---------- game flow ----------
  let run = null, acc = 0, last = 0, raf = 0;
  const $ = id => document.getElementById(id);
  const fmt = t => (t / 60).toFixed(2) + 's';
  const bestKey = i => 'mtbcrazy.best.' + i;
  const getBest = i => { try { const v = localStorage.getItem(bestKey(i)); return v ? +v : null; } catch (e) { return null; } };
  const setBest = (i, t) => { try { localStorage.setItem(bestKey(i), String(t)); } catch (e) { } };

  const pennyBox = $('penny'); pennyBox.checked = penny;
  pennyBox.addEventListener('change', () => { penny = pennyBox.checked; try { localStorage.setItem('mtbcrazy.penny', penny ? '1' : '0'); } catch (e) { } });
  function buildMenu() {
    const box = $('levels'); box.innerHTML = '';
    LEVELS.forEach((lv, i) => {
      if (i % 5 === 0) { const h = document.createElement('div'); h.className = 'tier'; h.textContent = TIERS[i / 5]; box.appendChild(h); }
      const b = document.createElement('button'); const best = getBest(i); const rec = records[i]; b.innerHTML = (i + 1) + '. ' + esc(lv.name) + '<small>' + (best != null ? 'best ' + fmt(best) : lv.blurb) + (rec && rec.name ? ' · record ' + fmt(rec.time) + ' ' + esc(rec.name) + (rec.named ? ' \u2726' : '') : '') + '</small>'; b.title = lv.blurb; b.addEventListener('click', () => startLevel(i)); box.appendChild(b);
    });
  }
  function showMenu() { run = null; cancelAnimationFrame(raf); buildMenu(); $('panel-title').hidden = false; $('panel-done').hidden = true; $('hud').hidden = true; draw(null); }
  function startLevel(i) {
    run = newRun(LEVELS[i]); run.lastMask = 0; acc = 0; last = performance.now(); held &= ~0;
    $('panel-title').hidden = true; $('panel-done').hidden = true; $('hud').hidden = false; $('hud-level').textContent = (i + 1) + ' · ' + LEVELS[i].name;
    stage.focus({ preventScroll: true }); cancelAnimationFrame(raf); raf = requestAnimationFrame(loop);
  }
  function finish() {
    const i = LEVELS.indexOf(run.level), t = Math.max(0, run.finishTick - run.bonus), best = getBest(i);
    const isBest = best == null || t < best; if (isBest) setBest(i, t);
    $('done-title').textContent = run.crashes ? 'Course clear' : 'Clean run!';
    $('done-time').textContent = fmt(t);
    $('done-best').textContent = isBest ? 'New best time for ' + run.level.name : 'Best ' + fmt(best);
    $('done-crashes').textContent = (run.crashes ? run.crashes + (run.crashes === 1 ? ' crash' : ' crashes') : 'No crashes') + ' · ' + (run.tricks ? run.tricks + (run.tricks === 1 ? ' trick' : ' tricks') : 'no tricks') + (run.bonus ? ' · ' + (run.bonus / 60) + ' s off for tricks' : '') + ' · run recorded, ' + run.inputs.length + ' ticks';
    $('btn-next').hidden = i + 1 >= LEVELS.length; $('panel-done').hidden = false;
    run.over = true; window.lastRun = { level: i, ticks: run.inputs.slice(), time: t, raw: run.finishTick, bonus: run.bonus, crashes: run.crashes, tricks: run.tricks };
    offerClaim(i, t);
  }
  function next() { const i = LEVELS.indexOf(run.level); if (i + 1 < LEVELS.length) startLevel(i + 1); else showMenu(); }
  $('btn-next').addEventListener('click', next);
  $('btn-again').addEventListener('click', () => startLevel(LEVELS.indexOf(run.level)));
  $('btn-menu').addEventListener('click', showMenu);

  // ---------- the record board ----------
  const claimForm = $('claim'), claimName = $('claim-name'), claimAddr = $('claim-addr'), claimNote = $('claim-note'), claimResult = $('claim-result'), claimBtn = $('claim-btn');
  let pendingClaim = null;
  try { claimName.value = localStorage.getItem('mtbcrazy.name') || ''; claimAddr.value = localStorage.getItem('mtbcrazy.addr') || ''; } catch (e) { }
  async function loadBoard() {
    try { const r = await fetch(API + '/ride/board', { cache: 'no-store' }); const d = await r.json(); records = d.board || []; if (!$('panel-title').hidden) buildMenu(); } catch (e) { /* the board is a nicety; the game does not need it */ }
  }
  function offerClaim(i, t) {
    const rec = records[i], beats = !rec || !rec.name || t < rec.time;
    pendingClaim = beats ? { level: i, log: encodeLog(run.inputs), time: t } : null;
    claimForm.hidden = !beats; claimResult.textContent = ''; claimBtn.disabled = false;
    if (beats) claimNote.textContent = rec && rec.name ? 'That beats the record on this course, ' + fmt(rec.time) + ' by ' + rec.name + '. Claim it and the purse moves to you.' : 'No record stands on this course yet. Claim it and the purse is yours.';
    else $('done-best').textContent += ' · record ' + fmt(rec.time) + ' by ' + rec.name;
  }
  claimForm.addEventListener('submit', async e => {
    e.preventDefault();
    if (!pendingClaim) return;
    const name = claimName.value.trim().slice(0, 24), addr = claimAddr.value.trim();
    if (!name) { claimName.focus(); return; }
    try { localStorage.setItem('mtbcrazy.name', name); localStorage.setItem('mtbcrazy.addr', addr); } catch (e2) { }
    claimBtn.disabled = true; claimResult.textContent = 'The referee is replaying your run\u2026';
    const claim = pendingClaim;
    try {
      const r = await fetch(API + '/ride/claim', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ level: claim.level, name, addr, log: claim.log }) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.error || ('the board answered ' + r.status));
      if (d.record) {
        records = d.board || records; pendingClaim = null; claimForm.hidden = true;
        $('done-best').textContent = 'Course record: ' + fmt(d.time) + ' by ' + name + (d.named ? ' (registered name)' : '');
        claimResult.textContent = 'Record! ' + (d.why || '');
      } else {
        claimResult.textContent = (d.why || 'Not a record.') + (d.time !== undefined && d.time !== claim.time ? ' The referee clocked ' + fmt(d.time) + '.' : '');
        claimBtn.disabled = false;
      }
    } catch (err) { claimResult.textContent = 'The board did not take it: ' + err.message; claimBtn.disabled = false; }
  });

  function loop(now) {
    if (!run) return;
    acc += Math.min(0.1, (now - last) / 1000); last = now;
    while (acc >= TICK) { acc -= TICK; if (!run.over) { run.lastMask = held; step(run, held); if (run.finished && !run.over) finish(); } }
    draw(run);
    $('hud-time').textContent = fmt(Math.max(0, (run.finished ? run.finishTick : run.tick) - run.bonus));
    $('hud-sprint').style.width = run.sprint + '%';
    $('hud-tricks').textContent = run.tricks ? run.tricks + (run.tricks === 1 ? ' trick' : ' tricks') : '';
    raf = requestAnimationFrame(loop);
  }

  // replay a recorded input log and return the finishing tick (null if it never finishes). Used by the checker.
  window.mtbTrace = function (levelIndex, inputs, every) { const r = newRun(LEVELS[levelIndex]); const out = []; for (let i = 0; i < inputs.length; i++) { step(r, inputs[i]); if (i % (every || 60) === 0) out.push([r.tick, Math.round((r.rear.x + r.front.x) / 2), Math.round((r.rear.y + r.front.y) / 2), r.crashes, r.cpIndex, r.rear.ground ? 1 : 0]); if (r.finished) { out.push(['finish', r.finishTick, r.crashes]); break; } } return out; };
  window.mtbAuto = function (levelIndex, pilot, maxTicks) { const r = newRun(LEVELS[levelIndex]); const log = []; for (let i = 0; i < maxTicks; i++) { const m = pilot(r, frameUp(r)); log.push(m); step(r, m); if (r.finished) return { finish: r.finishTick, crashes: r.crashes, bonus: r.bonus, tricks: r.tricks, decks: r.decks, log }; } return { finish: null, crashes: r.crashes, bonus: r.bonus, x: Math.round((r.rear.x + r.front.x) / 2), cp: r.cpIndex, log }; };
  window.mtbFindSalts = function (pilots, maxSalt, maxTicks) { const out = []; for (let i = 0; i < 20; i++) { let found = -1; for (let salt = 0; salt <= maxSalt && found < 0; salt++) { const lv = genLevel(i, salt); for (const pilot of pilots) { const r = newRun(lv); let fin = null; for (let t = 0; t < maxTicks; t++) { step(r, pilot(r, frameUp(r))); if (r.finished) { fin = r.finishTick || 1; break; } } if (fin) { found = salt; break; } } } out.push(found); } return out; };
  window.mtbLevels = LEVELS;   // read-only, for the checker
  window.mtbReplay = function (levelIndex, inputs) { const r = newRun(LEVELS[levelIndex]); for (const m of inputs) { step(r, m); if (r.finished) return Math.max(0, r.finishTick - r.bonus); } return null; };

  showMenu();
  loadBoard();
})();

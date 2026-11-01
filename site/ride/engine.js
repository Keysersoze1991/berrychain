/* MTB Crazy engine: the track builder, the twenty courses and the fixed-step physics (60 Hz, Verlet,
   one-sided track segments). Deterministic, so a run can be replayed from its input log. Loaded by the
   page (window.MTB) and by the referee on seed1 (require('./engine.js') under Node, see check.js). */
(function (root, factory) {
  'use strict';
  const m = factory();
  if (typeof module === 'object' && module && module.exports) module.exports = m; else root.MTB = m;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  // ---------- constants (per tick, 60 Hz) ----------
  const TICK = 1 / 60;
  const GRAV = 0.42;          // px / tick^2
  const WR = 13;              // wheel radius
  const FRAME = 58;           // wheelbase
  const HEAD_UP = 40;         // head height above the frame midpoint
  const HEAD_R = 9;
  const PEDAL = 0.33, PEDAL_SPRINT = 0.50;
  const VMAX = 15, VMAX_SPRINT = 19, VCAP = 23;
  const BRAKE = 0.90;
  const LEAN = 0.09;            // ground weight shift
  const AIR_SPIN = 7.0;         // px/tick of nose speed relative to tail while a lean key is held in the air
  const SPRINT_DRAIN = 0.5, SPRINT_FILL = 0.32; // per tick, meter 0..100
  const BIT = { PEDAL: 1, BRAKE: 2, BACK: 4, FWD: 8, SPRINT: 16 };

  // ---------- track builder ----------
  // Points are traced left to right; solid ground is on the right-hand side of travel,
  // so loops traced counter-clockwise on screen are ridden on the inside.
  function builder() {
    const b = { x: 0, y: 0, chunks: [[]], checkpoints: [], finishX: 0, minY: 0, maxY: 0, loops: [], deck: 0, decks: 0 };
    const cur = () => b.chunks[b.chunks.length - 1];
    const pt = (x, y, loop, q) => { const p = { x: Math.round(x * 100) / 100, y: Math.round(y * 100) / 100, l: !!loop }; if (loop) { p.loop = b.loops.length - 1; p.q = q; } if (b.deck) p.d = b.deck; cur().push(p); b.x = x; b.y = y; if (y < b.minY) b.minY = y; if (y > b.maxY) b.maxY = y; };
    const api = {
      start() { pt(0, 0); api.flat(260); api.check(); return api; },
      flat(len) { pt(b.x + len, b.y); return api; },
      slope(len, dy) { pt(b.x + len, b.y + dy); return api; },
      hill(len, h) { const n = Math.max(8, Math.round(len / 22)); const x0 = b.x, y0 = b.y; for (let i = 1; i <= n; i++) { const t = i / n; pt(x0 + len * t, y0 - h * (1 - Math.cos(2 * Math.PI * t)) / 2); } return api; },
      rise(len, h) { const n = Math.max(6, Math.round(len / 22)); const x0 = b.x, y0 = b.y; for (let i = 1; i <= n; i++) { const t = i / n; pt(x0 + len * t, y0 - h * (1 - Math.cos(Math.PI * t)) / 2); } return api; },
      fall(len, h) { const n = Math.max(6, Math.round(len / 22)); const x0 = b.x, y0 = b.y; for (let i = 1; i <= n; i++) { const t = i / n; pt(x0 + len * t, y0 + h * (1 - Math.cos(Math.PI * t)) / 2); } return api; },
      ramp(len, h) { pt(b.x + len, b.y - h); return api; },           // straight kicker
      drop(h) { pt(b.x, b.y + h); return api; },                        // sheer wall down
      bumps(n, len, h) { for (let i = 0; i < n; i++) api.hill(len, h); return api; },
      gap(len, dy) { const x = b.x + len, y = b.y + (dy || 0); b.chunks.push([]); pt(x, y); return api; },
      curve(r, deg) { const x0 = b.x, y0 = b.y, n = Math.max(8, Math.round(deg / 6)); for (let i = 1; i <= n; i++) { const a = (deg * Math.PI / 180) * i / n; pt(x0 + r * Math.sin(a), y0 - r * (1 - Math.cos(a))); } return api; },   // quarter-pipe style launch
      loop(r, gapDeg) { const cx = b.x, cy = b.y - r, n = 40; b.loops.push({ cx, cy, r, gap: gapDeg || 0 }); let inGap = false;
        for (let i = 1; i <= n; i++) { const travel = 360 * i / n; const skip = gapDeg && travel > 180 - gapDeg / 2 && travel < 180 + gapDeg / 2;
          if (skip) { if (!inGap) { b.chunks.push([]); inGap = true; } continue; }
          const a = Math.PI / 2 - 2 * Math.PI * i / n; pt(cx + r * Math.cos(a), cy + r * Math.sin(a), i < n, Math.floor((i - 1) / (n / 4))); }
        return api; },
      deckOn() { b.deck = ++b.decks; pt(b.x, b.y); return api; },      // from here the track is a raised deck: no ground under it, drawn as a ribbon
      deckOff() { b.deck = 0; pt(b.x, b.y); return api; },
      lowRoad(pts) { b.chunks.splice(b.chunks.length - 1, 0, pts.map(([x, y]) => { if (y > b.maxY) b.maxY = y; return { x, y }; })); return api; },   // ground under a deck, traced left to right; does not move the pen
      get y() { return b.y; },
      check() { b.checkpoints.push({ x: b.x, y: b.y }); api.flat(240); return api; },   // a respawn always gets a run-up
      finish() { b.finishX = b.x; api.flat(520); return api; },
      get x() { return b.x; },
      done(name, blurb) { return { name, blurb, chunks: b.chunks, loops: b.loops, checkpoints: b.checkpoints, finishX: b.finishX, length: b.x, deathY: b.maxY + 420, minY: b.minY }; }
    };
    return api;
  }

  // ---------- courses: 20 of them, generated from a seed, five per tier ----------
  const TIERS = ['Shore', 'Reef', 'Open Sea', 'Storm'];
  const NAMES = ['Berry Hill', 'Harbour Steps', "Devil's Elbow", 'The Mast', "Crow's Nest",
    'Reef Break', 'Salt Flats', 'Gull Rock', 'The Narrows', 'Widow Maker',
    'Open Water', 'Dead Reckoning', 'The Doldrums', 'Albatross', 'Kraken Loops',
    'Squall Line', 'Nine Lives', 'Davy Jones', 'Hurricane Deck', 'Maelstrom'];
  function rng(seed) { let t = seed >>> 0; return () => { t = (t + 0x6D2B79F5) >>> 0; let x = t; x = Math.imul(x ^ (x >>> 15), x | 1); x ^= x + Math.imul(x ^ (x >>> 7), x | 61); return ((x ^ (x >>> 14)) >>> 0) / 4294967296; }; }
  // one salt per course, chosen offline as the first that produced a course the test pilot could finish (see mtbFindSalts)
  const SALTS = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 1, 3];
  function genLevel(i, salt) {
    const tier = Math.floor(i / 5), d = tier + (i % 5) / 5;        // difficulty 0 .. 3.8
    const R = rng(0x5EED + i * 7919 + (salt || 0) * 104729);
    const pick = (lo, hi) => Math.round(lo + (hi - lo) * R());
    const lerp = (a, b) => a + (b - a) * Math.min(1, d / 3.8);
    const api = builder().start();
    const target = Math.round(15000 + d * 3500);
    let lastCp = api.x, last = '';
    const pieces = {
      hills() { const big = R() < 0.35; for (let k = 0; k < (big ? 1 : pick(1, 3)); k++) api.hill(big ? pick(480, 640) : pick(240, 360), Math.round((big ? lerp(130, 230) : lerp(50, 130)) * (0.7 + R() * 0.6))).flat(pick(80, 160)); },
      hillLoop() { const h = Math.round(lerp(170, 280)); api.hill(pick(540, 700), h).flat(pick(90, 150)).loop(pick(106, Math.round(lerp(112, 134)))).flat(pick(260, 340)); },   // a big hill, and the speed off it feeds a big loop
      jumpLoop() {   // a kicker in front of a loop on a raised deck: jump in and ride it (a second off), or drop short and take the low road underneath
        const L = pick(110, 140), H = Math.round(L * 0.5), G = Math.round(lerp(180, 250)), r = pick(96, Math.round(lerp(100, 124)));
        api.flat(pick(380, 460)).ramp(L, H);
        const xk = api.x, yk = api.y, y0 = yk + H, yLow = y0 + 70;
        api.deckOn().gap(G, 0).flat(pick(300, 360)).loop(r).flat(pick(160, 220));
        const xd = api.x;
        api.slope(260, y0 - yk).deckOff().lowRoad([[xk, yLow], [xd + 60, yLow], [xd + 260, y0]]).flat(pick(280, 340)); },
      bumps() { api.bumps(pick(3, 6), pick(80, 120), Math.round(lerp(20, 36))); api.flat(pick(140, 240)); },
      rollers() { const h = Math.round(lerp(110, 230)); api.rise(pick(220, 300), h).flat(pick(80, 160)).fall(pick(240, 320), h).flat(220); },
      kicker() { const L = Math.round(lerp(95, 175)), H = Math.round(L * lerp(0.42, 0.62)); const G = Math.round(lerp(150, 300) * (0.85 + R() * 0.3)); api.flat(pick(300, 400)).ramp(L, H).gap(G).flat(pick(240, 320)); },
      bigAir() { const h = Math.round(lerp(140, 230)); api.rise(pick(320, 380), h).flat(pick(380, 460)).ramp(pick(150, 180), Math.round(lerp(80, 110))).gap(Math.round(lerp(240, 300))).flat(240).fall(pick(220, 280), h).flat(260); },
      loop() { api.flat(pick(300, 380)).loop(pick(86, Math.round(lerp(88, 108)))).flat(pick(240, 320)); },
      twinLoop() { const r = pick(86, Math.round(lerp(88, 100))); api.flat(pick(320, 380)).loop(r).flat(320).loop(r).flat(260); },
      drop() { api.drop(Math.round(lerp(60, 160))).flat(pick(240, 320)); },
      stairs() { const h = Math.round(lerp(55, 120)); api.drop(h).flat(pick(180, 240)).drop(h).flat(pick(240, 320)); },
      whoops() { api.bumps(pick(6, 9), pick(56, 72), Math.round(lerp(14, 22))); api.flat(pick(160, 240)); },
      doubleKicker() { const L = Math.round(lerp(100, 150)), H = Math.round(L * 0.5); const G = Math.round(lerp(140, 230)); api.flat(pick(240, 320)).ramp(L, H).gap(G).flat(pick(160, 220)).ramp(L, H).gap(G).flat(pick(260, 320)); },
      stepDown() { const dropH = Math.round(lerp(220, 420)); api.flat(pick(340, 420)).ramp(pick(120, 150), pick(60, 80)).gap(Math.round(lerp(260, 400)), dropH).slope(pick(220, 300), Math.round(dropH * 0.5)).flat(pick(300, 360)); },
      megaKicker() { const r = pick(120, 160), deg = Math.round(lerp(44, 58)); const dropH = Math.round(lerp(220, 440)); api.flat(pick(440, 540)).curve(r, deg).gap(Math.round(lerp(280, 420)), dropH).slope(pick(220, 280), Math.round(dropH * 0.5)).flat(pick(300, 360)); },
      bowlLaunch() { const h = Math.round(lerp(160, 260)), r = pick(130, 170), deg = Math.round(lerp(50, 64)); const dropH = Math.round(lerp(260, 500)); api.fall(pick(240, 300), h).flat(pick(140, 200)).curve(r, deg).gap(Math.round(lerp(300, 460)), dropH).slope(pick(240, 300), Math.round(dropH * 0.5)).flat(pick(320, 380)); },
      gapLoop() { api.flat(pick(360, 440)).loop(pick(88, 100), Math.round(lerp(90, 130))).flat(pick(300, 360)); },
      cliffJump() { const h = Math.round(lerp(100, 200)); api.flat(220).ramp(pick(80, 110), pick(30, 50)).gap(Math.round(lerp(150, 250))).flat(140).fall(pick(220, 280), h).flat(260); }
    };
    const weights = [
      { hills: 3, bumps: 2, whoops: 2, rollers: 2, kicker: 4, doubleKicker: 2, stepDown: 2, megaKicker: 1, drop: 2, stairs: 1, loop: 1, hillLoop: 1, jumpLoop: 1 },
      { hills: 2, bumps: 1, whoops: 2, rollers: 2, kicker: 3, doubleKicker: 2, stepDown: 3, megaKicker: 2, bowlLaunch: 1, bigAir: 2, drop: 2, stairs: 2, loop: 2, hillLoop: 2, jumpLoop: 2, cliffJump: 1 },
      { hills: 2, bumps: 1, whoops: 2, rollers: 2, kicker: 3, doubleKicker: 2, stepDown: 3, megaKicker: 3, bowlLaunch: 2, bigAir: 2, drop: 2, stairs: 2, loop: 2, hillLoop: 2, jumpLoop: 3, twinLoop: 2, cliffJump: 2 },
      { hills: 1, bumps: 1, whoops: 2, rollers: 2, kicker: 3, doubleKicker: 3, stepDown: 3, megaKicker: 4, bowlLaunch: 3, bigAir: 3, drop: 2, stairs: 2, loop: 2, hillLoop: 3, jumpLoop: 3, twinLoop: 3, cliffJump: 3 }
    ][tier];
    const names = Object.keys(weights), total = names.reduce((t, n) => t + weights[n], 0);
    while (api.x < target) {
      let roll = R() * total, name = names[0];
      for (const n of names) { roll -= weights[n]; if (roll <= 0) { name = n; break; } }
      if (name === last) continue;
      pieces[name](); last = name;
      if (api.x - lastCp > 2600) { api.check(); lastCp = api.x; }
    }
    api.finish();
    return api.done(NAMES[i], TIERS[tier] + ' · course ' + (i % 5 + 1));
  }
  const LEVELS = []; for (let i = 0; i < 20; i++) LEVELS.push(genLevel(i, SALTS[i]));

  // ---------- physics ----------
  function newRun(level) {
    const cp = level.checkpoints[0];
    const run = { level, tick: 0, inputs: [], crashes: 0, finished: false, cpIndex: 0, sprint: 100, flash: 0, over: false, tricks: 0, airTicks: 0, airAngle: 0, lastAngle: null, toast: null, bonus: 0, decks: {} };
    spawn(run, cp);
    return run;
  }
  function spawn(run, cp) {
    run.rear = { x: cp.x - 60, y: cp.y - WR, px: 0, py: 0, ground: null, spin: 0 };
    run.front = { x: cp.x - 60 + FRAME, y: cp.y - WR, px: 0, py: 0, ground: null, spin: 0 };
    run.loopPhase = {};
    run.rear.px = run.rear.x; run.rear.py = run.rear.y; run.front.px = run.front.x; run.front.py = run.front.y;
    run.crashed = 0;
  }
  function frameUp(run) {
    let ux = run.front.x - run.rear.x, uy = run.front.y - run.rear.y;
    const d = Math.sqrt(ux * ux + uy * uy) || 1; ux /= d; uy /= d;
    return { ux, uy, upx: uy, upy: -ux };
  }
  function collideWheel(w, chunks, phase) {
    w.ground = null;
    let bestDir = null, bestDist = WR + 0.8;                              // contact within 0.8 px counts as riding the surface
    for (const c of chunks) {
      for (let i = 1; i < c.length; i++) {
        const a = c[i - 1], b = c[i];
        if ((a.x < w.x - 48 && b.x < w.x - 48) || (a.x > w.x + 48 && b.x > w.x + 48)) continue;
        const lid = b.loop !== undefined ? b.loop : a.loop;
        if (lid !== undefined && (b.q !== undefined ? b.q : a.q) === 0 && phase[lid]) continue;     // past the top: the entry quarter is behind you
        const dx = b.x - a.x, dy = b.y - a.y, L2 = dx * dx + dy * dy; if (!L2) continue;
        let t = ((w.x - a.x) * dx + (w.y - a.y) * dy) / L2; t = t < 0 ? 0 : t > 1 ? 1 : t;
        const cx = a.x + dx * t, cy = a.y + dy * t;
        const ox = w.x - cx, oy = w.y - cy, dist = Math.sqrt(ox * ox + oy * oy);
        const L = Math.sqrt(L2), sx = -dy / L, sy = dx / L;               // solid-side normal
        const side = ox * sx + oy * sy;                                   // > 0: the centre is past the surface
        const crossed = side > 0 && t > 0 && t < 1 && dist < VCAP + WR;   // went through the surface this tick (fast fall)
        if (!crossed && dist >= bestDist) continue;
        const sidePrev = (w.px - cx) * sx + (w.py - cy) * sy;             // where the wheel came from this tick
        if (sidePrev > 1.0) continue;                                      // from inside the solid: the back of a loop, ignore
        if (crossed || dist < bestDist) { bestDist = crossed ? 0 : dist; bestDir = { tx: dx / L, ty: dy / L, d: a.d || b.d || 0 }; }
        if (!crossed && dist >= WR) continue;
        let nx, ny, pen;
        if (side > 0 || dist < 1e-6) { nx = -sx; ny = -sy; pen = WR + side; }                 // crossed the surface: put it back on the riding side
        else { nx = ox / dist; ny = oy / dist; pen = WR - dist; }
        w.x += nx * pen; w.y += ny * pen;
        let vx = w.x - w.px, vy = w.y - w.py;                             // kill the velocity into the surface
        const vn = vx * nx + vy * ny;
        if (vn < 0) { vx -= vn * nx; vy -= vn * ny; w.px = w.x - vx; w.py = w.y - vy; }
      }
    }
    if (bestDir) w.ground = bestDir;
  }
  function headHits(run) {
    const f = frameUp(run);
    const hx = (run.rear.x + run.front.x) / 2 + f.upx * HEAD_UP, hy = (run.rear.y + run.front.y) / 2 + f.upy * HEAD_UP;
    for (const c of run.level.chunks) {
      for (let i = 1; i < c.length; i++) {
        const a = c[i - 1], b = c[i];
        if (a.l || b.l) continue;                                          // loops never hit the head; falling out of one onto the ground does
        if ((a.x < hx - 40 && b.x < hx - 40) || (a.x > hx + 40 && b.x > hx + 40)) continue;
        const dx = b.x - a.x, dy = b.y - a.y, L2 = dx * dx + dy * dy; if (!L2) continue;
        let t = ((hx - a.x) * dx + (hy - a.y) * dy) / L2; t = t < 0 ? 0 : t > 1 ? 1 : t;
        const ox = hx - (a.x + dx * t), oy = hy - (a.y + dy * t);
        if (ox * ox + oy * oy >= HEAD_R * HEAD_R) continue;
        const L = Math.sqrt(L2); if (ox * (-dy / L) + oy * (dx / L) > 0) continue;   // behind the surface (the back of a loop): not a hit
        return true;
      }
    }
    return false;
  }
  function step(run, mask) {
    run.inputs.push(mask); run.tick++;
    if (run.finished) return;
    if (run.crashed) { run.crashed--; if (!run.crashed) spawn(run, run.level.checkpoints[run.cpIndex]); return; }
    const r = run.rear, fw = run.front, f = frameUp(run);
    const sprinting = (mask & BIT.SPRINT) && run.sprint > 0 && (mask & BIT.PEDAL);
    run.sprint = sprinting ? Math.max(0, run.sprint - SPRINT_DRAIN) : Math.min(100, run.sprint + SPRINT_FILL);
    // drive
    if ((mask & BIT.PEDAL) && r.ground) {
      const acc = sprinting ? PEDAL_SPRINT : PEDAL, vmax = sprinting ? VMAX_SPRINT : VMAX;
      const along = (r.x - r.px) * r.ground.tx + (r.y - r.py) * r.ground.ty;
      const stalled = along < 1.5 && r.ground.ty < -0.45;                 // standing still on a steep wall: no traction, roll back and try again
      if (along < vmax && !stalled) for (const w of [r, fw]) { const g = w.ground || r.ground; w.px -= g.tx * acc; w.py -= g.ty * acc; }
    }
    if (r.ground || fw.ground) for (const w of [r, fw]) { w.px = w.x - (w.x - w.px) * 0.995; w.py = w.y - (w.y - w.py) * 0.995; } // rolling resistance
    if (mask & BIT.BRAKE) for (const w of [r, fw]) if (w.ground) { w.px = w.x - (w.x - w.px) * BRAKE; w.py = w.y - (w.y - w.py) * BRAKE; }
    // lean. In the air, holding a lean key spins the bike at a steady rate and letting go stops the spin
    // (arcade feel); on the ground it just shifts weight.
    const lean = (mask & BIT.FWD ? 1 : 0) - (mask & BIT.BACK ? 1 : 0);
    {
      const rvx = r.x - r.px, rvy = r.y - r.py, fvx = fw.x - fw.px, fvy = fw.y - fw.py;
      const w = (fvx - rvx) * f.upx + (fvy - rvy) * f.upy;             // how fast the nose is rising relative to the tail
      if (!r.ground || !fw.ground) {                                     // any wheel off the ground: rate-controlled spin
        const c = (-lean * AIR_SPIN - w) * 0.09;
        fw.px -= f.upx * c; fw.py -= f.upy * c; r.px += f.upx * c; r.py += f.upy * c;
      } else if (lean) {
        const k = LEAN * lean;
        fw.px += f.upx * k; fw.py += f.upy * k; r.px -= f.upx * k; r.py -= f.upy * k;
      }
    }
    // integrate
    for (const w of [r, fw]) {
      let vx = w.x - w.px, vy = w.y - w.py + GRAV;
      const sp = Math.sqrt(vx * vx + vy * vy); if (sp > VCAP) { vx *= VCAP / sp; vy *= VCAP / sp; }
      w.px = w.x; w.py = w.y; w.x += vx; w.y += vy;
    }
    // constraints and collisions
    for (let it = 0; it < 4; it++) {
      let dx = fw.x - r.x, dy = fw.y - r.y; const d = Math.sqrt(dx * dx + dy * dy) || 1; const corr = (d - FRAME) / d / 2;
      r.x += dx * corr; r.y += dy * corr; fw.x -= dx * corr; fw.y -= dy * corr;
      collideWheel(r, run.level.chunks, run.loopPhase); collideWheel(fw, run.level.chunks, run.loopPhase);
    }
    for (const w of [r, fw]) { const vx = w.x - w.px; w.spin += vx / WR; }
    run.level.loops.forEach((L, i) => {                                   // one phase per bike per loop
      const lim = L.r + WR + 50; let outside = 0;
      for (const w of [r, fw]) { const dx = w.x - L.cx, dy = w.y - L.cy; if (dx * dx + dy * dy > lim * lim) outside++; else if (dy < -L.r * 0.2 && dx < 0) run.loopPhase[i] = 1; }
      if (outside === 2) run.loopPhase[i] = 0;
    });
    // tricks: count flips and big air (display only, never feeds back into the physics)
    {
      const air = !r.ground && !fw.ground, f2 = frameUp(run), ang = Math.atan2(f2.uy, f2.ux);
      if (air) {
        if (run.lastAngle !== null) { let da = ang - run.lastAngle; if (da > Math.PI) da -= 2 * Math.PI; if (da < -Math.PI) da += 2 * Math.PI; run.airAngle += da; }
        run.airTicks++;
      } else if (run.airTicks > 0) {
        const flips = Math.floor(Math.abs(run.airAngle) / (Math.PI * 1.8));
        const deck = (r.ground && r.ground.d) || (fw.ground && fw.ground.d) || 0;        // landed on a raised deck (the jump loop)
        const jumpedIn = deck && run.airTicks >= 18 && !run.decks[deck] ? 1 : 0;
        if (jumpedIn) { run.decks[deck] = 1; run.tricks += 1; run.bonus += 60; }
        if (flips > 0) { run.tricks += flips; run.bonus += flips * 60; run.toast = { text: (flips === 2 ? 'Double ' : flips > 2 ? flips + 'x ' : '') + (run.airAngle < 0 ? 'backflip' : 'frontflip') + (jumpedIn ? ' into the loop!' : '!') + '  \u2212' + (flips + jumpedIn) + 's', t: 80 }; }
        else if (jumpedIn) run.toast = { text: 'Into the loop!  \u22121s', t: 70 };
        else if (run.airTicks > 55) { run.tricks += 1; run.toast = { text: 'Big air!', t: 60 }; }
        run.airTicks = 0; run.airAngle = 0;
      }
      run.lastAngle = ang;
    }
    // checkpoints, finish, crashes
    const mx = (r.x + fw.x) / 2, my = (r.y + fw.y) / 2;
    const cps = run.level.checkpoints;
    while (run.cpIndex + 1 < cps.length && mx > cps[run.cpIndex + 1].x) run.cpIndex++;
    if (mx > run.level.finishX) { run.finished = true; run.finishTick = run.tick; return; }
    if (my > run.level.deathY || headHits(run)) { run.crashes++; run.crashed = 45; run.flash = 12; run.airTicks = 0; run.airAngle = 0; run.toast = { text: 'Crash!', t: 45 }; }
  }


  // ---------- replay (the referee) ----------
  // A run is its input log: one mask per tick (bits: 1 pedal, 2 brake, 4 back, 8 forward, 16 sprint).
  // On the wire a log is a string, one character per tick from LOG_CHARS (mask 0..31).
  const LOG_CHARS = '0123456789abcdefghijklmnopqrstuv';
  const MAX_LOG_TICKS = 24000;   // 400 s at 60 Hz; no course needs anything like it
  function encodeLog(masks) { let s = ''; for (const m of masks) s += LOG_CHARS[(m | 0) & 31]; return s; }
  function decodeLog(s) { const out = []; for (let i = 0; i < s.length; i++) { const v = LOG_CHARS.indexOf(s[i]); if (v < 0) return null; out.push(v); } return out; }
  // Replays a log on a course and returns what the clock said, or null if the run never finished.
  function replay(levelIndex, masks) {
    if (!(levelIndex >= 0 && levelIndex < LEVELS.length) || !masks || masks.length > MAX_LOG_TICKS) return null;
    const r = newRun(LEVELS[levelIndex]);
    for (const m of masks) { step(r, m); if (r.finished) return { time: Math.max(0, r.finishTick - r.bonus), raw: r.finishTick, bonus: r.bonus, crashes: r.crashes, tricks: r.tricks, ticks: r.tick }; }
    return null;
  }

  return { TICK, GRAV, WR, FRAME, HEAD_UP, HEAD_R, PEDAL, PEDAL_SPRINT, VMAX, VMAX_SPRINT, VCAP, BRAKE, LEAN, AIR_SPIN, SPRINT_DRAIN, SPRINT_FILL, BIT, builder, TIERS, NAMES, rng, SALTS, genLevel, LEVELS, newRun, spawn, frameUp, collideWheel, headHits, step, LOG_CHARS, MAX_LOG_TICKS, encodeLog, decodeLog, replay };
});

/* MTB Crazy: a side-on mountain-bike stunt racer.
   Deterministic fixed-step physics (60 Hz, Verlet, one-sided track segments) so a run can be
   replayed from its input log and checked server-side when the race purse opens. */
'use strict';
(function () {
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
  const AIR_SPIN = 3.2;         // px/tick of nose speed relative to tail while a lean key is held in the air
  const SPRINT_DRAIN = 0.55, SPRINT_FILL = 0.18; // per tick, meter 0..100
  const BIT = { PEDAL: 1, BRAKE: 2, BACK: 4, FWD: 8, SPRINT: 16 };

  // ---------- track builder ----------
  // Points are traced left to right; solid ground is on the right-hand side of travel,
  // so loops traced counter-clockwise on screen are ridden on the inside.
  function builder() {
    const b = { x: 0, y: 0, chunks: [[]], checkpoints: [], finishX: 0, minY: 0, maxY: 0, loops: [] };
    const cur = () => b.chunks[b.chunks.length - 1];
    const pt = (x, y, loop, q) => { const p = { x: Math.round(x * 100) / 100, y: Math.round(y * 100) / 100, l: !!loop }; if (loop) { p.loop = b.loops.length - 1; p.q = q; } cur().push(p); b.x = x; b.y = y; if (y < b.minY) b.minY = y; if (y > b.maxY) b.maxY = y; };
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
      gap(len) { const x = b.x + len, y = b.y; b.chunks.push([]); pt(x, y); return api; },
      loop(r) { const cx = b.x, cy = b.y - r, n = 40; b.loops.push({ cx, cy, r }); for (let i = 1; i <= n; i++) { const a = Math.PI / 2 - 2 * Math.PI * i / n; pt(cx + r * Math.cos(a), cy + r * Math.sin(a), i < n, Math.floor((i - 1) / (n / 4))); } return api; },
      check() { b.checkpoints.push({ x: b.x, y: b.y }); api.flat(240); return api; },   // a respawn always gets a run-up
      finish() { b.finishX = b.x; api.flat(520); return api; },
      done(name, blurb) { return { name, blurb, chunks: b.chunks, loops: b.loops, checkpoints: b.checkpoints, finishX: b.finishX, length: b.x, deathY: b.maxY + 420, minY: b.minY }; }
    };
    return api;
  }

  const LEVELS = [
    // 1. Easy: rolling hills, small kickers, one gentle gap. Teaches pedal, lean and the clock.
    builder().start().hill(320, 60).flat(140).hill(300, 90).flat(200).bumps(3, 120, 26).flat(180).check()
      .ramp(90, 36).gap(120).flat(260).hill(360, 110).flat(160).rise(220, 110).flat(140).fall(260, 110).flat(200).check()
      .bumps(4, 100, 22).flat(160).ramp(100, 44).gap(150).flat(280).hill(300, 80).flat(300).ramp(110, 50).gap(170).flat(300).check()
      .rise(260, 150).flat(120).hill(240, 60).flat(120).fall(300, 150).flat(220).ramp(100, 40).gap(140).flat(320).finish()
      .done('Berry Hill', 'Rolling hills and a couple of friendly kickers.'),
    // 2. Drops and steps, bumps, kickers, and a first gentle loop with a long run-up.
    builder().start().rise(200, 80).flat(140).drop(60).flat(260).drop(80).flat(280).check().bumps(5, 90, 22).flat(180).ramp(100, 46).gap(150).flat(300).check()
      .drop(110).flat(320).rise(240, 120).flat(300).loop(85).flat(260).check().bumps(3, 110, 30).flat(160).ramp(110, 52).gap(190).flat(300).check()
      .drop(90).flat(240).drop(90).flat(260).rise(260, 160).flat(320).ramp(90, 42).gap(150).flat(220).fall(240, 160).flat(260).hill(280, 70).flat(300).finish()
      .done('Harbour Steps', 'Drops and steps down to the water. Lean back off the edges.'),
    // 3. Loops. Speed in, keep pedalling, do not brake at the top.
    builder().start().hill(260, 50).flat(300).loop(85).flat(280).check().ramp(100, 50).gap(180).flat(300).hill(240, 70).flat(320).loop(90).flat(300).check()
      .bumps(4, 100, 26).flat(200).ramp(110, 56).gap(210).flat(340).loop(95).flat(240).check()
      .rise(200, 100).flat(300).loop(90).flat(160).loop(90).flat(300).ramp(120, 62).gap(220).flat(340).finish()
      .done("Devil's Elbow", 'Loops. Speed in, lean back, do not brake at the top.'),
    // 4. Big air: long climbs, long run-ups, sprint jumps that need the whole meter.
    builder().start().rise(300, 180).flat(360).ramp(140, 80).gap(260).flat(220).fall(220, 180).flat(300).check()
      .bumps(4, 90, 30).flat(300).loop(85).flat(320).loop(85).flat(300).check()
      .rise(320, 240).flat(420).ramp(150, 96).gap(300).flat(220).fall(260, 240).flat(320).check()
      .drop(120).flat(280).hill(300, 90).flat(360).ramp(130, 70).gap(240).flat(300).loop(90).flat(300).ramp(120, 60).gap(200).flat(340).finish()
      .done('The Mast', 'Big air. Sprint off the top and land flat.'),
    // 5. Everything, longer.
    builder().start().hill(260, 70).flat(240).ramp(90, 40).gap(130).flat(240).drop(100).flat(300).check().loop(90).flat(240).bumps(3, 90, 34).flat(240).ramp(110, 64).gap(220).flat(300).check()
      .rise(240, 180).flat(380).loop(95).flat(200).drop(140).flat(300).check().ramp(130, 80).gap(290).flat(220).fall(200, 120).flat(300).hill(240, 60).flat(300).loop(85).flat(320).loop(85).flat(300).check()
      .bumps(5, 80, 24).flat(240).drop(90).flat(260).rise(300, 200).flat(400).ramp(150, 90).gap(310).flat(220).fall(260, 200).flat(300).ramp(120, 60).gap(240).flat(360).finish()
      .done("Crow's Nest", 'Everything at once. Clean this and you can call yourself crazy.')
  ];

  // ---------- physics ----------
  function newRun(level) {
    const cp = level.checkpoints[0];
    const run = { level, tick: 0, inputs: [], crashes: 0, finished: false, cpIndex: 0, sprint: 100, flash: 0, over: false };
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
        if ((a.x < w.x - 40 && b.x < w.x - 40) || (a.x > w.x + 40 && b.x > w.x + 40)) continue;
        const lid = b.loop !== undefined ? b.loop : a.loop;
        if (lid !== undefined && (b.q !== undefined ? b.q : a.q) === 0 && phase[lid]) continue;     // past the top: the entry quarter is behind you
        const dx = b.x - a.x, dy = b.y - a.y, L2 = dx * dx + dy * dy; if (!L2) continue;
        let t = ((w.x - a.x) * dx + (w.y - a.y) * dy) / L2; t = t < 0 ? 0 : t > 1 ? 1 : t;
        const cx = a.x + dx * t, cy = a.y + dy * t;
        const ox = w.x - cx, oy = w.y - cy, dist = Math.sqrt(ox * ox + oy * oy);
        if (dist >= bestDist) continue;
        const L = Math.sqrt(L2), sx = -dy / L, sy = dx / L;               // solid-side normal
        const sidePrev = (w.px - cx) * sx + (w.py - cy) * sy;             // where the wheel came from this tick
        if (sidePrev > 1.0) continue;                                      // from inside the solid: the back of a loop, ignore
        bestDist = dist; bestDir = { tx: dx / L, ty: dy / L };
        if (dist >= WR) continue;
        const side = ox * sx + oy * sy;
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
    // checkpoints, finish, crashes
    const mx = (r.x + fw.x) / 2, my = (r.y + fw.y) / 2;
    const cps = run.level.checkpoints;
    while (run.cpIndex + 1 < cps.length && mx > cps[run.cpIndex + 1].x) run.cpIndex++;
    if (mx > run.level.finishX) { run.finished = true; run.finishTick = run.tick; return; }
    if (my > run.level.deathY || headHits(run)) { run.crashes++; run.crashed = 45; run.flash = 12; }
  }

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
  const cam = { x: 0, y: 0 };

  function draw(run, alpha) {
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    // sky
    const sky = ctx.createLinearGradient(0, 0, 0, H); sky.addColorStop(0, '#6fb7e6'); sky.addColorStop(0.65, '#bfe1f5'); sky.addColorStop(1, '#e8f3e4');
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
      const g = c.filter(p => !p.l); if (g.length < 2) continue;
      ctx.beginPath(); ctx.moveTo(g[0].x, g[0].y); for (const p of g) ctx.lineTo(p.x, p.y);
      ctx.lineTo(g[g.length - 1].x, lv.deathY + 600); ctx.lineTo(g[0].x, lv.deathY + 600); ctx.closePath();
      ctx.fillStyle = '#7a5a3c'; ctx.fill();
      ctx.beginPath(); ctx.moveTo(g[0].x, g[0].y); for (const p of g) ctx.lineTo(p.x, p.y);
      ctx.lineWidth = 7; ctx.strokeStyle = '#4f9a4a'; ctx.lineJoin = 'round'; ctx.stroke();
      ctx.lineWidth = 2; ctx.strokeStyle = '#a3d37a'; ctx.stroke();
      // loops
      let i = 0; while (i < c.length) { if (!c[i].l) { i++; continue; } let j = i; while (j < c.length && c[j].l) j++; const s = Math.max(0, i - 1), e = Math.min(c.length - 1, j);
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
    for (const c of lv.chunks) { const g = c.filter(p => !p.l); for (let i = 1; i < g.length; i++) { if (x >= g[i - 1].x && x <= g[i].x) { const t = (x - g[i - 1].x) / ((g[i].x - g[i - 1].x) || 1); return g[i - 1].y + (g[i].y - g[i - 1].y) * t; } } }
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
  function wheel(w) {
    ctx.save(); ctx.translate(w.x, w.y); ctx.rotate(w.spin);
    ctx.lineWidth = 4; ctx.strokeStyle = '#1b2430'; ctx.beginPath(); ctx.arc(0, 0, WR, 0, Math.PI * 2); ctx.stroke();
    ctx.lineWidth = 1.5; ctx.strokeStyle = '#c9c9c9'; for (let i = 0; i < 6; i++) { const a = i * Math.PI / 3; ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(Math.cos(a) * (WR - 2), Math.sin(a) * (WR - 2)); ctx.stroke(); }
    ctx.fillStyle = '#5a5a5a'; ctx.beginPath(); ctx.arc(0, 0, 3, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
  }
  function bike(run) {
    const r = run.rear, fw = run.front, f = frameUp(run);
    if (run.crashed) { ctx.globalAlpha = 0.45; }
    wheel(r); wheel(fw);
    // frame in bike space
    ctx.save(); ctx.translate(r.x, r.y); ctx.transform(f.ux, f.uy, f.upx, f.upy, 0, 0); // x along the frame, y up
    ctx.lineWidth = 4.5; ctx.strokeStyle = '#c2382b'; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(22, 26); ctx.lineTo(44, 30); ctx.lineTo(FRAME, 0); ctx.moveTo(22, 26); ctx.lineTo(30, 4); ctx.lineTo(44, 30); ctx.moveTo(30, 4); ctx.lineTo(0, 0); ctx.stroke();
    ctx.strokeStyle = '#1b2430'; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(44, 30); ctx.lineTo(48, 42); ctx.lineTo(56, 42); ctx.stroke(); // bars
    ctx.beginPath(); ctx.moveTo(22, 26); ctx.lineTo(16, 34); ctx.lineTo(24, 36); ctx.stroke(); // saddle post
    ctx.fillStyle = '#1b2430'; ctx.beginPath(); ctx.arc(30, 4, 4, 0, Math.PI * 2); ctx.fill(); // crank
    // rider
    const lean = (run.lastMask & BIT.FWD ? 1 : 0) - (run.lastMask & BIT.BACK ? 1 : 0);
    const hipX = 18 - lean * 4, hipY = 36, shX = 36 + lean * 5, shY = 62;
    ctx.strokeStyle = '#d9a62b'; ctx.lineWidth = 7; ctx.beginPath(); ctx.moveTo(hipX, hipY); ctx.lineTo(shX, shY); ctx.stroke(); // torso
    ctx.strokeStyle = '#2b5a8a'; ctx.lineWidth = 5.5; ctx.beginPath(); ctx.moveTo(hipX, hipY); ctx.lineTo(26, 14); ctx.lineTo(30 + Math.cos(r.spin) * 7, 4 + Math.sin(r.spin) * 7); ctx.stroke(); // leg
    ctx.strokeStyle = '#e8c9a0'; ctx.lineWidth = 4.5; ctx.beginPath(); ctx.moveTo(shX, shY); ctx.lineTo(50, 48); ctx.lineTo(55, 43); ctx.stroke(); // arm
    ctx.fillStyle = '#e8c9a0'; ctx.beginPath(); ctx.arc(shX + 3, shY + 11, 7, 0, Math.PI * 2); ctx.fill(); // head
    ctx.fillStyle = '#c2382b'; ctx.beginPath(); ctx.arc(shX + 3, shY + 12, 8.5, Math.PI * 1.05, Math.PI * 2.05); ctx.fill(); // helmet
    ctx.restore(); ctx.globalAlpha = 1;
  }

  // ---------- input ----------
  let held = 0;
  const KEYS = { ArrowRight: BIT.PEDAL, KeyD: BIT.PEDAL, ArrowLeft: BIT.BRAKE, KeyA: BIT.BRAKE, ArrowUp: BIT.BACK, KeyW: BIT.BACK, ArrowDown: BIT.FWD, KeyS: BIT.FWD, ShiftLeft: BIT.SPRINT, ShiftRight: BIT.SPRINT, Space: BIT.SPRINT };
  window.addEventListener('keydown', e => {
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

  function buildMenu() {
    const box = $('levels'); box.innerHTML = '';
    LEVELS.forEach((lv, i) => { const b = document.createElement('button'); const best = getBest(i); b.innerHTML = (i + 1) + '. ' + lv.name + '<small>' + (best != null ? 'best ' + fmt(best) : lv.blurb) + '</small>'; b.title = lv.blurb; b.addEventListener('click', () => startLevel(i)); box.appendChild(b); });
  }
  function showMenu() { run = null; cancelAnimationFrame(raf); buildMenu(); $('panel-title').hidden = false; $('panel-done').hidden = true; $('hud').hidden = true; draw(null); }
  function startLevel(i) {
    run = newRun(LEVELS[i]); run.lastMask = 0; acc = 0; last = performance.now(); held &= ~0;
    $('panel-title').hidden = true; $('panel-done').hidden = true; $('hud').hidden = false; $('hud-level').textContent = (i + 1) + ' · ' + LEVELS[i].name;
    stage.focus({ preventScroll: true }); cancelAnimationFrame(raf); raf = requestAnimationFrame(loop);
  }
  function finish() {
    const i = LEVELS.indexOf(run.level), t = run.finishTick, best = getBest(i);
    const isBest = best == null || t < best; if (isBest) setBest(i, t);
    $('done-title').textContent = run.crashes ? 'Course clear' : 'Clean run!';
    $('done-time').textContent = fmt(t);
    $('done-best').textContent = isBest ? 'New best time for ' + run.level.name : 'Best ' + fmt(best);
    $('done-crashes').textContent = (run.crashes ? run.crashes + (run.crashes === 1 ? ' crash' : ' crashes') : 'No crashes') + ' · run recorded, ' + run.inputs.length + ' ticks';
    $('btn-next').hidden = i + 1 >= LEVELS.length; $('panel-done').hidden = false;
    run.over = true; window.lastRun = { level: i, ticks: run.inputs.slice(), time: t, crashes: run.crashes };
  }
  function next() { const i = LEVELS.indexOf(run.level); if (i + 1 < LEVELS.length) startLevel(i + 1); else showMenu(); }
  $('btn-next').addEventListener('click', next);
  $('btn-again').addEventListener('click', () => startLevel(LEVELS.indexOf(run.level)));
  $('btn-menu').addEventListener('click', showMenu);

  function loop(now) {
    if (!run) return;
    acc += Math.min(0.1, (now - last) / 1000); last = now;
    while (acc >= TICK) { acc -= TICK; if (!run.over) { run.lastMask = held; step(run, held); if (run.finished && !run.over) finish(); } }
    draw(run);
    $('hud-time').textContent = fmt(run.finished ? run.finishTick : run.tick);
    $('hud-sprint').style.width = run.sprint + '%';
    raf = requestAnimationFrame(loop);
  }

  // replay a recorded input log and return the finishing tick (null if it never finishes). Used by the checker.
  window.mtbTrace = function (levelIndex, inputs, every) { const r = newRun(LEVELS[levelIndex]); const out = []; for (let i = 0; i < inputs.length; i++) { step(r, inputs[i]); if (i % (every || 60) === 0) out.push([r.tick, Math.round((r.rear.x + r.front.x) / 2), Math.round((r.rear.y + r.front.y) / 2), r.crashes, r.cpIndex, r.rear.ground ? 1 : 0]); if (r.finished) { out.push(['finish', r.finishTick, r.crashes]); break; } } return out; };
  window.mtbAuto = function (levelIndex, pilot, maxTicks) { const r = newRun(LEVELS[levelIndex]); const log = []; for (let i = 0; i < maxTicks; i++) { const m = pilot(r, frameUp(r)); log.push(m); step(r, m); if (r.finished) return { finish: r.finishTick, crashes: r.crashes, log }; } return { finish: null, crashes: r.crashes, x: Math.round((r.rear.x + r.front.x) / 2), cp: r.cpIndex, log }; };
  window.mtbReplay = function (levelIndex, inputs) { const r = newRun(LEVELS[levelIndex]); for (const m of inputs) { step(r, m); if (r.finished) return r.finishTick; } return null; };

  showMenu();
})();

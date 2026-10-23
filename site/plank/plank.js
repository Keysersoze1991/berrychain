/* Walk the Plank: the captain's daily trivia dive. Talks to the plank service on seed1 (see berrychain/plank.py). */
'use strict';
(function () {
  const API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://localhost:8805' : 'https://seed1.berrychain.link';
  const $ = id => document.getElementById(id);
  const DEPTHS = [[6500, "Davy Jones' Locker"], [5000, 'the Abyss'], [3500, 'the Wreck'], [2000, 'the Reef'], [0, 'the Shallows']];
  const TIER_WORDS = { 10: 'Common as barnacles', 20: 'Heard it before', 30: 'Not bad, sailor', 50: 'Rare catch', 75: 'Deep water', 100: 'Nobody said that!' };

  let state = null;   // { session, mode, day, prompts, i, total, answers: [] }
  let timer = null, deadline = 0;
  const store = { get(k, d) { try { const v = localStorage.getItem('plank.' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem('plank.' + k, JSON.stringify(v)); } catch (e) { } } };

  // ---------- helpers
  function show(id) { for (const s of document.querySelectorAll('.screen')) s.hidden = s.id !== id; }
  function depthName(m) { for (const [lim, name] of DEPTHS) if (m >= lim) return name; return 'the Shallows'; }
  function setDepth(m) {
    $('depth').textContent = m.toLocaleString();
    const frac = Math.min(1, m / 7000);
    if (matchMedia('(max-width: 640px)').matches) { $('diver').style.left = (2 + frac * 90) + '%'; $('diver').style.top = ''; }
    else { $('diver').style.top = (4 + frac * 88) + '%'; $('diver').style.left = ''; }
  }
  async function api(path, opts) {
    const r = await fetch(API + path, Object.assign({ cache: 'no-store' }, opts || {}));
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || ('the ship\'s log answered ' + r.status));
    return data;
  }
  function esc(s) { return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
  function today() { return new Date().toISOString().slice(0, 10); }

  // ---------- title
  $('player').value = store.get('name', '');
  const played = store.get('daily', null);
  if (played && played.day === today()) $('title-note').textContent = 'You walked today\'s plank: ' + played.depth.toLocaleString() + ' m, ' + depthName(played.depth) + '. The endless plank is open, or come back tomorrow.';
  $('btn-daily').addEventListener('click', () => start('daily'));
  $('btn-endless').addEventListener('click', () => start('endless'));

  async function start(mode) {
    const name = $('player').value.trim().slice(0, 24);
    store.set('name', name);
    $('title-note').textContent = 'Fetching the captain\'s log…'; $('title-note').className = 'muted small';
    try {
      const data = await api('/plank/' + (mode === 'daily' ? 'today' : 'endless') + '?player=' + encodeURIComponent(name));
      state = { session: data.session, mode, day: data.day, seconds: data.seconds || 25, prompts: data.prompts, i: 0, total: 0, answers: [], name };
      setDepth(0);
      round();
    } catch (e) {
      $('title-note').textContent = 'The ship\'s log is out of reach (' + e.message + '). Try again in a moment.'; $('title-note').className = 'small err';
    }
  }

  // ---------- rounds
  function round() {
    const p = state.prompts[state.i];
    show('screen-round');
    $('round-n').textContent = (state.i + 1) + ' of ' + state.prompts.length;
    $('round-mode').textContent = state.mode === 'daily' ? 'Today\'s plank · ' + state.day : 'Endless plank';
    $('prompt').textContent = p.text;
    $('answer').value = ''; $('answer').disabled = false; $('answer').focus();
    deadline = performance.now() + state.seconds * 1000;
    $('timer-bar').style.width = '100%'; $('timer-bar').className = '';
    clearInterval(timer);
    timer = setInterval(() => {
      const left = Math.max(0, deadline - performance.now());
      $('timer-bar').style.width = (left / (state.seconds * 1000) * 100) + '%';
      if (left < 6000) $('timer-bar').className = 'hot';
      if (left <= 0) { clearInterval(timer); submit(''); }
    }, 200);
  }
  $('answer-form').addEventListener('submit', e => { e.preventDefault(); submit($('answer').value); });

  async function submit(text) {
    if (!state || $('answer').disabled) return;
    clearInterval(timer); $('answer').disabled = true;
    const p = state.prompts[state.i];
    let res;
    try {
      res = await api('/plank/answer', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session: state.session, pid: p.id, answer: text.trim(), player: state.name }) });
    } catch (e) {
      res = { valid: false, points: 0, why: 'The ship\'s log is out of reach: ' + e.message, top: [], total: state.total };
    }
    state.answers.push({ prompt: p.text, raw: text.trim(), canonical: res.canonical || null, points: res.points || 0 });
    state.total = res.total != null ? res.total : state.total + (res.points || 0);
    setDepth(state.total * 10);
    reveal(res, text.trim());
  }

  function reveal(res, raw) {
    show('screen-reveal');
    const pts = res.valid ? res.points : 0;
    $('badge').textContent = res.valid ? pts + ' points · ' + TIER_WORDS[pts] : 'No points';
    $('badge').className = 'badge t' + pts;
    $('reveal-title').textContent = res.valid ? res.canonical : (raw ? '“' + raw + '”' : 'No answer');
    if (res.valid) {
      const pct = Math.round((res.share || 0) * 100);
      $('reveal-sub').textContent = (pct < 1 ? 'Fewer than one in a hundred' : pct + ' in a hundred') + ' of the crew said that' + (res.how === 'judged' ? ' (new to the log, checked by the Harbourmaster)' : '') + '. You sink ' + (pts * 10) + ' m.';
    } else {
      $('reveal-sub').textContent = res.why || 'The captain does not recognise that one.';
    }
    const list = $('top-list'); list.innerHTML = '';
    for (const [name, n] of res.top || []) { const li = document.createElement('li'); li.innerHTML = '<span>' + esc(name) + '</span><span>' + n + '</span>'; if (res.valid && name === res.canonical) li.className = 'mine'; list.appendChild(li); }
    $('btn-next').textContent = state.i + 1 < state.prompts.length ? 'Next question' : 'See how deep you went';
    $('btn-next').focus();
  }
  $('btn-next').addEventListener('click', () => { state.i++; if (state.i < state.prompts.length) round(); else finish(); });
  window.addEventListener('keydown', e => { if (e.key === 'Enter' && !$('screen-reveal').hidden) $('btn-next').click(); });

  // ---------- finish
  async function finish() {
    show('screen-done');
    const depth = state.total * 10;
    $('done-title').textContent = 'You reached ' + depthName(depth);
    $('done-depth').textContent = depth.toLocaleString();
    const clean = state.answers.filter(a => a.points > 0).length;
    $('done-sub').textContent = clean + ' of ' + state.prompts.length + ' answers landed' + (state.mode === 'daily' ? '. Come back tomorrow for the next seven.' : '. Another seven await on the endless plank.');
    const recap = $('recap'); recap.innerHTML = '';
    for (const a of state.answers) { const li = document.createElement('li'); li.innerHTML = '<span>' + esc(a.prompt) + ': <strong>' + esc(a.canonical || a.raw || '—') + '</strong></span><span>' + a.points + '</span>'; recap.appendChild(li); }
    if (state.mode === 'daily') {
      store.set('daily', { day: state.day, depth });
      const best = store.get('best', 0); if (depth > best) store.set('best', depth);
      try {
        const b = await api('/plank/board?day=' + state.day);
        const ol = $('board'); ol.innerHTML = '';
        for (const row of b.board) { const li = document.createElement('li'); li.innerHTML = '<span>' + esc(row.player) + '</span><span>' + row.depth.toLocaleString() + ' m</span>'; ol.appendChild(li); }
        $('board-note').textContent = b.board.length ? 'The deepest of today\'s crew, by name.' : 'Nobody with a name has finished today yet. Give yours on the deck and you will be on this board.';
      } catch (e) { $('board-note').textContent = 'The crew board is out of reach right now.'; }
    } else {
      $('board').innerHTML = ''; $('board-note').textContent = 'The endless plank does not count for the crew board.';
    }
  }
  $('btn-copy').addEventListener('click', async () => {
    const depth = state.total * 10;
    const text = 'Walk the Plank ' + state.day + ': ' + depth.toLocaleString() + ' m, ' + depthName(depth) + '. ' + state.answers.map(a => a.points ? (a.points >= 75 ? '🟣' : a.points >= 50 ? '🟠' : a.points >= 30 ? '🟢' : '⚪') : '⚫').join('') + ' berrychain.link/plank';
    try { await navigator.clipboard.writeText(text); $('btn-copy').textContent = 'Copied'; } catch (e) { prompt('Copy your result', text); }
  });
  $('btn-again').addEventListener('click', () => start('endless'));
  $('btn-home').addEventListener('click', () => { show('screen-title'); setDepth(0); });

  show('screen-title');
})();

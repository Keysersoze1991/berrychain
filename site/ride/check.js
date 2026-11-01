#!/usr/bin/env node
/* MTB Crazy referee. Reads {"level": n, "log": "..."} on stdin, replays the run on the same engine the
   page uses and prints what the clock said: {"finished": true, "time": ticks, ...} or {"finished": false}.
   Times are in ticks (60 per second). `node check.js --courses` lists the courses. Used by berrychain/ride.py. */
'use strict';
const MTB = require('./engine.js');

function out(o) { process.stdout.write(JSON.stringify(o) + '\n'); }

if (process.argv.includes('--courses')) {
  out(MTB.LEVELS.map((lv, i) => ({ level: i, name: lv.name, tier: MTB.TIERS[Math.floor(i / 5)], length: Math.round(lv.length) })));
  process.exit(0);
}

let buf = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', c => { buf += c; if (buf.length > 200000) { out({ error: 'too large' }); process.exit(2); } });
process.stdin.on('end', () => {
  let q;
  try { q = JSON.parse(buf); } catch (e) { out({ error: 'bad json' }); process.exit(2); }
  const masks = typeof q.log === 'string' ? MTB.decodeLog(q.log) : Array.isArray(q.log) ? q.log.map(m => (m | 0) & 31) : null;
  if (!masks) { out({ error: 'bad log' }); process.exit(2); }
  const level = q.level | 0;
  if (!(level >= 0 && level < MTB.LEVELS.length)) { out({ error: 'no such course' }); process.exit(2); }
  const r = MTB.replay(level, masks);
  out(r ? Object.assign({ finished: true, level, course: MTB.LEVELS[level].name }, r) : { finished: false, level, course: MTB.LEVELS[level].name });
});

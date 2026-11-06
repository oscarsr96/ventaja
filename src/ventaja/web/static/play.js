// The possession player: scrub or play the recorded frames on the board, with a cursor on the advantage curve.
import { api } from '/static/app.js';
import { showFrame } from '/static/board.js';
import { setCursor } from '/static/curve.js';

const NO_DATA = 'No play data: run `ventaja frames build` with the tracking.';
const EPS = 0.02;                    // half a frame: closer than this to decision_t counts as the decision
let ui = null;                       // {bar, btn, dec, range, tLbl, cLbl, msg}
let play = null;                     // the loaded /api/play payload, or null
let t = 0;                           // current playback time, seconds relative to release
let raf = 0, playing = false, token = 0;

function box(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}
const fmtT = (v) => (v < 0 ? '−' : '') + Math.abs(v).toFixed(1) + ' s';

function nearest(frames, v) {        // frames are sorted by t
  let lo = 0, hi = frames.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (frames[mid].t < v) lo = mid; else hi = mid; }
  return Math.abs(frames[lo].t - v) <= Math.abs(frames[hi].t - v) ? frames[lo] : frames[hi];
}
function setEnabled(on) { for (const e of [ui.btn, ui.dec, ui.range]) e.disabled = !on; }
function setPlaying(on) {
  playing = on;
  ui.btn.textContent = on ? 'Pause' : 'Play';
  if (!on && raf) { cancelAnimationFrame(raf); raf = 0; }
}

// Show time v. `live` (inside the animation loop) never snaps to the decision position.
function seek(v, live) {
  if (!play || !play.frames.length) return;
  t = Math.min(play.t1, Math.max(play.t0, v));
  ui.range.value = String(t);
  const fr = nearest(play.frames, t);
  ui.tLbl.textContent = fmtT(t);
  ui.cLbl.textContent = fr.clock === null || fr.clock === undefined ? 'clock unknown' : 'shot clock ' + fr.clock.toFixed(1) + ' s';
  if (!live && Math.abs(t - play.decision_t) <= EPS) {
    t = play.decision_t;
    showFrame(null); setCursor(play.decision_t);
  } else { showFrame(fr); setCursor(t); }
}
function tick(now0) {
  let last = now0;
  const step = (now) => {
    if (!playing) return;
    const next = t + (now - last) / 1000;
    last = now;
    if (next >= play.t1) { seek(play.t1, true); setPlaying(false); return; }
    seek(next, true);
    raf = requestAnimationFrame(step);
  };
  raf = requestAnimationFrame(step);
}
function toggle() {
  if (!play) return;
  if (playing) { setPlaying(false); return; }
  if (t >= play.t1 - EPS) seek(play.t0, true);
  setPlaying(true);
  tick(performance.now());
}

export function mountPlay(host) {
  host.textContent = '';
  const bar = box('div', undefined, 'card playbar');
  const btn = box('button', 'Play'); btn.type = 'button';
  const dec = box('button', 'Decision'); dec.type = 'button';
  const range = document.createElement('input');
  range.type = 'range'; range.step = '0.04'; range.min = '0'; range.max = '1'; range.value = '0';
  range.setAttribute('aria-label', 'Time in the possession');
  const tLbl = box('span', '', 'k'), cLbl = box('span', '', 'k'), msg = box('span', '', 'hint');
  for (const e of [btn, dec, range, tLbl, cLbl, msg]) bar.appendChild(e);
  host.appendChild(bar);
  ui = { bar: bar, btn: btn, dec: dec, range: range, tLbl: tLbl, cLbl: cLbl, msg: msg };
  btn.addEventListener('click', toggle);
  dec.addEventListener('click', () => { if (!play) return; setPlaying(false); seek(play.decision_t); });
  range.addEventListener('input', () => { if (!play) return; setPlaying(false); seek(Number(range.value)); });
  setEnabled(false);
}

export async function loadPlay(shotId) {
  if (!ui) return;
  const mine = ++token;
  stop();
  play = null; setEnabled(false);
  ui.msg.textContent = ''; ui.tLbl.textContent = ''; ui.cLbl.textContent = '';
  let p;
  try { p = await api('/api/play/' + encodeURIComponent(shotId)); }
  catch (e) {
    if (mine === token) ui.msg.textContent = NO_DATA;
    return;
  }
  if (mine !== token) return;
  if (!p || !Array.isArray(p.frames) || !p.frames.length) { ui.msg.textContent = NO_DATA; return; }
  play = p;
  ui.range.min = String(p.t0); ui.range.max = String(p.t1);
  setEnabled(true);
  setPlaying(false);
  seek(p.decision_t);
  showFrame(null);
}

export function stop() {
  setPlaying(false);
  showFrame(null);
  setCursor(null);
  if (play && ui) {   // the board is back at the decision: make the bar say so too
    t = play.decision_t; ui.range.value = String(t); ui.tLbl.textContent = fmtT(t);
    const fr = nearest(play.frames, t);
    ui.cLbl.textContent = fr.clock === null || fr.clock === undefined ? 'clock unknown' : 'shot clock ' + fr.clock.toFixed(1) + ' s';
  }
}

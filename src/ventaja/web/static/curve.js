// Advantage curve: the real possession's shot value vs best pass value over time, drawn as inline SVG.
import { api, fmt } from '/static/app.js';

const NS = 'http://www.w3.org/2000/svg';
const W = 640, H = 240, L = 40, R = 12, T = 18, B = 28;
const SHOOTER = '#2457a6', PASS = '#1b1f24';
let drawn = null, token = 0;

function el(tag, attrs, text) {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text !== undefined) e.textContent = text;
  return e;
}

function path(rows, key, sx, sy) {
  let d = '', pen = false;
  for (const r of rows) {
    const v = r[key];
    if (v === null || v === undefined) { pen = false; continue; }
    d += (pen ? 'L' : 'M') + sx(r.t).toFixed(1) + ' ' + sy(v).toFixed(1);
    pen = true;
  }
  return d;
}

function draw(c) {
  const rows = c.rows;
  const t0 = Math.min(...rows.map((r) => r.t)), t1 = Math.max(0, ...rows.map((r) => r.t));
  const vals = rows.flatMap((r) => [r.handler_shot_value, r.best_pass_value]).filter((v) => v !== null && v !== undefined);
  const vmax = Math.max(2.5, ...vals);
  const sx = (t) => L + ((t - t0) / (t1 - t0 || 1)) * (W - L - R);
  const sy = (v) => H - B - (v / vmax) * (H - T - B);
  const svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', width: '100%', 'aria-label': 'Advantage curve' });
  svg.style.display = 'block';
  if (c.window) {
    const a = sx(Math.max(t0, c.window[0])), b = sx(Math.min(t1, c.window[1]));
    svg.appendChild(el('rect', { x: a, y: T, width: Math.max(0, b - a), height: H - T - B, fill: '#f4c542', opacity: 0.3 }));
  }
  svg.appendChild(el('line', { x1: L, y1: H - B, x2: W - R, y2: H - B, stroke: '#5f6b76' }));
  svg.appendChild(el('line', { x1: L, y1: T, x2: L, y2: H - B, stroke: '#5f6b76' }));
  for (const v of [0, vmax / 2, vmax]) svg.appendChild(el('text', { x: L - 4, y: sy(v) + 3, 'text-anchor': 'end', 'font-size': 10, fill: '#5f6b76' }, fmt.num(v, 1)));
  svg.appendChild(el('text', { x: W - R, y: H - 4, 'text-anchor': 'end', 'font-size': 10, fill: '#5f6b76' }, 'seconds to release'));
  svg.appendChild(el('text', { x: L, y: H - 4, 'text-anchor': 'start', 'font-size': 10, fill: '#5f6b76' }, fmt.num(t0, 1) + ' s'));
  const marks = [[c.decision_t, 'decision', '4 3'], [0, 'release', '']];
  for (const [t, label, dash] of marks) {
    if (t === null || t === undefined) continue;
    const x = sx(t);
    const ln = el('line', { x1: x, y1: T, x2: x, y2: H - B, stroke: '#c62828', 'stroke-width': 1.2 });
    if (dash) ln.setAttribute('stroke-dasharray', dash);
    svg.appendChild(ln);
    // labels end just left of their line, or start right of it when that would run into the y-axis gutter;
    // decision sits one row lower than release so the words never touch in either anchoring
    const row = label === 'release' ? T - 5 : T + 8;
    const near = x - L < 50;
    svg.appendChild(el('text', { x: near ? x + 3 : x - 3, y: row, 'text-anchor': near ? 'start' : 'end', 'font-size': 10, fill: '#c62828' }, label));
  }
  svg.appendChild(el('path', { d: path(rows, 'handler_shot_value', sx, sy), fill: 'none', stroke: SHOOTER, 'stroke-width': 2 }));
  svg.appendChild(el('path', { d: path(rows, 'best_pass_value', sx, sy), fill: 'none', stroke: PASS, 'stroke-width': 2 }));
  let prev = null;
  for (const r of rows) {
    if (r.handler_id !== prev) {
      const jer = c.handlers && c.handlers[String(r.handler_id)];
      if (jer !== undefined) svg.appendChild(el('text', { x: sx(r.t) + 2, y: H - B - 4, 'font-size': 10, fill: '#5f6b76' }, '#' + jer));
      prev = r.handler_id;
    }
  }
  return svg;
}

function legend() {
  const d = document.createElement('div');
  d.style.cssText = 'font-size:12px;color:#5f6b76;display:flex;gap:12px;flex-wrap:wrap';
  for (const [col, txt] of [[SHOOTER, 'handler shot value'], [PASS, 'best pass value']]) {
    const s = document.createElement('span'); const i = document.createElement('b');
    i.style.cssText = 'display:inline-block;width:14px;height:3px;margin-right:4px;vertical-align:middle;background:' + col;
    s.appendChild(i); s.appendChild(document.createTextNode(txt)); d.appendChild(s);
  }
  return d;
}

export async function showCurve(host, shotId) {
  if (!host || drawn === shotId && host.firstChild) return;   // moves on the board do not change the curve
  const mine = ++token;
  let c;
  try { c = await api('/api/curve/' + encodeURIComponent(shotId)); }
  catch (e) {
    if (mine !== token) return;
    drawn = null; host.textContent = '';
    const p = document.createElement('p'); p.className = 'hint'; p.textContent = 'No advantage curve for this shot: ' + e.message;
    host.appendChild(p); return;
  }
  if (mine !== token) return;
  drawn = shotId; host.textContent = '';
  const card = document.createElement('div'); card.className = 'card';
  card.appendChild(draw(c)); card.appendChild(legend());
  const note = document.createElement('p'); note.className = 'hint';
  note.textContent = 'The curve values the real possession; moves on the board do not change it.';
  card.appendChild(note); host.appendChild(card);
}

export function mount(section) {}
export function update(state) {}

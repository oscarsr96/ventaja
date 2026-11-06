// The whiteboard: SVG court, 2.5D projection, drag-to-move players, undo/reset.
// Moved from the former single-page index.html; header, table and headline now live in shot.js.
const NS = 'http://www.w3.org/2000/svg';
const R = 1.5;                       // player radius, feet
const V_LO = 0.6, V_HI = 1.5;        // fixed colour scale, same as the GIFs
const STOPS = [[68,1,84],[59,82,139],[33,145,140],[94,201,98],[253,231,37]]; // viridis, 5 stops
const DEBOUNCE_MS = 150;
const K = 0.25, DEPTH = 0.55, U0 = 0, V0 = 0;   // 2.5D: oblique skew, depth compression, offsets (feet)
const VIEWS = { '2D': '-49 -28.5 61 57', '2.5D': '-30.15 -40.5 74 42.5' };

const $ = (id) => document.getElementById(id);
let svg = null;                      // set by mountBoard
let onPayload = () => {};            // set by mountBoard
let onSelect = () => {};             // user picked a shot in the board selects
let ready = null;                    // resolves once court and shots are loaded
let court = null;                    // /api/court payload
let shots = [];                      // /api/shots rows
let shotId = null;                   // selected shot
let payload = null;                  // latest applied payload
const moves = new Map();             // player_id -> {x, y}; insertion order = move recency
let dragId = null;                   // player being dragged right now
let grab = { dx: 0, dy: 0 };         // pointer-to-centre offset at pointerdown
let lastPost = 0;                    // time of the last evaluate, for the leading-edge throttle
let seq = 0;                         // request sequence counter; only the newest response is applied
let loadError = null;               // message of the last failed loadShot
let timer = null;                    // debounce timer
const nodes = new Map();             // player_id -> {g, circle, num, lbl}
let arrow = null, ballEl = null, ground = null, figures = null, shadows = null, bcLbl = null;
let view = '2.5D';                   // '2.5D' | '2D', remembered in localStorage

function el(tag, attrs, parent, text) {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text !== undefined) e.textContent = text;
  if (parent) parent.appendChild(e);
  return e;
}
export function h(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}
export const f = (v, d) => (v === null || v === undefined || Number.isNaN(v)) ? '-' : Number(v).toFixed(d);

export function viridis(value) {
  const t = Math.min(1, Math.max(0, (value - V_LO) / (V_HI - V_LO)));
  const s = t * (STOPS.length - 1), i = Math.min(STOPS.length - 2, Math.floor(s)), u = s - i;
  const c = STOPS[i].map((a, k) => Math.round(a + (STOPS[i + 1][k] - a) * u));
  return { css: 'rgb(' + c.join(',') + ')', t: t };
}

/* ---------- status and network ---------- */
function setStatus(msg, info) {
  const s = $('status');
  s.textContent = msg || '';
  s.className = info ? 'info' : '';
}
export async function request(url, opts) { return parse(await fetch(url, opts)); }
async function parse(resp) {
  let body = null;
  try { body = await resp.json(); } catch (e) { body = null; }
  if (!resp.ok) {
    let d = body && body.detail;
    if (Array.isArray(d)) d = d.map((x) => (x.loc ? x.loc.join('.') + ': ' : '') + x.msg).join('; ');
    throw new Error(d || ('HTTP ' + resp.status));
  }
  return body;
}

/* ---------- court (static lines, y flipped so +y is up) ---------- */
function drawCourt() {
  el('rect', { x: -49, y: -28.5, width: 61, height: 57, fill: '#f2d9a8', rx: 1 }, ground);
  el('rect', { x: 0, y: -28.5, width: 12, height: 57, fill: '#dcc08b' }, ground);   // backcourt strip
  bcLbl = el('text', { 'text-anchor': 'middle', 'font-size': 1.4, fill: '#8a7448' }, svg, 'backcourt');   // screen space, see setView
  const c = court, g = el('g', { fill: 'none', stroke: '#222', 'stroke-width': 0.18 }, ground);
  const base = -c.half_length, side = c.width / 2, hx = c.hoop[0], hy = c.hoop[1];
  const line = (x1, y1, x2, y2) => el('line', { x1: x1, y1: -y1, x2: x2, y2: -y2 }, g);
  line(base, -side, base, side); line(base, side, 0, side);
  line(base, -side, 0, -side); line(0, -side, 0, side);
  el('circle', { cx: hx, cy: -hy, r: 0.75 }, g);
  el('path', { d: 'M' + hx + ' ' + (-hy - c.ra_radius) + ' A' + c.ra_radius + ' ' + c.ra_radius + ' 0 0 1 ' + hx + ' ' + (-hy + c.ra_radius) }, g);
  el('rect', { x: base, y: -c.key_half_width, width: c.key_x_max - base, height: 2 * c.key_half_width }, g);
  el('circle', { cx: c.key_x_max, cy: 0, r: 6 }, g);
  for (const y of [-c.corner_y, c.corner_y]) line(base, y, c.corner_x_max, y);
  const r = c.three_point_radius;
  el('path', { d: 'M' + c.corner_x_max + ' ' + (-c.corner_y) + ' A' + r + ' ' + r + ' 0 0 1 ' + c.corner_x_max + ' ' + c.corner_y }, g);
}
function initSvg() {
  const defs = el('defs', {}, svg);
  const m = el('marker', { id: 'ah', viewBox: '0 0 10 10', refX: 8, refY: 5, markerWidth: 5, markerHeight: 5, orient: 'auto-start-reverse' }, defs);
  el('path', { d: 'M0 0L10 5L0 10z', fill: '#c0392b' }, m);
  ground = el('g', { id: 'ground' }, svg);
  drawCourt();
  figures = el('g', { id: 'figures' }, svg);
  shadows = el('g', { 'pointer-events': 'none' }, ground);
  arrow = el('line', { stroke: '#c0392b', 'stroke-width': 0.45, 'marker-end': 'url(#ah)', 'pointer-events': 'none', visibility: 'hidden' }, ground);
  const stops = STOPS.map((c, i) => 'rgb(' + c.join(',') + ') ' + (i * 25) + '%').join(',');
  $('legendBar').style.background = 'linear-gradient(90deg,' + stops + ')';
}

/* ---------- views: one affine matrix on #ground, figures projected by hand ---------- */
// 2.5D: U = K*x + y + K*HL + U0, V = -DEPTH*(x + HL) + V0. On the drawn coords (x, -y) that is
// matrix(a b c d e f) with a=K, b=-DEPTH, c=-1, d=0, e=K*HL+U0, f=-DEPTH*HL+V0.
function project(x, y) {
  if (view === '2D') return [x, -y];
  const hl = court.half_length;
  return [K * (x + hl) + y + U0, -DEPTH * (x + hl) + V0];
}
function setView(v) {
  view = v === '2D' ? '2D' : '2.5D';
  $('viewSel').value = view;
  const hl = court.half_length, iso = view !== '2D';
  ground.setAttribute('transform', iso ? 'matrix(' + [K, -DEPTH, -1, 0, K * hl + U0, -DEPTH * hl + V0].join(' ') + ')' : 'matrix(1 0 0 1 0 0)');
  svg.setAttribute('viewBox', VIEWS[view]);
  svg.style.aspectRatio = VIEWS[view].split(' ').slice(2).join('/');
  const b = project(6, 26.5);
  bcLbl.setAttribute('x', b[0]); bcLbl.setAttribute('y', b[1]);
  shadows.setAttribute('display', iso ? '' : 'none');
  for (const n of nodes.values()) { n.flat.setAttribute('display', iso ? 'none' : ''); n.iso.setAttribute('display', iso ? '' : 'none'); }
}

/* ---------- players ---------- */
function buildPlayers(p) {
  for (const n of nodes.values()) { n.g.remove(); n.shadow.remove(); n.ring.remove(); }
  nodes.clear();
  if (ballEl) ballEl.remove();
  for (const pl of p.players) {
    const shadow = el('circle', { r: R, fill: 'rgba(0,0,0,.25)' }, shadows);
    const ring = el('circle', { r: R + 0.3, fill: 'none', stroke: '#333', 'stroke-width': 0.2, 'stroke-dasharray': '0.5 0.35' }, shadows);
    const g = el('g', { class: 'player' }, figures);
    const flat = el('g', {}, g);                                   // 2D: circle marker
    const circle = el('circle', { r: R }, flat);
    const num = el('text', { y: 0.5, 'font-size': 1.4 }, flat);
    const lbl = el('text', { y: R + 1.5, class: 'lbl', 'text-anchor': 'middle' }, flat);
    const iso = el('g', { transform: 'scale(0.072)' }, g);         // 2.5D: silhouette, 100 units tall
    el('rect', { x: -28, y: -100, width: 56, height: 100, fill: 'transparent' }, iso);   // hit area
    const body = el('path', { d: 'M-15,-76 L15,-76 L19,-40 L11,-40 L13,-2 L4,-2 L1,-36 L-1,-36 L-4,-2 L-13,-2 L-11,-40 L-19,-40 Z' }, iso);
    const head = el('circle', { cx: 0, cy: -88, r: 11 }, iso);
    const armD = 'M-15,-74 L-27,-46 L-21,-43 L-11,-62 M15,-74 L27,-46 L21,-43 L11,-62', armA = { d: armD, fill: 'none', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' };
    const armsOut = el('path', armA, iso);                          // outline colour, wider
    const arms = el('path', Object.assign({ 'stroke-width': 7 }, armA), iso);   // fill colour on top
    const inum = el('text', { x: 0, y: -52, 'font-size': 18 }, iso);
    const ilbl = el('text', { x: 0, y: -104, class: 'lbl5' }, iso);
    g.addEventListener('pointerdown', (ev) => startDrag(ev, pl.player_id, g));
    g.addEventListener('pointermove', (ev) => onDrag(ev, pl.player_id));
    g.addEventListener('pointerup', (ev) => endDrag(ev, pl.player_id, g));
    g.addEventListener('pointercancel', (ev) => endDrag(ev, pl.player_id, g));
    nodes.set(pl.player_id, { g: g, flat: flat, iso: iso, circle: circle, num: num, lbl: lbl, shadow: shadow, ring: ring, body: body, head: head, arms: arms, armsOut: armsOut, inum: inum, ilbl: ilbl });
  }
  ballEl = el('circle', { r: 0.8, fill: '#f08a24', stroke: '#7a3b00', 'stroke-width': 0.2, 'pointer-events': 'none' }, figures);
  setView(view);
}
export function jersey(pl) { return pl.jersey !== null && pl.jersey !== undefined ? String(pl.jersey) : String(pl.player_id).slice(-2); }

function place(id, x, y) {
  const n = nodes.get(id);
  if (!n) return;
  const u = project(x, y);
  n.g.setAttribute('transform', 'translate(' + u[0] + ' ' + u[1] + ')');   // figure: screen space
  for (const e of [n.shadow, n.ring]) { e.setAttribute('cx', x); e.setAttribute('cy', -y); }   // ground: feet
}
function currentPos(pl) {
  if (dragId === pl.player_id && moves.has(pl.player_id)) return moves.get(pl.player_id);
  return { x: pl.x, y: pl.y };
}

function render() {
  if (!payload) return;
  const optBy = drawBoard(payload);
  onPayload(payload, optBy);
}
function drawBoard(p) {
  const optBy = new Map(p.options.map((o) => [o.player_id, o]));
  const pos = new Map(), iso = view !== '2D';
  for (const pl of p.players) {
    const n = nodes.get(pl.player_id), o = optBy.get(pl.player_id), q = currentPos(pl);
    pos.set(pl.player_id, q);
    place(pl.player_id, q.x, q.y);
    let fill = '#9aa3ab', txt = '#fff';
    if (pl.side === 'offense') {
      const v = o ? viridis(o.adjusted_value) : { css: '#ccc', t: 0 };
      fill = v.css; txt = v.t > 0.6 ? '#111' : '#fff';
    }
    const moved = pl.moved || moves.has(pl.player_id), val = pl.side === 'offense' && o ? f(o.adjusted_value, 2) : '';
    n.circle.setAttribute('fill', fill);
    n.circle.setAttribute('stroke', pl.is_shooter ? '#000' : '#333');
    n.circle.setAttribute('stroke-width', pl.is_shooter ? 0.55 : 0.2);
    n.circle.setAttribute('stroke-dasharray', moved ? '0.5 0.35' : '');
    n.num.setAttribute('fill', txt);
    n.num.textContent = jersey(pl);
    n.num.classList.toggle('fb', pl.jersey === null || pl.jersey === undefined);
    n.lbl.setAttribute('y', q.y < -22 ? -(R + 0.6) : R + 1.5);   // keep the label off the sideline
    n.lbl.textContent = val;
    n.body.setAttribute('fill', fill); n.head.setAttribute('fill', fill); n.arms.setAttribute('stroke', fill);
    n.armsOut.setAttribute('stroke', pl.is_shooter ? '#000' : '#333');
    n.armsOut.setAttribute('stroke-width', pl.is_shooter ? 13 : 9.4);   // 7 + 2 * outline width
    for (const e of [n.body, n.head]) {
      e.setAttribute('stroke', pl.is_shooter ? '#000' : '#333');
      e.setAttribute('stroke-width', pl.is_shooter ? 3 : 1.2);
    }
    n.inum.setAttribute('fill', txt); n.inum.textContent = jersey(pl);
    n.inum.classList.toggle('fb', pl.jersey === null || pl.jersey === undefined);
    n.ilbl.textContent = val;
    n.ring.setAttribute('display', moved ? '' : 'none');
    n.g.classList.toggle('drag', dragId === pl.player_id);
  }
  if (iso && dragId === null) {   // far players first; re-parenting the dragged node would drop its pointer capture
    const order = p.players.map((pl) => ({ n: nodes.get(pl.player_id), x: currentPos(pl).x })).sort((a, b) => b.x - a.x);
    for (const e of order) figures.appendChild(e.n.g);
  }
  const s = pos.get(p.shooter_id);
  const alt = p.best_alt_player_id === null || p.best_alt_player_id === undefined ? null : pos.get(p.best_alt_player_id);
  if (s && alt) {
    const dx = alt.x - s.x, dy = alt.y - s.y, d = Math.hypot(dx, dy) || 1;
    arrow.setAttribute('x1', s.x + dx / d * R); arrow.setAttribute('y1', -(s.y + dy / d * R));
    arrow.setAttribute('x2', alt.x - dx / d * (R + 0.4)); arrow.setAttribute('y2', -(alt.y - dy / d * (R + 0.4)));
    arrow.setAttribute('visibility', d > 2 * R ? 'visible' : 'hidden');
  } else arrow.setAttribute('visibility', 'hidden');
  if (s) {
    const b = view === '2D' ? [s.x + 1.2, -(s.y - 1.2)] : project(s.x, s.y);
    ballEl.setAttribute('cx', view === '2D' ? b[0] : b[0] + 1.4); ballEl.setAttribute('cy', view === '2D' ? b[1] : b[1] - 4.6);
  }
  figures.appendChild(ballEl);
  return optBy;
}

export function hasJersey(pl) { return pl.jersey !== null && pl.jersey !== undefined; }

/* ---------- drag, debounce, evaluate ---------- */
function toFeet(ev) {
  const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY;
  const q = pt.matrixTransform(ground.getScreenCTM().inverse());
  return { x: q.x, y: -q.y };
}
function clampToCourt(q) {   // the server clamps too: a backcourt player snaps to the half line
  const hl = court.half_length, hw = court.width / 2;
  return { x: Math.min(0, Math.max(-hl, q.x)), y: Math.min(hw, Math.max(-hw, q.y)) };
}
function startDrag(ev, id, g) {
  if (!payload) return;
  ev.preventDefault();
  const pl = payload.players.find((x) => x.player_id === id), at = moves.get(id) || pl, m = toFeet(ev);
  grab = { dx: at.x - m.x, dy: at.y - m.y };   // keep the point of the circle that was grabbed
  dragId = id;
  g.setPointerCapture(ev.pointerId);
  g.classList.add('drag');
}
function onDrag(ev, id) {
  if (dragId !== id) return;
  const m = toFeet(ev), q = clampToCourt({ x: m.x + grab.dx, y: m.y + grab.dy });
  moves.delete(id); moves.set(id, q);          // re-insert: this player is now the most recent
  drawBoard(payload);                          // circle, label, arrow and ball follow at once
  clearTimeout(timer);
  const wait = lastPost + DEBOUNCE_MS - Date.now();   // first move posts now, then at most every 150 ms
  if (wait <= 0) evaluate(); else timer = setTimeout(evaluate, wait);
}
function endDrag(ev, id, g) {
  if (dragId !== id) return;
  if (g.hasPointerCapture(ev.pointerId)) g.releasePointerCapture(ev.pointerId);
  dragId = null;
  clearTimeout(timer);
  if (moves.has(id)) evaluate(); else render();
}
async function evaluate() {
  clearTimeout(timer);
  if (!shotId) return;
  if (moves.size === 0) { await loadShot(shotId); return; }
  const mine = ++seq;
  lastPost = Date.now();
  const body = { moves: Array.from(moves, ([player_id, q]) => ({ player_id: player_id, x: q.x, y: q.y })) };
  try {
    const p = await request('/api/shot/' + encodeURIComponent(shotId) + '/evaluate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (mine !== seq) return;                  // a newer request is in flight
    for (const m of p.moves) if (moves.has(m.player_id) && dragId !== m.player_id) moves.set(m.player_id, { x: m.x, y: m.y });
    payload = p; setStatus('');
    render();
  } catch (e) {
    if (mine === seq) setStatus('Evaluate failed: ' + e.message);
  }
}
async function loadShot(id) {
  const mine = ++seq;
  try {
    const p = await request('/api/shot/' + encodeURIComponent(id));
    if (mine !== seq) return null;
    if (payload === null || !nodes.size) buildPlayers(p);
    payload = p; setStatus('');
    render();
    return null;
  } catch (e) {
    if (mine === seq) { loadError = e.message; setStatus('Could not load shot: ' + e.message); }
    return e.message;
  }
}
function selectShot(id) {
  shotId = id; moves.clear(); dragId = null; clearTimeout(timer); payload = null;
  return loadShot(id);
}
function reset() { moves.clear(); clearTimeout(timer); if (shotId) loadShot(shotId); }
function undo() {
  if (moves.size === 0) { setStatus('Nothing to undo.', true); return; }
  const last = Array.from(moves.keys()).pop();
  moves.delete(last);
  evaluate();
}


/* ---------- selectors and start ---------- */
const HOST = `
  <div class="card">
    <h1>ventaja board</h1>
    <div id="controls">
      <select id="gameSel" aria-label="Game"></select>
      <select id="shotSel" aria-label="Shot"></select>
      <select id="viewSel" aria-label="View"><option value="2.5D">2.5D</option><option value="2D">2D</option></select>
      <button id="resetBtn" type="button">Reset</button>
      <button id="undoBtn" type="button">Undo last</button>
    </div>
  </div>
  <div class="card" id="courtWrap">
    <svg id="court" xmlns="http://www.w3.org/2000/svg" viewBox="-49 -28.5 61 57" role="img" aria-label="Half court with the ten players"></svg>
    <div id="legend"><span>adjusted value</span><i id="legendBar"></i><span id="legendTxt">0.6 &rarr; 1.5 (offense); defense grey; ball orange; thick black outline = shooter; dashed ring = moved; silhouette height is not real height</span></div>
    <div class="hint">Drag any player; the five option values recompute as you move.</div>
  </div>
  <div id="status" class="info" role="status"></div>`;
function fillShots(game, pick) {
  const sel = $('shotSel');
  sel.textContent = '';
  for (const s of shots.filter((x) => String(x.game_id) === String(game))) {
    const o = document.createElement('option');
    o.value = s.shot_id;
    o.textContent = s.shot_id + ' · ' + (s.shooter || s.shooter_id) + ' · ' + (s.team || '-') + ' · cost ' + f(s.cost, 2);
    sel.appendChild(o);
  }
  if (pick) sel.value = pick;
}
export { setStatus };
export function getShots() { return shots; }
export function getState() { return { shotId: shotId, payload: payload, moves: moves, shots: shots, view: view }; }
// Show a shot in the board; resolves to null, or to the error message when it cannot be loaded.
export async function showShot(id) {
  await ready;
  const row = shots.find((x) => x.shot_id === id);
  if (row) { $('gameSel').value = String(row.game_id); fillShots(row.game_id, id); }
  if (id === shotId && payload && moves.size === 0) return null;
  shotId = id; moves.clear(); dragId = null; clearTimeout(timer); payload = null;
  loadError = null;
  const err = await loadShot(id);
  return err || loadError;
}
export function mountBoard(host, opts) {
  onPayload = (opts && opts.onPayload) || onPayload;
  onSelect = (opts && opts.onSelect) || onSelect;
  host.innerHTML = HOST;
  svg = $('court');
  ready = start();
  return ready;
}
async function start() {
  try {
    court = await request('/api/court');
    shots = await request('/api/shots');
  } catch (e) { setStatus('Could not load court or shots: ' + e.message); return; }
  initSvg();
  try { view = localStorage.getItem('ventaja.board.view') === '2D' ? '2D' : '2.5D'; } catch (e) { view = '2.5D'; }
  setView(view);
  if (!shots.length) { setStatus('No valued shots to show.', true); return; }
  const games = Array.from(new Set(shots.map((s) => s.game_id)));
  for (const g of games) { const o = document.createElement('option'); o.value = String(g); o.textContent = 'game ' + g; $('gameSel').appendChild(o); }
  $('gameSel').addEventListener('change', () => { fillShots($('gameSel').value); if ($('shotSel').value) onSelect($('shotSel').value); });
  $('shotSel').addEventListener('change', (ev) => onSelect(ev.target.value));
  $('viewSel').addEventListener('change', (ev) => {
    setView(ev.target.value);
    try { localStorage.setItem('ventaja.board.view', view); } catch (e) { /* storage may be blocked */ }
    render();
  });
  $('resetBtn').addEventListener('click', reset);
  $('undoBtn').addEventListener('click', undo);
}

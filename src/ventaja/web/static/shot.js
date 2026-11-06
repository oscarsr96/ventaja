// The Shot view: header, headline, options table, clip, featured list and the other shots of the game.
import { mountBoard, showShot, getState, setStatus, jersey, viridis, hasJersey, f, h } from '/static/board.js';
import { api, navigate, fmt } from '/static/app.js';
import { showCurve } from '/static/curve.js';

const $ = (id) => document.getElementById(id);
const FEATURED_LABELS = { worst: 'Worst decisions', best: 'Best reads', late: 'Lost moments' };
let featured = null, reel = null, current = null, token = 0;

function field(label, valueNode) {
  const d = h('div'); d.appendChild(h('span', label, 'k')); valueNode.classList.add('v'); d.appendChild(valueNode); return d;
}
function clock(p) { return p.shot_clock === null || p.shot_clock === undefined ? 'clock unknown' : f(p.shot_clock, 1) + ' s on shot clock'; }
function playerLabel(pl) { return (hasJersey(pl) ? '#' + jersey(pl) : '(id ..' + jersey(pl) + ')') + ' ' + (pl.name || '-'); }
function renderHeader(p) {
  const hd = $('head'); hd.textContent = '';
  const sh = p.players.find((x) => x.player_id === p.shooter_id);
  const shots = getState().shots, moves = getState().moves;
  const row = shots.find((x) => x.shot_id === p.shot_id);
  const team = (row && row.team) || (sh && sh.team_id !== null ? 'team ' + sh.team_id : '-');
  hd.appendChild(field('Shooter', h('div', (sh ? playerLabel(sh) : String(p.shooter_id)) + ' · ' + team)));
  hd.appendChild(field('Rule · period · clock', h('div', p.rule + ' · P' + p.period + ' · ' + clock(p))));
  const alt = p.best_alt_value === null || p.best_alt_value === undefined;
  hd.appendChild(field('Shot value → best alternative', h('div', f(p.shot_value, 3) + ' → ' + (alt ? 'no viable pass' : f(p.best_alt_value, 3)))));
  const cost = h('div'); cost.appendChild(document.createTextNode(f(p.original_cost, 3) + ' → ' + f(p.cost, 3) + ' '));
  const dc = Math.abs(p.delta_cost) < 5e-4 ? 0 : p.delta_cost;   // float noise is not a change
  const dl = h('span', '(' + (dc > 0 ? '+' : '') + f(dc, 3) + ')', dc < 0 ? 'good' : dc > 0 ? 'bad' : '');
  cost.appendChild(dl);
  hd.appendChild(field('Cost: original → current (delta)', cost));
  if (sh && (sh.moved || moves.has(p.shooter_id))) hd.appendChild(h('div', 'The shot is valued from the new position.', '')).id = 'moveNote';
}
function renderTable(p) {
  const t = $('optTable'); t.textContent = '';
  const heads = ['', 'no.', 'type', 'zone', 'P', 'val', 'viab', 'adj', 'alt', 'name'];
  const tr = h('tr');
  heads.forEach((x, i) => tr.appendChild(h('th', x, i === 0 || i === 2 || i === 3 || i >= 8 ? 'l' : '')));
  t.appendChild(tr);
  const byId = new Map(p.players.map((x) => [x.player_id, x]));
  for (const o of p.options) {
    const pl = byId.get(o.player_id) || {};
    const mark = o.player_id === p.shooter_id ? '*' : (o.player_id === p.best_alt_player_id ? '>' : ' ');
    const r = h('tr', undefined, mark === '*' ? 'shooter' : mark === '>' ? 'alt' : '');
    const sw = h('td', undefined, 'sw'), b = h('b', jersey(pl)), v = viridis(o.adjusted_value);
    b.style.background = v.css; b.classList.toggle('fb', !hasJersey(pl)); b.style.color = v.t > 0.6 ? '#111' : '#fff'; sw.appendChild(b);
    const cells = [mark, null, o.option_type, o.zone, f(o.proba, 2), f(o.value, 3), f(o.viability, 2), f(o.adjusted_value, 3), o.alternative_type || '-', pl.name || '-'];
    cells.forEach((c, i) => {
      if (c === null) { r.appendChild(sw); return; }
      const td = h('td', String(c), (i === 0 || i === 2 || i === 3 || i >= 8 ? 'l' : '') + (i === 9 ? ' nm' : ''));
      if (i === 9) td.title = String(c);
      r.appendChild(td);
    });
    t.appendChild(r);
  }
}
function renderHeadline(p) {
  const row = getState().shots.find((x) => x.shot_id === p.shot_id);
  $('headline').textContent = row && row.headline_en ? row.headline_en : '';
}

function renderClip(p) {
  const box = $('clip'); box.textContent = '';
  const url = reel && reel.clips ? reel.clips[p.shot_id] : null;
  if (url) { const im = document.createElement('img'); im.src = url; im.alt = 'Clip of ' + p.shot_id; im.loading = 'lazy'; box.appendChild(im); }
  else box.appendChild(h('p', 'Clip not built: run `ventaja clip ' + p.shot_id + ' --out ' + p.shot_id + '.gif` (needs the tracking data).', 'hint'));
}
function renderFeatured() {
  const sel = $('featuredSel'); sel.textContent = '';
  const first = document.createElement('option'); first.value = ''; first.textContent = 'Featured shots...'; sel.appendChild(first);
  for (const key of ['worst', 'best', 'late']) {
    const g = document.createElement('optgroup'); g.label = FEATURED_LABELS[key];
    for (const it of featured[key] || []) {
      const o = document.createElement('option'); o.value = it.shot.shot_id;
      o.textContent = '#' + it.rank + ' ' + (it.shot.shooter.name || 'player ' + it.shot.shooter.player_id) + ' — ' + fmt.num(it.metric, 2);
      g.appendChild(o);
    }
    sel.appendChild(g);
  }
}
function renderOthers(p) {
  const shots = getState().shots, row = shots.find((x) => x.shot_id === p.shot_id);
  const game = row ? row.game_id : null, ul = $('others'); ul.textContent = '';
  $('othersTitle').textContent = game === null ? 'Other shots in this game' : 'Other shots in game ' + game;
  for (const s of shots.filter((x) => x.game_id === game)) {
    const li = h('li', (s.shooter || s.shooter_id) + ' · P' + s.period + ' · cost ' + f(s.cost, 2));
    li.tabIndex = 0; li.title = s.shot_id; if (s.shot_id === p.shot_id) li.className = 'cur';
    const go = () => navigate({ shot: s.shot_id });
    li.addEventListener('click', go);
    li.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') go(); });
    ul.appendChild(li);
  }
}
function onPayload(p, optBy) {
  current = p;
  const link = document.querySelector('nav a[data-nav="shot"]');
  if (link) link.setAttribute('href', '#shot=' + encodeURIComponent(p.shot_id));   // Shot tab keeps the current shot
  renderHeader(p); renderHeadline(p); renderTable(p, optBy);
  renderClip(p); renderOthers(p);
  showCurve($('curve'), p.shot_id);   // no-op unless the shot changed
  const sel = $('featuredSel'); if (sel) sel.value = [...sel.options].some((o) => o.value === p.shot_id) ? p.shot_id : '';
}

export function mount(section) {
  section.innerHTML = '<div id="layout"><div id="boardHost"></div><div id="side">' +
    '<div class="card" id="head"></div><p id="headline"></p><div id="curve"></div>' +
    '<div class="card" id="tableWrap"><table id="optTable"></table></div>' +
    '<div class="card" id="clip"></div>' +
    '<div class="card"><label class="k" for="featuredSel">Featured</label><select id="featuredSel"></select>' +
    '<h1 id="othersTitle">Other shots in this game</h1><ul id="others"></ul></div></div></div>';
  mountBoard($('boardHost'), { onPayload: onPayload, onSelect: (shot) => navigate({ shot: shot }) });
  $('featuredSel').addEventListener('change', (ev) => { if (ev.target.value) navigate({ shot: ev.target.value }); });
  const loading = Promise.all([
    api('/api/featured').then((x) => { featured = x; renderFeatured(); }),
    api('/api/reel').then((x) => { reel = x; if (current) renderClip(current); }),
  ]).catch((e) => setStatus('Could not load featured shots: ' + e.message));
  mount.loading = loading;
}

export async function update(state) {
  const mine = ++token;
  await mount.loading;
  if (mine !== token) return;
  const id = state.shot || (featured && featured.default_shot);
  if (!id) { setStatus('No valued shots to show.', true); return; }
  const err = await showShot(id);
  if (mine !== token || !err) return;
  const fallback = featured && featured.default_shot;
  setStatus('Shot ' + id + ' is not available: ' + err);
  if (fallback && fallback !== id) {
    await showShot(fallback);
    if (mine === token) setStatus('Shot ' + id + ' is not available: ' + err);
  }
}

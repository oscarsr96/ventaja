// Players view: filterable ranking with the league row pinned, then a player profile and that player's shots.
import { api, navigate, fmt } from '/static/app.js';

const METRICS = [['mean_cost', 'Mean cost'], ['good_read_share', 'Good-read share'], ['late_held_share', 'Late-held share']];
const BANDS = ['', '24-14', '14-6', '6-0'];
let root = null, rankBox = null, profBox = null, msg = null;
let filters = { team: '', clock: '', minShots: 1, by: 'mean_cost' };
let teamsLoaded = null, token = 0, listed = false;

function h(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined && text !== null) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}
function opt(value, label) { const o = document.createElement('option'); o.value = value; o.textContent = label; return o; }
function labelled(text, control) { const l = h('label', text + ' ', 'k'); l.style.display = 'inline-flex'; l.style.gap = '4px'; l.style.alignItems = 'center'; l.appendChild(control); return l; }

// table(heads, rows, onRow): rows are arrays of cell strings; a row may carry .cls and .id
function table(heads, rows, onRow) {
  const t = h('table'), hr = h('tr');
  heads.forEach((x, i) => hr.appendChild(h('th', x, i === 0 || x === 'Player' || x === 'Team' ? 'l' : '')));
  t.appendChild(hr);
  for (const r of rows) {
    const tr = h('tr', undefined, r.cls || '');
    r.cells.forEach((c, i) => tr.appendChild(h('td', c, heads[i] === 'Player' || heads[i] === 'Team' || heads[i] === 'Type' || heads[i] === 'Band' ? 'l' : '')));
    if (onRow && r.id !== undefined) {
      tr.style.cursor = 'pointer'; tr.tabIndex = 0;
      tr.addEventListener('click', () => onRow(r.id));
      tr.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') onRow(r.id); });
    }
    t.appendChild(tr);
  }
  const wrap = h('div'); wrap.style.overflowX = 'auto'; wrap.appendChild(t); return wrap;
}
function card(title) { const c = h('div', undefined, 'card'); if (title) c.appendChild(h('h1', title)); return c; }
function metricCells(m, band) {
  const cells = [m.n_shots, m.n_readable, fmt.num(m.mean_cost, 3), fmt.pct(m.good_read_share), fmt.pct(m.late_held_share)];
  if (band) cells.push(m.clock ? m.clock.n : '-', m.clock ? fmt.num(m.clock.cost, 3) : '-');
  return cells.map(String);
}

function renderRanking(r) {
  rankBox.textContent = '';
  const c = card('Ranking by ' + (METRICS.find((m) => m[0] === r.by) || [0, r.by])[1] + (r.clock ? ' · clock ' + r.clock : ''));
  const heads = ['#', 'Player', 'Team', 'Shots', 'Readable', 'Mean cost', 'Good reads', 'Late held'];
  if (r.clock) heads.push('Band n', 'Band cost');
  const rows = r.players.map((p) => ({ id: p.player.player_id, cells: [p.rank, p.player.name || '-', (p.player.team && p.player.team.name) || '-', ...metricCells(p.metrics, r.clock)] }));
  rows.push({ cls: 'shooter', cells: ['', 'League', '', ...metricCells(r.league, r.clock)] });
  if (!r.players.length) c.appendChild(h('p', 'No players match these filters.', 'hint'));
  c.appendChild(table(heads, rows, (id) => navigate({ player: String(id) })));
  rankBox.appendChild(c);
}

async function loadRanking(mine) {
  const body = { by: filters.by, min_shots: filters.minShots, limit: 50 };
  if (filters.team) body.team = filters.team;
  if (filters.clock) body.clock = filters.clock;
  msg.textContent = '';
  try {
    const r = await api('/api/ask/rank_players', { method: 'POST', body });
    if (mine === token) renderRanking(r);
  } catch (e) { if (mine === token) { rankBox.textContent = ''; msg.textContent = 'Could not load the ranking: ' + e.message; } }
}

async function renderProfile(id, mine) {
  profBox.textContent = '';
  let p, shots;
  try {
    [p, shots] = await Promise.all([
      api('/api/ask/player_profile', { method: 'POST', body: { player: String(id) } }),
      api('/api/ask/find_shots', { method: 'POST', body: { player: String(id), limit: 50 } }),
    ]);
  } catch (e) { if (mine === token) profBox.appendChild(h('p', 'Could not load the profile: ' + e.message, 'bad')); return; }
  if (mine !== token) return;
  const c = card('Player profile');
  const team = p.player.team && p.player.team.name ? p.player.team.name : '-';
  c.appendChild(h('div', (p.player.name || 'player ' + p.player.player_id) + ' · ' + team, 'v'));
  c.appendChild(h('p', 'Games: ' + (p.games.length ? p.games.join(', ') : '-') + ' · shots ' + p.n_shots + ' · readable ' + p.n_readable, 'hint'));
  const tot = [['Mean shot value', fmt.num(p.mean_shot_value, 3)], ['Mean best alternative', fmt.num(p.mean_best_alt_value, 3)], ['Mean cost', fmt.num(p.mean_cost, 3)],
    ['Good reads', fmt.pct(p.good_read_share)], ['Late held', fmt.pct(p.late_held_share)], ['Mean lag held (s)', fmt.num(p.mean_lag_held, 2)],
    ['Ignored alternative', p.ignored_alternative || '-']];
  c.appendChild(table(['Total', 'Value'], tot.map((x) => ({ cells: x }))));
  c.appendChild(h('h1', 'Shot-clock bands'));
  c.appendChild(table(['Band', 'Shots', 'Cost'], p.clock.map((b) => ({ cells: [b.band, b.n, fmt.num(b.cost, 3)] }))));
  c.appendChild(h('h1', 'Best alternatives'));
  c.appendChild(table(['Type', 'Shots', 'Cost'], p.alternatives.map((a) => ({ cells: [a.type, a.n, fmt.num(a.cost, 3)] }))));
  c.appendChild(h('h1', 'Season vs league'));
  const lg = p.league;
  const s = p.season || {};
  const seasonRows = Object.keys(s).map((k) => ({ cells: [k.replace(/_/g, ' '), s[k] === null || s[k] === undefined ? '-' : (Number.isInteger(s[k]) ? String(s[k]) : fmt.num(s[k], 3))] }));
  seasonRows.push({ cls: 'shooter', cells: ['League shots / readable', lg.n_shots + ' / ' + lg.n_readable] },
    { cls: 'shooter', cells: ['League mean cost', fmt.num(lg.mean_cost, 3)] },
    { cls: 'shooter', cells: ['League good reads', fmt.pct(lg.good_read_share)] },
    { cls: 'shooter', cells: ['League late held', fmt.pct(lg.late_held_share)] });
  c.appendChild(table(['Season', 'Value'], seasonRows));
  if (p.phrase) c.appendChild(h('p', p.phrase));
  if (p.caution) c.appendChild(h('p', p.caution, 'hint'));
  profBox.appendChild(c);
  const sc = card('Shots of this player (' + shots.total + ')');
  if (!shots.shots.length) sc.appendChild(h('p', 'No valued shots.', 'hint'));
  sc.appendChild(table(['Period', 'Clock', 'Cost', 'Good read', 'Verdict', 'Headline'],
    shots.shots.map((x) => ({ id: x.shot_id, cells: ['P' + x.period, x.shot_clock === null || x.shot_clock === undefined ? '-' : fmt.num(x.shot_clock, 1), fmt.num(x.cost, 3), x.good_read === null || x.good_read === undefined ? '-' : (x.good_read ? 'yes' : 'no'), x.verdict || '-', x.headline || ''] })),
    (shotId) => navigate({ shot: shotId })));
  profBox.appendChild(sc);
}

function buildBar(teams) {
  const bar = card(); bar.style.display = 'flex'; bar.style.flexWrap = 'wrap'; bar.style.gap = '10px';
  const team = document.createElement('select'); team.appendChild(opt('', 'All teams')); teams.forEach((t) => team.appendChild(opt(t, t)));
  const clock = document.createElement('select'); BANDS.forEach((b) => clock.appendChild(opt(b, b || 'any')));
  const min = document.createElement('input'); min.type = 'number'; min.min = '1'; min.value = String(filters.minShots); min.style.width = '5em';
  const by = document.createElement('select'); METRICS.forEach((m) => by.appendChild(opt(m[0], m[1])));
  const why = h('span', 'A clock band ranks by mean cost only (the service keeps no per-band read or lag shares).', 'hint'); why.hidden = true;
  const sync = () => {
    filters = { team: team.value, clock: clock.value, minShots: Math.max(1, parseInt(min.value, 10) || 1), by: by.value };
    if (filters.clock) { filters.by = 'mean_cost'; by.value = 'mean_cost'; }
    by.disabled = !!filters.clock; why.hidden = !filters.clock;
    const mine = ++token; loadRanking(mine);
  };
  [team, clock, min, by].forEach((x) => x.addEventListener('change', sync));
  [['Team', team], ['Clock band', clock], ['Min shots', min], ['Metric', by]].forEach(([t, c]) => bar.appendChild(labelled(t, c)));
  bar.appendChild(why);
  return bar;
}

export function mount(section) {
  root = section; section.textContent = '';
  msg = h('p', '', 'bad');
  rankBox = h('div'); profBox = h('div'); profBox.style.display = 'flex'; profBox.style.flexDirection = 'column'; profBox.style.gap = '10px';
  root.style.display = 'flex'; root.style.flexDirection = 'column'; root.style.gap = '10px';
  teamsLoaded = api('/api/ask/list_games', { method: 'POST', body: {} }).then((gs) => {
    const names = new Set();
    gs.forEach((g) => { if (g.home.name) names.add(g.home.name); if (g.away.name) names.add(g.away.name); });
    section.appendChild(buildBar([...names].sort()));
    section.appendChild(msg); section.appendChild(rankBox); section.appendChild(profBox);
  }).catch((e) => { section.appendChild(h('p', 'Could not load teams: ' + e.message, 'bad')); });
}

export async function update(state) {
  const mine = ++token;
  await teamsLoaded;
  if (mine !== token || !rankBox) return;
  if (!listed || !state.player) { listed = true; await loadRanking(mine); }
  profBox.textContent = '';
  if (state.player) await renderProfile(state.player, mine);
}

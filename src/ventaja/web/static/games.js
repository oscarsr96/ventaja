// Games view: the tracked games, and the valued shots of the chosen game sorted by cost.
import { api, navigate, fmt } from '/static/app.js';

let gamesBox = null, shotsBox = null, games = null, loading = null, token = 0;

function h(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined && text !== null) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}
function table(heads, rows, onRow, leftCols) {
  const t = h('table'), hr = h('tr');
  heads.forEach((x, i) => hr.appendChild(h('th', x, leftCols.includes(i) ? 'l' : '')));
  t.appendChild(hr);
  for (const r of rows) {
    const tr = h('tr', undefined, r.cls || '');
    r.cells.forEach((c, i) => tr.appendChild(h('td', String(c), leftCols.includes(i) ? 'l' : '')));
    tr.style.cursor = 'pointer'; tr.tabIndex = 0;
    tr.addEventListener('click', () => onRow(r.id));
    tr.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') onRow(r.id); });
    t.appendChild(tr);
  }
  const wrap = h('div'); wrap.style.overflowX = 'auto'; wrap.appendChild(t); return wrap;
}

function renderGames(selected) {
  gamesBox.textContent = '';
  const c = h('div', undefined, 'card'); c.appendChild(h('h1', 'Games'));
  const rows = games.map((g) => ({
    id: g.game_id, cls: String(g.game_id) === String(selected) ? 'shooter' : '',
    cells: [g.date || '-', g.home.name || '-', (g.home.score ?? '-') + ' - ' + (g.away.score ?? '-'), g.away.name || '-', g.valued_shots],
  }));
  c.appendChild(table(['Date', 'Home', 'Score', 'Away', 'Valued shots'], rows, (id) => navigate({ game: String(id) }), [0, 1, 3]));
  gamesBox.appendChild(c);
}

async function renderShots(gameId, mine) {
  shotsBox.textContent = '';
  if (!gameId) return;
  let shots;
  try { shots = await api('/api/shots?game=' + encodeURIComponent(gameId)); }
  catch (e) { if (mine === token) shotsBox.appendChild(h('p', 'Could not load the shots: ' + e.message, 'bad')); return; }
  if (mine !== token) return;
  const c = h('div', undefined, 'card'); c.appendChild(h('h1', 'Shots of game ' + gameId + ' by cost'));
  if (!shots.length) c.appendChild(h('p', 'No valued shots in this game.', 'hint'));
  const rows = shots.map((s) => ({
    id: s.shot_id,
    cells: [s.shooter || s.shooter_id, s.team || '-', (s.period === null || s.period === undefined ? '-' : 'P' + s.period), s.shot_clock === null || s.shot_clock === undefined ? '-' : fmt.num(s.shot_clock, 1),
      fmt.num(s.cost, 3), s.good_read === null || s.good_read === undefined ? '-' : (s.good_read ? 'yes' : 'no'), s.headline_en || ''],
  }));
  c.appendChild(table(['Shooter', 'Team', 'Period', 'Clock', 'Cost', 'Good read', 'Headline'], rows, (id) => navigate({ shot: id }), [0, 1, 6]));
  shotsBox.appendChild(c);
}

export function mount(section) {
  section.textContent = '';
  gamesBox = h('div'); shotsBox = h('div');
  section.appendChild(gamesBox); section.appendChild(shotsBox);
  // the app's --game filter (null = all games) hides the games the board does not serve
  loading = Promise.all([api('/api/ask/list_games', { method: 'POST', body: {} }), api('/api/about')])
    .then(([g, a]) => { games = a.games_filter ? g.filter((x) => a.games_filter.includes(x.game_id)) : g; })
    .catch((e) => { gamesBox.appendChild(h('p', 'Could not load games: ' + e.message, 'bad')); });
}

export async function update(state) {
  const mine = ++token;
  await loading;
  if (mine !== token || !games) return;
  renderGames(state.game);
  await renderShots(state.game, mine);
}

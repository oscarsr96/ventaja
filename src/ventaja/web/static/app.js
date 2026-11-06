// Shell: hash router, API helper and number formatting shared by every view.
const VIEWS = ['shot', 'players', 'games', 'ask', 'about'];
const KEYS = { shot: 'shot', ask: 'ask' };            // views whose hash value is the view's own argument
const modules = {}, sections = {};
let state = { view: 'shot', shot: '', player: '', game: '', ask: '' };

export const fmt = {
  num(x, d = 2) { return x === null || x === undefined || Number.isNaN(x) ? '-' : Number(x).toFixed(d); },
  pct(x) { return x === null || x === undefined || Number.isNaN(x) ? '-' : (Number(x) * 100).toFixed(0) + '%'; },
};

export async function api(path, { method = 'GET', body } = {}) {
  const opts = { method };
  if (body !== undefined) { opts.headers = { 'Content-Type': 'application/json' }; opts.body = JSON.stringify(body); }
  const resp = await fetch(path, opts);
  let json = null;
  try { json = await resp.json(); } catch (e) { json = null; }
  if (!resp.ok) {
    let d = json && (json.error || json.detail);
    if (Array.isArray(d)) d = d.map((x) => (x.loc ? x.loc.join('.') + ': ' : '') + x.msg).join('; ');
    throw new Error(d || 'HTTP ' + resp.status);
  }
  return json;
}

function parseHash(hash) {
  const next = { view: 'shot', shot: '', player: '', game: '', ask: '' };
  const parts = hash.replace(/^#/, '').split('&').filter(Boolean);
  parts.forEach((part, i) => {
    let k, v;
    try { [k, v = ''] = part.split('=').map(decodeURIComponent); } catch (e) { return; }   // malformed %-escape: ignore the part
    if (i === 0 && VIEWS.includes(k)) { next.view = k; if (KEYS[k]) next[k] = v; }
    else if (Object.hasOwn(next, k) && k !== 'view') next[k] = v;
  });
  return next;
}

function toHash(s) {
  const first = KEYS[s.view] && s[s.view] ? s.view + '=' + encodeURIComponent(s[s.view]) : s.view;
  const rest = [];
  if (s.view === 'players' && s.player) rest.push('player=' + encodeURIComponent(s.player));
  if (s.view === 'games' && s.game) rest.push('game=' + encodeURIComponent(s.game));
  return '#' + [first, ...rest].join('&');
}

export function navigate(patch) {
  const next = { ...state, ...patch };
  if (!('view' in patch)) next.view = 'shot' in patch ? 'shot' : 'player' in patch ? 'players' : 'game' in patch ? 'games' : 'ask' in patch ? 'ask' : next.view;
  location.hash = toHash(next);
}

function show() {
  state = parseHash(location.hash);
  for (const v of VIEWS) sections[v].hidden = v !== state.view;
  for (const a of document.querySelectorAll('nav a')) a.classList.toggle('active', a.dataset.nav === state.view);
  modules[state.view].update(state);
}

async function start() {
  const q = new URLSearchParams(location.search).get('shot');
  if (q && !location.hash) history.replaceState(null, '', location.pathname + '#shot=' + encodeURIComponent(q));
  for (const v of VIEWS) sections[v] = document.querySelector('section[data-view="' + v + '"]');
  const loaded = await Promise.all(VIEWS.map((v) => import('/static/' + v + '.js')));
  VIEWS.forEach((v, i) => { modules[v] = loaded[i]; });
  for (const v of VIEWS) modules[v].mount(sections[v]);
  window.addEventListener('hashchange', show);
  show();
}
start();

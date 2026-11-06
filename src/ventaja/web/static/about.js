// About view: what ventaja is, its four surfaces, the build numbers and the decision records.
import { api } from '/static/app.js';

const ADRS = [
  ['0001', 'Tracking orientation', '0001-orientacion-del-tracking.md'],
  ['0002', 'Raw, build and artifacts', '0002-raw-build-y-artefactos.md'],
  ['0003', 'Decision frame', '0003-frame-de-decision.md'],
  ['0004', 'Value model and viability', '0004-modelo-de-valor-y-viabilidad.md'],
  ['0005', 'Pass lane after the session', '0005-carril-de-pase-tras-la-sesion.md'],
  ['0006', 'Advantage curve and reel', '0006-curva-de-ventaja-y-reel.md'],
  ['0007', 'Shot clock off', '0007-reloj-de-posesion-apagado.md'],
  ['0008', 'Player card', '0008-ficha-de-jugador.md'],
  ['0009', 'Whiteboard', '0009-pizarra.md'],
  ['0010', 'MCP', '0010-mcp.md'],
  ['0011', 'Unified app', '0011-app-unificada.md'],
];
const DESCRIPTION = [
  'ventaja is a decision-analytics library for basketball tracking data, built for the SkillCorner x PySport Analytics Cup.',
  'It values every shot against the best viable pass at the decision frame; the cost is the expected points the better alternative would have added.',
  'Layer 2 replays that valuation along the possession and marks the windows in which a pass beat the shot, so a lost moment has a start, an end and a verdict.',
  'Player cards set those decisions beside the season profile, with a rule-based phrase and an explicit caution about sample size.',
  'The value model is validated leave-one-game-out, and the checks that fail are reported, not tuned away.',
  'Everything shipped is a derived artifact: regenerate it, never edit it.',
];
const SURFACES = [
  ['Command line', 'uv run ventaja ... : build, validate, decisions, curves, clips, reels and player cards.'],
  ['Whiteboard', 'The Shot view: drag the players and the value surface and the best pass update.'],
  ['MCP server', 'ventaja mcp serve : six tools for Claude Code, Claude Desktop or any MCP client (see Ask).'],
  ['This app', 'ventaja app : Shot, Players, Games, Ask and About over one local service.'],
];
let box = null, token = 0;

function h(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined && text !== null) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}
function card(title) { const c = h('div', undefined, 'card'); if (title) c.appendChild(h('h1', title)); return c; }
const dash = (v) => (v === null || v === undefined || v === '' ? '-' : String(v));

function numbersCard(a) {
  const c = card('Numbers'), g = h('div'); g.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:6px 14px';
  [['Games', a.games], ['Valued shots', a.valued_shots], ['Players', a.players], ['Model trained at', a.model_trained_at], ['Built at', a.built_at], ['Version', a.version]].forEach(([k, v]) => {
    const d = h('div'); d.appendChild(h('span', k, 'k')); d.appendChild(h('span', dash(v), 'v')); g.appendChild(d);
  });
  c.appendChild(g); return c;
}

function adrCard() {
  const c = card('Decision records'), list = h('div'), panel = h('pre');
  list.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px';
  panel.hidden = true; panel.style.cssText = 'white-space:pre-wrap;font:inherit;margin:8px 0 0;max-height:520px;overflow:auto';
  let mine = 0;
  for (const [num, title, file] of ADRS) {
    const b = h('button', num + ' ' + title); b.type = 'button';
    b.addEventListener('click', async () => {
      const t = ++mine;
      panel.hidden = false; panel.className = ''; panel.textContent = 'Loading...';
      try {
        const resp = await fetch('/docs/decisions/' + encodeURIComponent(file));
        const text = resp.ok ? await resp.text() : null;
        if (t !== mine) return;
        if (text === null) { panel.className = 'hint'; panel.textContent = resp.status === 404 ? 'ADR ' + num + ' not found.' : 'Could not load ADR ' + num + ': HTTP ' + resp.status; }
        else panel.textContent = text;
      } catch (e) { if (t === mine) { panel.className = 'bad'; panel.textContent = 'Could not load ADR ' + num + ': ' + e.message; } }
    });
    list.appendChild(b);
  }
  c.appendChild(list); c.appendChild(panel); return c;
}

export function mount(section) {
  section.textContent = '';
  section.style.cssText = 'display:flex;flex-direction:column;gap:10px';
  const d = card('What ventaja is');
  DESCRIPTION.forEach((t) => d.appendChild(h('p', t)));
  section.appendChild(d);
  const s = card('Four surfaces');
  SURFACES.forEach(([k, v]) => { const p = h('p'); p.appendChild(h('b', k + ': ')); p.appendChild(document.createTextNode(v)); s.appendChild(p); });
  section.appendChild(s);
  box = h('div'); section.appendChild(box);
  section.appendChild(adrCard());
}

export async function update(state) {
  const mine = ++token;
  try {
    const a = await api('/api/about');
    if (mine !== token) return;
    box.textContent = ''; box.appendChild(numbersCard(a));
  } catch (e) { if (mine === token) { box.textContent = ''; box.appendChild(h('p', 'Could not load the numbers: ' + e.message, 'bad')); } }
}

// Ask view: one form per MCP tool, generated from the tool's JSON schema, plus client setup and the glossary.
import { api } from '/static/app.js';

const REPO_PLACEHOLDER = '/path/to/ventaja';
let root = null, holderBox = null, pending = '';

function h(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined && text !== null) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}
function card(title) { const c = h('div', undefined, 'card'); if (title) c.appendChild(h('h1', title)); return c; }
function opt(value, label) { const o = document.createElement('option'); o.value = value; o.textContent = label; return o; }
function codeBlock(text) {
  const wrap = h('div'), pre = h('pre'), btn = h('button', 'Copy');
  pre.textContent = text; pre.style.cssText = 'margin:4px 0;padding:8px;background:var(--bg);border:1px solid var(--line);border-radius:6px;overflow-x:auto;user-select:all';
  btn.type = 'button';
  btn.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(text); btn.textContent = 'Copied'; } catch (e) { btn.textContent = 'Select and copy'; }
    setTimeout(() => { btn.textContent = 'Copy'; }, 1500);
  });
  wrap.appendChild(pre); wrap.appendChild(btn); return wrap;
}

// The non-null variant of a property (nullable params arrive as anyOf [{type}, {type: null}]).
function resolve(prop) {
  if (prop.anyOf) {
    const v = prop.anyOf.find((x) => x.type !== 'null') || {};
    return { ...v, description: prop.description, default: prop.default };
  }
  return prop;
}

// Build one control for a schema property; returns {el, read()} where read() gives undefined (omit) or a value, or throws.
function control(name, raw, required) {
  const p = resolve(raw), hint = [];
  let el, read;
  if (p.enum) {
    el = document.createElement('select'); el.appendChild(opt('', required ? '(choose)' : '(unset)'));
    p.enum.forEach((v) => el.appendChild(opt(String(v), String(v))));
    read = () => (el.value === '' ? undefined : el.value);
  } else if (p.type === 'boolean') {
    el = document.createElement('select'); [['', '(unset)'], ['true', 'true'], ['false', 'false']].forEach(([v, l]) => el.appendChild(opt(v, l)));
    read = () => (el.value === '' ? undefined : el.value === 'true');
  } else if (p.type === 'integer' || p.type === 'number') {
    el = document.createElement('input'); el.type = 'number'; el.style.width = '8em';
    if (p.minimum !== undefined) el.min = String(p.minimum);
    if (p.maximum !== undefined) el.max = String(p.maximum);
    if (p.type === 'number') el.step = 'any';
    if (p.minimum !== undefined || p.maximum !== undefined) hint.push('range ' + (p.minimum ?? '') + ' to ' + (p.maximum ?? ''));
    read = () => {
      if (el.value === '') return undefined;
      const n = Number(el.value);
      if (!Number.isFinite(n)) throw new Error(name + ' must be a number');
      return n;
    };
  } else if (p.type === 'array' || p.type === 'object') {
    el = document.createElement('textarea'); el.rows = 4; el.style.cssText = 'width:100%;font:12px ui-monospace,Menlo,monospace';
    const item = p.items && p.items.properties ? ' of {' + Object.keys(p.items.properties).join(', ') + '}' : '';
    hint.push('JSON ' + p.type + item + ', e.g. ' + (p.type === 'array' ? '[{"player": "...", "x": 0, "y": 0}]' : '{}'));
    read = () => {
      if (el.value.trim() === '') return undefined;
      try { return JSON.parse(el.value); } catch (e) { throw new Error(name + ' is not valid JSON: ' + e.message); }
    };
  } else {
    el = document.createElement('input'); el.type = 'text'; el.style.minWidth = '14em';
    read = () => (el.value.trim() === '' ? undefined : el.value.trim());
  }
  if (p.default !== undefined && p.default !== null && el.tagName !== 'SELECT') el.placeholder = 'default ' + p.default;
  else if (p.default !== undefined && p.default !== null) hint.push('default ' + p.default);
  el.id = 'ask-' + name + '-' + Math.random().toString(36).slice(2, 7);
  const row = h('div'); row.style.cssText = 'display:flex;flex-direction:column;gap:2px;margin:6px 0';
  const lab = h('label', name + (required ? ' *' : ''), 'k'); lab.htmlFor = el.id;
  row.appendChild(lab); row.appendChild(el);
  const desc = [p.description, ...hint].filter(Boolean).join(' · ');
  if (desc) row.appendChild(h('div', desc, 'hint'));
  const readReq = () => { const v = read(); if (required && v === undefined) throw new Error(name + ' is required'); return v; };
  return { row, read: readReq };
}

function toolCard(tool) {
  const c = card(tool.name); c.dataset.tool = tool.name;
  c.appendChild(h('p', tool.description || '', 'hint'));
  const props = (tool.input_schema && tool.input_schema.properties) || {};
  const req = new Set((tool.input_schema && tool.input_schema.required) || []);
  const form = document.createElement('form'), fields = [];
  for (const [name, prop] of Object.entries(props)) {
    const f = control(name, prop, req.has(name)); fields.push([name, f.read]); form.appendChild(f.row);
  }
  if (!fields.length) form.appendChild(h('p', 'No parameters.', 'hint'));
  const run = h('button', 'Run'); run.type = 'submit';
  const err = h('p', '', 'bad'), details = document.createElement('details'), sum = h('summary', 'Result'), pre = h('pre');
  details.hidden = true; details.appendChild(sum); details.appendChild(pre); pre.style.cssText = 'overflow:auto;max-height:420px;font-size:12px';
  let token = 0;
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const mine = ++token, body = {};
    err.textContent = '';
    try {
      for (const [name, read] of fields) { const v = read(); if (v !== undefined) body[name] = v; }
    } catch (e) { err.textContent = e.message; return; }
    run.disabled = true;
    try {
      const r = await api('/api/ask/' + encodeURIComponent(tool.name), { method: 'POST', body });
      if (mine !== token) return;
      pre.textContent = JSON.stringify(r, null, 2); details.hidden = false; details.open = true;
    } catch (e) {
      if (mine !== token) return;
      details.hidden = true; err.textContent = e.message;
    } finally { if (mine === token) run.disabled = false; }
  });
  form.appendChild(run); c.appendChild(form); c.appendChild(err); c.appendChild(details);
  return c;
}

function connectCard() {
  const c = card('Connect an AI client');
  c.appendChild(h('p', 'The same six tools are available to Claude Code, Claude Desktop or any MCP client, with no API key. Replace ' + REPO_PLACEHOLDER + ' with your clone\'s path.', 'hint'));
  c.appendChild(h('div', 'Claude Code', 'k'));
  c.appendChild(codeBlock('claude mcp add ventaja -- uv run --directory ' + REPO_PLACEHOLDER + ' ventaja mcp serve'));
  c.appendChild(h('div', 'Claude Desktop (claude_desktop_config.json)', 'k'));
  c.appendChild(codeBlock(JSON.stringify({ mcpServers: { ventaja: { command: 'uv', args: ['run', '--directory', REPO_PLACEHOLDER, 'ventaja', 'mcp', 'serve'] } } }, null, 2)));
  return c;
}

function glossaryCard() {
  const c = card('Glossary'), link = h('button', 'Show glossary'), box = h('pre');
  box.hidden = true; box.style.cssText = 'white-space:pre-wrap;font:inherit;margin:6px 0 0';
  let loaded = false, token = 0;
  link.type = 'button';
  link.addEventListener('click', async () => {
    if (loaded) { box.hidden = !box.hidden; link.textContent = box.hidden ? 'Show glossary' : 'Hide glossary'; return; }
    const mine = ++token;
    try {
      const resp = await fetch('/api/ask/glossary');
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const text = await resp.text();
      if (mine !== token) return;
      box.textContent = text; box.hidden = false; loaded = true; link.textContent = 'Hide glossary';
    } catch (e) { box.hidden = false; box.className = 'bad'; box.textContent = 'Could not load the glossary: ' + e.message; }
  });
  c.appendChild(link); c.appendChild(box);
  return c;
}

export function mount(section) {
  root = section; section.textContent = '';
  section.appendChild(connectCard());
  section.appendChild(glossaryCard());
  const holder = h('div'); holder.style.cssText = 'display:flex;flex-direction:column;gap:10px';
  section.appendChild(holder); holderBox = holder;
  api('/api/ask/schema').then((tools) => { tools.forEach((t) => holder.appendChild(toolCard(t))); focusTool(pending); })
    .catch((e) => { holder.appendChild(h('p', 'Could not load the tool schema: ' + e.message, 'bad')); });
}

// #ask=<tool>: scroll to that tool's card (once the schema has built the cards).
function focusTool(name) {
  if (!name || !holderBox) return;
  const c = [...holderBox.children].find((x) => x.dataset && x.dataset.tool === name);
  if (c) c.scrollIntoView({ block: 'start' });
}

export function update(state) { pending = state.ask || ''; focusTool(pending); }

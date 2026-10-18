#!/usr/bin/env node
/**
 * clash-gist-pool
 *
 * Sync proxies-only all.yaml from public GitHub Gists, dedupe/filter them,
 * validate with the local Mihomo core, delay-test through this machine's
 * network, and produce a provider file + report.
 *
 * No npm dependencies. Node >= 20. Windows/macOS/Linux.
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import http from 'node:http';
import net from 'node:net';
import crypto from 'node:crypto';
import { spawn, spawnSync, execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const SKILL_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SOURCES_PATH = path.join(SKILL_ROOT, 'sources.json');
const DEFAULT_URL = 'https://www.gstatic.com/generate_204';
const SUPPORTED_TYPES = new Set([
  'ss', 'ssr', 'vmess', 'vless', 'trojan', 'hysteria', 'hysteria2',
  'tuic', 'anytls', 'mieru', 'http', 'socks5'
]);

const DEFAULT_DISCOVERY = {
  queries: ['all.yaml+proxies', 'all.yaml+hysteria2', 'all.yaml+vmess', 'base64.txt+mihomo.yaml', 'subs-check'],
  maxPages: 2,
  maxAgeDays: 7,
  minNodes: 5,
  minCaTls: 1,
  maxCandidates: 40
};

function parseArgs(argv) {
  const cmd = argv[0] || 'help';
  const o = { _: [] };
  for (let i = 1; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--') { o._.push(...argv.slice(i + 1)); break; }
    if (!a.startsWith('--')) { o._.push(a); continue; }
    const eq = a.indexOf('=');
    if (eq >= 0) {
      o[a.slice(2, eq)] = a.slice(eq + 1);
    } else {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (next && !next.startsWith('--')) { o[key] = next; i++; }
      else o[key] = true;
    }
  }
  return { cmd, o };
}

const bool = (v) => v === true || v === '1' || v === 'true' || v === 'yes';
const num = (v, d) => Number.isFinite(Number(v)) ? Number(v) : d;
const log = (...a) => console.log(...a);
const warn = (...a) => console.error(...a);

function ensureDir(p) { fs.mkdirSync(p, { recursive: true }); }
function readJson(p, fallback) {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return fallback; }
}
function writeJson(p, v) { ensureDir(path.dirname(p)); fs.writeFileSync(p, JSON.stringify(v, null, 2) + '\n'); }
function writeText(p, v) { ensureDir(path.dirname(p)); fs.writeFileSync(p, v); }
function sha256(s) { return crypto.createHash('sha256').update(s).digest('hex'); }
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
function tail(s, n = 2500) { s = String(s || ''); return s.length > n ? s.slice(-n) : s; }

function loadSources() {
  const raw = readJson(SOURCES_PATH, null);
  if (!raw || !Array.isArray(raw.sources)) throw new Error(`invalid sources.json: ${SOURCES_PATH}`);
  return raw.sources.filter(s => s.enabled !== false);
}

function loadGithubToken() {
  if (process.env.GITHUB_TOKEN) return process.env.GITHUB_TOKEN.trim();
  const envPath = path.join(os.homedir(), '.agents', 'skills', 'github-account', '.env');
  try {
    for (const line of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
      const m = line.match(/^\s*GITHUB_TOKEN\s*=\s*(.+?)\s*$/);
      if (m) return m[1].replace(/^['"]|['"]$/g, '').trim();
    }
  } catch {}
  return null;
}

function apiHeaders(token) {
  const h = {
    'User-Agent': 'clash-gist-pool/1.0',
    'Accept': 'application/vnd.github+json'
  };
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

async function fetchTextWithTimeout(url, headers, timeoutMs = 30000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(new Error('fetch timeout')), timeoutMs);
  try {
    const res = await fetch(url, { headers, signal: ctrl.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
    return await res.text();
  } finally {
    clearTimeout(timer);
  }
}

function cachePaths(out, src) {
  const dir = path.join(out, 'cache', src.tag);
  return { dir, file: path.join(dir, 'all.yaml'), meta: path.join(dir, 'meta.json') };
}

function cadenceFromHistory(history) {
  const mins = [...new Set((history || [])
    .map(h => Math.floor((typeof h === 'string' ? new Date(h).getTime() : new Date(h.committed_at).getTime()) / 60000))
    .filter(Number.isFinite))].sort((a, b) => b - a);
  if (mins.length < 2) return null;
  const gaps = [];
  for (let i = 1; i < mins.length; i++) gaps.push(mins[i - 1] - mins[i]);
  gaps.sort((a, b) => a - b);
  const median = gaps[Math.floor(gaps.length / 2)];
  return { runs: mins.length, medianGapMin: median, first: new Date(mins[mins.length - 1] * 60000).toISOString(), last: new Date(mins[0] * 60000).toISOString() };
}

function extractProxies(yamlText) {
  const text = String(yamlText || '').replace(/^\uFEFF/, '');
  const lines = text.split(/\r?\n/);
  let start = -1;
  for (let i = 0; i < lines.length; i++) {
    if (/^proxies:\s*(#.*)?$/.test(lines[i])) { start = i; break; }
    if (/^proxies:\s*\[\s*\]\s*(#.*)?$/.test(lines[i])) return [];
  }
  if (start < 0) return [];
  let end = lines.length;
  for (let i = start + 1; i < lines.length; i++) {
    if (/^[A-Za-z_][A-Za-z0-9_-]*\s*:/.test(lines[i])) { end = i; break; }
  }
  const body = lines.slice(start + 1, end);
  let itemIndent = null;
  for (const line of body) {
    const m = line.match(/^(\s*)-\s+/);
    if (m) { itemIndent = m[1].length; break; }
  }
  if (itemIndent === null) return [];
  const items = [];
  let cur = null;
  for (const line of body) {
    const m = line.match(/^(\s*)-\s+/);
    if (m && m[1].length === itemIndent) {
      if (cur) items.push({ text: cur.join('\n') });
      cur = [line.slice(itemIndent)];
      continue;
    }
    if (cur) cur.push(line.slice(itemIndent));
  }
  if (cur) items.push({ text: cur.join('\n') });
  return items;
}

function stripComment(v) {
  let quote = null;
  for (let i = 0; i < v.length; i++) {
    const ch = v[i];
    if (quote) {
      if (ch === '\\' && quote === '"') { i++; continue; }
      if (ch === quote) quote = null;
    } else if (ch === '"' || ch === "'") {
      quote = ch;
    } else if (ch === '#' && (i === 0 || /\s/.test(v[i - 1]))) {
      return v.slice(0, i).trimEnd();
    }
  }
  return v;
}

function unescapeYamlDouble(s) {
  let out = '';
  for (let i = 1; i < s.length - 1; i++) {
    let ch = s[i];
    if (ch !== '\\') { out += ch; continue; }
    ch = s[++i];
    switch (ch) {
      case 'n': out += '\n'; break;
      case 't': out += '\t'; break;
      case 'r': out += '\r'; break;
      case 'b': out += '\b'; break;
      case 'f': out += '\f'; break;
      case 'v': out += '\v'; break;
      case '0': out += '\0'; break;
      case 'a': out += '\x07'; break;
      case 'e': out += '\x1b'; break;
      case 'x': out += String.fromCodePoint(parseInt(s.slice(i + 1, i + 3), 16)); i += 2; break;
      case 'u': out += String.fromCodePoint(parseInt(s.slice(i + 1, i + 5), 16)); i += 4; break;
      case 'U': out += String.fromCodePoint(parseInt(s.slice(i + 1, i + 9), 16)); i += 8; break;
      default: out += ch;
    }
  }
  return out;
}

function parseScalar(v) {
  v = stripComment(String(v).trim());
  if (v.length >= 2 && v.startsWith('"') && v.endsWith('"')) {
    return unescapeYamlDouble(v);
  }
  if (v.length >= 2 && v.startsWith("'") && v.endsWith("'")) {
    return v.slice(1, -1).replace(/''/g, "'");
  }
  return v;
}

function parseProxyBlock(text) {
  const first = String(text).split(/\r?\n/)[0] || '';
  if (/^\s*-\s*\{/.test(first)) return { inline: true };
  const fields = {};
  const lines = String(text).split(/\r?\n/);
  lines[0] = lines[0].replace(/^\s*-\s*/, '');
  for (let idx = 0; idx < lines.length; idx++) {
    const line = lines[idx];
    const m = line.match(/^(\s*)([A-Za-z0-9_-]+)\s*:\s*(.*)$/);
    if (!m) continue;
    const indent = m[1].length;
    if (idx > 0 && indent > 2) continue;
    const key = m[2];
    if (!['name', 'type', 'server', 'port', 'uuid', 'password', 'username', 'network', 'sni', 'servername', 'skip-cert-verify', 'tls', 'cipher', 'auth', 'auth-str', 'alterId', 'obfs', 'obfs-password', 'plugin'].includes(key)) continue;
    fields[key] = parseScalar(m[3]);
  }
  const port = Number(fields.port);
  return {
    inline: false,
    name: fields.name ? String(fields.name) : '',
    type: fields.type ? String(fields.type).toLowerCase() : '',
    server: fields.server ? String(fields.server) : '',
    port: Number.isInteger(port) ? port : null,
    uuid: fields.uuid ? String(fields.uuid) : '',
    password: fields.password ? String(fields.password) : '',
    username: fields.username ? String(fields.username) : '',
    network: fields.network ? String(fields.network) : '',
    sni: fields.sni ? String(fields.sni) : '',
    servername: fields.servername ? String(fields.servername) : '',
    cipher: fields.cipher ? String(fields.cipher) : '',
    auth: fields.auth ? String(fields.auth) : '',
    authStr: fields['auth-str'] ? String(fields['auth-str']) : '',
    alterId: fields.alterId ? String(fields.alterId) : '',
    obfs: fields.obfs ? String(fields.obfs) : '',
    obfsPassword: fields['obfs-password'] ? String(fields['obfs-password']) : '',
    plugin: fields.plugin ? String(fields.plugin) : '',
    tls: String(fields.tls || '').toLowerCase() === 'true',
    reality: /^\s*reality-opts:/m.test(String(text)),
    insecure: String(fields['skip-cert-verify'] || '').toLowerCase() === 'true'
  };
}

const CA_TLS_TYPES = new Set(['trojan', 'hysteria', 'hysteria2', 'tuic', 'anytls']);

function isCaTls(p) {
  if (!p || p.insecure) return false;
  if (p.reality) return false;
  if (p.tls) return true;
  return CA_TLS_TYPES.has(p.type);
}

function proxyKey(p) {
  return sha256([
    p.type, p.server.toLowerCase(), p.port,
    p.uuid, p.password, p.username,
    p.network, p.sni, p.servername,
    p.cipher, p.auth, p.authStr, p.alterId, p.obfs, p.obfsPassword, p.plugin,
    p.tls, p.reality
  ].join('|'));
}

function sanitizeName(name) {
  let s = String(name || '')
    .replace(/[\u0000-\u001f\u007f]/g, ' ')
    .replace(/[\\/]/g, '-')
    .replace(/\s+/g, ' ')
    .trim();
  if (!s) s = 'node';
  if (s.length > 110) s = s.slice(0, 100).trimEnd() + '~' + sha256(String(name)).slice(0, 6);
  return s;
}

function makeName(tag, original) {
  const prefix = `${tag}/`;
  const clean = sanitizeName(original);
  return clean.startsWith(prefix) ? clean : prefix + clean;
}

function renameBlock(text, newName) {
  const q = JSON.stringify(newName);
  if (/^\s*-\s*name\s*:/m.test(text)) return text.replace(/^(\s*-\s*name\s*:\s*).*$/m, `$1${q}`);
  if (/^\s*name\s*:/m.test(text)) return text.replace(/^(\s*name\s*:\s*).*$/m, `$1${q}`);
  return null;
}

function indentBlock(text, n) {
  return String(text).replace(/\s+$/, '').split(/\r?\n/).map(line => line ? ' '.repeat(n) + line : line).join('\n');
}

function renderProxies(records) {
  if (!records.length) return 'proxies: []\n';
  return 'proxies:\n' + records.map(r => indentBlock(r.block, 2)).join('\n') + '\n';
}

function sourceCadenceNote(src, state) {
  const c = cadenceFromHistory(state?.history);
  if (!c) return src.cadence || '';
  const mins = c.medianGapMin;
  const human = mins >= 120 ? `${Math.round(mins / 60)}h` : `${mins}m`;
  return `~${human} (${c.runs} recent runs)`;
}

async function getGistMeta(src, token) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(new Error('GitHub API timeout')), 30000);
  try {
    const res = await fetch(`https://api.github.com/gists/${src.id}`, { headers: apiHeaders(token), signal: ctrl.signal });
    if (!res.ok) throw new Error(`GitHub API ${res.status} ${res.statusText}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

async function syncSources(out, o) {
  const allSources = loadSources();
  const sources = allSources
    .filter(s => !o.source || s.tag === o.source)
    .sort((a, b) => (a.priority || 99) - (b.priority || 99));
  if (!sources.length) throw new Error('no matching sources');

  const statePath = path.join(out, 'state.json');
  const state = readJson(statePath, { sources: {} });
  const token = loadGithubToken();
  const entries = [];
  const errors = [];

  for (const src of sources) {
    const c = cachePaths(out, src);
    ensureDir(c.dir);
    let gist = null;
    let content = null;
    let status = '';
    try {
      gist = await getGistMeta(src, token);
      const file = gist.files?.['all.yaml'] || gist.files?.['All.yaml'];
      if (!file) throw new Error('all.yaml not found');
      const prev = state.sources[src.tag];
      if (!bool(o.force) && prev?.updated_at === gist.updated_at && fs.existsSync(c.file)) {
        content = fs.readFileSync(c.file, 'utf8');
        status = 'cached';
      } else {
        content = file.content;
        if (file.truncated || !content) {
          const rawUrl = `${file.raw_url}${file.raw_url.includes('?') ? '&' : '?'}ts=${Date.now()}`;
          content = await fetchTextWithTimeout(rawUrl, { 'User-Agent': 'clash-gist-pool/1.0' });
        }
        writeText(c.file, content);
        status = 'updated';
      }
      const items = extractProxies(content);
      state.sources[src.tag] = {
        updated_at: gist.updated_at,
        fetched_at: new Date().toISOString(),
        sha256: sha256(content),
        items: items.length,
        size: Buffer.byteLength(content),
        history: (gist.history || []).slice(0, 15).map(h => h.committed_at),
        status,
        error: null
      };
      writeJson(c.meta, { ...state.sources[src.tag], description: gist.description || '' });
      entries.push({ src, content, items, gist, status });
      log(`[sync] ${src.tag.padEnd(11)} ${status.padEnd(7)} items=${String(items.length).padStart(4)} updated=${gist.updated_at}`);
    } catch (e) {
      const prev = state.sources[src.tag];
      if (fs.existsSync(c.file)) {
        content = fs.readFileSync(c.file, 'utf8');
        const items = extractProxies(content);
        status = 'stale-cache';
        state.sources[src.tag] = { ...prev, status, error: String(e.message || e) };
        entries.push({ src, content, items, gist, status });
        warn(`[sync] ${src.tag}: ${e.message} — using stale cache (${items.length} items)`);
      } else {
        status = 'error';
        state.sources[src.tag] = { ...prev, status, error: String(e.message || e) };
        errors.push({ tag: src.tag, error: String(e.message || e) });
        warn(`[sync] ${src.tag}: ${e.message}`);
      }
    }
  }
  state.lastSync = new Date().toISOString();
  state.errors = errors;
  writeJson(statePath, state);
  return entries;
}

function uniqueTag(owner, used) {
  let base = String(owner || 'src').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'src';
  let tag = base;
  let n = 2;
  while (used.has(tag)) tag = `${base}-${n++}`;
  used.add(tag);
  return tag;
}

function cadenceLabel(c) {
  if (!c) return 'unknown';
  return `${c.medianGapMin}m median, ${c.runs} recent`;
}

async function discoverSources(out, o) {
  const cfgFile = readJson(SOURCES_PATH, { sources: [] });
  const cfg = { ...DEFAULT_DISCOVERY, ...(cfgFile.discovery || {}) };
  const queries = o.query ? String(o.query).split(',').map(s => s.trim()).filter(Boolean) : cfg.queries;
  const maxPages = Math.max(1, num(o['max-pages'], cfg.maxPages));
  const maxAgeDays = num(o['max-age-days'], cfg.maxAgeDays);
  const minNodes = num(o['min-nodes'], cfg.minNodes);
  const minCaTls = num(o['min-ca-tls'], cfg.minCaTls);
  const maxCandidates = Math.max(1, num(o['max-candidates'], cfg.maxCandidates));
  const token = loadGithubToken();
  const allSources = Array.isArray(cfgFile.sources) ? cfgFile.sources : [];
  const knownIds = new Set(allSources.map(s => s.id));
  const usedTags = new Set(allSources.map(s => s.tag));
  const candidates = new Map();

  for (const q of queries) {
    for (let page = 1; page <= maxPages; page++) {
      const url = `https://gist.github.com/search?q=${encodeURIComponent(q)}${page > 1 ? `&p=${page}` : ''}`;
      try {
        const html = await fetchTextWithTimeout(url, { 'User-Agent': 'Mozilla/5.0 (compatible; clash-gist-pool/1.0)' }, 30000);
        for (const m of html.matchAll(/href="\/([A-Za-z0-9_-]+)\/([0-9a-f]{20,})"/g)) {
          const owner = m[1];
          const id = m[2];
          if (knownIds.has(id) || candidates.has(id)) continue;
          candidates.set(id, { owner, id, query: q });
        }
      } catch (e) {
        warn(`[discover] search failed for "${q}" page ${page}: ${e.message}`);
      }
    }
  }

  const picked = [...candidates.values()].slice(0, maxCandidates);
  log(`[discover] ${candidates.size} unique candidates, auditing ${picked.length}`);
  const results = [];
  for (const c of picked) {
    try {
      const g = await getGistMeta({ id: c.id }, token);
      const ageDays = (Date.now() - new Date(g.updated_at).getTime()) / 86400000;
      if (ageDays > maxAgeDays) continue;
      const file = g.files?.['all.yaml'];
      if (!file || !file.size) continue;
      let content = file.content;
      if (file.truncated || !content) {
        content = await fetchTextWithTimeout(`${file.raw_url}${file.raw_url.includes('?') ? '&' : '?'}ts=${Date.now()}`, { 'User-Agent': 'clash-gist-pool/1.0' });
      }
      if (/^proxy-groups:\s*$/m.test(content) || /^rules:\s*$/m.test(content)) continue;
      const items = extractProxies(content);
      if (items.length < minNodes) continue;
      let insecure = 0;
      let caTls = 0;
      const types = {};
      for (const item of items) {
        const p = parseProxyBlock(item.text);
        if (p.inline || !p.name) continue;
        if (p.insecure) insecure++;
        if (isCaTls(p)) caTls++;
        if (p.type) types[p.type] = (types[p.type] || 0) + 1;
      }
      if (caTls < minCaTls) continue;
      const cadence = cadenceFromHistory(g.history);
      results.push({
        owner: c.owner, id: c.id, query: c.query,
        gist: `https://gist.github.com/${c.owner}/${c.id}`,
        raw: `https://gist.githubusercontent.com/${c.owner}/${c.id}/raw/all.yaml`,
        description: g.description || '',
        updated_at: g.updated_at,
        ageDays: Number(ageDays.toFixed(1)),
        nodes: items.length, insecure, caTls, types,
        cadence: cadence ? { runs: cadence.runs, medianGapMin: cadence.medianGapMin } : null
      });
    } catch (e) {
      warn(`[discover] audit failed for ${c.owner}/${c.id}: ${e.message}`);
    }
  }

  results.sort((a, b) => (b.caTls - a.caTls) || (b.nodes - a.nodes) || (new Date(b.updated_at) - new Date(a.updated_at)));
  writeJson(path.join(out, 'discovered.json'), { generatedAt: new Date().toISOString(), queries, candidates: results });
  const md = ['# Discovered Gist candidates', '', `Generated: ${new Date().toISOString()}`, '', '| Gist | Updated | Nodes | skip-cert | CA-TLS | Cadence |', '|---|---:|---:|---:|---:|---|'];
  for (const r of results) {
    md.push(`| [${r.owner}](${r.gist}) / [raw](${r.raw}) | ${r.updated_at} | ${r.nodes} | ${r.insecure} | ${r.caTls} | ${r.cadence ? r.cadence.medianGapMin + 'm' : '-'} |`);
  }
  md.push('', 'Candidates are not added unless `--add` is passed; added sources default to `enabled: false`. Review this file, then set `enabled: true` for sources worth testing.', '');
  writeText(path.join(out, 'discovered.md'), md.join('\n'));

  let added = 0;
  if (bool(o.add)) {
    for (const r of results) {
      if (allSources.some(s => s.id === r.id)) continue;
      const tag = uniqueTag(r.owner, usedTags);
      const maxPriority = allSources.reduce((n, s) => Math.max(n, Number(s.priority) || 0), 0);
      allSources.push({
        tag, owner: r.owner, id: r.id,
        gist: r.gist, raw: r.raw,
        priority: maxPriority + 1,
        enabled: false,
        expectedNodes: r.nodes,
        cadence: cadenceLabel(r.cadence ? { ...r.cadence, runs: r.cadence.runs } : null),
        lastAudit: new Date().toISOString().slice(0, 10),
        notes: `discovered by "${r.query}"; skip-cert ${r.insecure}; CA-TLS ${r.caTls}; review before enabling`
      });
      added++;
    }
    if (added) {
      cfgFile.sources = allSources;
      writeJson(SOURCES_PATH, cfgFile);
    }
  }
  log(`[discover] ${results.length} passing candidates; ${added} added disabled; report ${path.join(out, 'discovered.md')}`);
  for (const r of results.slice(0, 10)) {
    log(`[discover] ${r.owner.padEnd(20)} nodes=${String(r.nodes).padStart(4)} caTls=${String(r.caTls).padStart(3)} updated=${r.updated_at}`);
  }
  return results;
}

function buildPool(out, entries, o) {
  const ordered = [...entries].filter(e => e.content).sort((a, b) => (a.src.priority || 99) - (b.src.priority || 99));
  const usedKeys = new Set();
  const usedNames = new Set();
  const records = [];
  const sources = [];
  const skip = { inline: 0, invalid: 0, type: 0, insecure: 0, caTls: 0, duplicate: 0, rename: 0 };
  const allowTypes = o.types
    ? new Set(String(o.types).split(',').map(s => s.trim().toLowerCase()).filter(Boolean))
    : SUPPORTED_TYPES;

  for (const e of ordered) {
    const stat = {
      tag: e.src.tag, updatedAt: e.gist?.updated_at || '', status: e.status,
      cadence: e.src.cadence || '',
      raw: e.items.length, accepted: 0, insecure: 0, duplicate: 0, skipped: 0
    };
    for (const item of e.items) {
      const p = parseProxyBlock(item.text);
      if (p.inline) { skip.inline++; stat.skipped++; continue; }
      if (!p.name || !p.type || !p.server || !p.port || p.port < 1 || p.port > 65535) {
        skip.invalid++; stat.skipped++; continue;
      }
      if (!allowTypes.has(p.type)) { skip.type++; stat.skipped++; continue; }
      if (p.insecure) stat.insecure++;
      if (bool(o['exclude-insecure']) && p.insecure) { skip.insecure++; stat.skipped++; continue; }
      if (bool(o['ca-tls']) && !isCaTls(p)) { skip.caTls++; stat.skipped++; continue; }
      const key = proxyKey(p);
      if (usedKeys.has(key)) { skip.duplicate++; stat.duplicate++; continue; }
      usedKeys.add(key);

      const base = makeName(e.src.tag, p.name);
      let name = base;
      let n = 2;
      while (usedNames.has(name)) name = `${base}~${n++}`;
      usedNames.add(name);
      const block = renameBlock(item.text, name);
      if (!block) { skip.rename++; stat.skipped++; continue; }

      records.push({
        name, source: e.src.tag, type: p.type, server: p.server, port: p.port,
        insecure: p.insecure, block
      });
      stat.accepted++;
    }
    sources.push(stat);
  }

  writeText(path.join(out, 'merged.yaml'), renderProxies(records));
  const meta = records.map(({ name, source, type, server, port, insecure }) => ({ name, source, type, server, port, insecure }));
  writeJson(path.join(out, 'pool-meta.json'), meta);
  const summary = {
    generatedAt: new Date().toISOString(),
    sources,
    totals: {
      raw: sources.reduce((n, s) => n + s.raw, 0),
      accepted: records.length,
      duplicates: skip.duplicate,
      insecure: records.filter(r => r.insecure).length,
      skipped: Object.values(skip).reduce((a, b) => a + b, 0)
    },
    skip,
    types: records.reduce((m, r) => (m[r.type] = (m[r.type] || 0) + 1, m), {})
  };
  writeJson(path.join(out, 'pool-summary.json'), summary);
  return { records, summary };
}

function findCore(o) {
  const candidates = [
    o.core,
    process.env.MIHOMO_BIN,
    'C:\\Program Files\\Clash Verge\\verge-mihomo.exe',
    'C:\\Program Files\\Clash Verge Rev\\verge-mihomo.exe',
    '/Applications/Clash Verge.app/Contents/MacOS/verge-mihomo',
    path.join(os.homedir(), '.local', 'bin', 'mihomo'),
    path.join(os.homedir(), 'bin', 'mihomo'),
    '/usr/local/bin/mihomo',
    '/usr/bin/mihomo',
    '/opt/mihomo/mihomo',
    '/usr/local/bin/verge-mihomo',
    '/usr/bin/verge-mihomo',
    '/usr/local/bin/clash-meta',
    '/usr/bin/clash-meta'
  ].filter(Boolean);
  for (const p of candidates) {
    try { if (fs.statSync(p).isFile()) return p; } catch {}
  }
  try {
    const cmd = process.platform === 'win32' ? 'where.exe' : 'which';
    const names = process.platform === 'win32'
      ? ['verge-mihomo.exe', 'mihomo.exe']
      : ['mihomo', 'verge-mihomo', 'clash-meta'];
    for (const name of names) {
      try {
        const out = execFileSync(cmd, [name], { encoding: 'utf8' }).split(/\r?\n/).find(Boolean);
        if (out && fs.existsSync(out.trim())) return out.trim();
      } catch {}
    }
  } catch {}
  throw new Error('mihomo core not found; install it (scripts/install-mihomo.sh) or pass --core <path> / set MIHOMO_BIN');
}

function detectTun() {
  if (process.platform !== 'win32') return null;
  try {
    const script = "Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'Up' -and ($_.Name -like 'Mihomo*' -or $_.InterfaceDescription -like '*Meta Tunnel*') } | Select-Object -ExpandProperty Name";
    const out = execFileSync('powershell.exe', ['-NoProfile', '-Command', script], { encoding: 'utf8', timeout: 10000 }).trim();
    return out || null;
  } catch { return null; }
}

function coreVersion(core) {
  try { return execFileSync(core, ['-v'], { encoding: 'utf8', timeout: 15000 }).trim().split(/\r?\n/)[0]; }
  catch { return 'unknown'; }
}

function isPortFree(port) {
  return new Promise(resolve => {
    const srv = net.createServer();
    srv.once('error', () => resolve(false));
    srv.once('listening', () => srv.close(() => resolve(true)));
    srv.listen(port, '127.0.0.1');
  });
}

async function findFreePorts(mixedStart, apiStart) {
  let mixed = null, api = null;
  for (let p = mixedStart; p < mixedStart + 100; p++) {
    if (await isPortFree(p)) { mixed = p; break; }
  }
  if (!mixed) throw new Error('no free mixed-port found');
  for (let p = apiStart; p < apiStart + 100; p++) {
    if (p === mixed) continue;
    if (await isPortFree(p)) { api = p; break; }
  }
  if (!api) throw new Error('no free api-port found');
  return { mixed, api };
}

function apiGet(port, apiPath, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    const req = http.get({ host: '127.0.0.1', port, path: apiPath, timeout: timeoutMs }, res => {
      let data = '';
      res.setEncoding('utf8');
      res.on('data', d => data += d);
      res.on('end', () => {
        let json = null;
        try { json = data ? JSON.parse(data) : {}; } catch {}
        if (res.statusCode !== 200) {
          reject(new Error(json?.message || `HTTP ${res.statusCode}: ${tail(data, 200)}`));
        } else {
          resolve(json);
        }
      });
    });
    req.on('timeout', () => req.destroy(new Error(`API timeout after ${timeoutMs}ms`)));
    req.on('error', reject);
  });
}

async function waitForApi(port, child, timeoutMs = 25000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (child.exitCode !== null) throw new Error(`core exited with code ${child.exitCode}`);
    try { await apiGet(port, '/version', 1500); return; } catch {}
    await sleep(300);
  }
  throw new Error('core API did not become ready');
}

async function mapPool(items, limit, fn) {
  const results = new Array(items.length);
  let next = 0;
  const width = Math.max(1, Math.min(limit, items.length));
  async function worker() {
    while (true) {
      const i = next++;
      if (i >= items.length) return;
      results[i] = await fn(items[i], i);
    }
  }
  await Promise.all(Array.from({ length: width }, () => worker()));
  return results;
}

function testConfigText(ports, records) {
  const lines = [
    `mixed-port: ${ports.mixed}`,
    `external-controller: 127.0.0.1:${ports.api}`,
    'mode: rule',
    'log-level: warning',
    'ipv6: true',
    'dns:',
    '  enable: true',
    '  ipv6: true',
    '  default-nameserver:',
    '    - 223.5.5.5',
    '    - 119.29.29.29',
    '  proxy-server-nameserver:',
    '    - https://doh.pub/dns-query',
    '    - https://dns.alidns.com/dns-query',
    '  nameserver:',
    '    - https://doh.pub/dns-query',
    '    - https://dns.alidns.com/dns-query',
    'proxies:'
  ];
  for (const r of records) lines.push(indentBlock(r.block, 2));
  lines.push('proxy-groups:', '  - name: TEST', '    type: select', '    proxies:');
  for (const r of records) lines.push(`      - ${JSON.stringify(r.name)}`);
  lines.push('rules:', '  - MATCH,DIRECT', '');
  return lines.join('\n');
}

function resultSummary(results) {
  const ok = results.filter(r => r.ok);
  const delays = ok.map(r => r.delay).sort((a, b) => a - b);
  const median = delays.length ? delays[Math.floor(delays.length / 2)] : null;
  return { tested: results.length, ok: ok.length, failed: results.length - ok.length, medianDelay: median };
}

function writeReport(out, o, ctx) {
  const summary = readJson(path.join(out, 'pool-summary.json'), null);
  const results = readJson(path.join(out, 'results.json'), null);
  const lines = [];
  lines.push('# clash-gist-pool report', '');
  lines.push(`- Generated: ${new Date().toISOString()}`);
  lines.push(`- Core: ${ctx.coreVersion || 'not tested'}`);
  lines.push(`- Output: \`${out}\``);
  if (ctx.tun) lines.push(`- WARNING: TUN adapter detected (${ctx.tun}); test results may be contaminated.`);
  if (ctx.allowTun && ctx.tun) lines.push('- Tests were run with --allow-tun. Do not treat delays as clean measurements.');
  lines.push('');

  if (summary) {
    lines.push('## Sources', '');
    lines.push('| Source | Updated | Raw | Accepted | Dup | Insecure | Cadence |');
    lines.push('|---|---:|---:|---:|---:|---:|---|');
    for (const s of summary.sources) {
      const state = ctx.state?.sources?.[s.tag];
      const cadence = sourceCadenceNote({ cadence: s.cadence }, state);
      lines.push(`| ${s.tag} | ${s.updatedAt || '-'} | ${s.raw} | ${s.accepted} | ${s.duplicate || 0} | ${s.insecure || 0} | ${cadence || '-'} |`);
    }
    lines.push('');
    lines.push(`Totals: raw ${summary.totals.raw}, accepted ${summary.totals.accepted}, duplicates ${summary.totals.duplicates}, insecure ${summary.totals.insecure}, skipped ${summary.totals.skipped}.`);
    const types = Object.entries(summary.types || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k}:${v}`).join(', ');
    if (types) lines.push(`Types: ${types}.`);
    lines.push('');
  }

  if (results) {
    const rs = resultSummary(results);
    lines.push('## Tests', '');
    lines.push(`- Tested: ${rs.tested}`);
    lines.push(`- OK: ${rs.ok}`);
    lines.push(`- Failed: ${rs.failed}`);
    lines.push(`- Median delay: ${rs.medianDelay ?? '-'} ms`);
    const maxDelay = num(o['max-delay'], 1500);
    const usableMeta = readJson(path.join(out, 'usable-meta.json'), null);
    const usableCount = usableMeta ? usableMeta.length : results.filter(r => r.ok && r.delay > 0 && r.delay <= maxDelay).length;
    lines.push(`- Usable (delay <= ${maxDelay} ms${bool(o['exclude-insecure']) ? ', skip-cert-verify excluded' : ''}${bool(o['ca-tls']) ? ', CA-TLS only' : ''}): ${usableCount}`);
    lines.push('');
    const top = results.filter(r => r.ok).sort((a, b) => a.delay - b.delay).slice(0, 20);
    if (top.length) {
      lines.push('### Fastest', '');
      lines.push('| # | Name | Source | Type | Delay |');
      lines.push('|---:|---|---|---|---:|');
      top.forEach((r, i) => lines.push(`| ${i + 1} | ${String(r.name).replace(/\|/g, '\\|')} | ${r.source || '-'} | ${r.type || '-'} | ${r.delay} ms |`));
      lines.push('');
    }
    const fails = results.filter(r => !r.ok);
    if (fails.length) {
      lines.push('### Failed samples', '');
      for (const r of fails.slice(0, 15)) lines.push(`- ${r.name} (${r.type || '?'}): ${r.error || 'failed'}`);
      lines.push('');
    }
  }

  lines.push('## Safety', '');
  lines.push('- These are third-party public free nodes. Assume the operator can log or modify traffic.');
  lines.push('- Do not use them for banking, primary email, GitHub, or other sensitive accounts.');
  lines.push('- `skip-cert-verify: true` is common in these pools; use `--exclude-insecure` to remove those nodes.');
  lines.push('- This tool never edits your active Clash config; it only writes files under the output directory.');
  lines.push('');
  writeText(path.join(out, 'report.md'), lines.join('\n'));
}

async function runTests(out, o, pool) {
  const tun = detectTun();
  if (tun && !bool(o['allow-tun'])) {
    throw new Error(`TUN adapter is up (${tun}). Turn off TUN before testing, or pass --allow-tun to run a contaminated smoke test.`);
  }
  const core = findCore(o);
  const ver = coreVersion(core);
  log(`[test] core: ${ver}`);
  if (tun) warn(`[test] WARNING: TUN adapter is up (${tun}); results may be contaminated.`);

  let records = pool.records;
  if (o.source) records = records.filter(r => r.source === o.source);
  if (o.type) {
    const types = new Set(String(o.type).split(',').map(s => s.trim().toLowerCase()));
    records = records.filter(r => types.has(r.type));
  }
  const limit = num(o.limit, 0);
  if (limit > 0) records = records.slice(0, limit);
  if (!records.length) throw new Error('no proxies selected for testing');

  const ports = await findFreePorts(num(o['mixed-port'], 17990), num(o['api-port'], 19090));
  const testDir = path.join(out, 'test');
  ensureDir(testDir);
  const dataDir = path.join(testDir, 'data');
  ensureDir(dataDir);
  const cfgPath = path.join(testDir, 'config.yaml');
  const coreLogPath = path.join(testDir, 'core.log');
  writeText(cfgPath, testConfigText(ports, records));

  const check = spawnSync(core, ['-t', '-f', cfgPath, '-d', dataDir], { encoding: 'utf8', timeout: 90000, windowsHide: true });
  if (check.status !== 0) {
    const detail = tail(`${check.stdout || ''}\n${check.stderr || ''}`, 4000);
    writeText(path.join(testDir, 'validate.log'), detail);
    throw new Error(`core config validation failed. See ${path.join(testDir, 'validate.log')}\n${detail}`);
  }

  const logStream = fs.createWriteStream(coreLogPath, { flags: 'w' });
  const child = spawn(core, ['-d', dataDir, '-f', cfgPath], { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(logStream);
  child.stderr.pipe(logStream);
  let stopRequested = false;
  const stop = async () => {
    if (stopRequested) return;
    stopRequested = true;
    try { child.kill(); } catch {}
    await sleep(400);
    if (child.exitCode === null && process.platform === 'win32') {
      try { execFileSync('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' }); } catch {}
    }
  };

  try {
    await waitForApi(ports.api, child);
    const url = o.url || DEFAULT_URL;
    const timeout = num(o.timeout, 5000);
    const attempts = Math.max(1, num(o.attempts, 1));
    const concurrency = Math.max(1, num(o.concurrency, 16));
    let done = 0;
    log(`[test] ${records.length} proxies, concurrency ${concurrency}, timeout ${timeout}ms, url ${url}`);
    const results = await mapPool(records, concurrency, async (r) => {
      let best = null;
      let lastError = '';
      for (let a = 0; a < attempts; a++) {
        try {
          const path = `/proxies/${encodeURIComponent(r.name)}/delay?url=${encodeURIComponent(url)}&timeout=${timeout}`;
          const res = await apiGet(ports.api, path, timeout + 4000);
          const delay = Number(res.delay);
          if (Number.isFinite(delay) && delay > 0) { best = delay; break; }
          lastError = res.message || 'no delay';
        } catch (e) {
          lastError = String(e.message || e);
        }
      }
      done++;
      if (done % 25 === 0 || done === records.length) process.stderr.write(`\r[test] ${done}/${records.length}`);
      return {
        name: r.name, source: r.source, type: r.type, server: r.server, port: r.port,
        insecure: r.insecure, ok: best !== null, delay: best, error: best === null ? tail(lastError, 300) : ''
      };
    });
    process.stderr.write('\n');
    writeJson(path.join(out, 'results.json'), results);
    buildUsable(out, o, results, records);
    writeReport(out, o, { coreVersion: ver, tun, allowTun: bool(o['allow-tun']), state: readJson(path.join(out, 'state.json'), {}) });
    return { results, coreVersion: ver, tun };
  } finally {
    await stop();
    logStream.end();
  }
}

function loadTargets(o) {
  const file = path.resolve(o['targets-file'] || process.env.TARGETS_FILE || path.join(SKILL_ROOT, 'targets.json'));
  let raw = readJson(file, null);
  if (!raw) {
    if (o['targets-file']) throw new Error(`targets file not found: ${file}`);
    raw = readJson(SOURCES_PATH, {}).targets || [];
  }
  const list = Array.isArray(raw) ? raw : raw.targets;
  const all = (Array.isArray(list) ? list : []).filter(t => {
    if (!t || !t.name || !t.url) return false;
    try { new URL(t.url); return true; } catch { return false; }
  });
  const names = o.targets ? String(o.targets).split(',').map(s => s.trim()).filter(Boolean) : null;
  return names ? all.filter(t => names.includes(t.name)) : all;
}

function writeSiteReport(out, ctx) {
  const { results, targets, coreVersion, tun, allowTun } = ctx;
  const lines = [];
  lines.push('# Site latency report', '');
  lines.push(`- Generated: ${new Date().toISOString()}`);
  lines.push(`- Core: ${coreVersion}`);
  lines.push(`- Tested nodes: ${results.length}`);
  if (tun) lines.push(`- WARNING: TUN adapter detected (${tun}); results are contaminated.`);
  lines.push('');
  lines.push('## Targets', '');
  lines.push('| Target | URL | OK | Median |');
  lines.push('|---|---|---:|---:|');
  for (const t of targets) {
    const ds = results.map(r => r.targets[t.name]).filter(x => x && x.ok).map(x => x.delay).sort((a, b) => a - b);
    const med = ds.length ? ds[Math.floor(ds.length / 2)] : null;
    lines.push(`| ${t.name} | ${t.url} | ${ds.length}/${results.length} | ${med === null ? '-' : med + ' ms'} |`);
  }
  lines.push('');
  lines.push('## Matrix', '');
  const header = ['Node', 'Type', ...targets.map(t => t.name)];
  lines.push(`| ${header.join(' | ')} |`);
  lines.push(`|${header.map(() => '---').join('|')}|`);
  const sorted = [...results].sort((a, b) => {
    const avg = r => {
      const ds = Object.values(r.targets).filter(x => x && x.ok).map(x => x.delay);
      return ds.length ? ds.reduce((n, x) => n + x, 0) / ds.length : 99999;
    };
    return avg(a) - avg(b);
  });
  for (const r of sorted) {
    const cells = targets.map(t => {
      const x = r.targets[t.name];
      return x && x.ok ? `${x.delay} ms` : '×';
    });
    lines.push(`| ${String(r.name).replace(/\|/g, '\\|')} | ${r.type || '-'} | ${cells.join(' | ')} |`);
  }
  lines.push('');
  lines.push('## Notes', '');
  lines.push('- The delay API sends an HTTP request through the proxy to the target URL; it is not just a TCP handshake to the proxy server.');
  lines.push('- A 403/Cloudflare/captcha page may still count as a successful delay. This measures reachability/latency, not account access, streaming availability, or region unlock.');
  lines.push('- Use TUN off for clean numbers; a TUN detection warning means the test traffic may be double-proxied.');
  lines.push('');
  writeText(path.join(out, 'site-report.md'), lines.join('\n'));
}

async function siteTest(out, o) {
  const usablePath = path.join(out, 'usable.yaml');
  if (!fs.existsSync(usablePath)) throw new Error('missing usable.yaml; run pipeline/test first');
  const targets = loadTargets(o);
  if (!targets.length) throw new Error('no targets matched');
  const meta = readJson(path.join(out, 'usable-meta.json'), []);
  const byName = new Map(meta.map(m => [m.name, m]));
  let records = extractProxies(fs.readFileSync(usablePath, 'utf8')).map(item => {
    const p = parseProxyBlock(item.text);
    return { ...p, block: item.text, source: byName.get(p.name)?.source || '' };
  }).filter(r => r.name && r.block);
  if (o.source) records = records.filter(r => r.source === o.source);
  if (o.type) {
    const types = new Set(String(o.type).split(',').map(s => s.trim().toLowerCase()));
    records = records.filter(r => types.has(r.type));
  }
  const limit = num(o.limit, 0);
  if (limit > 0) records = records.slice(0, limit);
  if (!records.length) throw new Error('no proxies selected for site test');

  const tun = detectTun();
  if (tun && !bool(o['allow-tun'])) {
    throw new Error(`TUN adapter is up (${tun}). Turn off TUN before site-test, or pass --allow-tun for a contaminated smoke test.`);
  }
  const core = findCore(o);
  const ver = coreVersion(core);
  if (tun) warn(`[site-test] WARNING: TUN adapter is up (${tun}); results are contaminated.`);
  const ports = await findFreePorts(num(o['mixed-port'], 17990), num(o['api-port'], 19090));
  const testDir = path.join(out, 'site-test');
  ensureDir(testDir);
  const dataDir = path.join(testDir, 'data');
  ensureDir(dataDir);
  const cfgPath = path.join(testDir, 'config.yaml');
  const coreLogPath = path.join(testDir, 'core.log');
  writeText(cfgPath, testConfigText(ports, records));
  const check = spawnSync(core, ['-t', '-f', cfgPath, '-d', dataDir], { encoding: 'utf8', timeout: 90000, windowsHide: true });
  if (check.status !== 0) {
    const detail = tail(`${check.stdout || ''}\n${check.stderr || ''}`, 4000);
    writeText(path.join(testDir, 'validate.log'), detail);
    throw new Error(`core config validation failed. See ${path.join(testDir, 'validate.log')}\n${detail}`);
  }

  const logStream = fs.createWriteStream(coreLogPath, { flags: 'w' });
  const child = spawn(core, ['-d', dataDir, '-f', cfgPath], { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(logStream);
  child.stderr.pipe(logStream);
  let stopRequested = false;
  const stop = async () => {
    if (stopRequested) return;
    stopRequested = true;
    try { child.kill(); } catch {}
    await sleep(400);
    if (child.exitCode === null && process.platform === 'win32') {
      try { execFileSync('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' }); } catch {}
    }
  };

  try {
    await waitForApi(ports.api, child);
    const timeout = num(o.timeout, 5000);
    const concurrency = Math.max(1, num(o.concurrency, 8));
    let done = 0;
    log(`[site-test] ${records.length} proxies x ${targets.length} targets, concurrency ${concurrency}`);
    const results = await mapPool(records, concurrency, async (r) => {
      const row = { name: r.name, source: r.source, type: r.type, targets: {} };
      for (const t of targets) {
        try {
          const apiPath = `/proxies/${encodeURIComponent(r.name)}/delay?url=${encodeURIComponent(t.url)}&timeout=${timeout}`;
          const res = await apiGet(ports.api, apiPath, timeout + 4000);
          const delay = Number(res.delay);
          row.targets[t.name] = Number.isFinite(delay) && delay > 0
            ? { ok: true, delay }
            : { ok: false, error: res.message || 'no delay' };
        } catch (e) {
          row.targets[t.name] = { ok: false, error: tail(e.message || String(e), 200) };
        }
      }
      done++;
      process.stderr.write(`\r[site-test] ${done}/${records.length}`);
      return row;
    });
    process.stderr.write('\n');
    writeJson(path.join(out, 'site-results.json'), {
      generatedAt: new Date().toISOString(),
      coreVersion: ver,
      targets,
      results
    });
    writeSiteReport(out, { results, targets, coreVersion: ver, tun, allowTun: bool(o['allow-tun']) });
    log(`[site-test] report -> ${path.join(out, 'site-report.md')}`);
    return results;
  } finally {
    await stop();
    logStream.end();
  }
}

async function publishGist(out, o) {
  const usablePath = path.join(out, 'usable.yaml');
  if (!fs.existsSync(usablePath)) throw new Error(`missing ${usablePath}; run test first`);
  const content = fs.readFileSync(usablePath, 'utf8');
  const usableItems = extractProxies(content);
  if (usableItems.length === 0) {
    throw new Error('usable.yaml has no proxies; refusing to publish an empty nodes.yaml');
  }
  const meta = readJson(path.join(out, 'usable-meta.json'), []);
  const insecure = meta.filter(x => x && x.insecure).length;
  if (insecure > 0 && !bool(o['allow-insecure'])) {
    throw new Error(`usable.yaml has ${insecure} skip-cert-verify:true nodes; run build --exclude-insecure first, or pass --allow-insecure`);
  }
  const publishState = readJson(path.join(out, 'publish.json'), null);
  const prevCount = Number(publishState?.nodes_count || 0);
  if (prevCount > 0) {
    const minKeep = Math.max(3, Math.floor(prevCount * 0.5));
    if (meta.length < minKeep && !bool(o['allow-shrink'])) {
      throw new Error(`refusing to shrink subscription from ${prevCount} to ${meta.length} nodes (minimum ${minKeep}); pass --allow-shrink intentionally`);
    }
  }
  const caTls = bool(o['ca-tls']) || !!publishState?.ca_tls;
  if (caTls) {
    const bad = extractProxies(content)
      .map(item => parseProxyBlock(item.text))
      .filter(p => p.inline || !isCaTls(p)).length;
    if (bad > 0 && !bool(o['allow-non-ca-tls'])) {
      throw new Error(`this is a CA-TLS subscription but usable.yaml has ${bad} non-CA-TLS/Reality/plain nodes; run build --exclude-insecure --ca-tls, or pass --allow-non-ca-tls`);
    }
  }
  const token = loadGithubToken();
  if (!token) throw new Error('GITHUB_TOKEN not found (env or github-account/.env)');
  const headers = { ...apiHeaders(token), 'Content-Type': 'application/json' };
  const publishPath = path.join(out, 'publish.json');
  const state = readJson(publishPath, null);
  const gistId = o.gist || process.env.GIST_ID || state?.id;

  if (bool(o.create) || !gistId) {
    const res = await fetch('https://api.github.com/gists', {
      method: 'POST', headers,
      body: JSON.stringify({
        description: o.description || 'Clash gist pool subscription (nodes.yaml)',
        public: false,
        files: { 'nodes.yaml': { content } }
      })
    });
    const g = await res.json();
    if (!res.ok) throw new Error(`create gist failed: ${g.message || res.status}`);
    const owner = g.owner?.login || state?.owner;
    const next = {
      id: g.id, owner,
      html_url: g.html_url,
      raw_nodes: `https://gist.githubusercontent.com/${owner}/${g.id}/raw/nodes.yaml`,
      description: g.description,
      updated_at: g.updated_at,
      nodes_count: meta.length || undefined,
      strict: insecure === 0,
      ca_tls: caTls
    };
    writeJson(publishPath, next);
    log(`[publish] created secret gist ${g.id}`);
    log(`[publish] nodes: ${next.raw_nodes}`);
    return next;
  }

  const res = await fetch(`https://api.github.com/gists/${gistId}`, {
    method: 'PATCH', headers,
    body: JSON.stringify({ files: { 'nodes.yaml': { content } } })
  });
  const g = await res.json();
  if (!res.ok) throw new Error(`update gist failed: ${g.message || res.status}`);
  const remote = g.files?.['nodes.yaml']?.content;
  const owner = g.owner?.login || state?.owner;
  const next = {
    ...state,
    id: g.id, owner,
    html_url: g.html_url,
    raw_nodes: `https://gist.githubusercontent.com/${owner}/${g.id}/raw/nodes.yaml`,
    raw_config: state?.raw_config || `https://gist.githubusercontent.com/${owner}/${g.id}/raw/clash.yaml`,
    subscription_url: state?.subscription_url || `https://gist.githubusercontent.com/${owner}/${g.id}/raw/clash.yaml`,
    description: g.description,
    updated_at: g.updated_at,
    nodes_count: meta.length || state?.nodes_count,
    strict: insecure === 0,
    exactMatch: remote === content
  };
  writeJson(publishPath, next);
  log(`[publish] updated ${g.id}; exact match: ${next.exactMatch}`);
  log(`[publish] nodes: ${next.raw_nodes}`);
  return next;
}

function buildUsable(out, o, results, testedRecords) {
  const maxDelay = num(o['max-delay'], 1500);
  const byName = new Map(testedRecords.map(r => [r.name, r]));
  const usable = results
    .filter(r => !(bool(o['exclude-insecure']) && r.insecure))
    .filter(r => !(bool(o['ca-tls']) && !isCaTls(byName.get(r.name) || {})))
    .filter(r => r.ok && r.delay > 0 && r.delay <= maxDelay && byName.has(r.name))
    .sort((a, b) => a.delay - b.delay);
  const records = usable.map(r => byName.get(r.name));
  writeText(path.join(out, 'usable.yaml'), renderProxies(records));
  writeJson(path.join(out, 'usable-meta.json'), usable.map(({ name, source, type, server, port, insecure, delay }) => ({ name, source, type, server, port, insecure, delay })));
  log(`[build] usable: ${records.length}/${results.length} (<= ${maxDelay} ms) -> ${path.join(out, 'usable.yaml')}`);
  return usable;
}

async function main() {
  const { cmd, o } = parseArgs(process.argv.slice(2));
  if (o.help || cmd === 'help' || cmd === '-h') {
    log(`Usage:
  node scripts/clash-gist-pool.mjs sync [--out DIR] [--source TAG] [--force]
  node scripts/clash-gist-pool.mjs test [--limit N] [--source TAG] [--type http,vless]
  node scripts/clash-gist-pool.mjs build [--max-delay MS]   # rebuild usable.yaml from last results
  node scripts/clash-gist-pool.mjs run  [--limit N]
  node scripts/clash-gist-pool.mjs site-test [--targets github,google] [--limit N]
  node scripts/clash-gist-pool.mjs discover [--add] [--max-pages N] [--max-candidates N]
  node scripts/clash-gist-pool.mjs pipeline [--discover] [--publish] [--exclude-insecure] [--ca-tls]
  node scripts/clash-gist-pool.mjs publish [--gist ID] [--create] [--description TEXT]
  node scripts/clash-gist-pool.mjs status

Common options:
  --out DIR              output directory (default: ./gist-pool)
  --core PATH            mihomo core binary (or MIHOMO_BIN)
  --exclude-insecure     drop skip-cert-verify: true nodes
  --ca-tls               only CA-verified TLS: explicit tls:true (excluding Reality) or TLS-inherent protocols
  --allow-tun            allow tests while a TUN adapter is up (contaminated)
  --timeout MS           per-proxy delay timeout (default 5000)
  --concurrency N        parallel delay tests (default 16)
  --attempts N           attempts per proxy (default 1)
  --url URL              health-check URL for test/pipeline
  --targets LIST         site-test target names (default: all in targets.json)
  --targets-file PATH    alternate target list (JSON {targets:[{name,url}]})
  --max-delay MS         usable threshold (default 1500)
  --limit N              test/build only first N proxies
  --force                refetch even if updated_at is unchanged
  --allow-insecure       allow publish even if usable.yaml still has insecure nodes
  --allow-non-ca-tls     allow publish to a CA-TLS subscription with non-CA-TLS nodes
  --allow-shrink         allow publishing fewer than half of the previous node count
`);
    return;
  }

  const out = path.resolve(o.out || path.join(process.cwd(), 'gist-pool'));
  ensureDir(out);
  writeText(path.join(out, '.gitignore'), '*\n!.gitignore\n');

  if (cmd === 'status') {
    const state = readJson(path.join(out, 'state.json'), { sources: {} });
    const sources = loadSources();
    log('tag          updated_at                 items  status      cadence');
    for (const s of sources) {
      const st = state.sources[s.tag] || {};
      log(`${s.tag.padEnd(12)} ${String(st.updated_at || '-').padEnd(26)} ${String(st.items ?? '-').padStart(5)}  ${String(st.status || '-').padEnd(10)} ${s.cadence || ''}`);
    }
    return;
  }

  if (cmd === 'sync') {
    const entries = await syncSources(out, o);
    const pool = buildPool(out, entries, o);
    writeReport(out, o, { coreVersion: 'not tested', tun: detectTun(), allowTun: false, state: readJson(path.join(out, 'state.json'), {}) });
    log(`[sync] merged ${pool.summary.totals.accepted}/${pool.summary.totals.raw} -> ${path.join(out, 'merged.yaml')}`);
    log(`[sync] report -> ${path.join(out, 'report.md')}`);
    return;
  }

  if (cmd === 'build') {
    const results = readJson(path.join(out, 'results.json'), null);
    if (!results) throw new Error('no results.json; run test first');
    const text = fs.readFileSync(path.join(out, 'merged.yaml'), 'utf8');
    const meta = readJson(path.join(out, 'pool-meta.json'), []);
    const byName = new Map(meta.map(m => [m.name, m]));
    const records = extractProxies(text).map(item => {
      const p = parseProxyBlock(item.text);
      return { ...p, block: item.text, source: byName.get(p.name)?.source || '' };
    }).filter(p => p.name && p.block);
    buildUsable(out, o, results, records);
    writeReport(out, o, { coreVersion: 'from previous test', tun: detectTun(), allowTun: false, state: readJson(path.join(out, 'state.json'), {}) });
    log(`[build] report -> ${path.join(out, 'report.md')}`);
    return;
  }

  if (cmd === 'site-test') {
    await siteTest(out, o);
    return;
  }

  if (cmd === 'discover') {
    await discoverSources(out, o);
    return;
  }

  if (cmd === 'pipeline') {
    if (bool(o.discover)) await discoverSources(out, o);
    const entries = await syncSources(out, o);
    const pool = buildPool(out, entries, o);
    if (bool(o['no-test'])) {
      writeReport(out, o, { coreVersion: 'not tested', tun: detectTun(), allowTun: false, state: readJson(path.join(out, 'state.json'), {}) });
    } else {
      await runTests(out, o, pool);
    }
    if (bool(o.publish)) {
      await publishGist(out, { ...o, gist: o.gist || process.env.GIST_ID });
    }
    log(`[pipeline] done -> ${path.join(out, 'report.md')}`);
    return;
  }

  if (cmd === 'publish') {
    await publishGist(out, o);
    return;
  }

  if (cmd === 'test' || cmd === 'run') {
    let entries;
    if (cmd === 'run' || !fs.existsSync(path.join(out, 'merged.yaml'))) {
      entries = await syncSources(out, o);
    }
    const pool = entries ? buildPool(out, entries, o) : null;
    let mergedRecords = [];
    if (!pool) {
      const text = fs.readFileSync(path.join(out, 'merged.yaml'), 'utf8');
      const meta = readJson(path.join(out, 'pool-meta.json'), []);
      const byName = new Map(meta.map(m => [m.name, m]));
      mergedRecords = extractProxies(text).map(item => {
        const p = parseProxyBlock(item.text);
        const m = byName.get(p.name);
        return { ...p, block: item.text, source: m?.source || '' };
      }).filter(p => p.name && p.block);
    }
    const p = pool || { records: mergedRecords };
    await runTests(out, o, p);
    log(`[done] report -> ${path.join(out, 'report.md')}`);
    return;
  }

  throw new Error(`unknown command: ${cmd}`);
}

main().catch(e => {
  warn(`ERROR: ${e.message || e}`);
  if (process.argv.includes('--debug')) warn(e.stack || '');
  process.exit(1);
});

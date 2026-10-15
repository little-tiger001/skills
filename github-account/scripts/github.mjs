#!/usr/bin/env node
/* 操作 GitHub 账户（REST API，无第三方依赖）。
 * token 来自本 skill 目录的 .env（GITHUB_TOKEN=...）或环境变量 GITHUB_TOKEN / GH_TOKEN。
 * 只与 api.github.com / uploads.github.com 通信；任何输出都不包含 token。
 */
import fs from 'node:fs';
import path from 'node:path';
import https from 'node:https';
import { envValue, SKILL_ROOT } from './env.mjs';
const API = 'https://api.github.com';
const UPLOADS = 'https://uploads.github.com';
const UA = 'github-account-skill';

const USAGE = `用法:
  node scripts/github.mjs whoami
  node scripts/github.mjs repos [--limit 30]
  node scripts/github.mjs repo <owner/repo>
  node scripts/github.mjs about <owner/repo> [--description 文本] [--homepage URL] [--topics a,b,c] [--dry-run]
  node scripts/github.mjs rate
  node scripts/github.mjs deploy-keys <owner/repo>
  node scripts/github.mjs add-deploy-key <owner/repo> --key "ssh-ed25519 …" [--title 名称] [--read-only]
  node scripts/github.mjs releases <owner/repo> [--limit 20]
  node scripts/github.mjs release <owner/repo> --tag v1.0.0 [--name 标题] [--notes-file 文件]
        [--asset 文件]... [--target 分支] [--draft] [--prerelease] [--update-notes] [--replace-asset] [--dry-run]
  node scripts/github.mjs upload <owner/repo> --tag v1.0.0 --asset 文件 [--name 远端名] [--replace-asset] [--dry-run]`;

/* 不要用 process.exit()：在 Windows 上它会在 undici 的连接句柄还在收尾时
 * 触发 libuv 断言（Assertion failed: !(handle->flags & UV_HANDLE_CLOSING)），
 * 退出码变成 0xC0000409 并吐一行断言噪声。统一改成抛错 + 顶层设 exitCode。 */
function fail(msg) {
  throw new Error(msg);
}

function loadToken() {
  return envValue(['GITHUB_TOKEN']);
}

function parseArgs(argv) {
  const positional = [];
  const flags = { asset: [] };
  const bools = new Set(['draft', 'prerelease', 'update-notes', 'replace-asset', 'dry-run', 'read-only']);
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (!a.startsWith('--')) { positional.push(a); continue; }
    const key = a.slice(2);
    if (bools.has(key)) { flags[key] = true; continue; }
    const val = argv[i + 1];
    if (val === undefined || val.startsWith('--')) throw new Error(`--${key} 需要一个值`);
    i += 1;
    if (key === 'asset') flags.asset.push(val); else flags[key] = val;
  }
  return { positional, flags };
}

function normalizeRepo(input) {
  if (!input) throw new Error('缺少 <owner/repo>');
  let s = String(input).trim().replace(/\.git$/, '').replace(/\/+$/, '');
  const ssh = /^git@[^:]+:(.+)$/.exec(s);
  if (ssh) s = ssh[1];
  const url = /^https?:\/\/[^/]+\/(.+)$/.exec(s);
  if (url) s = url[1];
  if (!/^[^/\s]+\/[^/\s]+$/.test(s)) throw new Error(`无法解析仓库标识: ${input}（应为 owner/repo 或仓库 URL）`);
  return s;
}

const TOKEN = loadToken();

async function api(pathname, { method = 'GET', body, accept } = {}) {
  const res = await fetch(API + pathname, {
    method,
    headers: {
      Authorization: `Bearer ${TOKEN}`,
      Accept: accept || 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': UA,
      ...(body ? { 'Content-Type': 'application/json; charset=utf-8' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let json = null;
  try { json = text ? JSON.parse(text) : null; } catch { /* 非 JSON 响应 */ }
  if (!res.ok) {
    const msg = (json && json.message) || text.slice(0, 300) || '(无响应正文)';
    const doc = json && json.documentation_url ? `  ${json.documentation_url}` : '';
    const detail = json && Array.isArray(json.errors) && json.errors.length
      ? '\n  ' + json.errors.map((e) => `${e.resource || ''}${e.field ? '.' + e.field : ''} ${e.code || ''}`).join('\n  ')
      : '';
    throw new Error(`HTTP ${res.status}: ${msg}${doc}${detail}`);
  }
  return { json, headers: res.headers };
}

async function releaseByTag(repo, tag) {
  try {
    return (await api(`/repos/${repo}/releases/tags/${encodeURIComponent(tag)}`)).json;
  } catch (e) {
    if (/HTTP 404/.test(e.message)) return null;
    throw e;
  }
}

async function assetsOf(repo, releaseId) {
  return (await api(`/repos/${repo}/releases/${releaseId}/assets?per_page=100`)).json;
}

/* 大文件附件上传：用 https.request 流式发，不用 fetch。
 * fetch（undici）有 300 秒的 body 超时且拿不到进度，几十 MB 的安装包在慢线路上
 * 会直接以 "fetch failed" 结束、真正原因藏在 e.cause 里，排查极难。
 * 这里不设 socket 超时，每 10 MB 打一次进度，失败时把 HTTP 状态与响应正文带出来。
 */
function uploadStream(url, file, size) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const req = https.request(
      {
        method: 'POST',
        hostname: u.hostname,
        path: u.pathname + u.search,
        headers: {
          Authorization: `Bearer ${TOKEN}`,
          Accept: 'application/vnd.github+json',
          'Content-Type': 'application/octet-stream',
          'Content-Length': String(size),
          'User-Agent': UA,
        },
      },
      (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => {
          const text = Buffer.concat(chunks).toString('utf8');
          if (res.statusCode >= 200 && res.statusCode < 300) resolve(text);
          else {
            let msg = text.slice(0, 300);
            try { msg = JSON.parse(text).message || msg; } catch { /* 原样 */ }
            reject(new Error(`上传附件失败 HTTP ${res.statusCode}: ${msg}`));
          }
        });
      }
    );
    req.on('error', (e) => reject(new Error(`上传连接中断: ${e.code || e.message}`)));

    const stream = fs.createReadStream(file);
    let sent = 0;
    let mark = 0;
    stream.on('data', (chunk) => {
      sent += chunk.length;
      if (sent - mark >= 10 * 1024 * 1024) {
        mark = sent;
        process.stdout.write(`  …已发送 ${Math.round((sent / size) * 100)}%\n`);
      }
    });
    stream.on('error', (e) => reject(new Error('读取文件失败: ' + e.message)));
    stream.pipe(req);
  });
}

async function ensureAsset(repo, release, file, remoteName, flags) {
  if (!release) throw new Error('release 不存在，无法上传附件');
  if (!fs.existsSync(file)) throw new Error('附件不存在: ' + file);
  const stat = fs.statSync(file);
  if (!stat.isFile()) throw new Error('附件不是文件: ' + file);
  const name = remoteName || path.basename(file);

  const existing = (await assetsOf(repo, release.id)).find((a) => a.name === name);
  if (existing && !flags['replace-asset']) {
    console.log(`跳过: 远端已有同名附件 ${name}（要覆盖加 --replace-asset）`);
    return;
  }
  if (existing && flags['replace-asset']) {
    if (flags['dry-run']) console.log(`[dry-run] 会删除旧附件 ${name} (id=${existing.id}) 后重传`);
    else {
      await api(`/repos/${repo}/releases/assets/${existing.id}`, { method: 'DELETE' });
      console.log('已删除旧附件: ' + name);
    }
  }
  if (flags['dry-run']) {
    console.log(`[dry-run] 会上传 ${file}（${stat.size} 字节）作为 ${name}`);
    return;
  }

  const url = `${UPLOADS}/repos/${repo}/releases/${release.id}/assets?name=${encodeURIComponent(name)}`;
  console.log(`上传 ${name}（${(stat.size / 1024 / 1024).toFixed(1)} MB）…`);
  await uploadStream(url, file, stat.size);

  const uploaded = (await assetsOf(repo, release.id)).find((a) => a.name === name);
  if (!uploaded) throw new Error(`上传后没在远端找到附件 ${name}`);
  if (uploaded.size !== stat.size) {
    throw new Error(`上传后大小不一致: 本地 ${stat.size} 字节，远端 ${uploaded.size} 字节`);
  }
  console.log(`附件已上传: ${uploaded.name}  ${uploaded.size} 字节  state=${uploaded.state}  digest=${uploaded.digest || '-'}`);
  console.log('下载地址: ' + uploaded.browser_download_url);
}

function readNotes(flags) {
  if (!flags['notes-file']) return undefined;
  const p = flags['notes-file'];
  if (!fs.existsSync(p)) throw new Error('说明文件不存在: ' + p);
  return fs.readFileSync(p, 'utf8');
}

async function main() {
  const { positional, flags } = parseArgs(process.argv.slice(2));
  const [command, repoArg] = positional;
  if (!command || command === 'help') { console.log(USAGE); return; }

  if (!TOKEN) {
    fail(`没有找到 token。把 GITHUB_TOKEN=<token> 写进 ${path.join(SKILL_ROOT, '.env')}` +
      '（该文件已被技能仓库的 .gitignore 忽略），或设置环境变量 GITHUB_TOKEN。');
  }
  if (command === 'deploy-keys') {
    const repo = normalizeRepo(repoArg);
    const { json } = await api(`/repos/${repo}/keys`);
    if (!json.length) { console.log(`${repo} 还没有 deploy key`); return; }
    for (const k of json) {
      console.log(`#${k.id}  ${k.title}  read_only=${k.read_only}  创建=${k.created_at}  最近使用=${k.last_used_at || '(从未)'}`);
    }
    return;
  }

  if (command === 'add-deploy-key') {
    const repo = normalizeRepo(repoArg);
    if (!flags.key && !flags.file) throw new Error('缺 --key <公钥文本> 或 --file <公钥路径>');
    if (flags.file && !fs.existsSync(flags.file)) throw new Error('公钥文件不存在: ' + flags.file);
    const key = (flags.key || fs.readFileSync(flags.file, 'utf8')).trim();
    if (!/^(ssh-rsa|ssh-ed25519|ecdsa-sha2-|ssh-dss)\s/.test(key)) {
      throw new Error('这不像是公钥（应以 ssh-rsa / ssh-ed25519 / ecdsa-sha2- 开头）');
    }
    const title = flags.title || 'gitlab-push-mirror';
    const existing = (await api(`/repos/${repo}/keys`)).json.find((k) => String(k.key).trim() === key);
    if (existing) {
      console.log(`这把 deploy key 已经存在：#${existing.id}  ${existing.title}  read_only=${existing.read_only}`);
      if (existing.read_only) console.log('注意：它是只读的，镜像推送会失败——需要可写（read_only=false）');
      return;
    }
    if (flags['dry-run']) {
      console.log(`[dry-run] 会给 ${repo} 添加 deploy key：title=${title} read_only=${!!flags['read-only']}`);
      return;
    }
    const created = (await api(`/repos/${repo}/keys`, {
      method: 'POST',
      body: { title, key, read_only: !!flags['read-only'] },
    })).json;
    console.log(`已添加 deploy key：#${created.id}  ${created.title}  read_only=${created.read_only}`);
    if (created.read_only) console.log('注意：这是只读 key，推送镜像会失败');
    return;
  }

  if (command === 'whoami') {
    const { json, headers } = await api('/user');
    console.log('登录名: ' + json.login);
    console.log('名称: ' + (json.name || '-') + '  类型: ' + json.type);
    const scopes = headers.get('x-oauth-scopes');
    console.log('OAuth scopes: ' + (scopes ? scopes : '（响应无此头：fine-grained token 不报 scope，不代表权限不足）'));
    return;
  }

  if (command === 'repos') {
    const limit = Number(flags.limit || 30);
    const { json } = await api(`/user/repos?per_page=${limit}&sort=updated&affiliation=owner,collaborator,organization_member`);
    for (const r of json) {
      console.log(`${r.full_name}  ${r.private ? 'private' : 'public '}  更新=${r.updated_at}  ${r.size}KB  默认分支=${r.default_branch}`);
    }
    console.log(`共 ${json.length} 个（上限 ${limit}）`);
    return;
  }

  if (command === 'repo') {
    const repo = normalizeRepo(repoArg);
    const { json } = await api(`/repos/${repo}`);
    console.log(`${json.full_name}  ${json.private ? 'private' : 'public'}  ${json.visibility || ''}`);
    console.log(`描述: ${json.description || '(空)'}`);
    console.log(`主页: ${json.homepage || '(空)'}`);
    console.log(`topics: ${(json.topics || []).length ? json.topics.join(', ') : '(无)'}`);
    console.log(`默认分支: ${json.default_branch}  大小: ${json.size}KB  最近推送: ${json.pushed_at}`);
    console.log(`权限: ${JSON.stringify(json.permissions)}  （push=false 说明 token 只能读，建 release/传附件会 403）`);
    console.log(`issues=${json.has_issues}  actions=${json.has_actions !== false}  wiki=${json.has_wiki}`);
    return;
  }

  if (command === 'about') {
    const repo = normalizeRepo(repoArg);
    const patch = {};
    if (flags.description !== undefined) patch.description = flags.description;
    if (flags.homepage !== undefined) patch.homepage = flags.homepage;
    if (!Object.keys(patch).length && !flags.topics) {
      throw new Error('至少给一个 --description / --homepage / --topics');
    }
    if (Object.keys(patch).length) {
      if (flags['dry-run']) console.log(`[dry-run] PATCH /repos/${repo} ${JSON.stringify(patch)}`);
      else {
        const { json } = await api(`/repos/${repo}`, { method: 'PATCH', body: patch });
        console.log(`已更新 description=${JSON.stringify(json.description)} homepage=${JSON.stringify(json.homepage)}`);
      }
    }
    if (flags.topics) {
      // topics 是整体替换（PUT 语义），不接受中文与大写：GitHub 只允许小写字母、数字、连字符
      const names = String(flags.topics).split(',').map((s) => s.trim().toLowerCase()).filter(Boolean);
      const bad = names.filter((n) => !/^[a-z0-9][a-z0-9-]*$/.test(n));
      if (bad.length) throw new Error('topics 只能用小写字母/数字/连字符，非法: ' + bad.join(', '));
      if (flags['dry-run']) console.log(`[dry-run] PUT /repos/${repo}/topics ${JSON.stringify(names)}`);
      else {
        const { json } = await api(`/repos/${repo}/topics`, {
          method: 'PUT',
          body: { names },
          accept: 'application/vnd.github.mercy-preview+json',
        });
        console.log('topics 已更新: ' + json.names.join(', '));
      }
    }
    return;
  }

  if (command === 'rate') {
    const { json } = await api('/rate_limit');
    for (const [name, r] of Object.entries(json.resources)) {
      if (name === 'core' || name === 'search' || name === 'graphql') {
        console.log(`${name}: ${r.remaining}/${r.limit}  重置于 ${new Date(r.reset * 1000).toLocaleString()}`);
      }
    }
    return;
  }

  if (command === 'releases') {
    const repo = normalizeRepo(repoArg);
    const limit = Number(flags.limit || 20);
    const { json } = await api(`/repos/${repo}/releases?per_page=${limit}`);
    if (!json.length) { console.log(`${repo} 还没有 release`); return; }
    for (const r of json) {
      console.log(`${r.tag_name}  ${r.name || ''}  draft=${r.draft}  prerelease=${r.prerelease}  ${r.published_at || '(未发布)'}`);
      console.log('  ' + r.html_url);
      for (const a of r.assets) console.log(`  附件: ${a.name}  ${a.size} 字节  state=${a.state}  digest=${a.digest || '-'}`);
    }
    return;
  }

  if (command === 'release') {
    const repo = normalizeRepo(repoArg);
    const tag = flags.tag;
    if (!tag) throw new Error('缺少 --tag');
    let notes = readNotes(flags);
    let release = await releaseByTag(repo, tag);

    if (release) {
      console.log(`release 已存在，复用: ${release.html_url}`);
      if (flags['update-notes']) {
        if (notes === undefined) throw new Error('--update-notes 需要同时给 --notes-file');
        if (flags['dry-run']) console.log('[dry-run] 会覆盖 release 说明');
        else {
          release = (await api(`/repos/${repo}/releases/${release.id}`, {
            method: 'PATCH',
            body: { body: notes, ...(flags.name ? { name: flags.name } : {}) },
          })).json;
          console.log('release 说明已更新');
        }
      }
    } else {
      const body = {
        tag_name: tag,
        name: flags.name || tag,
        draft: !!flags.draft,
        prerelease: !!flags.prerelease,
      };
      if (notes !== undefined) body.body = notes;
      if (flags.target) body.target_commitish = flags.target;
      if (flags['dry-run']) {
        console.log('[dry-run] 会创建 release: ' + JSON.stringify({ ...body, body: body.body ? `<${body.body.length} 字符>` : '(空)' }));
      } else {
        release = (await api(`/repos/${repo}/releases`, { method: 'POST', body })).json;
        console.log('release 已创建: ' + release.html_url);
        console.log(release.html_url);
      }
    }

    for (const file of flags.asset) await ensureAsset(repo, release, file, undefined, flags);
    if (!flags.asset.length) console.log('（没有 --asset，只处理了 release 本身）');
    return;
  }

  if (command === 'upload') {
    const repo = normalizeRepo(repoArg);
    if (!flags.tag) throw new Error('缺少 --tag');
    if (!flags.asset.length) throw new Error('缺少 --asset');
    const release = await releaseByTag(repo, flags.tag);
    if (!release) throw new Error(`${repo} 没有 tag 为 ${flags.tag} 的 release`);
    for (const file of flags.asset) await ensureAsset(repo, release, file, flags.name, flags);
    return;
  }

  fail(`未知命令: ${command}\n\n${USAGE}`);
}

main().catch((e) => {
  // 网络类错误（TypeError: fetch failed）真正的原因在 e.cause，必须一起打出来
  const cause = e && e.cause ? `  [${e.cause.code || e.cause.message || e.cause}]` : '';
  console.error('错误: ' + (e && e.message ? e.message : String(e)) + cause);
  process.exitCode = 1;
});

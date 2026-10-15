#!/usr/bin/env node
/* 操作校内 GitLab（默认 https://git.ustc.edu.cn，API v4）。
 * token 来自本 skill 目录的 .env（GITLAB_USTC_TOKEN=...）或同名环境变量；只发给该实例。
 *
 * 公开项目的大部分读取（project / releases / tags / packages）不需要 token，匿名即可；
 * whoami 与所有写操作（release / upload）必须有 token。
 *
 * Release 附件的做法和 GitHub 不一样：GitLab 的 release 只能挂"链接"，文件要先用
 * Generic Packages 上传（PUT /projects/:id/packages/generic/:pkg/:ver/:file），
 * 再把该包地址作为 asset link 挂上去（direct_asset_path 决定 /-/releases/<tag>/downloads/<file> 这个短链）。
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import https from 'node:https';
import { envValue, SKILL_ROOT } from './env.mjs';

const TOKEN = envValue(['GITLAB_USTC_TOKEN', 'GITLAB_TOKEN']);
const BASE = (envValue(['GITLAB_USTC_URL']) || 'https://git.ustc.edu.cn').replace(/\/+$/, '');
const UA = 'github-account-skill/gitlab';

const USAGE = `用法（校内 GitLab，默认 ${BASE}）:
  node scripts/gitlab.mjs whoami                       # 账号 + token 权限范围（需 token）
  node scripts/gitlab.mjs keys                         # 已登记的 SSH 公钥
  node scripts/gitlab.mjs add-key --file ~/.ssh/id_rsa.pub [--title 名称]
  node scripts/gitlab.mjs projects [--search 关键词] [--mine] [--limit 30]
  node scripts/gitlab.mjs project <id|group/project>   # 公开项目可匿名
  node scripts/gitlab.mjs tags <id|group/project>
  node scripts/gitlab.mjs releases <id|group/project>
  node scripts/gitlab.mjs mirrors <id|group/project>        # 镜像状态（含 host_keys / last_error）
  node scripts/gitlab.mjs mirror-add <id|group/project> --url <远端> --user <用户名> --password <token|PAT>

  # 上传附件到 Generic Packages（不发 release，只传文件）
  node scripts/gitlab.mjs upload <id|group/project> --package my_diary --version 1.1.0 --asset 文件 [--name 远端名]

  # 建 release，并把附件传成包再挂成 release asset link
  node scripts/gitlab.mjs release <id|group/project> --tag 1.1.0 [--name 标题] [--notes-file 文件]
        [--ref main] [--package my_diary] [--asset 文件]... [--dry-run]`;

function fail(msg) {
  throw new Error(msg);
}

function parseArgs(argv) {
  const positional = [];
  const flags = { asset: [], 'asset-name': [] };
  const bools = new Set(['dry-run', 'mine']);
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (!a.startsWith('--')) { positional.push(a); continue; }
    const key = a.slice(2);
    if (bools.has(key)) { flags[key] = true; continue; }
    const val = argv[i + 1];
    if (val === undefined || val.startsWith('--')) throw new Error(`--${key} 需要一个值`);
    i += 1;
    if (key === 'asset' || key === 'asset-name') flags[key].push(val); else flags[key] = val;
  }
  return { positional, flags };
}

function needToken() {
  if (!TOKEN) {
    fail(`这个操作需要 token。把 GITLAB_USTC_TOKEN=<token> 写进 ${path.join(SKILL_ROOT, '.env')}`
      + '（该文件已被技能仓库的 .gitignore 忽略），或设置同名环境变量。');
  }
}

async function api(pathname, { method = 'GET', body, anonymous = false } = {}) {
  const headers = { 'User-Agent': UA, Accept: 'application/json' };
  if (!anonymous && TOKEN) headers['PRIVATE-TOKEN'] = TOKEN;
  const res = await fetch(BASE + '/api/v4' + pathname, {
    method,
    headers: { ...headers, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let json = null;
  try { json = text ? JSON.parse(text) : null; } catch { /* 非 JSON */ }
  if (!res.ok) {
    const msg = (json && (json.message || json.error)) || text.slice(0, 300) || '(无响应正文)';
    throw new Error(`HTTP ${res.status}: ${typeof msg === 'string' ? msg : JSON.stringify(msg)}`);
  }
  return json;
}

/* 大文件上传：与 github.mjs 同样的理由——不用 fetch（undici 的 body 超时有 300 秒上限，
 * 拿不到进度，失败只报 "fetch failed"），改用 https.request 流式发。 */
function uploadStream(urlString, file, size) {
  return new Promise((resolve, reject) => {
    const u = new URL(urlString);
    const req = https.request(
      {
        method: 'PUT',
        hostname: u.hostname,
        port: u.port || 443,
        path: u.pathname + u.search,
        headers: {
          'PRIVATE-TOKEN': TOKEN,
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
          else reject(new Error(`上传失败 HTTP ${res.statusCode}: ${text.slice(0, 300)}`));
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

function packageUrl(projectId, pkg, version, name) {
  return `${BASE}/api/v4/projects/${projectId}/packages/generic/${encodeURIComponent(pkg)}/${encodeURIComponent(version)}/${encodeURIComponent(name)}`;
}

async function resolveProject(idOrPath, { anonymous = false } = {}) {
  if (!idOrPath) throw new Error('缺少 <id|group/project>');
  const key = /^\d+$/.test(String(idOrPath)) ? String(idOrPath) : encodeURIComponent(String(idOrPath));
  return api(`/projects/${key}`, { anonymous });
}

async function doUpload(project, pkg, version, file, remoteName) {
  if (!fs.existsSync(file) || !fs.statSync(file).isFile()) throw new Error('附件不存在: ' + file);
  const size = fs.statSync(file).size;
  const name = remoteName || path.basename(file);
  const url = packageUrl(project.id, pkg, version, name);
  console.log(`上传 ${name}（${(size / 1024 / 1024).toFixed(1)} MB）→ 包 ${pkg}/${version}`);
  await uploadStream(url, file, size);
  console.log('上传完成，包地址: ' + url);
  return url;
}

async function main() {
  const { positional, flags } = parseArgs(process.argv.slice(2));
  const [command, target] = positional;
  if (!command || command === 'help') { console.log(USAGE); return; }
  console.log(`[${BASE}${TOKEN ? '' : ' · 未配置 token（匿名读取）'}]`);

  if (command === 'whoami') {
    needToken();
    try {
      const v = await api('/version');
      console.log(`实例版本: GitLab ${v.version} (${(v.revision || '').slice(0, 8)})  ${BASE}`);
    } catch (e) { console.log('实例版本: 读不到（' + e.message + '）'); }
    const user = await api('/user');
    console.log(`登录名: ${user.username}  名字: ${user.name || '-'}  id=${user.id}  ${user.state || ''}`);
    console.log('邮箱: ' + (user.email || '(未公开)'));
    console.log('是否管理员: ' + (user.is_admin === undefined ? '(未返回)' : user.is_admin));
    // token 自身的权限范围：GitLab 15.5+ 才有这个接口，没有就退化成提示
    try {
      const t = await api('/personal_access_tokens/self');
      console.log(`token: ${t.name}  scopes=[${(t.scopes || []).join(', ')}]  到期=${t.expires_at || '永不过期'}`);
      console.log(`token 有效: ${t.active}  最近使用: ${t.last_used_at || '(从未)'}`);
    } catch (e) {
      console.log('token 权限范围: 读不到（' + e.message + '）——该实例版本可能低于 15.5');
    }
    return;
  }

  if (command === 'keys') {
    needToken();
    const keys = await api('/user/keys');
    if (!keys.length) { console.log('这个账号还没有登记任何 SSH key'); return; }
    for (const k of keys) {
      console.log(`#${k.id}  ${k.title}  ${String(k.key).slice(0, 44)}…  创建=${k.created_at}  最近使用=${k.last_used_at || '(从未)'}`);
    }
    return;
  }

  if (command === 'add-key') {
    needToken();
    if (!flags.file) throw new Error('缺 --file <公钥路径>（不是私钥）');
    if (!fs.existsSync(flags.file)) throw new Error('公钥文件不存在: ' + flags.file);
    const key = fs.readFileSync(flags.file, 'utf8').trim();
    if (!/^(ssh-rsa|ssh-ed25519|ecdsa-sha2-|ssh-dss)\s/.test(key)) {
      throw new Error('这不像是公钥（应以 ssh-rsa / ssh-ed25519 / ecdsa-sha2- 开头）');
    }
    const title = flags.title || `${os.hostname()} (agent)`;
    const dup = (await api('/user/keys')).find((k) => String(k.key).trim() === key);
    if (dup) { console.log(`这把公钥已经登记过：#${dup.id}  ${dup.title}`); return; }
    const created = await api('/user/keys', { method: 'POST', body: { title, key } });
    console.log(`已添加公钥：#${created.id}  ${created.title}`);
    console.log(`指纹: ${created.fingerprint || ''}  ${created.fingerprint_sha256 || ''}`);
    return;
  }

  if (command === 'pipelines') {
    const p = await resolveProject(target);
    if (flags.cancel) {
      needToken();
      const r = await api(`/projects/${p.id}/pipelines/${flags.cancel}/cancel`, { method: 'POST' });
      console.log(`取消 #${r.id}：请求已接受（回读状态常仍是取消前的值，稍后再跑一次 pipelines 确认）`);
      return;
    }
    const list = await api(`/projects/${p.id}/pipelines?per_page=${Number(flags.limit || 10)}`);
    if (!list.length) { console.log(`${p.path_with_namespace} 没有 pipeline 记录`); return; }
    for (const x of list) console.log(`#${x.id}  ${x.status}  ${x.ref}  ${x.created_at}  ${x.web_url}`);
    const pending = list.filter((x) => ['pending', 'running', 'created'].includes(x.status));
    if (pending.length) console.log(`待处理 ${pending.length} 条：取消用 pipelines <项目> --cancel <id>`);
    return;
  }

  if (command === 'mirrors') {
    const p = await resolveProject(target);
    const list = await api(`/projects/${p.id}/remote_mirrors`);
    if (!list.length) { console.log(`${p.path_with_namespace} 还没有配置镜像`); return; }
    for (const m of list) {
      console.log(`#${m.id}  ${m.url}`);
      console.log(`  方向=${m.mirror_direction || 'push'}  auth=${m.auth_method}  enabled=${m.enabled}`
        + `  only_protected_branches=${m.only_protected_branches}  keep_divergent_refs=${m.keep_divergent_refs}`);
      console.log(`  状态=${m.update_status}  上次尝试=${m.last_update_at || '(无)'}  上次成功=${m.last_successful_update_at || '(无)'}`);
      if (m.last_error) console.log(`  错误: ${m.last_error}`);
      console.log(`  host_keys=${(m.host_keys || []).length} 个`);
    }
    console.log('提示: PUT /remote_mirrors/:id 不会触发更新，得向源仓库 push 一次（约 5 分钟节流）。');
    return;
  }

  if (command === 'mirror-add') {
    needToken();
    const p = await resolveProject(target);
    if (!flags.url) throw new Error('缺 --url <远端仓库地址>');
    if ((flags.auth || 'password') !== 'password') {
      throw new Error('API 只支持 auth_method=password（实测 ssh 会被拒：auth_method 不包含于列表中）；'
        + 'SSH 镜像只能在项目网页 设置→仓库→镜像仓库 上建，建完用 mirrors 查看。');
    }
    if (!flags.user || !flags.password) throw new Error('password 方式需要 --user 与 --password（GitHub 用用户名 + PAT）');
    const body = { url: flags.url, enabled: true, auth_method: 'password', user: flags.user, password: flags.password };
    if (flags['dry-run']) {
      console.log('[dry-run] POST /remote_mirrors ' + JSON.stringify({ ...body, password: '<已省略>' }));
      return;
    }
    const created = await api(`/projects/${p.id}/remote_mirrors`, { method: 'POST', body });
    console.log(`已建镜像 #${created.id}  ${created.url}  状态=${created.update_status}`);
    console.log('提醒: 这个凭据会存在 GitLab 服务器上，尽量用只对目标仓库可写的最小权限 token。');
    return;
  }

  if (command === 'projects') {
    const limit = Number(flags.limit || 30);
    const q = new URLSearchParams({ per_page: String(limit), order_by: 'last_activity_at' });
    if (flags.search) q.set('search', flags.search);
    if (flags.mine) { needToken(); q.set('membership', 'true'); }
    const list = await api(`/projects?${q}`);
    for (const p of list) {
      console.log(`${p.path_with_namespace}  id=${p.id}  ${p.visibility}  更新=${p.last_activity_at}  ${p.default_branch || '(空仓库)'}`);
      if (p.description) console.log('    ' + p.description.slice(0, 100));
    }
    console.log(`共 ${list.length} 个（上限 ${limit}）`);
    return;
  }

  if (command === 'project') {
    const p = await resolveProject(target);
    console.log(`${p.path_with_namespace}  id=${p.id}  ${p.visibility}  默认分支=${p.default_branch}`);
    console.log(`描述: ${p.description || '(空)'}`);
    console.log(`SSH:   ${p.ssh_url_to_repo}`);
    console.log(`HTTPS: ${p.http_url_to_repo}`);
    console.log(`网页:  ${p.web_url}`);
    if (p.permissions) {
      const acc = p.permissions.project_access || p.permissions.group_access;
      console.log(`我的权限: ${acc ? (acc.access_level + ' (' + (acc.access_level_description || '') + ')') : JSON.stringify(p.permissions)}`
        + '  —— 推代码/建 release 至少需要 Developer(30)');
    }
    try {
      const s = await api(`/projects/${p.id}?statistics=true`);
      if (s.statistics) {
        console.log(`仓库大小: ${(s.statistics.repository_size / 1024 / 1024).toFixed(2)} MB  提交数: ${s.statistics.commit_count}`
          + `  占用: ${(s.statistics.storage_size / 1024 / 1024).toFixed(2)} MB`);
      }
    } catch (e) { console.log('统计: 读不到（' + e.message + '）'); }
    try {
      const branches = await api(`/projects/${p.id}/repository/branches`);
      console.log(`分支: ${branches.length ? branches.map((b) => `${b.name}@${b.commit.short_id}`).join(', ') : '(空仓库)'}`);
    } catch (e) { console.log('分支: 读不到（' + e.message + '）'); }
    return;
  }

  if (command === 'tags') {
    const p = await resolveProject(target, { anonymous: true });
    const tags = await api(`/projects/${p.id}/repository/tags`, { anonymous: true });
    if (!tags.length) { console.log(`${p.path_with_namespace} 还没有 tag`); return; }
    for (const t of tags) console.log(`${t.name}  ${t.commit ? t.commit.short_id : ''}  ${t.created_at || ''}`);
    return;
  }

  if (command === 'releases') {
    const p = await resolveProject(target, { anonymous: true });
    const rels = await api(`/projects/${p.id}/releases`, { anonymous: true });
    if (!rels.length) { console.log(`${p.path_with_namespace} 还没有 release`); return; }
    for (const r of rels) {
      console.log(`${r.tag_name}  ${r.name || ''}  ${r.released_at || ''}  ${r.upcoming_release ? '(upcoming)' : ''}`);
      console.log('  ' + `${BASE}/${p.path_with_namespace}/-/releases/${r.tag_name}`);
      for (const a of r.assets?.links || []) console.log(`  附件: ${a.name}  → ${a.direct_asset_url || a.url}`);
    }
    return;
  }

  if (command === 'upload') {
    needToken();
    const p = await resolveProject(target);
    const pkg = flags.package;
    const version = flags.version || flags.tag;
    if (!pkg) throw new Error('缺 --package');
    if (!version) throw new Error('缺 --version');
    if (!flags.asset.length) throw new Error('缺 --asset');
    for (const file of flags.asset) await doUpload(p, pkg, version, file, flags.name);
    return;
  }

  if (command === 'release') {
    needToken();
    const p = await resolveProject(target);
    const tag = flags.tag;
    if (!tag) throw new Error('缺 --tag');
    const pkg = flags.package || p.path;
    const notes = flags['notes-file'] ? fs.readFileSync(flags['notes-file'], 'utf8') : undefined;
    if (flags['notes-file'] && !fs.existsSync(flags['notes-file'])) throw new Error('说明文件不存在: ' + flags['notes-file']);

    const exists = (await api(`/projects/${p.id}/releases/${encodeURIComponent(tag)}`, { anonymous: true }).catch(() => null));
    if (exists) {
      console.log(`release ${tag} 已存在: ${BASE}/${p.path_with_namespace}/-/releases/${tag}`);
      if (notes !== undefined) {
        if (flags['dry-run']) console.log('[dry-run] 会 PUT 覆盖 release 说明');
        else {
          await api(`/projects/${p.id}/releases/${encodeURIComponent(tag)}`, { method: 'PUT', body: { description: notes, ...(flags.name ? { name: flags.name } : {}) } });
          console.log('release 说明已更新');
        }
      }
    } else {
      const body = { tag_name: tag, name: flags.name || tag };
      if (notes !== undefined) body.description = notes;
      if (flags.ref) body.ref = flags.ref;
      if (flags['dry-run']) console.log('[dry-run] 会创建 release: ' + JSON.stringify({ ...body, description: body.description ? `<${body.description.length} 字符>` : '(空)' }));
      else {
        await api(`/projects/${p.id}/releases`, { method: 'POST', body });
        console.log(`release 已创建: ${BASE}/${p.path_with_namespace}/-/releases/${tag}`);
      }
    }

    if (!flags.asset.length) { console.log('（没有 --asset，只处理了 release 本身）'); return; }
    for (let i = 0; i < flags.asset.length; i += 1) {
      const file = flags.asset[i];
      const name = flags['asset-name'][i] || path.basename(file);
      if (flags['dry-run']) {
        console.log(`[dry-run] 会传 ${file} 到 generic 包 ${pkg}/${tag}/${name}，再挂成 asset link`);
        continue;
      }
      const url = await doUpload(p, pkg, tag, file, name);
      const link = await api(`/projects/${p.id}/releases/${encodeURIComponent(tag)}/assets/links`, {
        method: 'POST',
        body: { name, url, direct_asset_path: `/${name}`, link_type: 'package' },
      });
      console.log(`附件已挂到 release: ${link.name} → ${link.direct_asset_url}`);
    }
    return;
  }

  fail(`未知命令: ${command}\n\n${USAGE}`);
}

main().catch((e) => {
  const cause = e && e.cause ? `  [${e.cause.code || e.cause.message || e.cause}]` : '';
  console.error('错误: ' + (e && e.message ? e.message : String(e)) + cause);
  process.exitCode = 1;
});

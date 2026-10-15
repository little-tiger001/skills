---
name: github-account
description: 用 REST API 操作本机用户的代码托管账户：GitHub（校验 token 与权限、列出仓库、创建/查看 release、上传 release 附件如安装包）与校内 GitLab（git.ustc.edu.cn：项目/分支/tag/release 查询、Generic Packages 上传附件、建 release）。用户提到 GitHub、校内 GitLab、发布 release、上传安装包、仓库列表、token 权限、没有 gh CLI 想走 API 时使用。
---

# GitHub / 校内 GitLab 账户操作

两个平台各一个脚本，都只用 Node（本机 v24）内置模块，无第三方依赖：
`scripts/github.mjs`（GitHub REST API；本机**没有装 `gh` CLI**）、
`scripts/gitlab.mjs`（`git.ustc.edu.cn` 的 API v4）。`.env` 与共享读取模块 `scripts/env.mjs` 由两者共用。

## 凭据

- token 在本 skill 目录的 `.env`：GitHub 用 `GITHUB_TOKEN`，校内 GitLab 用 `GITLAB_USTC_TOKEN`（配 `GITLAB_USTC_URL`，默认 `https://git.ustc.edu.cn`）。脚本自己读，也可退回同名环境变量。
- 共享技能仓库（`~/.agents/skills`）的 `.gitignore` 已忽略 `.env`。**绝不要**把 token 复制进任何仓库、SKILL.md、commit、issue，也不要在回复里回显。
- 各脚本只与自己的平台通信：`github.mjs` → `api.github.com` / `uploads.github.com`；`gitlab.mjs` → `GITLAB_USTC_URL` 指向的实例。不把 token 发给别处。
- 权限：GitHub fine-grained token 需勾中目标仓库并给 **Contents: Read and write**（建 release 与传附件都要它），classic PAT 需要 `repo`；校内 GitLab token 至少要 `api`（或 `read_api` + `write_repository`）。建议都设到期时间。
- 撤销入口：GitHub classic <https://github.com/settings/tokens>、fine-grained <https://github.com/settings/personal-access-tokens>；校内 GitLab → 实例网页 → Preferences → Access tokens。

## 用法

```bash
cd ~/.agents/skills/github-account

node scripts/github.mjs whoami
node scripts/github.mjs repos [--limit 50]
node scripts/github.mjs repo <owner/repo>      # 含 permissions，用来判断 token 是否可写
node scripts/github.mjs about <owner/repo> --description "…" --topics a,b,c
node scripts/github.mjs rate                  # 剩余速率额度
node scripts/github.mjs deploy-keys <owner/repo>
node scripts/github.mjs add-deploy-key <owner/repo> --key "ssh-ed25519 …" [--title 名称] [--read-only]
node scripts/github.mjs releases <owner/repo> [--limit 20]

# 建 release 并上传附件（--asset 可重复）
node scripts/github.mjs release <owner/repo> --tag v1.0.0 --name "我的日记 v1.0.0" \
  --notes-file release/RELEASE_NOTES.md \
  --asset "release/我的日记-安装包-1.0.0.exe"
node scripts/github.mjs release <owner/repo> --tag v1.0.0 --asset x.exe --dry-run

# 往已有 release 追加/替换附件
node scripts/github.mjs upload <owner/repo> --tag v1.0.0 --asset x.exe [--name 远端名] [--replace-asset]
```

- `<owner/repo>` 也接受 `https://github.com/owner/repo` 或 `git@github.com:owner/repo.git`。
- 同名 release 已存在时默认**复用且不改说明**；要覆盖说明加 `--update-notes`。
- `--target <分支>` 指定 tag 的落点（默认仓库默认分支）；`--draft` / `--prerelease` 可用。
- 每个附件上传后回读远端大小与本地比对，并打印 `digest`。

## 用法（校内 GitLab）

```bash
cd ~/.agents/skills/github-account

node scripts/gitlab.mjs whoami                          # 账号 + token 实际 scopes（需 token）
node scripts/gitlab.mjs keys                            # 已登记的 SSH 公钥
node scripts/gitlab.mjs add-key --file ~/.ssh/id_rsa.pub --title "Windows Tiger"
node scripts/gitlab.mjs projects [--search 关键词] [--mine]
node scripts/gitlab.mjs project <id|group/project>      # 公开项目可匿名
node scripts/gitlab.mjs tags|releases <id|group/project>

# 传附件（先传成 Generic Package）
node scripts/gitlab.mjs upload <id|group/project> --package my_diary --version 1.1.0 --asset 文件

# 建 release 并自动"传包 + 挂 asset link"（--asset-name 控制远端文件名，两平台可保持一致）
node scripts/gitlab.mjs release <id|group/project> --tag 1.1.0 --ref main \
  --notes-file release/RELEASE_NOTES-1.1.0.md --package my_diary \
  --asset "release/我的日记-安装包-1.1.0.exe" --asset-name my_diary-1.1.0.exe
```

- `<id|group/project>` 用 `9152` 或 `LittleTiger/my_diary` 都行（数字 id 与完整路径都能解析）。
- 读取类命令（project / tags / releases / packages）对公开项目**不需要 token**；`whoami` 与所有写操作需要。
- `--dry-run` 只打印将要执行的调用。

## 事实与坑（2026-10-15 实测）

### 路由（本机环境，两个平台都适用）

- 本机设了 `HTTP_PROXY/HTTPS_PROXY=http://127.0.0.1:10808` 且 `NODE_USE_ENV_PROXY=1`，于是脚本里用 `fetch` 的 **API 调用走本地代理**；而用 `https.request` 的**附件上传不认这两个变量、始终直连**（混合路由）。
- 代理抖动时 API 会以 `fetch failed [UND_ERR_CONNECT_TIMEOUT]` 结束——外层消息看不出来，真因在 `e.cause`（脚本已把它打出来）。
- 想强制直连：`$env:NODE_USE_ENV_PROXY='0'`（实测 GitHub API 直连 0.8s vs 走代理 1.9s）。想强制走代理给上传用，得自己实现 CONNECT 隧道，脚本目前没做。
- 校园网到 `git.ustc.edu.cn` 极快（0.2s），且 `NO_PROXY` 里已排除 `.ustc.edu.cn`，所以校内 API 调用本来就不走代理。

### GitHub

- 附件必须传到 `uploads.github.com`，且 `Content-Type: application/octet-stream`；发到 `api.github.com` 会 404/415。
- **大文件用 `https.request` 流式发，不要用 fetch**：undici 的 body 超时是 300 秒、拿不到进度，几十 MB 的安装包在慢线路上会以 `TypeError: fetch failed` 结束，真正原因藏在 `e.cause`（曾实测踩到）。脚本里已改成流式 + 每 10 MB 报进度，并且不设 socket 超时。
- 中文附件名用 `?name=<percent-encoded UTF-8>`；`我的日记-安装包-1.0.0.exe` 实测可用。
- 建 release：`POST /repos/{owner}/{repo}/releases`；tag 不存在时 GitHub 会按 `target_commitish` 创建。
- fine-grained token 的响应里**没有** `x-oauth-scopes` 头，`whoami` 因此只报登录名，不代表权限不足。
- 私有仓库无权限时 GitHub 返回 **404 而不是 403**，别据此判断仓库不存在。
- 仓库 topics 只允许小写字母/数字/连字符（中文会被 422 拒绝）；`about --topics` 是**整体替换**而非追加，所以要一次给全。`description` 与 `homepage` 走 `PATCH /repos/{owner}/{repo}`，topics 走单独的 `PUT /repos/{owner}/{repo}/topics`（需 mercy-preview Accept 头）。

### 校内 GitLab（git.ustc.edu.cn）

- 实例是 `https://git.ustc.edu.cn`，API 在 `/api/v4`；认证头是 `PRIVATE-TOKEN`（不是 Bearer）。校园网内延迟约 **0.2s**（TLS 完成 0.17s），对比 GitHub 走本地代理约 6.3s——**推拉和上传都快得多**。
- 公开项目的 `project` / `releases` / `tags` / `packages` 可以**匿名读取**（实测 `LittleTiger/my_diary` id=9152）；`/version` 与 `/metadata` 需要 token，所以实例版本只能等 token 到位再读。
- token 自身的权限范围用 `GET /personal_access_tokens/self` 读（GitLab **15.5+** 才有；脚本在该接口不存在时降级为提示，不报错）。
- **Release 附件与 GitHub 不同**：GitLab 的 release 只能挂"链接"，文件要先 `PUT /projects/:id/packages/generic/:pkg/:ver/:file` 传成 Generic Package，再用 `POST /projects/:id/releases/:tag/assets/links` 挂上去（`direct_asset_path` 决定 `/-/releases/<tag>/downloads/<file>` 这个短链）。脚本的 `release` 命令把这两步串起来了。
- 上传同样走 `https.request` 流式（理由和 GitHub 一样），并复用每 10 MB 的进度输出。
- **实测（2026-10-15，GitLab 19.4.2）**：`whoami` 能读回 token scopes 与到期时间；Generic Package `PUT` 成功；`POST .../releases` 与 `POST .../assets/links` 成功；`PUT .../releases/:tag` 覆盖说明成功，远端说明与本地文件**逐字符一致**（1859 字符）；包文件可用 `package_files` 里的 `file_sha256` 校验，也可匿名下载回来自己算 SHA256。校园网下载 **16.8 MB/s**（同一份 63 MB 包，GitHub 上传只有 33 KB/s）。
- **从 GitHub 导入的保真度（实测）**：分支与 tag 都会带过来且**保留原始 SHA**（所以本地 `git push` 到 GitLab 是 no-op，不会产生历史分歧）；release 也带（标题/日期/说明）但**不含附件**；`.github/` 与 CI 配置不导入。
- **推 ref 可能自动产生一条 pipeline 记录**，即使仓库里没有 `.gitlab-ci.yml`：实测 `my_diary` 项目推分支与推 tag 各留下一条（状态 `pending`，等 runner），而 `skills` 项目推 tag 一条都没产生——机制没弄清，**推完顺手跑一次 `pipelines <项目>`，有 pending 就 `--cancel <id>`**（取消后状态变 `canceled`）。

### 镜像仓库（GitLab → GitHub，实测 2026-10-15）

- **API 只能建「HTTPS + 密码」镜像**：`POST /projects/:id/remote_mirrors` 带 `{url, enabled, auth_method:'password', user, password}`（实测 201）。`auth_method:'ssh'` 在 POST 与 PUT 上都被拒（`auth_method 不包含于列表中`），**SSH 镜像只能在网页上建**。
- 网页建 SSH 推送镜像的要点：URL `ssh://git@github.com/<owner>/<repo>.git`、方向=推送、验证方式=SSH 公钥、用户名=`git`；先点**「检测主机密钥」**（`GET /remote_mirrors` 里 `host_keys` 有值才算成功，实测拿到 GitHub 三把主机密钥）；「保留分叉的 refs」不勾 = 源端强制覆盖目标端，「仅镜像受保护的分支」不勾才连 tag 一起同步。
- 建完把页面上生成的公钥挂到目标仓库当**可写** deploy key：`node scripts/github.mjs add-deploy-key <owner/repo> --file pub --title "GitLab push mirror"`（`read_only` 必须为 false，否则推送被拒）。
- **`PUT /projects/:id/remote_mirrors/:id` 不触发更新**（实测返回 200 后 `update_status` 仍是 `none`）。真正的触发是**向源仓库 push 一次**，而且是**节流**的：实测推 tag 后约 10–25 秒完成，但实测一次正常提交的端到端延迟是 **约 3 分 11 秒**（提交 21:44:16 → 镜像成功 21:47:27），符合文档里「最多每 5 分钟更新一次」。**看到目标仓库没立刻变不要以为坏了**，等几分钟再查 `mirrors`：`状态=finished` 且 `上次成功` 有时间戳、`last_error` 为空，再去目标端 `ls-remote` 核对 ref。
- **验证不能只看状态**：一定要去目标端 `git ls-remote` 核对那个 ref 真的到了（实测 tag 出现在 GitHub 上）。
- **推送镜像不会删除 ref**：源端删掉的分支/tag，目标端会留着，必须两边各删一次。`keep_divergent_refs:false` 下源端会强推覆盖目标端，所以**启用镜像后不要再直接往目标仓库推**。
- API 读不到镜像的 SSH 公钥（响应里没有 `public_key` 字段），只能从网页复制。

## 排查顺序

### GitHub

1. `401` → token 缺失/过期/被撤销；`403` → 权限不足或触发了速率限制（看响应里的 `message`）。
2. `404` → 私有仓库没被 token 授权（换 token 勾选），或仓库名拼错。
3. 附件 `415` → `Content-Type` 不对；`422` → 同名附件已存在（加 `--replace-asset`）或 tag 已被别的 release 占用。
4. 建 release `422` → `--target` 分支名不存在，或该 tag 已关联另一个 release。
5. 上传中途失败且远端留下半个附件：`node scripts/github.mjs releases <repo>` 看 state，再 `--replace-asset` 重传。

### 校内 GitLab

1. `401` → 没带 token 或 token 被撤销；`403` → token 角色不够（项目里至少 Developer，scope 要有 `api` 或 `write_repository`）。
2. `404` → 项目路径写错，或私有项目没授权（GitLab 对无权限也是 404）。
3. 建 release `400 tag_name is missing` / tag 冲突 → 补 `--ref`，或该 tag 已存在（脚本会改为复用并可选覆盖说明）。
4. 附件挂不上 → 先确认 Generic Package 那步真的成功了（`packages` 列表里能看到），再挂 link；只挂 link 而没有包会得到一个 404 的下载地址。
5. 实例版本低于 15.5 → `whoami` 读不到 token scopes，这不是错误，只是拿不到权限清单。

---
name: wps-agent-api
description: 用 WPS AI 助理身份密钥（AGENT_API_KEY）调用 WPS 开放平台 v7 API，读取或总结金山文档（kdocs）分享链接、查当前用户/日历/日程/会话/群组/邮箱、直连任意 v7 接口。用户提到 WPS 云文档、金山文档、kdocs、分享链接 /l/、AI 助理身份、AGENT_API_KEY、WPS 日程或 WPS 会话时使用。
---

# WPS Agent API

凭 AI 助理身份密钥换取 AccessToken，再调 WPS 开放平台 v7 接口。不需要 WPS 365 CLI，不需要企业管理员审批。

## 配置

密钥放在本 skill 目录的 `.env`：`AGENT_API_KEY=apik:<sk_id>.<secret_key>`。
该文件已被 `.gitignore` 覆盖，不会进仓库。读取优先级：`.env` > 进程环境变量 > 用户级环境变量。
密钥只在创建时显示一次，丢失后在助理身份页面「重置」获取新的。

首次使用前，如果 `.env` 里是空的，**停下来**，让用户自己把密钥写进本 skill 目录的 `.env`（或设用户级环境变量 `AGENT_API_KEY`）。不要索要密钥、不要让它出现在对话里。

## 认证链路

1. `POST https://account.wps.cn/api/authorization/agent/v1/token`，body `{"grant_type":"api_key","api_key":"<密钥>"}`
2. 校验 `result == "ok"`，取 `data.access_token`（JWT，`data.expires_in` 秒有效，实测 43200 = 12h）
3. 业务请求带 `Authorization: Bearer <access_token>`，打到 `https://openapi.wps.cn/v7/...`

token 里的 `scope` 是实际授权清单（实测 203 项），`deputor_id` 是被代表的用户 id，`actor_type=agent`。

## 用法

```
python <SKILL_DIR>/scripts/wps_agent.py token            # 验证密钥
python <SKILL_DIR>/scripts/wps_agent.py me               # 当前用户
python <SKILL_DIR>/scripts/wps_agent.py drives           # 驱动盘列表
python <SKILL_DIR>/scripts/wps_agent.py ls --drive <id> [--parent 0] [--recursive]
python <SKILL_DIR>/scripts/wps_agent.py calendars        # 日历列表
python <SKILL_DIR>/scripts/wps_agent.py agenda           # 日程列表（默认主日历）
python <SKILL_DIR>/scripts/wps_agent.py chats            # 会话列表
python <SKILL_DIR>/scripts/wps_agent.py groups           # 群组列表
python <SKILL_DIR>/scripts/wps_agent.py mailboxes        # 邮箱列表
python <SKILL_DIR>/scripts/wps_agent.py read --url "https://365.kdocs.cn/l/<link_id>"
python <SKILL_DIR>/scripts/wps_agent.py meta --link-id <link_id>
python <SKILL_DIR>/scripts/wps_agent.py api --method GET --path /v7/users/current
```

查询类命令支持 `--format json|text`（text 为一行一条）与 `--page-size` / `--page-token`。
`agenda` 可加 `--calendar <id>`。`read` 支持 `--format md|txt|json`、`--output <文件>`。
`token` 默认只打印长度与有效期；确需原文加 `--print-token`。

## 读分享文档的固定三步

1. 从链接 `/l/<link_id>` 取 link_id
2. `GET /v7/links/{link_id}/meta` → `data.drive_id`、`data.file_id`
3. `GET /v7/drives/{drive_id}/files/{file_id}/content?format=markdown` → `data.markdown`

第 3 步若 `openapi.wps.cn` 返回 4xx，回退 `https://api.wps.cn` 重试——脚本内建的正常路径，`[WARN] ... fallback to` 不代表失败，不要中断。

## 删除与恢复

```
POST /v7/drives/{drive_id}/files/{file_id}/delete   # 删除（无请求体、无查询参数）
GET  /v7/deleted_files?page_size=10                 # 回收站
```

权限要求 `kso.file.readwrite`（用户授权即可，实测通过）。**删除是软删，进回收站**，可用 `recycle` 命令确认，用户在 WPS 网页「回收站」恢复。

实测注意：对**不存在或已删**的 file_id 调用 delete，返回的是 `400 请求参数不支持 / 400000004`，**不是**「文件不存在」——不要把这个码误判成「接口不可用」。判断某文件是否真的删掉了，唯一可靠办法是重新 `ls` 比对 `file_id`。

命令：`rm --drive <id> --file <id1,id2>`（**默认 dry-run，必须加 `--yes` 才真删**）、`recycle`。

## 调用约定

- **查询参数一律 snake_case**：`page_size`、`page_token`。传 `PageSize` 会报 `validate fail {"PageSize":"min(1)"}`，别被这个报错误导。
- 网关对**不存在的路由**返回 `404 Route Not Found / 404000001`；对**存在但参数不对**返回 `400 请求参数不支持 / 400000004`。后者说明路径是对的，只需换参数。
- 响应里集合有 `items` 和 `Items` 两种拼写，两种都要读。

## 助理身份调不通的接口

以下接口存在，但只接受**应用身份**，用助理身份会返回
`403 this API does not support user authorization, required app scopes: [...]`：

| 接口 | 用途 |
|---|---|
| `POST /v7/messages/batch_create` | **发 IM 消息** |
| `GET /v7/users` | 通讯录用户列表 |
| `GET /v7/user_mailboxes` `GET /v7/public_mailboxes` | 邮箱/公共邮箱列表 |
| `GET /v7/mail_contacts` | 邮件联系人 |

**发消息必须走开放平台应用（即已删除的 CLI 那条路，需企业管理员审批）**，助理身份密钥做不到——不要浪费时间重试。

## 查阅官方接口文档（关键技巧）

文档站有两套域名，**只有 `open.wps.cn` 那套能直接抓**：

- 页面：`https://open.wps.cn/documents/<path>`（SSR 出正文，如 `/app-integration-dev/wps365/server/yundoc/file/get-file-list`）
- **同一页的原始 Markdown**：`https://open-docs.wpscdn.cn/docs-md/zh/<path>.md`

即把页面 URL 的 `/documents/` 换成 `https://open-docs.wpscdn.cn/docs-md/zh/` 再加 `.md` 即可。用它可以免登录拿到任意接口的 **请求地址、路径参数、查询参数、权限要求**——猜参数前先来这里查。

注意 `365.kdocs.cn/3rd/open/documents/...` 是另一套 SPA：深链会报「文档不存在」，抓不到内容。

云文档业务域的路由前缀是 `yundoc`（不是 `drive`）：`yundoc/file/*`、`yundoc/drive/*`、`yundoc/file-link/*`、`yundoc/file-transfer/*`。

## 云文档浏览：可以完整枚举（已实测跑通）

两步，缺一不可：

```
GET /v7/drives?page_size=50&allotee_type=user        # 盘列表，allotee_type 必填
GET /v7/drives/{drive_id}/files/{parent_id}/children?page_size=500
```

- **`allotee_type` 是 `/v7/drives` 的必填参数**，漏了只报 `400 请求参数不支持`，不会提示缺哪个参数。实测只接受 `user`（`group` 报 400，`app` 报 `403 不支持的账号类型`）。
- `allotee_type=user` = 个人盘（「我的云文档」「我的企业文档」「自动备份」这类）；`group` = 团队盘即文档库。
- 列目录：`parent_id` 根目录传 `0`；`page_size` 必填（公网上限 500）；翻页用 `next_page_token`。
- 实测规模：两个个人盘递归下来 1514 文件 / 105 目录 / 13.2 GB，无权限报错。

命令：`drives [--allotee-type user]`、`ls --drive <id> [--parent 0] [--recursive]`。

### 排查记录（别再走弯路）

- `/v7/doclibs?page_size=10` 可用（`kso.doclib.read`），返回的是**文档库/团队文档**列表，与个人盘无关；实测为空。
- `GET /v7/airpage/documents` → `403 unable to read user permission`。
- **读邮件正文**：没找到消息列表路由；`GET /v7/mailboxes` 通但返回空 `items`。
- `GET /v7/files/search`：路由存在，穷举 49 个参数名全部 `400 请求参数不支持`，参数名仍未破解。
- 曾经把 `403 无权限` 误判成「数据权限未配」——**是错的**。真实原因是 drive_id 猜错了；拿到正确 drive_id 后一切正常。**不要因为一次 403 就断定缺权限，先确认 id 从 `drives` 接口查出来。**


## 文档入口

- API 能力地图：<https://365.kdocs.cn/3rd/open/documents/>（分类需站内点击展开）
- 在线调试器：<https://365.kdocs.cn/3rd/open/api-explorer/>（需登录）
- 报错对照：`InvalidApiKey` → 密钥失效让用户重置；`notCompanyMember` → Agent 未加入企业；`403 无权限` → 数据权限未配；正文长度 0 → 查文档权限。

## 约束

- 任何输出、日志、文件里都不得出现完整密钥；最多报长度或 `apik:` 前缀。
- 这把密钥代表用户本人且近乎全量读写（含邮件、消息、文件权限），属于高危凭证，不要写进仓库、云盘或对话。

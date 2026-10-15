---
name: ustc-cloud
description: 操作中国科大云盘（pan.ustc.edu.cn，Seafile 定制版）：用 WebDAV 列出/下载/上传/删除云端文件，编写 seafile-ignore.txt 同步忽略规则，并排查同步、冲突、解除同步、只读等问题。用户提到科大云盘、pan.ustc.edu.cn、云盘同步/忽略、seafile-ignore、WebDAV 挂载云盘时使用。
---

# 科大云盘操作

本机客户端是「科大云盘」（Seafile 9.0.12 定制版），服务端是 Seafile。

## 凭据

- WebDAV 的地址与账号密码在本 skill 目录的 `.env`（`USTC_CLOUD_WEBDAV_URL` / `USTC_CLOUD_USERNAME` / `USTC_CLOUD_PASSWORD`），用前先读。
- 用户名用**带 `@auth.local` 后缀**的形式（如 `2202315921@auth.local`）——2026-10-14 实测这样才通，别自行去掉后缀。
- 该目录属于共享技能仓库，`.gitignore` 已忽略 `.env`。**绝不要**把 `.env` 复制或移动进被同步的资料库（如 `C:\Users\zhang\科大云盘\大四上`），否则密码会被上传到云端，云盘还有版本历史。
- 不要把密码写进 SKILL.md，也不要在回复里回显密码。

## 服务事实（2026-10-14 实测）

| 项 | 值 |
|---|---|
| 网页端 | <https://pan.ustc.edu.cn> |
| WebDAV 端点 | `https://pan.ustc.edu.cn/seafile/seafdav/`（`PROPFIND` 返回 401 + `WWW-Authenticate: Basic realm="Seafile Authentication"`；用假凭据返回 401 `Access not authorized`，说明走 Basic 认证） |
| 访问验证 | 2026-10-14 用本 skill 的 `.env` 凭据实测：`PROPFIND seafdav/` → **207**，列出 6 个资料库（笔记 / 大三上 / 大三下 / zotero / 大四上 / Backup）；`seafdav/大四上/` → **207**，7 个目录 + `学期计划.md` + 已上传的 `seafile-ignore.txt`（1317 B） |
| API token | **不可用**。该部署没有用户自助获取的 API token：`POST /seafile/api2/auth-token/` 只认账号密码（用不存在的用户名探测返回 400 `Unable to login with provided credentials.`）；客户端 `repo.db` 里存的 40 位 token 是同步协议专用，拿来调 API 一律 401。要程序化操作走 WebDAV。 |
| 桌面客户端 | `C:\Program Files\科大云盘\bin\seafile-applet.exe` |
| 客户端配置 / 数据 | `C:\Users\zhang\ustc_ccnet`（日志在 `logs\`） / `C:\Users\zhang\科大云盘\seafile-data`（`repo.db` 是只读可查的 SQLite） |

## WebDAV 操作

- 顶层列出的就是各资料库（实测：笔记 / 大三上 / 大三下 / zotero / 大四上 / Backup），库内路径接在资料库名之后：`<资料库名>/<子路径>`。
- 路径一律用 `/`；含中文或空格的路径要 URL 编码。写操作前先 `PROPFIND` 确认路径存在。

```bash
set -a; . ./.env; set +a
BASE="$USTC_CLOUD_WEBDAV_URL"

# 列出资料库
curl -u "$USTC_CLOUD_USERNAME:$USTC_CLOUD_PASSWORD" -X PROPFIND -H "Depth: 1" "$BASE"
# 列出库内目录
curl -u "$USTC_CLOUD_USERNAME:$USTC_CLOUD_PASSWORD" -X PROPFIND -H "Depth: 1" "$BASE/大四上/"
# 下载 / 上传 / 删除 / 建目录
curl -u "$USTC_CLOUD_USERNAME:$USTC_CLOUD_PASSWORD" -o out.bin "$BASE/大四上/学期计划.md"
curl -u "$USTC_CLOUD_USERNAME:$USTC_CLOUD_PASSWORD" -T ./local.txt "$BASE/大四上/local.txt"
curl -u "$USTC_CLOUD_USERNAME:$USTC_CLOUD_PASSWORD" -X DELETE "$BASE/大四上/local.txt"
curl -u "$USTC_CLOUD_USERNAME:$USTC_CLOUD_PASSWORD" -X MKCOL "$BASE/大四上/新目录/"
```

Windows 映射盘符（需启动 `WebClient` 服务）：`net use Z: https://pan.ustc.edu.cn/seafile/seafdav/ /user:<用户名> *`。自带重定向器对中文名、大量小文件表现一般，批量操作用 curl/脚本更稳。

## 同步忽略规则 seafile-ignore.txt

- 放**资料库根目录**（如 `C:\Users\zhang\科大云盘\大四上\seafile-ignore.txt`），放子目录无效；客户端每次提交前重新读取，改完不用重启。
- 每行一个 pattern：`#` 注释、空行忽略；`*` 可跨 `/` 递归匹配，`?` 匹配一个字符；以 `/` 结尾只匹配目录。
- 实现依据：客户端把每行拼成「资料库绝对路径 + `/` + pattern」再整体匹配（`daemon/repo-mgr.c` 的 `seafile_load_ignore_files` / `seaf_repo_check_ignore_file`，GLib `g_pattern_match_string`）。所以 `*.zip` 能覆盖任意深度的 zip，而 `.mineru/` 只能匹配库根下的同名目录——要任意深度得写 `*/.mineru/`。
- 只影响客户端，且只对**尚未同步**的内容生效：已上传内容不会被自动删除，只是本机后续改动不再回传。
- ⚠️ **反向不成立**：`seaf_repo_fetch_and_checkout()` 虽加载了 ignore 列表却从未使用，判断本地是否跳过删除的 `should_ignore_on_checkout()`（`lib/utils.c`）只看 Windows 非法路径。**在云端删除一个"本地已忽略但仍在索引里"的文件，客户端会把本地副本一起删掉。** 要清云端腾空间，先把文件复制到资料库之外。

## 排查顺序

1. 同步卡住/失败：`C:\Users\zhang\ustc_ccnet\logs\seafile.log` 搜 `Repo '<名>' sync state transition`；`events.log` 看事件。
2. 哪些库在同步、各自本地路径：只读 `seafile-data\repo.db` 的 `RepoProperty`（`worktree`、`token`、`username`）。
3. 忽略规则是否生效：按上面的拼接规则算出被忽略目标的完整路径，核对 pattern 是否真的匹配（`*` 跨目录）。
4. 冲突文件：`xxx.txt(SFConflict 姓名 2017-12-25-11-30-28)`。

界面操作（网页版、同步到本地、解除同步、只读、收藏、活动、代理、账号切换）与完整说明见 `references/科大云盘使用说明.md`。

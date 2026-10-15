# 参考来源、本机路径与插件发现优先级

所有相对路径都相对本 skill 目录解析。快照取自 2026-10-15，本机安装版 **Super Productivity 19.2.0**。

## 1. 本 skill 自带的离线快照

| 文件 | 上游来源 | 大小 |
|---|---|---|
| `references/plugin-development.md` | `docs/plugin-development.md` @ master | 36 757 B |
| `references/plugin-api-types.ts` | `packages/plugin-api/src/types.ts` @ master | 29 899 B |

上游更新时以线上为准；要写代码就以 `plugin-api-types.ts` 为准，指南本身承认"可能不是最新"。

## 2. 上游权威路径

| 内容 | 地址 |
|---|---|
| 开发指南 | https://github.com/super-productivity/super-productivity/blob/master/docs/plugin-development.md |
| 类型契约（**权威**） | https://github.com/super-productivity/super-productivity/blob/master/packages/plugin-api/src/types.ts |
| 官方社区插件清单 | https://github.com/super-productivity/super-productivity/blob/master/src/assets/community-plugins.json |
| 示例插件 | https://github.com/super-productivity/super-productivity/tree/master/packages/plugin-dev |
| 示例插件（逐个） | `packages/plugin-dev/yesterday-tasks-plugin`、`packages/plugin-dev/procrastination-buster`、`packages/plugin-dev/api-test-plugin`、`packages/plugin-dev/boilerplate-solid-js` |
| npm 包 | https://www.npmjs.com/package/@super-productivity/plugin-api |
| Wiki（安装/管理） | https://github.com/super-productivity/super-productivity/wiki |
| 中央插件清单讨论 | https://github.com/super-productivity/super-productivity/discussions/5547 |
| 与安装版严格一致的契约 | 取对应 tag 的 types.ts，例如 https://github.com/super-productivity/super-productivity/blob/v19.2.0/packages/plugin-api/src/types.ts |

不要猜 URL 里的 tag 名：`v` 前缀加版本号（`v19.2.0`、`v19.1.0`、`v19.0.1`），需现查 `tags` 接口确认。

## 3. 本机路径（Windows 安装版）

| 内容 | 路径 |
|---|---|
| 安装目录 | `%LOCALAPPDATA%\Programs\Super Productivity` |
| 应用包 | `…\resources\app.asar` |
| 可执行文件（读版本） | `…\Super Productivity.exe` |
| 用户数据目录 | `%APPDATA%\superProductivity` |
| 内置插件 | `app.asar` 内 `.tmp/angular-dist/browser/assets/bundled-plugins/<plugin-id>/` |
| 社区清单快照 | `app.asar` 内 `.tmp/angular-dist/browser/assets/community-plugins.json` |
| 用户上传的插件 | `%APPDATA%\superProductivity\IndexedDB\file__0.indexeddb.leveldb\` |

**关键事实：用户上传（社区）插件不落盘为文件夹。** 它们存在 IndexedDB：

- 数据库 `SUPPluginCache`，对象仓库 `plugins`，每条含 `manifestText` / `pluginCode` / `indexHtml`。
- 路径标识为 `uploaded://<plugin-id>`，这是磁盘上唯一能搜到的痕迹。
- 启用/禁用状态同样只在 IndexedDB（`pluginMetadata`），**不能**靠 `%APPDATA%\superProductivity\plugins` 判断——该目录不存在是正常的。

内置插件则是随包分发的资源文件，出现在 `app.asar` 里。

## 4. 插件来源与优先级

按 P0→P4 依次尝试，不要跳级。

| 优先级 | 来源 | 位置 | 用途 | 可信度 |
|---|---|---|---|---|
| **P0** | **本机内置插件** | `app.asar` → `…/assets/bundled-plugins/<id>/` | 抄可运行实现、对照本安装版契约；`api-test-plugin` 是官方"覆盖全部 API"的参考实现 | 官方随包分发 |
| **P1** | **本机已上传插件** | IndexedDB `SUPPluginCache` / `uploaded://<id>` | 确认本机已装了什么、避免 id 冲突 | 第三方，未验证 |
| **P2** | **官方社区清单** | `src/assets/community-plugins.json`（应用内也有一份快照，Settings → Plugins 卡片展示） | 找现成功能、看星级选型 | 第三方，未验证 |
| **P3** | **官方示例与样板** | `packages/plugin-dev/` | 需要 SolidJS UI 时用 `boilerplate-solid-js` | 官方 |
| **P4** | **任意 GitHub / Codeberg 搜索** | 全网 | 前三级都没有时兜底 | 完全不可信 |

优先级理由：

1. 本机内容与安装版**版本严格匹配**，抄来的 API 一定存在；上游 master 可能已经用了本机没有的 API。
2. 先查本机再看网络，能避免重复造轮子和 id 冲突。
3. P2 是官方维护的策展清单，比随机搜索可信，但仍需读源码——清单不审核代码。
4. P3 的示例偏教学，功能完整度不如内置插件。

拿不准版本时用这个判据：`manifest.minSupVersion` 必须 ≤ 本机版本（19.2.0）。本机 23 个内置插件的 `minSupVersion` 跨度是 7.0.0 ~ 19.2.0，可作为 API 新旧的标尺——`minSupVersion: 19.2.0` 的 `parallel-code` 用的是最新 API。

## 5. 发现插件的命令

```powershell
# 列出内置插件 + 已上传插件 + 社区清单位置
pwsh -File scripts/sp-plugins.ps1 -Action list

# 直接看某个内置插件的某个文件
pwsh -File scripts/sp-plugins.ps1 -Action cat -PluginId api-test-plugin -File manifest.json

# 导出内置插件到目录，便于整目录阅读
pwsh -File scripts/sp-plugins.ps1 -Action extract -PluginId api-test-plugin -OutDir .\sp-api-test
```

取社区清单最新内容：

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/super-productivity/super-productivity/master/src/assets/community-plugins.json |
  Select-Object -ExpandProperty Content
```

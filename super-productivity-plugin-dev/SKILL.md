---
name: super-productivity-plugin-dev
description: Write, review, debug, install, or find plugins for the Super Productivity app — manifest.json plus plugin.js and/or index.html, packaged as a ZIP. Use when asked to extend or automate Super Productivity, add hooks or PluginAPI calls, find existing or community plugins, decide which plugin source to trust, or locate the plugin API contract, examples, and install paths on this machine or upstream.
---

# Super Productivity 插件开发

一个插件就是一个 ZIP，根目录含三件套：

```
my-plugin/
├── manifest.json   # 必需
├── plugin.js       # 宿主侧代码（快捷键/注册/后台逻辑）
├── index.html      # iframe UI（可选）
├── icon.svg
└── config-schema.json   # 可选，manifest 的 jsonSchemaCfg 指向它
```

安装路径**只有一条**：Settings → Plugins → Choose Plugin File 上传 ZIP。没有"从文件夹加载"。改完代码必须重新打包再上传。

## 先定契约，再写代码

1. 读 `references/plugin-api-types.ts`（967 行，权威）。指南自己声明可能过时，**API 名称一律以 types 为准，不要凭记忆写**。
2. 需要与安装版严格一致时，取对应 tag 的 types.ts（本机是 19.2.0 → `v19.2.0`）。先查 tags 接口确认 tag 名。
3. 约束版本：`manifest.minSupVersion` 必须 ≤ 本机版本。本机内置插件 `minSupVersion` 跨 7.0.0 ~ 19.2.0，可当 API 新旧的标尺。

## 找样例与已有插件：按优先级，不要跳级

| 优先级 | 来源 | 位置 | 用途 |
|---|---|---|---|
| **P0** | 本机内置插件 | `app.asar` → `…/assets/bundled-plugins/<id>/` | 抄可运行实现；`api-test-plugin` 覆盖全部 API，是最佳参考 |
| **P1** | 本机已上传插件 | IndexedDB `SUPPluginCache` / `uploaded://<id>` | 看本机装了什么、避免 id 冲突 |
| **P2** | 官方社区清单 | `src/assets/community-plugins.json` | 找现成功能 |
| **P3** | 官方示例/样板 | `packages/plugin-dev/` | 要 SolidJS UI 用 `boilerplate-solid-js` |
| **P4** | 全网搜索 | GitHub / Codeberg | 兜底，完全不可信 |

P0 优先的理由：与安装版**版本严格匹配**，抄来的 API 一定存在；上游 master 可能已用本机没有的 API。完整路径表、URL 和理由见 `references/sources.md`。

一条命令列出本机全部来源：

```powershell
pwsh -File scripts/sp-plugins.ps1 -Action list
```

```powershell
# 看某个内置插件的文件
pwsh -File scripts/sp-plugins.ps1 -Action cat -PluginId api-test-plugin -File manifest.json
# 整目录导出后阅读
pwsh -File scripts/sp-plugins.ps1 -Action extract -PluginId api-test-plugin -OutDir .\sp-api-test
```

关键事实：**用户上传的插件不落盘为文件夹**，存在 IndexedDB；`%APPDATA%\superProductivity\plugins` 不存在是正常的，别据此回答"没装插件"。内置插件才是 `app.asar` 里的文件。

## manifest 必填字段

`id` `name` `version` `manifestVersion`（当前为 1）`minSupVersion` `hooks[]` `permissions[]`。`hooks` 和 `permissions` 是**必需数组**，不用就写 `[]`（`description` 可选）。其余可选字段（`iFrame` `sidePanel` `icon` `jsonSchemaCfg` `allowedHosts` `nodeScriptConfig` `type` `i18n` `uiKit` …）以 types 为准。

12 个 hook：`taskCreated` `taskComplete` `taskUpdate` `taskDelete` `currentTaskChange` `finishDay` `languageChange` `persistedDataChanged` `action` `anyTaskUpdate` `projectListUpdate` `workContextChange`

## 类型选择

- 要监听 hook、注册快捷键/菜单/头部按钮、跑后台逻辑 → 必须有 `plugin.js`。
- 只要 UI → 可以只发 `manifest.json` + `index.html`，但 manifest 里要 `iFrame: true`。
- iframe 只拿到**过滤后的** `window.PluginAPI`。回调类注册方法（`registerHeaderButton` `registerMenuEntry` `registerTaskContextMenuEntry` `registerSidePanelButton` `registerConfigHandler` 等）**只能**在宿主侧 `plugin.js` 里调用。

## 硬约束（踩了会出安全问题）

- `plugin.js` 通过 `new Function` 跑在宿主 renderer 里，**不是沙箱**，能碰宿主特权 API。只装你读过源码的插件。
- iframe 带 `allow-same-origin`，**不是安全边界**，能直接读 `window.parent`。
- 网络默认 fail-closed：要在 `permissions` 里加 `"http"`，并在 `allowedHosts` 写**精确主机名**（无通配符，端口被忽略），两者缺一 `PluginAPI.request` 就不可用。
- 跑原生代码只能走 `executeNodeScript()`，需 `permissions: ["nodeExecution"]` + 主进程原生授权弹窗；上传插件的弹窗标注为"未验证第三方代码 + 完整机器访问"，**默认拒绝**。授权按插件 id 记，禁用/卸载/重传即清除。因此 `id` 必须是单个安全 token：无空白、冒号、`/`、`\`，≤100 字符，推荐小写 kebab-case。
- 没有 `window.ea.exec()`；旧的可执行任意 shell 的 IPC 已被移除。

## 开发与调试

1. 打包 ZIP。
2. Settings → Plugins → Choose Plugin File 上传。
3. F12 / Ctrl+Shift+I 打开 DevTools 看 console。
4. 对照 P0 的 `api-test-plugin` 排查；它将每个 API 调用与预期结果并排展示。

## 发布到社区清单

功能可用后，提 PR 往 `src/assets/community-plugins.json` 加一条（`name` `shortDescription` `url` `author` `authorUrl` `stars`）。安装说明统一写成：下载 release ZIP → Settings → Plugins → Choose Plugin File。

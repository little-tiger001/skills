---
name: magic-hand-windows
version: 1.1.0
display_name: "妙控手 MagicHand · Windows 桌面操控"
display_name_en: "MagicHand · Windows Computer Use"
author: ERPers00001
description: "Windows 桌面操控（Computer Use）：让 AI 亲手操作本机应用。原生 Win32 界面走 HWND 树按索引精准点击；自绘界面（微信、Qt、Flutter、Electron）自动回退到截图判态 + 坐标点击。纯 ctypes 实现，零第三方依赖，离线可用，每一步回读验证。"
description_zh: "Windows 桌面操控（Computer Use）：让 AI 亲手操作本机应用。原生 Win32 界面走 HWND 树按索引精准点击；自绘界面（微信、Qt、Flutter、Electron）自动回退到截图判态 + 坐标点击。纯 ctypes 实现，零第三方依赖，离线可用，每一步回读验证。"
description_en: "Windows computer use — let the agent drive desktop apps directly. Indexed clicks via the Win32 HWND tree for native UIs; screenshot + coordinate fallback for self-drawn UIs (WeChat, Qt, Flutter, Electron). Pure ctypes, zero dependencies, works offline, with read-back verification on every step."
---

# 妙控手 MagicHand — WorkBuddy 版 Computer Use（Windows）

> **定位。** 行业同类能力通称 **computer use**。本技能在 Windows 上让 AI **亲手操作桌面
> 应用**：以结构化 **Win32（HWND）树**为主通道按索引精准点击，自绘界面（微信 / Qt /
> Flutter / Electron）自动回退到「截图判态 + 坐标点击」，每一步**回读验证**再继续。
>
> **纯 `ctypes` 实现，不需要 pip 安装任何包**，离线即可用。零第三方依赖、零 Rust/Go
> 侧要 loaded 的插件：只要有一份 Windows Python 3.8+ 就能跑。

## 环境要求

| 项 | 要求 |
|---|---|
| 系统 | Windows 10 / 11（含 Server） |
| Python | 3.8+（`py -3` / `python` / `python3` 任一可用即可） |
| 第三方包 | **无** |
| 权限 | 必须在**交互式桌面会话（WinSta0）**里运行，见下节 |

目录结构：

```
magic-hand/
├── SKILL.md
├── _skillhub_meta.json
├── scripts/
│   ├── cu_ui.py        引擎主体（Win32 ctypes）
│   ├── cu_live.py      实时屏幕 HTTP 服务（可选，端口 8899）
│   ├── bmp2png.py      截图 BMP→PNG + 裁剪放大 + 坐标标尺 / 准星
│   ├── winmove.py      窗口枚举 / 移动 / 还原
│   ├── clip.py         剪贴板读写
│   ├── start_cu_bridge.bat    双击启动桥
│   └── install_task.bat       注册「登录时自动启动桥」的计划任务
└── templates/
    └── com.workbuddy.cu-bridge.xml   计划任务 XML 模板
```

## 先理解一件事：GUI 会话

在 WorkBuddy 的 Bash 子进程里，**本机的交互式桌面权限**决定了能不能真的动鼠标：

| 检查 | 交互式会话里 | 非交互 / 服务会话里 |
|---|---|---|
| 进程所在的窗口站 | `WinSta0` | 其它（如 `Service-0x0-...`） |
| `EnumWindows` 能看到的真实窗口 | 你桌面上所有窗口 | 几乎为空（只有会话自己的） |
| 移动鼠标 / 发送按键 / 截图 | ✅ 生效 | ❌ **静默无效**（调用返回成功但什么也没发生） |

**这不是权限勾选能解决的**——进程属于哪个会话在启动时就决定了。修复方法：
**让桥接进程跑在你自己的交互式会话里**。

### 第零步 — 永远先 `probe`

```bat
python cu_ui.py probe
```

按 `verdict` 分流：

| verdict | 含义 | 怎么办 |
|---|---|---|
| `READY` | 在 `WinSta0`，既能看也能动 | 直接用 `cu_ui.py`，或走桥 |
| `NO_GUI_SESSION` | 不在交互式会话 | 双击 `start_cu_bridge.bat` 启动 serve；不要从服务的非交互会话里拉起 |
| `NOT_WINDOWS` | 不在 Windows 上 | 本技能是 Windows 版，无法运行 |

很多桌面环境里，从 Bash 直接跑 `probe` 就返回 `READY`，可以端到端直连测试。
换台机器或服务环境时很可能拿到 `NO_GUI_SESSION`——那就必须走桥。

## 桥：两种启动方式

| 方式 | 文件 | 何时用 |
|---|---|---|
| 双击启动（推荐） | `scripts/start_cu_bridge.bat` | 随时手动启动桥 |
| 登录自动启动 | `scripts/install_task.bat`（或模板 `templates/com.workbuddy.cu-bridge.xml`） | 想每次登录自动起 |

> ⚠️ 任务计划必须 `/IT`（InteractiveToken / 仅当用户登录时运行）。若改成
> "无论是否登录都运行"，任务会落到 `session 0`，拿不到桌面 → `NO_GUI_SESSION`。

桥跑起来后，agent 通过文件与它对话（路径在 `%TEMP%`）：

| 文件 | 作用 |
|---|---|
| `%TEMP%\cu_cmd.jsonl` | agent 追加 **一行 JSON** 指令 |
| `%TEMP%\cu_status.json` | 最近一条指令的结果 |
| `%TEMP%\cu_tree.txt` | 最近一次 `tree` 的完整输出（树很长，不塞进 status） |
| `%TEMP%\cu_alive` | 心跳：`<pid> <session_ok>` |
| `%TEMP%\cu_stop` | `touch` 它即可停止桥 |
| `%TEMP%\cu_shot.bmp` | 最近一次截图（BMP） |

协议：追加命令 → 轮询 `cu_status.json` 直到 `id` 匹配 → 读结果（`out`，或
`tree` 读 `cu_tree.txt`）。**同一时刻只能有一个桥**——两个 serve 会抢同一批文件。

## 引擎：`scripts/cu_ui.py`

```bat
python cu_ui.py probe                      # 会话探测
python cu_ui.py apps                       # 运行中的应用 + pid
python cu_ui.py launch notepad --wait 2    # 启动应用（名字 / 路径 / exe）
python cu_ui.py tree notepad --depth 12    # 打印带数字索引的 HWND 树
python cu_ui.py info notepad 1             # 单个节点的详情
python cu_ui.py click notepad 1            # 按索引操作
python cu_ui.py set notepad 1 "文本"        # 按索引设值
python cu_ui.py focus notepad              # 把应用提到前台
python cu_ui.py xy --app notepad --win 0 --nx 500 --ny 514   # 归一化坐标点击
python cu_ui.py type "hello"               # 向当前焦点控件打字
python cu_ui.py key ctrl+a                 # 按键 / 组合键
python cu_ui.py scroll down --app notepad --idx 1 --pages 1  # 滚动
python cu_ui.py drag --app notepad --from-idx 1 --to-idx 5   # 拖拽
python cu_ui.py seltext notepad 1 "World" --mode select      # 选中文本
python cu_ui.py act notepad 1 press        # 命名动作（press/click/setfocus/show）
python cu_ui.py shot                       # 截图到 %TEMP%/cu_shot.bmp
python cu_ui.py watch --on --interval 0.8  # 持续截图循环
python cu_ui.py serve                      # 桥模式（在交互式会话里运行）
```

`<app>` 接受 **pid / 精确名 / 名称子串 / exe 名**（如 `notepad`、`weixin`、`1536`）。

### 配套工具

```bat
python bmp2png.py %TEMP%\cu_shot.bmp %TEMP%\shot.png                  :: BMP→PNG（供 Read 查看）
python bmp2png.py %TEMP%\cu_shot.bmp %TEMP%\crop.png  X Y W H SCALE   :: 裁剪 + 放大，精定位按钮
python bmp2png.py %TEMP%\cu_shot.bmp %TEMP%\g.png X Y W H SCALE --grid 25   :: 叠加绝对坐标标尺
python bmp2png.py %TEMP%\cu_shot.bmp %TEMP%\v.png X Y W H SCALE --cross CX CY  :: 十字准星校验坐标
python winmove.py --list weixin            :: 列出匹配窗口的 hwnd / pid / rect
python winmove.py weixin --rect 950 320 965 650   :: 移动/摆正窗口（含最小化还原）
python clip.py get                         :: 读剪贴板
python clip.py set "文本"                   :: 写剪贴板（配合 key ctrl+v 粘贴）
python clip.py set --file P.txt | clear
```

全部纯 `ctypes`，无第三方依赖。

### 读树

```
app: notepad (pid 1536, exe notepad.exe)  windows: 1  nodes: 3
  window idx=0 "无标题 - 记事本"
[0] Window "无标题 - 记事本" sub:Notepad
  [1] Edit "Hello from WorkBuddy Windows engine"
  [2] Control sub:msctls_statusbar32
```

四条规则：

1. **索引是行首的整数，不是行号。** 编号会跳（0 → 1 → 2 …）。
2. **每次界面变化后索引都会失效。** 打开菜单、提交、滚动、切换窗口后都要重读树。
3. **`ok:true` 不是证明。** 证明是「下一步的树显示目标状态」。
4. 不要反复打印整棵树——读完一次、规划、行动，只在决策边界重读。

> 窗口的三颗标题栏按钮（最小化/最大化/关闭）也出现在每个应用里，看到它们**不**
> 证明应用自身 UI 可读。真正的控件是 `Button`/`Edit`/`StaticText` 等带行为的节点。

### 该走索引，还是走坐标？

先读树判断应用底层怎么画的：

| UI 怎么画的 | HWND 树里有真的控件节点吗 | 怎么办 |
|---|---|---|
| 原生 Win32（Notepad、计算器、文件对话框、Explorer 面板、多数业务系统） | ✅ `Edit`/`Button`/`ComboBox`… 带行为 | 用索引 `click`/`set` |
| Web / Electron / CEF | 仅在网页内容里（DOM 元素不是 HWND） | 优先用浏览器自动化，不要在这里硬点 |
| 自绘画布（**微信 / WeChat、Qt、Flutter、游戏**） | ❌ 内容区塌缩成空 `Control`（如 `MMUIRenderSubWindowHW`） | 立即切到 **坐标**：`xy` / `drag`，按窗口归一化 0–1000 |

实测 `tree weixin` 只长出一棵空树：

```
app: weixin (pid 8536, exe weixin.exe)  windows: 1  nodes: 2
  window idx=0 "微信"
[0] Window "微信" sub:Qt51514QWindowIcon
  [1] Control "MMUIRenderSubWindowHW" sub:MMUIRenderSubWindowHW
```

——索引路径在这里**死路一条**。这时用：
`xy --app weixin --win 0 --nx 310 --ny 60`（窗口归一化 0–1000，抗窗口移动/缩放）。
**绝对像素 `xy --x 310 --y 60` 也能用，但窗口一挪就偏，是最后手段。**

### ⭐ 定位点击目标：永远别靠缩略图估算

读图时你看到的截图**已经被缩放过了**，在上面「目测」一个按钮的像素坐标必然偏——
实测偏差可达 300+ 像素（曾把某个菜单按钮估成 (830,276)，实际是 (498,59)）。
用 `bmp2png.py` 的两个叠加层把坐标**读出来**，而不是猜：

```bash
# 1) 标尺网格：线永远落在「绝对坐标」的整数倍上，读图即得坐标
python bmp2png.py %TEMP%\cu_shot.bmp %TEMP%\g.png X Y W H SCALE --grid 25
#    红线 = 50 的倍数（带数字标签），浅蓝线 = 25 的倍数。标签就是屏幕绝对坐标。
#    建议 SCALE 取 4–5，裁剪区控制在 900×900 像素以内，保证长边 ≈1000 便于阅读。

# 2) 十字准星：在候选坐标上画十字，看图是否正落在目标上 —— 自校验，闭环
python bmp2png.py %TEMP%\cu_shot.bmp %TEMP%\v.png X Y W H SCALE --cross CX CY
#    准星偏了就用同一张 bmp 重画（不必重新截图），微调 CX CY 直到命中，再 xy 点击。
```

两条经验：

- **准星比网格更快**：先粗估一个坐标 → 画准星 → 一眼看出偏多少 → 修正 → 点。通常一轮收敛。
- **裁剪窗口的 X Y W H 也要尽量贴近目标**，否则 SCALE 放大后视野太小、找不到参照物。

### 实战示例：自绘 UI（微信）「搜索联系人 → 发消息」

自绘应用没有可依赖的索引，靠「**截图判态 + 坐标点击**」逐步推进。这是最难的那一类
界面，其他自绘应用照此套路即可：

1. `focus weixin` → `shot` → `bmp2png.py` 转 PNG → 读图确认已登录。
2. 点左上「搜索」框。
3. `type "联系人名"` —— **`WM_CHAR` 在 Qt 自绘应用上实测可用**，中文正常输入，无需 SendInput。
4. 读图，点「联系人」区里的目标行（务必区分同名的公众号 / 群聊）。
5. 读图确认顶部标题栏是对的人 → 点底部输入框。
6. `type "正文"` → 读图确认输入框内容。
7. 用 `--cross` 读图定位绿色「发送」按钮再点。
8. `shot` 复查：己方绿色气泡出现 + 输入框清空 + 左列表预览更新 = 发送成功。

> ⚠️ 关键经验：自绘应用的按钮坐标**必须**用 `bmp2png.py ... SCALE` 放大核对后再点。
> 直接照缩略图估算会偏几十像素而点空（实测一次即踩坑：估 (1378,806) 点空，
> 实际按钮在 (1352,825)）。**坐标随分辨率 / 窗口位置变化，换机重算。**

### 命令实现与回退

- **click**：`Button` → `SendMessage(BM_CLICK)`（无需前台，最稳）；其它 →
  `SetForegroundWindow` + 真实鼠标点击中心（`win:mouse`）。
- **set**：`Edit`/`RichEdit` → `WM_SETTEXT`（整段替换）；其它 → 点击聚焦后 `WM_CHAR`
  逐字键入（`win:type`）。
- **type**：`WM_CHAR` 发到前台窗口（支持中文等任意文本）。**实测 Qt 自绘应用
  （微信）也能收到**，中文输入正常——不必改用 SendInput。
- **key**：`VK` + 修饰键组合（`ctrl+a`、`alt+f4`、`tab`、`down`…）。
- **scroll**：先试控件原生；否则在坐标处滚轮（`win:wheel`）。
- **drag**：真实鼠标 down→移动→up（`win:mouse_drag`）。
- **seltext**：Edit 控件的 `EM_SETSEL`，并**回读 `EM_GETSEL` 校验**（不只看 `ok`）。
- **shot**：`BitBlt` 全屏 → BMP（纯 ctypes，无需 Pillow）；`watch` 循环写同一文件。
  > 注意：BMP 无法被 Read 直接显示。要「看」截图，先用 `bmp2png.py` 转 PNG 再读。
  > 这是引擎侧唯一的视觉通道——自绘应用判断界面状态全靠它。

### 陈旧的索引会被拦下

`click`/`set`/`act`/`seltext` 会拿目标行当前的 `(role, title, cls)` 和上次树比对，
若不一致就报 `stale_index` 拒绝（带 `--force` 可故意覆盖）。这避免了「索引没变但
界面已变、点到别处真实控件」的静默误操作。

## 交给用户亲自操作（必须停手）

遇到以下情况，**停下并把控制权交还用户**：登录 / 输密码 / 扫码 / MFA / 授权弹窗 /
手动接管。报出应用名、精确步骤，让用户做完再说一声。不要重试、不要绕过、不要
代输凭据。微信登录就是典型：打开微信后**扫码那一步必须由本人完成**——引擎可以把
窗口点到扫码页，但二维码得本人拿手机扫。

## 安全护栏

- 只操作前台可见窗口。
- 删除 / 批量发送 / 登出 / 退出，需用户显式确认。
- 截图是瞬时观察，未经用户要求不落盘、不交付。
- 桌面可能含隐私内容，仅用于决策，不外传。
- 紧急停止：`touch %TEMP%\cu_stop`，或把鼠标甩到左上角（若同时跑了别的 driver）。

## 能力已验证（Windows 10 / WinSta0 实测）

- `probe` → `READY`，`station: WinSta0`。
- `launch notepad` → 启动成功；`tree notepad` 拿到结构化树。
- `set`→`click`→`type` 在记事本里落地：`[1] Edit "Hello from WorkBuddy Windows engine"`。
- `seltext ... "WorkBuddy"` → `selected_range: [11, 20]`，`verified: true`。
- 桥：`serve` 起在交互式会话，agent 通过 `cu_cmd.jsonl` 下发 `apps`/`tree`，结果正确写回。
- `shot` → 全屏 BMP（1920×1080）。
- 空树应用（微信）→ 切坐标流，**搜联系人 → 发消息**完整链路可用（气泡出现 + 输入框清空 + 列表预览更新）。
- 窗口被自绘面板撑出屏幕 → `winmove.py --rect` 摆回后可继续操作。
- 坐标精度：改用 `--grid` / `--cross` 读图定位后，一次收敛。

## 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `verdict: NO_GUI_SESSION` | 进程不在 `WinSta0` | 双击 `start_cu_bridge.bat`，或装任务计划（`/IT`）；绝不在非交互会话重试 |
| 命令返回 `ok` 但桌面毫无反应 | 同上，静默失败 | `probe` 确认会话，改走桥 |
| `app_not_found` | 应用没运行 / token 不匹配 | 先 `apps` 看真实名，或用 pid |
| `index_out_of_range` | 重读后树重排号 | 重读树取新索引 |
| `stale_index` | 目标行身份变了 | 重读树；必要时 `--force` |
| 点击「成功」但什么也没发生 | 你信了过期的 `ok` | 重读树确认目标仍在那 |
| 自绘应用点不到 | 索引路径死路 | 改用 `xy`/`drag` 归一化坐标 |
| 截出来的图打不开 / 无法查看 | 是 BMP 格式 | 用 `bmp2png.py` 转 PNG 再读 |
| 批量脚本在 cmd 里行为诡异 | `.bat` 用了 LF 行尾 | 转成 CRLF（打包时已自动处理） |

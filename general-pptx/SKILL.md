---
name: general-pptx
description: 手工创建或改造 .pptx 时使用：用 PptxGenJS 从零写一版自由排版的幻灯片、按模板拆包改页/改字/换版式、删除或复制幻灯片、提取演示文本与页面结构。适用于用户明确要求"自己写代码做 PPT""不用模板系统、自由设计版面""修改已有的 pptx 或导师给的模板"，或需要编辑既有幻灯片这类 artifact-presentations 做不到的操作。触发词：pptx、ppt、deck、slides、演示文稿、幻灯片、模板。若只是按标准内容生成常规汇报/讲座幻灯片，改用 artifact-presentations。
---

# General PPTX（本机适配版）

## 定位与分工

本 skill = **手工排版 + XML 级读写**，补 DSH 内置 `artifact-presentations` 的空缺。两者二选一，不要混用：

- 造一份常规汇报/讲座/学院模板幻灯片，要统一观感、可复现 → `artifact-presentations`（`office_presentation`）。
- 改已有的 pptx、导师给的模板，或要自己控制坐标/配色/字体、写代码排版 → 本 skill。

`office_presentation` 只有 create/inspect/validate，**改不了已有幻灯片**，这是本 skill 的不可替代之处。

## 本机环境（已就绪，不要安装）

- Python 用 `py -3`（3.14，已装 `python-pptx`/`markitdown`/`Pillow`/`lxml`/`defusedxml`）。`python3`、`python` 在这台机器上是 WindowsApps 存根，执行没有任何输出，不要用。
- Node 与 `pptxgenjs@4.0.1` 已可用。图标用的 `react-icons`/`sharp` 未装，确实需要时再装。
- 渲染走 DSH 自带的 LibreOffice Kit，由 `scripts/render_slides.py` 自动定位，**不要装 LibreOffice 或 poppler**。
- 相对 qoder 原版的改动：删除 Linux 专用的 `scripts/office/soffice.py`；`check_text_overflow.py` 改为几何估算（原因见该脚本 docstring）；渲染改走 Kit（WPS COM 兜底）；图片获取改为用项目内素材或宿主能力。

## 完成清单（必做）

- [ ] 文本 QA：`py -3 -m markitdown out.pptx` — 内容、顺序、错字、模板残留占位符
- [ ] 边界检查：`py -3 scripts/check_overlap.py out.pptx`
- [ ] 溢出估算：`py -3 scripts/check_text_overflow.py out.pptx`
- [ ] 渲染看图：`py -3 scripts/render_slides.py out.pptx --out preview-v1`，再自己 `read_image` 或交给 subagent
- [ ] 修 → 重跑 → 直到一轮全新检查无新问题

## 读取内容

```bash
py -3 -m markitdown deck.pptx                        # 纯文本，看内容与顺序
py -3 scripts/thumbnail.py deck.pptx grid --cols 4   # 缩略图网格，看版式
py -3 scripts/office/unpack.py deck.pptx unpacked/   # 原始 XML
```

## 编辑已有演示

完整流程见 [editing.md](editing.md)。骨架：`unpack → 改 slideN.xml → clean → pack`。

- 删页/改序在 `ppt/presentation.xml` 的 `<p:sldIdLst>`；复制页用 `scripts/add_slide.py`，不要手工拷 slide 文件。
- 改文字用 Edit 工具逐处替换，不要用脚本批量替换；多页并行时各页是独立 XML，可交给 subagent。
- 模板槽位多于素材时，整组删掉多余元素（图 + 文本框），不要只清空文字。

## 从零创建

PptxGenJS 教程与 API、常见坑见 [crafting.md](crafting.md)；风格选择、配色、字体、布局、避坑见 [references/design.md](references/design.md)。

## 图片

本机没有内置图像生成工具。需要配图时：优先用项目内已有图片；其次问用户；不要联网抓图，也不要为了"每页都要有视觉元素"破坏学术/技术风的克制版面。宿主若配置了图像 provider，按其对应 skill 生成。

## QA：渲染看图

```bash
py -3 scripts/render_slides.py deck.pptx --out preview-2 --pages 1,3,6 --dpi 144
py -3 scripts/render_slides.py deck.pptx --out preview-kit --engine kit   # WPS 不可用时
```

脚本打印每页 PNG 路径和 manifest 路径；`missingFonts` 非空必须在结论里说明（字体被替换会改变换行）。**输出目录必须是新目录**，脚本拒绝覆盖。

**默认走 WPS COM**：2026-10 在本机实测，DSH 自带 LibreOffice Kit（0.1.2）对 13.333×7.5in 的宽屏 deck 渲染会把内容画得比页面大——页面尺寸正确但右侧和底部被裁掉，PptxGenJS 和 python-pptx 生成的 deck 都中招；同一文件用 WPS COM 导出正常。所以 `auto` 先试 COM，Kit 只作兜底；用 Kit 出图后务必确认画面没有被放大裁切。

看图时按这份清单找问题，找不到问题就再看得更狠一点：

- 文字被裁掉、挤成一团，或为塞进去被压得很小
- 元素相撞（文字压文字、线穿过字），但卡片上叠字、背景上贴标签属故意
- 装饰线按单行标题设计，标题却折成两行
- 页脚/来源与正文相撞；边距小于 0.3"，或某处大片空白与某处拥挤并存
- 栏与同类元素没对齐；低对比文字或图标
- 残留占位符（"请填写""标题区域""高亮词部分""lorem ipsum"）、未删的设计参考页

**换一双眼睛**：不要只自己复核。用 `subagent` / `subagent_fork` 看渲染图，附上图片路径与每页预期内容。至少完成一轮"发现问题 → 修 → 复查"。

## 常见坑

- 颜色写 6 位十六进制、不加 `#`；透明度用 `opacity`，不要编码进颜色字符串。
- 用 `bullet: true`，不要写 Unicode "•"（会双项目符号）；数组项之间加 `breakLine: true`。
- 选项对象每次现造，不要跨调用复用（PptxGenJS 会原地改写）。
- `shadow.offset` 不能为负；`ROUNDED_RECTANGLE` 不要配直角强调条。
- 编辑 XML：智能引号用实体（`&#x201C;`），解析用 `defusedxml`，需要保留空格时加 `xml:space="preserve"`。
- 文字放不下时压缩文案，不要缩字号、不要撑破模板版式比例。

---
name: mineru
description: "Parse and read documents (PDF, images, Word, PPT, Excel) with the official MinerU API. Use when the user asks to 解析/提取/转换/阅读 a document or PDF, extract text/tables/formulas/images, or mentions MinerU. Also use to 整理/清理/维护 the .mineru cache folder — find and delete 死文件/orphaned/stale Markdown and images whose source document was renamed or deleted (清理 .mineru 文件夹, 清理死文件, 清理缓存). Check ./.mineru/ for an existing Markdown result before parsing; outputs use ./.mineru/ with images in ./.mineru/img/."
argument-hint: "[要解析的文件路径，可多个]"
user-invocable: true
---

# MinerU 文档解析

将本地文档（PDF、图片、Word、PPT、Excel）通过 **MinerU 官方 API** 解析为结构化 Markdown，提取文档中的图片；当文档已经解析过时，直接读取已有 Markdown。

## 何时使用
- 用户要求「解析 / 提取 / 转换」某个文档或 PDF 为 Markdown
- 用户要求「阅读」某个 PDF，或要求根据 PDF 内容回答问题
- 用户要求从文档中提取文字、表格、公式、图片
- 用户要求「整理 / 清理」`.mineru/` 缓存，或删除源文件改名后残留的死文件
- 用户提到 MinerU

## 配置
Token 等配置存放在本 skill 目录下的 `.env` 文件。首次使用时，将 `.env.example` 复制为 `.env` 并填写 `MINERU_TOKEN`。

## 使用步骤
1. 确认文件路径和当前工作区根目录。
2. 阅读 PDF 时先按命名规则检查缓存：把 PDF 相对工作区根目录路径中的 `/` 转换为 `-`，去掉 PDF 后缀。例如 `课件/课件-0-绪论.pdf` 对应 `.mineru/课件-课件-0-绪论.md`。
3. 如果对应 Markdown 存在，直接读取它，并按需读取 `.mineru/img/` 中的图片；不要重新调用 API。若还需要页码、表格 HTML、公式等机器可读结构，读同名的 `.mineru/<同名>.content_list.json`。
4. 如果 Markdown 不存在，或用户明确要求重新解析，在当前工作区根目录运行：
   ```
   python <SKILL_DIR>\\scripts\\parse.py <文件1> [文件2 ...]
   ```
   常用附加参数：`--refresh`（忽略缓存强制重解析）、`--keep-zip`（把 MinerU 返回的完整 zip 保存到工作区根目录，便于查看包内内容）、`--ocr`（扫描件）、`--model pipeline|vlm`。
5. 脚本会将 Markdown 写入 `.mineru/`，将提取的图片写入 `.mineru/img/`，将内容列表写入 `.mineru/<同名>.content_list.json`。
6. 向用户报告命中的 Markdown，或新生成的 Markdown、图片数量与内容列表。

## 输出文件与优先级
- `.mineru/<同名>.md`：正文，阅读、检索、总结首选。
- `.mineru/<同名>.content_list.json`：按阅读顺序的块列表，每块含 `type`（text/title/table/image/equation）、`page_idx`、`text_level`、表格 HTML、公式 LaTeX。需要页码引用、只取表格/公式、按章节切分时用它。
- `.mineru/img/`：提取的图片，md 中的引用已改写为 `img/<名>`。
- 包内的 `layout.json`(middle.json)、`*_model.json` 体积大且基本只服务渲染，**不落盘**；确需查看时用 `--keep-zip` 保留原始 zip 自行解压。

## 清理死文件
源文件被改名或删除后，`.mineru/` 中对应的 Markdown 与图片会失去指向，成为死文件。
用清理脚本扫描并删除它们（脚本按命名规则反查源文件是否存在）：

```
python <SKILL_DIR>\\scripts\\clean.py            # 预览（dry-run，默认）
python <SKILL_DIR>\\scripts\\clean.py --delete   # 删除（会二次确认）
python <SKILL_DIR>\\scripts\\clean.py --delete --yes   # 跳过确认
```

- 默认只列出死文件，不删除；加 `--delete` 才真正删除。
- 会同时清理死 Markdown、内容列表 JSON 和 `.mineru/img/` 中对应的孤儿图片，并删除空的 `img/` 目录。
- 若源文件只是改名，可先用 `--delete` 清掉旧缓存，再重新解析新文件。

## 注意事项
- 单文件限制：不超过 200MB、200 页。
- 解析是异步任务，脚本会自动轮询。
- 仅使用 Python 标准库，需要 Python 3.8+。
- API Token 只保存在本机 `.env`，不要提交到 Git。

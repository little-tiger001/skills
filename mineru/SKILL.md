---
name: mineru
description: "Parse and read documents (PDF, images, Word, PPT, Excel) with the official MinerU API. Use when the user asks to 解析/提取/转换/阅读 a document or PDF, extract text/tables/formulas/images, or mentions MinerU. Check ./.mineru/ for an existing Markdown result before parsing; outputs use ./.mineru/ with images in ./.mineru/img/."
argument-hint: "[要解析的文件路径，可多个]"
user-invocable: true
---

# MinerU 文档解析

将本地文档（PDF、图片、Word、PPT、Excel）通过 **MinerU 官方 API** 解析为结构化 Markdown，提取文档中的图片；当文档已经解析过时，直接读取已有 Markdown。

## 何时使用
- 用户要求「解析 / 提取 / 转换」某个文档或 PDF 为 Markdown
- 用户要求「阅读」某个 PDF，或要求根据 PDF 内容回答问题
- 用户要求从文档中提取文字、表格、公式、图片
- 用户提到 MinerU

## 配置
Token 等配置存放在本 skill 目录下的 `.env` 文件。首次使用时，将 `.env.example` 复制为 `.env` 并填写 `MINERU_TOKEN`。

## 使用步骤
1. 确认文件路径和当前工作区根目录。
2. 阅读 PDF 时先按命名规则检查缓存：把 PDF 相对工作区根目录路径中的 `/` 转换为 `-`，去掉 PDF 后缀。例如 `课件/课件-0-绪论.pdf` 对应 `.mineru/课件-课件-0-绪论.md`。
3. 如果对应 Markdown 存在，直接读取它，并按需读取 `.mineru/img/` 中的图片；不要重新调用 API。
4. 如果 Markdown 不存在，或用户明确要求重新解析，在当前工作区根目录运行：
   ```
   python <SKILL_DIR>\\scripts\\parse.py <文件1> [文件2 ...]
   ```
5. 脚本会将 Markdown 写入 `.mineru/`，将提取的图片写入 `.mineru/img/`。
6. 向用户报告命中的 Markdown，或新生成的 Markdown 和图片数量。

## 注意事项
- 单文件限制：不超过 200MB、200 页。
- 解析是异步任务，脚本会自动轮询。
- 仅使用 Python 标准库，需要 Python 3.8+。
- API Token 只保存在本机 `.env`，不要提交到 Git。

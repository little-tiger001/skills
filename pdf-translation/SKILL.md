---
name: pdf-translation
description: "Use when the user asks to translate one or multiple PDFs, papers, theses, Word documents, or scanned documents with the global pdf2zh MCP server."
---

# PDF Translation

Use the global `pdf2zh` MCP server for document translation. It is available in any VS Code workspace.

The server uses the OpenAI-compatible provider configured in the local PDFMathTranslate `.env` file. Never include API keys in this Skill file or in chat.

Batch tuning options in that `.env` are `OPENAILIKED_BATCH_SIZE=32` and
`OPENAILIKED_BATCH_MAX_CHARS=80000`. They combine several paragraphs into one
API request. Keep the character limit within the model provider's context
window. Use `translate_pdfs` for multiple independent files in one MCP call;
the files are processed sequentially to keep rate usage predictable.

The MCP exposes both `translate_pdfs` and the backward-compatible
`translate_pdf`. Pass a list of absolute paths when translating multiple files.

## Workflow

1. Confirm the input path exists and is an absolute path.
2. Preserve the original file. Never overwrite it.
3. Use `auto` for the source language when supported; otherwise ask the user.
4. Default the target language to Chinese unless the user specifies another language.
5. Generate both mono and dual PDFs when both outputs are available.
6. Report the absolute paths of every generated file.
7. For scanned PDFs, enable OCR or explain that OCR language data is required.
8. If the provider returns HTTP 429, report rate limiting and do not retry indefinitely.
9. Do not claim success unless the output files exist.

## User-facing result

Keep the final response concise. Include the input file, target language, provider if known, output paths, and warnings about OCR, rate limits, or partial-page testing.

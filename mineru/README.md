# MinerU Skill

Use the official MinerU API to parse local PDFs and other supported documents into Markdown with extracted images.

Copy `.env.example` to `.env`, then set `MINERU_TOKEN`. The skill checks the current workspace `.mineru/` cache before submitting a new parse task.

## Scripts

- `scripts/parse.py` — parse documents into `.mineru/` Markdown + images.
- `scripts/clean.py` — find and remove orphaned cache files (dead Markdown/images whose source document was renamed or deleted). Dry-run by default; pass `--delete` to remove.

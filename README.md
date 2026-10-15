# Personal Agent Skills

A collection of reusable skills for AI coding agents.

## Skills

| Skill | What it does |
|---|---|
| `data-visualization-studio` | Build interactive or static charts, dashboards and statistical plots from datasets (PNG / SVG / HTML / PDF). |
| `find-skills` | Entry point for skill discovery and installation. Prefers skillhub, falls back to clawhub. |
| `general-pptx` | Hand-write or rework `.pptx`: PptxGenJS layouts from scratch, edit a supplied template in place, delete/duplicate slides, extract text and page structure. |
| `github-account` | Drive a GitHub account and the USTC GitLab (git.ustc.edu.cn) over REST: token scopes, repos, releases and their assets, Generic Packages, push-mirror status. No `gh` CLI needed. |
| `mineru` | Parse local documents (PDF, images, Word, PPT, Excel) through the official MinerU API, and maintain the workspace `.mineru/` cache. |
| `olcli-ustc` | Sync and compile USTC Overleaf LaTeX projects from the command line; also downloads build outputs such as `.bbl` for arXiv. |
| `pdf-translation` | Translate PDFs, papers, theses or scanned documents with the global pdf2zh MCP server. |
| `skill-install-rules` | Decide where a skill belongs: a single tool's own skill directory, or the shared cross-tool directory. |
| `skillhub-preference` | Prefer `skillhub` over `clawhub` when discovering, installing or updating skills. |
| `super-productivity-plugin-dev` | Write, review, debug or install Super Productivity plugins (`manifest.json` plus `plugin.js`/`index.html`, packaged as a ZIP). |
| `ustc-cloud` | Work with the USTC cloud drive (pan.ustc.edu.cn, a customised Seafile) over WebDAV: list, download, upload, delete, write `seafile-ignore.txt`, and troubleshoot sync problems. |

## Installation

Clone this repository into the agent's skills directory, or copy/link an individual skill into the directory supported by your agent.

Never commit real API tokens. Copy a skill's `.env.example` to `.env` and fill in local credentials; `.env`, `__pycache__/`, `.mineru/` and the agent's own runtime state files are git-ignored.

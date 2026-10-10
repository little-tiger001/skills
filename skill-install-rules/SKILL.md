---
name: skill-install-rules
description: Decides where to install a skill so it lands in the right place. Use whenever installing, adding, moving, or relocating an agent skill, or when choosing between a tool-specific skill directory and the shared cross-tool directory. Rule - marketplace-installed skills go into each agent tool's own default skill directory; general/reusable skills obtained elsewhere (git clone, manual download, another tool) go into the shared directory so every agent can use them.
---

# Skill Install Rules

## Overview

Route every skill to one of two places so nothing is duplicated, nothing pollutes a tool-managed directory, and reusable skills stay shared across all agent tools.

## The rule

Decide by **where the skill came from**, not by which tool is asking:

- **Installed from an agent tool's own marketplace / built-in installer** → put it in **that tool's default skill directory**. The tool manages updates and metadata there; do not move it out.
- **A general/reusable skill obtained any other way** (git clone, manual download, a bundle from a website, copied from another tool, hand-written) → put it in the **shared cross-tool directory**: `~/.agents/skills/<skill-name>/`.

Rationale: marketplace skills carry tool-specific metadata and auto-update, so they belong to their tool. General skills are meant to be reused by every agent, so they live in one shared, version-controlled place that all tools read.

## Known directories

| Purpose | Path |
|---|---|
| Shared cross-tool skills (general/reusable) | `~/.agents/skills/` |
| Qoder — user marketplace skills | `~/.qoder-cn/skills/` |
| Qoder — project-scoped skills | `<repo>/.qoder/skills/` |

Most agent tools also read `~/.agents/skills/` in addition to their own directory. For any tool not listed here, **confirm its actual default skill directory before writing** (check its docs or settings) rather than assuming a path.

## Procedure

1. Identify the skill's origin: marketplace-installed, or general/reusable from elsewhere.
2. Marketplace → the installing tool's own default directory. General → `~/.agents/skills/<skill-name>/`.
3. Each skill is a folder containing `SKILL.md` (plus optional `scripts/`, `references/`, `assets/`). Folder name must equal the frontmatter `name`.
4. After placing it, reload skills in the tool (e.g. `/skills reload` or restart) and verify it appears in the skills list.

## Constraints

- **Do not symlink or junction a tool's whole skill directory onto `~/.agents/skills`.** `~/.agents/skills` is a git repository; merging a tool's live install target into it turns every marketplace install into untracked repo noise and risks accidental commits/pushes and deletion hazards. Keep the two directories separate and let each tool read both.
- Never commit real secrets into `~/.agents/skills`. Put credentials in a gitignored `.env` (already ignored), not in `SKILL.md`.
- If a general skill was mistakenly placed in a tool-specific directory, move its folder into `~/.agents/skills/` and remove the original so it is not loaded twice.

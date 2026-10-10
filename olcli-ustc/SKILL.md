---
name: olcli-ustc
description: Sync and manage USTC Overleaf LaTeX projects from the command line. Pull projects locally, push changes back, compile PDFs, and download compile outputs like .bbl files for arXiv submissions. Use when working with LaTeX, Overleaf, academic papers, or arXiv on the USTC Overleaf instance.
license: MIT
metadata:
  base_url: https://latex.ustc.edu.cn
  cookie_name: overleaf.sid
  agent_url: https://latex.ustc.edu.cn/agent
---

# olcli-ustc Skill

Manage USTC Overleaf LaTeX projects via the `olcli` CLI.

## Installation (for AI agents on headless servers)

This skill is designed for AI agents that need to install olcli and authenticate on a headless server. The authentication flow requires a one-time token from a browser session.

### Step 1: Get a token from the user

Tell the user to visit this URL in their browser (they must be logged into USTC Overleaf):

> https://latex.ustc.edu.cn/agent/setup

The page will display a one-time token. Ask the user to copy and paste it to you.

### Step 2: Download the skill bundle

The bundle IS the skill folder — it contains this SKILL.md plus install scripts for all platforms. Download and extract it:

```bash
curl -sSL https://latex.ustc.edu.cn/agent/bundle.tar.gz -o olcli-ustc-bundle.tar.gz
tar xzf olcli-ustc-bundle.tar.gz
```

Or for Windows (zip):

```powershell
Invoke-WebRequest https://latex.ustc.edu.cn/agent/bundle.zip -OutFile olcli-ustc-bundle.zip
Expand-Archive olcli-ustc-bundle.zip
```

After extraction you will have:
- `SKILL.md` — this file (instructions for the AI agent)
- `install.sh` — bash install script (Linux/macOS)
- `install.ps1` — PowerShell install script (Windows)

### Step 3: Install and authenticate

Run the local install script with the user-provided token:

**Linux/macOS:**
```bash
bash install.sh --token USER_PROVIDED_TOKEN
```

**Windows:**
```powershell
.\install.ps1 -Token USER_PROVIDED_TOKEN
```

This will:
- Install olcli (USTC edition) from the locally-hosted tarball
- Configure USTC defaults (base URL: https://latex.ustc.edu.cn, cookie: overleaf.sid)
- Exchange the token for a session cookie and authenticate
- Verify authentication via `olcli whoami`

If olcli is already installed, the script skips installation and only refreshes authentication.

olcli is installed to `~/.local/olcli-ustc/bin/`. If `olcli` is not found after install, run:

```bash
source ~/.bashrc
```

Or set PATH for the current session:

```bash
export PATH="$HOME/.local/olcli-ustc/bin:$PATH"
```

The binary is at `~/.local/olcli-ustc/bin/olcli`.

### Step 3: Verify

```bash
olcli whoami
olcli list
```

## Manual Installation (without token)

If the user prefers to install manually:

```bash
npm install -g https://latex.ustc.edu.cn/agent/olcli-ustc-latest.tgz
olcli config set-url https://latex.ustc.edu.cn
olcli config set-cookie-name overleaf.sid
olcli auth --token USER_PROVIDED_TOKEN
```

## npm config hygiene (IMPORTANT)

- **NEVER** run `npm config set prefix ...` to point npm at the olcli install dir — it writes `prefix=` permanently to the user-level `~/.npmrc` and hijacks the machine's default global-install location for every project afterwards.
- Only when installing / invoking the **local olcli-ustc** copy should a temporary prefix be used, and **only scoped to that single command** via the environment variable, which never touches `~/.npmrc`:

  ```bash
  npm_config_prefix="$HOME/.local/olcli-ustc" npm install -g <tarball-or-url>
  npm_config_prefix="$HOME/.local/olcli-ustc" npx olcli ...   # if needed per-command
  ```

- After any install, verify the user config was not altered:

  ```bash
  npm config get prefix   # must still be the system default, NOT ~/.local/olcli-ustc
  ```

  If `~/.npmrc` was polluted (e.g. it contains `prefix=...olcli-ustc`), restore it by removing that line or running `npm config set prefix "$HOME/.npm-global"` (or the original value).
- The bundled `install.sh`/`install.ps1` already follow this rule; never re-introduce a bare `npm config set prefix` in custom recipes.

## Common Workflows

### Pull a project to work locally

```bash
olcli pull "My Paper"
cd My_Paper/
```

### Edit and sync changes

```bash
olcli push
olcli sync
olcli sync --no-delete
```

### Compile and download PDF

```bash
olcli pdf
olcli pdf -o paper.pdf
olcli compile
```

### Download .bbl for arXiv submission

```bash
olcli output bbl
olcli output bbl -o main.bbl
olcli output --list
```

### Upload figures or assets

```bash
olcli upload figure1.png "My Paper"
```

### Delete or rename remote files

```bash
olcli delete chapters/old.tex
olcli rename old.tex new.tex
```

### Review comments

```bash
olcli comments list
olcli comments list --status open
olcli comments add main.tex "Fix this citation"
olcli comments resolve <thread-id>
```

## Commands Reference

| Command | Description |
|---------|-------------|
| `olcli auth --token <token>` | Authenticate with one-time token (recommended) |
| `olcli auth --cookie <value>` | Authenticate with session cookie |
| `olcli whoami` | Check authentication status |
| `olcli logout` | Clear stored credentials |
| `olcli check` | Show config paths and credential sources |
| `olcli list` | List all projects |
| `olcli info [project]` | Show project details |
| `olcli pull [project] [dir]` | Download project files |
| `olcli push [dir]` | Upload local changes |
| `olcli sync [dir]` | Bidirectional sync |
| `olcli upload <file> [project]` | Upload a single file |
| `olcli download <file> [project]` | Download a single file |
| `olcli delete <file> [project]` | Delete a remote file (alias: `rm`) |
| `olcli rename <old> <new> [project]` | Rename a remote file (alias: `mv`) |
| `olcli compile [project]` | Trigger compilation |
| `olcli pdf [project]` | Compile and download PDF |
| `olcli output [type]` | Download compile outputs (bbl, log, aux, etc.) |
| `olcli zip [project]` | Download as zip archive |
| `olcli comments list [project]` | List review comments |
| `olcli comments add <file> <msg>` | Add a comment |
| `olcli comments resolve <id>` | Resolve a comment thread |

## Tips

- Run commands from a synced directory (contains `.olcli.json`) to auto-detect the project
- Use `olcli push --dry-run` or `olcli sync --dry-run` to preview before applying
- Use `olcli pull --force` to overwrite local changes
- LaTeX build artifacts (`.aux`, `.bbl`, `.log`, etc.) are filtered by default; add custom patterns to `.olignore`
- Use `olcli --timeout 60000 pull "Big Project"` for slow connections

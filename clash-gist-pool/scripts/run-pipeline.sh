#!/usr/bin/env bash
# Scheduled headless pipeline: sync sources -> CA-TLS filter -> local delay test -> publish nodes.yaml.
# Required: GIST_ID (or an existing <out>/publish.json) and a Mihomo core.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${GIST_POOL_OUT:-$HOME/gist-pool}"
CORE="${MIHOMO_BIN:-$(command -v mihomo || command -v verge-mihomo || true)}"

if [[ -z "$CORE" ]]; then
  echo "mihomo core not found. Run: bash '$SKILL_DIR/scripts/install-mihomo.sh'" >&2
  echo "then set MIHOMO_BIN or add ~/.local/bin to PATH." >&2
  exit 1
fi
export MIHOMO_BIN="$CORE"

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  ENV_FILE="${GITHUB_ENV_FILE:-$HOME/.agents/skills/github-account/.env}"
  if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
  fi
fi

if [[ -z "${GIST_ID:-}" && ! -f "$OUT/publish.json" ]]; then
  echo "set GIST_ID (the secret Gist to update) or copy publish.json into $OUT" >&2
  exit 1
fi

ARGS=(--out "$OUT" --exclude-insecure --ca-tls --publish)
if [[ "${DISCOVER:-0}" == "1" ]]; then
  ARGS+=(--discover --add)
fi
if [[ -n "${CONCURRENCY:-}" ]]; then ARGS+=(--concurrency "$CONCURRENCY"); fi
if [[ -n "${TIMEOUT:-}" ]]; then ARGS+=(--timeout "$TIMEOUT"); fi
if [[ -n "${MAX_DELAY:-}" ]]; then ARGS+=(--max-delay "$MAX_DELAY"); fi

mkdir -p "$OUT"
exec "${NODE_BIN:-node}" "$SKILL_DIR/scripts/clash-gist-pool.mjs" pipeline "${ARGS[@]}" "$@"

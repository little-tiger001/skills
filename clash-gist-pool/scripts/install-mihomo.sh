#!/usr/bin/env bash
# Install a standalone Mihomo core without a GUI.
# MIHOMO_VERSION=v1.19.32 by default; override for a newer release.
set -euo pipefail

VERSION="${MIHOMO_VERSION:-v1.19.32}"
DEST="${MIHOMO_INSTALL_DIR:-$HOME/.local/bin}"
case "$(uname -m)" in
  x86_64|amd64) ARCH=amd64 ;;
  aarch64|arm64) ARCH=arm64 ;;
  *) echo "unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

mkdir -p "$DEST"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

try_asset() {
  local name="$1"
  local url="https://github.com/MetaCubeX/mihomo/releases/download/${VERSION}/${name}"
  echo "trying ${url}"
  if curl -fL --retry 3 --connect-timeout 15 --max-time 180 -o "$TMP/mihomo.gz" "$url"; then
    gzip -dc "$TMP/mihomo.gz" > "$TMP/mihomo"
    chmod +x "$TMP/mihomo"
    mv "$TMP/mihomo" "$DEST/mihomo"
    return 0
  fi
  return 1
}

try_asset "mihomo-linux-${ARCH}-${VERSION}.gz" || \
try_asset "mihomo-linux-${ARCH}-compatible-${VERSION}.gz" || {
  echo "download failed. Set MIHOMO_VERSION to a valid release and retry." >&2
  exit 1
}

"$DEST/mihomo" -v
echo
echo "installed: $DEST/mihomo"
echo "add to PATH: export PATH=\"$DEST:\$PATH\""
echo "or set: export MIHOMO_BIN=\"$DEST/mihomo\""

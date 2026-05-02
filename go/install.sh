#!/bin/sh
# rekipedia installer — downloads the latest release binary
# Usage: curl -fsSL https://github.com/unrealandychan/rekipedia/releases/latest/download/install.sh | sh
set -e

REPO="unrealandychan/rekipedia"
BIN="reki"
INSTALL_DIR="${INSTALL_DIR:-/usr/local/bin}"

# Detect OS
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
case "$OS" in
  linux) ;;
  darwin) ;;
  *) echo "Unsupported OS: $OS" && exit 1 ;;
esac

# Detect architecture
ARCH=$(uname -m)
case "$ARCH" in
  x86_64)  ARCH="amd64" ;;
  aarch64) ARCH="arm64" ;;
  arm64)   ARCH="arm64" ;;
  *)       echo "Unsupported arch: $ARCH" && exit 1 ;;
esac

# Get latest version
VERSION=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
  | grep '"tag_name"' | cut -d'"' -f4)

if [ -z "$VERSION" ]; then
  echo "Error: could not determine latest version" && exit 1
fi

ARCHIVE="${BIN}_${VERSION#v}_${OS}_${ARCH}.tar.gz"
URL="https://github.com/${REPO}/releases/download/${VERSION}/${ARCHIVE}"

echo "→ Installing rekipedia ${VERSION} (${OS}/${ARCH})..."

TMP=$(mktemp -d)
trap "rm -rf $TMP" EXIT

curl -fsSL "$URL" | tar -xzC "$TMP"
chmod +x "$TMP/$BIN"

# Install (prefer sudo if not root)
if [ "$(id -u)" = "0" ]; then
  mv "$TMP/$BIN" "$INSTALL_DIR/$BIN"
elif command -v sudo > /dev/null 2>&1; then
  sudo mv "$TMP/$BIN" "$INSTALL_DIR/$BIN"
else
  echo "Cannot install to $INSTALL_DIR — try: INSTALL_DIR=~/.local/bin $0"
  exit 1
fi

echo "✓ rekipedia  installed to ${INSTALL_DIR}/${BIN}"
echo "  Run: reki --help"

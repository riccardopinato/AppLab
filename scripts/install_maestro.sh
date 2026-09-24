#!/usr/bin/env bash
set -Eeuo pipefail

MAESTRO_BIN_DIR="$HOME/.maestro/bin"
MAESTRO_VERSION="${MAESTRO_VERSION:-2.10.0}"
export MAESTRO_CLI_NO_ANALYTICS=1
export MAESTRO_VERSION

persist_path() {
  if [[ -n "${GITHUB_PATH:-}" ]]; then
    printf '%s\n' "$MAESTRO_BIN_DIR" >> "$GITHUB_PATH"
  fi
}

if command -v maestro >/dev/null 2>&1; then
  CURRENT="$(maestro --version 2>/dev/null || true)"
  if [[ "$CURRENT" == *"$MAESTRO_VERSION"* ]]; then
    echo "[AppLab] Maestro already pinned: $CURRENT"
    persist_path
    exit 0
  fi
  echo "[AppLab] replacing Maestro '$CURRENT' with pinned $MAESTRO_VERSION"
  rm -rf "$HOME/.maestro"
fi

command -v java >/dev/null 2>&1 || {
  echo "[AppLab] ERROR: Java 17+ is required by Maestro." >&2
  exit 1
}

echo "[AppLab] installing pinned Maestro $MAESTRO_VERSION..."
curl --fail --silent --show-error --location "https://get.maestro.mobile.dev" | bash
export PATH="$MAESTRO_BIN_DIR:$PATH"
persist_path

command -v maestro >/dev/null 2>&1 || {
  echo "[AppLab] ERROR: Maestro binary not found after installation." >&2
  exit 1
}

INSTALLED="$(maestro --version)"
echo "[AppLab] Maestro installed: $INSTALLED"
[[ "$INSTALLED" == *"$MAESTRO_VERSION"* ]] || {
  echo "[AppLab] ERROR: expected Maestro $MAESTRO_VERSION." >&2
  exit 1
}

#!/usr/bin/env bash
set -Eeuo pipefail

MAESTRO_BIN_DIR="$HOME/.maestro/bin"

persist_path() {
  if [[ -n "${GITHUB_PATH:-}" ]]; then
    printf '%s\n' "$MAESTRO_BIN_DIR" >> "$GITHUB_PATH"
  fi
}

if command -v maestro >/dev/null 2>&1; then
  echo "[AppLab] Maestro already installed: $(maestro --version || true)"
  persist_path
  exit 0
fi

command -v java >/dev/null 2>&1 || {
  echo "[AppLab] ERROR: Java 17+ is required by Maestro." >&2
  exit 1
}

echo "[AppLab] installing Maestro..."
curl -fsSL "https://get.maestro.mobile.dev" | bash
export PATH="$MAESTRO_BIN_DIR:$PATH"
persist_path

command -v maestro >/dev/null 2>&1 || {
  echo "[AppLab] ERROR: Maestro binary not found after installation." >&2
  exit 1
}

maestro --version

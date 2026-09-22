#!/usr/bin/env bash
set -Eeuo pipefail

if command -v maestro >/dev/null 2>&1; then
  echo "[AppLab] Maestro already installed: $(maestro --version || true)"
  exit 0
fi

command -v java >/dev/null 2>&1 || {
  echo "[AppLab] ERROR: Java 17+ is required by Maestro." >&2
  exit 1
}

echo "[AppLab] installing Maestro..."
curl -fsSL "https://get.maestro.mobile.dev" | bash
export PATH="$PATH:$HOME/.maestro/bin"
command -v maestro >/dev/null 2>&1 || {
  echo "[AppLab] ERROR: Maestro binary not found after installation." >&2
  exit 1
}
maestro --version

#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "[AppLab] FAIL: $*" >&2
  exit 1
}

[[ "$(uname -s)" == "Linux" ]] || fail "Live Emulator requires Linux."
command -v docker >/dev/null 2>&1 || fail "Docker Engine is not installed."
docker info >/dev/null 2>&1 || fail "Docker Engine is not reachable."
[[ -e /dev/kvm ]] || fail "/dev/kvm is missing. Enable KVM/nested virtualization."
[[ -r /dev/kvm && -w /dev/kvm ]] || fail "/dev/kvm is not readable/writable by the current user."

echo "[AppLab] Linux: OK"
echo "[AppLab] Docker: OK"
echo "[AppLab] KVM: OK"
echo "[AppLab] Host ready for AppLab Live Emulator."

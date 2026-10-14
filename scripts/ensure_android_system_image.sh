#!/usr/bin/env bash
set -Eeuo pipefail

API_LEVEL="${APPLAB_ANDROID_API_LEVEL:-${1:-}}"
TARGET="${APPLAB_ANDROID_TARGET:-google_apis}"
ARCH="${APPLAB_ANDROID_ARCH:-x86_64}"
CHANNEL="${APPLAB_ANDROID_CHANNEL:-0}"
SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"

if [[ -z "$API_LEVEL" ]]; then
  echo "APPLAB_ANDROID_API_LEVEL (or positional API level) is required." >&2
  exit 2
fi
if [[ -z "$SDK_ROOT" ]]; then
  echo "ANDROID_SDK_ROOT or ANDROID_HOME is required." >&2
  exit 2
fi
if ! command -v sdkmanager >/dev/null 2>&1; then
  echo "sdkmanager is required." >&2
  exit 2
fi

PACKAGE="system-images;android-${API_LEVEL};${TARGET};${ARCH}"
IMAGE_DIR="$SDK_ROOT/system-images/android-${API_LEVEL}/${TARGET}/${ARCH}"

# android-emulator-runner invokes sdkmanager even when an AVD snapshot is cached.
# Preinstall the image here so transient/corrupt archive downloads can be retried
# deterministically before the trusted runtime step starts.
if [[ -f "$IMAGE_DIR/source.properties" ]]; then
  echo "Android system image already present: $PACKAGE"
  exit 0
fi

yes | sdkmanager --licenses >/dev/null 2>&1 || true

for attempt in 1 2 3; do
  echo "Installing Android system image: $PACKAGE (attempt $attempt/3)"
  if sdkmanager --install "$PACKAGE" --channel="$CHANNEL"; then
    if [[ -f "$IMAGE_DIR/source.properties" ]]; then
      echo "Android system image ready: $PACKAGE"
      exit 0
    fi
    echo "sdkmanager returned success but source.properties is missing." >&2
  else
    echo "sdkmanager failed for $PACKAGE on attempt $attempt." >&2
  fi

  # A failed sdkmanager download can leave an invalid partial image/archive.
  # Remove only the target image and download caches before retrying.
  rm -rf "$IMAGE_DIR"
  rm -rf "$HOME/.android/cache"
  rm -rf "$SDK_ROOT/temp" "$SDK_ROOT/.temp"
  mkdir -p "$HOME/.android/cache"

  if [[ "$attempt" -lt 3 ]]; then
    sleep $((attempt * 5))
  fi
done

echo "Unable to prepare Android system image after 3 attempts: $PACKAGE" >&2
exit 1

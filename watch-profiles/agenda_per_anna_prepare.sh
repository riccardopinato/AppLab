#!/usr/bin/env bash
set -Eeuo pipefail

test -f pubspec.yaml
test -f pubspec.lock
test -f tool/prepare_android_platform.py

SCAFFOLD_ROOT="${RUNNER_TEMP:-/tmp}/agenda_per_anna_applab_scaffold"
rm -rf android "$SCAFFOLD_ROOT"

flutter create \
  --project-name agenda_per_anna \
  --org com.riccardopinato \
  --platforms=android \
  "$SCAFFOLD_ROOT"

cp -R "$SCAFFOLD_ROOT/android" .
python3 tool/prepare_android_platform.py

test -f android/app/build.gradle.kts
test -f android/app/src/main/AndroidManifest.xml

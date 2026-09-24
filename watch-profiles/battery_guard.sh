#!/usr/bin/env bash
set -Eeuo pipefail

rm -rf /tmp/battery_guard_scaffold
flutter create \
  --platforms=android \
  --org com.riccardopinato \
  --project-name battery_guard \
  /tmp/battery_guard_scaffold

cp /tmp/battery_guard_scaffold/android/gradlew android/gradlew
cp /tmp/battery_guard_scaffold/android/gradlew.bat android/gradlew.bat
mkdir -p android/gradle/wrapper
cp /tmp/battery_guard_scaffold/android/gradle/wrapper/gradle-wrapper.jar android/gradle/wrapper/gradle-wrapper.jar
cp /tmp/battery_guard_scaffold/android/gradle/wrapper/gradle-wrapper.properties android/gradle/wrapper/gradle-wrapper.properties

if [[ ! -f .metadata ]]; then
  cp /tmp/battery_guard_scaffold/.metadata .metadata
fi

chmod +x android/gradlew

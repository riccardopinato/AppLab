#!/usr/bin/env bash
set -Eeuo pipefail

test -f tool/flutter_launcher_icons_android.yaml
dart run flutter_launcher_icons -f tool/flutter_launcher_icons_android.yaml

test -d android/app/src/main/res

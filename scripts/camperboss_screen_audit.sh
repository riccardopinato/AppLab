#!/usr/bin/env bash
set -Eeuo pipefail

PKG="com.camperboss.camperboss"
OUT="$GITHUB_WORKSPACE/audit-output/api-${API_LEVEL}"
mkdir -p "$OUT"

dump_ui() {
  adb shell uiautomator dump /sdcard/window.xml >/dev/null 2>&1 || true
  adb pull /sdcard/window.xml "$OUT/current.xml" >/dev/null 2>&1 || true
}

capture() {
  local name="$1"
  sleep 1.2
  adb exec-out screencap -p > "$OUT/${name}.png" || true
  adb shell uiautomator dump /sdcard/window.xml >/dev/null 2>&1 || true
  adb pull /sdcard/window.xml "$OUT/${name}.xml" >/dev/null 2>&1 || true
  adb logcat -d -v time > "$OUT/${name}-logcat.txt" || true
}

find_center() {
  local needle="$1"
  dump_ui
  python3 - "$OUT/current.xml" "$needle" <<'PY'
import re, sys, xml.etree.ElementTree as ET
path, needle = sys.argv[1], sys.argv[2].casefold()
root = ET.parse(path).getroot()
nodes = list(root.iter("node"))
def score(node):
    text=(node.attrib.get("text","")+" "+node.attrib.get("content-desc","")).strip()
    hay=text.casefold()
    if needle not in hay:
        return None
    clickable=node.attrib.get("clickable")=="true"
    enabled=node.attrib.get("enabled")!="false"
    exact = hay.strip()==needle
    return (1 if enabled else 0, 1 if clickable else 0, 1 if exact else 0, -len(hay))
candidates=[(score(n),n) for n in nodes]
candidates=[x for x in candidates if x[0] is not None]
if not candidates:
    raise SystemExit(2)
candidates.sort(key=lambda x:x[0], reverse=True)
b=candidates[0][1].attrib.get("bounds","")
m=re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",b)
if not m:
    raise SystemExit(3)
x1,y1,x2,y2=map(int,m.groups())
print(f"{(x1+x2)//2} {(y1+y2)//2}")
PY
}

tap_label() {
  local label="$1"
  local tries="${2:-3}"
  local pos=""
  for ((i=0;i<tries;i++)); do
    if pos="$(find_center "$label" 2>/dev/null)"; then
      read -r x y <<<"$pos"
      adb shell input tap "$x" "$y"
      sleep 1.0
      return 0
    fi
    adb shell input swipe 720 2350 720 900 350 || true
    sleep 0.5
  done
  echo "MISSING TAP TARGET: $label" | tee -a "$OUT/findings.txt"
  return 1
}

wait_label() {
  local label="$1"
  local timeout="${2:-25}"
  for ((i=0;i<timeout;i++)); do
    if find_center "$label" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "MISSING EXPECTED UI: $label" | tee -a "$OUT/findings.txt"
  capture "failure-${label//[^a-zA-Z0-9]/_}"
  return 1
}

back() { adb shell input keyevent 4; sleep 1; }

adb install -r "$GITHUB_WORKSPACE/apk/app-debug.apk"
adb shell pm clear "$PKG" >/dev/null
adb logcat -c || true
adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null
wait_label "Camper cockpit" 35
capture "01-home-first-run"

tap_label "Camper"
wait_label "My camper"
capture "02-camper-hub"

tap_label "Vehicle profile"
wait_label "My vehicle"
capture "03-vehicle-profile-empty"
back

tap_label "Vehicle documents"
wait_label "Vehicle documents"
capture "04-documents-empty"
back

tap_label "Maintenance"
wait_label "Maintenance"
capture "05-maintenance-empty"
back

tap_label "Trips"
wait_label "Trips"
capture "06-trips-hub"

tap_label "Trip planner"
wait_label "Trip planner"
capture "07-trip-planner-empty"
back

tap_label "Checklists"
wait_label "Checklist"
capture "08-checklist-empty"
back

tap_label "Travel journal"
wait_label "Travel journal"
capture "09-journal-empty"
back

tap_label "Budget, fuel & bookings"
wait_label "Costs, budgets & bookings"
capture "10-finance-empty"
back

tap_label "GPX, memories & statistics"
capture "11-travel-history-empty"
back

tap_label "More"
wait_label "More"
capture "12-more-hub"

tap_label "Search"
wait_label "Search"
capture "13-search-empty"
back

tap_label "Offline content"
capture "14-offline-content"
back

tap_label "Backup & recovery"
capture "15-backup"
back

tap_label "Language"
capture "16-language"
back

# Guided onboarding: explicitly exercise both runtime permission requests.
tap_label "Guided setup"
wait_label "Language and country"
capture "17-setup-language"
tap_label "Continue"
capture "18-setup-vehicle"
tap_label "Continue"
capture "19-setup-location"
if tap_label "Explain and request" 1; then
  sleep 1
  capture "20-location-permission-dialog"
  # Android wording varies slightly across API levels.
  tap_label "While using the app" 1 || tap_label "Allow" 1 || true
fi
tap_label "Continue"
capture "21-setup-notifications"
if tap_label "Explain and request" 1; then
  sleep 1
  capture "22-notification-permission-dialog"
  tap_label "Allow" 1 || true
fi
tap_label "Continue"
capture "23-setup-guides"
tap_label "Continue"
capture "24-setup-checklist"
tap_label "Continue"
capture "25-setup-confirmation"
tap_label "Complete setup" 2 || tap_label "Complete configuration" 2 || true
sleep 2
capture "26-setup-complete-result"

# Return to top-level More and inspect reminders state after onboarding.
back || true
if ! find_center "More" >/dev/null 2>&1; then
  adb shell input keyevent 4 || true
fi
tap_label "More" 2 || true
tap_label "Notifications" 3 || true
capture "27-notification-settings"

# Map/POI surface.
back || true
tap_label "Map" 3 || true
wait_label "Smart map" 25 || true
capture "28-map"
tap_label "Offline contents" 3 || true
capture "29-map-offline-content"
back || true
capture "30-map-return"

# Final fatal/framework exception scan.
adb logcat -d -v time > "$OUT/final-logcat.txt" || true
grep -E "FATAL EXCEPTION|Unhandled Exception|Another exception was thrown|PlatformException|MissingPluginException|A RenderFlex overflowed" "$OUT/final-logcat.txt" > "$OUT/runtime-exceptions.txt" || true

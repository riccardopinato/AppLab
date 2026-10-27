#!/usr/bin/env bash
set -Eeuo pipefail

chmod +x scripts/*.sh
: "${SELFTEST_PROFILE:?SELFTEST_PROFILE is required}"
SELFTEST_PROFILE_REASON="${SELFTEST_PROFILE_REASON:-UNKNOWN}"
SELFTEST_SELECTED_LABS="${SELFTEST_SELECTED_LABS:-}"
SELFTEST_UNITS="${SELFTEST_UNITS:-}"
export SELFTEST_SELECTED_LABS SELFTEST_UNITS
echo "AppLab v6.0G self-test profile: $SELFTEST_PROFILE ($SELFTEST_PROFILE_REASON)"
echo "AppLab v6.0G selected units: $SELFTEST_UNITS"

if [[ "$SELFTEST_PROFILE" == "FAST" ]]; then
  python - <<'PY'
import json
import os
from pathlib import Path

labs = [
    "system", "performance", "network", "persistence",
    "configuration", "resource_pressure", "background",
    "storage", "upgrade",
]
selected = {
    value.strip()
    for value in os.environ.get("SELFTEST_SELECTED_LABS", "").split(",")
    if value.strip()
}
unknown = sorted(selected - set(labs))
assert not unknown, unknown
payload = {
    "schema_version": 1,
    "planner_version": "v6.0G-selftest-1.1",
    "mode": "fast",
    "changed_files": [],
    "selected_labs": {name: name in selected for name in labs},
    "reasons": {
        name: (
            ["V60G_TARGETED_SELFTEST_UNIT"]
            if name in selected
            else ["V60G_UNSELECTED_SELFTEST_UNIT"]
        )
        for name in labs
    },
    "fallback_full": False,
}
Path("v60g-fast-plan.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
  RUN_MAESTRO=true \
    MAESTRO_FLOW="$GITHUB_WORKSPACE/tests/flows/selftest.yaml" \
    REPORT_DIR="$GITHUB_WORKSPACE/applab-report-fast" \
    APPLAB_TARGET_ROOT="$GITHUB_WORKSPACE" \
    APPLAB_PROJECT_ROOT="$GITHUB_WORKSPACE" \
    APPLAB_VERSION="5.3.5" \
    APPLAB_ANALYSIS_MODE="fast" \
    APPLAB_ANALYSIS_PLAN_JSON="$GITHUB_WORKSPACE/v60g-fast-plan.json" \
    ./scripts/verify_apk.sh \
      "$GITHUB_WORKSPACE/runtime-fixture/app-debug.apk" \
      "dev.applab.selftest"

  python - <<'PY'
import json
from pathlib import Path

import os

root = Path("applab-report-fast")
result = json.loads((root / "result.json").read_text(encoding="utf-8"))
assert result["result"] == "PASS", result
assert result["analysis_mode"] == "fast", result
assert result["maestro"] == "PASS", result
selected = {
    value.strip()
    for value in os.environ.get("SELFTEST_SELECTED_LABS", "").split(",")
    if value.strip()
}
key_by_lab = {
    "system": "system_lab",
    "performance": "performance_lab",
    "network": "network_lab",
    "persistence": "persistence_lab",
    "configuration": "configuration_lab",
    "resource_pressure": "resource_pressure_lab",
    "background": "background_lab",
    "storage": "storage_lab",
    "upgrade": "upgrade_lab",
}
for lab, key in key_by_lab.items():
    status = result[key]
    if lab in selected:
        allowed = {"PASS"} if lab == "system" else {"PASS", "WARN"}
        assert status in allowed, (lab, status, result)
    else:
        assert status in {"SKIPPED", "NO_BASELINE"}, (lab, status, result)
assert (root / "launch.png").stat().st_size > 0
assert (root / "post-maestro.png").stat().st_size > 0
assert (root / "logcat.txt").stat().st_size > 0
xml = (root / "post-maestro-window.xml").read_text(
    encoding="utf-8", errors="ignore"
)
assert "INTERACTION_OK" in xml, xml[:1000]
PY
  exit 0
fi

test "$SELFTEST_PROFILE" = "FULL"
RUN_MAESTRO=true MAESTRO_FLOW="$GITHUB_WORKSPACE/tests/flows/selftest.yaml" REPORT_DIR="$GITHUB_WORKSPACE/applab-report" APPLAB_TARGET_ROOT="$GITHUB_WORKSPACE" APPLAB_PROJECT_ROOT="$GITHUB_WORKSPACE" APPLAB_UPGRADE_BASELINE_APK="$GITHUB_WORKSPACE/runtime-fixture/app-debug.apk" APPLAB_VERSION="5.3.5" ./scripts/verify_apk.sh "$GITHUB_WORKSPACE/runtime-fixture/app-debug.apk" "dev.applab.selftest"
grep -Fq -- "- Result: PASS" "$GITHUB_WORKSPACE/applab-report/summary.md"
grep -Fq -- "- Maestro: PASS" "$GITHUB_WORKSPACE/applab-report/summary.md"
grep -Fq "dev.applab.selftest" "$GITHUB_WORKSPACE/applab-report/activity.txt"
grep -Fq "INTERACTION_OK" "$GITHUB_WORKSPACE/applab-report/post-maestro-window.xml"
test -s "$GITHUB_WORKSPACE/applab-report/launch.png"
test -s "$GITHUB_WORKSPACE/applab-report/post-maestro.png"
test -s "$GITHUB_WORKSPACE/applab-report/logcat.txt"
python -c 'import json,pathlib; report=json.loads(pathlib.Path("applab-report/visual-journey.json").read_text()); names={item["name"] for item in report["checkpoints"]}; assert {"launch","final","settings","dialog"} <= names, names; assert report["checkpoint_count"] >= 4, report; assert report["visual_qa"] == "PASS", report'
python -c 'import json,pathlib; report=json.loads(pathlib.Path("applab-report/system-lab.json").read_text()); assert report["result"] == "PASS", report; assert report["process_restart"]["restart_success"], report; assert report["deep_links"][0]["success"], report; assert any(x["permission"] == "android.permission.POST_NOTIFICATIONS" and x["success"] for x in report["permission_actions"]), report'
python -c 'import json,pathlib; report=json.loads(pathlib.Path("applab-report/network-lab.json").read_text()); assert report["result"] in {"PASS","WARN"}, report; assert report["package_id"] == "dev.applab.selftest", report'
test -s "$GITHUB_WORKSPACE/applab-report/network-offline.png"
test -s "$GITHUB_WORKSPACE/applab-report/network-recovered.png"
python -c 'import json,pathlib; report=json.loads(pathlib.Path("applab-report/persistence-lab.json").read_text()); assert report["result"] in {"PASS","WARN"}, report; assert len(report["cycles"]) >= 1, report; assert all(x["pid_after_relaunch"] for x in report["cycles"]), report'
test -s "$GITHUB_WORKSPACE/applab-report/persistence-cycle-1.png"
python -c 'import json,pathlib; report=json.loads(pathlib.Path("applab-report/configuration-lab.json").read_text()); assert report["result"] in {"PASS","WARN"}, report; assert len(report["stages"]) >= 2, report; assert all(x["pid"] for x in report["stages"]), report'
test -s "$GITHUB_WORKSPACE/applab-report/config-portrait-1.png"
test -s "$GITHUB_WORKSPACE/applab-report/config-foreground-1.png"
python -c 'import json,pathlib; report=json.loads(pathlib.Path("applab-report/resource-pressure-lab.json").read_text()); assert report["result"] in {"PASS","WARN"}, report; assert len(report["trim_actions"]) >= 1, report; assert len(report["process_death"]) >= 1, report; assert all(x["pid_after_recovery"] for x in report["process_death"]), report'
test -s "$GITHUB_WORKSPACE/applab-report/resource-recovery-1.png"
python -c 'import json,pathlib; report=json.loads(pathlib.Path("applab-report/background-lab.json").read_text()); assert report["result"] in {"PASS","WARN"}, report; assert len(report["cycles"]) >= 1, report; assert all(x["recovery"]["pid"] for x in report["cycles"]), report'
test -s "$GITHUB_WORKSPACE/applab-report/background-recovery-1.png"
python -c 'import json,pathlib; report=json.loads(pathlib.Path("applab-report/storage-lab.json").read_text()); assert report["result"] in {"PASS","WARN"}, report; assert report["recovered_pid"], report; assert report["disk_before"]["free_mb"] is None or report["disk_before"]["free_mb"] >= 0, report'
test -s "$GITHUB_WORKSPACE/applab-report/storage-recovery.png"
python -c 'import json,pathlib; report=json.loads(pathlib.Path("applab-report/upgrade-lab.json").read_text()); assert report["result"] in {"PASS","WARN"}, report; assert report["upgrade"]["in_place_install_succeeded"], report; assert report["upgrade"]["current_pid"], report'
test -s "$GITHUB_WORKSPACE/applab-report/upgrade-before.png"
test -s "$GITHUB_WORKSPACE/applab-report/upgrade-after.png"

RUN_MAESTRO=false REPORT_DIR="$GITHUB_WORKSPACE/applab-report-no-maestro" APPLAB_TARGET_ROOT="$GITHUB_WORKSPACE" APPLAB_PROJECT_ROOT="$GITHUB_WORKSPACE" APPLAB_UPGRADE_BASELINE_APK="$GITHUB_WORKSPACE/runtime-fixture/app-debug.apk" APPLAB_VERSION="5.3.5" ./scripts/verify_apk.sh "$GITHUB_WORKSPACE/runtime-fixture/app-debug.apk" "dev.applab.selftest"
python -c 'import json,pathlib; report=json.loads(pathlib.Path("applab-report-no-maestro/result.json").read_text()); journey=json.loads(pathlib.Path("applab-report-no-maestro/visual-journey.json").read_text()); system=json.loads(pathlib.Path("applab-report-no-maestro/system-lab.json").read_text()); network=json.loads(pathlib.Path("applab-report-no-maestro/network-lab.json").read_text()); persistence=json.loads(pathlib.Path("applab-report-no-maestro/persistence-lab.json").read_text()); configuration=json.loads(pathlib.Path("applab-report-no-maestro/configuration-lab.json").read_text()); resource=json.loads(pathlib.Path("applab-report-no-maestro/resource-pressure-lab.json").read_text()); background=json.loads(pathlib.Path("applab-report-no-maestro/background-lab.json").read_text()); storage=json.loads(pathlib.Path("applab-report-no-maestro/storage-lab.json").read_text()); upgrade=json.loads(pathlib.Path("applab-report-no-maestro/upgrade-lab.json").read_text()); assert report["result"] == "PASS", report; assert report["maestro"] == "SKIPPED", report; assert report["network_lab"] in {"PASS","WARN"}, report; assert report["persistence_lab"] in {"PASS","WARN"}, report; assert report["configuration_lab"] in {"PASS","WARN"}, report; assert configuration["result"] in {"PASS","WARN"}, configuration; assert report["resource_pressure_lab"] in {"PASS","WARN"}, report; assert resource["result"] in {"PASS","WARN"}, resource; assert report["background_lab"] in {"PASS","WARN"}, report; assert background["result"] in {"PASS","WARN"}, background; assert report["storage_lab"] in {"PASS","WARN"}, report; assert storage["result"] in {"PASS","WARN"}, storage; assert report["upgrade_lab"] in {"PASS","WARN"}, report; assert persistence["result"] in {"PASS","WARN"}, persistence; assert upgrade["result"] in {"PASS","WARN"}, upgrade; assert journey["checkpoint_count"] == 2, journey; assert {x["name"] for x in journey["checkpoints"]} == {"launch","final"}, journey; assert system["result"] == "PASS", system; assert network["result"] in {"PASS","WARN"}, network'

python -c 'import json,pathlib; labs=["system","performance","network","persistence","configuration","resource_pressure","background","storage","upgrade"]; payload={"schema_version":1,"planner_version":"0.8.0","mode":"fast","changed_files":["README.md"],"selected_labs":{k:False for k in labs},"reasons":{k:[] for k in labs},"fallback_full":False}; pathlib.Path("fast-plan.json").write_text(json.dumps(payload, indent=2)+"\n", encoding="utf-8")'
RUN_MAESTRO=false REPORT_DIR="$GITHUB_WORKSPACE/applab-report-fast" APPLAB_TARGET_ROOT="$GITHUB_WORKSPACE" APPLAB_PROJECT_ROOT="$GITHUB_WORKSPACE" APPLAB_VERSION="5.3.5" APPLAB_ANALYSIS_MODE="fast" APPLAB_ANALYSIS_PLAN_JSON="$GITHUB_WORKSPACE/fast-plan.json" ./scripts/verify_apk.sh "$GITHUB_WORKSPACE/runtime-fixture/app-debug.apk" "dev.applab.selftest"
python -c 'import json,pathlib; r=json.loads(pathlib.Path("applab-report-fast/result.json").read_text()); assert r["result"] == "PASS", r; keys=["system_lab","performance_lab","network_lab","persistence_lab","configuration_lab","resource_pressure_lab","background_lab","storage_lab","upgrade_lab"]; assert all(r[k] in {"SKIPPED","NO_BASELINE"} for k in keys), r'
python -c 'import json,pathlib; r=json.loads(pathlib.Path("applab-report-fast/result.json").read_text()); assert r["analysis_mode"] == "fast", r'

rm -rf "$GITHUB_WORKSPACE/applab-report-certification" "$GITHUB_WORKSPACE/certification-contract"
cp -R "$GITHUB_WORKSPACE/applab-report" "$GITHUB_WORKSPACE/applab-report-certification"
mkdir -p "$GITHUB_WORKSPACE/certification-contract"
cp "$GITHUB_WORKSPACE/runtime-fixture/app-debug.apk" "$GITHUB_WORKSPACE/certification-contract/app.apk"
python -c 'import hashlib,json,pathlib; rp=pathlib.Path("applab-report-certification/result.json"); r=json.loads(rp.read_text(encoding="utf-8")); r["analysis_mode"]="certification"; rp.write_text(json.dumps(r,indent=2,sort_keys=True),encoding="utf-8"); apk=pathlib.Path("certification-contract/app.apk"); digest=hashlib.sha256(apk.read_bytes()).hexdigest(); pathlib.Path("certification-contract/contract.json").write_text(json.dumps({"schema_version":1,"analysis_mode":"certification","apk":{"sha256":digest}},indent=2,sort_keys=True),encoding="utf-8")'
python -c 'import json,pathlib,subprocess,sys; p=subprocess.run([sys.executable,"scripts/certification_gate.py","--report-dir","applab-report-certification","--contract-root","certification-contract","--api-level","35","--emulator-profile","pixel_7_pro"],check=False); c=json.loads(pathlib.Path("applab-report-certification/certification.json").read_text()); assert c["status"] in {"CERTIFIED","BLOCKED"}, c; assert c["status"] != "NOT_CERTIFIED", c; assert (c["status"]=="CERTIFIED" and p.returncode==0) or (c["status"]=="BLOCKED" and p.returncode!=0), (c,p.returncode)'


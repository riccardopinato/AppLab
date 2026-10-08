#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_BRIEF_ANDROID_RUNTIME = re.compile(
    r"^[VDIWEF]/AndroidRuntime(?:\(\s*(\d+)\))?:\s*(.*)$"
)
_THREADTIME_ANDROID_RUNTIME = re.compile(
    r"^\S+\s+\S+\s+(\d+)\s+\d+\s+[VDIWEF]\s+AndroidRuntime:\s*(.*)$"
)
_PROCESS_LINE = re.compile(
    r"^Process:\s*([^,\s]+)(?:,\s*PID:\s*(\d+))?"
)
_ANR_LINE = re.compile(r"\bANR in\s+([^,\s]+)")


def _is_target_process(process_name: str, package_id: str) -> bool:
    return process_name == package_id or process_name.startswith(package_id + ":")



def _android_runtime_entry(line: str) -> tuple[str | None, str] | None:
    match = _BRIEF_ANDROID_RUNTIME.match(line.strip())
    if match:
        return match.group(1), match.group(2)
    match = _THREADTIME_ANDROID_RUNTIME.match(line.strip())
    if match:
        return match.group(1), match.group(2)
    return None


def target_crash_state(
    logcat: str,
    package_id: str,
) -> tuple[str, list[str]]:
    """Return a target-scoped Android runtime failure and exact evidence lines."""
    lines = logcat.splitlines()

    for index, line in enumerate(lines):
        anr = _ANR_LINE.search(line)
        if anr and _is_target_process(anr.group(1), package_id):
            return "ANR detected", lines[max(0, index - 2) : index + 4]

    entries = [_android_runtime_entry(line) for line in lines]
    for index, entry in enumerate(entries):
        if entry is None:
            continue
        emitter_pid, message = entry
        if not message.startswith("FATAL EXCEPTION:"):
            continue

        evidence = [lines[index]]
        for detail_index in range(index + 1, min(len(lines), index + 24)):
            detail_entry = entries[detail_index]
            if detail_entry is None:
                continue

            detail_pid, detail_message = detail_entry
            if detail_message.startswith("FATAL EXCEPTION:"):
                # Another AndroidRuntime crash record started before this record
                # identified its process. Do not cross-associate the two.
                if emitter_pid is None or detail_pid == emitter_pid:
                    break
                continue

            # With real logcat output, AndroidRuntime's emitter PID is the
            # strongest record boundary. Ignore interleaved runtime lines from
            # other processes.
            if (
                emitter_pid is not None
                and detail_pid is not None
                and detail_pid != emitter_pid
            ):
                continue

            evidence.append(lines[detail_index])
            process = _PROCESS_LINE.match(detail_message)
            if process is None:
                continue

            process_name = process.group(1)
            process_pid = process.group(2)
            if not _is_target_process(process_name, package_id):
                break

            if (
                emitter_pid is not None
                and process_pid is not None
                and emitter_pid != process_pid
            ):
                # A Process line whose declared PID disagrees with the runtime
                # emitter cannot belong to this fatal record.
                break

            return "fatal exception detected", evidence

    return "", []


def self_test() -> None:
    package = "com.riccardopinato.trail_path"

    foreign = """E/AndroidRuntime( 1200): FATAL EXCEPTION: main
E/AndroidRuntime( 1200): Process: com.google.android.apps.nexuslauncher, PID: 1200
E/AndroidRuntime( 1200): java.lang.RuntimeException: launcher failure
I/ActivityManager(  700): Process: com.riccardopinato.trail_path state changed
"""
    assert target_crash_state(foreign, package) == ("", [])

    interleaved = """E/AndroidRuntime( 1200): FATAL EXCEPTION: main
E/AndroidRuntime( 2200): Process: com.riccardopinato.trail_path, PID: 2200
E/AndroidRuntime( 1200): Process: com.google.android.apps.nexuslauncher, PID: 1200
"""
    assert target_crash_state(interleaved, package) == ("", [])

    target = """E/AndroidRuntime( 2200): FATAL EXCEPTION: main
E/AndroidRuntime( 2200): Process: com.riccardopinato.trail_path, PID: 2200
E/AndroidRuntime( 2200): java.lang.RuntimeException: target failure
"""
    reason, evidence = target_crash_state(target, package)
    assert reason == "fatal exception detected"
    assert any("Process: com.riccardopinato.trail_path" in line for line in evidence)

    threadtime = """10-06 15:21:10.000  2200  2200 E AndroidRuntime: FATAL EXCEPTION: main
10-06 15:21:10.001  2200  2200 E AndroidRuntime: Process: com.riccardopinato.trail_path, PID: 2200
"""
    assert target_crash_state(threadtime, package)[0] == "fatal exception detected"

    subprocess_fatal = """E/AndroidRuntime( 3300): FATAL EXCEPTION: worker
E/AndroidRuntime( 3300): Process: com.riccardopinato.trail_path:worker, PID: 3300
E/AndroidRuntime( 3300): java.lang.RuntimeException: worker failure
"""
    assert target_crash_state(subprocess_fatal, package)[0] == "fatal exception detected"

    neighbor = """E/AndroidRuntime( 4400): FATAL EXCEPTION: main
E/AndroidRuntime( 4400): Process: com.riccardopinato.trail_path_extra, PID: 4400
"""
    assert target_crash_state(neighbor, package) == ("", [])

    anr = "E/ActivityManager( 700): ANR in com.riccardopinato.trail_path\n"
    assert target_crash_state(anr, package)[0] == "ANR detected"
    subprocess_anr = "E/ActivityManager( 700): ANR in com.riccardopinato.trail_path:worker\n"
    assert target_crash_state(subprocess_anr, package)[0] == "ANR detected"

    print("AppLab target-scoped Android runtime health self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-id")
    parser.add_argument("--logcat-file")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.package_id or not args.logcat_file:
        raise SystemExit("--package-id and --logcat-file are required")

    logcat = Path(args.logcat_file).read_text(
        encoding="utf-8",
        errors="replace",
    )
    reason, evidence = target_crash_state(logcat, args.package_id)
    print(
        json.dumps(
            {
                "crashed": bool(reason),
                "reason": reason,
                "evidence": evidence,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

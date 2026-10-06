from app.diagnostics import analyze_logcat


def test_clean_running_process_passes() -> None:
    result = analyze_logcat(
        "09-23 10:00:00.000 I/App: ready",
        package_id="com.example.app",
        running=True,
    )
    assert result["result"] == "PASS"
    assert result["issue_count"] == 0


def test_stopped_process_fails() -> None:
    result = analyze_logcat(
        "",
        package_id="com.example.app",
        running=False,
    )
    assert result["result"] == "FAIL"
    assert result["issues"][0]["code"] == "PROCESS_NOT_RUNNING"


def test_anr_and_flutter_exception_fail() -> None:
    result = analyze_logcat(
        "ANR in com.example.app\nUnhandled Exception: boom",
        package_id="com.example.app",
        running=True,
    )
    codes = {item["code"] for item in result["issues"]}
    assert result["result"] == "FAIL"
    assert "ANR" in codes
    assert "FLUTTER_EXCEPTION" in codes


def test_foreign_android_runtime_fatal_does_not_fail_target() -> None:
    result = analyze_logcat(
        """E/AndroidRuntime( 1200): FATAL EXCEPTION: main
E/AndroidRuntime( 1200): Process: com.google.android.apps.nexuslauncher, PID: 1200
E/AndroidRuntime( 1200): java.lang.RuntimeException: launcher failure
I/ActivityManager( 700): Process: com.example.app state changed
""",
        package_id="com.example.app",
        running=True,
    )
    assert result["result"] == "PASS"
    assert all(item["code"] != "FATAL_EXCEPTION" for item in result["issues"])


def test_interleaved_foreign_fatal_does_not_cross_attribute_target() -> None:
    result = analyze_logcat(
        """E/AndroidRuntime( 1200): FATAL EXCEPTION: main
E/AndroidRuntime( 2200): Process: com.example.app, PID: 2200
E/AndroidRuntime( 1200): Process: com.google.android.apps.nexuslauncher, PID: 1200
""",
        package_id="com.example.app",
        running=True,
    )
    assert result["result"] == "PASS"
    assert all(item["code"] != "FATAL_EXCEPTION" for item in result["issues"])


def test_target_android_runtime_fatal_fails() -> None:
    result = analyze_logcat(
        """E/AndroidRuntime( 2200): FATAL EXCEPTION: main
E/AndroidRuntime( 2200): Process: com.example.app, PID: 2200
E/AndroidRuntime( 2200): java.lang.RuntimeException: target failure
""",
        package_id="com.example.app",
        running=True,
    )
    codes = {item["code"] for item in result["issues"]}
    assert result["result"] == "FAIL"
    assert "FATAL_EXCEPTION" in codes

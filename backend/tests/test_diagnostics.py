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

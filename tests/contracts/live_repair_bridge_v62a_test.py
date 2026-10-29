#!/usr/bin/env python3
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import live_repair_intake_v62a as intake
import live_repair_attempt_v62a as attempt


def test_reject_untrusted_event() -> None:
    with patch.object(intake.subprocess, "check_output", return_value="a" * 40 + "\n"):
        params = (Path("."), Path("not-present.db"), {}, {}, {}, {}, "")
        try:
            intake.inspect_repair(*params)
        except intake.RepairAdmissionError as error:
            assert "EXACT_LIVE_ADMISSION_REQUIRED" in str(error)
        else:
            raise AssertionError("untrusted admission accepted")
        try:
            attempt.run(*params, Path("not-present.patch"))
        except intake.RepairAdmissionError:
            pass
        else:
            raise AssertionError("worker bypassed the admission guard")

def test_reject_publication_without_persisted_patch_hash() -> None:
    params = (Path("."), Path("not-present.db"), {}, {}, {}, {}, "",
              Path("not-present.patch"))
    try:
        attempt.run(*params, publish=True)
    except attempt.AttemptBlocked as error:
        assert "PUBLISHED_DRAFT_REQUIRES_APPROVED_PATCH_HASH" in str(error)
    else:
        raise AssertionError("draft publication accepted without exact patch hash")



if __name__ == "__main__":
    test_reject_untrusted_event()
    test_reject_publication_without_persisted_patch_hash()
    print("v6.2A real WorkItem rejection regression PASS")

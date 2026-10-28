#!/usr/bin/env python3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import self_canary_witness_v62a as mod  # noqa: E402


def test_witness_self_test() -> None:
    mod.self_test()


if __name__ == "__main__":
    test_witness_self_test()
    print("v6.2A contract regression PASS")

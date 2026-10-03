#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# These are growth ceilings, not quality scores. Crossing a ceiling requires
# extraction/refactor justification before more logic is added to the monolith.
LIMITS = {
    "scripts/app_intelligence.py": 1600,
    "scripts/studio_snapshot.py": 1300,
    "scripts/verify_apk.sh": 1150,
    "scripts/longitudinal_product_intelligence.py": 1050,
    "scripts/autonomous_app_review.py": 500,
}


def logical_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def main() -> int:
    failures: list[str] = []
    for relative, limit in LIMITS.items():
        path = ROOT / relative
        if not path.is_file():
            failures.append(f"missing tracked maintainability file: {relative}")
            continue
        lines = logical_lines(path)
        print(f"{relative}: {lines}/{limit} lines")
        if lines > limit:
            failures.append(
                f"{relative} exceeded maintainability growth ceiling: {lines} > {limit}"
            )
    if failures:
        raise SystemExit("\n".join(failures))
    print("AppLab maintainability growth budget PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

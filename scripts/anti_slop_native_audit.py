#!/usr/bin/env python3
"""Read-only, advisory Unslop U1-U20 triage for Flutter/Dart and Kotlin/Compose.

The MIT upstream 'unslop-ui' supports web sources, not native apps. This
independent, conservative adapter reports candidate patterns, NEVER edits code.
A raw count is not a quality score or CI failure without an explicit --max.
Some U rules are semantically/visually review-only and cannot be inferred here.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
import json
import re
from collections import Counter
from pathlib import Path

EXTENSIONS = {".dart", ".kt", ".kts", ".arb"}
SKIP_DIRS = {
    ".git", ".dart_tool", ".gradle", ".idea", "build", ".next",
    ".symlinks", "node_modules", "coverage", "Pods", "generated", "gen",
    "test", "androidTest", "integration_test", "__pycache__",
}
MAX_BYTES = 1_000_000
UPSTREAM_SHA = "cd891160453f26aaacc569bad96a8d10d595076d"
RULES = {
    "U1": ("AT-18", "AT-27", "AT-40"),
    "U2": ("AT-19", "AT-40"),
    "U3": ("AT-21", "AT-40"),
    "U6": ("AT-21", "AT-45", "AT-49"),
    "U8": ("AT-38", "AT-39"),
    "U9": ("AT-41", "AT-45", "AT-46"),
    "U11": ("AT-09", "AT-10", "AT-12"),
    "U12": ("AT-17", "AT-40", "AT-46"),
    "U17": ("AT-01", "AT-05", "AT-12", "AT-13"),
    "U19": ("AT-24", "AT-25", "AT-53"),
    "U20": ("AT-29", "AT-30", "AT-34", "AT-36", "AT-59"),
}
REVIEW_ONLY = ["U4", "U5", "U7", "U10", "U13", "U14", "U15", "U16", "U18"]
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF]")
STATIC_BADGE = re.compile(
    r"(?:Badge|Chip|AssistChip|OmniStatusPill)\s*\("
    r"(?:(?!\)\s*[,;]).){0,240}?"
    r"""(?:Text\s*\(\s*|text\s*[:=]\s*|label\s*[:=]\s*Text\s*\(\s*)["']"""
    r"""(?:LIVE|NEW|BETA|AI|PRO|HOT)["']""",
    re.S | re.I,
)
PATTERNS = {
    "U1": re.compile(r"\beyebrow\s*\.\s*(?:uppercase\s*\(\s*\)|toUpperCase\s*\(\s*\))", re.I),
    "U2": re.compile(r"""(?<![0-9])["']0[1-9]\s*(?://|[|§])"""),
    "U3": re.compile(r"\bText\s*\(\s*(?:text\s*[:=]\s*)?subtitle\b"),
    "U6": re.compile(r"""["'][^"'\n]*(?:·|•)[^"'\n]*(?:·|•)[^"'\n]*["']"""),
    "U8": re.compile(r"""["'][A-Z][a-z]{2,}\.\s+[A-Z][a-z]{2,}\.\s+[A-Z][a-z]{2,}\.?["']"""),
    "U12": re.compile(r"\b(?:bar|line|pie|scatter|donut|area)\s+(?:chart|graph)\s+(?:of|showing|for)\b", re.I),
    "U17": re.compile(r"\b(?:Brush\.(?:linearGradient|radialGradient)|LinearGradient\s*\(|RadialGradient\s*\(|BoxShadow\s*\()"),
    "U19": re.compile(r"\bFontWeight\.(?:w800|w900|ExtraBold|Black)\b"),
    "U20": re.compile(r"\b(?:rememberInfiniteTransition|infiniteRepeatable|repeatForever|AnimationController\([^)]*\)\s*\.\s*repeat)\s*\("),
}
SURFACE_RULES = {"U17", "U19", "U20"}


def source_files(targets: list[Path]):
    """Traverse predictable source files, without generated copies/test fixtures."""
    paths: set[Path] = set()
    for target in targets:
        if target.is_file() and target.suffix.lower() in EXTENSIONS:
            paths.add(target.resolve())
        elif target.is_dir():
            for path in target.rglob("*"):
                if (path.is_file() and path.suffix.lower() in EXTENSIONS
                        and not set(path.relative_to(target).parts[:-1]) & SKIP_DIRS):
                    paths.add(path.resolve())
    return sorted(paths)


def detect(text: str, surface: bool = False):
    """Return candidate spans, never a conclusive design defect."""
    findings = []
    for rule, pattern in PATTERNS.items():
        if rule in SURFACE_RULES and not surface:
            continue
        for match in pattern.finditer(text):
            findings.append((rule, match.start()))
    for match in STATIC_BADGE.finditer(text):
        findings.append(("U9", match.start()))
    # Search emoji in visible string literals, not comments/imports.
    for match in re.finditer(r"""(?:"[^"\n]*"|'[^'\n]*')""", text):
        if EMOJI.search(match.group()):
            findings.append(("U11", match.start()))
    return sorted(set(findings), key=lambda item: (item[1], item[0]))


def audit(targets: list[Path], surface: bool = False, source_sha: str = "") -> dict:
    findings = []
    total_files = 0
    skipped_files = 0
    # Keep stable, unambiguous target-relative paths without exposing host paths.
    roots = [(target.resolve(), target.is_file()) for target in targets]
    for path in source_files(targets):
        try:
            if path.stat().st_size > MAX_BYTES:
                skipped_files += 1
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            skipped_files += 1
            continue
        total_files += 1
        # Match the containing scan root, retaining nested paths and no absolute location.
        name = path.name
        for root, is_file in roots:
            parent = root.parent if is_file else root
            try:
                relative = path.relative_to(parent).as_posix()
            except ValueError:
                continue
            name = f"{root.name}/{relative}" if len(roots) > 1 else relative
            break
        # Avoid repeatedly splitting/copying and recounting for every candidate.
        lines = text.splitlines()
        line_ends = [i for i, ch in enumerate(text) if ch == "\n"]
        for rule, offset in detect(text, surface=surface):
            number = bisect_right(line_ends, offset) + 1
            excerpt = lines[number - 1].strip()[:160] if number <= len(lines) else ""
            findings.append({
                "path": name, "line": number, "rule": rule,
                "at": list(RULES[rule]), "confidence": "REVIEW_REQUIRED",
                "excerpt": excerpt,
            })
    findings.sort(key=lambda f: (f["path"], f["line"], f["rule"]))
    counts = Counter(f["rule"] for f in findings)
    return {
        "schema_version": 1,
        "status": "ADVISORY_NOT_CERTIFICATION",
        "source_sha": source_sha or None,
        "upstream": f"felipebasurto/unslop-ui@{UPSTREAM_SHA}",
        "platforms": ["Flutter/Dart", "Kotlin/Compose"],
        "surface_enabled": surface,
        "files_scanned": total_files, "files_skipped": skipped_files,
        "counts": dict(sorted(counts.items())), "total_candidates": len(findings),
        "manual_review_rules": REVIEW_ONLY,
        "findings": findings,
        "visual_review": "NOT_VERIFIED", "physical_review": "NOT_VERIFIED",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--surface", action="store_true", help="Review visual styling candidates")
    parser.add_argument("--source-sha", default="", help="Verified source commit SHA if known")
    parser.add_argument("--max", type=int, default=None, help="Optional, opt-in count threshold")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    args = parser.parse_args(argv)
    if args.max is not None and args.max < 0:
        parser.error("--max must be >= 0")
    report = audit(args.paths, args.surface, args.source_sha)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(f"Unslop native advisory: {report['total_candidates']} candidates across {report['files_scanned']} files")
        for row in report["findings"]:
            print(f"{row['path']}:{row['line']}: {row['rule']} => {','.join(row['at'])} [REVIEW] {row['excerpt']}")
        print("Not a visual/physical certification.")
    return int(args.max is not None and report["total_candidates"] > args.max)


if __name__ == "__main__":
    raise SystemExit(main())

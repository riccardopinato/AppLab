# AppLab Canonical Workflow Registry

This registry separates current workflow authority from filenames retained for
backward compatibility.

## Current canonical workflows

| Purpose | Canonical workflow | Authority |
| --- | --- | --- |
| Static + container CI | `.github/workflows/ci.yml` | Required engineering gate |
| Browser live-emulator E2E | `.github/workflows/live-emulator-self-test.yml` | Runtime UI gate |
| Android Emulator Self Test | `.github/workflows/emulator-self-test.yml` | Android runtime gate |
| True Autonomous Review | `.github/workflows/autonomous-app-review-v31.yml` | Current trusted evidence/review gate despite historical filename |
| Trusted APK verification | `.github/workflows/trusted-apk-verifier.yml` | Trusted runtime authority |
| Production certification | `.github/workflows/production-certification.yml` | Release certification authority |
| Universal target build/verify | `.github/workflows/universal-project-runner.yml` | Reusable build/verification entrypoint |

## Compatibility-only paths

### autonomous-app-review-v3.yml

This workflow is deliberately retained only for callers that still require
static/advisory product review. It is manual/reusable only, cannot consume
target-authored runtime evidence, and is **not** the current autonomous-review
authority.

### autonomous-app-review-v31.yml

The filename is retained because external repositories may already reference it.
Its display name, implementation and output are AppLab v4.0.2. New documentation
must call it **True Autonomous Review**, not “v3.1 workflow”, unless discussing
history.

## Naming policy

Historical filenames may remain when renaming would break external callers.
That compatibility must be explicit here. Display names, documentation, report
versions and authority statements must track the current platform version.

A compatibility filename is therefore not treated as uncontrolled legacy debt
when:
1. its current authority is unambiguous;
2. its triggers do not duplicate the canonical pipeline;
3. it is covered by current CI/security policy;
4. removal would create avoidable consumer breakage.

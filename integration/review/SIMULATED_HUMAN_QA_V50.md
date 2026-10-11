# AppLab v5.0.0 — Simulated Human QA

## Goal

Add a bounded human-like usability review layer on top of already-produced AppLab evidence.

The module does not impersonate real users and does not create a new release,
runtime, physical-device or certification authority. It converts trusted product
and runtime evidence into explicit simulated-user review sessions.

## Authority

- Record type: SIMULATED_HUMAN_QA
- Authority: APPLAB_SIMULATED_HUMAN_QA_ADVISORY
- Classification: SIMULATED USER REVIEW

The output is advisory evidence only.

It cannot:
- emit or promote CERTIFIED;
- override deterministic technical gates;
- claim REAL USER VALIDATION;
- claim PHYSICAL DEVICE EVIDENCE;
- emit FIX_NOW;
- convert missing evidence into a user failure.

## Identity and provenance

Every record is bound to the canonical Evidence Graph v2 identity and its exact
BuildArtifact root:

- repository;
- immutable resolved source SHA;
- trusted workflow run id;
- Android package id;
- APK SHA-256;
- version name;
- version code.

Malformed, stale or mismatched graph identity fails closed.

Source reports remain authoritative. The simulated layer references findings from:
- app-intelligence.json;
- user-journey.json;
- ux-friction.json;
- state-edge-case.json;
- evidence-confidence.json;
- evidence-graph.json.

## Canonical personas

v5.0 runs exactly seven bounded personas:

1. beginner
2. power_user
3. older_user
4. accessibility_focused
5. privacy_conscious
6. impatient
7. offline_user

Each persona has explicit goals, focus areas and evidence requirements. Personas
do not invent observations outside the source evidence.

## Task outcomes

Each bounded task produces one of:

- FRICTION_SIGNAL
- EVIDENCE_INCOMPLETE
- NO_STRONG_SIGNAL
- NOT_APPLICABLE

A cognitive walkthrough is emitted per task using evidence-backed criteria.

## Heuristic review

The module also evaluates bounded heuristic lenses including:
- visibility and feedback;
- clarity and match;
- user control and recovery;
- efficiency;
- error prevention/recovery;
- accessibility support.

These are review signals, not defect verdicts.

## Consensus and disagreements

Evidence-backed signals are evaluated across persona focus areas. Multi-persona
agreement is preserved together with non-supporting personas.

Allowed advisory routes are only:
- VERIFY_NEXT
- IMPROVE
- NO_ACTION

No simulated result can become FIX_NOW automatically.

## Determinism

The v5.0 core is deterministic and does not require an LLM. This prevents a
model-generated interpretation from changing deterministic QA or release gates.

Future model-assisted layers may consume the record, but must preserve the same
authority boundary and provenance.

## Studio

AppLab Studio reads simulated-human-qa.json through a dedicated fail-closed
projection. It validates:
- schema/version/authority/classification;
- canonical persona set;
- task outcomes and cognitive walkthrough presence;
- allowed advisory routes;
- guardrails;
- exact Evidence Graph / artifact identity;
- deterministic record digest;
- internally derived advisory state.

Malformed or stale records are projected as EVIDENCE_INCOMPLETE, never as green
simulated evidence.

## True Autonomous Review integration

The trusted review pipeline builds Simulated Human QA after Evidence Graph
generation and before release evidence aggregation. Its markdown report is
included in the GitHub step summary and its JSON record is packaged into
Studio-ready evidence.

## Validation

v5.0 is protected by:
- simulated_human_qa.py --self-test;
- studio_simulated_human.py self-test;
- audit contract invariants;
- workflow contract invariants;
- normal AppLab CI and frontend build;
- repository governance and CodeQL;
- Browser E2E, Emulator Self Test and True Autonomous Review runtime gates.

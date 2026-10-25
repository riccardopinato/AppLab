# AppLab v5.4D — Conductor Shadow Pilot

Status: **SHADOW IMPLEMENTED / ZERO DISPATCH CAPABILITY**

Reference: `conductor-oss/conductor@1488804170d159021c7e62dce61514b8f31ef9ff`.

The workflow definition follows the pinned Conductor WorkflowDef shape: workflow name/version, schemaVersion 2, restartable execution and ordered SIMPLE tasks with unique task references.

## Shadow DAG

```text
validate_identity
  -> consume_plan
  -> model_queue
  -> model_worker
  -> compare_actual
```

The pilot consumes copies of:

- normalized v5.4 Event metadata;
- the authoritative Smart Test Plan output;
- actual AppLab execution metadata;
- read-only worker inventory.

It does not create authoritative Operations or dispatch work.

## Comparison record

The terminal record is `APPLAB_CONDUCTOR_SHADOW_COMPARISON` with:

- `authority = NONE_SHADOW_ONLY`;
- exact workflow version/digest;
- pinned Conductor reference SHA;
- repository/SHA identity comparison;
- analysis-mode comparison;
- required-lab coverage comparison;
- theoretical queue model;
- theoretical worker/fallback model;
- actual terminal state as observation only.

The shadow record cannot create PASS, FAIL or CERTIFIED.

## Recovery

Every phase can emit `APPLAB_CONDUCTOR_SHADOW_CHECKPOINT`.

A checkpoint binds:

- immutable workflow version;
- digest of Event, plan, actual metadata and inventory;
- next phase index;
- partial deterministic state.

Resume fails if any bound input changes.

The contract test resumes from every non-terminal phase and requires byte-equivalent final semantic output.

## Fail-closed rules

Promotion evidence is false when:

- repository/SHA identity differs;
- actual analysis mode differs from Smart Test Plan;
- any required lab is absent;
- checkpoint input changes;
- workflow/reference version drifts.

Worker-model mismatch is observed separately because D remains read-only and does not choose the real executor.

## Explicit non-capabilities

No:

- Conductor server credentials;
- network client;
- workflow start API call;
- GitHub dispatch;
- worker lease mutation;
- test-plan mutation;
- verdict mutation;
- certification authority.

v5.4E may consume these deterministic queue decisions only after v5.4D remains green.

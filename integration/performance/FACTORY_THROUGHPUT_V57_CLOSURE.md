# AppLab v5.7 — Real Evidence Closure

Status: **v5.7B PROVEN / v5.7E PROMOTION EVIDENCE IN PROGRESS**

## v5.7B — Real Adoption Pilots & Speed Evidence

Authoritative evidence source: AppLab Continuous Maintenance run `40404428444`
against AppLab `1574aeff628ae3f8edc7fb31b09dd8df267b3696`.

The v5.7A observatory reports both declared throughput pilots as adopted:

- `riccardopinato/Agenda-per-Anna`
- `riccardopinato/In-Cucina-con-gli-Anime`

The v5.7B throughput report records:

- Anna's Diary: `EVIDENCE_READY`, 10 real primary samples,
  first-commit-to-merge p50 = 3400 s.
- In cucina con gli anime: `EVIDENCE_READY`, 10 real primary samples,
  first-commit-to-merge p50 = 978 s.
- `promotion_ready=true`.
- No synthetic samples are accepted.

Therefore the v5.7B promotion gate is satisfied.

## v5.7E — Throughput & Verification Reuse

Real carrier:

- repository: `riccardopinato/Battery_Guard`
- adopted source SHA: `d8cf237ab2df2daf427b87ca057871e3143bccc7`
- trusted AppLab SHA: `1574aeff628ae3f8edc7fb31b09dd8df267b3696`
- Repo Watcher run: `40404428661`
- v5.7E shadow admission: `SHADOW_READY`

First content-addressed build execution:

- result: **MISS**
- reason: `artifact-not-found`
- execution key:
  `6495b2f72b7b74142094592c9e3dd18b210847214ba588cf3c007d4875c4ef5e`
- artifact:
  `applab-build-v41-watch-battery-guard-6495b2f72b7b74142094592c`
- artifact ID: `12690911324`
- build job: `121858525668`
- build job result: **PASS**

The first trusted runtime verification must pass before the exact same job is
re-run to prove a real content-addressed **HIT**. v5.7E remains open until that
HIT also passes the separate exact-artifact promotion gate.

## Authority boundaries

- No cross-SHA PASS reuse.
- Runtime verification remains tied to the exact APK bytes.
- Production Certification remains the only certification authority.
- Physical-device/store evidence remains separate.
- A cache HIT that fails exact-artifact promotion must fail closed before PASS
  evidence is finalized or bound.

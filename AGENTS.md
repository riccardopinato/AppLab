# AppLab — repository operating contract

Applies to work in `riccardopinato/AppLab`. This is an agent procedure entrypoint,
**not** a replacement for the AppLab roadmap, product rules, verification contracts,
App-Factory-Core CURRENT/Master/Golden, or real implementation.

## Authority order
1. AppLab Product Bible, when present, governs product decisions.
2. `ROADMAP.md` and linked detailed roadmap govern authorized execution.
3. `App-Factory-Core/CURRENT.yaml` resolves current Factory Master and Golden Rules;
   perform **one** bootstrap at the start of Factory-dependent work, pin its SHA.
4. Repository contracts and architecture decide local implementation.
5. Exact source SHA + trusted test/evidence decide runtime state.

## Scope and safety
- Stay in Chat mode when acting through ChatGPT. Use branch -> tests -> PR -> exact-head
  checks/review -> gated merge. Never force-push protected main.
- Use the existing v5.4/v5.5 durable execution and v6 agents; never invent parallel
  scheduler, evidence/verifier authority or certification.
- Autonomous worker: max 5 files, 250 changed lines, 2 attempts, LOW/NORMAL risk only.
- No autonomous changes to App-Factory-Core, secrets, release, branch protection,
  policy/workflows/AGENTS.md, protected contracts or weaker tests.
- Independent review and required exact-head checks precede any automatic merge.
- Runtime PASS is not physical-device, store, production or real closed-loop repair proof.
- v6.2 rollout remains `SELF_CANARY`. No implicit `PILOT_3` / `PILOT_5`.

## Load only when relevant
- `governance/agents/git-workflow.md` for branching, PR and merge.
- `governance/agents/testing-validation.md` for tests, evidence and certification.
- `governance/agents/code-hygiene.md` for bounded cleanup.
- `governance/agents/research-reuse.md` for dependency and donor checks.

All changes to this governance contract go through normal branch/PR/review.

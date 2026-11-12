# X10-009 — Selezione adapter AppLab → App Factory Agent Core

**Audit:** 12/11/2026. **AppLab source SHA verificato:** [2d57d9cea85ac03016b24e103046e47b6f02acb5](https://github.com/riccardopinato/AppLab/commit/2d57d9cea85ac03016b24e103046e47b6f02acb5). **Factory:** `App-Factory-Core@c5adc147046beb7024629466d10eeb799c3c2619`, Master 27 / Golden Index 29.  
**Stato:** `ADAPTER_SELECTION_SOURCE_AUDITED`; nessun nuovo orchestrator, nessun runner importato o eseguito e nessuna modifica al runtime AppLab.

## Contratto di confine (non duplicare l'esistente)
`Agent Core` espone un contratto pubblico di job/approval, ma **AppLab resta owner** di durable queue, work graph, investigation, bounded patch e PR steward. L'Agent Core non deve avviare un motore concorrente con proprio database di verità. Il boundary sarà un adapter di invocazione *opt-in*, con source SHA/permissions e versioni verificate.

| Responsabilità | Owner e funzione letta sul sorgente | Limite |
|---|---|---|
| Event admission | [`controlled_event_v54g.admit`](https://github.com/riccardopinato/AppLab/blob/2d57d9cea85ac03016b24e103046e47b6f02acb5/scripts/controlled_event_v54g.py) | Richiede db_path, config_path, repository, source_ref, resolved_sha, applab_sha, delivery_id, live_requested; allowlist del pilota |
| Durable queue | [`DurablePerRepoQueue.enqueue`](https://github.com/riccardopinato/AppLab/blob/2d57d9cea85ac03016b24e103046e47b6f02acb5/scripts/durable_queue_v54e.py), `claim_next` | Operazione già ammessa, idempotence/lease e worker identity; NON duplicare scheduler |
| Work graph | [`agent_work_graph_v60a.adapt_operation_to_work_item`](https://github.com/riccardopinato/AppLab/blob/2d57d9cea85ac03016b24e103046e47b6f02acb5/scripts/agent_work_graph_v60a.py) | Input Operation già validata; `allow_code_edit` e `allow_draft_pr_steward` **false di default** |
| Investigation | [`causal_repo_investigator_v60b.build_investigation`](https://github.com/riccardopinato/AppLab/blob/2d57d9cea85ac03016b24e103046e47b6f02acb5/scripts/causal_repo_investigator_v60b.py) | `triage,plan,repo_root`; output `PROPOSAL_ONLY`, UNKNOWN fail-closed |
| Bounded patch | [`bounded_fix_worker_v60c.apply_bounded_patch`](https://github.com/riccardopinato/AppLab/blob/2d57d9cea85ac03016b24e103046e47b6f02acb5/scripts/bounded_fix_worker_v60c.py) | repo_root, patch_path, work_item, investigation, attempt_number; exact Git HEAD SHA e workspace Git validi |
| Draft PR | [`draft_pr_steward_v60e.materialize_local/decide_remote_action/execute_remote`](https://github.com/riccardopinato/AppLab/blob/2d57d9cea85ac03016b24e103046e47b6f02acb5/scripts/draft_pr_steward_v60e.py) | `CREATE_DRAFT_PR`/update capability + source identity, review esterna e no auto-approval |
| v6.2 self-canary | [`autonomous_repair_v62a.process`](https://github.com/riccardopinato/AppLab/blob/2d57d9cea85ac03016b24e103046e47b6f02acb5/scripts/autonomous_repair_v62a.py) | Usare soltanto se l'espansione di rollout è esplicitamente autorizzata, non default |
| Existing reuse planner | [`factory_reuse_planner_v57d.build_report`](https://github.com/riccardopinato/AppLab/blob/2d57d9cea85ac03016b24e103046e47b6f02acb5/scripts/factory_reuse_planner_v57d.py) | Legge Registry con `CURRENT.yaml`; nessuna ammissione Golden automatica |

## Mappatura API proposta da X10-010
```text
Agent Core JobDesignV1 target.repo + exact source_sha + allowed_paths
   ↓ validate authority, provider, owner and review scope
AppLab controlled_event admission or Work Graph Operation (never both schedulers)
   ↓ DurablePerRepoQueue claim with exact lease/worker id
analyze       → causal_repo_investigator; read-only PROPOSAL_ONLY
run_tests     → AppLab focused test runner scoped to exact SHA
propose_diff  → bounded_fix_worker only after explicit ALLOW_CODE_EDIT
prepare_pr    → draft_pr_steward only after CREATE_DRAFT_PR; no self-approve
   ↓ evidence refs (run URL, source SHA, status) → Agent Core result
   ↓ review/CI exact head and authorized merge outside adapter
```

**No code copying:** eventuali adapter possono importare via installazione locale verificata/CLI per release specifica e registrare versioni; vietata importazione da `main` mobile o da file sconosciuti. Nessun broker o modello AI richiesto come dipendenza per test del contratto.

## Contratto degli stati e collisioni
- L'utente ha approvato nessun **tetto artificiale a task di programma** nella coda 10x; ciò **non cambia** i limiti runtime esistenti di AppLab.
- [`controlled_event_v54g.py`](https://github.com/riccardopinato/AppLab/blob/2d57d9cea85ac03016b24e103046e47b6f02acb5/scripts/controlled_event_v54g.py) ha `QUEUE_LIMITS.max_ready_global = 2`, `max_ready_per_repo = 1`, `max_active_global = 1`, `max_active_per_repo = 1`. Il [`DurablePerRepoQueue`](https://github.com/riccardopinato/AppLab/blob/2d57d9cea85ac03016b24e103046e47b6f02acb5/scripts/durable_queue_v54e.py) ha default indipendenti (ready 8, active 4). **Non cambiare limiti del pilota per soddisfare la roadmap senza prove**.
- Due task read-only indipendenti possono lavorare in parallelo su GitHub senza occupare lease AppLab; un writer di AppLab mantiene lease/lock reali. Un task `BLOCKED` non trattiene slot programma; il lease di un worker reale si gestisce solo tramite recovery canonico.
- Il routing verso un esecutore diverso o la capacità effettiva di parallelismo è una futura decisione di runtime, non un attributo che Agent Core può inventare.

## X10-010 — acceptance obbligatoria prima della prima esecuzione
1. Gateway deny-by-default per repo/ref/path/mode/phase; nessun PAT/secret in payload o log.
2. `analyze` autorizzato senza edit; `propose_diff`/PR bloccati senza capability e approval scoped.
3. Il commit del consumer deve esistere, essere un SHA40 e corrispondere al checkout esatto; mismatch / PR diff out-of-scope bloccati.
4. Verifica perdita eventi, lease scaduti, doppia delivery, changed SHA e rete indisponibile in fixture, senza ripetere PASS inesistenti.
5. Test del contratto **sintetici e senza rete**; runtime/AppLab CLI pilota reale testato separatamente.
6. Mai elevare automaticamente v6.2 oltre `SELF_CANARY` ([operational proof](https://github.com/riccardopinato/AppLab/blob/2d57d9cea85ac03016b24e103046e47b6f02acb5/integration/roadmap/APPLAB_V62_OPERATIONAL_PROOF.md)).

**Risultato X10-009:** selezione adapter completata come evidence del sorgente a commit fissato. **Non** equivale a integrazione runtime o chiamata AI.

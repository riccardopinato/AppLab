# X10-028 — QA test router condiviso (AppLab reuse)

**Factory baseline:** `App-Factory-Core@c5adc147046beb7024629466d10eeb799c3c2619`; owner AppLab; prerequisite X10-027 source audit [PR #217](https://github.com/riccardopinato/AppLab/pull/217).

## Implementato
[`scripts/qa_test_router_x10.py`](../../scripts/qa_test_router_x10.py) associa un *consumer descriptor* (`repository`, `source_sha`, `engine`, `analysis_mode`, `mandatory_labs`) al piano già generato dal **vero** `smart_test_plan.analyze_repository`. Il chiamante trusted deve passare **`smart_test_plan.validate_plan`**. Il modulo non copia le euristiche del planner né le certificazioni.

I gate `maestro`, `visual_qa`, `visual_regression`, `visual_journey`, nove specialist lab inclusi performance sono letti da `certification_gate.STRICT_GATES`, non da una seconda matrice di autorità. La route:
- Per FAST seleziona i lab derivati dal planner, aggiungendo quelli **obbligatori per l'app** senza rimuovere quelli esistenti.
- Per FULL richiede tutti i lab già previsti da AppLab, senza ridurne la copertura.
- Per CERTIFICATION mantiene tutti i 13 STRICT_GATES e analisi/test/build prescritti, senza eccezioni consumer.
- Controlla sorgente SHA40, repository e identità del piano, scelta engine Flutter/native Android, booleans dei gate, nomi dei lab e impossibilità di downgrading.

`delegate(route, runner=trusted_applab_executor)` fornisce un punto di invocazione verso un **runner AppLab già esistente**, accetta solo un rapporto con stessa identità SHA/mode e l'intero set di gate attesi, e produce `APP_FACTORY_X10_QA_RECEIPT` distinguendo `RUNNER_REPORTED_ONLY` da `BLOCKED_OR_FAIL_REPORTED`. Gli stati `NOT_RUN`, `NO_BASELINE`, `UNKNOWN`, `ERROR` e `FAIL` non diventano PASS; persino tutti i PASS segnalati dal runner restano **self-reported non verificati** finché la verifica indipendente AppLab non conferma prove immutable. L'adapter non firma APK, non certifica Store e non promuove Golden.

## Esecuzione e limiti
[`backend/tests/test_x10_qa_test_router.py`](../../backend/tests/test_x10_qa_test_router.py) verifica l'algoritmo con planner/executor **sintetici**. Per l'uso reale passare piano da `smart_test_plan.py` su checkout esatto, manifest consumer approvato e dispatcher AppLab già autorizzato; nessuna shell o pipeline runtime viene creata da questo modulo.

- **SOURCE+CI** significa corretta costruzione della route/receipt, non esecuzione di test su Anna's Diary, World Days, Battery Guard o altri consumer.
- **X10-029/030/031** restano owner di baselines visual, performance/a11y e signing provenienza; X10-032 richiede prova umana fisica.
- AppLab v6.2 rollout `SELF_CANARY` e limiti runtime rimangono invariati. Solo reviewer/verifier esterno può attestare prove reali e sbloccare la distribuzione.

## Review hardening 2026-11-12 — receipt provenance e gate non vuoti

Il delegator non può produrre `all_reported_pass:true` quando il piano contiene zero gate, manca un test statico obbligatorio o FULL/CERTIFICATION omette un gate canonico. La route caller-carried deve avere i campi identità e stato originali, ma **non è una firma** e richiede comunque verifica indipendente. Un report con URL vuoto è `BLOCKED_OR_FAIL_REPORTED` e include `TRUSTED_RUN_REFERENCE_MISSING`. Gli URL Actions sono accettati solo per il consumer stesso o il runner `riccardopinato/AppLab` (che può eseguire test su un consumer esterno); l'URL è validato per struttura e repository, **non** autenticato tramite GitHub API né associato a un run SHA/artifact reale. Anche tutti i gate PASS rimangono `RUNNER_REPORTED_ONLY` e `independent_provenance_verified:false`.

I test di regressione includono route vuota o manomessa, gate qualità rimossi, URL estraneo, mancanza di run URL e percorso AppLab legittimo. La PR X10-028 resta soggetta a review, CI exact-head e correzione della dipendenza browser-runner da AppLab #220; non è una certificazione di feature consumer.

## Review fix: FULL strict gate composition

Codex ha individuato sul commit `5f2418eb35` una incoerenza fra `route()` e `delegate()`: il primo includeva `maestro` e i gate visuali soltanto in CERTIFICATION, mentre il secondo impone giustamente l'intera matrice `STRICT_GATES` anche per FULL. Ora anche FULL (incluso FAST elevato a FULL dal planner) include gli stessi gate stretti; non viene concesso alcun PASS certificativo o avvio di test consumer. Test dedicati verificano percorsi FULL/FAST→FULL con i gate canonici completi e receipt comunque `RUNNER_REPORTED_ONLY`.

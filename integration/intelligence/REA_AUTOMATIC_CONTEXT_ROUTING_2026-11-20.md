# REA — selezione automatica contestuale negli audit AppLab

**20 novembre 2026 · Factory baseline `2b05a569c4072f10f7dcf8fe0b11432081c1e4d5` · Master v27 / Golden Index v31 `CERTIFIED PROCESS` (scope statico).**

## Scopo

AppLab **non richiede più che il WorkItem selezioni manualmente REA come strumento**. Il pianificatore degli audit (`audit_orchestrator.build_plan`) e la revisione autonoma (`autonomous_app_review.build_review`) includono una decisione `rea_research` dalla stessa evidence context. Il router è `scripts/rea_auto_router.py`. L'operatività REA resta CLI, con unico adapter canonico `scripts/rea_cli_research.py` o precedente bridge PE `scripts/rea_cli_bridge.py`. Niente MCP, processo residente, auto-download, dipendenza nelle app o escursione in tutti i repo.

## Politica source-first e guadagno informativo

| Segnale diagnosticato da AppLab | Decisione quando esiste artefatto verificato | Famiglia |
|---|---|---|
| `source_vs_artifact_diff` | Confronto compilato/sorgenti | APK Android/Flutter o PE |
| `manifest_permissions_diverge` | Permessi/componenti nel compilato divergono dal manifest atteso | Android/JADX |
| `unexpected_native_dependency` | Librerie native sconosciute / inattese | Android/JADX |
| `aot_snapshot_unexplained` | Anomalia su build Flutter/Dart AOT | Flutter build + AOT |
| `artifact_growth_unexplained` | Delta dimensione non spiegabile con i sorgenti | Famiglia dell'artefatto |
| `managed_dependencies_unknown` | Metadati/dipendenze .NET non risolte | Managed PE |
| `installer_contents_unknown` | Composizione package Desktop non chiarita dai sorgenti | Desktop directory |
| `missing_source` | Analisi del binario solo se fonte realmente mancante | Famiglia dell'artefatto |

Un normale commit, cambio estetico, audit contenuti o CI verde **non attiva REA**. Prima vengono sorgenti, test, donor interni e QA esistenti. La decisione registra punteggio, ragioni, modo e operazioni. Lo stesso artifact SHA+source SHA+operazioni già analizzati vengono saltati. Non vengono inferiti diritti da testo diagnostico: **provenienza e autorizzazione sono gate separati**.

## Stati e auto-esecuzione

- `SKIP`: nessuna lacuna binaria, sorgente sufficiente o stessa evidence già analizzata.
- `BLOCKED`: diritti assenti, formato non supportato, identità errata, file cambiato, eseguibile REA coincide col target, output in posizione inammissibile.
- `PROPOSE`: utile ma manca l'artefatto, SHA, runtime REA, JAR JADX verificato, budget adeguato o approvazione specifica per binario esterno.
- `AUTO_RUN`: **solo file locale dell'app/repo di proprietà**, fonte e SHA esatti, mismatch utile, runtime REA già disponibile, budget e destinazione privata validi. Nessun tool viene installato o eseguito per il solo fatto di valutare la policy.

Il solo uso dei nomi `REA`, `Flutter`, `Android`, `APK` in un messaggio non costituisce trigger. Per un APK nativo REA/JADX non viene avviato se il JAR pinned non è presente e hash-verificato. Le directory Desktop usano `inspect_tree` per SHA del payload; le app Flutter usano l'inspector APK esistente. La decisione **non** autorizza reverse engineering di programmi terzi senza conferma dei diritti.

## Integrazione CLI nei WorkItem

Il producer del WorkItem può emettere il contesto JSON da anomalie macchina e artefatto già creato. Non deve scegliere il motore REA. Esempio (valori illustrativi da sostituire con metadati **reali**):

```json
{
  "repository": "OWNER/OWNED_APP",
  "source_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "authorization": "OWNED",
  "artifact_path": "/private/build/app-release.apk",
  "artifact_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "artifact_kind": "APK",
  "stack": "flutter",
  "source_complete": true,
  "symptoms": ["aot_snapshot_unexplained"],
  "rea_bin": "/private/tools/node_modules/.bin/rea",
  "output_dir": "/private/rea-output"
}
```

```bash
python scripts/audit_orchestrator.py --app-intelligence /private/app-intelligence.json \
  --rea-context /private/workitem-rea.json --rea-auto-execute \
  --output-dir /private/audit-plan

python scripts/autonomous_app_review.py --repo-root /private/repo \
  --rea-context /private/workitem-rea.json --rea-auto-execute \
  --output-dir /private/autonomous-review
```

`--rea-auto-execute` attiva il **dispatcher per i soli casi AUTO_RUN**, in base alla policy: non impone di lanciare REA per ogni WorkItem. Senza il flag si registra soltanto la decisione. In assenza di artifact context il report standard dichiara `SKIP / SOURCE_FIRST_NO_BINARY_GAP`, senza inventare analisi. Il CI usa un fixture innocuo per provare anche la vera invocazione automatica; il repository consumer deve fornire i propri bytes/SHA nel proprio runner autorizzato.

## Misure di sicurezza e maturità

Il dispatcher passa argomenti strutturati a Python (`subprocess.run` **senza shell**), con script canonico, SHA atteso, output privato e tempo massimo. Verifica inoltre l'hash nel receipt di ritorno, non soltanto l'exit code. Gli output REA rimangono `UNVALIDATED_EXTERNAL_OUTPUT`; non promuovono donor E3, Golden di prodotto, affidabilità runtime o Play readiness. Nessun APK o payload privato viene pubblicato nel report.

Questa è **selezione autonoma condizionata da evidenze disponibili**, non scansione di tutte le app né agente continuamente attivo. Il Golden certificato copre soltanto il processo di ricerca statica già testato, non la precisione di ogni futura selezione. Nuove regole/segnali richiedono test, review e exact-head CI.

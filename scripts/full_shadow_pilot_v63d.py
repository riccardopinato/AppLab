"""Helpers for the advisory FULL shadow three-way runtime pilot."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

def opted_in(root: Path, repository: str) -> bool:
    payload = json.loads((root / 'config/journey-sharding-pilots.json').read_text())
    values = payload.get('repositories', {})
    matches = ([v for k, v in values.items()
                if isinstance(k, str) and k.lower() == repository.lower()]
               if isinstance(values, dict) else [])
    entry = matches[0] if len(matches) == 1 else None
    return isinstance(entry, dict) and entry.get('mode') == 'shadow' and entry.get('full_shadow') is True

def groups(selected: list[str], catalog: dict[str, Any]) -> list[dict[str, Any]]:
    if len(set(selected)) != len(selected) or set(selected) != set(catalog):
        return []
    ui, diary, deep = [], [], []
    for name in selected:
        row = catalog[name]
        if row.get('risk_class') == 'deep':
            deep.append(name)
        elif any(v in {'memories', 'diary'} for v in row.get('surfaces', [])):
            diary.append(name)
        else:
            ui.append(name)
    if not (ui and diary and deep):
        return []
    return [{'id': 'full-ui-navigation', 'journeys': ui},
            {'id': 'full-diary-memories', 'journeys': diary},
            {'id': 'full-deep-security', 'journeys': deep}]

def self_test(trusted: Path, contract: Path, evidence: Path, build_plan) -> None:
    cfg = trusted / 'config/journey-sharding-pilots.json'
    raw = json.loads(cfg.read_text())
    raw['repositories']['Owner/App'] = raw['repositories'].pop('owner/app')
    raw['repositories']['Owner/App']['full_shadow'] = True
    cfg.write_text(json.dumps(raw))
    assert opted_in(trusted, 'owner/app') and opted_in(trusted, 'OWNER/APP')
    (evidence / '.maestro/memory.yaml').write_text('appId: demo\n')
    target = evidence / 'applab.project.json'
    project = json.loads(target.read_text())
    project['journeys']['catalog']['memory'] = {
        'flow': '.maestro/memory.yaml', 'paths': ['lib/diary/**'],
        'labs': [], 'surfaces': ['memories'], 'capabilities': ['diary'],
        'risk_class': 'normal', 'always_fast': False}
    target.write_text(json.dumps(project))
    plan_path = contract / 'analysis-plan.json'
    plan = json.loads(plan_path.read_text())
    plan.update({'lane': 'FULL_RUNTIME',
                 'selected_journeys': ['shell', 'memory', 'vault-deep'],
                 'journey_selection': {'enforcement_eligible': False,
                                       'unmatched_paths': ['lib/unmapped.dart']}})
    plan_path.write_text(json.dumps(plan))
    result = build_plan(contract_root=contract, trusted_root=trusted, repository='owner/app')
    assert result['enabled'] and result['mode'] == 'shadow' and not result['authoritative']
    assert len(result['shards']) == 3 and not result['coordinator_journeys']
    import journey_sharding_admission
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as temp:
        output = Path(temp) / 'out'
        admitted = journey_sharding_admission.reconcile(result, visual_baseline_ready=True,
                                                        upgrade_baseline_ready=True)
        journey_sharding_admission.write_outputs(output, admitted)
        assert 'full_shadow=true' in output.read_text()
    assert set().union(*(set(s['journeys']) for s in result['shards'])) == set(plan['selected_journeys'])
    plan['selected_journeys'] = ['shell', 'vault-deep']
    plan_path.write_text(json.dumps(plan))
    assert not build_plan(contract_root=contract, trusted_root=trusted, repository='owner/app')['enabled']
    plan['selected_journeys'] = ['shell', 'memory', 'vault-deep']
    plan['lane'] = 'CERTIFICATION'
    plan_path.write_text(json.dumps(plan))
    assert not build_plan(contract_root=contract, trusted_root=trusted, repository='owner/app')['enabled']
    plan['lane'] = 'FULL_RUNTIME'
    plan_path.write_text(json.dumps(plan))
    raw['repositories']['Owner/App']['mode'] = 'authoritative'
    cfg.write_text(json.dumps(raw))
    assert not build_plan(contract_root=contract, trusted_root=trusted, repository='owner/app')['enabled']

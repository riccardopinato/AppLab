"""Helpers for the advisory FULL shadow three-way runtime pilot."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

def opted_in(root: Path, repository: str) -> bool:
    payload = json.loads((root / 'config/journey-sharding-pilots.json').read_text())
    values = payload.get('repositories', {})
    entry = values.get(repository.lower()) if isinstance(values, dict) else None
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
    raw['repositories']['owner/app']['full_shadow'] = True
    cfg.write_text(json.dumps(raw))
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
    raw['repositories']['owner/app']['mode'] = 'authoritative'
    cfg.write_text(json.dumps(raw))
    assert not build_plan(contract_root=contract, trusted_root=trusted, repository='owner/app')['enabled']

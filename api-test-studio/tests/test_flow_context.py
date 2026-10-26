"""Each flow-pipeline call gets only the API context it needs, and the job reports its Claude usage."""
import json

from contracts.flows import (brief_endpoint, compact_endpoint, dependencies, dependency_hints, domain_for, operation_index,
                             requirements)
from helper import claude, flow_cases

from .conftest import beat, pair_helper
from .test_flows import AREAS, DOMAIN, ENDPOINTS, FakeFlowClaude
from .test_models import run_job, start_job


def pipeline():
    pipe = flow_cases.FlowPipeline({'title': 'Petstore'}, ENDPOINTS, FakeFlowClaude(), '.', lambda *a: None)
    pipe.restore(json.loads(json.dumps({**DOMAIN, 'areas': AREAS})), [])
    return pipe


def test_area_designer_gets_full_contracts_only_for_its_own_operations():
    pipe = pipeline()
    pets = next(g for g in pipe.groups() if g['name'] == 'Pets')
    task = pipe.context(pets, mode='plan')
    assert {op['operationId'] for op in task['operations']} == pets['operations']
    assert len(task['operationIndex']) == len(ENDPOINTS)  # every operation is still usable as a setup step
    assert all(hint['operation'] in pets['operations'] for hint in task['dependencies'])
    assert task['requirements'] == pets['requirements'] and task['scope']['name'] == 'Pets'


def test_journeys_get_every_operation_briefly_and_gap_filling_gets_only_the_missing_operations():
    pipe = pipeline()
    journeys = next(g for g in pipe.groups() if g['name'] == flow_cases.JOURNEYS)
    task = pipe.context(journeys, mode='plan')
    assert len(task['operations']) == len(ENDPOINTS) and all('statuses' in op and 'responses' not in op for op in task['operations'])
    assert 'areas' not in task['domain']
    missing = [r for r in pipe.required if r['id'] == 'op:listPets']
    gap = pipe.context(None, mode='fill-gaps', missingRequirements=missing, existingFlows=[])
    assert [op['operationId'] for op in gap['operations']] == ['listPets'] and 'requirements' not in gap
    assert len(json.dumps(gap)) < len(json.dumps(pipe.context(journeys, mode='plan')))


def test_dependency_hints_rank_creating_operations_first_and_stay_short():
    edges = dependencies(ENDPOINTS)
    hints = dependency_hints(edges, ENDPOINTS)
    required = {(e['to'], e['target']) for e in edges if e['required']}
    assert {(h['operation'], h['input']) for h in hints} == required
    get_pet = next(h for h in hints if h['operation'] == 'getPet')
    assert get_pet['from'][0].startswith('createPet ') and len(get_pet['from']) <= 3
    rule = next(r for r in requirements(ENDPOINTS, edges, DOMAIN) if r['id'].startswith('dep:getPet:'))
    assert '(e.g. createPet' in rule['description']


def test_brief_index_and_error_responses_are_compact():
    create = next(e for e in ENDPOINTS if e['operationId'] == 'createPet')
    brief = brief_endpoint(create)
    assert brief['statuses'] == sorted(create['responses']) and any(f.rstrip('*') == 'name' for f in brief['body'])
    line = operation_index(create)
    assert line.startswith('createPet: POST /pets [') and '201' in line
    full = compact_endpoint(create)
    assert all('schema' not in detail for status, detail in full['responses'].items() if not status.startswith('2'))


def test_domain_for_keeps_only_what_the_operations_touch():
    trimmed = domain_for(DOMAIN, {'getOrder'})
    assert {e['name'] for e in trimmed['entities']} <= {e['name'] for e in DOMAIN['entities']}
    assert all(t['operationId'] == 'getOrder' or t['entity'] in {e['name'] for e in trimmed['entities']} for t in trimmed['transitions'])
    assert len(json.dumps(trimmed)) <= len(json.dumps(DOMAIN))


def test_job_usage_is_summed_and_reported(project, monkeypatch):
    import subprocess
    monkeypatch.setattr(claude, 'claude_command', lambda: ['claude'])
    lead, pid = project
    helper = pair_helper(lead)
    beat(helper)
    job = start_job(lead, pid)

    def runner(args, **kwargs):
        envelope = {'type': 'result', 'is_error': False, 'structured_output': {'ok': True},
                    'modelUsage': {'claude-sonnet-5-5': {'inputTokens': 100, 'outputTokens': 20, 'cacheReadInputTokens': 900,
                                                         'cacheCreationInputTokens': 50, 'costUSD': 0.01}}}
        return subprocess.CompletedProcess(args, 0, json.dumps(envelope), '')
    run_job(helper, runner)
    usage = lead.get(f'/api/projects/{pid}/jobs/{job["id"]}').json()['usage']
    agents = usage.pop('agents')
    assert usage == {'calls': 1, 'inputTokens': 100, 'cacheReadTokens': 900, 'cacheWriteTokens': 50, 'outputTokens': 20, 'costUsd': 0.01}
    assert agents == {'framework-analyzer': {'calls': 1, 'inputTokens': 100, 'cacheReadTokens': 900, 'cacheWriteTokens': 50,
                                             'outputTokens': 20, 'errors': 0, 'checked': 0, 'checkFailed': 0}}

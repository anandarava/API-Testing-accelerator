"""Parallel unit generation: concurrency, early stop and unique case numbers under simultaneous results."""
import threading
import time

import pytest

from contracts.coverage import obligations
from helper import unit_cases
from helper.claude import CLAUDE_TIMEOUT, ClaudeError, ClaudeStatus, run_agent
from helper.runner import Helper

from .conftest import beat, pair_helper, upload
from .test_unit_cases import fitting

SPEC = """
openapi: 3.0.3
info: {title: Parallel, version: '1'}
paths:
""" + ''.join(f"""  /items{i}:
    post:
      operationId: create{i}
      requestBody:
        required: true
        content:
          application/json:
            schema: {{type: object, required: [name], properties: {{name: {{type: string, maxLength: 10}}}}}}
      responses:
        '201': {{description: created}}
        '400': {{description: invalid}}
""" for i in range(7))


class SlowClaude:
    """Answers every agent correctly after a short delay and records how many calls overlap."""

    def __init__(self, delay=0.05, fail_on=None):
        self.delay, self.fail_on = delay, fail_on
        self.lock, self.running, self.peak, self.calls = threading.Lock(), 0, 0, 0

    def __call__(self, agent, task, schema, **options):
        with self.lock:
            self.running += 1
            self.calls += 1
            self.peak = max(self.peak, self.running)
        try:
            time.sleep(self.delay)
            if self.fail_on and task.get('endpoint', {}).get('operationId') == self.fail_on:
                raise ClaudeError('Your Claude usage limit has been reached. Try again after it resets.')
            if agent == 'unit-scenario-planner':
                return {'scenarios': [fitting(f'S{i + 1:02d}', r['id']) for i, r in enumerate(task['requirements'])]}
            if agent == 'unit-case-writer':
                return {'cases': [{'scenarioKey': key, 'title': f'Case {key}', 'objective': 'o', 'category': 'required', 'priority': 'P2',
                                   'preconditions': [], 'request': {'auth': 'valid', 'body': {}}, 'expected': {'status': 400, 'responseSchema': 'none'},
                                   'testData': '', 'cleanup': [], 'needsConfirmation': False, 'confirmationNote': ''} for key in task['onlyKeys']]}
            return {'verdict': 'ready', 'summary': 'Fine.', 'findings': []}
        finally:
            with self.lock:
                self.running -= 1


def endpoints():
    from studio.openapi import parse_spec
    return parse_spec(SPEC)['endpoints']


def test_default_limits():
    assert unit_cases.PARALLEL_ENDPOINTS == 5
    assert CLAUDE_TIMEOUT == 3600
    assert run_agent.__defaults__[1] == CLAUDE_TIMEOUT  # timeout default of run_agent


def test_runs_five_endpoints_at_once_and_submits_each():
    fake = SlowClaude(delay=0.1)
    submitted, reports = [], []
    job = {'api': {}, 'endpoints': [{'id': f'e{i}', 'details': e} for i, e in enumerate(endpoints())]}
    result = unit_cases.generate(job, lambda message, percent=None: reports.append((message, percent)), submitted.append, agent=fake)
    assert result == {'endpoints': 7, 'failed': 0}
    assert fake.peak == 5
    assert sorted(r['endpointId'] for r in submitted) == [f'e{i}' for i in range(7)]
    assert any('up to 5 at a time' in m for m, _ in reports) and reports[-1] == ('Finished', 100)
    assert any(m.startswith('3 of 7 endpoints done') for m, _ in reports)


def test_usage_limit_stops_new_endpoints_but_keeps_finished_ones():
    fake = SlowClaude(delay=0.05, fail_on='create0')
    submitted = []
    job = {'api': {}, 'endpoints': [{'id': f'e{i}', 'details': e} for i, e in enumerate(endpoints())]}
    with pytest.raises(ClaudeError, match=r'usage limit.*Finished \d of 7 endpoints'):
        unit_cases.generate(job, lambda *a, **k: None, submitted.append, agent=fake, parallel=2)
    assert 'e0' not in {r['endpointId'] for r in submitted}
    assert len(submitted) < 7  # queued endpoints were not started after the limit was hit


def test_simultaneous_results_get_unique_case_numbers(project):
    lead, pid = project
    assert upload(lead, pid, 'parallel.yaml', SPEC, 'application/yaml').status_code == 200
    helper = pair_helper(lead)
    beat(helper)
    ids = [e['id'] for e in lead.get(f'/api/projects/{pid}/endpoints').json()['endpoints']]
    assert lead.post(f'/api/projects/{pid}/unit/generate', json={'endpointIds': ids}).status_code == 200

    fake = SlowClaude(delay=0.02)
    status = ClaudeStatus(installed=True, loggedIn=True)
    handlers = {'unit.generate': lambda job_input, report, submit=None: unit_cases.generate(job_input, report, submit, agent=fake)}
    assert Helper(helper, log=lambda _: None, claude_status=lambda: status, handlers=handlers).run_once()

    overview = lead.get(f'/api/projects/{pid}/unit/endpoints').json()
    assert overview['job']['status'] == 'succeeded'
    codes = []
    for endpoint_id in ids:
        detail = lead.get(f'/api/projects/{pid}/unit/endpoints/{endpoint_id}').json()
        expected = len(obligations(next(e for e in endpoints() if e['path'] == detail['endpoint']['path'])))
        assert len(detail['cases']) == expected
        codes += [c['code'] for c in detail['cases']]
    assert len(codes) == len(set(codes))

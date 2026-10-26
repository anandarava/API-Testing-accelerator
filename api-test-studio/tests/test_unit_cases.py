"""Unit test case module: coverage rules, the helper pipeline and server-side review."""
import pytest

from contracts.coverage import gaps, obligations
from helper import unit_cases
from helper.claude import ClaudeError
from helper.runner import Helper
from studio.openapi import parse_spec

from .conftest import EXAMPLES, beat, pair_helper, upload

PETSTORE = (EXAMPLES / 'petstore.yaml').read_text(encoding='utf-8')
PARSED = parse_spec(PETSTORE)
CREATE_PET = next(e for e in PARSED['endpoints'] if e['operationId'] == 'createPet')
GET_PET = next(e for e in PARSED['endpoints'] if e['operationId'] == 'getPet')


def ids(endpoint):
    return {item['id'] for item in obligations(endpoint, PARSED['securitySchemes'])}


def test_coverage_requirements_for_create_pet():
    found = ids(CREATE_PET)
    assert {'positive:minimal', 'positive:full', 'status:201', 'status:400', 'status:401', 'status:409',
            'required:body', 'required:body.name', 'null:body.name', 'type:body.name',
            'boundary:body.name:minLength', 'boundary:body.name:maxLength', 'boundary:body.tag:maxLength',
            'header:content-type', 'auth:missing', 'auth:invalid'} <= found
    # Read-only response fields are not request requirements; 5xx is never a target.
    assert not any('body.id' in item or item.startswith('status:5') for item in found)


def test_coverage_requirements_for_path_parameters_and_nested_bodies():
    found = ids(GET_PET)
    assert {'invalid:path.petId', 'notfound:path.petId', 'format:path.petId', 'status:404'} <= found
    endpoint = {'method': 'POST', 'path': '/orders', 'pointer': '#/x', 'parameters': [], 'security': [{}],
                'responses': {'201': {'description': 'ok'}},
                'requestBody': {'required': True, 'mediaType': 'application/json', 'schema': {
                    'type': 'object', 'required': ['items'],
                    'properties': {'id': {'type': 'string', 'readOnly': True},
                                   'items': {'type': 'array', 'minItems': 1, 'items': {
                                       'type': 'object', 'required': ['sku'],
                                       'properties': {'sku': {'type': 'string', 'pattern': '^[A-Z]+$'},
                                                      'qty': {'type': 'integer', 'minimum': 1}}}}}}}}
    found = ids(endpoint)
    assert {'readonly:body.id', 'required:body.items', 'boundary:body.items:minItems',
            'required:body.items[].sku', 'pattern:body.items[].sku', 'boundary:body.items[].qty:minimum'} <= found
    assert 'auth:missing' not in found  # optional security ({}) means anonymous access is allowed


def scenario(key, covers, category='required', status=400):
    return {'key': key, 'title': f'Scenario {key}', 'category': category, 'condition': f'one change ({key}: {", ".join(covers) or category})',
            'expectedStatus': status, 'covers': covers, 'source': 'requestBody', 'priority': 'P2',
            'needsConfirmation': False, 'confirmationNote': ''}


FITTING = {'positive': ('positive', 201), 'invalid': ('path_params', 400), 'notfound': ('path_params', 404),
           'required': ('required', 400), 'null': ('required', 400), 'type': ('type', 400), 'boundary': ('boundary', 400),
           'enum': ('enum', 400), 'format': ('format', 400), 'pattern': ('format', 400), 'readonly': ('security', 400),
           'header': ('headers', 400)}


def fitting(key, rid):
    """A scenario that really tests the requirement (the code no longer trusts a bare `covers` claim)."""
    kind = rid.split(':', 1)[0]
    if kind == 'status':
        return scenario(key, [rid], 'error_handling' if not rid.endswith(('200', '201', '204')) else 'positive', int(rid.split(':')[1]))
    if kind == 'auth':
        return scenario(key, [rid], 'auth', 403 if rid == 'auth:forbidden' else 401)
    category, status = FITTING.get(kind, ('business', 400))
    return scenario(key, [rid], category, status)


def case(key, title=None):
    return {'scenarioKey': key, 'title': title or f'Case for {key}', 'objective': 'Proves one rule.', 'category': 'required',
            'priority': 'P2', 'preconditions': [], 'request': {'auth': 'valid', 'body': {'name': 'Rex'}},
            'expected': {'status': 400, 'responseSchema': 'error'}, 'testData': '', 'cleanup': [],
            'needsConfirmation': False, 'confirmationNote': ''}


class FakeClaude:
    """Plans all but two requirements, then fills them when asked; writes and reviews every scenario."""

    def __init__(self, drop=2, writer_skips_once=()):
        self.calls, self.drop, self.writer_skips = [], drop, set(writer_skips_once)

    def __call__(self, agent, task, schema, **options):
        self.calls.append((agent, task.get('mode'), task.get('onlyKeys')))
        if agent == 'unit-scenario-planner':
            requirements = [r['id'] for r in task['requirements']]
            if task['mode'] == 'plan':
                keep = requirements[:-self.drop] if self.drop else requirements
                planned = [fitting(f'S{i + 1:02d}', rid) for i, rid in enumerate(keep)]
                return {'scenarios': planned + [scenario(f'S{len(keep) + 1:02d}', ['not-a-requirement'], 'business', 409)]}
            if task['mode'] == 'add-suggested':
                return {'scenarios': [scenario('S01', [], 'business', 409)]}
            # Deliberately reuse an existing key: the helper must renumber it.
            return {'scenarios': [fitting('S01', r['id']) for r in task['missingRequirements']]}
        if agent == 'unit-case-writer':
            keys = [k for k in task['onlyKeys'] if k not in self.writer_skips]
            self.writer_skips.clear()
            prefix = 'Revised case for' if task['mode'] == 'revise' else 'Case for'
            return {'cases': [case(k, f'{prefix} {k}') for k in keys]}
        return {'verdict': 'needs_attention', 'summary': 'One gap.',
                'findings': [{'scenarioKey': 'S01', 'severity': 'major', 'issue': 'Weak assertion', 'suggestion': 'Check the message'}]}


def test_pipeline_fills_gaps_renumbers_and_batches():
    fake = FakeClaude(drop=2, writer_skips_once={'S03'})
    scenarios, rounds = unit_cases.plan(CREATE_PET, PARSED, fake, '.')
    assert rounds == 2 and not gaps(obligations(CREATE_PET, PARSED['securitySchemes']), scenarios)
    keys = [s['key'] for s in scenarios]
    assert len(keys) == len(set(keys))
    assert all('not-a-requirement' not in s['covers'] for s in scenarios)  # unknown ids are dropped
    written = unit_cases.write(CREATE_PET, PARSED, scenarios, fake, '.')
    assert [c['scenarioKey'] for c in written] == keys  # the skipped case was retried
    writer_calls = [c for c in fake.calls if c[0] == 'unit-case-writer']
    assert max(len(c[2]) for c in writer_calls) <= unit_cases.WRITER_BATCH


def test_review_findings_trigger_a_fix_pass():
    fake = FakeClaude(drop=0)
    scenarios, _ = unit_cases.plan(CREATE_PET, PARSED, fake, '.')
    cases = unit_cases.write(CREATE_PET, PARSED, scenarios, fake, '.')
    verdict = {'verdict': 'needs_attention', 'summary': '', 'findings': [
        {'scenarioKey': 'S02', 'severity': 'blocker', 'issue': 'Wrong check type', 'suggestion': 'Use matches_pattern'},
        {'scenarioKey': 'S03', 'severity': 'minor', 'issue': 'Wording', 'suggestion': ''},
        {'scenarioKey': 'checklist', 'severity': 'major', 'issue': 'No persistence check', 'suggestion': 'GET the created pet'}]}
    improved, revised, changed = unit_cases.improve(CREATE_PET, PARSED, scenarios, cases, verdict, fake, '.')
    assert changed and len(improved) == len(scenarios) + 1 and len(revised) == len(improved)
    titles = {c['scenarioKey']: c['title'] for c in revised}
    assert titles['S02'] == 'Revised case for S02' and titles['S03'] == 'Case for S03'  # minor findings are left to QA
    revise_call = next(c for c in fake.calls if c[0] == 'unit-case-writer' and c[1] == 'revise')
    assert revise_call[2] == ['S02']
    nothing = {'verdict': 'ready', 'summary': '', 'findings': [{'scenarioKey': 'S03', 'severity': 'minor', 'issue': 'x', 'suggestion': ''}]}
    assert unit_cases.improve(CREATE_PET, PARSED, scenarios, cases, nothing, fake, '.')[2] == set()


def test_usage_limit_stops_the_job():
    def limited(*_args, **_kwargs):
        raise ClaudeError('Your Claude usage limit has been reached. Try again after it resets.')
    job_input = {'api': PARSED, 'endpoints': [{'id': 'e1', 'details': CREATE_PET}, {'id': 'e2', 'details': GET_PET}]}
    with pytest.raises(ClaudeError, match='Finished 0 of 2'):
        unit_cases.generate(job_input, lambda *a: None, agent=limited)


def setup_project(project):
    lead, pid = project
    assert upload(lead, pid, 'petstore.yaml', PETSTORE, 'application/yaml').status_code == 200
    helper = pair_helper(lead)
    beat(helper)
    endpoints = lead.get(f'/api/projects/{pid}/endpoints').json()['endpoints']
    return lead, pid, helper, {e['operationId']: e['id'] for e in endpoints}


def run_helper(helper_client, agent):
    status = __import__('helper.claude', fromlist=['ClaudeStatus']).ClaudeStatus(installed=True, loggedIn=True)
    handlers = {'unit.generate': lambda job_input, report, submit=None: unit_cases.generate(job_input, report, submit, agent=agent)}
    assert Helper(helper_client, log=lambda _: None, claude_status=lambda: status, handlers=handlers).run_once()


def test_generation_end_to_end_and_review(project, make_user):
    lead, pid, helper, endpoint_ids = setup_project(project)
    job = lead.post(f'/api/projects/{pid}/unit/generate', json={'endpointIds': [endpoint_ids['createPet'], endpoint_ids['getPet']]})
    assert job.status_code == 200, job.text
    assert lead.post(f'/api/projects/{pid}/unit/generate', json={'endpointIds': [endpoint_ids['getPet']]}).status_code == 409
    run_helper(helper, FakeClaude(drop=1))

    summary = lead.get(f'/api/projects/{pid}/unit/endpoints').json()
    assert summary['job']['status'] == 'succeeded'
    rows = {e['id']: e for e in summary['endpoints']}
    create = rows[endpoint_ids['createPet']]
    assert create['coverage']['gaps'] == 0 and create['coverage']['covered'] == create['coverage']['total']
    assert create['cases']['in_review'] == create['caseCount'] > 10
    assert rows[endpoint_ids['listPets']]['coverage'] is None

    detail = lead.get(f'/api/projects/{pid}/unit/endpoints/{endpoint_ids["createPet"]}').json()
    assert all(r['covered'] and r['scenarios'] for r in detail['requirements'])
    assert detail['review']['verdict'] == 'needs_attention'
    cases = detail['cases']
    # The fake reviewer always flags S01, so it is revised and still carries the final review's note.
    # Endpoints finish in parallel, so numbering starts wherever this endpoint's turn came, but each
    # endpoint's cases get one continuous range.
    numbers = [int(c['code'][3:]) for c in cases]
    assert numbers == list(range(numbers[0], numbers[0] + len(numbers)))
    assert cases[0]['title'] == 'Revised case for S01'
    assert cases[0]['findings'][0]['issue'] == 'Weak assertion'
    assert cases[0]['content']['covers'] and cases[0]['createdBy'] == 'Lena Lead'

    # An employee can review: approve, request changes (comment required), reject.
    employee = make_user('Eli Employee')
    lead.post(f'/api/projects/{pid}/members', json={'email': 'eli.employee@example.test'})
    first, second, third = (c['id'] for c in cases[:3])
    assert employee.post(f'/api/projects/{pid}/unit/cases/review', json={'caseIds': [first, second], 'action': 'approve'}).status_code == 200
    assert employee.post(f'/api/projects/{pid}/unit/cases/review', json={'caseIds': [third], 'action': 'needs_changes'}).status_code == 400
    assert employee.post(f'/api/projects/{pid}/unit/cases/review',
                         json={'caseIds': [third], 'action': 'needs_changes', 'comment': 'Use a 51-char name'}).status_code == 200
    approved = lead.get(f'/api/projects/{pid}/unit/cases/{first}').json()
    assert approved['status'] == 'approved' and approved['reviewedBy'] == 'Eli Employee'

    # Editing an approved case sends it back to review; stale revisions are rejected.
    edit = {key: approved['content'][key] for key in ('objective', 'preconditions', 'request', 'expected', 'testData', 'cleanup')}
    edit.update(revision=approved['revision'], title='Edited title', category=approved['category'], priority='P1')
    saved = employee.patch(f'/api/projects/{pid}/unit/cases/{first}', json=edit)
    assert saved.status_code == 200 and saved.json()['status'] == 'in_review' and saved.json()['title'] == 'Edited title'
    assert employee.patch(f'/api/projects/{pid}/unit/cases/{first}', json=edit).status_code == 409

    totals = lead.get(f'/api/projects/{pid}/unit/endpoints').json()['totals']
    assert totals['approved'] == 1 and totals['needs_changes'] == 1

    activity = [a['summary'] for a in lead.get(f'/api/projects/{pid}/activity').json()]
    assert any('requirements covered' in line for line in activity)
    assert any('Eli Employee approved 2 unit test cases' in line for line in activity)


def test_regeneration_keeps_approved_cases(project):
    lead, pid, helper, endpoint_ids = setup_project(project)
    target = endpoint_ids['getPet']
    lead.post(f'/api/projects/{pid}/unit/generate', json={'endpointIds': [target]})
    run_helper(helper, FakeClaude(drop=0))
    cases = lead.get(f'/api/projects/{pid}/unit/endpoints/{target}').json()['cases']
    lead.post(f'/api/projects/{pid}/unit/cases/review', json={'caseIds': [cases[0]['id']], 'action': 'approve'})

    lead.post(f'/api/projects/{pid}/unit/generate', json={'endpointIds': [target]})
    run_helper(helper, FakeClaude(drop=0))
    again = lead.get(f'/api/projects/{pid}/unit/endpoints/{target}').json()['cases']
    assert len(again) == len(cases)  # the approved case kept, its duplicate skipped, the rest replaced
    kept = next(c for c in again if c['id'] == cases[0]['id'])
    assert kept['status'] == 'approved'
    assert len({c['code'] for c in again}) == len(again)


def test_endpoint_failure_is_recorded_and_other_endpoints_continue(project):
    lead, pid, helper, endpoint_ids = setup_project(project)

    class Flaky(FakeClaude):
        def __call__(self, agent, task, schema, **options):
            if task.get('endpoint', {}).get('operationId') == 'getPet':
                raise ClaudeError('Claude returned incomplete unit-scenario-planner output')
            return super().__call__(agent, task, schema, **options)

    lead.post(f'/api/projects/{pid}/unit/generate', json={'endpointIds': [endpoint_ids['getPet'], endpoint_ids['deletePet']]})
    run_helper(helper, Flaky(drop=0))
    rows = {e['id']: e for e in lead.get(f'/api/projects/{pid}/unit/endpoints').json()['endpoints']}
    assert 'incomplete' in rows[endpoint_ids['getPet']]['coverage']['error'] and rows[endpoint_ids['getPet']]['caseCount'] == 0
    assert rows[endpoint_ids['deletePet']]['caseCount'] > 0


def test_generate_requires_connected_helper_and_known_endpoints(project):
    lead, pid = project
    upload(lead, pid, 'petstore.yaml', PETSTORE, 'application/yaml')
    endpoints = lead.get(f'/api/projects/{pid}/endpoints').json()['endpoints']
    response = lead.post(f'/api/projects/{pid}/unit/generate', json={'endpointIds': [endpoints[0]['id']]})
    assert response.status_code == 409 and 'not connected' in response.json()['detail']
    beat(pair_helper(lead))
    assert lead.post(f'/api/projects/{pid}/unit/generate', json={'endpointIds': ['unknown']}).status_code == 400


def test_spec_reupload_marks_cases_outdated(project):
    lead, pid, helper, endpoint_ids = setup_project(project)
    lead.post(f'/api/projects/{pid}/unit/generate', json={'endpointIds': [endpoint_ids['createPet']]})
    run_helper(helper, FakeClaude(drop=0))
    upload(lead, pid, 'petstore.yaml', PETSTORE.replace('maxLength: 50', 'maxLength: 60'), 'application/yaml')
    current = {e['operationId']: e['id'] for e in lead.get(f'/api/projects/{pid}/endpoints').json()['endpoints']}
    detail = lead.get(f'/api/projects/{pid}/unit/endpoints/{current["createPet"]}').json()
    assert detail['coverage']['outdated'] is True and detail['cases'][0]['outdated'] is True

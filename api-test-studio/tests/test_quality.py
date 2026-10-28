"""Unit coverage and writer checks, large-API analysis, role efficiency, agent quality numbers and the prompt eval."""
import json

from contracts.checks import placeholder_problems, schema_problems, unit_case_problems
from contracts.coverage import claim_holds, gaps, obligations
from contracts.flows import chunk_operations, merge_domains
from helper import claude, flow_cases, role_cases, unit_cases

from .test_flows import ENDPOINTS, FakeFlowClaude
from .test_roles import FakeRoleClaude, access_model
from .test_unit_cases import CREATE_PET, PARSED, FakeClaude, scenario


# --- Unit coverage and writer checks -----------------------------------------------------------------------

def test_unit_claims_need_the_right_category_and_status():
    assert claim_holds('required:body.name', scenario('S01', ['required:body.name'], 'required', 400))
    assert not claim_holds('required:body.name', scenario('S01', ['required:body.name'], 'positive', 201))
    assert claim_holds('auth:forbidden', scenario('S02', ['auth:forbidden'], 'auth', 403))
    assert not claim_holds('auth:forbidden', scenario('S02', ['auth:forbidden'], 'auth', 401))
    assert claim_holds('status:409', scenario('S03', ['status:409'], 'business', 409))
    required = obligations(CREATE_PET, PARSED['securitySchemes'])
    claims_all = [scenario('S01', [r['id'] for r in required], 'required', 400)]
    assert 'positive:minimal' in {g['id'] for g in gaps(required, claims_all)}  # a 400 scenario cannot prove success


def test_writer_output_checks():
    good = {'category': 'positive', 'request': {'auth': 'valid', 'headers': {}, 'body': {'name': 'Rex'}},
            'expected': {'status': 201, 'responseSchema': 'success', 'bodyChecks': [{'path': '$.id', 'check': 'exists'}]}}
    assert unit_case_problems(good, CREATE_PET, PARSED['securitySchemes']) == []
    status_only = {**good, 'expected': {'status': 201, 'responseSchema': 'none', 'bodyChecks': []}}
    problems = ' '.join(unit_case_problems(status_only, CREATE_PET, PARSED['securitySchemes']))
    assert 'responseSchema to "success"' in problems and 'add bodyChecks' in problems
    bad = {'category': 'positive', 'request': {'auth': 'valid', 'headers': {'Authorization': 'Bearer x'},
                                               'body': {'name': 5, 'note': '{{random.word}}'}}, 'expected': {'status': 418}}
    problems = ' '.join(unit_case_problems(bad, CREATE_PET, PARSED['securitySchemes']))
    assert 'carries credentials' in problems and 'unknown placeholder' in problems and 'not documented' in problems
    assert 'should be string' in problems
    assert schema_problems({'tag': 'x' * 300}, CREATE_PET['requestBody']['schema']) and placeholder_problems({'a': '{{unique.code}}'}) == []


class WriterBreaksOnce(FakeClaude):
    def __init__(self):
        super().__init__(drop=0)
        self.writer_tasks = []

    def __call__(self, agent, task, schema, **options):
        if agent == 'unit-case-writer':
            self.writer_tasks.append(task)
            cases = super().__call__(agent, task, schema, **options)['cases']
            if 'previousProblems' not in task:
                cases[0]['expected']['status'] = 418
            return {'cases': cases}
        return super().__call__(agent, task, schema, **options)


def test_unit_writer_retries_only_failing_cases_and_counts_check_failures():
    claude.job_model.begin(None)
    fake = WriterBreaksOnce()
    scenarios, _ = unit_cases.plan(CREATE_PET, PARSED, fake, '.')
    cases = unit_cases.write(CREATE_PET, PARSED, scenarios, fake, '.')
    assert len(cases) == len(scenarios) and len(fake.writer_tasks) == 2
    assert list(fake.writer_tasks[1]['previousProblems']) == [scenarios[0]['key']]
    assert fake.writer_tasks[1]['onlyKeys'] == [scenarios[0]['key']]
    stats = claude.job_model.usage()['agents']['unit-case-writer']
    assert stats['checked'] == len(scenarios) + 1 and stats['checkFailed'] == 1


def test_duplicate_scenarios_are_dropped():
    a = scenario('S01', ['required:body.name'])
    assert unit_cases.dedupe([a, {**a, 'key': 'S02'}, scenario('S03', ['type:body.name'], 'type')]) == [a, scenario('S03', ['type:body.name'], 'type')]


# --- Flows: large APIs are analysed in parts ------------------------------------------------------------------

def test_large_apis_are_analysed_in_parts_and_merged():
    many = [{**e, 'operationId': f"{e['operationId']}{i}", 'tags': [f'T{i % 4}']} for i in range(14) for e in ENDPOINTS]
    parts = chunk_operations(many, 30)
    assert sum(map(len, parts)) == len(many) and all(len(p) <= 30 for p in parts)
    merged = merge_domains([
        {'summary': 'short', 'entities': [{'name': 'Pet', 'description': 'a', 'operations': ['a'], 'states': ['x']}],
         'businessRules': [{'key': 'R1', 'rule': 'Names are unique', 'source': 's'}], 'areas': [{'name': 'Pets', 'operations': ['a']}]},
        {'summary': 'a longer summary', 'entities': [{'name': 'pet', 'description': 'longer', 'operations': ['b'], 'states': ['y']}],
         'businessRules': [{'key': 'R1', 'rule': 'names are  unique', 'source': 's'}, {'key': 'R2', 'rule': 'Stock >= 0', 'source': 's'}],
         'areas': [{'name': 'PETS', 'operations': ['b']}]}])
    assert merged['summary'] == 'a longer summary' and len(merged['entities']) == 1
    assert merged['entities'][0]['operations'] == ['a', 'b'] and merged['entities'][0]['description'] == 'longer'
    assert [r['key'] for r in merged['businessRules']] == ['R1', 'R2'] and merged['areas'][0]['operations'] == ['a', 'b']


# --- Roles: routine cases are built in code ---------------------------------------------------------------------

def _role_item(op, base=True):
    endpoint = next(e for e in ENDPOINTS if e['operationId'] == op)
    item = {'id': op, 'details': endpoint}
    if base:
        item['baseCase'] = {'code': 'TC-0001', 'title': 'Delete a pet', 'approved': True, 'objective': 'o',
                            'preconditions': ['Create a pet'], 'cleanup': [], 'testData': '',
                            'request': {'auth': 'valid', 'pathParams': {'petId': '{{created.petId}}'}, 'query': {}, 'headers': {},
                                        'body': None, 'bodyNote': ''},
                            'expected': {'status': 204, 'responseSchema': 'none', 'bodyChecks': [], 'headers': {}, 'notes': ''}}
    return item


def test_routine_role_endpoints_need_no_claude_call():
    from contracts.roles import normalise
    model = normalise(access_model(['deletePet']), [e['operationId'] for e in ENDPOINTS])
    fake = FakeRoleClaude()
    result = role_cases.EndpointRoles(_role_item('deletePet'), {'model': model}, fake, '.').run(lambda *a: None)
    assert fake.calls == []  # nothing for Claude: allowed and denied cases come from the unit case
    allowed, denied = result['cases']
    assert allowed['roles'] == ['Owner'] and allowed['expected']['status'] == 204
    assert denied['roles'] == ['Customer', 'Clerk'] and denied['expected']['status'] == 404 and denied['needsConfirmation']
    assert 'read the record back' in denied['verifyUnchanged'] and denied['preconditions'] == ['As Owner: Create a pet']
    # Without a positive unit case, Claude designs them as before.
    fake = FakeRoleClaude()
    role_cases.EndpointRoles(_role_item('deletePet', base=False), {'model': model}, fake, '.').run(lambda *a: None)
    assert fake.calls and fake.calls[0][:2] == ('role-case-designer', 'design')


def test_ownership_still_goes_to_claude_after_the_routine_cases():
    from contracts.roles import normalise
    model = normalise(access_model(['getOrder']), [e['operationId'] for e in ENDPOINTS])

    class Owner(FakeRoleClaude):
        def __call__(self, agent, task, schema, **options):
            if agent == 'role-case-designer' and task['mode'] == 'complete':
                self.calls.append((agent, 'complete', 'getOrder'))
                from .test_roles import case
                return {'cases': [case('R01', 'ownership', ['Customer'], 404, 'second', 'Other customer is refused')]}
            return super().__call__(agent, task, schema, **options)
    item = _role_item('getOrder')
    item['baseCase']['expected']['status'] = 200
    fake = Owner()
    result = role_cases.EndpointRoles(item, {'model': model}, fake, '.').run(lambda *a: None)
    assert fake.calls[0][:2] == ('role-case-designer', 'complete')
    first, second = result['cases'][:2]
    assert first['kind'] == 'allowed' and first['roles'] == ['Clerk', 'Owner', 'Customer'] and 'TC-0001' in first['testData']
    assert second['key'] == 'R02' and second['kind'] == 'ownership' and second['userSlot'] == 'second'


def test_analyst_is_asked_again_for_operations_it_left_out():
    calls = []

    def agent(name, task, schema, **options):
        calls.append([op['operationId'] for op in task['operations']])
        model = access_model([op['operationId'] for op in task['operations']])
        if len(calls) == 1:
            model['operations'] = [r for r in model['operations'] if r['operationId'] != 'getOrder']
        return model
    ops = [{'operationId': o} for o in ('placeOrder', 'getOrder', 'deletePet')]
    model = role_cases.analyze({'document': {'filename': 'r.csv', 'text': 'x'}, 'api': {}, 'operations': ops}, lambda *a: None, agent=agent)
    assert calls == [['placeOrder', 'getOrder', 'deletePet'], ['getOrder']]
    assert next(r for r in model['model']['operations'] if r['operationId'] == 'getOrder')['own'] == ['Customer']


# --- The prompt eval runs end to end on fixed input ----------------------------------------------------------------

def test_prompt_eval_scores_a_run(tmp_path, monkeypatch):
    from evals import run_eval
    monkeypatch.setattr(run_eval, 'RESULTS', tmp_path)
    for module, fake in ((unit_cases, FakeClaude), (flow_cases, FakeFlowClaude)):
        original = module.generate
        monkeypatch.setattr(module, 'generate', lambda job, report, submit=None, _o=original, _f=fake, **kw: _o(job, report, submit, agent=_f()))
    run_eval.main(['--modules', 'unit,flows', '--endpoints', '2', '--spec', str(run_eval.HERE / 'petstore.yaml')])
    run_eval.main(['--modules', 'unit', '--endpoints', '1'])
    reports = sorted(tmp_path.glob('*.json'))
    assert reports
    summary = json.loads(reports[-1].read_text(encoding='utf-8'))['summary']
    assert 'unitCoverage%' in summary and summary['unitCases'] > 0

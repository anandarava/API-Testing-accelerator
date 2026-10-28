"""Flow test cases: dependency evidence, plan validation, the helper pipeline and portal review."""
import threading

from contracts.flows import dependencies, gaps, requirements, validate_plan
from helper import claude, flow_cases, scripts
from helper.claude import ClaudeError, ClaudeStatus
from helper.runner import Helper
from studio.openapi import parse_spec

from .conftest import EXAMPLES
from .test_scripts import FakeCli, confirmed_project, writer
from .test_unit_cases import setup_project

PARSED = parse_spec((EXAMPLES / 'petstore.yaml').read_text(encoding='utf-8'))
ENDPOINTS = PARSED['endpoints']

DOMAIN = {'summary': 'A pet store.', 'entities': [{'name': 'Pet', 'description': 'A pet', 'identifier': 'id',
                                                   'operations': ['createPet'], 'states': ['available', 'pending']}],
          'relationships': ['An order references a pet'],
          'transitions': [{'entity': 'Pet', 'fromState': 'available', 'toState': 'pending', 'operationId': 'placeOrder', 'condition': ''}],
          'businessRules': [{'key': 'R1', 'rule': 'Only available pets can be ordered', 'source': 'placeOrder description', 'operations': ['placeOrder']}],
          'assumptions': []}


def step(key, op, status, inputs=(), captures=()):
    return {'key': key, 'operationId': op, 'purpose': f'{op} step', 'expectedStatus': status,
            'inputs': [{'target': t, 'source': s} for t, s in inputs], 'captures': [{'name': n, 'path': p} for n, p in captures]}


def outline(key, steps, covers=(), title=None, type='happy_path'):
    return {'key': key, 'title': title or f'Flow {key}', 'type': type, 'goal': 'Prove the journey', 'priority': 'P1',
            'steps': steps, 'covers': list(covers), 'needsConfirmation': False, 'confirmationNote': ''}


LIFECYCLE = outline('F01', [
    step('S1', 'createPet', 201, captures=[('petId', '$.id')]),
    step('S2', 'getPet', 200, inputs=[('path.petId', 'steps.S1.petId')]),
    step('S3', 'updatePet', 200, inputs=[('path.petId', 'steps.S1.petId')]),
    step('S4', 'deletePet', 204, inputs=[('path.petId', 'steps.S1.petId')]),
    step('S5', 'getPet', 404, inputs=[('path.petId', 'steps.S1.petId')]),
])
ORDER = outline('F02', [
    step('S1', 'createPet', 201, captures=[('petId', '$.id')]),
    step('S2', 'placeOrder', 201, inputs=[('body.petId', 'steps.S1.petId')], captures=[('orderId', '$.id')]),
    step('S3', 'getOrder', 200, inputs=[('path.orderId', 'steps.S2.orderId')]),
    step('S4', 'listPets', 200),
], covers=['transition:Pet:available->pending', 'rule:R1'])


def test_dependencies_and_requirements():
    edges = dependencies(ENDPOINTS)
    assert {'from': 'placeOrder', 'to': 'getOrder', 'value': '$.id', 'target': 'path.orderId', 'resource': 'order', 'required': True} in edges
    assert any(e['from'] == 'createPet' and e['to'] == 'placeOrder' and e['target'] == 'body.petId' for e in edges)
    ids = {r['id'] for r in requirements(ENDPOINTS, edges, DOMAIN)}
    assert {'op:createPet', 'op:getOrder', 'dep:getPet:path.petId', 'dep:getOrder:path.orderId',
            'transition:Pet:available->pending', 'rule:R1'} <= ids


def test_plan_validation_catches_broken_data_flow():
    assert validate_plan([LIFECYCLE, ORDER], ENDPOINTS) == []
    broken = outline('F03', [step('S1', 'createPet', 201), step('S2', 'getPet', 200, inputs=[('path.petId', 'steps.S1.petId')]),
                             step('S3', 'nope', 200), step('S4', 'getPet', 418)])
    problems = validate_plan([broken], ENDPOINTS)
    assert any('no earlier step captures' in p for p in problems)
    assert any('nope does not exist' in p for p in problems)
    assert any('418 is not documented' in p for p in problems)


def test_coverage_from_structure_and_covers():
    required = requirements(ENDPOINTS, dependencies(ENDPOINTS), DOMAIN)
    assert gaps(required, [LIFECYCLE, ORDER]) == []
    missing = {g['id'] for g in gaps(required, [LIFECYCLE])}
    assert missing == {'op:placeOrder', 'op:getOrder', 'op:listPets', 'dep:getOrder:path.orderId',
                       'transition:Pet:available->pending', 'rule:R1'}


def success(status):
    """What a writer must expect: a 2xx checks its body, anything else only the status."""
    if 200 <= status < 300:
        return {'status': status, 'responseSchema': 'success', 'bodyChecks': [{'path': '$.id', 'check': 'exists'}],
                'headers': {}, 'notes': ''}
    return {'status': status, 'responseSchema': 'none', 'bodyChecks': [], 'headers': {}, 'notes': ''}


def detailed(o, ops=None):
    steps = [{'key': s['key'], 'operationId': s['operationId'], 'purpose': s['purpose'],
              'request': {'auth': 'valid', 'pathParams': {}, 'query': {}, 'headers': {}, 'body': None, 'bodyNote': ''},
              'expected': success(s['expectedStatus']), 'captures': s['captures']} for s in o['steps']]
    if ops:
        steps = [{**st, 'operationId': op} for st, op in zip(steps, ops)]
    return {'flowKey': o['key'], 'title': o['title'], 'objective': o['goal'], 'type': o['type'], 'priority': o['priority'],
            'preconditions': [], 'steps': steps, 'testData': '', 'cleanup': ['Delete the pet'], 'needsConfirmation': False,
            'confirmationNote': ''}


AREAS = [{'name': 'Pets', 'description': 'Pet catalogue', 'operations': ['listPets', 'createPet', 'getPet', 'updatePet', 'deletePet']},
         {'name': 'Store', 'description': 'Orders', 'operations': ['placeOrder', 'getOrder']}]
STORE = outline('F03', [
    step('S1', 'createPet', 201, captures=[('petId', '$.id')]),
    step('S2', 'placeOrder', 201, inputs=[('body.petId', 'steps.S1.petId')], captures=[('orderId', '$.id')]),
    step('S3', 'getOrder', 200, inputs=[('path.orderId', 'steps.S2.orderId')]),
], title='Order lookup')
JOURNEY = outline('F09', ORDER['steps'][:3], covers=['transition:Pet:available->pending', 'rule:R1'], title='Order journey',
                  type='end_to_end')
PROCESS = {'key': 'P1', 'name': 'Customer orders a pet', 'actors': ['Customer'], 'description': 'A new pet is ordered and the order is read back.',
           'steps': ['createPet', 'placeOrder', 'getOrder'], 'outcome': 'The order exists for the pet'}


class FakeFlowClaude:
    """Answers per design scope, like the real pipeline:

    - domain analysis splits the API into the Pets and Store areas;
    - Pets designs the lifecycle plus one broken flow (fixed on request) and gets a review suggestion;
    - Store designs an order lookup (its first written version has the wrong steps and is retried);
    - the cross-area journeys call designs the order journey;
    - nobody lists pets, so the combined coverage check asks for one more flow.
    """

    def __init__(self, areas=True):
        self.lock = threading.Lock()
        self.calls, self.areas = [], areas
        self.writer_breaks_once = {'Order lookup'}

    def __call__(self, agent, task, schema, **options):
        scope = (task.get('scope') or {}).get('name', 'all')
        with self.lock:
            self.calls.append((agent, task.get('mode'), scope))
        if agent == 'flow-domain-analyst':
            return {**DOMAIN, 'areas': AREAS if self.areas else []}
        if agent == 'flow-process-analyst':
            return {'processes': [PROCESS]}
        if agent == 'flow-designer':
            mode = task['mode']
            if mode == 'plan':
                if scope == 'Pets':
                    broken = outline('F02', [step('S1', 'createPet', 201), step('S2', 'getPet', 200, inputs=[('path.petId', 'steps.S9.petId')])],
                                     title='Broken read')
                    return {'flows': [LIFECYCLE, broken]}
                return {'flows': [STORE if scope == 'Store' else JOURNEY]}
            if mode == 'fix':
                flow = task['flows'][0]
                return {'flows': [{**flow, 'steps': LIFECYCLE['steps'][:2]}]}
            if mode == 'fill-gaps':
                return {'flows': [outline('F01', [step('S1', 'listPets', 200), step('S2', 'createPet', 201)],
                                          covers=['unknown:req'], title='Catalogue listing')]}
            return {'flows': [outline('F01', [step('S1', 'createPet', 201, captures=[('petId', '$.id')]),
                                              step('S2', 'getPet', 200, inputs=[('path.petId', 'steps.S1.petId')])],
                                      title='Created pet is readable', type='data_integrity')]}
        if agent == 'flow-case-writer':
            out = []
            for o in task['outlines']:
                with self.lock:
                    broken = o['title'] in self.writer_breaks_once
                    self.writer_breaks_once.discard(o['title'])
                if broken:
                    out.append(detailed(o, ops=['getPet'] * len(o['steps'])))  # wrong sequence -> rejected, retried
                else:
                    out.append({**detailed(o), 'title': ('Revised ' if task['mode'] == 'revise' else '') + o['title']})
            return {'flows': out}
        first = task['flows'][0]['flowKey']
        findings = [{'flowKey': first, 'severity': 'major', 'issue': 'Deleted state never verified', 'suggestion': 'Add a GET'}]
        if scope == 'Pets':
            findings.append({'flowKey': 'plan', 'severity': 'major', 'issue': 'No read-after-create flow', 'suggestion': 'Create then read'})
        return {'verdict': 'needs_attention', 'summary': f'{scope} close.', 'findings': findings}


def test_pipeline_designs_areas_and_journeys_in_parallel_then_fills_gaps():
    fake = FakeFlowClaude()
    job_input = {'api': {'title': 'Petstore'}, 'endpoints': [{'id': e['operationId'], 'details': e} for e in ENDPOINTS]}
    submitted = []
    assert flow_cases.generate(job_input, lambda *a: None, submitted.append, agent=fake) == {'flows': 6}
    stages = [s['stage'] for s in submitted]
    assert stages[0] == 'domain' and stages[-1] == 'final' and stages.count('group') == 3
    assert {s['group'] for s in submitted if s['stage'] == 'group'} == {flow_cases.JOURNEYS, 'Pets', 'Store'}
    plan = [o for s in submitted for o in s.get('plan', [])]
    keys = [o['key'] for o in plan]
    assert len(keys) == len(set(keys)) == 6 and validate_plan(plan, ENDPOINTS) == []
    assert all('unknown:req' not in o['covers'] for o in plan)
    titles = {f['title'] for s in submitted for f in s.get('flows', [])}
    assert {'Revised Order lookup', 'Created pet is readable', 'Revised Catalogue listing', 'Broken read'} <= titles
    assert any(t.startswith('Revised ') and 'Order journey' in t for t in titles)
    designer = [(mode, scope) for agent, mode, scope in fake.calls if agent == 'flow-designer']
    assert ('plan', flow_cases.JOURNEYS) in designer and ('plan', 'Pets') in designer and ('plan', 'Store') in designer
    assert ('fix', 'Pets') in designer and ('add-suggested', 'Pets') in designer and ('fill-gaps', 'all') in designer
    # Each group sends its own review; the final step sends only the coverage-gap review.
    reviews = {s['group']: s['review'] for s in submitted if s['stage'] == 'group'}
    assert reviews['Pets']['summary'] == 'Pets close.' and submitted[-1]['review']['summary'] == 'Coverage gaps: all close.'


def test_single_area_api_skips_the_journeys_call():
    fake = FakeFlowClaude(areas=False)
    one_area = [e for e in ENDPOINTS if e['operationId'] in ('createPet', 'getPet', 'updatePet', 'deletePet', 'listPets')]
    for e in one_area:
        e['tags'] = ['Pets']
    job_input = {'api': {}, 'endpoints': [{'id': e['operationId'], 'details': e} for e in one_area]}
    submitted = []
    flow_cases.generate(job_input, lambda *a: None, submitted.append, agent=fake)
    assert [s['group'] for s in submitted if s['stage'] == 'group'] == ['Pets']
    assert all(scope != flow_cases.JOURNEYS for _, _, scope in fake.calls)


def run_flow_helper(helper, agent):
    status = ClaudeStatus(installed=True, loggedIn=True)
    handlers = {'flows.generate': lambda job_input, report, submit=None: flow_cases.generate(job_input, report, submit, agent=agent)}
    assert Helper(helper, log=lambda _: None, claude_status=lambda: status, handlers=handlers).run_once()


def test_portal_flow_review_edit_and_scripts(project, tmp_path, monkeypatch, make_user):
    monkeypatch.setattr(scripts.shutil, 'which', lambda name: 'node')
    lead, pid, helper, _, root, view = confirmed_project(project, tmp_path)
    assert lead.post(f'/api/projects/{pid}/flows/generate').status_code == 200
    assert lead.post(f'/api/projects/{pid}/flows/generate').status_code == 409
    run_flow_helper(helper, FakeFlowClaude())

    data = lead.get(f'/api/projects/{pid}/flows').json()
    assert data['job']['status'] == 'succeeded' and data['analysis']['domain']['summary'] == 'A pet store.'
    assert [a['name'] for a in data['analysis']['domain']['areas']] == ['Pets', 'Store']
    assert data['analysis']['covered'] == data['analysis']['total'] and data['totals']['in_review'] == 6
    review = data['analysis']['review']
    assert {a['name'] for a in review['areas']} == {flow_cases.JOURNEYS, 'Pets', 'Store', 'Coverage gaps'}  # groups finish in any order
    pets = next(a for a in review['areas'] if a['name'] == 'Pets')
    assert pets['summary'] == 'Pets close.' and pets['verdict'] == 'needs_attention'
    assert {f['area'] for f in review['findings']} >= {'Pets', 'Store'}
    flows = {f['title']: f for f in data['flows']}
    lifecycle = flows['Revised Flow F01']  # the Pets reviewer flagged it, so the fix pass revised it
    assert lifecycle['category'] == 'happy_path' and lifecycle['content']['steps'][0]['operationId'] == 'createPet'
    assert lifecycle['findings'][0]['issue'] == 'Deleted state never verified'
    assert flows['Revised Order lookup']['content']['area'] == 'Store' and flows['Revised Catalogue listing']['content']['area'] == 'Coverage gaps'
    assert {k: v for k, v in data['operations']['getOrder'].items() if k != 'summary'} == {'method': 'GET', 'path': '/orders/{orderId}'}
    activity = [a['summary'] for a in lead.get(f'/api/projects/{pid}/activity').json()]
    assert any('2 business areas' in line for line in activity) and any('for Pets' in line for line in activity)

    # Editing validates operations, refreshes the outline and sends the flow back to review.
    target = lifecycle
    edit = {'revision': target['revision'], 'title': 'Pet lifecycle', 'objective': 'x', 'type': 'state_transition', 'priority': 'P1',
            'preconditions': [], 'steps': target['content']['steps'], 'testData': '', 'cleanup': []}
    bad = {**edit, 'steps': [{**target['content']['steps'][0], 'operationId': 'nope'}, target['content']['steps'][1]]}
    assert lead.patch(f'/api/projects/{pid}/flows/{target["id"]}', json=bad).status_code == 400
    saved = lead.patch(f'/api/projects/{pid}/flows/{target["id"]}', json=edit)
    assert saved.status_code == 200 and saved.json()['title'] == 'Pet lifecycle'
    assert saved.json()['content']['outline']['type'] == 'state_transition'

    # Review uses the shared review action; approved flows appear on the Scripts page.
    lead.put(f'/api/projects/{pid}/framework/profile', json={'revision': view['revision'], 'profile': view['profile'], 'confirm': True})
    lead.post(f'/api/projects/{pid}/unit/cases/review', json={'caseIds': [target['id']], 'action': 'approve'})
    rows = lead.get(f'/api/projects/{pid}/scripts').json()['flows']
    assert [r['id'] for r in rows] == [target['id']] and rows[0]['state'] == 'not_generated' and rows[0]['steps'] == 5
    other = flows['Revised Order lookup']['id']
    assert lead.post(f'/api/projects/{pid}/scripts/generate', json={'flowIds': [other]}).status_code == 400
    assert lead.post(f'/api/projects/{pid}/scripts/generate', json={'flowIds': [target['id']]}).status_code == 200

    cli = FakeCli(tsc_failures=0)
    cli.expected = 1
    status = ClaudeStatus(installed=True, loggedIn=True)
    handlers = {'scripts.generate': lambda job_input, report, submit=None: scripts.generate(job_input, report, submit, writer([]), cli)}
    assert Helper(helper, log=lambda _: None, claude_status=lambda: status, handlers=handlers).run_once()
    detail = lead.get(f'/api/projects/{pid}/scripts/flow/{target["id"]}').json()
    assert detail['state'] == 'up_to_date' and detail['filePath'] == 'tests/api/flows/pet-lifecycle.flow.spec.ts'
    scripted = {f['id']: f for f in lead.get(f'/api/projects/{pid}/flows').json()['flows']}
    assert scripted[target['id']]['script'] == 'current'


def test_flow_generation_requires_spec_and_helper(project):
    lead, pid = project
    assert lead.post(f'/api/projects/{pid}/flows/generate').status_code == 400
    lead2, pid2, helper, _ = setup_project((lead, pid))
    assert lead2.post(f'/api/projects/{pid2}/flows/generate').status_code == 200


def test_structured_progress_tracks_stages_and_areas():
    from contracts.flows import FlowProgress
    reports = []
    job_input = {'api': {}, 'endpoints': [{'id': e['operationId'], 'details': e} for e in ENDPOINTS]}
    flow_cases.generate(job_input, lambda message, percent, detail=None: reports.append((message, percent, detail)),
                        lambda result: None, agent=FakeFlowClaude())
    details = [FlowProgress.model_validate(d) for _, _, d in reports]
    assert [d.stage for d in details][0] == 'analyze' and details[-1].stage == 'done'
    stages = list(dict.fromkeys(d.stage for d in details))
    assert stages == ['analyze', 'design', 'coverage', 'done']
    design = [d for d in details if d.stage == 'design']
    assert design[0].areas == 2 and [g.name for g in design[0].groups] == [flow_cases.JOURNEYS, 'Pets', 'Store']
    assert all(g.status == 'waiting' for g in design[0].groups)
    assert any(g.status == 'working' and g.step for d in design for g in d.groups)
    last = details[-1]
    assert all(g.status == 'done' and g.finishedAt >= g.startedAt for g in last.groups)
    assert last.savedFlows == 6 and last.gapFlows is not None
    assert set(last.stageStartedAt) == {'analyze', 'design', 'coverage', 'done'}


def test_portal_stores_flow_progress_detail(project, tmp_path):
    lead, pid, helper, *_ = confirmed_project(project, tmp_path)
    job = lead.post(f'/api/projects/{pid}/flows/generate').json()
    claimed = helper.post('/api/helper/jobs/claim').json()['job']
    detail = {'stage': 'design', 'operations': 12, 'areas': 2, 'parallel': 2, 'savedFlows': 3,
              'groups': [{'name': 'Pets', 'status': 'done', 'step': 'saved', 'flows': 3, 'startedAt': 1.0, 'finishedAt': 2.0}],
              'stageStartedAt': {'analyze': 0.5, 'design': 1.0}}
    assert helper.post(f"/api/helper/jobs/{claimed['id']}/progress", json={'message': 'x', 'percent': 40, 'detail': detail}).status_code == 200
    stored = lead.get(f'/api/projects/{pid}/jobs/{job["id"]}').json()['progress']['detail']
    assert stored['groups'][0]['name'] == 'Pets' and stored['savedFlows'] == 3
    bad = {**detail, 'stage': 'nonsense'}
    assert helper.post(f"/api/helper/jobs/{claimed['id']}/progress", json={'message': 'x', 'detail': bad}).status_code == 422


class LimitOnStore(FakeFlowClaude):
    """Hits the Claude usage limit when the Store area is designed."""

    def __call__(self, agent, task, schema, **options):
        if agent == 'flow-designer' and task.get('mode') == 'plan' and (task.get('scope') or {}).get('name') == 'Store':
            with self.lock:
                self.calls.append((agent, 'plan', 'Store'))
            raise ClaudeError(claude.friendly_failure("You've hit your org's monthly spend limit · run /usage-credits"))
        return super().__call__(agent, task, schema, **options)


def test_stopped_design_continues_without_redoing_finished_areas(project, tmp_path):
    lead, pid, helper, *_ = confirmed_project(project, tmp_path)
    lead.post(f'/api/projects/{pid}/flows/generate')
    run_flow_helper(helper, LimitOnStore())
    data = lead.get(f'/api/projects/{pid}/flows').json()
    assert data['job']['status'] == 'failed' and 'spend limit' in data['job']['error'] and 'Continue generation' in data['job']['error']
    assert data['resume'] == {'doneGroups': 2, 'totalGroups': 3, 'flows': len(data['flows'])}
    before = {f['id']: f['code'] for f in data['flows']}
    keys_before = {f['scenarioKey'] for f in data['flows']}
    assert {f['content']['area'] for f in data['flows']} == {flow_cases.JOURNEYS, 'Pets'}

    job = lead.post(f'/api/projects/{pid}/flows/continue').json()
    assert lead.post(f'/api/projects/{pid}/flows/continue').status_code == 409  # already running
    fake = FakeFlowClaude()
    run_flow_helper(helper, fake)

    assert not any(agent == 'flow-domain-analyst' for agent, _, _ in fake.calls)
    planned = {scope for agent, mode, scope in fake.calls if agent == 'flow-designer' and mode == 'plan'}
    assert planned == {'Store'}
    data = lead.get(f'/api/projects/{pid}/flows').json()
    assert data['job']['id'] == job['id'] and data['job']['status'] == 'succeeded' and data['resume'] is None
    after = {f['id']: f['code'] for f in data['flows']}
    assert all(after.get(i) == c for i, c in before.items())  # earlier flows are kept as they were
    keys = [f['scenarioKey'] for f in data['flows']]
    assert len(keys) == len(set(keys)) and keys_before < set(keys)
    assert {f['content']['area'] for f in data['flows']} >= {flow_cases.JOURNEYS, 'Pets', 'Store'}
    assert data['analysis']['covered'] == data['analysis']['total']
    assert 'Pets' in data['analysis']['review']['summary']  # earlier reviews survive the continued final step
    assert lead.post(f'/api/projects/{pid}/flows/continue').status_code == 409  # nothing left to continue


def test_continue_needs_a_saved_analysis_and_the_same_spec(project, tmp_path):
    lead, pid, helper, *_ = confirmed_project(project, tmp_path)
    assert lead.post(f'/api/projects/{pid}/flows/continue').status_code == 409
    lead.post(f'/api/projects/{pid}/flows/generate')

    def no_analysis(agent, task, schema, **options):
        raise ClaudeError(claude.friendly_failure('usage limit reached'))
    run_flow_helper(helper, no_analysis)
    assert lead.get(f'/api/projects/{pid}/flows').json()['resume'] is None  # stopped before anything was saved
    assert lead.post(f'/api/projects/{pid}/flows/continue').status_code == 409


def test_continue_works_for_jobs_that_did_not_record_finished_groups(project, tmp_path):
    from studio.db import SessionLocal
    from studio.models import Job
    lead, pid, helper, *_ = confirmed_project(project, tmp_path)
    job = lead.post(f'/api/projects/{pid}/flows/generate').json()
    run_flow_helper(helper, LimitOnStore())
    with SessionLocal() as db:  # what an older portal stored: no record of finished groups
        stored = db.get(Job, job['id'])
        stored.result = None
        db.commit()
    assert lead.get(f'/api/projects/{pid}/flows').json()['resume']['doneGroups'] == 2


def test_duplicate_journeys_are_dropped_across_groups():
    pipe = flow_cases.FlowPipeline({}, ENDPOINTS, FakeFlowClaude(), '.', lambda *a: None)
    first = pipe.unique([STORE])
    again = pipe.unique([{**STORE, 'key': 'F44', 'title': 'Same journey, other area'}])
    other_type = pipe.unique([{**STORE, 'key': 'F45', 'type': 'data_integrity'}])
    assert [f['key'] for f in first] == ['F03'] and again == [] and [f['key'] for f in other_type] == ['F45']

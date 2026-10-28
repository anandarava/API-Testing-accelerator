"""End-to-end coverage: business processes become requirements, journeys cover them, and existing designs can add them."""
from contracts.flows import (claim_holds, cross_area_requirements, gaps, in_order, key_steps, proof, relevant_requirements, requirements,
                             satisfied, uncovered_areas, validate_processes)
from helper import flow_cases
from helper.claude import ClaudeError

from .test_flows import AREAS, DOMAIN, ENDPOINTS, FakeFlowClaude, PROCESS, detailed, outline, run_flow_helper, step
from .test_scripts import confirmed_project

UPDATE_THEN_ORDER = {'key': 'P2', 'name': 'Customer updates a pet, then orders it', 'actors': ['Customer'],
                     'steps': ['createPet', 'updatePet', 'placeOrder', 'getOrder'], 'outcome': 'The order exists'}
E2E = outline('F01', [step('S1', 'createPet', 201, captures=[('petId', '$.id')]),
                      step('S2', 'updatePet', 200, inputs=[('path.petId', 'steps.S1.petId')]),
                      step('S3', 'placeOrder', 201, inputs=[('body.petId', 'steps.S1.petId')], captures=[('orderId', '$.id')]),
                      step('S4', 'getOrder', 200, inputs=[('path.orderId', 'steps.S3.orderId')])],
              covers=['process:P2'], title='Update and order a pet', type='end_to_end')


def domain(*processes):
    return {**DOMAIN, 'areas': AREAS, 'processes': list(processes)}


def test_process_requirement_needs_its_calls_in_order():
    required = requirements(ENDPOINTS, [], domain(PROCESS))
    item = next(r for r in required if r['id'] == 'process:P1')
    assert item['category'] == 'process' and item['check'] == {'sequence': ['createPet', 'placeOrder', 'getOrder']}
    assert 'in this order' in proof(item['check'])
    ordered = outline('F01', [step('S1', 'createPet', 201), step('S2', 'listPets', 200), step('S3', 'placeOrder', 201),
                              step('S4', 'getOrder', 200)])
    shuffled = outline('F02', [step('S1', 'placeOrder', 201), step('S2', 'createPet', 201), step('S3', 'getOrder', 200)])
    assert claim_holds(ordered, item['check']) and not claim_holds(shuffled, item['check'])
    # Proven by structure, even when the flow does not claim it; a wrong order never counts.
    assert 'process:P1' in satisfied([ordered], {r['id']: r.get('check') for r in required})
    assert 'process:P1' in {g['id'] for g in gaps(required, [shuffled])}
    assert in_order(['a', 'x', 'b', 'c'], ['a', 'b', 'c']) and not in_order(['a', 'c'], ['a', 'b', 'c'])


def test_coverage_needs_the_state_changes_and_the_outcome_read_not_every_look_up():
    methods = {'login': 'POST', 'listDoctors': 'GET', 'book': 'POST', 'getInvoice': 'GET', 'pay': 'POST', 'myPayments': 'GET'}
    assert key_steps(['login', 'listDoctors', 'book', 'getInvoice', 'pay', 'myPayments'], methods) == ['login', 'book', 'pay', 'myPayments']
    assert key_steps(['listDoctors', 'getInvoice'], methods) == ['listDoctors', 'getInvoice']  # nothing changes: keep all
    assert key_steps(['book', 'listDoctors'], {'book': 'POST'}) == ['book', 'listDoctors']
    required = requirements(ENDPOINTS, [], domain({**PROCESS, 'steps': ['createPet', 'listPets', 'placeOrder', 'getPet', 'getOrder']}))
    check = next(r['check'] for r in required if r['id'] == 'process:P1')
    assert check == {'sequence': ['createPet', 'placeOrder', 'getOrder']}


def test_processes_are_cleaned_and_routed_to_the_right_design_call():
    cleaned = validate_processes([
        {**PROCESS, 'key': 'P9', 'steps': ['createPet', 'nope', 'placeOrder', 'placeOrder', 'getOrder']},
        {**PROCESS, 'key': 'P3', 'name': 'Same journey again'},
        {**PROCESS, 'key': 'P4', 'steps': ['createPet']},
        {**PROCESS, 'key': 'P5', 'name': 'Pet catalogue', 'steps': ['createPet', 'listPets']},
    ], ENDPOINTS)
    assert [(p['key'], p['steps']) for p in cleaned] == [('P1', ['createPet', 'placeOrder', 'getOrder']), ('P2', ['createPet', 'listPets'])]
    model = domain(*cleaned)
    required = requirements(ENDPOINTS, [], model)
    journeys = {r['id'] for r in cross_area_requirements(required, model, AREAS)}
    pets = {r['id'] for r in relevant_requirements(required, set(AREAS[0]['operations']), model)}
    assert 'process:P1' in journeys and 'process:P1' not in pets  # crosses Pets and Store
    assert 'process:P2' in pets and 'process:P2' not in journeys  # stays inside Pets
    assert [a['name'] for a in uncovered_areas([cleaned[1]], AREAS)] == ['Store']


class ProcessFake(FakeFlowClaude):
    """The first catalog misses the Store area, so the analyst is asked once more."""

    def __call__(self, agent, task, schema, **options):
        if agent == 'flow-process-analyst':
            with self.lock:
                self.calls.append((agent, task['mode'], 'all'))
            if task['mode'] == 'catalog':
                return {'processes': [{**PROCESS, 'key': 'P1', 'name': 'Pet catalogue', 'steps': ['createPet', 'listPets']}]}
            assert task['missingAreas'] == ['Store'] and task['existingProcesses'][0]['key'] == 'P1'
            return {'processes': [{**PROCESS, 'key': 'P2'}]}
        return super().__call__(agent, task, schema, **options)


def test_analysis_lists_processes_until_every_area_is_in_one():
    fake = ProcessFake()
    pipeline = flow_cases.FlowPipeline({}, ENDPOINTS, fake, '.', lambda *a: None)
    model = pipeline.analyze()
    assert [p['name'] for p in model['processes']] == ['Pet catalogue', 'Customer orders a pet']
    assert [mode for agent, mode, _ in fake.calls if agent == 'flow-process-analyst'] == ['catalog', 'add']
    assert {'process:P1', 'process:P2'} <= {r['id'] for r in pipeline.required}


def test_many_processes_are_designed_in_parallel_batches():
    processes = [{'id': f'process:P{i}', 'category': 'process'} for i in range(1, 15)]
    rule = {'id': 'rule:R1', 'category': 'business_rule'}
    batches = flow_cases.FlowPipeline.design_batches({'kind': 'journeys', 'requirements': processes + [rule]})
    assert [len(b) for b in batches] == [7, 6, 2] and rule in batches[0]
    area = {'kind': 'area', 'requirements': processes}
    assert flow_cases.FlowPipeline.design_batches(area) == [processes]


class JourneysFake(FakeFlowClaude):
    """An existing design without processes; adding journeys finds two, one already covered by the order journey."""

    def __init__(self, fail=False):
        super().__init__()
        self.fail, self.designed = fail, []

    def __call__(self, agent, task, schema, **options):
        if agent == 'flow-process-analyst':
            with self.lock:
                self.calls.append((agent, task['mode'], 'all'))
            return {'processes': [PROCESS, UPDATE_THEN_ORDER]}
        if agent == 'flow-designer' and task.get('mode') == 'plan':
            if self.fail:
                raise ClaudeError('The model returned nothing useful.')
            self.designed.append([r['id'] for r in task['requirements']])
            return {'flows': [E2E]}
        if agent == 'flow-case-writer' and any(o['title'] == E2E['title'] for o in task['outlines']):
            return {'flows': [detailed(o) for o in task['outlines']]}
        return super().__call__(agent, task, schema, **options)


class NoProcesses(FakeFlowClaude):
    def __call__(self, agent, task, schema, **options):
        if agent == 'flow-process-analyst':
            raise ClaudeError('Claude returned incomplete flow-process-analyst output.')
        return super().__call__(agent, task, schema, **options)


def test_fill_gaps_adds_only_the_missing_end_to_end_journeys(project, tmp_path):
    lead, pid, helper, *_ = confirmed_project(project, tmp_path)
    assert lead.post(f'/api/projects/{pid}/flows/fill-gaps').status_code == 409  # nothing designed yet
    lead.post(f'/api/projects/{pid}/flows/generate')
    run_flow_helper(helper, NoProcesses())  # an older design: no business processes
    before = lead.get(f'/api/projects/{pid}/flows').json()
    assert before['analysis']['domain']['processes'] == [] and before['totals']['in_review'] == 6

    fake = JourneysFake()
    assert lead.post(f'/api/projects/{pid}/flows/fill-gaps').status_code == 200
    run_flow_helper(helper, fake)
    after = lead.get(f'/api/projects/{pid}/flows').json()
    assert after['job']['status'] == 'succeeded'
    assert [p['name'] for p in after['analysis']['domain']['processes']] == [PROCESS['name'], UPDATE_THEN_ORDER['name']]
    assert fake.designed == [['process:P2']]  # P1 is already proven by the existing order journey
    added = [f for f in after['flows'] if f['title'].endswith('Update and order a pet')]
    assert len(added) == 1 and added[0]['category'] == 'end_to_end' and added[0]['content']['area'] == flow_cases.JOURNEYS
    assert after['totals']['in_review'] == 7  # nothing was replaced
    processes = {r['id']: r['covered'] for r in after['analysis']['requirements'] if r['category'] == 'process'}
    assert processes == {'process:P1': True, 'process:P2': True}

    # Every process is covered now: a second run designs nothing.
    again = JourneysFake()
    assert lead.post(f'/api/projects/{pid}/flows/fill-gaps').status_code == 200
    run_flow_helper(helper, again)
    assert again.designed == [] and not any(agent == 'flow-process-analyst' for agent, _, _ in again.calls)
    assert lead.get(f'/api/projects/{pid}/flows').json()['totals']['in_review'] == 7


def test_failed_fill_gaps_job_is_not_offered_as_a_stopped_design(project, tmp_path):
    lead, pid, helper, *_ = confirmed_project(project, tmp_path)
    lead.post(f'/api/projects/{pid}/flows/generate')
    run_flow_helper(helper, NoProcesses())
    lead.post(f'/api/projects/{pid}/flows/fill-gaps')
    run_flow_helper(helper, JourneysFake(fail=True))
    data = lead.get(f'/api/projects/{pid}/flows').json()
    assert data['job']['status'] == 'failed' and data['resume'] is None and data['totals']['in_review'] == 6


def test_fill_gaps_also_closes_gaps_that_are_not_processes(project, tmp_path):
    lead, pid, helper, *_ = confirmed_project(project, tmp_path)
    lead.post(f'/api/projects/{pid}/flows/generate')
    run_flow_helper(helper, FakeFlowClaude())  # its one business process is covered by the order journey
    flows = lead.get(f'/api/projects/{pid}/flows').json()
    assert flows['analysis']['covered'] == flows['analysis']['total']
    # Remove the only flow that lists pets: listPets is no longer used by any flow.
    listing = next(f for f in flows['flows'] if f['title'] == 'Revised Catalogue listing')
    lead.delete(f"/api/projects/{pid}/unit/cases/{listing['id']}")
    gap = lead.get(f'/api/projects/{pid}/flows').json()['analysis']
    assert gap['covered'] < gap['total']

    fake = FakeFlowClaude()
    assert lead.post(f'/api/projects/{pid}/flows/fill-gaps').status_code == 200
    run_flow_helper(helper, fake)
    after = lead.get(f'/api/projects/{pid}/flows').json()
    assert after['job']['status'] == 'succeeded' and after['analysis']['covered'] == after['analysis']['total']
    # No business process was missing, so no journeys were designed; the usual gap round added the flow.
    assert not any(scope == flow_cases.JOURNEYS for agent, _, scope in fake.calls if agent == 'flow-designer')
    assert any(mode == 'fill-gaps' for agent, mode, _ in fake.calls if agent == 'flow-designer')
    refilled = [f for f in after['flows'] if f['title'] == 'Revised Catalogue listing']
    assert len(refilled) == 1 and refilled[0]['content']['area'] == 'Coverage gaps'
    assert after['totals']['in_review'] == flows['totals']['in_review']  # nothing else was replaced

"""Edge-case coverage is proven by the flows themselves, writer output is checked, and reviews stay focused."""
import json
import subprocess

from sqlalchemy import create_engine, inspect, text

from contracts.flows import (claim_holds, dependencies, for_prompt, gaps, requirements, unproven_claims, validate_plan)
from helper import claude, flow_cases

from .conftest import beat, pair_helper
from .test_flows import DOMAIN, ENDPOINTS, FakeFlowClaude, detailed, outline, step
from .test_models import Answer, start_job

RICH = {**DOMAIN,
        'entities': [{**e, 'lockedStates': ['sold']} if e['name'] == 'Pet' else e for e in DOMAIN['entities']],
        'businessRules': [{'key': 'R1', 'rule': 'A pet can be ordered once', 'source': 'placeOrder', 'operations': ['placeOrder'],
                           'kind': 'uniqueness'},
                          {'key': 'R2', 'rule': 'Retries with one Idempotency-Key do not duplicate', 'source': 'createPet',
                           'operations': ['createPet'], 'kind': 'idempotency'}],
        'transitions': DOMAIN['transitions'] + [{'entity': 'Pet', 'fromState': 'pending', 'toState': 'sold', 'operationId': 'updatePet',
                                                 'condition': ''}],
        'sideEffects': [{'operationId': 'placeOrder', 'effect': 'the pet becomes pending', 'verifyWith': 'getPet'}]}
CREATE = step('S1', 'createPet', 201, captures=[('petId', '$.id')])
ORDER = step('S2', 'placeOrder', 201, inputs=[('body.petId', 'steps.S1.petId')])


def required():
    return {r['id']: r for r in requirements(ENDPOINTS, dependencies(ENDPOINTS), RICH)}


def test_claims_count_only_when_the_flow_proves_them():
    req = required()
    happy = outline('F01', [CREATE, ORDER], covers=['rule:R1'])
    assert not claim_holds(happy, req['rule:R1']['check'])  # a uniqueness rule needs a refused step
    duplicate = outline('F02', [CREATE, ORDER, step('S3', 'placeOrder', 409, inputs=[('body.petId', 'steps.S1.petId')])],
                        covers=['rule:R1'], type='negative')
    assert claim_holds(duplicate, req['rule:R1']['check'])
    retry = outline('F03', [CREATE, step('S2', 'createPet', 201)], covers=['rule:R2'])
    assert claim_holds(retry, req['rule:R2']['check']) and not claim_holds(outline('F04', [CREATE, ORDER]), req['rule:R2']['check'])
    effect_id = next(i for i in req if i.startswith('effect:placeOrder'))
    seen = outline('F05', [CREATE, ORDER, step('S3', 'getPet', 200, inputs=[('path.petId', 'steps.S1.petId')])], covers=[effect_id])
    assert claim_holds(seen, req[effect_id]['check']) and not claim_holds(outline('F06', [CREATE, ORDER]), req[effect_id]['check'])
    locked = req['locked:Pet:sold']
    sold_then_edit = outline('F07', [CREATE, step('S2', 'updatePet', 200, inputs=[('path.petId', 'steps.S1.petId')]),
                                     step('S3', 'updatePet', 400, inputs=[('path.petId', 'steps.S1.petId')])])
    assert claim_holds(sold_then_edit, locked['check'])
    assert unproven_claims([happy, duplicate], list(req.values())) == {'F01': ['rule:R1']}
    assert 'rule:R1' in {g['id'] for g in gaps(list(req.values()), [happy])}


def test_requirements_reach_agents_with_a_proof_sentence_and_without_machine_checks():
    shown = {r['id']: r for r in for_prompt(list(required().values()))}
    assert '4xx' in shown['rule:R1']['proof'] and 'twice' in shown['rule:R2']['proof']
    assert 'later getPet step' in shown[next(i for i in shown if i.startswith('effect:'))]['proof']
    assert all('check' not in r for r in shown.values())


def test_captures_must_read_a_documented_response_field():
    bad = outline('F01', [step('S1', 'createPet', 201, captures=[('petId', '$.petIdentifier')]),
                          step('S2', 'getPet', 200, inputs=[('path.petId', 'steps.S1.petId')])])
    problems = validate_plan([bad], ENDPOINTS)
    assert any("does not return a field 'petIdentifier'" in p for p in problems)
    assert validate_plan([outline('F02', [CREATE, step('S2', 'getPet', 200, inputs=[('path.petId', 'steps.S1.petId')])])], ENDPOINTS) == []


class WriterBreaksPlaceholders(FakeFlowClaude):
    """The first writer answer uses a value before it is captured; the retry gets the problems and fixes it."""

    def __init__(self):
        super().__init__()
        self.writer_tasks = []

    def __call__(self, agent, task, schema, **options):
        if agent == 'flow-case-writer' and task['mode'] == 'write':
            self.writer_tasks.append(task)
            flows = []
            for o in task['outlines']:
                flow = detailed(o)
                if 'previousProblems' not in task:
                    flow['steps'][0]['request']['pathParams'] = {'petId': '{{steps.S9.petId}}'}
                flows.append(flow)
            return {'flows': flows}
        return super().__call__(agent, task, schema, **options)


def test_writer_output_is_checked_and_only_failing_flows_are_retried():
    fake = WriterBreaksPlaceholders()
    pipe = flow_cases.FlowPipeline({}, ENDPOINTS, fake, '.', lambda *a: None)
    pipe.restore(json.loads(json.dumps({**DOMAIN, 'areas': []})), [])
    lifecycle = outline('F01', [CREATE, step('S2', 'getPet', 200, inputs=[('path.petId', 'steps.S1.petId')])])
    written = pipe.write([lifecycle])
    assert list(written) == ['F01'] and len(fake.writer_tasks) == 2
    assert 'before any earlier step captures it' in fake.writer_tasks[1]['previousProblems']['F01'][0]


def test_writer_batches_are_sized_by_steps():
    long = [outline(f'F0{i}', [step(f'S{n}', 'getPet', 200) for n in range(1, 31)]) for i in range(1, 4)]
    short = [outline(f'F1{i}', [CREATE, step('S2', 'getPet', 200)]) for i in range(7)]
    assert [len(b) for b in flow_cases.FlowPipeline.batches(long)] == [1, 1, 1]  # 30-step journeys get their own call
    assert [len(b) for b in flow_cases.FlowPipeline.batches(short)] == [5, 2]  # short flows: at most 5 per call


def test_final_review_rechecks_only_the_changed_flows():
    fake = FakeFlowClaude()
    reviews = []
    original = fake.__call__

    def agent(name, task, schema, **options):
        if name == 'flow-reviewer':
            reviews.append((task['mode'], [f['flowKey'] for f in task['flows']]))
        return original(name, task, schema, **options)
    job_input = {'api': {}, 'endpoints': [{'id': e['operationId'], 'details': e} for e in ENDPOINTS]}
    flow_cases.generate(job_input, lambda *a: None, lambda r: None, agent=agent)
    rechecks = [keys for mode, keys in reviews if mode == 'recheck']
    first = [keys for mode, keys in reviews if mode == 'review']
    reviewed, rechecked = set().union(*map(set, first)), set().union(*map(set, rechecks))
    assert rechecks and reviewed - rechecked  # flows the reviewer did not flag are not reviewed a second time
    assert rechecked - reviewed  # flows added from the reviewer's suggestions are


def test_writer_model_is_used_only_for_writing_flow_steps(project, monkeypatch):
    monkeypatch.setattr(claude, 'claude_command', lambda: ['claude'])
    lead, pid = project
    helper = pair_helper(lead)
    beat(helper)
    assert lead.put('/api/me/preferences', json={'claudeModel': 'opus', 'writerModel': 'sonnet'}).json()['writerModel'] == 'sonnet'
    assert lead.put('/api/me/preferences', json={'writerModel': 'gpt-4'}).status_code == 422
    assert lead.get('/api/me/preferences').json()['claudeModel'] == 'opus'
    start_job(lead, pid)
    calls = []

    def runner(args, **kwargs):
        calls.append(args[args.index('--model') + 1] if '--model' in args else None)
        envelope = {'type': 'result', 'is_error': False, 'structured_output': {'ok': True}, 'modelUsage': {}}
        return subprocess.CompletedProcess(args, 0, json.dumps(envelope), '')

    def handler(job_input, report, submit=None):
        claude.run_agent('flow-designer', {}, Answer, cwd='.', runner=runner)
        claude.run_agent('flow-case-writer', {}, Answer, cwd='.', runner=runner)
        return {}
    from helper.claude import ClaudeStatus
    from helper.runner import Helper
    status = ClaudeStatus(installed=True, loggedIn=True)
    Helper(helper, log=lambda _: None, claude_status=lambda: status, handlers={'framework.analyze': handler}).run_once()
    assert calls == ['opus', 'sonnet']


def test_missing_columns_are_added_to_an_older_database(tmp_path, monkeypatch):
    from studio import db as studio_db
    engine = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE user_preferences (user_id VARCHAR(32) PRIMARY KEY, claude_model VARCHAR(60), '
                                'last_models JSON, last_used_at FLOAT)'))
        connection.execute(text("INSERT INTO user_preferences VALUES ('u1', 'opus', '[]', NULL)"))
    monkeypatch.setattr(studio_db, 'engine', engine)
    studio_db.add_missing_columns()
    studio_db.add_missing_columns()  # running it again changes nothing
    assert 'writer_model' in {c['name'] for c in inspect(engine).get_columns('user_preferences')}
    with engine.connect() as connection:
        assert connection.execute(text('SELECT claude_model, writer_model FROM user_preferences')).fetchall() == [('opus', '')]

"""The project assistant: answers from a project snapshot, confirmed actions and drafted flows."""
from pathlib import Path

from helper import assistant
from helper.claude import ClaudeError, ClaudeStatus
from helper.runner import Helper

from .test_flows import FakeFlowClaude, run_flow_helper
from .test_scripts import confirmed_project

STATUS = ClaudeStatus(installed=True, loggedIn=True)


class AssistantFake(FakeFlowClaude):
    """Answers like the project assistant; flow design calls go to the usual fake pipeline."""

    def __init__(self, reply=None, fail=False):
        super().__init__()
        self.reply, self.fail, self.seen = reply or {}, fail, {}

    def __call__(self, agent, task, schema, **options):
        if agent == 'project-assistant':
            if self.fail:
                raise ClaudeError('Your Claude usage limit has been reached.')
            root = Path(options['cwd'])
            self.seen = {'task': task, 'tools': options.get('tools'), 'files': sorted(p.relative_to(root).as_posix()
                                                                                       for p in root.rglob('*.md'))}
            self.seen['stats'] = (root / 'stats.md').read_text(encoding='utf-8')
            return {'answer': 'Here you go.', 'caseCodes': [], 'actions': [], 'flowRequests': [], 'followUps': [],
                    **self.reply}
        return super().__call__(agent, task, schema, **options)


def designed(project, tmp_path):
    lead, pid, helper, *_ = confirmed_project(project, tmp_path)
    lead.post(f'/api/projects/{pid}/flows/generate')
    run_flow_helper(helper, FakeFlowClaude())
    flows = lead.get(f'/api/projects/{pid}/flows').json()['flows']
    return lead, pid, helper, {f['title']: f for f in flows}


def run_assistant(helper, agent) -> bool:
    handlers = {'assistant.message': lambda job_input, report, submit=None, meter=None:
                assistant.answer(job_input, report, submit, meter, agent=agent)}
    return Helper(helper, log=lambda _: None, claude_status=lambda: STATUS, handlers=handlers, lane='assistant').run_once()


def ask(lead, pid, text, **context):
    response = lead.post(f'/api/projects/{pid}/assistant/messages', json={'text': text, 'context': context})
    assert response.status_code == 200, response.text
    return response.json()


def test_answers_from_a_snapshot_of_the_project(project, tmp_path):
    lead, pid, helper, flows = designed(project, tmp_path)
    code = flows['Revised Order lookup']['code']
    pending = ask(lead, pid, 'Which flows place an order?', page='flows')['messages']
    assert [m['role'] for m in pending] == ['user', 'assistant'] and pending[1]['status'] == 'pending'
    assert lead.post(f'/api/projects/{pid}/assistant/messages', json={'text': 'And another?'}).status_code == 409

    fake = AssistantFake({'answer': f'{code} places an order.', 'caseCodes': [code, 'TC-9999'], 'followUps': ['Which are approved?']})
    # The main lane never takes assistant messages; the assistant lane answers them.
    assert not Helper(helper, log=lambda _: None, claude_status=lambda: STATUS, handlers={}).run_once()
    assert run_assistant(helper, fake)
    assert fake.seen['tools'] == ('Read', 'Glob', 'Grep') and fake.seen['task']['context'] == {'page': 'flows'}
    assert {'README.md', 'stats.md', 'flows/index.md', 'unit/index.md', 'analysis/processes.md', 'analysis/coverage.md',
            'endpoints.md', 'activity.md'} <= set(fake.seen['files'])
    assert 'rules.md' not in fake.seen['files']
    assert any(f.startswith('flows/store/') for f in fake.seen['files']) and '- Flow: 6 total' in fake.seen['stats']

    answer = lead.get(f'/api/projects/{pid}/assistant').json()['messages'][-1]
    assert answer['status'] == 'done' and answer['text'] == f'{code} places an order.'
    assert [c['code'] for c in answer['cases']] == [code]  # unknown codes are dropped; codes in the text become links
    assert answer['followUps'] == ['Which are approved?'] and answer['actions'] == []

    # The next question carries the conversation so far.
    ask(lead, pid, 'Which of them are approved?')
    second = AssistantFake()
    run_assistant(helper, second)
    assert [h['role'] for h in second.seen['task']['history']] == ['user', 'assistant']
    assert second.seen['task']['history'][1]['text'] == f'{code} places an order.'


def test_actions_run_only_when_confirmed_and_with_the_usual_checks(project, tmp_path):
    lead, pid, helper, flows = designed(project, tmp_path)
    codes = [flows['Revised Order lookup']['code'], flows['Broken read']['code']]
    ask(lead, pid, 'Approve the store flows')
    run_assistant(helper, AssistantFake({'answer': 'Two flows match.', 'actions': [
        {'kind': 'review', 'title': 'Approve 2 flows', 'caseCodes': codes, 'reviewAction': 'approve'},
        {'kind': 'export', 'title': 'Download approved flows', 'module': 'flow', 'exportFormat': 'csv', 'exportStatus': 'approved'}]}))
    message = lead.get(f'/api/projects/{pid}/assistant').json()['messages'][-1]
    action = message['actions'][0]
    assert action['state'] == 'proposed' and [c['code'] for c in action['cases']] == codes
    assert all(f['status'] == 'in_review' for f in lead.get(f'/api/projects/{pid}/flows').json()['flows'])  # nothing ran yet

    done = lead.post(f"/api/projects/{pid}/assistant/messages/{message['id']}/actions/0").json()
    assert done['messages'][-1]['actions'][0]['state'] == 'done' and '2 test cases approved' in done['messages'][-1]['actions'][0]['result']
    statuses = {f['code']: f['status'] for f in lead.get(f'/api/projects/{pid}/flows').json()['flows']}
    assert all(statuses[c] == 'approved' for c in codes)
    assert lead.post(f"/api/projects/{pid}/assistant/messages/{message['id']}/actions/0").status_code == 409  # once only
    export = lead.post(f"/api/projects/{pid}/assistant/messages/{message['id']}/actions/1").json()
    assert export['download'] == f'/api/projects/{pid}/export?module=flow&format=csv&status=approved'
    activity = [a['summary'] for a in lead.get(f'/api/projects/{pid}/activity').json()]
    assert any('confirmed an assistant action: Approve 2 flows' in line for line in activity)


def test_a_missing_flow_becomes_a_checked_draft_the_user_can_add(project, tmp_path):
    lead, pid, helper, flows = designed(project, tmp_path)
    ask(lead, pid, 'You missed: a created pet must be readable right away')
    run_assistant(helper, AssistantFake({'answer': 'No flow reads a pet right after creating it. I drafted one.',
                                         'flowRequests': [{'title': 'Read a new pet', 'description': 'Create a pet, then read it by its id.'}]}))
    message = lead.get(f'/api/projects/{pid}/assistant').json()['messages'][-1]
    draft = message['drafts'][0]
    assert draft['state'] == 'pending' and draft['title'] == 'Created pet is readable' and draft['area'] == 'Pets'
    assert draft['steps'] == ['POST /pets', 'GET /pets/{petId}'] and message['draftError'] == ''

    added = lead.post(f"/api/projects/{pid}/assistant/messages/{message['id']}/drafts/0/accept").json()
    code = added['messages'][-1]['drafts'][0]['caseCode']
    flow = next(f for f in lead.get(f'/api/projects/{pid}/flows').json()['flows'] if f['code'] == code)
    assert flow['status'] == 'in_review' and flow['content']['area'] == 'Pets' and flow['content']['source'] == 'assistant'
    assert lead.post(f"/api/projects/{pid}/assistant/messages/{message['id']}/drafts/0/accept").status_code == 409


def test_drafts_need_a_designed_project(project, tmp_path):
    lead, pid, helper, *_ = confirmed_project(project, tmp_path)
    ask(lead, pid, 'Add a flow for ordering')
    run_assistant(helper, AssistantFake({'flowRequests': [{'title': 'Order a pet', 'description': 'Create a pet and order it.'}]}))
    message = lead.get(f'/api/projects/{pid}/assistant').json()['messages'][-1]
    assert message['drafts'] == [] and 'Design the flows of this project first' in message['draftError']


def test_failures_are_shown_and_clearing_starts_over(project, tmp_path):
    lead, pid, helper, _ = designed(project, tmp_path)
    ask(lead, pid, 'Summarise the review notes')
    run_assistant(helper, AssistantFake(fail=True))
    message = lead.get(f'/api/projects/{pid}/assistant').json()['messages'][-1]
    assert message['status'] == 'failed' and 'usage limit' in message['error']
    assert lead.delete(f'/api/projects/{pid}/assistant/messages').json()['messages'] == []


def test_assistant_needs_the_helper(project):
    lead, pid = project
    response = lead.post(f'/api/projects/{pid}/assistant/messages', json={'text': 'Hello'})
    assert response.status_code == 409 and 'Local Helper' in response.json()['detail']

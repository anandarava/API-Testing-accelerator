"""Role-based test cases: the roles file, the permission grid, role cases per endpoint, export and scripts."""
import io
import json
import zipfile

import pytest

from contracts.roles import covered, normalise, role_gaps, role_requirements, validate_role_cases
from helper import role_cases, scripts
from helper.claude import ClaudeStatus
from helper.runner import Helper
from studio.documents import DocumentError, extract_text

from .test_unit_cases import setup_project

ROLES_CSV = """role,description,can do,cannot do
Customer,Buys pets,"place orders, read own orders","create or delete pets"
Clerk,Runs the shop,"create and update pets, read all orders","delete pets"
Owner,Owns the shop,everything,
"""


def operations(lead, pid):
    return {e['operationId']: e for e in lead.get(f'/api/projects/{pid}/endpoints').json()['endpoints']}


def access_model(op_ids):
    rows = []
    for op in op_ids:
        if op == 'placeOrder':
            rows.append({'operationId': op, 'allowed': ['Customer', 'Owner'], 'own': [], 'denied': ['Clerk'], 'unknown': [],
                         'evidence': 'Customer: place orders', 'source': 'file'})
        elif op == 'getOrder':
            rows.append({'operationId': op, 'allowed': ['Clerk', 'Owner'], 'own': ['Customer'], 'denied': [], 'unknown': [],
                         'evidence': 'read own orders', 'source': 'file'})
        elif op == 'deletePet':
            rows.append({'operationId': op, 'allowed': ['Owner'], 'own': [], 'denied': ['customer', 'Clerk', 'Ghost'],
                         'unknown': [], 'evidence': 'cannot delete pets', 'source': 'file'})
    return {'summary': 'Three roles.', 'roles': [{'name': 'Customer', 'description': 'Buys pets', 'users': 2, 'source': 'file'},
                                                 {'name': 'Clerk', 'description': 'Runs the shop', 'users': 1, 'source': 'file'},
                                                 {'name': 'Owner', 'description': 'Owns the shop', 'users': 1, 'source': 'file'}],
            'operations': rows, 'rules': [], 'systemCallers': [], 'missingFromFile': ['Admin'], 'questions': ['Can clerks cancel orders?']}


def case(key, kind, roles, status, slot='first', title=None):
    return {'key': key, 'title': title or f'{kind} {key}', 'objective': 'Prove access', 'kind': kind, 'roles': roles, 'userSlot': slot,
            'priority': 'P1', 'preconditions': ['As Customer (first user): place an order'],
            'request': {'auth': 'valid', 'pathParams': {}, 'query': {}, 'headers': {}, 'body': None, 'bodyNote': ''},
            'expected': {'status': status, 'responseSchema': 'none', 'bodyChecks': [], 'headers': {}, 'notes': ''},
            'verifyUnchanged': 'Read back as Owner' if status >= 400 else '', 'testData': '', 'cleanup': [],
            'needsConfirmation': False, 'confirmationNote': ''}


class FakeRoleClaude:
    def __init__(self):
        self.calls = []

    def __call__(self, agent, task, schema, **options):
        self.calls.append((agent, task.get('mode'), (task.get('endpoint') or {}).get('operationId')))
        if agent == 'access-control-analyst':
            return access_model([op['operationId'] for op in task['operations']])
        if agent == 'role-case-designer':
            op, mode = task['endpoint']['operationId'], task['mode']
            if op == 'placeOrder' and mode == 'design':
                return {'cases': [case('R01', 'allowed', ['Customer', 'Owner'], 201), case('R02', 'denied', ['Clerk'], 200)]}
            if op == 'placeOrder' and mode == 'fix':  # the code check said a denied case must expect a 4xx
                return {'cases': [case('R02', 'denied', ['Clerk'], 400)]}  # this spec documents 400, not 403
            if op == 'getOrder':
                if mode == 'revise':
                    return {'cases': [case('R03', 'ownership', ['Customer'], 404, 'second', 'Other customer cannot read the order')]}
                return {'cases': [case('R01', 'allowed', ['Clerk', 'Owner', 'Customer'], 200)]}
            return {'cases': [case('R01', 'allowed', ['Owner'], 204), case('R02', 'denied', ['Customer', 'Clerk'], 404)]}
        if agent == 'role-case-reviewer':
            if task['endpoint']['operationId'] == 'getOrder' and task['mode'] == 'review':
                return {'verdict': 'needs_attention', 'summary': 'No second customer.',
                        'findings': [{'scenarioKey': 'checklist', 'severity': 'major', 'issue': 'Ownership untested',
                                      'suggestion': 'Second customer reads the order'}]}
            return {'verdict': 'ready', 'summary': 'Fine.', 'findings': []}
        raise AssertionError(agent)


def run(helper_client, agent):
    status = ClaudeStatus(installed=True, loggedIn=True)
    handlers = {'access.analyze': lambda job_input, report, submit=None: role_cases.analyze(job_input, report, submit, agent=agent),
                'roles.generate': lambda job_input, report, submit=None: role_cases.generate(job_input, report, submit, agent=agent)}
    assert Helper(helper_client, log=lambda _: None, claude_status=lambda: status, handlers=handlers).run_once()


# --- Roles file --------------------------------------------------------------------------------------

def _docx(rows):
    cells = ''.join('<w:tr>' + ''.join(f'<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>' for c in row) + '</w:tr>' for row in rows)
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           '<w:p><w:r><w:t>Roles of the shop</w:t></w:r></w:p><w:tbl>' + cells + '</w:tbl></w:body></w:document>')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('word/document.xml', xml)
    return stream.getvalue()


def _xlsx(rows):
    from openpyxl import Workbook
    book = Workbook()
    for row in rows:
        book.active.append(row)
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def test_roles_files_are_read_in_every_supported_format():
    assert 'Clerk | Runs the shop' in extract_text('roles.csv', ROLES_CSV.encode())
    assert 'Owner' in extract_text('roles.xlsx', _xlsx([['role', 'can do'], ['Owner', 'everything']]))
    assert 'Roles of the shop' in extract_text('roles.docx', _docx([['role', 'can do'], ['Clerk', 'update pets']]))
    assert 'Clerk' in extract_text('roles.json', json.dumps({'roles': [{'name': 'Clerk', 'can': ['update pets']}]}).encode())
    assert 'Clerk' in extract_text('roles.yaml', b'roles:\n  - name: Clerk\n')
    assert 'Reset password' in extract_text('roles.md', b'# Roles\n- Customer\n  Reset password: allowed\n')
    with pytest.raises(DocumentError, match='Upload the roles file as'):
        extract_text('roles.pdf', b'%PDF')


@pytest.mark.parametrize('filename, data', [
    ('roles.csv', b'role,username,password\nOwner,owner@shop.test,Secret123\n'),
    ('roles.txt', b'Owner role\nOWNER_PASSWORD=Secret123\n'),
    ('roles.json', json.dumps({'roles': [{'name': 'Owner', 'password': 'Secret123'}]}).encode()),
    ('roles.xlsx', _xlsx([['role', 'token'], ['Owner', 'eyJhbGciOi']])),
])
def test_files_with_credentials_are_refused(filename, data):
    with pytest.raises(DocumentError, match="Keep usernames and passwords in your framework's credentials file"):
        extract_text(filename, data)


# --- Permission model ------------------------------------------------------------------------------------

def test_the_grid_puts_every_role_in_exactly_one_list_and_keeps_the_strictest_answer():
    model = access_model(['deletePet'])
    model['operations'][0]['allowed'].append('Clerk')  # listed as allowed and denied: denied wins
    grid = normalise(model, ['deletePet', 'listPets'])
    delete = grid['operations'][0]
    assert delete['allowed'] == ['Owner'] and delete['denied'] == ['Customer', 'Clerk'] and delete['unknown'] == []
    assert grid['operations'][1] == {'operationId': 'listPets', 'evidence': '', 'source': 'inferred', 'allowed': [], 'own': [],
                                     'denied': [], 'unknown': ['Customer', 'Clerk', 'Owner']}


def test_role_coverage_is_computed_from_the_cases():
    grid = normalise(access_model(['getOrder']), ['getOrder'])
    required = role_requirements(grid, 'getOrder')
    assert {r['id'] for r in required} == {'role:getOrder:Clerk:allowed', 'role:getOrder:Owner:allowed', 'role:getOrder:Customer:own'}
    allowed = case('R01', 'allowed', ['Clerk', 'Owner', 'Customer'], 200)
    assert [r['id'] for r in role_gaps(required, [allowed])] == ['role:getOrder:Customer:own']
    other = case('R02', 'ownership', ['Customer'], 404, 'second')
    assert role_gaps(required, [allowed, other]) == []
    assert not covered(required[2], [allowed, {**other, 'userSlot': 'first'}])


def test_code_checks_reject_wrong_roles_and_statuses():
    endpoint = {'responses': {'201': {}, '403': {}}}
    problems = validate_role_cases([case('R01', 'denied', ['Clerk'], 201), case('R02', 'allowed', ['Ghost'], 201),
                                    case('R03', 'allowed', ['Clerk'], 418)], endpoint, ['Clerk', 'Owner'])
    assert any('R01: a denied case must expect a 4xx' in p for p in problems)
    assert any('R02: role "Ghost"' in p for p in problems)
    assert any('R03: status 418 is not documented' in p for p in problems)


# --- Portal ---------------------------------------------------------------------------------------------

def test_without_a_roles_file_no_role_cases_are_generated(project):
    lead, pid, helper, ids = setup_project(project)
    view = lead.get(f'/api/projects/{pid}/roles').json()
    assert view['document'] is None and view['analysis'] is None and all(e['caseCount'] == 0 for e in view['endpoints'])
    assert 'Upload the roles file first' in lead.post(f'/api/projects/{pid}/roles/analyze').json()['detail']
    assert 'Upload the roles file first' in lead.post(f'/api/projects/{pid}/roles/generate',
                                                      json={'endpointIds': [ids['placeOrder']]}).json()['detail']
    refused = lead.post(f'/api/projects/{pid}/roles/document', files={'file': ('creds.csv', b'role,password\nOwner,x1\n', 'text/csv')})
    assert refused.status_code == 400 and 'credentials' in refused.json()['detail']


def test_roles_file_analysis_grid_edits_and_role_cases(project):
    lead, pid, helper, ids = setup_project(project)
    assert lead.post(f'/api/projects/{pid}/roles/document', files={'file': ('roles.csv', ROLES_CSV.encode(), 'text/csv')}).status_code == 200
    assert 'Analyze the roles file first' in lead.post(f'/api/projects/{pid}/roles/generate',
                                                       json={'endpointIds': [ids['placeOrder']]}).json()['detail']
    lead.post(f'/api/projects/{pid}/roles/analyze')
    fake = FakeRoleClaude()
    run(helper, fake)
    view = lead.get(f'/api/projects/{pid}/roles').json()
    assert [r['name'] for r in view['analysis']['model']['roles']] == ['Customer', 'Clerk', 'Owner']
    assert view['credentials'][0] == {'role': 'Customer', 'prefix': 'CUSTOMER', 'users': 2}
    delete = next(e for e in view['endpoints'] if e['operationId'] == 'deletePet')['access']
    assert delete['denied'] == ['Customer', 'Clerk']  # 'customer' matched by name, 'Ghost' dropped

    bad = lead.put(f'/api/projects/{pid}/roles/access/listPets', json={'allowed': ['Owner'], 'own': [], 'denied': [], 'unknown': []})
    assert bad.status_code == 400 and 'exactly one list' in bad.json()['detail']

    targets = [ids['placeOrder'], ids['getOrder'], ids['deletePet'], ids['listPets']]
    lead.post(f'/api/projects/{pid}/roles/generate', json={'endpointIds': targets})
    run(helper, fake)
    view = lead.get(f'/api/projects/{pid}/roles').json()
    rows = {e['operationId']: e for e in view['endpoints']}
    assert rows['placeOrder']['coverage']['covered'] == rows['placeOrder']['coverage']['total'] == 3
    assert rows['getOrder']['coverage']['covered'] == 3  # the reviewer's ownership suggestion was added
    assert 'No permission is decided' in rows['listPets']['coverage']['error']
    assert set(rows['placeOrder']['roles']) == {'Customer', 'Owner', 'Clerk'}
    detail = lead.get(f"/api/projects/{pid}/roles/endpoints/{ids['getOrder']}").json()
    assert [c['category'] for c in detail['cases']] == ['allowed', 'ownership']
    assert detail['cases'][1]['content']['userSlot'] == 'second'
    assert all(r['covered'] and r['cases'] for r in detail['requirements'])
    # Role cases live apart from the unit cases of the same endpoint.
    unit_rows = {e['id']: e for e in lead.get(f'/api/projects/{pid}/unit/endpoints').json()['endpoints']}
    assert unit_rows[ids['getOrder']]['caseCount'] == 0

    # Approve one case, correct the grid: the endpoint is outdated, the approved case survives regeneration.
    first = detail['cases'][0]
    lead.post(f'/api/projects/{pid}/unit/cases/review', json={'caseIds': [first['id']], 'action': 'approve'})
    assert lead.put(f'/api/projects/{pid}/roles/access/getOrder',
                    json={'allowed': ['Owner'], 'own': ['Customer'], 'denied': ['Clerk'], 'unknown': []}).status_code == 200
    rows = {e['operationId']: e for e in lead.get(f'/api/projects/{pid}/roles').json()['endpoints']}
    assert rows['getOrder']['coverage']['outdated'] is True

    edited = lead.patch(f"/api/projects/{pid}/unit/cases/{detail['cases'][1]['id']}", json={
        'revision': detail['cases'][1]['revision'], 'title': 'Second customer is refused', 'category': 'ownership', 'priority': 'P1',
        'request': first['content']['request'], 'expected': {**first['content']['expected'], 'status': 404}, 'roles': ['Customer']})
    assert edited.status_code == 200 and edited.json()['category'] == 'ownership'
    wrong = lead.patch(f"/api/projects/{pid}/unit/cases/{detail['cases'][1]['id']}", json={
        'revision': edited.json()['revision'], 'title': 'x' * 5, 'category': 'boundary', 'priority': 'P1',
        'request': first['content']['request'], 'expected': first['content']['expected']})
    assert wrong.status_code == 400

    export = lead.get(f'/api/projects/{pid}/export?module=role&format=csv')
    assert export.status_code == 200 and 'Ownership (second user)' in export.content.decode('utf-8-sig')


def test_role_scripts_get_their_own_file_and_the_credential_names(tmp_path):
    profile = {'testDirectory': 'tests/api'}
    endpoint = {'method': 'GET', 'path': '/orders/{orderId}', 'roleCases': True}
    assert scripts.suggested_path(profile, endpoint) == 'tests/api/orders-by-id.get.roles.spec.ts'
    assert scripts.suggested_path(profile, {**endpoint, 'roleCases': False}) == 'tests/api/orders-by-id.get.spec.ts'
    tasks = []

    def writer(agent, task, schema, **options):
        tasks.append(task)
        raise scripts.ScriptError('stop after capturing the task')
    item = {'id': 'role:e1', 'endpointKey': 'ROLE GET /orders/{orderId}', 'details': {**endpoint, 'roles': [{'name': 'Clerk'}]},
            'cases': [{'id': 'c1', 'code': 'TC-0001', 'title': 'Clerk reads', 'category': 'allowed', 'priority': 'P1',
                       'content': {'roles': ['Clerk'], 'request': {}, 'expected': {}}, 'fingerprint': 'x'}]}
    with pytest.raises(scripts.ScriptError):
        scripts.write_endpoint(tmp_path, profile, {}, item, {'files': {}}, lambda *a: None, writer, credential_keys=['CLERK_USERNAME'])
    assert tasks[0]['kind'] == 'roles' and tasks[0]['credentialKeys'] == ['CLERK_USERNAME']
    assert tasks[0]['cases'][0]['roles'] == ['Clerk']

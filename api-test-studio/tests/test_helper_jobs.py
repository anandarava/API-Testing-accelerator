import time

from studio.db import SessionLocal
from studio.models import Job

from .conftest import beat, pair_helper

PROFILE = {
    'summary': 'Playwright API tests with a typed client per resource.',
    'testDirectory': 'tests/api', 'testFilePattern': 'tests/api/**/*.spec.ts', 'fileNaming': '<resource>.spec.ts',
    'imports': [{'purpose': 'fixtures', 'statement': "import { test, expect } from '../../src/fixtures/api.fixture';"}],
    'httpClient': {'style': 'custom-client', 'description': 'UsersClient wraps APIRequestContext',
                   'location': 'src/clients/users-client.ts', 'exampleUsage': 'await users.create(body)'},
    'fixtures': [], 'authentication': {'approach': 'Bearer token from API_TOKEN', 'envVariables': ['API_TOKEN']},
    'baseUrl': {'source': 'playwright.config.ts use.baseURL', 'envVariable': 'API_BASE_URL'},
    'assertions': {'style': 'expect(response.status()).toBe(...)'},
    'testData': {'approach': 'Inline objects'}, 'conventions': ['One describe block per endpoint'],
}
SCAN = {'playwrightVersion': '1.58.2', 'typescriptVersion': '5.9.3', 'configFiles': ['playwright.config.ts'],
        'specFileCount': 1, 'sampleSpecFiles': ['tests/api/users.spec.ts'], 'scripts': {'test': 'playwright test'}}


def connected_project(project):
    lead, pid = project
    helper = pair_helper(lead)
    beat(helper)
    assert lead.put(f'/api/projects/{pid}/framework/path', json={'path': 'C:\\work\\api-tests'}).status_code == 200
    return lead, pid, helper


def test_pairing_and_presence(project):
    lead, _ = project
    assert lead.get('/api/me/helper').json()['paired'] is False
    helper = pair_helper(lead)
    state = lead.get('/api/me/helper').json()
    assert state['paired'] is True and state['connected'] is False
    beat(helper)
    state = lead.get('/api/me/helper').json()
    assert state['connected'] is True and state['claude']['subscriptionType'] == 'max'
    # Helper tokens cannot use the portal, and browser sessions cannot act as a helper.
    assert helper.get('/api/projects').status_code == 403
    assert lead.post('/api/helper/jobs/claim').status_code == 403
    # Disconnecting revokes the helper token.
    assert lead.delete('/api/me/helper').status_code == 200
    assert helper.post('/api/helper/jobs/claim').status_code == 401


def test_pairing_code_is_single_use_and_normalized(project):
    lead, _ = project
    from fastapi.testclient import TestClient
    from studio.main import app
    code = lead.post('/api/me/helper/pairing-code').json()['code']
    anonymous = TestClient(app)
    assert anonymous.post('/api/helper/pair', json={'code': code.lower().replace('-', ' ')}).status_code == 200
    assert anonymous.post('/api/helper/pair', json={'code': code}).status_code == 400


def test_framework_path_must_be_absolute(project):
    lead, pid = project
    response = lead.put(f'/api/projects/{pid}/framework/path', json={'path': 'relative/folder'})
    assert response.status_code == 400
    assert lead.put(f'/api/projects/{pid}/framework/path', json={'path': '/home/qa/api-tests'}).status_code == 200


def test_analyze_requires_folder_and_connected_helper(project):
    lead, pid = project
    assert lead.post(f'/api/projects/{pid}/framework/analyze').status_code == 400
    lead.put(f'/api/projects/{pid}/framework/path', json={'path': 'C:\\work\\api-tests'})
    response = lead.post(f'/api/projects/{pid}/framework/analyze')
    assert response.status_code == 409 and 'not connected' in response.json()['detail']


def test_framework_analysis_round_trip(project, make_user):
    lead, pid, helper = connected_project(project)
    other = make_user('Eli Employee')
    lead.post(f'/api/projects/{pid}/members', json={'email': 'eli.employee@example.test'})
    other_helper = pair_helper(other)

    job = lead.post(f'/api/projects/{pid}/framework/analyze').json()
    assert job['status'] == 'queued'
    assert lead.post(f'/api/projects/{pid}/framework/analyze').status_code == 409
    # Jobs only go to the requester's own computer.
    assert other_helper.post('/api/helper/jobs/claim').json()['job'] is None
    claimed = helper.post('/api/helper/jobs/claim').json()['job']
    assert claimed['id'] == job['id'] and claimed['input']['frameworkPath'] == 'C:\\work\\api-tests'
    assert helper.post('/api/helper/jobs/claim').json()['job'] is None  # leased

    assert helper.post(f'/api/helper/jobs/{job["id"]}/progress', json={'message': 'Reading', 'percent': 40}).status_code == 200
    bad = helper.post(f'/api/helper/jobs/{job["id"]}/complete', json={'result': {'profile': {'summary': 'x'}, 'scan': SCAN}})
    assert bad.status_code == 400
    done = helper.post(f'/api/helper/jobs/{job["id"]}/complete', json={'result': {'profile': PROFILE, 'scan': SCAN}})
    assert done.status_code == 200, done.text

    view = other.get(f'/api/projects/{pid}/framework').json()
    assert view['status'] == 'draft' and view['profile']['testDirectory'] == 'tests/api'
    assert view['myPath'] == '' and view['latestJob']['status'] == 'succeeded'

    # Any member can correct and confirm; stale revisions are rejected.
    edited = {**view['profile'], 'testDirectory': 'tests/api/v2'}
    saved = other.put(f'/api/projects/{pid}/framework/profile', json={'revision': view['revision'], 'profile': edited, 'confirm': True})
    assert saved.status_code == 200 and saved.json()['status'] == 'confirmed'
    stale = lead.put(f'/api/projects/{pid}/framework/profile', json={'revision': view['revision'], 'profile': edited})
    assert stale.status_code == 409
    setup = lead.get(f'/api/projects/{pid}').json()['setup']
    assert setup == {'specUploaded': False, 'helperConnected': True, 'frameworkPathSet': True, 'frameworkProfile': 'confirmed'}


def test_failed_and_cancelled_jobs(project):
    lead, pid, helper = connected_project(project)
    job = lead.post(f'/api/projects/{pid}/framework/analyze').json()
    helper.post('/api/helper/jobs/claim')
    assert helper.post(f'/api/helper/jobs/{job["id"]}/fail', json={'error': 'No package.json found.'}).status_code == 200
    jobs = lead.get(f'/api/projects/{pid}/jobs').json()
    assert jobs[0]['status'] == 'failed' and jobs[0]['error'] == 'No package.json found.'

    second = lead.post(f'/api/projects/{pid}/framework/analyze').json()
    assert lead.post(f'/api/projects/{pid}/jobs/{second["id"]}/cancel').json()['status'] == 'cancelled'
    assert helper.post('/api/helper/jobs/claim').json()['job'] is None


def test_expired_lease_is_reclaimed_then_given_up(project):
    lead, pid, helper = connected_project(project)
    job = lead.post(f'/api/projects/{pid}/framework/analyze').json()
    for attempt in (1, 2, 3):
        claimed = helper.post('/api/helper/jobs/claim').json()['job']
        assert claimed['attempt'] == attempt
        with SessionLocal() as db:
            db.get(Job, job['id']).lease_until = time.time() - 1
            db.commit()
    assert helper.post('/api/helper/jobs/claim').json()['job'] is None
    assert 'stopped responding' in lead.get(f'/api/projects/{pid}/jobs/{job["id"]}').json()['error']


def test_job_fails_when_requester_loses_access(project, make_user):
    lead, pid = project
    employee = make_user('Eli Employee')
    lead.post(f'/api/projects/{pid}/members', json={'email': 'eli.employee@example.test'})
    helper = pair_helper(employee)
    beat(helper)
    employee.put(f'/api/projects/{pid}/framework/path', json={'path': 'C:\\eli\\api-tests'})
    job = employee.post(f'/api/projects/{pid}/framework/analyze').json()
    lead.delete(f'/api/projects/{pid}/members/{employee.user["id"]}')
    assert helper.post('/api/helper/jobs/claim').json()['job'] is None
    assert lead.get(f'/api/projects/{pid}/jobs/{job["id"]}').json()['status'] == 'failed'

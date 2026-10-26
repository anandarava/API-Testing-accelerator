from fastapi.testclient import TestClient

from studio.main import app

from .conftest import upload

SPEC = '{"openapi": "3.0.3", "info": {"title": "T", "version": "1"}, "paths": {"/a": {"get": {"responses": {"200": {"description": "ok"}}}}}}'


def test_register_login_logout():
    client = TestClient(app)
    assert client.get('/api/auth/me').status_code == 401
    body = {'name': 'Asha', 'email': 'Asha@Example.test', 'password': 'long-enough'}
    assert client.post('/api/auth/register', json=body).json()['email'] == 'asha@example.test'
    assert client.post('/api/auth/register', json=body).status_code == 409
    assert client.get('/api/auth/me').json()['name'] == 'Asha'
    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/auth/me').status_code == 401
    assert client.post('/api/auth/login', json={'email': 'asha@example.test', 'password': 'wrong-pass'}).status_code == 401
    assert client.post('/api/auth/login', json={'email': 'ASHA@example.test', 'password': 'long-enough'}).status_code == 200


def test_short_password_has_readable_error():
    response = TestClient(app).post('/api/auth/register', json={'name': 'A', 'email': 'a@b.co', 'password': 'short'})
    assert response.status_code == 422
    assert response.json()['detail'].startswith('password:')


def test_cross_site_cookie_write_is_rejected(make_user):
    lead = make_user()
    response = lead.post('/api/projects', json={'name': 'X'}, headers={'Origin': 'https://evil.example'})
    assert response.status_code == 403


def test_lead_and_employee_permissions(project, make_user):
    lead, pid = project
    employee = make_user('Eli Employee')
    outsider = make_user('Omar Outsider')

    assert outsider.get(f'/api/projects/{pid}').status_code == 404
    assert lead.post(f'/api/projects/{pid}/members', json={'email': 'nobody@example.test'}).status_code == 404
    added = lead.post(f'/api/projects/{pid}/members', json={'email': 'ELI.EMPLOYEE@example.test'})
    assert added.status_code == 200 and added.json()['role'] == 'employee'
    assert lead.post(f'/api/projects/{pid}/members', json={'email': 'eli.employee@example.test'}).status_code == 409

    # Employees can see and work in the project ...
    assert [p['role'] for p in employee.get('/api/projects').json()] == ['employee']
    assert upload(employee, pid, 'a.json', SPEC).status_code == 200
    # ... but cannot manage access or the project itself.
    assert employee.post(f'/api/projects/{pid}/members', json={'email': 'omar.outsider@example.test'}).status_code == 403
    assert employee.patch(f'/api/projects/{pid}/members/{employee.user["id"]}', json={'role': 'lead'}).status_code == 403
    assert employee.patch(f'/api/projects/{pid}', json={'name': 'Renamed'}).status_code == 403
    assert employee.delete(f'/api/projects/{pid}').status_code == 403

    members = lead.get(f'/api/projects/{pid}/members').json()
    assert [(m['name'], m['role']) for m in members] == [('Lena Lead', 'lead'), ('Eli Employee', 'employee')]
    actions = [a['action'] for a in lead.get(f'/api/projects/{pid}/activity').json()]
    assert {'project.created', 'member.added', 'spec.uploaded'} <= set(actions)


def test_project_always_keeps_a_lead(project, make_user):
    lead, pid = project
    employee = make_user('Eli Employee')
    lead.post(f'/api/projects/{pid}/members', json={'email': 'eli.employee@example.test'})
    me = lead.user['id']
    assert lead.patch(f'/api/projects/{pid}/members/{me}', json={'role': 'employee'}).status_code == 409
    assert lead.delete(f'/api/projects/{pid}/members/{me}').status_code == 409

    assert lead.patch(f'/api/projects/{pid}/members/{employee.user["id"]}', json={'role': 'lead'}).status_code == 200
    assert lead.patch(f'/api/projects/{pid}/members/{me}', json={'role': 'employee'}).status_code == 200
    # The promoted lead now manages access; the former lead cannot.
    assert lead.delete(f'/api/projects/{pid}/members/{employee.user["id"]}').status_code == 403
    assert employee.delete(f'/api/projects/{pid}/members/{me}').status_code == 200
    assert lead.get(f'/api/projects/{pid}').status_code == 404


def test_lead_can_delete_project(project):
    lead, pid = project
    upload(lead, pid, 'a.json', SPEC)
    assert lead.delete(f'/api/projects/{pid}').status_code == 200
    assert lead.get('/api/projects').json() == []

import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix='studio-tests-')
os.environ['STUDIO_DATA_DIR'] = _TMP
os.environ['STUDIO_DATABASE_URL'] = 'sqlite:///' + Path(_TMP, 'test.db').as_posix()
os.environ['STUDIO_HELPER_HOME'] = str(Path(_TMP, 'helper'))
# Tests never talk to a real local AI server, even when the developer's shell has one set up.
for _name in [name for name in os.environ if name.startswith('STUDIO_LLM_')]:
    del os.environ[_name]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from studio.db import Base, engine  # noqa: E402
from studio.main import app  # noqa: E402
from studio.security import auth_limiter, pairing_limiter  # noqa: E402

# Sample spec and framework used by the tests; STUDIO_EXAMPLES can point to a copy elsewhere.
EXAMPLES = Path(os.environ.get('STUDIO_EXAMPLES') or Path(__file__).resolve().parents[1] / 'examples')


@pytest.fixture(autouse=True)
def fresh_database():
    from studio import models  # noqa: F401
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    auth_limiter.reset()
    pairing_limiter.reset()
    yield


@pytest.fixture
def make_user():
    """Return a function that registers a user and returns a signed-in TestClient."""
    clients = []

    def create(name='Lead User', email=None):
        client = TestClient(app)
        email = email or name.lower().replace(' ', '.') + '@example.test'
        response = client.post('/api/auth/register', json={'name': name, 'email': email, 'password': 'correct-horse'})
        assert response.status_code == 200, response.text
        client.user = response.json()
        clients.append(client)
        return client

    yield create
    for client in clients:
        client.close()


@pytest.fixture
def project(make_user):
    lead = make_user('Lena Lead')
    created = lead.post('/api/projects', json={'name': 'Orders API', 'description': 'Checkout services'}).json()
    return lead, created['id']


def upload(client, project_id, filename, content, content_type='application/json'):
    data = content.encode() if isinstance(content, str) else content
    return client.post(f'/api/projects/{project_id}/specs', files={'file': (filename, data, content_type)})


def pair_helper(client) -> TestClient:
    code = client.post('/api/me/helper/pairing-code').json()['code']
    token = TestClient(app).post('/api/helper/pair', json={'code': code, 'hostname': 'qa-laptop'}).json()['token']
    helper = TestClient(app, headers={'Authorization': 'Bearer ' + token})
    return helper


def beat(helper):
    response = helper.post('/api/helper/heartbeat', json={
        'hostname': 'qa-laptop', 'helperVersion': '0.1.0',
        'claude': {'installed': True, 'version': '2.1.301', 'loggedIn': True, 'email': 'qa@example.test',
                   'subscriptionType': 'max', 'error': ''}})
    assert response.status_code == 200, response.text

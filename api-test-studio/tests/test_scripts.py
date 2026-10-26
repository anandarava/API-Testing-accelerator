"""Script generation: path and code safety, the write/check/fix loop, and portal tracking."""
import json
import shutil
import subprocess

import pytest

from helper import scripts
from helper.claude import ClaudeStatus
from helper.runner import Helper

from .conftest import EXAMPLES, beat, pair_helper
from .test_unit_cases import FakeClaude, run_helper, setup_project

SAMPLE = EXAMPLES / 'sample-playwright-framework'
PROFILE = json.loads(json.dumps({'testDirectory': 'tests/api'}))


def spec_file(codes, extra=''):
    tests = '\n'.join(f"  test('{c} does something', async ({{ pets }}) => {{ expect(1).toBe(1); }});" for c in codes)
    return ("import { test, expect } from '../../src/fixtures/api.fixture';\n\n"
            f"test.describe('POST /pets', () => {{\n{tests}\n{extra}}});\n")


@pytest.mark.parametrize('path', ['../outside.spec.ts', '/abs/x.spec.ts', 'C:/x.spec.ts', 'tests/api/notes.md',
                                  'node_modules/x/a.spec.ts', 'tests/../../x.spec.ts'])
def test_unsafe_paths_are_rejected(tmp_path, path):
    with pytest.raises(scripts.ScriptError):
        scripts.safe_path(tmp_path, path)


def test_code_safety_and_case_presence():
    clean = spec_file(['TC-0001', 'TC-0002'])
    assert scripts.problems_in(clean, ['TC-0001', 'TC-0002']) == []
    assert 'TC-0003' in scripts.problems_in(clean, ['TC-0001', 'TC-0003'])[0]
    for bad in ["import { readFileSync } from 'fs';", "require('child_process')", 'await page.waitForTimeout(5000);',
                "test.only('x', () => {});", 'eval("1")', "import os from 'node:os';", '// @ts-ignore']:
        assert scripts.problems_in(spec_file(['TC-0001'], bad), ['TC-0001']), bad


def test_suggested_path_follows_profile():
    assert scripts.suggested_path({'testDirectory': 'tests/api/'}, {'method': 'POST', 'path': '/pets'}) == 'tests/api/pets.post.spec.ts'
    assert scripts.suggested_path({'testDirectory': 'e2e'}, {'method': 'GET', 'path': '/v1/pets/{petId}'}) == 'e2e/pets-by-id.get.spec.ts'
    assert scripts.suggested_path({}, {'method': 'POST', 'path': '/stores/{id}/orders'}) == 'tests/api/stores-orders.post.spec.ts'


class FakeCli:
    """Simulates node: tsc fails once for our file, eslint passes, playwright lists the tests."""

    def __init__(self, tsc_failures=1, listed=None):
        self.tsc_failures, self.listed, self.calls = tsc_failures, listed, []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        joined = ' '.join(args)
        if 'tsc' in joined:
            if self.tsc_failures:
                self.tsc_failures -= 1
                return subprocess.CompletedProcess(args, 2, "tests/api/pets.post.spec.ts(3,7): error TS2304: Cannot find name 'pet'.\n"
                                                            "src/other.ts(1,1): error TS1005: unrelated", '')
            return subprocess.CompletedProcess(args, 2, 'src/other.ts(1,1): error TS1005: unrelated', '')
        if 'eslint' in joined:
            return subprocess.CompletedProcess(args, 0, '', '')
        count = self.listed if self.listed is not None else self.expected
        return subprocess.CompletedProcess(args, 0, f'Listing tests:\nTotal: {count} tests in 1 file', '')


def framework_copy(tmp_path):
    root = tmp_path / 'framework'
    shutil.copytree(SAMPLE, root, ignore=shutil.ignore_patterns('node_modules'))
    for package in ('typescript/bin/tsc', 'eslint/bin/eslint.js', '@playwright/test/cli.js'):
        target = root / 'node_modules' / package
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('')
    (root / 'eslint.config.mjs').write_text('export default [];')
    return root


def writer(codes_by_call):
    calls = []

    def agent(name, task, schema, **options):
        calls.append((name, task))
        codes = [c['code'] for c in task['cases']]
        path = (task.get('existingFile') or {}).get('path') or task.get('suggestedPath') or task['file']['path']
        return {'file': {'path': path, 'content': spec_file(codes_by_call.pop(0) if codes_by_call else codes), 'caseCodes': codes},
                'envVariables': ['API_TOKEN'], 'notes': f'{name} note'}
    agent.calls = calls
    return agent


def item(codes):
    return {'id': 'ep1', 'endpointKey': 'POST /pets', 'details': {'method': 'POST', 'path': '/pets'},
            'cases': [{'id': f'case-{c}', 'code': c, 'title': c, 'category': 'positive', 'priority': 'P1',
                       'content': {'objective': '', 'preconditions': [], 'request': {}, 'expected': {}, 'testData': '', 'cleanup': []}}
                      for c in codes]}


def test_write_check_fix_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(scripts.shutil, 'which', lambda name: 'node')
    root = framework_copy(tmp_path)
    cli = FakeCli(tsc_failures=1)
    cli.expected = 2
    # First draft forgets TC-0002 -> fixer round 1; then tsc fails once -> fixer round 2; then everything passes.
    agent = writer([['TC-0001'], ['TC-0001', 'TC-0002'], ['TC-0001', 'TC-0002']])
    manifest = scripts.load_manifest(root)
    result = scripts.write_endpoint(root, PROFILE, {}, item(['TC-0001', 'TC-0002']), manifest, lambda *a: None, agent, cli)
    assert result['path'] == 'tests/api/pets.post.spec.ts' and result['fixRounds'] == 2
    assert [c['status'] for c in result['checks']] == ['passed', 'passed', 'passed']
    assert 'Other files in the project have TypeScript errors' in result['checks'][0]['detail']
    assert [name for name, _ in agent.calls] == ['script-writer', 'script-fixer', 'script-fixer']
    assert 'TC-0002' in agent.calls[1][1]['problems'][0]
    written = (root / result['path']).read_text(encoding='utf-8')
    assert written == result['content'] and result['diff'].startswith('--- /dev/null')
    assert json.loads((root / scripts.MANIFEST).read_text())['files'][result['path']]['caseCodes'] == ['TC-0001', 'TC-0002']
    # Checks run with a minimal environment: no tokens or portal credentials leak to generated code.
    env = cli.calls[0][1]['env']
    assert env.get('CI') == '1' and not any('TOKEN' in key or 'SECRET' in key for key in env)

    # Second generation updates the managed file in place and produces a diff.
    cli2 = FakeCli(tsc_failures=0)
    cli2.expected = 3
    again = scripts.write_endpoint(root, PROFILE, {}, item(['TC-0001', 'TC-0002', 'TC-0009']), manifest, lambda *a: None, writer([]), cli2)
    assert again['path'] == result['path'] and again['fixRounds'] == 0
    assert '+  test(\'TC-0009' in again['diff']


def test_unmanaged_files_are_never_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(scripts.shutil, 'which', lambda name: 'node')
    root = framework_copy(tmp_path)
    (root / 'tests/api/pets.post.spec.ts').write_text('// hand written')
    with pytest.raises(scripts.ScriptError, match='was not created by API Test Studio'):
        scripts.write_endpoint(root, PROFILE, {}, item(['TC-0001']), scripts.load_manifest(root), lambda *a: None, writer([]), FakeCli())
    assert (root / 'tests/api/pets.post.spec.ts').read_text() == '// hand written'


def test_forbidden_code_is_never_left_in_the_framework(tmp_path, monkeypatch):
    monkeypatch.setattr(scripts.shutil, 'which', lambda name: 'node')
    root = framework_copy(tmp_path)

    def evil(name, task, schema, **options):
        return {'file': {'path': 'tests/api/pets.post.spec.ts', 'content': spec_file(['TC-0001'], "require('child_process');"),
                         'caseCodes': ['TC-0001']}, 'envVariables': [], 'notes': ''}
    with pytest.raises(scripts.ScriptError, match='not saved'):
        scripts.write_endpoint(root, PROFILE, {}, item(['TC-0001']), scripts.load_manifest(root), lambda *a: None, evil, FakeCli())
    assert not (root / 'tests/api/pets.post.spec.ts').exists()


def test_checks_are_skipped_without_node_modules(tmp_path):
    root = tmp_path / 'fw'
    shutil.copytree(SAMPLE, root, ignore=shutil.ignore_patterns('node_modules'))
    checks = scripts.run_checks(root, 'tests/api/x.spec.ts', 1, runner=lambda *a, **k: pytest.fail('must not run'))
    assert {c['status'] for c in checks} == {'skipped'} and 'npm install' in checks[0]['detail']


def test_discovery_detects_missing_tests(tmp_path, monkeypatch):
    monkeypatch.setattr(scripts.shutil, 'which', lambda name: 'node')
    root = framework_copy(tmp_path)
    cli = FakeCli(tsc_failures=0, listed=1)
    checks = {c['name']: c for c in scripts.run_checks(root, 'tests/api/x.spec.ts', 2, cli)}
    assert checks['discovery']['status'] == 'failed' and 'expected 2' in checks['discovery']['detail']


# --- Portal ------------------------------------------------------------------------------------------

def confirmed_project(project, tmp_path):
    lead, pid, helper, endpoint_ids = setup_project(project)
    root = framework_copy(tmp_path)
    lead.put(f'/api/projects/{pid}/framework/path', json={'path': str(root)})
    from tests.test_helper_jobs import PROFILE as FULL_PROFILE, SCAN
    lead.post(f'/api/projects/{pid}/framework/analyze')
    job = helper.post('/api/helper/jobs/claim').json()['job']
    helper.post(f'/api/helper/jobs/{job["id"]}/complete', json={'result': {'profile': FULL_PROFILE, 'scan': SCAN}})
    view = lead.get(f'/api/projects/{pid}/framework').json()
    return lead, pid, helper, endpoint_ids, root, view


def test_portal_script_flow(project, tmp_path, monkeypatch):
    monkeypatch.setattr(scripts.shutil, 'which', lambda name: 'node')
    lead, pid, helper, endpoint_ids, root, view = confirmed_project(project, tmp_path)
    target = endpoint_ids['createPet']
    lead.post(f'/api/projects/{pid}/unit/generate', json={'endpointIds': [target]})
    run_helper(helper, FakeClaude(drop=0))
    cases = lead.get(f'/api/projects/{pid}/unit/endpoints/{target}').json()['cases']

    # Requirements: approved cases and a confirmed profile.
    response = lead.post(f'/api/projects/{pid}/scripts/generate', json={'endpointIds': [target]})
    assert response.status_code == 400 and 'Confirm the framework profile' in response.json()['detail']
    lead.put(f'/api/projects/{pid}/framework/profile', json={'revision': view['revision'], 'profile': view['profile'], 'confirm': True})
    response = lead.post(f'/api/projects/{pid}/scripts/generate', json={'endpointIds': [target]})
    assert response.status_code == 400 and 'no approved test cases' in response.json()['detail']
    approve = [c['id'] for c in cases[:3]]
    lead.post(f'/api/projects/{pid}/unit/cases/review', json={'caseIds': approve, 'action': 'approve'})
    assert lead.post(f'/api/projects/{pid}/scripts/generate', json={'endpointIds': [target]}).status_code == 200

    cli = FakeCli(tsc_failures=0)
    cli.expected = 3
    status = ClaudeStatus(installed=True, loggedIn=True)
    handlers = {'scripts.generate': lambda job_input, report, submit=None: scripts.generate(job_input, report, submit, writer([]), cli)}
    assert Helper(helper, log=lambda _: None, claude_status=lambda: status, handlers=handlers).run_once()

    rows = lead.get(f'/api/projects/{pid}/scripts').json()['endpoints']
    assert len(rows) == 1 and rows[0]['state'] == 'up_to_date' and rows[0]['scripted'] == 3
    detail = lead.get(f'/api/projects/{pid}/scripts/{target}').json()
    assert detail['filePath'] == 'tests/api/pets.post.spec.ts' and 'TC-0001' in detail['content']
    assert all(c['state'] == 'current' for c in detail['cases']) and detail['envVariables'] == ['API_TOKEN']
    unit_cases = {c['id']: c for c in lead.get(f'/api/projects/{pid}/unit/endpoints/{target}').json()['cases']}
    assert unit_cases[approve[0]]['script'] == 'current' and unit_cases[cases[5]['id']]['script'] is None

    # Re-approving does not make scripts outdated; editing does, and so does approving another case.
    lead.post(f'/api/projects/{pid}/unit/cases/review', json={'caseIds': [approve[0]], 'action': 'reopen'})
    lead.post(f'/api/projects/{pid}/unit/cases/review', json={'caseIds': [approve[0]], 'action': 'approve'})
    assert lead.get(f'/api/projects/{pid}/scripts').json()['endpoints'][0]['state'] == 'up_to_date'
    case = lead.get(f'/api/projects/{pid}/unit/cases/{approve[1]}').json()
    edit = {k: case['content'][k] for k in ('objective', 'preconditions', 'request', 'expected', 'testData', 'cleanup')}
    lead.patch(f'/api/projects/{pid}/unit/cases/{approve[1]}', json={**edit, 'revision': case['revision'], 'title': 'Changed',
                                                                     'category': case['category'], 'priority': case['priority']})
    lead.post(f'/api/projects/{pid}/unit/cases/review', json={'caseIds': [approve[1], cases[4]['id']], 'action': 'approve'})
    row = lead.get(f'/api/projects/{pid}/scripts').json()['endpoints'][0]
    assert row['state'] == 'needs_update' and row['changed'] == 1 and row['new'] == 1 and row['scripted'] == 2

    activity = [a['summary'] for a in lead.get(f'/api/projects/{pid}/activity').json()]
    assert any('3 tests written to tests/api/pets.post.spec.ts' in line and 'all checks passed' in line for line in activity)


def test_case_numbers_are_never_reused(project):
    lead, pid, helper, endpoint_ids = setup_project(project)
    target = endpoint_ids['getPet']
    lead.post(f'/api/projects/{pid}/unit/generate', json={'endpointIds': [target]})
    run_helper(helper, FakeClaude(drop=0))
    first = {c['code'] for c in lead.get(f'/api/projects/{pid}/unit/endpoints/{target}').json()['cases']}
    lead.post(f'/api/projects/{pid}/unit/generate', json={'endpointIds': [target]})
    run_helper(helper, FakeClaude(drop=0))
    second = {c['code'] for c in lead.get(f'/api/projects/{pid}/unit/endpoints/{target}').json()['cases']}
    assert first.isdisjoint(second)


@pytest.mark.skipif(not (SAMPLE / 'node_modules' / '@playwright' / 'test').is_dir() or not shutil.which('node'),
                    reason='Run npm install in examples/sample-playwright-framework for the real tool check')
def test_real_checks_against_sample_framework(tmp_path):
    root = tmp_path / 'fw'
    shutil.copytree(SAMPLE, root, symlinks=True)
    (root / 'tests/api/generated.post.spec.ts').write_text(
        "import { test, expect } from '../../src/fixtures/api.fixture';\n"
        "test('TC-0001 creates a pet', async ({ pets }) => {\n  const response = await pets.create({ name: 'Rex' });\n"
        "  expect(response.status()).toBe(201);\n});\n", encoding='utf-8')
    checks = {c['name']: c for c in scripts.run_checks(root, 'tests/api/generated.post.spec.ts', 1)}
    assert checks['typecheck']['status'] == 'passed', checks['typecheck']
    assert checks['discovery']['status'] == 'passed', checks['discovery']

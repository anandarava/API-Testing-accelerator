"""Local Helper behaviour: framework scan, Claude invocation and the job loop."""
import json
import shutil
import subprocess

import pytest

from helper import claude, framework
from helper.runner import Helper

from .conftest import EXAMPLES, beat, pair_helper
from .test_helper_jobs import PROFILE

SAMPLE = EXAMPLES / 'sample-playwright-framework'


def test_scan_sample_framework():
    facts = framework.scan(str(SAMPLE))
    assert facts.playwrightVersion == '1.58.2'
    assert 'playwright.config.ts' in facts.configFiles and 'tsconfig.json' in facts.configFiles
    assert facts.specFileCount == 1 and facts.sampleSpecFiles == ['tests/api/pets.spec.ts']
    assert facts.envExampleKeys == ['API_BASE_URL', 'API_TOKEN']


@pytest.mark.parametrize('setup, message', [
    (lambda root: None, 'does not exist'),
    (lambda root: root.mkdir(), 'No package.json'),
    (lambda root: (root.mkdir(), (root / 'package.json').write_text('{"devDependencies": {}}')), 'not a Playwright project'),
    (lambda root: (root.mkdir(), (root / 'package.json').write_text(
        '{"devDependencies": {"@playwright/test": "1", "typescript": "5"}}')), 'No playwright.config'),
])
def test_scan_rejects_unusable_folders(tmp_path, setup, message):
    root = tmp_path / 'framework'
    setup(root)
    with pytest.raises(framework.FrameworkError, match=message):
        framework.scan(str(root))


def fake_cli(stdout, returncode=0, stderr=''):
    calls = []

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    return runner, calls


def test_run_agent_builds_restricted_command_and_validates_output(monkeypatch, tmp_path):
    monkeypatch.setattr(claude, 'claude_command', lambda: ['claude'])
    monkeypatch.setenv('STUDIO_HELPER_TOKEN', 'secret')
    runner, calls = fake_cli(json.dumps({'is_error': False, 'structured_output': PROFILE}))
    from contracts import FrameworkProfile
    result = claude.run_agent('framework-analyzer', {'scan': {}}, FrameworkProfile, cwd=tmp_path,
                              tools=('Read', 'Glob', 'Grep'), runner=runner)
    assert result['testDirectory'] == 'tests/api'
    args, kwargs = calls[0]
    assert args[args.index('--tools') + 1] == 'Read,Glob,Grep'
    assert 'Read(**/.env)' in args[args.index('--disallowedTools') + 1]
    assert '--no-session-persistence' in args and '--json-schema' in args
    assert kwargs['cwd'] == str(tmp_path) and 'STUDIO_HELPER_TOKEN' not in kwargs['env']
    assert 'TASK_JSON' in kwargs['input']


def test_agent_prompt_includes_skills():
    prompt = claude.agent_prompt('framework-analyzer')
    assert 'senior SDET' in prompt and '# Skill: playwright-framework-conventions' in prompt


@pytest.mark.parametrize('stdout, returncode, message', [
    ('not json', 1, 'could not complete'),
    (json.dumps({'is_error': True, 'result': "You've hit your limit"}), 0, 'usage limit'),
    (json.dumps({'is_error': False, 'structured_output': {'summary': 'only'}}), 0, 'incomplete'),
])
def test_run_agent_failures_are_readable(monkeypatch, tmp_path, stdout, returncode, message):
    monkeypatch.setattr(claude, 'claude_command', lambda: ['claude'])
    runner, _ = fake_cli(stdout, returncode)
    from contracts import FrameworkProfile
    with pytest.raises(claude.ClaudeError, match=message):
        claude.run_agent('framework-analyzer', {}, FrameworkProfile, cwd=tmp_path, runner=runner)


def test_helper_loop_runs_analysis_end_to_end(project, tmp_path):
    lead, pid = project
    target = tmp_path / 'framework'
    shutil.copytree(SAMPLE, target)
    helper_client = pair_helper(lead)
    beat(helper_client)
    lead.put(f'/api/projects/{pid}/framework/path', json={'path': str(target)})
    lead.post(f'/api/projects/{pid}/framework/analyze')

    def fake_agent(name, task, schema, **options):
        assert name == 'framework-analyzer' and options['cwd'] == str(target)
        assert task['scan']['specFileCount'] == 1
        return PROFILE

    status = claude.ClaudeStatus(installed=True, loggedIn=True, version='2.1.301')
    logs = []
    helper = Helper(helper_client, log=logs.append, claude_status=lambda: status,
                    handlers={'framework.analyze': lambda job_input, report, **_: framework.analyze(job_input, report, agent=fake_agent)})
    assert helper.run_once() is True
    assert helper.run_once() is False
    view = lead.get(f'/api/projects/{pid}/framework').json()
    assert view['status'] == 'draft' and view['scan']['sampleSpecFiles'] == ['tests/api/pets.spec.ts']
    assert any('Done' in line for line in logs)


def test_helper_reports_job_failure(project, tmp_path):
    lead, pid = project
    helper_client = pair_helper(lead)
    beat(helper_client)
    lead.put(f'/api/projects/{pid}/framework/path', json={'path': str(tmp_path / 'missing')})
    job = lead.post(f'/api/projects/{pid}/framework/analyze').json()
    status = claude.ClaudeStatus(installed=True, loggedIn=True)
    Helper(helper_client, log=lambda _: None, claude_status=lambda: status).run_once()
    result = lead.get(f'/api/projects/{pid}/jobs/{job["id"]}').json()
    assert result['status'] == 'failed' and 'does not exist on this computer' in result['error']


def test_helper_refuses_to_run_against_a_different_portal_version(project, monkeypatch):
    from helper import runner
    lead, _ = project
    helper_client = pair_helper(lead)
    monkeypatch.setattr(runner, 'CONTRACT_FINGERPRINT', 'different')
    status = claude.ClaudeStatus(installed=True, loggedIn=True)
    with pytest.raises(runner.VersionMismatch):
        Helper(helper_client, log=lambda _: None, claude_status=lambda: status).run_once()

"""Choosing the Claude model in the portal and showing which model actually ran."""
import json
import subprocess

from pydantic import BaseModel

from helper import claude
from helper.claude import ClaudeStatus
from helper.runner import Helper

from .conftest import beat, pair_helper


class Answer(BaseModel):
    ok: bool


def cli_reporting(model_id: str, calls: list):
    def runner(args, **kwargs):
        calls.append(args)
        envelope = {'type': 'result', 'is_error': False, 'structured_output': {'ok': True},
                    'modelUsage': {model_id: {'inputTokens': 10, 'outputTokens': 2}}}
        return subprocess.CompletedProcess(args, 0, json.dumps(envelope), '')
    return runner


def run_job(helper_client, runner):
    """Run one framework.analyze job whose handler makes a single Claude call."""
    def handler(job_input, report, submit=None):
        claude.run_agent('framework-analyzer', {}, Answer, cwd='.', runner=runner)
        report('Analyzed', 90)
        return {}
    status = ClaudeStatus(installed=True, loggedIn=True)
    Helper(helper_client, log=lambda _: None, claude_status=lambda: status,
           handlers={'framework.analyze': handler}).run_once()


def start_job(lead, pid):
    lead.put(f'/api/projects/{pid}/framework/path', json={'path': 'C:\\work\\api-tests'})
    return lead.post(f'/api/projects/{pid}/framework/analyze').json()


def test_preferences_default_and_validation(make_user):
    user = make_user()
    prefs = user.get('/api/me/preferences').json()
    assert (prefs['claudeModel'], prefs['lastModels'], prefs['lastUsedAt']) == ('default', [], None)
    ids = [option['id'] for option in prefs['options']]
    assert ids[:2] == ['default', 'fable'] and {'opus', 'sonnet', 'haiku'} <= set(ids)
    assert {'id': 'claude-opus-4-8', 'label': 'Opus 4.8', 'family': 'Opus'} in prefs['options']
    assert {'claude-opus-5-5', 'claude-opus-5', 'claude-sonnet-5-5', 'claude-haiku-4-5'} <= set(ids)
    assert user.put('/api/me/preferences', json={'claudeModel': 'claude-opus-4-8'}).json()['claudeModel'] == 'claude-opus-4-8'
    # A full id that is not in the list yet (a newer release) is accepted; anything else is not.
    assert user.put('/api/me/preferences', json={'claudeModel': 'claude-opus-6-1'}).status_code == 200
    for bad in ('gpt-4', 'claude-opus', 'opus 4.8', 'claude-opus-4-8; rm -rf', '--model'):
        assert user.put('/api/me/preferences', json={'claudeModel': bad}).status_code == 422
    assert user.put('/api/me/preferences', json={'claudeModel': 'sonnet'}).json()['claudeModel'] == 'sonnet'
    assert user.get('/api/me/helper').json()['model']['claudeModel'] == 'sonnet'


def test_selected_model_is_passed_to_claude_and_actual_model_is_reported(project, monkeypatch):
    monkeypatch.setattr(claude, 'claude_command', lambda: ['claude'])
    lead, pid = project
    helper = pair_helper(lead)
    beat(helper)
    lead.put('/api/me/preferences', json={'claudeModel': 'opus'})
    job = start_job(lead, pid)
    calls = []
    run_job(helper, cli_reporting('claude-opus-5-5', calls))

    args = calls[0]
    assert args[args.index('--model') + 1] == 'opus'
    done = lead.get(f'/api/projects/{pid}/jobs/{job["id"]}').json()
    assert done['model'] == 'opus' and done['models'] == ['claude-opus-5-5'] and done['progress']['models'] == ['claude-opus-5-5']
    prefs = lead.get('/api/me/preferences').json()
    assert prefs['lastModels'] == ['claude-opus-5-5'] and prefs['lastUsedAt']


def test_default_model_sends_no_flag_and_switching_affects_new_jobs_only(project, monkeypatch):
    monkeypatch.setattr(claude, 'claude_command', lambda: ['claude'])
    lead, pid = project
    helper = pair_helper(lead)
    beat(helper)
    first = start_job(lead, pid)
    calls = []
    run_job(helper, cli_reporting('claude-sonnet-5-5', calls))
    assert '--model' not in calls[0]
    assert lead.get(f'/api/projects/{pid}/jobs/{first["id"]}').json()['model'] == 'default'

    lead.put('/api/me/preferences', json={'claudeModel': 'haiku'})
    second = start_job(lead, pid)
    run_job(helper, cli_reporting('claude-haiku-5-5', calls))
    assert calls[1][calls[1].index('--model') + 1] == 'haiku'
    assert lead.get(f'/api/projects/{pid}/jobs/{first["id"]}').json()['models'] == ['claude-sonnet-5-5']
    assert lead.get(f'/api/projects/{pid}/jobs/{second["id"]}').json()['models'] == ['claude-haiku-5-5']


def test_main_model_is_listed_before_small_helper_models():
    tracker = claude.JobModel()
    tracker.begin('sonnet')
    tracker.record({'modelUsage': {'claude-haiku-5-5': {'outputTokens': 40}, 'claude-sonnet-5-5': {'outputTokens': 900}}})
    tracker.record({'modelUsage': {'claude-haiku-5-5': {'outputTokens': 30}}})
    assert tracker.models() == ['claude-sonnet-5-5', 'claude-haiku-5-5']
    tracker.begin('default')
    assert tracker.selected is None and tracker.models() == []


def test_pinned_version_is_passed_through_and_unavailable_model_is_explained(project, monkeypatch):
    monkeypatch.setattr(claude, 'claude_command', lambda: ['claude'])
    lead, pid = project
    helper = pair_helper(lead)
    beat(helper)
    lead.put('/api/me/preferences', json={'claudeModel': 'claude-opus-4-8'})
    job = start_job(lead, pid)
    calls = []
    run_job(helper, cli_reporting('claude-opus-4-8', calls))
    assert calls[0][calls[0].index('--model') + 1] == 'claude-opus-4-8'
    assert lead.get(f'/api/projects/{pid}/jobs/{job["id"]}').json()['models'] == ['claude-opus-4-8']
    assert 'not available for your account' in claude.friendly_failure(
        "There's an issue with the selected model (claude-opus-9). It may not exist or you may not have access to it. "
        'API Error: 404 {"type":"error","error":{"type":"not_found_error","message":"model: claude-opus-9"}}')

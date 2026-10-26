"""Running jobs on a local OpenAI-compatible AI server instead of Claude, and switching between them."""
import json
import os
import subprocess

import httpx
import pytest
from pydantic import BaseModel

from contracts import LocalLlmStatus
from helper import claude, config, local_llm
from helper.claude import ClaudeError, ClaudeStatus
from helper.runner import Helper

from .conftest import beat, pair_helper


class Answer(BaseModel):
    ok: bool
    title: str = ''


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv('STUDIO_LLM_BASE_URL', 'http://llm.test:3300/')
    monkeypatch.setenv('STUDIO_LLM_API_KEY', 'sk-test')
    monkeypatch.delenv('STUDIO_LLM_MODELS', raising=False)
    claude.job_model.begin('local:qwen3.5:35b')
    yield
    claude.job_model.begin(None)


def fake(*replies, requests=None):
    """An httpx client whose server answers each chat request with the next reply."""
    queue = list(replies)

    def handle(request: httpx.Request):
        body = json.loads(request.content or b'{}')
        if requests is not None:
            requests.append((request, body))
        reply = queue.pop(0)
        if isinstance(reply, httpx.Response):
            return reply
        message = {'role': 'assistant', 'content': reply} if isinstance(reply, str) else {'role': 'assistant', 'content': '', **reply}
        return httpx.Response(200, json={'choices': [{'finish_reason': 'tool_calls' if 'tool_calls' in message else 'stop',
                                                      'message': message}],
                                         'usage': {'prompt_tokens': 100, 'completion_tokens': 20}})
    return httpx.Client(transport=httpx.MockTransport(handle))


def tool_call(name, **arguments):
    return {'tool_calls': [{'id': f'call_{name}', 'type': 'function',
                            'function': {'name': name, 'arguments': json.dumps(arguments)}}]}


def test_preferences_accept_local_models_and_reject_unsafe_ids(make_user):
    user = make_user()
    assert user.put('/api/me/preferences', json={'claudeModel': 'local:qwen3.5:35b'}).json()['claudeModel'] == 'local:qwen3.5:35b'
    assert user.put('/api/me/preferences', json={'claudeModel': 'opus'}).json()['claudeModel'] == 'opus'
    for bad in ('local:', 'local:qwen 3', 'local:-rf', 'local:a;rm -rf', 'local:' + 'x' * 60, 'qwen3.5:35b'):
        assert user.put('/api/me/preferences', json={'claudeModel': bad}).status_code == 422, bad


def test_helper_reports_local_server_to_the_portal(project):
    lead, _ = project
    helper = pair_helper(lead)
    status = LocalLlmStatus(configured=True, reachable=True, server='10.0.0.5', models=['qwen3.5:35b'])
    Helper(helper, log=lambda _: None, claude_status=lambda: ClaudeStatus(installed=False),
           local_status=lambda: status).heartbeat(force=True)
    state = lead.get('/api/me/helper').json()
    assert state['local'] == {'configured': True, 'reachable': True, 'server': '10.0.0.5', 'models': ['qwen3.5:35b'], 'error': ''}
    assert state['claude']['installed'] is False


def test_old_heartbeat_without_local_status_still_works(project):
    lead, _ = project
    helper = pair_helper(lead)
    beat(helper)
    assert lead.get('/api/me/helper').json()['local'] == {'configured': False, 'reachable': False, 'server': '', 'models': [], 'error': ''}


def test_local_model_runs_on_the_server_not_claude(server, monkeypatch):
    def no_claude():
        raise AssertionError('Claude Code must not be started for a local model')
    monkeypatch.setattr(claude, 'claude_command', no_claude)
    seen = []
    monkeypatch.setattr(local_llm, 'run_agent', lambda agent, task, schema, cwd, **kw: seen.append((agent, kw['model'])) or {'ok': True})
    assert claude.run_agent('unit-case-writer', {}, Answer, cwd='.') == {'ok': True}
    assert seen == [('unit-case-writer', 'local:qwen3.5:35b')]


def test_request_shape_usage_and_validated_answer(server, tmp_path):
    requests = []
    client = fake('{"ok": true, "title": "Create pet"}', requests=requests)
    result = local_llm.run_agent('unit-case-writer', {'endpoint': 'POST /pet'}, Answer, cwd=tmp_path,
                                 model='local:qwen3.5:35b', client=client)
    assert result == {'ok': True, 'title': 'Create pet'}
    request, body = requests[0]
    assert str(request.url) == 'http://llm.test:3300/v1/chat/completions'
    assert request.headers['authorization'] == 'Bearer sk-test'
    assert body['model'] == 'qwen3.5:35b' and body['reasoning_effort'] == 'none' and body['num_ctx'] == 65536
    assert body['response_format']['json_schema']['schema'] == Answer.model_json_schema() and 'tools' not in body
    assert body['messages'][0]['role'] == 'system' and '# Role' in body['messages'][0]['content']
    assert 'POST /pet' in body['messages'][1]['content']
    assert claude.job_model.models() == ['local:qwen3.5:35b']
    usage = claude.job_model.usage()
    assert (usage['calls'], usage['inputTokens'], usage['outputTokens'], usage['costUsd']) == (1, 100, 20, 0)


def test_invalid_answer_is_corrected_then_fails_after_the_limit(server, tmp_path):
    requests = []
    client = fake('Here you go: {"ok": "maybe"}', '```json\n{"ok": true}\n```', requests=requests)
    assert local_llm.run_agent('unit-case-writer', {}, Answer, cwd=tmp_path, model='local:q', client=client) == {'ok': True, 'title': ''}
    correction = requests[1][1]['messages'][-1]['content']
    assert 'not valid for the required JSON schema' in correction and 'ok' in correction

    client = fake('nope', 'still nope', 'never json')
    with pytest.raises(ClaudeError, match='does not match the expected format after 2 corrections'):
        local_llm.run_agent('unit-case-writer', {}, Answer, cwd=tmp_path, model='local:q', client=client)
    assert claude.job_model.usage()['agents']['unit-case-writer']['errors'] == 1


def test_tool_loop_reads_framework_files_but_never_secrets(server, tmp_path):
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'pet.spec.ts').write_text("import { test } from '@playwright/test';\n", encoding='utf-8')
    (tmp_path / '.env').write_text('API_TOKEN=secret-value', encoding='utf-8')
    requests = []
    client = fake(tool_call('glob', pattern='**/*.spec.ts'), tool_call('read_file', path='tests/pet.spec.ts'),
                  tool_call('read_file', path='.env'), tool_call('read_file', path='../outside.txt'),
                  tool_call('grep', pattern='secret'), '{"ok": true}', requests=requests)
    result = local_llm.run_agent('script-writer', {}, Answer, cwd=tmp_path, tools=('Read', 'Glob', 'Grep'),
                                 model='local:q', client=client)
    assert result['ok'] is True
    assert [t['function']['name'] for t in requests[0][1]['tools']] == ['read_file', 'glob', 'grep']
    tool_results = [m['content'] for m in requests[-1][1]['messages'] if m['role'] == 'tool']
    assert tool_results[0] == 'tests/pet.spec.ts'
    assert "1\timport { test } from '@playwright/test';" in tool_results[1]
    assert 'cannot be read' in tool_results[2] and 'outside the framework folder' in tool_results[3]
    assert tool_results[4] == 'No matches.'
    assert 'secret-value' not in json.dumps(requests[-1][1])


def test_tool_turn_limit_forces_a_final_answer(server, tmp_path):
    requests = []
    client = fake(tool_call('glob', pattern='*'), tool_call('glob', pattern='*'), '{"ok": true}', requests=requests)
    assert local_llm.run_agent('framework-analyzer', {}, Answer, cwd=tmp_path, tools=('Glob',), max_turns=2,
                               model='local:q', client=client)['ok'] is True
    last = requests[-1][1]
    assert 'tools' not in last and 'response_format' in last
    assert last['messages'][-1]['content'] == 'Stop using tools and give your final JSON answer now.'


@pytest.mark.parametrize('response, message', [
    (httpx.Response(403, json={'error': {'message': "The requested model 'gemma4:26b' is not available for this API key"}}),
     'not available for your API key'),
    (httpx.Response(401, json={'error': {'message': 'invalid key'}}), 'rejected the API key'),
    (httpx.Response(429, text='busy'), 'busy'),
    (httpx.Response(500, text='boom'), 'HTTP 500'),
])
def test_server_errors_are_explained(server, tmp_path, response, message):
    with pytest.raises(ClaudeError, match=message):
        local_llm.run_agent('unit-case-writer', {}, Answer, cwd=tmp_path, model='local:q', client=fake(response))


def test_truncated_prompt_and_unfinished_answer_are_reported(server, tmp_path, monkeypatch):
    monkeypatch.setenv('STUDIO_LLM_CONTEXT', '4096')
    full = httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok": true}'}}],
                                     'usage': {'prompt_tokens': 4096, 'completion_tokens': 1}})
    with pytest.raises(ClaudeError, match='too long for the local model'):
        local_llm.run_agent('unit-case-writer', {}, Answer, cwd=tmp_path, model='local:q', client=fake(full))
    cut = httpx.Response(200, json={'choices': [{'finish_reason': 'length', 'message': {'content': '{"ok": tr'}}], 'usage': {}})
    with pytest.raises(ClaudeError, match='ran out of room'):
        local_llm.run_agent('unit-case-writer', {}, Answer, cwd=tmp_path, model='local:q', client=fake(cut))


def test_not_configured_is_explained(monkeypatch, tmp_path):
    monkeypatch.delenv('STUDIO_LLM_BASE_URL', raising=False)
    with pytest.raises(ClaudeError, match='No local AI server is set up'):
        local_llm.run_agent('unit-case-writer', {}, Answer, cwd=tmp_path, model='local:q')
    assert local_llm.status() == LocalLlmStatus(configured=False)


def test_status_lists_chat_models_only(server):
    listed = {'data': [{'id': 'qwen3.5:35b', 'mode': 'chat'}, {'id': 'qwen3-embedding:0.6b', 'mode': 'embedding'},
                       {'id': 'nomic-embed-text'}]}
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=listed)))
    assert local_llm.status(client) == LocalLlmStatus(configured=True, reachable=True, server='llm.test', models=['qwen3.5:35b'])
    denied = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(401)))
    assert 'rejected the API key' in local_llm.status(denied).error


def test_api_key_never_reaches_claude_or_node(monkeypatch):
    monkeypatch.setenv('STUDIO_LLM_API_KEY', 'sk-test')
    assert 'STUDIO_LLM_API_KEY' not in claude._clean_env()


def test_env_file_fills_missing_settings_only(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('# comment\nSTUDIO_LLM_BASE_URL="http://from-file:3300"\nexport STUDIO_LLM_MODELS=a,b\nSTUDIO_LLM_API_KEY=file-key\n',
                   encoding='utf-8')
    monkeypatch.delenv('STUDIO_LLM_BASE_URL', raising=False)
    monkeypatch.delenv('STUDIO_LLM_MODELS', raising=False)
    monkeypatch.setenv('STUDIO_LLM_API_KEY', 'already-set')
    config.load_env(env)
    assert os.environ['STUDIO_LLM_BASE_URL'] == 'http://from-file:3300'
    assert os.environ['STUDIO_LLM_MODELS'] == 'a,b' and os.environ['STUDIO_LLM_API_KEY'] == 'already-set'


def test_helper_explains_an_older_portal_instead_of_crashing():
    from helper.runner import VersionMismatch
    old_portal = httpx.Client(base_url='http://portal.test', transport=httpx.MockTransport(
        lambda request: httpx.Response(422, json={'detail': 'local: Extra inputs are not permitted'})))
    helper = Helper(old_portal, log=lambda _: None, claude_status=lambda: ClaudeStatus(installed=True),
                    local_status=lambda: LocalLlmStatus())
    with pytest.raises(VersionMismatch, match='newer than the portal'):
        helper.heartbeat(force=True)

"""Run our agents on an OpenAI-compatible server (LiteLLM, Ollama, vLLM) instead of Claude Code.

A model id such as ``local:qwen3.5:35b`` selects this provider. The agent instructions, skills and output
schemas are the same ones Claude gets; only the transport differs. The server address and key come from the
helper's environment (``STUDIO_LLM_BASE_URL``, ``STUDIO_LLM_API_KEY``), never from the portal.
"""
import fnmatch
import json
import os
import re
import threading
import time
from pathlib import Path

import httpx
from pydantic import BaseModel, ValidationError

from contracts import LOCAL_MODEL_PREFIX, LocalLlmStatus

from .claude import ClaudeError, agent_prompt, job_model, task_prompt

# Files the agents may never read, the same rule Claude Code gets.
BLOCKED_FILES = ('.env', '.env.*', '*.pem', '*.key')
SKIPPED_DIRS = {'node_modules', '.git', 'dist', 'build', 'playwright-report', 'test-results', '.venv', '__pycache__'}
MAX_READ_CHARS = 40_000
MAX_LIST = 200
MAX_GREP = 100
# How many times a model may correct an answer that is not valid JSON for the schema.
MAX_CORRECTIONS = 2
_slots_lock = threading.Lock()
_slots: tuple[int, threading.BoundedSemaphore] | None = None


def settings() -> dict:
    env = os.environ.get
    return {'baseUrl': (env('STUDIO_LLM_BASE_URL') or '').strip().rstrip('/'),
            'apiKey': (env('STUDIO_LLM_API_KEY') or '').strip(),
            'models': [m.strip() for m in (env('STUDIO_LLM_MODELS') or '').split(',') if m.strip()],
            'timeout': int(env('STUDIO_LLM_TIMEOUT') or 900),
            'concurrency': max(1, int(env('STUDIO_LLM_CONCURRENCY') or 2)),
            'context': int(env('STUDIO_LLM_CONTEXT') or 65536),
            'thinking': (env('STUDIO_LLM_THINKING') or 'false').lower() == 'true'}


def is_local(model: str | None) -> bool:
    return bool(model) and model.startswith(LOCAL_MODEL_PREFIX)


def _server_name(base_url: str) -> str:
    return httpx.URL(base_url).host if base_url else ''


def _url(base_url: str, path: str) -> str:
    # LiteLLM and vLLM serve /v1/...; accept a base URL given with or without the /v1 suffix.
    return base_url + path if base_url.endswith('/v1') else base_url + '/v1' + path


def _headers(config: dict) -> dict:
    return {'Authorization': f"Bearer {config['apiKey']}"} if config['apiKey'] else {}


def status(client: httpx.Client | None = None) -> LocalLlmStatus:
    config = settings()
    if not config['baseUrl']:
        return LocalLlmStatus(configured=False)
    server = _server_name(config['baseUrl'])
    try:
        own = client or httpx.Client(timeout=15)
        try:
            response = own.get(_url(config['baseUrl'], '/models'), headers=_headers(config))
        finally:
            if client is None:
                own.close()
    except httpx.HTTPError as exc:
        return LocalLlmStatus(configured=True, server=server, models=config['models'],
                              error=f'Cannot reach the local AI server ({exc.__class__.__name__}).')
    if response.status_code in (401, 403):
        return LocalLlmStatus(configured=True, server=server, models=config['models'],
                              error='The local AI server rejected the API key (STUDIO_LLM_API_KEY).')
    if response.is_error:
        return LocalLlmStatus(configured=True, server=server, models=config['models'],
                              error=f'The local AI server returned HTTP {response.status_code}.')
    try:
        listed = response.json().get('data') or []
    except ValueError:
        listed = []
    chat = [str(m.get('id')) for m in listed if isinstance(m, dict) and m.get('id') and m.get('mode', 'chat') != 'embedding'
            and 'embed' not in str(m.get('id')).lower()]
    return LocalLlmStatus(configured=True, reachable=True, server=server, models=(chat or config['models'])[:30])


def _semaphore(size: int) -> threading.BoundedSemaphore:
    """One GPU server cannot run many requests at once; limit parallel calls across the job's threads."""
    global _slots
    with _slots_lock:
        if _slots is None or _slots[0] != size:
            _slots = (size, threading.BoundedSemaphore(size))
        return _slots[1]


# --- Read-only file tools for the framework and script agents ---------------------------------------------

TOOL_SPECS = {
    'Read': {'type': 'function', 'function': {
        'name': 'read_file', 'description': 'Read a text file of the framework. Returns numbered lines.',
        'parameters': {'type': 'object', 'properties': {
            'path': {'type': 'string', 'description': 'Path relative to the framework root'},
            'offset': {'type': 'integer', 'description': 'First line to read (1-based)', 'default': 1},
            'limit': {'type': 'integer', 'description': 'Number of lines to read', 'default': 400}},
            'required': ['path']}}},
    'Glob': {'type': 'function', 'function': {
        'name': 'glob', 'description': 'List framework files matching a glob pattern such as "tests/**/*.spec.ts".',
        'parameters': {'type': 'object', 'properties': {'pattern': {'type': 'string'}}, 'required': ['pattern']}}},
    'Grep': {'type': 'function', 'function': {
        'name': 'grep', 'description': 'Search framework files for a regular expression. Returns file:line: text.',
        'parameters': {'type': 'object', 'properties': {
            'pattern': {'type': 'string', 'description': 'Regular expression'},
            'glob': {'type': 'string', 'description': 'Only search files matching this glob, e.g. "**/*.ts"'}},
            'required': ['pattern']}}},
}


def _blocked(path: Path) -> bool:
    return any(fnmatch.fnmatch(path.name.lower(), pattern) for pattern in BLOCKED_FILES)


def _inside(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f'{relative} is outside the framework folder.')
    if _blocked(target):
        raise ValueError(f'{relative} may contain secrets and cannot be read.')
    return target


def _files(root: Path):
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIPPED_DIRS)
        for name in sorted(names):
            path = Path(folder) / name
            if not _blocked(path):
                yield path


def _match(relative: str, pattern: str) -> bool:
    pattern = pattern.lstrip('./')
    return fnmatch.fnmatch(relative, pattern) or (pattern.startswith('**/') and fnmatch.fnmatch(relative, pattern[3:]))


def run_tool(root: Path, name: str, arguments: dict) -> str:
    """Run one read-only tool call inside ``root`` and return its text result (errors included)."""
    try:
        if name == 'read_file':
            target = _inside(root, str(arguments.get('path', '')))
            if not target.is_file():
                return f"Error: {arguments.get('path')} is not a file."
            lines = target.read_text(encoding='utf-8', errors='replace').splitlines()
            start = max(1, int(arguments.get('offset') or 1))
            count = max(1, min(2000, int(arguments.get('limit') or 400)))
            text = '\n'.join(f'{number}\t{line}' for number, line in enumerate(lines[start - 1:start - 1 + count], start))
            more = f'\n... {len(lines) - (start - 1 + count)} more lines' if len(lines) > start - 1 + count else ''
            return (text[:MAX_READ_CHARS] + more) or '(empty file)'
        if name == 'glob':
            pattern = str(arguments.get('pattern') or '**/*')
            found = [p.relative_to(root).as_posix() for p in _files(root) if _match(p.relative_to(root).as_posix(), pattern)]
            return '\n'.join(found[:MAX_LIST]) + (f'\n... {len(found) - MAX_LIST} more' if len(found) > MAX_LIST else '') or 'No files found.'
        if name == 'grep':
            expression = re.compile(str(arguments.get('pattern', '')))
            only = str(arguments.get('glob') or '')
            hits = []
            for path in _files(root):
                relative = path.relative_to(root).as_posix()
                if (only and not _match(relative, only)) or path.stat().st_size > 1_000_000:
                    continue
                for number, line in enumerate(path.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
                    if expression.search(line):
                        hits.append(f'{relative}:{number}: {line.strip()[:300]}')
                        if len(hits) >= MAX_GREP:
                            return '\n'.join(hits) + '\n... more matches not shown'
            return '\n'.join(hits) or 'No matches.'
        return f'Error: unknown tool {name}.'
    except (OSError, ValueError, re.error) as exc:
        return f'Error: {exc}'


# --- The agent loop -------------------------------------------------------------------------------------------

def _output_rules(schema: type[BaseModel], tools: bool) -> str:
    look = ('Use the tools to study the framework first. When you have what you need, stop calling tools and '
            if tools else '')
    return (f'\n\n# Output\n\n{look}Reply with exactly one JSON object that matches this JSON schema. No markdown, '
            f'no code fences, no text before or after it.\n\n'
            + json.dumps(schema.model_json_schema(), ensure_ascii=False, separators=(',', ':')))


def _parse(content: str):
    text = (content or '').strip()
    fenced = re.match(r'^```(?:json)?\s*(.*?)\s*```$', text, re.S)
    if fenced:
        text = fenced.group(1)
    text = re.sub(r'^<think>.*?</think>\s*', '', text, flags=re.S)
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find('{'), text.rfind('}')
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def friendly_failure(status_code: int, text: str) -> str:
    lowered = text.lower()
    if status_code in (401, 403) and ('model' in lowered and ('not available' in lowered or 'access' in lowered)):
        return 'This local model is not available for your API key. Pick another model in the Model menu.'
    if status_code in (401, 403):
        return 'The local AI server rejected the API key. Check STUDIO_LLM_API_KEY in the helper .env file.'
    if status_code == 404 or 'not found' in lowered:
        return 'The local AI server does not have this model. Pick another model in the Model menu.'
    if status_code == 429:
        return 'The local AI server is busy or its rate limit was reached. Try again in a few minutes.'
    if 'context' in lowered and ('length' in lowered or 'window' in lowered or 'too long' in lowered):
        return 'The task is too long for the local model\'s context window. Raise STUDIO_LLM_CONTEXT or use Claude.'
    return ''


class _Call:
    """One agent call: the conversation, its usage and the request settings."""

    def __init__(self, agent: str, model: str, client: httpx.Client, config: dict, deadline: float):
        self.agent, self.model, self.client, self.config, self.deadline = agent, model, client, config, deadline
        self.name = model[len(LOCAL_MODEL_PREFIX):]

    def send(self, messages: list, tools: list | None, schema: dict | None) -> dict:
        remaining = self.deadline - time.time()
        if remaining <= 0:
            raise ClaudeError(f'The local model did not finish within {self.config["timeout"] // 60} minutes.')
        body = {'model': self.name, 'messages': messages, 'temperature': 0.2, 'num_ctx': self.config['context'],
                # LiteLLM caches answers; a retried or regenerated task needs a fresh one.
                'cache': {'no-cache': True}}
        if not self.config['thinking']:
            body['reasoning_effort'] = 'none'
        if tools:
            body['tools'] = tools
        elif schema:
            body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'answer', 'schema': schema}}
        with _semaphore(self.config['concurrency']):
            try:
                response = self.client.post(_url(self.config['baseUrl'], '/chat/completions'), json=body,
                                            headers=_headers(self.config), timeout=min(remaining, self.config['timeout']))
            except httpx.TimeoutException as exc:
                raise ClaudeError(f'The local model did not answer within {self.config["timeout"] // 60} minutes.') from exc
            except httpx.HTTPError as exc:
                raise ClaudeError(f'Cannot reach the local AI server: {exc.__class__.__name__}.') from exc
        if response.is_error:
            detail = friendly_failure(response.status_code, response.text)
            raise ClaudeError(detail or f'The local AI server returned HTTP {response.status_code}: {response.text[:500]}')
        try:
            reply = response.json()
            choice = reply['choices'][0]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ClaudeError('The local AI server sent an answer in an unexpected format.') from exc
        usage = reply.get('usage') or {}
        job_model.record({'modelUsage': {self.model: {'inputTokens': usage.get('prompt_tokens') or 0,
                                                      'outputTokens': usage.get('completion_tokens') or 0}}}, self.agent)
        if (usage.get('prompt_tokens') or 0) >= self.config['context'] - 16:
            raise ClaudeError('The task is too long for the local model\'s context window (STUDIO_LLM_CONTEXT='
                              f'{self.config["context"]}). Raise it if the server allows, or use Claude for this job.')
        if choice.get('finish_reason') == 'length':
            raise ClaudeError('The local model ran out of room before finishing its answer. Raise STUDIO_LLM_CONTEXT '
                              'or use Claude for this job.')
        return choice.get('message') or {}


def run_agent(agent: str, task: dict, schema: type[BaseModel], cwd: str | Path, tools: tuple[str, ...] = (),
              timeout: int | None = None, max_turns: int = 40, model: str = '', client: httpx.Client | None = None) -> dict:
    """Run one agent on the local server and return output validated against ``schema``."""
    config = settings()
    if not config['baseUrl']:
        raise ClaudeError('No local AI server is set up on this computer. Add STUDIO_LLM_BASE_URL and STUDIO_LLM_API_KEY '
                          'to the helper .env file and restart the helper, or pick a Claude model.')
    timeout = min(timeout or config['timeout'], config['timeout'] * 4)
    root = Path(cwd).resolve()
    specs = [TOOL_SPECS[name] for name in tools if name in TOOL_SPECS]
    json_schema = schema.model_json_schema()
    messages = [{'role': 'system', 'content': agent_prompt(agent) + _output_rules(schema, bool(specs))},
                {'role': 'user', 'content': task_prompt(task)}]
    own = client or httpx.Client()
    call = _Call(agent, model, own, config, time.time() + timeout)
    corrections, turns, use_tools = 0, 0, bool(specs)
    try:
        while True:
            turns += 1
            if turns > max_turns + MAX_CORRECTIONS + 1:
                raise ClaudeError(f'The local model did not finish the {agent} task within {max_turns} turns.')
            if use_tools and turns > max_turns:
                use_tools = False  # out of tool turns: ask for the answer now
                messages.append({'role': 'user', 'content': 'Stop using tools and give your final JSON answer now.'})
            message = call.send(messages, specs if use_tools else None, None if use_tools else json_schema)
            calls = message.get('tool_calls') or []
            if calls and use_tools:
                messages.append({'role': 'assistant', 'content': message.get('content') or '', 'tool_calls': calls})
                for item in calls:
                    function = item.get('function') or {}
                    try:
                        arguments = json.loads(function.get('arguments') or '{}')
                    except ValueError:
                        arguments = {}
                    messages.append({'role': 'tool', 'tool_call_id': item.get('id', ''),
                                     'content': run_tool(root, function.get('name', ''), arguments if isinstance(arguments, dict) else {})})
                continue
            content = message.get('content') or ''
            try:
                return schema.model_validate(_parse(content)).model_dump()
            except (ValueError, ValidationError) as exc:
                corrections += 1
                if corrections > MAX_CORRECTIONS:
                    raise ClaudeError(f'The local model returned {agent} output that does not match the expected format '
                                      f'after {MAX_CORRECTIONS} corrections: {str(exc)[:500]}') from exc
                # Ask for the corrected answer with the schema enforced and no tools.
                use_tools = False
                messages += [{'role': 'assistant', 'content': content[:20_000]},
                             {'role': 'user', 'content': 'That answer is not valid for the required JSON schema: '
                                                         f'{str(exc)[:1500]}\nReply again with only the corrected, complete JSON object.'}]
    except ClaudeError:
        job_model.fail(agent)
        raise
    finally:
        if client is None:
            own.close()

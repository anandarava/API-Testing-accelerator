"""Script generation: write one spec per endpoint into the user's framework, then type-check, lint and list it.

Generated tests are never executed against an API here; the QA runs them.
"""
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath

from contracts.scripts import ScriptOutput

from .claude import ClaudeError, run_agent
from .framework import scan

MANIFEST = Path('.api-test-studio') / 'manifest.json'
SPEC_SUFFIX = re.compile(r'\.(spec|test)\.(ts|mts|cts)$')
FORBIDDEN = [
    (re.compile(r'\bchild_process\b'), 'child_process'),
    (re.compile(r'''from\s+['"](node:)?fs(/promises)?['"]|require\(\s*['"](node:)?fs'''), 'file-system access'),
    (re.compile(r'''['"]node:(fs|child_process|net|dgram|cluster|worker_threads|vm|os)['"]'''), 'Node system modules'),
    (re.compile(r'\beval\s*\('), 'eval'),
    (re.compile(r'\bnew\s+Function\s*\('), 'new Function'),
    (re.compile(r'process\.exit'), 'process.exit'),
    (re.compile(r'\btest\.only\b|\bdescribe\.only\b'), 'test.only'),
    (re.compile(r'waitForTimeout\s*\(|setTimeout\s*\(\s*\w*\s*,\s*\d{3,}'), 'fixed waits'),
    (re.compile(r'@ts-(ignore|nocheck)'), '@ts-ignore'),
]
SAFE_ENV = ('PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'HOME', 'USERPROFILE', 'APPDATA',
            'LOCALAPPDATA', 'PROGRAMDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'NUMBER_OF_PROCESSORS', 'LANG')
CHECK_TIMEOUT = 300
MAX_FIX_ROUNDS = 2


class ScriptError(RuntimeError):
    """The generated file cannot be used; reported on the endpoint in the portal."""


def digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


# --- Manifest of files this tool manages -------------------------------------------------------

def load_manifest(root: Path) -> dict:
    path = root / MANIFEST
    if not path.is_file():
        return {'version': 1, 'files': {}}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        assert data.get('version') == 1 and isinstance(data.get('files'), dict)
        return data
    except Exception as exc:
        raise ScriptError(f'{MANIFEST.as_posix()} is damaged. Fix or delete it, then try again.') from exc


def save_manifest(root: Path, manifest: dict):
    path = root / MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding='utf-8')
    temporary.replace(path)


# --- Validation -------------------------------------------------------------------------------------

def safe_path(root: Path, relative: str) -> Path:
    clean = relative.replace('\\', '/').strip()
    parts = PurePosixPath(clean).parts
    if not clean or clean.startswith('/') or re.match(r'^[A-Za-z]:', clean) or '..' in parts:
        raise ScriptError(f'Claude proposed an unsafe file path: {relative}')
    if not SPEC_SUFFIX.search(clean) or any(p in ('node_modules', '.git', '.api-test-studio') for p in parts):
        raise ScriptError(f'Generated tests must be .spec.ts/.test.ts files outside node_modules: {relative}')
    target = (root / clean).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ScriptError(f'Claude proposed a path outside the framework: {relative}')
    return target


def problems_in(content: str, codes: list[str]) -> list[str]:
    found = [f'Uses {label}, which is not allowed in generated tests.' for pattern, label in FORBIDDEN if pattern.search(content)]
    missing = [code for code in codes if not re.search(rf'''['"`]{re.escape(code)}\b''', content)]
    if missing:
        found.append('These test case codes have no test whose title starts with the code: ' + ', '.join(missing))
    return found


def suggested_path(profile: dict, endpoint: dict) -> str:
    directory = (profile.get('testDirectory') or 'tests/api').strip('/').replace('\\', '/')
    if endpoint.get('flow'):
        slug = '-'.join(re.findall(r'[a-z0-9]+', endpoint['path'].lower())[:8]) or 'flow'
        return f'{directory}/flows/{slug}.flow.spec.ts'
    suffix = '.roles' if endpoint.get('roleCases') else ''
    segments = [s for s in endpoint['path'].split('/') if s and not s.startswith('{') and not re.fullmatch(r'v\d+', s)]
    words = [w for s in segments[-2:] for w in re.split(r'[^A-Za-z0-9]+', s) if w]
    name = '-'.join(words or ['root']).lower()
    if '{' in endpoint['path'].rsplit('/', 1)[-1]:
        name += '-by-id'
    return f"{directory}/{name}.{endpoint['method'].lower()}{suffix}.spec.ts"


# --- Checks -------------------------------------------------------------------------------------------

def _env() -> dict:
    env = {key: value for key, value in os.environ.items() if key.upper() in SAFE_ENV}
    env.update(CI='1', FORCE_COLOR='0', NO_COLOR='1')
    return env


def _run(args, root: Path, runner):
    try:
        result = runner(args, cwd=str(root), env=_env(), capture_output=True, text=True, encoding='utf-8',
                        errors='replace', timeout=CHECK_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, f'Timed out after {CHECK_TIMEOUT} seconds.'
    return result.returncode, (result.stdout + '\n' + result.stderr).strip()


def run_checks(root: Path, relative: str, expected_tests: int, runner=subprocess.run) -> list[dict]:
    node = shutil.which('node')
    modules = root / 'node_modules'
    if not node or not modules.is_dir():
        reason = 'Node.js is not installed.' if not node else 'Run npm install in your framework to enable checks.'
        return [{'name': name, 'status': 'skipped', 'detail': reason, 'output': ''} for name in ('typecheck', 'lint', 'discovery')]
    checks = []
    posix = relative.replace('\\', '/')

    tsc = modules / 'typescript' / 'bin' / 'tsc'
    if tsc.is_file() and (root / 'tsconfig.json').is_file():
        code, output = _run([node, str(tsc), '--noEmit', '--pretty', 'false', '-p', 'tsconfig.json'], root, runner)
        mine = [line for line in output.splitlines() if line.replace('\\', '/').startswith(posix)]
        if code is None:
            checks.append({'name': 'typecheck', 'status': 'failed', 'detail': output, 'output': ''})
        elif mine:
            checks.append({'name': 'typecheck', 'status': 'failed', 'detail': f'{len(mine)} TypeScript error(s) in this file',
                           'output': '\n'.join(mine)[-8000:]})
        else:
            other = ' Other files in the project have TypeScript errors.' if code else ''
            checks.append({'name': 'typecheck', 'status': 'passed', 'detail': 'No TypeScript errors in this file.' + other, 'output': ''})
    else:
        checks.append({'name': 'typecheck', 'status': 'skipped', 'detail': 'TypeScript or tsconfig.json not found.', 'output': ''})

    eslint = modules / 'eslint' / 'bin' / 'eslint.js'
    has_config = any(root.glob('eslint.config.*')) or any(root.glob('.eslintrc*'))
    if eslint.is_file() and has_config:
        code, output = _run([node, str(eslint), '--no-warn-ignored', posix], root, runner)
        status = 'passed' if code == 0 else 'failed'
        checks.append({'name': 'lint', 'status': status, 'detail': 'No lint errors.' if code == 0 else 'ESLint reported problems.',
                       'output': '' if code == 0 else output[-8000:]})
    else:
        checks.append({'name': 'lint', 'status': 'skipped', 'detail': 'ESLint is not configured in this framework.', 'output': ''})

    cli = modules / '@playwright' / 'test' / 'cli.js'
    if cli.is_file():
        code, output = _run([node, str(cli), 'test', '--list', posix], root, runner)
        match = re.search(r'Total:\s+(\d+)\s+tests?', output)
        listed = int(match.group(1)) if match else 0
        if code == 0 and listed and listed % expected_tests == 0:
            projects = listed // expected_tests
            suffix = f' across {projects} Playwright projects' if projects > 1 else ''
            checks.append({'name': 'discovery', 'status': 'passed', 'detail': f'Playwright found {listed} tests{suffix}.', 'output': ''})
        else:
            detail = f'Playwright found {listed} tests; expected {expected_tests}.' if code == 0 else 'Playwright could not load the file.'
            checks.append({'name': 'discovery', 'status': 'failed', 'detail': detail, 'output': output[-8000:]})
    else:
        checks.append({'name': 'discovery', 'status': 'skipped', 'detail': '@playwright/test is not installed.', 'output': ''})
    return checks


# --- Generation ----------------------------------------------------------------------------------------

def _case_brief(case: dict) -> dict:
    keys = ('objective', 'preconditions', 'request', 'expected', 'steps', 'testData', 'cleanup', 'roles', 'userSlot',
            'verifyUnchanged')
    return {'code': case['code'], 'title': case['title'], 'category': case['category'], 'priority': case['priority'],
            **{key: case['content'][key] for key in keys if key in case['content']}}


def write_endpoint(root: Path, profile: dict, api: dict, item: dict, manifest: dict, report, agent=run_agent,
                   runner=subprocess.run, credential_keys: list[str] | None = None) -> dict:
    endpoint, cases = item['details'], item['cases']
    codes = [case['code'] for case in cases]
    managed = {path: entry for path, entry in manifest['files'].items() if entry.get('endpointId') == item['endpointKey']}
    existing_path = next(iter(managed), None)
    existing = None
    if existing_path and (root / existing_path).is_file():
        existing = {'path': existing_path, 'content': (root / existing_path).read_text(encoding='utf-8', errors='replace')}
    kind = 'flow' if endpoint.get('flow') else 'roles' if endpoint.get('roleCases') else 'endpoint'
    task = {'kind': kind, 'profile': profile, 'api': api, 'endpoint': endpoint,
            'cases': [_case_brief(c) for c in cases],
            'existingFile': existing, 'suggestedPath': existing_path or suggested_path(profile, endpoint)}
    if kind == 'roles':
        task['credentialKeys'] = credential_keys or []
    output = agent('script-writer', task, ScriptOutput, cwd=root, tools=('Read', 'Glob', 'Grep'), max_turns=60)

    path = output['file']['path'].replace('\\', '/')
    target = safe_path(root, path)
    if existing_path and path != existing_path:
        raise ScriptError(f'Claude tried to move the managed file {existing_path} to {path}.')
    if not existing_path and target.exists():
        raise ScriptError(f'{path} already exists and was not created by API Test Studio. It was not overwritten.')
    previous = existing['content'] if existing else ''
    content, rounds, checks = output['file']['content'], 0, []
    env_variables, notes = output['envVariables'], output['notes']
    while True:
        issues = problems_in(content, codes)
        if not issues:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8', newline='\n')
            report_check = f'checking {path} (TypeScript, lint, test discovery)'
            report(report_check)
            checks = run_checks(root, path, len(codes), runner)
            issues = [f"{c['name']}: {c['detail']}\n{c['output']}" for c in checks if c['status'] == 'failed']
        if not issues or rounds >= MAX_FIX_ROUNDS:
            break
        rounds += 1
        report(f'fixing {len(issues)} problem(s), round {rounds} of {MAX_FIX_ROUNDS}')
        fixed = agent('script-fixer', {'file': {'path': path, 'content': content}, 'problems': issues, 'profile': profile,
                                       'cases': [_case_brief(c) for c in cases]},
                      ScriptOutput, cwd=root, tools=('Read', 'Glob', 'Grep'), max_turns=40)
        content = fixed['file']['content']
        env_variables = list(dict.fromkeys(env_variables + fixed['envVariables']))
        notes = '\n'.join(filter(None, [notes, fixed['notes']]))
    unsafe = problems_in(content, codes)
    if unsafe:
        # Never leave a file with forbidden code or missing cases in the framework.
        if previous:
            target.write_text(previous, encoding='utf-8', newline='\n')
        elif target.exists():
            target.unlink()
        raise ScriptError('The generated file was not saved: ' + ' '.join(unsafe))

    manifest['files'][path] = {'endpointId': item['endpointKey'], 'sha256': digest(content), 'caseCodes': codes}
    save_manifest(root, manifest)
    diff = ''.join(difflib.unified_diff(previous.splitlines(keepends=True), content.splitlines(keepends=True),
                                        fromfile=f'a/{path}' if previous else '/dev/null', tofile=f'b/{path}'))
    return {'endpointId': item['id'], 'path': path, 'content': content, 'sha256': digest(content), 'diff': diff,
            'caseIds': [case['id'] for case in cases], 'checks': checks, 'fixRounds': rounds,
            'envVariables': env_variables, 'notes': notes}


def generate(job_input: dict, report, submit=None, agent=run_agent, runner=subprocess.run) -> dict:
    root = Path(job_input['frameworkPath']).resolve()
    report('Checking your framework folder', 2)
    found = scan(str(root))
    credential_keys = list(getattr(found, 'envExampleKeys', None) or (found.get('envExampleKeys', []) if isinstance(found, dict) else []))
    manifest = load_manifest(root)
    endpoints, done = job_input['endpoints'], 0
    for index, item in enumerate(endpoints):
        is_flow = bool(item['details'].get('flow'))
        label = f"flow {item['cases'][0]['code']}" if is_flow else f"{item['details']['method']} {item['details']['path']}"
        if item['details'].get('roleCases'):
            label += ' (role tests)'
        share = 100 / len(endpoints)

        def step(message, fraction=0.5):
            report(f'{label} ({index + 1} of {len(endpoints)}): {message}', int(share * (index + fraction)))

        step('writing the chained flow test' if is_flow else f"writing {len(item['cases'])} tests in your framework's style", 0.1)
        try:
            result = write_endpoint(root, job_input['profile'], job_input['api'], item, manifest, step, agent, runner,
                                    credential_keys)
            done += 1
        except (ClaudeError, ScriptError) as exc:
            if 'usage limit' in str(exc) or 'not signed in' in str(exc):
                raise ClaudeError(f'{exc} Finished {done} of {len(endpoints)} endpoints.') from exc
            result = {'endpointId': item['id'], 'error': str(exc)[:1500]}
        if submit:
            submit(result)
    if not done:
        raise ScriptError('No scripts could be generated. See the endpoint errors in the portal.')
    report('Finished', 100)
    return {'endpoints': done, 'failed': len(endpoints) - done}

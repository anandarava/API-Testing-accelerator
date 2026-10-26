"""Role-based test cases.

analyze: access-control-analyst reads the roles file and the API and builds the permission grid.
generate: per endpoint, role-case-designer writes the role cases, code checks them (known roles, documented
statuses, a refusal for every denied role...), role-case-reviewer reviews, serious findings are fixed, and only
the changed cases are re-reviewed. Endpoints run in parallel and are sent to the portal as they finish.
"""
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

from contracts.flows import chunk_operations, compact_endpoint
from contracts.roles import (AccessModel, RoleCaseSet, access_row, covered, normalise, role_gaps, role_requirements,
                             validate_role_cases)
from contracts.unit import CaseReview

from . import claude
from .claude import ClaudeError, run_agent

PARALLEL_ENDPOINTS = 5
ANALYST_SPLIT = 80  # APIs with more operations are analysed in parts of ANALYST_PART operations
ANALYST_PART = 50
SERIOUS = ('blocker', 'major')
SEVERITY_ORDER = {'blocker': 0, 'major': 1, 'minor': 2}
MAX_FINDINGS = 15


def _fatal(exc: Exception) -> bool:
    text = str(exc)
    return 'usage limit' in text or 'not signed in' in text


# --- Permission analysis ---------------------------------------------------------------------------------

def merge_models(parts: list[dict]) -> dict:
    """One permission model from several partial answers: roles by name, operation rows and rules combined."""
    roles: dict[str, dict] = {}
    for part in parts:
        for role in part.get('roles', []):
            key = role['name'].casefold()
            if key not in roles:
                roles[key] = dict(role)
            else:
                roles[key]['users'] = max(roles[key].get('users', 1), role.get('users', 1))
                roles[key]['description'] = roles[key].get('description') or role.get('description', '')

    def unique(values):
        return list(dict.fromkeys(values))
    return {'summary': max((p.get('summary', '') for p in parts), key=len, default=''), 'roles': list(roles.values()),
            'operations': [row for p in parts for row in p.get('operations', [])],
            'rules': list({r['rule'].casefold(): r for p in parts for r in p.get('rules', [])}.values()),
            'systemCallers': unique(c for p in parts for c in p.get('systemCallers', [])),
            'missingFromFile': unique(c for p in parts for c in p.get('missingFromFile', [])),
            'questions': unique(q for p in parts for q in p.get('questions', []))}


def analyze(job_input: dict, report, submit=None, agent=run_agent) -> dict:
    operations = job_input['operations']
    report(f"Reading {job_input['document']['filename']} and {len(operations)} operations", 10)
    base = {'rolesFile': job_input['document'], 'api': job_input['api']}
    with tempfile.TemporaryDirectory(prefix='studio-roles-') as workspace:
        def ask(ops: list[dict], part: dict | None = None) -> dict:
            task = {**base, 'operations': ops, **({'part': part} if part else {})}
            return agent('access-control-analyst', task, AccessModel, cwd=workspace, max_turns=4)

        if len(operations) <= ANALYST_SPLIT:
            model = ask(operations)
        else:
            parts = chunk_operations(operations, ANALYST_PART)
            with ThreadPoolExecutor(max_workers=min(len(parts), PARALLEL_ENDPOINTS), thread_name_prefix='access') as pool:
                answers = list(pool.map(lambda ip: ask(ip[1], {'number': ip[0] + 1, 'of': len(parts)}), enumerate(parts)))
            model = merge_models(answers)
        answered = {row['operationId'] for row in model.get('operations', [])}
        left_out = [op for op in operations if op['operationId'] not in answered]
        if left_out:  # long answers sometimes skip operations; ask again for exactly those
            report(f'Asking again for {len(left_out)} operations the first answer left out', 70)
            model = merge_models([model, ask(left_out, {'number': 2, 'of': 2, 'onlyMissing': True})])
    model = normalise(model, [op['operationId'] for op in operations])
    unknown = sum(len(row['unknown']) for row in model['operations'])
    report(f"{len(model['roles'])} roles, {unknown} permissions to confirm", 100)
    return {'model': model}


# --- Role cases for one endpoint -----------------------------------------------------------------------------

def _renumber(new: list[dict], existing: list[dict]) -> list[dict]:
    used = {c['key'] for c in existing}
    number = max((int(c['key'][1:]) for c in existing if c['key'][1:].isdigit()), default=0)
    out = []
    for case in new:
        if case['key'] in used:
            number += 1
            case = {**case, 'key': f'R{number:02d}'}
        used.add(case['key'])
        number = max(number, int(case['key'][1:]) if case['key'][1:].isdigit() else number)
        out.append(case)
    return out


class EndpointRoles:
    def __init__(self, item: dict, job_input: dict, agent, workspace):
        self.item, self.endpoint, self.agent, self.workspace = item, item['details'], agent, workspace
        self.model = job_input['model']
        self.operation_id = self.endpoint['operationId']
        self.roles = [r['name'] for r in self.model['roles']]
        self.required = role_requirements(self.model, self.operation_id)
        self.context = {
            'endpoint': compact_endpoint(self.endpoint),
            'access': access_row(self.model, self.operation_id),
            'rules': [r for r in self.model.get('rules', []) if self.operation_id in r.get('operations', [])],
            'roles': [{k: r.get(k) for k in ('name', 'description', 'users')} for r in self.model['roles']],
            'systemCallers': self.model.get('systemCallers', []),
            'operationIndex': job_input.get('operationIndex', []),
        }

    def call(self, agent, task, schema):
        return self.agent(agent, task, schema, cwd=self.workspace, max_turns=4)

    def templated(self) -> list[dict]:
        """Allowed and denied cases built in code from the endpoint's positive unit case: no Claude call needed."""
        base, row = self.item.get('baseCase'), self.context['access']
        if not base or not row:
            return []
        responses = self.endpoint.get('responses', {})
        expected = base.get('expected') or {}
        summary = (self.endpoint.get('summary') or self.operation_id).rstrip('.')
        source = f"Built from {'approved' if base.get('approved') else 'the'} unit case {base['code']} ({base['title']})."
        cases, allowed = [], row['allowed'] + row['own']
        common = {'priority': 'P1', 'testData': ' '.join(filter(None, [source, base.get('testData', '')]))[:1500],
                  'needsConfirmation': False, 'confirmationNote': ''}
        if allowed:
            cases.append({**common, 'key': 'R01', 'title': f'{", ".join(allowed)} can: {summary}'[:200],
                          'objective': f'Each role that may call this operation succeeds. {source}', 'kind': 'allowed',
                          'roles': allowed, 'userSlot': 'first',
                          'preconditions': [f'As each role in turn: {p}' for p in base.get('preconditions') or []]
                          or ['Each role uses data it owns or may access'],
                          'request': {**(base.get('request') or {}), 'auth': 'valid'}, 'expected': expected,
                          'verifyUnchanged': '', 'cleanup': base.get('cleanup') or []})
        status = '403' if '403' in responses else '404' if '404' in responses else ''
        if row['denied'] and status:
            setup = allowed[0] if allowed else 'a role that may create the data'
            reads = self.endpoint['method'] == 'GET'
            cases.append({**common, 'key': f'R{len(cases) + 1:02d}', 'title': f'{", ".join(row["denied"])} cannot: {summary}'[:200],
                          'objective': f'Every role that must not call this operation is refused. {source}', 'kind': 'denied',
                          'roles': row['denied'], 'userSlot': 'first',
                          'preconditions': [f'As {setup}: {p}' for p in base.get('preconditions') or []],
                          'request': {**(base.get('request') or {}), 'auth': 'valid'},
                          'expected': {'status': int(status), 'responseSchema': 'error' if (responses.get(status) or {}).get('schema') else 'none',
                                       'bodyChecks': [], 'headers': {}, 'notes': ''},
                          'verifyUnchanged': '' if reads else f'As {setup}: read the record back and check that nothing changed.',
                          'cleanup': [f'As {setup}: {c}' for c in base.get('cleanup') or []],
                          **({'needsConfirmation': True,
                              'confirmationNote': 'The spec documents 404 but not 403 here; confirm which status a refused role gets.'}
                             if status == '404' else {})})
        return self.keep_valid(cases)

    def problems(self, cases: list[dict]) -> tuple[list[str], list[dict]]:
        return validate_role_cases(cases, self.endpoint, self.roles), role_gaps(self.required, cases)

    def design(self, existing: list[dict]) -> list[dict]:
        missing = role_gaps(self.required, existing)
        if existing and not missing and not self.context['rules']:
            return existing  # everything is covered by the cases built in code
        task = {**self.context, 'mode': 'complete' if existing else 'design', 'requirements': self.required}
        if existing:
            task.update(existingCases=existing, missingRequirements=missing)
        designed = self.call('role-case-designer', task, RoleCaseSet)['cases']
        cases = existing + _renumber(designed, existing) if existing else designed
        problems, missing = self.problems(cases)
        claude.job_model.check('role-case-designer', len(designed), len({p.split(':', 1)[0] for p in problems}))
        if problems or missing:  # one fix round for structural problems and uncovered role checks
            fixed = self.call('role-case-designer', {**self.context, 'mode': 'fix', 'requirements': self.required,
                                                    'currentCases': cases, 'problems': problems,
                                                    'missingRequirements': missing}, RoleCaseSet)['cases']
            by_key = {c['key']: c for c in cases}
            by_key.update({c['key']: c for c in fixed})
            cases = list(by_key.values())
        return self.keep_valid(cases)

    def keep_valid(self, cases: list[dict]) -> list[dict]:
        """Drop cases that still break the code checks, so nothing wrong reaches the reviewer or the QA."""
        broken = {p.split(':', 1)[0] for p in validate_role_cases(cases, self.endpoint, self.roles)}
        return [c for c in cases if c['key'] not in broken]

    def review(self, cases: list[dict], mode='review') -> dict:
        requirements = [{**r, 'covered': covered(r, cases)} for r in self.required]
        verdict = self.call('role-case-reviewer', {**self.context, 'mode': mode, 'requirements': requirements, 'cases': cases},
                            CaseReview)
        verdict['findings'] = sorted(verdict.get('findings', []), key=lambda f: SEVERITY_ORDER.get(f['severity'], 3))[:MAX_FINDINGS]
        return verdict

    def improve(self, cases: list[dict], verdict: dict) -> tuple[list[dict], set[str]]:
        serious = [f for f in verdict.get('findings', []) if f['severity'] in SERIOUS]
        if not serious:
            return cases, set()
        revised = self.call('role-case-designer', {**self.context, 'mode': 'revise', 'requirements': self.required,
                                                  'currentCases': cases, 'reviewFindings': serious}, RoleCaseSet)['cases']
        by_key = {c['key']: c for c in cases}
        known = set(by_key)
        changed = {c['key'] for c in revised if c['key'] in known and c != by_key[c['key']]}
        added = _renumber([c for c in revised if c['key'] not in known], cases)
        by_key.update({c['key']: c for c in revised if c['key'] in known})
        by_key.update({c['key']: c for c in added})
        result = self.keep_valid(list(by_key.values()))
        return result, (changed | {c['key'] for c in added}) & {c['key'] for c in result}

    def run(self, step) -> dict:
        if not self.required:
            return {'endpointId': self.item['id'], 'cases': [],
                    'error': 'No permission is decided for this operation yet. Mark the roles in the permission grid, then generate again.'}
        step('building role cases', 0.1)
        templated = self.templated()
        if templated and not role_gaps(self.required, templated) and not self.context['rules']:
            # Routine endpoint: allowed and denied cases come from the approved unit case; nothing for Claude to add.
            return {'endpointId': self.item['id'], 'cases': templated,
                    'review': {'verdict': 'ready', 'findings': [],
                               'summary': 'Allowed and denied cases were built from the endpoint\'s positive unit case, '
                                          'so they follow the same valid request.'}}
        step('designing the remaining role cases' if templated else 'designing role cases', 0.2)
        cases = self.design(templated)
        if not cases:
            raise ClaudeError('No valid role cases could be designed for this operation.')
        step(f'reviewing {len(cases)} role cases', 0.55)
        verdict = self.review(cases)
        step('fixing what the reviewer found', 0.75)
        cases, changed = self.improve(cases, verdict)
        if changed:
            step('final review', 0.9)
            recheck = self.review([c for c in cases if c['key'] in changed], mode='recheck')
            kept = [f for f in verdict['findings'] if f['scenarioKey'] not in changed
                    and not (f['scenarioKey'] == 'checklist' and f['severity'] in SERIOUS)]
            findings = sorted(kept + recheck['findings'], key=lambda f: SEVERITY_ORDER.get(f['severity'], 3))
            verdict = {'verdict': 'needs_attention' if any(f['severity'] in SERIOUS for f in findings) else 'ready',
                       'summary': recheck.get('summary') or verdict.get('summary', ''), 'findings': findings[:MAX_FINDINGS * 2]}
        known = {c['key'] for c in cases}
        verdict['findings'] = [f for f in verdict['findings'] if f['scenarioKey'] in known or f['scenarioKey'] == 'checklist']
        return {'endpointId': self.item['id'], 'cases': cases, 'review': verdict}


def generate(job_input: dict, report, submit=None, agent=run_agent, parallel: int = PARALLEL_ENDPOINTS) -> dict:
    endpoints = job_input['endpoints']
    total = len(endpoints)
    lock = threading.Lock()
    active: dict[str, tuple[str, float]] = {}
    counts = {'done': 0, 'failed': 0}
    stop: list[Exception] = []

    def publish():
        with lock:
            finished = counts['done'] + counts['failed']
            progress = finished + sum(fraction for _, fraction in active.values())
            working = '; '.join(f'{label}: {message}' for label, (message, _) in list(active.items())[:parallel])
        report(f'{finished} of {total} endpoints done' + (f' · {working}' if working else ''), int(100 * progress / total))

    def run(item: dict):
        label = f"{item['details']['method']} {item['details']['path']}"
        with lock:
            if stop:
                return
            active[label] = ('starting', 0.0)

        def step(message, fraction):
            with lock:
                active[label] = (message, fraction)
            publish()

        try:
            with tempfile.TemporaryDirectory(prefix='studio-roles-') as workspace:
                result = EndpointRoles(item, job_input, agent, workspace).run(step)
            outcome = 'failed' if result.get('error') else 'done'
        except ClaudeError as exc:
            if _fatal(exc):
                with lock:
                    stop.append(exc)
                    active.pop(label, None)
                return
            result, outcome = {'endpointId': item['id'], 'error': str(exc)[:1500]}, 'failed'
        try:
            if submit:
                submit(result)
        except Exception as exc:  # the portal rejected the result or the job was cancelled
            with lock:
                stop.append(exc)
                active.pop(label, None)
            return
        with lock:
            counts[outcome] += 1
            active.pop(label, None)
        publish()

    report(f'Starting {total} endpoint{"s" if total != 1 else ""}, up to {min(parallel, total)} at a time', 1)
    with ThreadPoolExecutor(max_workers=max(1, min(parallel, total)), thread_name_prefix='roles') as pool:
        for future in [pool.submit(run, item) for item in endpoints]:
            future.result()
    done, failed = counts['done'], counts['failed']
    if stop:
        error = stop[0]
        if isinstance(error, ClaudeError):
            raise ClaudeError(f'{error} Finished {done} of {total} endpoints; generate the rest later.') from error
        raise error
    if not done:
        raise ClaudeError('Role test cases could not be generated for any selected endpoint. See the endpoint notes in the portal.')
    report('Finished', 100)
    return {'endpoints': done, 'failed': failed}

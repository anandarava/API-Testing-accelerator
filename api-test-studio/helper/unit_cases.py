"""Unit test case generation.

plan -> verify coverage -> fill gaps -> write cases -> review -> fix (add suggested scenarios,
revise flagged cases) -> final review.

Endpoints are processed in parallel (PARALLEL_ENDPOINTS at a time); each one is sent to the
portal as soon as it finishes.
"""
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

from contracts.checks import unit_case_problems
from contracts.coverage import gaps, obligations, unproven, with_proof
from contracts.unit import CaseReview, CaseSet, ScenarioChecklist

from . import claude
from .claude import ClaudeError, run_agent

PARALLEL_ENDPOINTS = 5
MAX_GAP_ROUNDS = 2
WRITER_BATCH = 20
MAX_FINDINGS = 15
SERIOUS = ('blocker', 'major')
SEVERITY_ORDER = {'blocker': 0, 'major': 1, 'minor': 2}


def _renumber(new: list[dict], existing: list[dict]) -> list[dict]:
    used = {s['key'] for s in existing}
    number = max((int(s['key'][1:]) for s in existing), default=0)
    result = []
    for scenario in new:
        if scenario['key'] in used or not scenario['key'][1:].isdigit():
            number += 1
            scenario = {**scenario, 'key': f'S{number:02d}'}
        number = max(number, int(scenario['key'][1:]))
        used.add(scenario['key'])
        result.append(scenario)
    return result


def _condition(scenario: dict) -> tuple:
    return scenario['category'], ' '.join(str(scenario.get('condition', '')).casefold().split()), scenario.get('expectedStatus')


def dedupe(scenarios: list[dict]) -> list[dict]:
    """Drop scenarios that test exactly the same condition as an earlier one."""
    seen, out = set(), []
    for scenario in scenarios:
        signature = _condition(scenario)
        if signature in seen:
            continue
        seen.add(signature)
        out.append(scenario)
    return out


def _existing(scenarios: list[dict]) -> list[dict]:
    claims = unproven(scenarios)
    return [{**{k: s[k] for k in ('key', 'title', 'covers')}, **({'unprovenCovers': claims[s['key']]} if s['key'] in claims else {})}
            for s in scenarios]


def plan(endpoint: dict, api: dict, agent, workspace, domain: dict | None = None) -> tuple[list[dict], int]:
    required = obligations(endpoint, api.get('securitySchemes'))
    context = {'endpoint': endpoint, 'api': api, 'requirements': with_proof(required), **({'domain': domain} if domain else {})}
    scenarios = dedupe(agent('unit-scenario-planner', {**context, 'mode': 'plan'}, ScenarioChecklist, cwd=workspace, max_turns=4)['scenarios'])
    claude.job_model.check('unit-scenario-planner', len(required), len(gaps(required, scenarios)))
    known = {item['id'] for item in required}
    rounds = 1
    for _ in range(MAX_GAP_ROUNDS):
        missing = gaps(required, scenarios)
        if not missing:
            break
        rounds += 1
        task = {**context, 'mode': 'fill-gaps', 'existingScenarios': _existing(scenarios), 'missingRequirements': with_proof(missing)}
        extra = agent('unit-scenario-planner', task, ScenarioChecklist, cwd=workspace, max_turns=4)['scenarios']
        scenarios = dedupe(scenarios + _renumber(extra, scenarios))
    for scenario in scenarios:
        scenario['covers'] = [oid for oid in scenario['covers'] if oid in known]
    return scenarios, rounds


def _flag(case: dict, problems: list[str]) -> dict:
    """A case that still fails the code check after a retry reaches the QA marked, never silently."""
    note = 'Code check: ' + ' '.join(problems)
    return {**case, 'needsConfirmation': True, 'confirmationNote': (note + ' ' + case.get('confirmationNote', '')).strip()[:500]}


def write(endpoint: dict, api: dict, scenarios: list[dict], agent, workspace, mode: str = 'write', current: dict | None = None,
          findings: dict | None = None) -> list[dict]:
    """Write (or revise) cases; each answer is checked in code and only the failing cases are asked again."""
    by_key, cases = {s['key']: s for s in scenarios}, {}
    keys = list(by_key)
    schemes = api.get('securitySchemes')
    for batch in [keys[i:i + WRITER_BATCH] for i in range(0, len(keys), WRITER_BATCH)]:
        problems: dict[str, list[str]] = {}
        drafts: dict[str, dict] = {}
        for _attempt in range(2):
            pending = [key for key in batch if key not in cases]
            if not pending:
                break
            task = {'mode': mode, 'endpoint': endpoint, 'api': api, 'scenarios': [by_key[k] for k in pending], 'onlyKeys': pending}
            if mode == 'revise':
                task.update(currentCases=[current[k] for k in pending if k in current],
                            reviewFindings=[f for k in pending for f in findings.get(k, [])])
            if problems:
                task['previousProblems'] = {k: v for k, v in problems.items() if k in pending}
            problems = {}
            answered = 0
            for case in agent('unit-case-writer', task, CaseSet, cwd=workspace, max_turns=4)['cases']:
                key = case['scenarioKey']
                if key not in by_key or key in cases or key not in pending:
                    continue
                answered += 1
                found = unit_case_problems(case, endpoint, schemes)
                if found:
                    problems[key], drafts[key] = found, case
                else:
                    cases[key] = case
            claude.job_model.check('unit-case-writer', answered, len(problems))
        for key, case in drafts.items():
            if key not in cases:
                cases[key] = _flag(case, problems.get(key, []))
    return [cases[key] for key in keys if key in cases]


def improve(endpoint: dict, api: dict, scenarios: list[dict], cases: list[dict], verdict: dict, agent, workspace,
            domain: dict | None = None):
    """Act on serious review findings: add suggested scenarios and revise flagged cases. Returns the changed keys."""
    serious = [f for f in verdict.get('findings', []) if f['severity'] in SERIOUS]
    by_case = {c['scenarioKey']: c for c in cases}
    suggestions = [f for f in serious if f['scenarioKey'] == 'checklist']
    flagged = {}
    for finding in serious:
        if finding['scenarioKey'] in by_case:
            flagged.setdefault(finding['scenarioKey'], []).append(finding)
    changed: set[str] = set()
    if not suggestions and not flagged:
        return scenarios, cases, changed
    required = obligations(endpoint, api.get('securitySchemes'))
    known = {item['id'] for item in required}
    if suggestions:
        task = {'mode': 'add-suggested', 'endpoint': endpoint, 'api': api, 'requirements': with_proof(required),
                'existingScenarios': _existing(scenarios), 'reviewSuggestions': suggestions, **({'domain': domain} if domain else {})}
        extra = agent('unit-scenario-planner', task, ScenarioChecklist, cwd=workspace, max_turns=4)['scenarios']
        extra = dedupe(scenarios + _renumber(extra, scenarios))[len(scenarios):]
        for scenario in extra:
            scenario['covers'] = [oid for oid in scenario['covers'] if oid in known]
        scenarios = scenarios + extra
        added = write(endpoint, api, extra, agent, workspace)
        by_case.update({c['scenarioKey']: c for c in added})
        changed |= {c['scenarioKey'] for c in added}
    if flagged:
        targets = [s for s in scenarios if s['key'] in flagged]
        revised = write(endpoint, api, targets, agent, workspace, mode='revise', current=by_case, findings=flagged)
        by_case.update({c['scenarioKey']: c for c in revised})
        changed |= {c['scenarioKey'] for c in revised}
    return scenarios, [by_case[s['key']] for s in scenarios if s['key'] in by_case], changed


def review(endpoint: dict, api: dict, scenarios: list[dict], cases: list[dict], agent, workspace, mode: str = 'review') -> dict:
    required = obligations(endpoint, api.get('securitySchemes'))
    covering = {item['id']: [s['key'] for s in scenarios if item['id'] in s['covers']] for item in required}
    still_missing = {item['id'] for item in gaps(required, scenarios)}
    coverage = [{**item, 'coveredBy': covering[item['id']], 'covered': item['id'] not in still_missing} for item in with_proof(required)]
    keys = {c['scenarioKey'] for c in cases}
    task = {'mode': mode, 'endpoint': endpoint, 'requirements': coverage,
            'scenarios': [s for s in scenarios if mode == 'review' or s['key'] in keys], 'cases': cases}
    verdict = agent('unit-case-reviewer', task, CaseReview, cwd=workspace, max_turns=4)
    verdict['findings'] = sorted(verdict.get('findings', []), key=lambda f: SEVERITY_ORDER.get(f['severity'], 3))[:MAX_FINDINGS]
    return verdict


def generate_endpoint(item: dict, api: dict, agent, workspace, step) -> dict:
    """The full pipeline for one endpoint. Raises ClaudeError on failure."""
    endpoint, domain = item['details'], item.get('domain')
    step('designing the scenario checklist', 0.05)
    scenarios, rounds = plan(endpoint, api, agent, workspace, domain)
    step(f'writing {len(scenarios)} test cases', 0.4)
    cases = write(endpoint, api, scenarios, agent, workspace)
    step('reviewing the test cases', 0.65)
    verdict = review(endpoint, api, scenarios, cases, agent, workspace)
    step('fixing what the reviewer found', 0.75)
    scenarios, cases, changed = improve(endpoint, api, scenarios, cases, verdict, agent, workspace, domain)
    if changed:
        step('final review', 0.9)
        # Re-check only the cases that changed; keep the first review's notes on the others.
        recheck = review(endpoint, api, scenarios, [c for c in cases if c['scenarioKey'] in changed], agent, workspace, mode='recheck')
        kept = [f for f in verdict.get('findings', []) if f['scenarioKey'] not in changed
                and not (f['scenarioKey'] == 'checklist' and f['severity'] in SERIOUS)]
        findings = sorted(kept + recheck.get('findings', []), key=lambda f: SEVERITY_ORDER.get(f['severity'], 3))
        verdict = {'verdict': 'needs_attention' if any(f['severity'] in SERIOUS for f in findings) else 'ready',
                   'summary': recheck.get('summary') or verdict.get('summary', ''), 'findings': findings[:MAX_FINDINGS * 2]}
    return {'endpointId': item['id'], 'checklist': scenarios, 'cases': cases, 'review': verdict, 'rounds': rounds}


def _fatal(exc: Exception) -> bool:
    """Errors that will hit every remaining endpoint too, so starting more work is pointless."""
    text = str(exc)
    return 'usage limit' in text or 'not signed in' in text


def generate(job_input: dict, report, submit=None, agent=run_agent, parallel: int = PARALLEL_ENDPOINTS) -> dict:
    endpoints, api = job_input['endpoints'], job_input['api']
    total = len(endpoints)
    lock = threading.Lock()
    active: dict[str, tuple[str, float]] = {}  # endpoint label -> (current step, fraction done)
    counts = {'done': 0, 'failed': 0}
    stop: list[Exception] = []  # the first fatal error; once set, queued endpoints are not started

    def publish():
        with lock:
            finished = counts['done'] + counts['failed']
            progress = finished + sum(fraction for _, fraction in active.values())
            working = '; '.join(f'{label}: {message}' for label, (message, _) in list(active.items())[:parallel])
        report(f'{finished} of {total} endpoints done' + (f' · {working}' if working else ''), int(100 * progress / total))

    def run(item: dict):
        endpoint = item['details']
        label = f"{endpoint['method']} {endpoint['path']}"
        with lock:
            if stop:
                return
            active[label] = ('starting', 0.0)

        def step(message, fraction):
            with lock:
                active[label] = (message, fraction)
            publish()

        try:
            with tempfile.TemporaryDirectory(prefix='studio-unit-') as workspace:
                result = generate_endpoint(item, api, agent, workspace, step)
            outcome = 'done'
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
        except Exception as exc:  # the portal rejected the result or the job was cancelled: stop everything
            with lock:
                stop.append(exc)
                active.pop(label, None)
            return
        with lock:
            counts[outcome] += 1
            active.pop(label, None)
        publish()

    report(f'Starting {total} endpoint{"s" if total != 1 else ""}, up to {min(parallel, total)} at a time', 1)
    with ThreadPoolExecutor(max_workers=max(1, min(parallel, total)), thread_name_prefix='unit') as pool:
        for future in [pool.submit(run, item) for item in endpoints]:
            future.result()

    done, failed = counts['done'], counts['failed']
    if stop:
        error = stop[0]
        if isinstance(error, ClaudeError):
            raise ClaudeError(f'{error} Finished {done} of {total} endpoints; generate the rest later.') from error
        raise error
    if not done:
        raise ClaudeError('Test cases could not be generated for any selected endpoint. See the endpoint errors in the portal.')
    report('Finished', 100)
    return {'endpoints': done, 'failed': failed}

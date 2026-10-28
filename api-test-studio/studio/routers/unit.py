"""Unit test case module: generation jobs, coverage, review and editing."""
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from contracts.coverage import gaps, obligations
from contracts.flows import domain_for
from contracts.roles import RoleCaseKind
from contracts.unit import Category, Expected, Priority, RequestSpec, UnitEndpointResult

from ..db import get_db
from ..openapi import digest
from ..deps import current_user, membership, record
from ..models import Counter, Endpoint, EndpointCoverage, FlowAnalysis, Job, Project, ScriptRecord, Spec, TestCase, User
from .helper import ACTIVE, helper_state, job_json
from .projects import current_spec

router = APIRouter(prefix='/api/projects/{project_id}/unit', tags=['Unit test cases'])
KIND = 'unit.generate'
MAX_ENDPOINTS_PER_JOB = 100
STATUSES = ('in_review', 'approved', 'needs_changes', 'rejected')


class GenerateInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    endpointIds: list[str] = Field(min_length=1, max_length=MAX_ENDPOINTS_PER_JOB)


class CaseEdit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int
    title: str = Field(min_length=3, max_length=200)
    objective: str = Field(default='', max_length=1000)
    category: Category | RoleCaseKind
    priority: Priority
    preconditions: list[str] = Field(default_factory=list, max_length=20)
    request: RequestSpec
    expected: Expected
    testData: str = Field(default='', max_length=1500)
    cleanup: list[str] = Field(default_factory=list, max_length=10)
    roles: list[str] | None = Field(default=None, max_length=30, description='Role cases only: the roles the case runs as')
    verifyUnchanged: str | None = Field(default=None, max_length=500)


class ReviewAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    caseIds: list[str] = Field(min_length=1, max_length=500)
    action: Literal['approve', 'reject', 'needs_changes', 'reopen']
    comment: str = Field(default='', max_length=2000)


def regenerating_ids(db: DbSession, project_id: str) -> list[str]:
    jobs = db.scalars(select(Job).where(Job.project_id == project_id, Job.kind == 'case.regenerate', Job.status.in_(ACTIVE)))
    return [job.input['caseId'] for job in jobs]


def next_number(db: DbSession, project_id: str) -> int:
    counter = db.get(Counter, (project_id, 'case'))
    if not counter:
        start = db.scalar(select(func.max(TestCase.number)).where(TestCase.project_id == project_id)) or 0
        counter = Counter(project_id=project_id, name='case', value=start)
        db.add(counter)
    counter.value += 1
    return counter.value


def code(case: TestCase) -> str:
    return f'TC-{case.number:04d}'


def names(db: DbSession, *ids) -> dict:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    return dict(db.execute(select(User.id, User.name).where(User.id.in_(wanted))).all())


def case_fingerprint(case: TestCase) -> str:
    """Changes only when what a script must implement changes (not on approval or comments)."""
    return digest({'title': case.title, 'category': case.category, 'priority': case.priority, 'content': case.content})


def script_state(case: TestCase, scripted: dict | None) -> str | None:
    if not scripted or case.id not in scripted:
        return None
    return 'current' if scripted[case.id] == case_fingerprint(case) else 'outdated'


def case_json(case: TestCase, people: dict, current_version: int | None = None, scripted: dict | None = None) -> dict:
    return {'id': case.id, 'code': code(case), 'module': case.module, 'method': case.method, 'path': case.path,
            'operationId': case.operation_id, 'scenarioKey': case.scenario_key, 'title': case.title,
            'category': case.category, 'priority': case.priority, 'status': case.status,
            'needsConfirmation': case.needs_confirmation, 'content': case.content, 'findings': case.findings,
            'reviewComment': case.review_comment, 'revision': case.revision,
            'createdBy': people.get(case.created_by), 'createdAt': case.created_at,
            'updatedBy': people.get(case.updated_by), 'updatedAt': case.updated_at,
            'reviewedBy': people.get(case.reviewed_by), 'reviewedAt': case.reviewed_at,
            'specVersion': case.spec_version,
            'outdated': current_version is not None and case.spec_version != current_version,
            'script': script_state(case, scripted)}


def endpoint_cases(db: DbSession, project_id: str, method: str, path: str) -> list[TestCase]:
    return db.scalars(select(TestCase).where(TestCase.project_id == project_id, TestCase.module == 'unit',
                                             TestCase.method == method, TestCase.path == path)
                      .order_by(TestCase.number)).all()


def project_endpoint(db: DbSession, project_id: str, endpoint_id: str) -> tuple[Endpoint, Spec]:
    spec = current_spec(db, project_id)
    endpoint = db.get(Endpoint, endpoint_id)
    if not spec or not endpoint or endpoint.spec_id != spec.id:
        raise HTTPException(404, 'Endpoint not found in the current API spec.')
    return endpoint, spec


def coverage_summary(record_: EndpointCoverage | None, endpoint: Endpoint) -> dict | None:
    if not record_:
        return None
    total = len(record_.requirements)
    return {'total': total, 'covered': total - len(record_.gaps), 'gaps': len(record_.gaps),
            'outdated': record_.fingerprint != endpoint.fingerprint, 'error': record_.error,
            'generatedAt': record_.generated_at, 'verdict': (record_.review or {}).get('verdict')}


# --- Generation ------------------------------------------------------------------------

@router.post('/generate')
def generate(project_id: str, body: GenerateInput, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, _ = membership(db, project_id, user)
    spec = current_spec(db, project_id)
    if not spec:
        raise HTTPException(400, 'Upload an API spec first.')
    if not helper_state(db, user.id)['connected']:
        raise HTTPException(409, 'Your Local Helper is not connected. Start it on your computer and try again.')
    running = db.scalar(select(Job).where(Job.project_id == project_id, Job.kind == KIND, Job.status.in_(ACTIVE)))
    if running:
        who = db.get(User, running.requested_by).name
        raise HTTPException(409, f'Unit test cases are already being generated by {who}. Wait for it to finish.')
    ids = list(dict.fromkeys(body.endpointIds))
    rows = {e.id: e for e in db.scalars(select(Endpoint).where(Endpoint.spec_id == spec.id, Endpoint.id.in_(ids)))}
    if len(rows) != len(ids):
        raise HTTPException(400, 'Some selected endpoints are not in the current API spec. Reload and try again.')
    job = Job(project_id=project_id, kind=KIND, requested_by=user.id,
              input={'specVersion': spec.version,
                     'api': {'title': spec.title, 'version': spec.api_version, 'servers': spec.servers,
                             'securitySchemes': spec.security_schemes},
                     'endpoints': [{'id': i, 'details': rows[i].details, **endpoint_domain(db, project_id, spec, rows[i])} for i in ids]},
              progress={'message': 'Waiting for your Local Helper', 'percent': 0})
    db.add(job)
    record(db, project, user, 'unit.generation_started',
           f'{user.name} started unit test case generation for {len(ids)} endpoint{"s" if len(ids) != 1 else ""}')
    db.commit()
    return job_json(job, user.name)


def endpoint_domain(db: DbSession, project_id: str, spec: Spec, endpoint: Endpoint) -> dict:
    """Business rules, locked states and side effects from the whole-API analysis that concern this endpoint."""
    analysis = db.get(FlowAnalysis, project_id)
    if not analysis or not analysis.domain or analysis.spec_sha256 != spec.sha256:
        return {}
    domain = domain_for(analysis.domain, {endpoint.operation_id})
    effects = [e for e in analysis.domain.get('sideEffects', []) if e.get('operationId') == endpoint.operation_id]
    if not (domain['businessRules'] or domain['transitions'] or effects):
        return {}
    return {'domain': {'businessRules': domain['businessRules'], 'transitions': domain['transitions'], 'sideEffects': effects,
                       'entities': [e for e in domain['entities'] if e.get('states')]}}


def store_endpoint_result(db: DbSession, job: Job, user: User, result: dict):
    """Called for each endpoint the helper finishes. The server re-checks coverage itself."""
    parsed = UnitEndpointResult.model_validate(result)
    if parsed.endpointId not in {item['id'] for item in job.input['endpoints']}:
        raise HTTPException(400, 'This endpoint was not part of the job.')
    endpoint = db.get(Endpoint, parsed.endpointId)
    spec = db.get(Spec, endpoint.spec_id)
    project = db.get(Project, job.project_id)
    required = obligations(endpoint.details, spec.security_schemes)
    known = {item['id'] for item in required}
    checklist = [s.model_dump() for s in parsed.checklist]
    for scenario in checklist:
        scenario['covers'] = [oid for oid in scenario['covers'] if oid in known]
    coverage = db.get(EndpointCoverage, (job.project_id, endpoint.method, endpoint.path)) or \
        EndpointCoverage(project_id=job.project_id, method=endpoint.method, path=endpoint.path)
    coverage.spec_version, coverage.fingerprint, coverage.job_id = spec.version, endpoint.fingerprint, job.id
    coverage.generated_by, coverage.generated_at = user.id, time.time()
    label = f'{endpoint.method} {endpoint.path}'
    if parsed.error:
        coverage.error = parsed.error
        if not coverage.requirements:
            coverage.requirements, coverage.gaps = required, [item['id'] for item in required]
        db.merge(coverage)
        record(db, project, user, 'unit.endpoint_failed', f'Unit case generation failed for {label}', error=parsed.error[:300])
        return

    by_key = {s['key']: s for s in checklist}
    cases = [c.model_dump() for c in parsed.cases if c.scenarioKey in by_key]
    review = parsed.review.model_dump() if parsed.review else None
    findings = {}
    for finding in (review or {}).get('findings', []):
        findings.setdefault(finding['scenarioKey'], []).append(finding)

    existing = endpoint_cases(db, job.project_id, endpoint.method, endpoint.path)
    approved_titles = {c.title.casefold() for c in existing if c.status == 'approved'}
    for case in existing:
        if case.status != 'approved':
            db.delete(case)
    db.flush()
    added = 0
    for draft in cases:
        if draft['title'].casefold() in approved_titles:
            continue
        scenario = by_key[draft['scenarioKey']]
        number = next_number(db, job.project_id)
        added += 1
        content = {key: draft[key] for key in ('objective', 'preconditions', 'request', 'expected', 'testData', 'cleanup')}
        content.update(condition=scenario['condition'], covers=scenario['covers'], source=scenario['source'],
                       confirmationNote=draft['confirmationNote'] or scenario['confirmationNote'])
        db.add(TestCase(project_id=job.project_id, module='unit', number=number, method=endpoint.method,
                        path=endpoint.path, operation_id=endpoint.operation_id, spec_version=spec.version,
                        scenario_key=draft['scenarioKey'], title=draft['title'], category=draft['category'],
                        priority=draft['priority'], needs_confirmation=draft['needsConfirmation'] or scenario['needsConfirmation'],
                        content=content, findings=findings.get(draft['scenarioKey'], []), source_job_id=job.id,
                        created_by=user.id, updated_by=user.id))
    missing = [item['id'] for item in gaps(required, checklist)]
    coverage.requirements, coverage.checklist, coverage.gaps = required, checklist, missing
    coverage.review, coverage.rounds, coverage.error = review, parsed.rounds, ''
    db.merge(coverage)
    covered = len(required) - len(missing)
    record(db, project, user, 'unit.endpoint_generated',
           f'Claude designed {added} unit test case{"s" if added != 1 else ""} for {label} '
           f'(requirements covered {covered}/{len(required)})')


def complete_generation(db: DbSession, job: Job, user: User, result: dict):
    job.result = {'endpoints': int(result.get('endpoints', 0)), 'failed': int(result.get('failed', 0))}
    record(db, db.get(Project, job.project_id), user, 'unit.generation_finished',
           f'Unit test case generation finished on {user.name}\'s computer — the cases are ready for review')


# --- Reading ---------------------------------------------------------------------------------

@router.get('/endpoints')
def endpoints(project_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    spec = current_spec(db, project_id)
    job = db.scalar(select(Job).where(Job.project_id == project_id, Job.kind == KIND).order_by(Job.created_at.desc()).limit(1))
    latest_job = job_json(job, db.get(User, job.requested_by).name) if job else None
    if not spec:
        return {'endpoints': [], 'job': latest_job, 'totals': {s: 0 for s in STATUSES}}
    rows = db.scalars(select(Endpoint).where(Endpoint.spec_id == spec.id).order_by(Endpoint.position)).all()
    counts = {}
    for method, path, status, total in db.execute(
            select(TestCase.method, TestCase.path, TestCase.status, func.count()).where(
                TestCase.project_id == project_id, TestCase.module == 'unit').group_by(TestCase.method, TestCase.path, TestCase.status)):
        counts.setdefault((method, path), {})[status] = total
    coverage = {(c.method, c.path): c for c in db.scalars(select(EndpointCoverage).where(EndpointCoverage.project_id == project_id))}
    totals = {s: 0 for s in STATUSES}
    items = []
    for endpoint in rows:
        by_status = counts.get((endpoint.method, endpoint.path), {})
        for status, total in by_status.items():
            totals[status] = totals.get(status, 0) + total
        items.append({'id': endpoint.id, 'method': endpoint.method, 'path': endpoint.path, 'summary': endpoint.summary,
                      'tags': endpoint.tags, 'cases': {s: by_status.get(s, 0) for s in STATUSES},
                      'caseCount': sum(by_status.values()),
                      'coverage': coverage_summary(coverage.get((endpoint.method, endpoint.path)), endpoint)})
    return {'endpoints': items, 'job': latest_job, 'totals': totals}


@router.get('/endpoints/{endpoint_id}')
def endpoint_detail(project_id: str, endpoint_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    endpoint, spec = project_endpoint(db, project_id, endpoint_id)
    record_ = db.get(EndpointCoverage, (project_id, endpoint.method, endpoint.path))
    script = db.get(ScriptRecord, (project_id, endpoint.method, endpoint.path))
    scripted = script.case_fingerprints if script else None
    cases = endpoint_cases(db, project_id, endpoint.method, endpoint.path)
    people = names(db, *[c.created_by for c in cases], *[c.updated_by for c in cases], *[c.reviewed_by for c in cases],
                   record_.generated_by if record_ else None)
    requirements = []
    if record_:
        missing = set(record_.gaps)
        for item in record_.requirements:
            requirements.append({**item, 'covered': item['id'] not in missing,
                                 'scenarios': [s['key'] for s in record_.checklist if item['id'] in s.get('covers', [])]})
    return {'endpoint': {'id': endpoint.id, 'method': endpoint.method, 'path': endpoint.path, 'summary': endpoint.summary,
                         'operationId': endpoint.operation_id},
            'coverage': coverage_summary(record_, endpoint),
            'requirements': requirements, 'review': record_.review if record_ else None,
            'generatedBy': people.get(record_.generated_by) if record_ else None,
            'cases': [case_json(c, people, spec.version, scripted) for c in cases],
            'regenerating': regenerating_ids(db, project_id)}


def project_case(db: DbSession, project_id: str, case_id: str) -> TestCase:
    case = db.get(TestCase, case_id)
    if not case or case.project_id != project_id:
        raise HTTPException(404, 'Test case not found.')
    return case


@router.get('/cases/{case_id}')
def get_case(project_id: str, case_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    case = project_case(db, project_id, case_id)
    spec = current_spec(db, project_id)
    return case_json(case, names(db, case.created_by, case.updated_by, case.reviewed_by), spec.version if spec else None)


# --- Editing and review ----------------------------------------------------------------------

@router.patch('/cases/{case_id}')
def edit_case(project_id: str, case_id: str, body: CaseEdit, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, _ = membership(db, project_id, user)
    case = project_case(db, project_id, case_id)
    if case.revision != body.revision:
        raise HTTPException(409, 'Someone else changed this test case. Reload to see the latest version.')
    role_case = case.module == 'role'
    if role_case != (body.category in RoleCaseKind.__args__):
        raise HTTPException(400, 'Choose a category of this kind of test case.')
    case.title, case.category, case.priority = body.title.strip(), body.category, body.priority
    content = dict(case.content)
    content.update(objective=body.objective, preconditions=body.preconditions, request=body.request.model_dump(),
                   expected=body.expected.model_dump(), testData=body.testData, cleanup=body.cleanup)
    if role_case and body.roles is not None:
        if not body.roles:
            raise HTTPException(400, 'A role test case needs at least one role.')
        content['roles'] = list(dict.fromkeys(body.roles))
    if role_case and body.verifyUnchanged is not None:
        content['verifyUnchanged'] = body.verifyUnchanged
    case.content = content
    previous = case.status
    case.status, case.revision = 'in_review', case.revision + 1
    case.updated_by, case.updated_at = user.id, time.time()
    note = ' and moved it back to review' if previous == 'approved' else ''
    record(db, project, user, 'unit.case_edited', f'{user.name} edited {code(case)} {case.title}{note}', caseId=case.id)
    db.commit()
    spec = current_spec(db, project_id)
    return case_json(case, names(db, case.created_by, case.updated_by, case.reviewed_by), spec.version if spec else None)


VERBS = {'approve': ('approved', 'approved'), 'reject': ('rejected', 'rejected'),
         'needs_changes': ('needs_changes', 'requested changes on'), 'reopen': ('in_review', 'reopened')}


@router.post('/cases/review')
def review_cases(project_id: str, body: ReviewAction, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, _ = membership(db, project_id, user)
    if body.action == 'needs_changes' and not body.comment.strip():
        raise HTTPException(400, 'Add a comment that explains what needs to change.')
    ids = list(dict.fromkeys(body.caseIds))
    cases = db.scalars(select(TestCase).where(TestCase.project_id == project_id, TestCase.id.in_(ids))).all()
    if len(cases) != len(ids):
        raise HTTPException(404, 'Some test cases no longer exist. Reload and try again.')
    status, verb = VERBS[body.action]
    now = time.time()
    for case in cases:
        case.status, case.revision = status, case.revision + 1
        case.reviewed_by, case.reviewed_at = (user.id, now) if body.action != 'reopen' else (None, None)
        case.review_comment = body.comment.strip() if body.action in ('needs_changes', 'reject') else ''
        if body.action == 'approve':
            case.needs_confirmation = False
    subject = f'{code(cases[0])} {cases[0].title}' if len(cases) == 1 else f'{len(cases)} unit test cases'
    record(db, project, user, f'unit.cases_{status}', f'{user.name} {verb} {subject}', caseIds=ids[:50])
    db.commit()
    return {'updated': len(cases), 'status': status}


@router.delete('/cases/{case_id}')
def delete_case(project_id: str, case_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, _ = membership(db, project_id, user)
    case = project_case(db, project_id, case_id)
    record(db, project, user, 'unit.case_deleted', f'{user.name} deleted {code(case)} {case.title}')
    module = case.module
    db.delete(case)
    if module == 'flow':
        from .flows import refresh_coverage
        refresh_coverage(db, project_id)  # what the deleted flow covered may now be a gap
    db.commit()
    return {'ok': True}


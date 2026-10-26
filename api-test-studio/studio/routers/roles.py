"""Role-based test cases: the roles file, the permission grid built from it, and role cases per endpoint.

Without a roles file nothing here runs: role cases are only generated from the roles the team documents.
"""
import hashlib
import json
import time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from contracts.flows import operation_index
from contracts.roles import (ACCESS_LISTS, AccessAnalysisResult, RoleEndpointResult, access_row, contributes, env_prefix,
                             normalise, role_gaps, role_requirements)

from ..db import get_db
from ..deps import current_user, membership, record
from ..documents import DocumentError, extract_text
from ..models import AccessAnalysis, AccessDocument, Endpoint, Job, Project, RoleCoverage, ScriptRecord, Spec, TestCase, User
from .helper import ACTIVE, helper_state, job_json
from .projects import current_spec
from .unit import STATUSES, case_json, code, names, next_number, project_endpoint, regenerating_ids

router = APIRouter(prefix='/api/projects/{project_id}/roles', tags=['Role test cases'])
ANALYZE = 'access.analyze'
GENERATE = 'roles.generate'
MAX_ENDPOINTS_PER_JOB = 100
ROLE_SCRIPT = 'ROLE'


class GenerateInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    endpointIds: list[str] = Field(min_length=1, max_length=MAX_ENDPOINTS_PER_JOB)


class AccessEdit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    allowed: list[str] = Field(default_factory=list)
    own: list[str] = Field(default_factory=list)
    denied: list[str] = Field(default_factory=list)
    unknown: list[str] = Field(default_factory=list)


def _sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def row_fingerprint(model: dict, operation_id: str) -> str:
    """What the role cases of one endpoint depend on: its permission row and the access rules that mention it."""
    row = access_row(model, operation_id) or {}
    rules = [r for r in model.get('rules', []) if operation_id in r.get('operations', [])]
    return _sha({'row': {k: row.get(k, []) for k in ACCESS_LISTS}, 'rules': rules,
                 'roles': [r['name'] for r in model.get('roles', [])]})


def _latest(db: DbSession, project_id: str, kind: str) -> Job | None:
    return db.scalar(select(Job).where(Job.project_id == project_id, Job.kind == kind).order_by(Job.created_at.desc()).limit(1))


def _job(db: DbSession, job: Job | None) -> dict | None:
    return job_json(job, db.get(User, job.requested_by).name) if job else None


def role_cases(db: DbSession, project_id: str, method: str | None = None, path: str | None = None) -> list[TestCase]:
    query = select(TestCase).where(TestCase.project_id == project_id, TestCase.module == 'role')
    if method:
        query = query.where(TestCase.method == method, TestCase.path == path)
    return db.scalars(query.order_by(TestCase.number)).all()


def case_dict(case: TestCase) -> dict:
    """The fields coverage is computed from."""
    return {'key': case.scenario_key, 'kind': case.category, 'roles': case.content.get('roles', []),
            'userSlot': case.content.get('userSlot', 'first'), 'expected': case.content.get('expected', {})}


def analysis_state(db: DbSession, project_id: str, spec: Spec | None) -> dict:
    document = db.get(AccessDocument, project_id)
    analysis = db.get(AccessAnalysis, project_id)
    return {'document': document, 'analysis': analysis,
            'ready': bool(document and analysis and analysis.document_sha == document.sha256 and analysis.model),
            'outdated': bool(analysis and ((document and analysis.document_sha != document.sha256)
                                           or (spec and analysis.spec_sha != spec.sha256)))}


# --- Roles file -----------------------------------------------------------------------------------------

@router.post('/document')
async def upload_document(project_id: str, file: UploadFile = File(...), db: DbSession = Depends(get_db),
                          user: User = Depends(current_user)):
    project, _ = membership(db, project_id, user)
    data = await file.read()
    try:
        text = extract_text(file.filename or 'roles.txt', data)
    except DocumentError as exc:
        raise HTTPException(400, str(exc)) from exc
    sha = hashlib.sha256(text.encode()).hexdigest()
    document = db.get(AccessDocument, project_id) or AccessDocument(project_id=project_id)
    changed = document.sha256 != sha
    document.filename, document.size, document.text, document.sha256 = (file.filename or 'roles')[:300], len(data), text, sha
    document.uploaded_by, document.uploaded_at = user.id, time.time()
    db.merge(document)
    record(db, project, user, 'roles.document_uploaded', f'{user.name} uploaded the roles file {document.filename}'
           + ('' if changed else ' (unchanged)'))
    db.commit()
    return {'filename': document.filename, 'changed': changed}


@router.delete('/document')
def delete_document(project_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, _ = membership(db, project_id, user)
    document = db.get(AccessDocument, project_id)
    if document:
        db.delete(document)
        record(db, project, user, 'roles.document_removed', f'{user.name} removed the roles file; role test cases will not be generated')
        db.commit()
    return {'ok': True}


# --- Permission analysis ------------------------------------------------------------------------------

def _access_view(endpoint: Endpoint) -> dict:
    """What the analyst needs from one operation: who it is for, in the contract's own words."""
    details = endpoint.details
    return {'operationId': details['operationId'], 'method': details['method'], 'path': details['path'],
            'summary': (details.get('summary') or '')[:200], 'description': (details.get('description') or '')[:400],
            'tags': details.get('tags', []), 'security': details.get('security', []),
            'statuses': sorted(details.get('responses', {}))}


@router.post('/analyze')
def analyze(project_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, _ = membership(db, project_id, user)
    spec = current_spec(db, project_id)
    document = db.get(AccessDocument, project_id)
    if not spec:
        raise HTTPException(400, 'Upload an API spec first.')
    if not document:
        raise HTTPException(400, 'Upload the roles file first. Role test cases are only generated from your roles file.')
    if not helper_state(db, user.id)['connected']:
        raise HTTPException(409, 'Your Local Helper is not connected. Start it on your computer and try again.')
    if db.scalar(select(Job).where(Job.project_id == project_id, Job.kind.in_((ANALYZE, GENERATE)), Job.status.in_(ACTIVE))):
        raise HTTPException(409, 'Roles are already being analyzed or role cases generated. Wait for it to finish.')
    endpoints = db.scalars(select(Endpoint).where(Endpoint.spec_id == spec.id).order_by(Endpoint.position)).all()
    job = Job(project_id=project_id, kind=ANALYZE, requested_by=user.id,
              input={'specSha256': spec.sha256, 'documentSha256': document.sha256,
                     'document': {'filename': document.filename, 'text': document.text},
                     'api': {'title': spec.title, 'description': spec.description[:2000], 'securitySchemes': spec.security_schemes},
                     'operations': [_access_view(e) for e in endpoints]},
              progress={'message': 'Waiting for your Local Helper', 'percent': 0})
    db.add(job)
    record(db, project, user, 'roles.analysis_started', f'{user.name} asked Claude to analyze the roles file against the API')
    db.commit()
    return job_json(job, user.name)


def complete_analysis(db: DbSession, job: Job, user: User, result: dict):
    parsed = AccessAnalysisResult.model_validate(result)
    operation_ids = [item['operationId'] for item in job.input['operations']]
    model = normalise(parsed.model.model_dump(), operation_ids)
    analysis = db.get(AccessAnalysis, job.project_id) or AccessAnalysis(project_id=job.project_id)
    analysis.document_sha, analysis.spec_sha, analysis.model = job.input['documentSha256'], job.input['specSha256'], model
    analysis.edited_by, analysis.edited_at, analysis.job_id = None, None, job.id
    analysis.generated_by, analysis.generated_at = user.id, time.time()
    db.merge(analysis)
    job.result = {'roles': len(model['roles']), 'operations': len(model['operations'])}
    unknown = sum(len(row['unknown']) for row in model['operations'])
    record(db, db.get(Project, job.project_id), user, 'roles.analyzed',
           f'Claude analyzed {len(model["roles"])} roles across {len(model["operations"])} operations'
           + (f' ({unknown} permissions still unknown)' if unknown else ''))


@router.put('/access/{operation_id}')
def edit_access(project_id: str, operation_id: str, body: AccessEdit, db: DbSession = Depends(get_db),
                user: User = Depends(current_user)):
    """Correct one row of the permission grid; every role must be in exactly one list."""
    project, _ = membership(db, project_id, user)
    analysis = db.get(AccessAnalysis, project_id)
    if not analysis or not analysis.model:
        raise HTTPException(400, 'Analyze the roles file first.')
    names_ = [r['name'] for r in analysis.model['roles']]
    given = [n for access in ACCESS_LISTS for n in getattr(body, access)]
    if sorted(given) != sorted(names_):
        raise HTTPException(400, f'Put every role in exactly one list: {", ".join(names_)}.')
    model = json.loads(json.dumps(analysis.model))
    row = access_row(model, operation_id)
    if not row:
        raise HTTPException(404, 'Operation not found in the permission grid.')
    for access in ACCESS_LISTS:
        row[access] = [n for n in names_ if n in getattr(body, access)]
    row['source'], row['editedBy'] = 'edited', user.name
    analysis.model, analysis.edited_by, analysis.edited_at = model, user.id, time.time()
    record(db, project, user, 'roles.access_edited', f'{user.name} corrected the permissions of {operation_id}')
    db.commit()
    return {'row': row}


# --- Role case generation ---------------------------------------------------------------------------

@router.post('/generate')
def generate(project_id: str, body: GenerateInput, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, _ = membership(db, project_id, user)
    spec = current_spec(db, project_id)
    if not spec:
        raise HTTPException(400, 'Upload an API spec first.')
    state = analysis_state(db, project_id, spec)
    if not state['document']:
        raise HTTPException(400, 'Upload the roles file first. Without it, role test cases are not generated.')
    if not state['ready']:
        raise HTTPException(400, 'Analyze the roles file first, so the cases follow its permissions.')
    if not helper_state(db, user.id)['connected']:
        raise HTTPException(409, 'Your Local Helper is not connected. Start it on your computer and try again.')
    if db.scalar(select(Job).where(Job.project_id == project_id, Job.kind.in_((ANALYZE, GENERATE)), Job.status.in_(ACTIVE))):
        raise HTTPException(409, 'Roles are already being analyzed or role cases generated. Wait for it to finish.')
    ids = list(dict.fromkeys(body.endpointIds))
    rows = {e.id: e for e in db.scalars(select(Endpoint).where(Endpoint.spec_id == spec.id, Endpoint.id.in_(ids)))}
    if len(rows) != len(ids):
        raise HTTPException(400, 'Some selected endpoints are not in the current API spec. Reload and try again.')
    model = state['analysis'].model
    every = db.scalars(select(Endpoint).where(Endpoint.spec_id == spec.id).order_by(Endpoint.position)).all()
    job = Job(project_id=project_id, kind=GENERATE, requested_by=user.id,
              input={'specVersion': spec.version, 'model': model,
                     'api': {'title': spec.title, 'securitySchemes': spec.security_schemes},
                     'operationIndex': [operation_index(e.details) for e in every],
                     'endpoints': [{'id': i, 'details': rows[i].details, 'access': row_fingerprint(model, rows[i].operation_id),
                                    **base_case(db, project_id, rows[i])} for i in ids]},
              progress={'message': 'Waiting for your Local Helper', 'percent': 0})
    db.add(job)
    record(db, project, user, 'roles.generation_started',
           f'{user.name} started role test case generation for {len(ids)} endpoint{"s" if len(ids) != 1 else ""}')
    db.commit()
    return job_json(job, user.name)


def base_case(db: DbSession, project_id: str, endpoint: Endpoint) -> dict:
    """The endpoint's positive unit case (approved first), the valid request routine role cases are built from."""
    rows = db.scalars(select(TestCase).where(TestCase.project_id == project_id, TestCase.module == 'unit',
                                             TestCase.method == endpoint.method, TestCase.path == endpoint.path,
                                             TestCase.category == 'positive', TestCase.status.in_(('approved', 'in_review')))
                      .order_by(TestCase.number)).all()
    ok = [c for c in rows if 200 <= int((c.content.get('expected') or {}).get('status') or 0) < 300]
    best = next((c for c in ok if c.status == 'approved'), ok[0] if ok else None)
    if not best:
        return {}
    keys = ('objective', 'preconditions', 'request', 'expected', 'testData', 'cleanup')
    return {'baseCase': {'code': code(best), 'title': best.title, 'approved': best.status == 'approved',
                         **{k: best.content.get(k) for k in keys}}}


def store_endpoint_result(db: DbSession, job: Job, user: User, result: dict):
    """One endpoint's role cases. Coverage is recomputed here from the cases, never taken from the helper."""
    parsed = RoleEndpointResult.model_validate(result)
    item = next((i for i in job.input['endpoints'] if i['id'] == parsed.endpointId), None)
    if not item:
        raise HTTPException(400, 'This endpoint was not part of the job.')
    endpoint = db.get(Endpoint, parsed.endpointId)
    spec = db.get(Spec, endpoint.spec_id)
    project = db.get(Project, job.project_id)
    model = job.input['model']
    required = role_requirements(model, endpoint.operation_id)
    coverage = db.get(RoleCoverage, (job.project_id, endpoint.method, endpoint.path)) or \
        RoleCoverage(project_id=job.project_id, method=endpoint.method, path=endpoint.path)
    coverage.access, coverage.job_id, coverage.generated_by, coverage.generated_at = item['access'], job.id, user.id, time.time()
    label = f'{endpoint.method} {endpoint.path}'
    if parsed.error:
        coverage.error = parsed.error
        coverage.requirements, coverage.gaps = required, [r['id'] for r in required]
        db.merge(coverage)
        record(db, project, user, 'roles.endpoint_failed', f'Role case generation did not finish for {label}', error=parsed.error[:300])
        return
    roles = {r['name'] for r in model['roles']}
    review = parsed.review.model_dump() if parsed.review else None
    findings = {}
    for finding in (review or {}).get('findings', []):
        findings.setdefault(finding['scenarioKey'], []).append(finding)
    existing = role_cases(db, job.project_id, endpoint.method, endpoint.path)
    approved_titles = {c.title.casefold() for c in existing if c.status == 'approved'}
    for case in existing:
        if case.status != 'approved':
            db.delete(case)
    db.flush()
    added = 0
    for draft in (c.model_dump() for c in parsed.cases):
        draft['roles'] = [r for r in draft['roles'] if r in roles]
        if not draft['roles'] or draft['title'].casefold() in approved_titles:
            continue
        added += 1
        content = {key: draft[key] for key in ('objective', 'preconditions', 'request', 'expected', 'verifyUnchanged',
                                               'testData', 'cleanup', 'roles', 'userSlot', 'confirmationNote')}
        db.add(TestCase(project_id=job.project_id, module='role', number=next_number(db, job.project_id), method=endpoint.method,
                        path=endpoint.path, operation_id=endpoint.operation_id, spec_version=spec.version,
                        scenario_key=draft['key'], title=draft['title'], category=draft['kind'], priority=draft['priority'],
                        needs_confirmation=draft['needsConfirmation'], content=content, findings=findings.get(draft['key'], []),
                        source_job_id=job.id, created_by=user.id, updated_by=user.id))
    db.flush()
    cases = [case_dict(c) for c in role_cases(db, job.project_id, endpoint.method, endpoint.path)]
    coverage.requirements, coverage.gaps = required, [r['id'] for r in role_gaps(required, cases)]
    coverage.review, coverage.error = review, ''
    db.merge(coverage)
    covered = len(required) - len(coverage.gaps)
    record(db, project, user, 'roles.endpoint_generated',
           f'Claude designed {added} role test case{"s" if added != 1 else ""} for {label} '
           f'(role checks covered {covered}/{len(required)})')


def complete_generation(db: DbSession, job: Job, user: User, result: dict):
    job.result = {'endpoints': int(result.get('endpoints', 0)), 'failed': int(result.get('failed', 0))}
    record(db, db.get(Project, job.project_id), user, 'roles.generation_finished',
           f'Role test case generation finished on {user.name}\'s computer; the cases are ready for review')


# --- Reading -----------------------------------------------------------------------------------------------

def _coverage_summary(coverage: RoleCoverage | None, current: str) -> dict | None:
    if not coverage:
        return None
    total = len(coverage.requirements)
    return {'total': total, 'covered': total - len(coverage.gaps), 'error': coverage.error, 'generatedAt': coverage.generated_at,
            'outdated': bool(current) and coverage.access != current, 'verdict': (coverage.review or {}).get('verdict')}


@router.get('')
def overview(project_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    spec = current_spec(db, project_id)
    state = analysis_state(db, project_id, spec)
    document, analysis = state['document'], state['analysis']
    people = names(db, document.uploaded_by if document else None, analysis.generated_by if analysis else None,
                   analysis.edited_by if analysis else None)
    model = analysis.model if analysis else {}
    view = {'document': {'filename': document.filename, 'size': document.size, 'uploadedAt': document.uploaded_at,
                         'uploadedBy': people.get(document.uploaded_by)} if document else None,
            'analysis': {'model': model, 'generatedAt': analysis.generated_at, 'generatedBy': people.get(analysis.generated_by),
                         'editedAt': analysis.edited_at, 'editedBy': people.get(analysis.edited_by),
                         'outdated': state['outdated'], 'ready': state['ready']} if analysis else None,
            'credentials': [{'role': r['name'], 'prefix': env_prefix(r['name']), 'users': r.get('users', 1)}
                            for r in model.get('roles', [])],
            'analyzeJob': _job(db, _latest(db, project_id, ANALYZE)), 'job': _job(db, _latest(db, project_id, GENERATE)),
            'endpoints': [], 'totals': {s: 0 for s in STATUSES}}
    if not spec:
        return view
    counts = {}
    for method, path, status, total in db.execute(
            select(TestCase.method, TestCase.path, TestCase.status, func.count()).where(
                TestCase.project_id == project_id, TestCase.module == 'role').group_by(TestCase.method, TestCase.path, TestCase.status)):
        counts.setdefault((method, path), {})[status] = total
    roles_by_endpoint = {}
    for method, path, content in db.execute(select(TestCase.method, TestCase.path, TestCase.content).where(
            TestCase.project_id == project_id, TestCase.module == 'role')):
        roles_by_endpoint.setdefault((method, path), set()).update(content.get('roles', []))
    coverage = {(c.method, c.path): c for c in db.scalars(select(RoleCoverage).where(RoleCoverage.project_id == project_id))}
    for endpoint in db.scalars(select(Endpoint).where(Endpoint.spec_id == spec.id).order_by(Endpoint.position)):
        key = (endpoint.method, endpoint.path)
        by_status = counts.get(key, {})
        for status, total in by_status.items():
            view['totals'][status] = view['totals'].get(status, 0) + total
        row = access_row(model, endpoint.operation_id) if model else None
        view['endpoints'].append({
            'id': endpoint.id, 'method': endpoint.method, 'path': endpoint.path, 'summary': endpoint.summary, 'tags': endpoint.tags,
            'operationId': endpoint.operation_id, 'access': row, 'cases': {s: by_status.get(s, 0) for s in STATUSES},
            'caseCount': sum(by_status.values()), 'roles': sorted(roles_by_endpoint.get(key, set())),
            'coverage': _coverage_summary(coverage.get(key), row_fingerprint(model, endpoint.operation_id) if model else '')})
    return view


@router.get('/endpoints/{endpoint_id}')
def endpoint_detail(project_id: str, endpoint_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    endpoint, spec = project_endpoint(db, project_id, endpoint_id)
    analysis = db.get(AccessAnalysis, project_id)
    model = analysis.model if analysis else {}
    coverage = db.get(RoleCoverage, (project_id, endpoint.method, endpoint.path))
    script = db.get(ScriptRecord, (project_id, ROLE_SCRIPT, f'{endpoint.method} {endpoint.path}'))
    cases = role_cases(db, project_id, endpoint.method, endpoint.path)
    people = names(db, *[c.created_by for c in cases], *[c.updated_by for c in cases], *[c.reviewed_by for c in cases])
    dicts = {c.id: case_dict(c) for c in cases}
    requirements = []
    if coverage:
        missing = set(coverage.gaps)
        for item in coverage.requirements:
            by = [code(c) for c in cases if contributes(item, dicts[c.id])]
            requirements.append({**item, 'covered': item['id'] not in missing, 'cases': by})
    return {'endpoint': {'id': endpoint.id, 'method': endpoint.method, 'path': endpoint.path, 'summary': endpoint.summary,
                         'operationId': endpoint.operation_id},
            'access': access_row(model, endpoint.operation_id) if model else None,
            'rules': [r for r in model.get('rules', []) if endpoint.operation_id in r.get('operations', [])],
            'coverage': _coverage_summary(coverage, row_fingerprint(model, endpoint.operation_id) if model else ''),
            'requirements': requirements, 'review': coverage.review if coverage else None,
            'cases': [case_json(c, people, spec.version, script.case_fingerprints if script else None) for c in cases],
            'regenerating': regenerating_ids(db, project_id)}


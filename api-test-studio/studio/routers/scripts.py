"""Script generation: approved cases become Playwright specs in each QA's local framework."""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from contracts.flows import compact_endpoint
from contracts.scripts import ScriptEndpointResult

from ..db import get_db
from ..deps import current_user, membership, record
from contracts.roles import env_prefix

from ..models import (AccessAnalysis, Endpoint, FrameworkProfileRecord, Job, Project, ScriptRecord, TestCase, User,
                      UserProjectSetting)
from .helper import ACTIVE, helper_state, job_json
from .projects import current_spec
from .unit import case_fingerprint, code, names, project_case, project_endpoint

router = APIRouter(prefix='/api/projects/{project_id}/scripts', tags=['Scripts'])
KIND = 'scripts.generate'
FLOW = 'FLOW'
MAX_ENDPOINTS = 50


class GenerateInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    endpointIds: list[str] = Field(default_factory=list, max_length=MAX_ENDPOINTS)
    flowIds: list[str] = Field(default_factory=list, max_length=MAX_ENDPOINTS)
    roleEndpointIds: list[str] = Field(default_factory=list, max_length=MAX_ENDPOINTS)


ROLE = 'ROLE'


def approved_cases(db: DbSession, project_id: str, method: str, path: str, module: str = 'unit') -> list[TestCase]:
    return db.scalars(select(TestCase).where(TestCase.project_id == project_id, TestCase.module == module,
                                             TestCase.method == method, TestCase.path == path, TestCase.status == 'approved')
                      .order_by(TestCase.number)).all()


def summarize(script: ScriptRecord | None, approved: list[TestCase]) -> dict:
    """Compare what was scripted with the cases that are approved now."""
    scripted = script.case_fingerprints if script else {}
    current = [c for c in approved if scripted.get(c.id) == case_fingerprint(c)]
    changed = [c for c in approved if c.id in scripted and scripted[c.id] != case_fingerprint(c)]
    new = [c for c in approved if c.id not in scripted]
    removed = [cid for cid in scripted if cid not in {c.id for c in approved}]
    failed = [c for c in (script.checks if script else []) if c['status'] == 'failed']
    if not script or (not script.file_path and script.error):
        state = 'failed' if script and script.error else 'not_generated'
    elif changed or new or removed:
        state = 'needs_update'
    elif failed:
        state = 'checks_failed'
    else:
        state = 'up_to_date'
    return {'state': state, 'approved': len(approved), 'scripted': len(current), 'changed': len(changed), 'new': len(new),
            'removed': len(removed), 'checks': [{'name': c['name'], 'status': c['status'], 'detail': c['detail']} for c in (script.checks if script else [])],
            'filePath': script.file_path if script else '', 'error': script.error if script else '',
            'generatedAt': script.generated_at if script else None}


@router.get('')
def overview(project_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    spec = current_spec(db, project_id)
    job = db.scalar(select(Job).where(Job.project_id == project_id, Job.kind == KIND).order_by(Job.created_at.desc()).limit(1))
    profile = db.get(FrameworkProfileRecord, project_id)
    setting = db.get(UserProjectSetting, (user.id, project_id))
    base = {'job': job_json(job, db.get(User, job.requested_by).name) if job else None,
            'profileStatus': profile.status if profile else 'missing', 'frameworkPathSet': bool(setting and setting.framework_path),
            'endpoints': [], 'flows': [], 'roleEndpoints': []}
    if not spec:
        return base
    scripts = {(s.method, s.path): s for s in db.scalars(select(ScriptRecord).where(ScriptRecord.project_id == project_id))}
    people = names(db, *[s.generated_by for s in scripts.values()])
    for endpoint in db.scalars(select(Endpoint).where(Endpoint.spec_id == spec.id).order_by(Endpoint.position)):
        approved = approved_cases(db, project_id, endpoint.method, endpoint.path)
        script = scripts.get((endpoint.method, endpoint.path))
        if not approved and not script:
            continue
        base['endpoints'].append({'id': endpoint.id, 'method': endpoint.method, 'path': endpoint.path, 'summary': endpoint.summary,
                                  'generatedBy': people.get(script.generated_by) if script else None, **summarize(script, approved)})
    for endpoint in db.scalars(select(Endpoint).where(Endpoint.spec_id == spec.id).order_by(Endpoint.position)):
        approved = approved_cases(db, project_id, endpoint.method, endpoint.path, 'role')
        script = scripts.get((ROLE, f'{endpoint.method} {endpoint.path}'))
        if not approved and not script:
            continue
        base['roleEndpoints'].append({'id': endpoint.id, 'method': endpoint.method, 'path': endpoint.path, 'summary': endpoint.summary,
                                      'generatedBy': people.get(script.generated_by) if script else None,
                                      **summarize(script, approved)})
    flows = db.scalars(select(TestCase).where(TestCase.project_id == project_id, TestCase.module == 'flow')
                       .order_by(TestCase.number)).all()
    flow_scripts = {s.path: s for s in scripts.values() if s.method == FLOW}
    flow_people = names(db, *[s.generated_by for s in flow_scripts.values()])
    base['flows'] = []
    for case in flows:
        script = flow_scripts.get(case.id)
        if case.status != 'approved' and not script:
            continue
        approved = [case] if case.status == 'approved' else []
        base['flows'].append({'id': case.id, 'code': code(case), 'title': case.title, 'steps': len(case.content.get('steps', [])),
                              'generatedBy': flow_people.get(script.generated_by) if script else None, **summarize(script, approved)})
    return base


def script_view(db: DbSession, script: ScriptRecord | None, approved: list[TestCase]) -> dict:
    scripted = script.case_fingerprints if script else {}
    cases = [{'id': c.id, 'code': code(c), 'title': c.title,
              'state': 'current' if scripted.get(c.id) == case_fingerprint(c) else 'changed' if c.id in scripted else 'new'}
             for c in approved]
    return {**summarize(script, approved), 'cases': cases,
            'content': script.content if script else '', 'diff': script.diff if script else '',
            'checksFull': script.checks if script else [], 'envVariables': script.env_variables if script else [],
            'notes': script.notes if script else '', 'fixRounds': script.fix_rounds if script else 0,
            'generatedBy': db.get(User, script.generated_by).name if script else None}


@router.get('/flow/{case_id}')
def flow_detail(project_id: str, case_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    case = project_case(db, project_id, case_id)
    if case.module != 'flow':
        raise HTTPException(404, 'Flow test case not found.')
    script = db.get(ScriptRecord, (project_id, FLOW, case.id))
    return {'endpoint': {'id': case.id, 'method': FLOW, 'path': f'{code(case)} {case.title}', 'summary': case.title},
            **script_view(db, script, [case] if case.status == 'approved' else [])}


@router.get('/role/{endpoint_id}')
def role_detail(project_id: str, endpoint_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    endpoint, _ = project_endpoint(db, project_id, endpoint_id)
    script = db.get(ScriptRecord, (project_id, ROLE, f'{endpoint.method} {endpoint.path}'))
    approved = approved_cases(db, project_id, endpoint.method, endpoint.path, 'role')
    return {'endpoint': {'id': endpoint.id, 'method': endpoint.method, 'path': endpoint.path, 'summary': endpoint.summary},
            **script_view(db, script, approved)}


@router.get('/{endpoint_id}')
def detail(project_id: str, endpoint_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    endpoint, _ = project_endpoint(db, project_id, endpoint_id)
    script = db.get(ScriptRecord, (project_id, endpoint.method, endpoint.path))
    approved = approved_cases(db, project_id, endpoint.method, endpoint.path)
    return {'endpoint': {'id': endpoint.id, 'method': endpoint.method, 'path': endpoint.path, 'summary': endpoint.summary},
            **script_view(db, script, approved)}


@router.post('/generate')
def generate(project_id: str, body: GenerateInput, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, _ = membership(db, project_id, user)
    profile = db.get(FrameworkProfileRecord, project_id)
    if not profile or profile.status != 'confirmed':
        raise HTTPException(400, 'Confirm the framework profile first, so scripts follow your conventions.')
    setting = db.get(UserProjectSetting, (user.id, project_id))
    if not setting or not setting.framework_path:
        raise HTTPException(400, 'Set your local framework folder on the Framework page first.')
    if not helper_state(db, user.id)['connected']:
        raise HTTPException(409, 'Your Local Helper is not connected. Start it on your computer and try again.')
    running = db.scalar(select(Job).where(Job.project_id == project_id, Job.kind == KIND, Job.status.in_(ACTIVE),
                                          Job.requested_by == user.id))
    if running:
        raise HTTPException(409, 'Your computer is already generating scripts for this project. Wait for it to finish.')
    if not body.endpointIds and not body.flowIds and not body.roleEndpointIds:
        raise HTTPException(400, 'Select at least one endpoint or flow.')
    spec = current_spec(db, project_id)
    items = []
    operations = {e.operation_id: e.details for e in db.scalars(select(Endpoint).where(Endpoint.spec_id == spec.id))} if spec else {}
    for case_id in dict.fromkeys(body.flowIds):
        case = project_case(db, project_id, case_id)
        if case.module != 'flow' or case.status != 'approved':
            raise HTTPException(400, f'{code(case)} is not an approved flow test case.')
        used = list(dict.fromkeys(case.content.get('operations', [])))
        items.append({'id': case.id, 'endpointKey': f'{FLOW} {case.id}',
                      'details': {'method': FLOW, 'path': case.title, 'flow': True,
                                  'operations': [compact_endpoint(operations[o]) for o in used if o in operations]},
                      'cases': [{'id': case.id, 'code': code(case), 'title': case.title, 'category': case.category,
                                 'priority': case.priority, 'content': case.content, 'fingerprint': case_fingerprint(case)}]})
    for endpoint_id in dict.fromkeys(body.endpointIds):
        endpoint, _ = project_endpoint(db, project_id, endpoint_id)
        cases = approved_cases(db, project_id, endpoint.method, endpoint.path)
        if not cases:
            raise HTTPException(400, f'{endpoint.method} {endpoint.path} has no approved test cases yet.')
        items.append({'id': endpoint.id, 'endpointKey': f'{endpoint.method} {endpoint.path}', 'details': endpoint.details,
                      'cases': [{'id': c.id, 'code': code(c), 'title': c.title, 'category': c.category, 'priority': c.priority,
                                 'content': c.content, 'fingerprint': case_fingerprint(c)} for c in cases]})
    access = db.get(AccessAnalysis, project_id)
    roles = [{'name': r['name'], 'description': r.get('description', ''), 'users': r.get('users', 1), 'envPrefix': env_prefix(r['name'])}
             for r in ((access.model or {}).get('roles', []) if access else [])]
    for endpoint_id in dict.fromkeys(body.roleEndpointIds):
        endpoint, _ = project_endpoint(db, project_id, endpoint_id)
        cases = approved_cases(db, project_id, endpoint.method, endpoint.path, 'role')
        if not cases:
            raise HTTPException(400, f'{endpoint.method} {endpoint.path} has no approved role test cases yet.')
        items.append({'id': f'role:{endpoint.id}', 'endpointKey': f'{ROLE} {endpoint.method} {endpoint.path}',
                      'details': {**endpoint.details, 'roleCases': True, 'roles': roles},
                      'cases': [{'id': c.id, 'code': code(c), 'title': c.title, 'category': c.category, 'priority': c.priority,
                                 'content': c.content, 'fingerprint': case_fingerprint(c)} for c in cases]})
    job = Job(project_id=project_id, kind=KIND, requested_by=user.id,
              input={'frameworkPath': setting.framework_path, 'profile': profile.profile, 'profileRevision': profile.revision,
                     'api': {'title': spec.title, 'servers': spec.servers, 'securitySchemes': spec.security_schemes},
                     'endpoints': items},
              progress={'message': 'Waiting for your Local Helper', 'percent': 0})
    db.add(job)
    total = sum(len(i['cases']) for i in items)
    record(db, project, user, 'scripts.generation_started',
           f'{user.name} started script generation for {total} approved case{"s" if total != 1 else ""} '
           f'in {len(items)} file{"s" if len(items) != 1 else ""}')
    db.commit()
    return job_json(job, user.name)


def store_script_result(db: DbSession, job: Job, user: User, result: dict):
    parsed = ScriptEndpointResult.model_validate(result)
    item = next((i for i in job.input['endpoints'] if i['id'] == parsed.endpointId), None)
    if not item:
        raise HTTPException(400, 'This endpoint was not part of the job.')
    method, path = item['endpointKey'].split(' ', 1)
    script = db.get(ScriptRecord, (job.project_id, method, path)) or ScriptRecord(project_id=job.project_id, method=method, path=path)
    script.job_id, script.generated_by, script.generated_at = job.id, user.id, time.time()
    project = db.get(Project, job.project_id)
    if parsed.error:
        script.error = parsed.error
        db.merge(script)
        record(db, project, user, 'scripts.endpoint_failed', f'Script generation failed for {item["endpointKey"]}', error=parsed.error[:300])
        return
    fingerprints = {c['id']: c['fingerprint'] for c in item['cases']}
    script.file_path, script.content, script.sha256, script.diff = parsed.path, parsed.content, parsed.sha256, parsed.diff
    script.case_fingerprints = {cid: fingerprints[cid] for cid in parsed.caseIds if cid in fingerprints}
    script.checks = [c.model_dump() for c in parsed.checks]
    script.fix_rounds, script.env_variables, script.notes, script.error = parsed.fixRounds, parsed.envVariables, parsed.notes, ''
    script.profile_revision = job.input.get('profileRevision', 0)
    db.merge(script)
    failed = [c.name for c in parsed.checks if c.status == 'failed']
    outcome = f'checks failed: {", ".join(failed)}' if failed else 'all checks passed'
    record(db, project, user, 'scripts.endpoint_generated',
           f'{len(script.case_fingerprints)} test{"s" if len(script.case_fingerprints) != 1 else ""} written to {parsed.path} on {user.name}\'s computer ({outcome})')


def complete_generation(db: DbSession, job: Job, user: User, result: dict):
    job.result = {'endpoints': int(result.get('endpoints', 0)), 'failed': int(result.get('failed', 0))}
    record(db, db.get(Project, job.project_id), user, 'scripts.generation_finished',
           f'Script generation finished on {user.name}\'s computer')

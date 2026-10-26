"""Flow test case module: whole-API analysis jobs, coverage, review and editing."""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from contracts.flows import (FlowAnalysisResult, FlowStep, FlowType, dependencies, gaps, outline_from_steps, requirements,
                             validate_plan)
from contracts.unit import Priority

from ..db import get_db
from ..deps import current_user, membership, record
from ..models import Endpoint, FlowAnalysis, Job, Project, ScriptRecord, TestCase, User
from .helper import ACTIVE, helper_state, job_json
from .projects import current_spec
from .unit import STATUSES, case_json, code, names, next_number, project_case, regenerating_ids

router = APIRouter(prefix='/api/projects/{project_id}/flows', tags=['Flow test cases'])
KIND = 'flows.generate'
FLOW_METHOD = 'FLOW'


class FlowEdit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int
    title: str = Field(min_length=3, max_length=200)
    objective: str = Field(default='', max_length=1000)
    type: FlowType
    priority: Priority
    preconditions: list[str] = Field(default_factory=list, max_length=20)
    steps: list[FlowStep] = Field(min_length=2)
    testData: str = Field(default='', max_length=1500)
    cleanup: list[str] = Field(default_factory=list, max_length=20)


def flow_cases(db: DbSession, project_id: str) -> list[TestCase]:
    return db.scalars(select(TestCase).where(TestCase.project_id == project_id, TestCase.module == 'flow')
                      .order_by(TestCase.number)).all()


def scripted_flows(db: DbSession, project_id: str) -> dict:
    rows = db.scalars(select(ScriptRecord).where(ScriptRecord.project_id == project_id, ScriptRecord.method == FLOW_METHOD))
    return {cid: fp for row in rows for cid, fp in row.case_fingerprints.items()}


def _check_can_start(db: DbSession, project_id: str, user: User):
    project, _ = membership(db, project_id, user)
    spec = current_spec(db, project_id)
    if not spec:
        raise HTTPException(400, 'Upload an API spec first.')
    if spec.endpoint_count < 2:
        raise HTTPException(400, 'Flow test cases need at least two operations in the API spec.')
    if not helper_state(db, user.id)['connected']:
        raise HTTPException(409, 'Your Local Helper is not connected. Start it on your computer and try again.')
    running = db.scalar(select(Job).where(Job.project_id == project_id, Job.kind == KIND, Job.status.in_(ACTIVE)))
    if running:
        raise HTTPException(409, f'Flows are already being designed by {db.get(User, running.requested_by).name}.')
    return project, spec


def _new_job(db: DbSession, project_id: str, user: User, spec, **extra) -> Job:
    endpoints = db.scalars(select(Endpoint).where(Endpoint.spec_id == spec.id).order_by(Endpoint.position)).all()
    job = Job(project_id=project_id, kind=KIND, requested_by=user.id,
              input={'specVersion': spec.version, 'specSha256': spec.sha256,
                     'api': {'title': spec.title, 'version': spec.api_version, 'description': spec.description[:2000],
                             'servers': spec.servers, 'securitySchemes': spec.security_schemes},
                     'endpoints': [{'id': e.id, 'details': e.details} for e in endpoints], **extra},
              progress={'message': 'Waiting for your Local Helper', 'percent': 0})
    db.add(job)
    return job


@router.post('/generate')
def generate(project_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, spec = _check_can_start(db, project_id, user)
    job = _new_job(db, project_id, user, spec)
    record(db, project, user, 'flows.generation_started', f'{user.name} asked Claude to analyze the APIs and design flow test cases')
    db.commit()
    return job_json(job, user.name)


def _lineage(job: Job) -> list[str]:
    """The ids of every job that worked on the current design: the jobs it continued, then itself."""
    return [*((job.input or {}).get('resume') or {}).get('jobIds', []), job.id]


def resume_state(db: DbSession, project_id: str, spec=None) -> dict | None:
    """What a stopped design can continue from, or None when it has to start over."""
    job = db.scalar(select(Job).where(Job.project_id == project_id, Job.kind == KIND).order_by(Job.created_at.desc()).limit(1))
    analysis = db.get(FlowAnalysis, project_id)
    spec = spec or current_spec(db, project_id)
    if (not job or job.status not in ('failed', 'cancelled') or not analysis or analysis.job_id != job.id
            or not spec or spec.sha256 != analysis.spec_sha256 or not analysis.domain):
        return None
    lineage = _lineage(job)
    jobs = db.scalars(select(Job).where(Job.id.in_(lineage))).all()
    done = list(dict.fromkeys(name for j in sorted(jobs, key=lambda j: j.created_at)
                              for name in (j.result or {}).get('groups', [])))
    flows = [c for c in flow_cases(db, project_id) if c.source_job_id in lineage]
    if not any('groups' in (j.result or {}) for j in jobs):
        # Jobs from before finished groups were recorded: a group's flows are saved only once it is finished.
        done = list(dict.fromkeys(c.content.get('area') for c in flows if c.content.get('area') not in (None, '', 'Coverage gaps')))
    areas = analysis.domain.get('areas', [])
    total = len(areas) + (1 if len(areas) > 1 else 0)
    return {'jobIds': lineage, 'doneGroups': done, 'totalGroups': total, 'flows': len(flows), 'flowCases': flows}


@router.post('/continue')
def continue_generation(project_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    """Continue a design that stopped (for example at a usage limit) without redoing finished areas."""
    project, spec = _check_can_start(db, project_id, user)
    state = resume_state(db, project_id, spec)
    if not state:
        raise HTTPException(409, 'There is no stopped design to continue. Start a new design instead.')
    analysis = db.get(FlowAnalysis, project_id)
    counts: dict[str, int] = {}
    for case in state['flowCases']:
        counts[case.content.get('area', '')] = counts.get(case.content.get('area', ''), 0) + 1
    job = _new_job(db, project_id, user, spec, resume={
        'jobIds': state['jobIds'], 'domain': analysis.domain,
        'doneGroups': [{'name': name, 'flows': counts.get(name, 0)} for name in state['doneGroups']],
        'outlines': [c.content['outline'] for c in state['flowCases'] if c.content.get('outline')]})
    db.flush()
    analysis.job_id = job.id  # the continued job adds to this design
    remaining = max(0, state['totalGroups'] - len(state['doneGroups']))
    record(db, project, user, 'flows.generation_continued',
           f'{user.name} continued the flow design: {len(state["doneGroups"])} areas were already done, {remaining} to go')
    db.commit()
    return job_json(job, user.name)


def _outlines(db: DbSession, project_id: str) -> list[dict]:
    """Validated outlines of the current flows; the server computes coverage from these."""
    return [c.content['outline'] for c in flow_cases(db, project_id) if c.content.get('outline')]


def _store_domain(db: DbSession, job: Job, user: User, parsed: FlowAnalysisResult, endpoints: list[dict]):
    if not parsed.domain:
        raise HTTPException(400, 'The domain stage must include the domain analysis.')
    domain = parsed.domain.model_dump()
    edges = dependencies(endpoints)
    required = requirements(endpoints, edges, domain)
    # A new design replaces every flow that is not approved; approved flows are kept.
    for case in flow_cases(db, job.project_id):
        if case.status != 'approved':
            db.delete(case)
    db.flush()
    analysis = db.get(FlowAnalysis, job.project_id) or FlowAnalysis(project_id=job.project_id)
    analysis.spec_version, analysis.spec_sha256 = job.input['specVersion'], job.input.get('specSha256', '')
    analysis.domain, analysis.dependencies, analysis.requirements = domain, edges, required
    analysis.gaps = [r['id'] for r in gaps(required, _outlines(db, job.project_id))]
    analysis.review, analysis.rounds, analysis.job_id = None, 1, job.id
    analysis.generated_by, analysis.generated_at = user.id, time.time()
    db.merge(analysis)
    record(db, db.get(Project, job.project_id), user, 'flows.domain_analyzed',
           f'Claude analyzed the API: {len(domain["entities"])} entities, {len(domain["businessRules"])} business rules, '
           f'{len(domain.get("areas", []))} business areas')


def _store_flows(db: DbSession, job: Job, user: User, parsed: FlowAnalysisResult, endpoints: list[dict]):
    analysis = db.get(FlowAnalysis, job.project_id)
    if not analysis or analysis.job_id != job.id:
        raise HTTPException(409, 'Send the domain analysis before the flows.')
    plan = [o.model_dump() for o in parsed.plan]
    # Re-check structure on the server; never trust the helper's own verdict.
    broken = {p.split('/', 1)[0] for p in validate_plan(plan, endpoints)}
    outlines = {o['key']: o for o in plan if o['key'] not in broken}
    review = parsed.review.model_dump() if parsed.review else None
    findings = {}
    for finding in (review or {}).get('findings', []):
        findings.setdefault(finding['flowKey'], []).append(finding)
    existing = flow_cases(db, job.project_id)
    approved_titles = {c.title.casefold() for c in existing if c.status == 'approved'}
    lineage = set(_lineage(job))
    this_job = {c.scenario_key: c for c in existing if c.source_job_id in lineage}
    group = parsed.group or ('Coverage gaps' if parsed.stage == 'final' else '')
    added = 0
    for flow in (f.model_dump() for f in parsed.flows):
        outline = outlines.get(flow['flowKey'])
        if not outline or flow['title'].casefold() in approved_titles or flow['flowKey'] in this_job:
            continue
        added += 1
        content = {key: flow[key] for key in ('objective', 'preconditions', 'steps', 'testData', 'cleanup')}
        content.update(goal=outline['goal'], covers=outline['covers'], outline=outline, area=group,
                       confirmationNote=flow['confirmationNote'] or outline['confirmationNote'],
                       operations=[s['operationId'] for s in flow['steps']])
        db.add(TestCase(project_id=job.project_id, module='flow', number=next_number(db, job.project_id), method=FLOW_METHOD,
                        path=flow['flowKey'], operation_id='', spec_version=job.input['specVersion'], scenario_key=flow['flowKey'],
                        title=flow['title'], category=flow['type'], priority=flow['priority'],
                        needs_confirmation=flow['needsConfirmation'] or outline['needsConfirmation'], content=content,
                        findings=findings.get(flow['flowKey'], []), source_job_id=job.id, created_by=user.id, updated_by=user.id))
    db.flush()
    if parsed.stage == 'group' and group:
        finished = (job.result or {}).get('groups', [])
        job.result = {**(job.result or {}), 'groups': [*finished, group] if group not in finished else finished}
    analysis.gaps = [r['id'] for r in gaps(analysis.requirements, _outlines(db, job.project_id))]
    resumed = bool((job.input or {}).get('resume'))
    if parsed.stage == 'final' and not resumed:
        analysis.review, analysis.rounds = review, parsed.rounds
    elif parsed.stage == 'final':
        # A continued design already holds the reviews of earlier areas; add only what this final step found.
        analysis.rounds = parsed.rounds
        if review:
            combined = dict(analysis.review or {'verdict': 'ready', 'summary': '', 'findings': []})
            combined['verdict'] = 'ready' if combined['verdict'] == 'ready' and review['verdict'] == 'ready' else 'needs_attention'
            combined['summary'] = ' '.join(filter(None, [combined['summary'], review['summary']]))[:800]
            combined['findings'] = (combined['findings'] + review['findings'])[:60]
            analysis.review = combined
    elif review:
        combined = dict(analysis.review or {'verdict': 'ready', 'summary': '', 'findings': []})
        combined['verdict'] = 'ready' if combined['verdict'] == 'ready' and review['verdict'] == 'ready' else 'needs_attention'
        combined['summary'] = ' '.join(filter(None, [combined['summary'], f"{group}: {review['summary']}"]))[:800]
        combined['findings'] = (combined['findings'] + review['findings'])[:60]
        analysis.review = combined
    covered = len(analysis.requirements) - len(analysis.gaps)
    where = 'to close coverage gaps' if parsed.stage == 'final' else f'for {group}'
    record(db, db.get(Project, job.project_id), user, 'flows.generated',
           f'Claude designed {added} flow test case{"s" if added != 1 else ""} {where} '
           f'(requirements covered {covered}/{len(analysis.requirements)})')


def store_flow_result(db: DbSession, job: Job, user: User, result: dict):
    parsed = FlowAnalysisResult.model_validate(result)
    endpoints = [item['details'] for item in job.input['endpoints']]
    if parsed.stage == 'domain':
        _store_domain(db, job, user, parsed, endpoints)
    else:
        _store_flows(db, job, user, parsed, endpoints)


def complete_generation(db: DbSession, job: Job, user: User, result: dict):
    job.result = {**(job.result or {}), 'flows': int(result.get('flows', 0))}


@router.get('')
def overview(project_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    spec = current_spec(db, project_id)
    job = db.scalar(select(Job).where(Job.project_id == project_id, Job.kind == KIND).order_by(Job.created_at.desc()).limit(1))
    analysis = db.get(FlowAnalysis, project_id)
    cases = flow_cases(db, project_id)
    people = names(db, *[c.created_by for c in cases], *[c.updated_by for c in cases], *[c.reviewed_by for c in cases],
                   analysis.generated_by if analysis else None)
    scripted = scripted_flows(db, project_id)
    totals = {s: sum(c.status == s for c in cases) for s in STATUSES}
    view = None
    if analysis:
        missing = set(analysis.gaps)
        view = {'domain': analysis.domain, 'dependencies': analysis.dependencies, 'review': analysis.review,
                'requirements': [{**r, 'covered': r['id'] not in missing} for r in analysis.requirements],
                'covered': len(analysis.requirements) - len(missing), 'total': len(analysis.requirements),
                'generatedAt': analysis.generated_at, 'generatedBy': people.get(analysis.generated_by),
                'outdated': bool(spec and spec.sha256 != analysis.spec_sha256)}
    endpoints = {}
    if spec:
        endpoints = {e.operation_id: {'method': e.method, 'path': e.path, 'summary': e.summary or ''}
                     for e in db.scalars(select(Endpoint).where(Endpoint.spec_id == spec.id))}
    resume = resume_state(db, project_id, spec)
    return {'job': job_json(job, db.get(User, job.requested_by).name) if job else None, 'analysis': view,
            'resume': {'doneGroups': len(resume['doneGroups']), 'totalGroups': resume['totalGroups'], 'flows': resume['flows']}
            if resume else None,
            'operations': endpoints, 'totals': totals, 'regenerating': regenerating_ids(db, project_id),
            'flows': [case_json(c, people, spec.version if spec else None, scripted) for c in cases]}


@router.patch('/{case_id}')
def edit_flow(project_id: str, case_id: str, body: FlowEdit, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, _ = membership(db, project_id, user)
    case = project_case(db, project_id, case_id)
    if case.module != 'flow':
        raise HTTPException(404, 'Flow test case not found.')
    if case.revision != body.revision:
        raise HTTPException(409, 'Someone else changed this flow. Reload to see the latest version.')
    steps = [s.model_dump() for s in body.steps]
    spec = current_spec(db, project_id)
    if spec:
        known = {e.operation_id for e in db.scalars(select(Endpoint).where(Endpoint.spec_id == spec.id))}
        unknown = [s['operationId'] for s in steps if s['operationId'] not in known]
        if unknown:
            raise HTTPException(400, f'Unknown operation in steps: {", ".join(unknown)}')
    content = dict(case.content)
    content.update(objective=body.objective, preconditions=body.preconditions, steps=steps, testData=body.testData,
                   cleanup=body.cleanup, operations=[s['operationId'] for s in steps],
                   outline=outline_from_steps(content.get('outline'), case.scenario_key, body.title, body.type, body.priority, steps))
    case.content, case.title, case.category, case.priority = content, body.title.strip(), body.type, body.priority
    previous = case.status
    case.status, case.revision, case.updated_by, case.updated_at = 'in_review', case.revision + 1, user.id, time.time()
    note = ' and moved it back to review' if previous == 'approved' else ''
    record(db, project, user, 'flows.case_edited', f'{user.name} edited {code(case)} {case.title}{note}', caseId=case.id)
    db.commit()
    return case_json(case, names(db, case.created_by, case.updated_by, case.reviewed_by), spec.version if spec else None,
                     scripted_flows(db, project_id))

"""Pairing, presence and job exchange for the Local Helper running on each QA's computer."""
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from contracts import (ASSISTANT_KINDS, CLAUDE_MODEL_CATALOG, CLAUDE_MODELS, CUSTOM_MODEL_PATTERN, LOCAL_MODEL_PATTERN, VERSION, HelperHeartbeat,
                       JobUsage)
from contracts.fingerprint import CONTRACT_FINGERPRINT
from contracts.flows import FlowProgress

from .. import config
from ..db import get_db
from ..deps import current_user, helper_user
from ..models import AuthSession, HelperStatus, Job, PairingCode, Project, ProjectMember, User, UserPreference
from ..security import new_pairing_code, new_token, normalize_pairing_code, pairing_limiter, token_hash

router = APIRouter(tags=['Local Helper'])
ACTIVE = ('queued', 'running')
RESULT_LOCK = threading.Lock()
MAX_ATTEMPTS = 3


class PairInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str = Field(min_length=4, max_length=20)
    hostname: str = Field(default='', max_length=200)


class ProgressInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str = Field(default='', max_length=500)
    percent: int | None = Field(default=None, ge=0, le=100)
    models: list[str] = Field(default_factory=list, max_length=10, description='Models Claude reported for this job so far')
    detail: FlowProgress | None = Field(default=None, description='Structured progress of a flow generation job')
    usage: JobUsage | None = None


MODEL_CHOICES = '|'.join(CLAUDE_MODELS) + '|' + CUSTOM_MODEL_PATTERN + '|' + LOCAL_MODEL_PATTERN


class PreferencesInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    claudeModel: str | None = Field(default=None, max_length=60, pattern=f'^({MODEL_CHOICES})$',
                                    description="A Claude model, or local:<model> on the helper's local AI server. "
                                                'Every step of a job runs on it.')


class CompleteInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    result: dict
    models: list[str] = Field(default_factory=list, max_length=10)
    usage: JobUsage | None = None


class FailInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    error: str = Field(max_length=4000)
    models: list[str] = Field(default_factory=list, max_length=10)
    usage: JobUsage | None = None


def preference(db: DbSession, user_id: str) -> UserPreference:
    return db.get(UserPreference, user_id) or UserPreference(user_id=user_id, claude_model='default', last_models=[])


def remember_models(db: DbSession, user_id: str, models: list[str]):
    if not models:
        return
    pref = preference(db, user_id)
    pref.last_models, pref.last_used_at = list(dict.fromkeys(models)), time.time()
    db.merge(pref)


def preferences_json(pref: UserPreference) -> dict:
    return {'claudeModel': pref.claude_model, 'lastModels': pref.last_models or [],
            'lastUsedAt': pref.last_used_at,
            'options': [{'id': model_id, 'label': label, 'family': family} for model_id, label, family in CLAUDE_MODEL_CATALOG]}


def helper_state(db: DbSession, user_id: str) -> dict:
    status = db.get(HelperStatus, user_id)
    paired = db.scalar(select(AuthSession.token_hash).where(AuthSession.user_id == user_id, AuthSession.kind == 'helper',
                                                           AuthSession.expires_at > time.time()).limit(1)) is not None
    connected = bool(paired and status and status.last_seen >= time.time() - config.HELPER_ONLINE_SECONDS)
    return {'paired': paired, 'connected': connected, 'lastSeen': status.last_seen if status else None,
            'hostname': status.hostname if status else '', 'helperVersion': status.helper_version if status else '',
            'claude': status.claude if status and connected else None,
            'local': (status.local_llm or None) if status and connected else None,
            'model': preferences_json(preference(db, user_id))}


def job_json(job: Job, requester_name: str | None = None) -> dict:
    return {'id': job.id, 'projectId': job.project_id, 'kind': job.kind, 'status': job.status,
            'requestedBy': job.requested_by, 'requestedByName': requester_name, 'progress': job.progress,
            'model': (job.input or {}).get('claudeModel'), 'models': (job.progress or {}).get('models', []),
            'usage': (job.progress or {}).get('usage'),
            'error': job.error, 'createdAt': job.created_at, 'startedAt': job.started_at, 'finishedAt': job.finished_at}


# --- Browser side -------------------------------------------------------------

@router.get('/api/me/helper')
def my_helper(db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    return helper_state(db, user.id)


@router.get('/api/me/preferences')
def my_preferences(db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    return preferences_json(preference(db, user.id))


@router.put('/api/me/preferences')
def update_preferences(body: PreferencesInput, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    pref = preference(db, user.id)
    if body.claudeModel is not None:
        pref.claude_model = body.claudeModel
    db.merge(pref)
    db.commit()
    return preferences_json(preference(db, user.id))


@router.post('/api/me/helper/pairing-code')
def pairing_code(db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    db.execute(delete(PairingCode).where((PairingCode.user_id == user.id) | (PairingCode.expires_at < time.time())))
    code = new_pairing_code()
    db.add(PairingCode(code_hash=token_hash(code), user_id=user.id, expires_at=time.time() + config.PAIRING_CODE_SECONDS))
    db.commit()
    return {'code': f'{code[:4]}-{code[4:]}', 'expiresInSeconds': config.PAIRING_CODE_SECONDS}


@router.delete('/api/me/helper')
def disconnect_helper(db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.kind == 'helper'))
    db.execute(delete(HelperStatus).where(HelperStatus.user_id == user.id))
    db.commit()
    return {'ok': True}


# --- Helper side ----------------------------------------------------------------

@router.post('/api/helper/pair')
def pair(body: PairInput, request: Request, db: DbSession = Depends(get_db)):
    pairing_limiter.check(request.client.host if request.client else 'unknown')
    record = db.get(PairingCode, token_hash(normalize_pairing_code(body.code)))
    if not record or record.expires_at < time.time():
        raise HTTPException(400, 'This pairing code is invalid or has expired. Create a new one in the portal.')
    user = db.get(User, record.user_id)
    db.delete(record)
    # One computer per user: pairing again replaces the previous helper.
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.kind == 'helper'))
    token = new_token()
    db.add(AuthSession(token_hash=token_hash(token), user_id=user.id, kind='helper', label=body.hostname,
                       expires_at=time.time() + config.HELPER_TOKEN_SECONDS))
    db.commit()
    return {'token': token, 'user': {'name': user.name, 'email': user.email}, 'serverVersion': VERSION}


@router.post('/api/helper/heartbeat')
def heartbeat(body: HelperHeartbeat, db: DbSession = Depends(get_db), user: User = Depends(helper_user)):
    status = db.get(HelperStatus, user.id) or HelperStatus(user_id=user.id)
    status.last_seen, status.hostname, status.helper_version = time.time(), body.hostname, body.helperVersion
    status.claude = body.claude.model_dump()
    status.local_llm = body.local.model_dump()
    db.merge(status)
    db.commit()
    return {'ok': True, 'serverVersion': VERSION, 'contracts': CONTRACT_FINGERPRINT}


def _touch(db: DbSession, user: User):
    status = db.get(HelperStatus, user.id)
    if status:
        status.last_seen = time.time()


@router.post('/api/helper/jobs/claim')
def claim(lane: str = 'main', db: DbSession = Depends(get_db), user: User = Depends(helper_user)):
    """The next job for this helper. The assistant lane takes only assistant messages; the main lane everything else."""
    _touch(db, user)
    now = time.time()
    kinds = Job.kind.in_(ASSISTANT_KINDS) if lane == 'assistant' else Job.kind.not_in(ASSISTANT_KINDS)
    candidates = db.scalars(select(Job).where(Job.requested_by == user.id, Job.status.in_(ACTIVE), Job.lease_until < now, kinds)
                            .order_by(Job.created_at)).all()
    for job in candidates:
        if not db.get(ProjectMember, (job.project_id, user.id)):
            # Access was removed after the job was queued.
            job.status, job.error, job.finished_at = 'failed', 'You no longer have access to this project.', now
            continue
        if job.attempts >= MAX_ATTEMPTS:
            job.status, job.finished_at = 'failed', now
            job.error = 'The Local Helper stopped responding while running this job. Start it again and retry.'
            continue
        job.status, job.attempts, job.lease_until = 'running', job.attempts + 1, now + config.JOB_LEASE_SECONDS
        job.started_at = job.started_at or now
        # The model chosen when the job starts is the one it runs on, even if the user switches later.
        pref = preference(db, user.id)
        model = pref.claude_model
        job.input = {**job.input, 'claudeModel': model}
        project = db.get(Project, job.project_id)
        db.commit()
        # Sent with an assistant job but not stored on it: a snapshot of the project, taken now.
        extra = {}
        if job.kind in ASSISTANT_KINDS:
            from ..assistant_snapshot import build_snapshot
            extra['snapshot'] = build_snapshot(db, job.project_id, user)
        return {'job': {'id': job.id, 'kind': job.kind, 'projectId': job.project_id, 'projectName': project.name,
                        'input': {**job.input, **extra}, 'attempt': job.attempts, 'model': model}}
    db.commit()
    return {'job': None}


def _running_job(db: DbSession, job_id: str, user: User) -> Job:
    job = db.get(Job, job_id)
    if not job or job.requested_by != user.id:
        raise HTTPException(404, 'Job not found.')
    if job.status != 'running':
        raise HTTPException(409, f'This job is {job.status} and can no longer be updated.')
    return job


@router.post('/api/helper/jobs/{job_id}/progress')
def progress(job_id: str, body: ProgressInput, db: DbSession = Depends(get_db), user: User = Depends(helper_user)):
    _touch(db, user)
    job = _running_job(db, job_id, user)
    job.progress = body.model_dump(exclude={name for name in ('detail', 'usage') if getattr(body, name) is None})
    job.lease_until = time.time() + config.JOB_LEASE_SECONDS
    remember_models(db, user.id, body.models)
    db.commit()
    return {'ok': True}


def _handlers():
    from .framework import complete_framework_analysis
    from . import assistant, cases, flows, roles, scripts, unit
    return {'complete': {'framework.analyze': complete_framework_analysis, 'unit.generate': unit.complete_generation,
                         'scripts.generate': scripts.complete_generation, 'flows.generate': flows.complete_generation,
                         'case.regenerate': cases.complete_regeneration, 'access.analyze': roles.complete_analysis,
                         'roles.generate': roles.complete_generation, 'assistant.message': assistant.store_reply},
            'partial': {'unit.generate': unit.store_endpoint_result, 'scripts.generate': scripts.store_script_result,
                        'flows.generate': flows.store_flow_result, 'roles.generate': roles.store_endpoint_result,
                        'case.regenerate': cases.store_regenerated}}


@router.post('/api/helper/jobs/{job_id}/partial')
def partial(job_id: str, body: CompleteInput, db: DbSession = Depends(get_db), user: User = Depends(helper_user)):
    # Helpers send several endpoints' results at once; saving them one at a time keeps
    # per-project counters such as TC numbers unique.
    with RESULT_LOCK:
        _touch(db, user)
        job = _running_job(db, job_id, user)
        handler = _handlers()['partial'].get(job.kind)
        if not handler:
            raise HTTPException(400, f'{job.kind} jobs do not accept partial results.')
        try:
            handler(db, job, user, body.result)
        except ValidationError as exc:
            raise HTTPException(400, 'The result does not match the expected format: ' + str(exc)[:800]) from exc
        job.lease_until = time.time() + config.JOB_LEASE_SECONDS
        db.commit()
    return {'ok': True}


@router.post('/api/helper/jobs/{job_id}/complete')
def complete(job_id: str, body: CompleteInput, db: DbSession = Depends(get_db), user: User = Depends(helper_user)):
    job = _running_job(db, job_id, user)
    try:
        _handlers()['complete'][job.kind](db, job, user, body.result)
    except ValidationError as exc:
        raise HTTPException(400, 'The result does not match the expected format: ' + str(exc)[:800]) from exc
    models = body.models or (job.progress or {}).get('models', [])
    job.status, job.finished_at, job.lease_until = 'succeeded', time.time(), 0
    usage = body.usage.model_dump() if body.usage else (job.progress or {}).get('usage')
    job.progress = {'message': 'Done', 'percent': 100, 'models': models, **({'usage': usage} if usage else {})}
    remember_models(db, user.id, models)
    db.commit()
    return {'ok': True}


@router.post('/api/helper/jobs/{job_id}/fail')
def fail(job_id: str, body: FailInput, db: DbSession = Depends(get_db), user: User = Depends(helper_user)):
    job = _running_job(db, job_id, user)
    job.status, job.error, job.finished_at, job.lease_until = 'failed', body.error, time.time(), 0
    if body.usage:
        job.progress = {**(job.progress or {}), 'usage': body.usage.model_dump()}
    if body.models:
        job.progress = {**(job.progress or {}), 'models': body.models}
        remember_models(db, user.id, body.models)
    db.commit()
    return {'ok': True}

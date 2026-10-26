"""Framework folder (per user) and framework profile (shared by the project)."""
import time
from pathlib import PurePosixPath, PureWindowsPath

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from contracts import FrameworkAnalysisResult, FrameworkProfile

from ..db import get_db
from ..deps import current_user, membership, record
from ..models import FrameworkProfileRecord, Job, Project, User, UserProjectSetting
from .helper import ACTIVE, helper_state, job_json

router = APIRouter(prefix='/api/projects/{project_id}/framework', tags=['Framework'])
ANALYZE = 'framework.analyze'


class PathInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str = Field(min_length=1, max_length=1000)


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=0)
    profile: FrameworkProfile
    confirm: bool = False


def valid_local_path(path: str) -> str:
    path = path.strip().strip('"')
    if any(ord(ch) < 32 for ch in path) or not (PureWindowsPath(path).is_absolute() or PurePosixPath(path).is_absolute()):
        raise HTTPException(400, 'Enter the full folder path, for example C:\\work\\api-tests or /home/me/api-tests.')
    return path


def latest_job(db: DbSession, project_id: str) -> Job | None:
    return db.scalar(select(Job).where(Job.project_id == project_id, Job.kind == ANALYZE)
                     .order_by(Job.created_at.desc()).limit(1))


@router.get('')
def framework(project_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    setting = db.get(UserProjectSetting, (user.id, project_id))
    profile = db.get(FrameworkProfileRecord, project_id)
    job = latest_job(db, project_id)
    updated_by = db.get(User, profile.updated_by).name if profile else None
    requester = db.get(User, job.requested_by).name if job else None
    return {'myPath': setting.framework_path if setting else '',
            'profile': profile.profile if profile else None, 'scan': profile.scan if profile else None,
            'status': profile.status if profile else 'missing', 'revision': profile.revision if profile else 0,
            'updatedBy': updated_by, 'updatedAt': profile.updated_at if profile else None,
            'latestJob': job_json(job, requester) if job else None}


@router.put('/path')
def set_path(project_id: str, body: PathInput, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    path = valid_local_path(body.path)
    setting = db.get(UserProjectSetting, (user.id, project_id)) or UserProjectSetting(user_id=user.id, project_id=project_id)
    setting.framework_path = path
    db.merge(setting)
    db.commit()
    return {'myPath': path}


@router.post('/analyze')
def analyze(project_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, _ = membership(db, project_id, user)
    setting = db.get(UserProjectSetting, (user.id, project_id))
    if not setting or not setting.framework_path:
        raise HTTPException(400, 'Set your local framework folder first.')
    if not helper_state(db, user.id)['connected']:
        raise HTTPException(409, 'Your Local Helper is not connected. Start it on your computer and try again.')
    if db.scalar(select(Job.id).where(Job.project_id == project_id, Job.kind == ANALYZE, Job.status.in_(ACTIVE))):
        raise HTTPException(409, 'A framework analysis is already running for this project.')
    job = Job(project_id=project_id, kind=ANALYZE, requested_by=user.id,
              input={'frameworkPath': setting.framework_path, 'projectName': project.name},
              progress={'message': 'Waiting for your Local Helper', 'percent': 0})
    db.add(job)
    record(db, project, user, 'framework.analysis_started', f'{user.name} started a framework analysis')
    db.commit()
    return job_json(job, user.name)


@router.put('/profile')
def save_profile(project_id: str, body: ProfileInput, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, _ = membership(db, project_id, user)
    profile = db.get(FrameworkProfileRecord, project_id)
    if not profile:
        raise HTTPException(404, 'Analyze the framework before editing its profile.')
    if profile.revision != body.revision:
        raise HTTPException(409, 'Someone else changed the framework profile. Reload to see the latest version.')
    profile.profile = body.profile.model_dump()
    profile.status = 'confirmed' if body.confirm else profile.status
    profile.updated_by, profile.updated_at, profile.revision = user.id, time.time(), profile.revision + 1
    verb = 'confirmed' if body.confirm else 'edited'
    record(db, project, user, f'framework.profile_{verb}', f'{user.name} {verb} the framework profile')
    db.commit()
    return framework(project_id, db, user)


def complete_framework_analysis(db: DbSession, job: Job, user: User, result: dict):
    parsed = FrameworkAnalysisResult.model_validate(result)
    profile = db.get(FrameworkProfileRecord, job.project_id)
    revision = profile.revision + 1 if profile else 1
    db.merge(FrameworkProfileRecord(project_id=job.project_id, profile=parsed.profile.model_dump(),
                                    scan=parsed.scan.model_dump(), status='draft', source_job_id=job.id,
                                    updated_by=user.id, updated_at=time.time(), revision=revision))
    job.result = {'specFileCount': parsed.scan.specFileCount}
    record(db, db.get(Project, job.project_id), user, 'framework.analyzed',
           f'Framework analysis finished on {user.name}\'s computer — review and confirm the profile')

import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..db import get_db
from ..deps import LEAD, current_user, membership, record
from ..models import Job, User
from .helper import ACTIVE, job_json

router = APIRouter(prefix='/api/projects/{project_id}/jobs', tags=['Jobs'])


@router.get('')
def list_jobs(project_id: str, kind: str | None = None, limit: int = Query(default=20, ge=1, le=100),
              db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    query = select(Job, User.name).join(User, User.id == Job.requested_by).where(Job.project_id == project_id)
    if kind:
        query = query.where(Job.kind == kind)
    rows = db.execute(query.order_by(Job.created_at.desc()).limit(limit)).all()
    return [job_json(job, name) for job, name in rows]


@router.get('/{job_id}')
def get_job(project_id: str, job_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    job = db.get(Job, job_id)
    if not job or job.project_id != project_id:
        raise HTTPException(404, 'Job not found.')
    return job_json(job, db.get(User, job.requested_by).name)


@router.post('/{job_id}/cancel')
def cancel_job(project_id: str, job_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, member = membership(db, project_id, user)
    job = db.get(Job, job_id)
    if not job or job.project_id != project_id:
        raise HTTPException(404, 'Job not found.')
    if job.requested_by != user.id and member.role != LEAD:
        raise HTTPException(403, 'Only the person who started this job or a project lead can cancel it.')
    if job.status not in ACTIVE:
        raise HTTPException(409, 'This job has already finished.')
    job.status, job.finished_at, job.lease_until, job.error = 'cancelled', time.time(), 0, f'Cancelled by {user.name}'
    record(db, project, user, 'job.cancelled', f'{user.name} cancelled a {job.kind} job', jobId=job.id)
    db.commit()
    return job_json(job, db.get(User, job.requested_by).name)

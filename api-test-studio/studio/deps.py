"""Authentication and project-permission helpers used by every router."""
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session as DbSession

from .db import get_db
from .models import Activity, AuthSession, Project, ProjectMember, User
from .security import token_hash

SESSION_COOKIE = 'studio_session'
LEAD, EMPLOYEE = 'lead', 'employee'


@dataclass
class Caller:
    user: User
    kind: str  # browser | helper


def _authenticate(request: Request, db: DbSession) -> Caller:
    header = request.headers.get('authorization', '')
    token = header[7:] if header.startswith('Bearer ') else request.cookies.get(SESSION_COOKIE, '')
    if not token:
        raise HTTPException(401, 'Please sign in to continue.')
    if not header and request.method not in ('GET', 'HEAD', 'OPTIONS'):
        # Cookie-authenticated writes must come from this site.
        origin = request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            raise HTTPException(403, 'Cross-site request rejected.')
    session = db.get(AuthSession, token_hash(token))
    if not session or session.expires_at < time.time():
        raise HTTPException(401, 'Your session has expired. Please sign in again.')
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, 'Please sign in to continue.')
    return Caller(user, session.kind)


def current_user(request: Request, db: DbSession = Depends(get_db)) -> User:
    caller = _authenticate(request, db)
    if caller.kind != 'browser':
        raise HTTPException(403, 'Helper tokens can only be used by the Local Helper.')
    return caller.user


def helper_user(request: Request, db: DbSession = Depends(get_db)) -> User:
    caller = _authenticate(request, db)
    if caller.kind != 'helper':
        raise HTTPException(403, 'This endpoint is only for the Local Helper.')
    return caller.user


def membership(db: DbSession, project_id: str, user: User, lead: bool = False) -> tuple[Project, ProjectMember]:
    project = db.get(Project, project_id)
    member = db.get(ProjectMember, (project_id, user.id)) if project else None
    if not project or not member:
        raise HTTPException(404, 'Project not found, or you do not have access to it.')
    if lead and member.role != LEAD:
        raise HTTPException(403, 'Only a project lead can do this.')
    return project, member


def record(db: DbSession, project: Project, actor: User | None, action: str, summary: str, **detail):
    db.add(Activity(project_id=project.id, actor_id=actor.id if actor else None,
                    action=action, summary=summary, detail=detail))
    project.updated_at = time.time()

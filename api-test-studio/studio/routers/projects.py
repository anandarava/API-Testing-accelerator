from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession

from ..db import get_db
from ..deps import EMPLOYEE, LEAD, current_user, membership, record
from ..models import (Activity, Counter, Endpoint, EndpointCoverage, FlowAnalysis, FrameworkProfileRecord, Job, Project,
                      ProjectMember, ScriptRecord, Spec, TestCase, User, UserProjectSetting)
from .helper import helper_state

router = APIRouter(prefix='/api/projects', tags=['Projects'])


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=1000)


class MemberInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=3, max_length=254)
    role: str = Field(default=EMPLOYEE, pattern=f'^({LEAD}|{EMPLOYEE})$')


class RoleInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: str = Field(pattern=f'^({LEAD}|{EMPLOYEE})$')


def current_spec(db: DbSession, project_id: str) -> Spec | None:
    return db.scalar(select(Spec).where(Spec.project_id == project_id, Spec.is_current.is_(True)))


def project_card(db: DbSession, project: Project, role: str) -> dict:
    spec = current_spec(db, project.id)
    members = db.scalar(select(func.count()).select_from(ProjectMember).where(ProjectMember.project_id == project.id))
    return {'id': project.id, 'name': project.name, 'description': project.description, 'role': role,
            'createdAt': project.created_at, 'updatedAt': project.updated_at, 'memberCount': members,
            'spec': {'title': spec.title, 'version': spec.version, 'apiVersion': spec.api_version,
                     'endpointCount': spec.endpoint_count} if spec else None}


@router.get('')
def list_projects(db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    rows = db.execute(select(Project, ProjectMember.role).join(ProjectMember, ProjectMember.project_id == Project.id)
                      .where(ProjectMember.user_id == user.id).order_by(Project.updated_at.desc())).all()
    return [project_card(db, project, role) for project, role in rows]


@router.post('')
def create_project(body: ProjectInput, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project = Project(name=body.name.strip(), description=body.description.strip(), created_by=user.id)
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=LEAD, added_by=user.id))
    record(db, project, user, 'project.created', f'{user.name} created the project')
    db.commit()
    return project_card(db, project, LEAD)


@router.get('/{project_id}')
def get_project(project_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, member = membership(db, project_id, user)
    card = project_card(db, project, member.role)
    setting = db.get(UserProjectSetting, (user.id, project.id))
    profile = db.get(FrameworkProfileRecord, project.id)
    card['setup'] = {
        'specUploaded': card['spec'] is not None,
        'helperConnected': helper_state(db, user.id)['connected'],
        'frameworkPathSet': bool(setting and setting.framework_path),
        'frameworkProfile': profile.status if profile else 'missing',
    }
    return card


@router.patch('/{project_id}')
def update_project(project_id: str, body: ProjectInput, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, member = membership(db, project_id, user, lead=True)
    project.name, project.description = body.name.strip(), body.description.strip()
    record(db, project, user, 'project.updated', f'{user.name} updated the project details')
    db.commit()
    return project_card(db, project, member.role)


@router.delete('/{project_id}')
def delete_project(project_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, _ = membership(db, project_id, user, lead=True)
    for model in (Activity, ScriptRecord, Counter, FlowAnalysis, TestCase, EndpointCoverage, Job, Endpoint, Spec, FrameworkProfileRecord,
                  UserProjectSetting, ProjectMember):
        db.execute(delete(model).where(model.project_id == project_id))
    db.delete(project)
    db.commit()
    return {'ok': True}


# --- Members ---------------------------------------------------------------

def member_json(member: ProjectMember, user: User) -> dict:
    return {'userId': user.id, 'name': user.name, 'email': user.email, 'role': member.role, 'addedAt': member.added_at}


def lead_count(db: DbSession, project_id: str) -> int:
    return db.scalar(select(func.count()).select_from(ProjectMember)
                     .where(ProjectMember.project_id == project_id, ProjectMember.role == LEAD))


@router.get('/{project_id}/members')
def list_members(project_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    rows = db.execute(select(ProjectMember, User).join(User, User.id == ProjectMember.user_id)
                      .where(ProjectMember.project_id == project_id)).all()
    rows.sort(key=lambda row: (row[0].role != LEAD, row[1].name.lower()))
    return [member_json(m, u) for m, u in rows]


@router.post('/{project_id}/members')
def add_member(project_id: str, body: MemberInput, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, _ = membership(db, project_id, user, lead=True)
    target = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if not target:
        raise HTTPException(404, f'No account found for {body.email}. Ask them to create an account first.')
    if db.get(ProjectMember, (project_id, target.id)):
        raise HTTPException(409, f'{target.name} is already a member of this project.')
    member = ProjectMember(project_id=project_id, user_id=target.id, role=body.role, added_by=user.id)
    db.add(member)
    record(db, project, user, 'member.added', f'{user.name} added {target.name} as {body.role}',
           memberId=target.id, role=body.role)
    db.commit()
    return member_json(member, target)


@router.patch('/{project_id}/members/{member_id}')
def change_role(project_id: str, member_id: str, body: RoleInput, db: DbSession = Depends(get_db),
                user: User = Depends(current_user)):
    project, _ = membership(db, project_id, user, lead=True)
    member = db.get(ProjectMember, (project_id, member_id))
    if not member:
        raise HTTPException(404, 'Member not found.')
    if member.role == LEAD and body.role != LEAD and lead_count(db, project_id) == 1:
        raise HTTPException(409, 'A project needs at least one lead. Make someone else a lead first.')
    target = db.get(User, member_id)
    if member.role != body.role:
        member.role = body.role
        record(db, project, user, 'member.role_changed', f'{user.name} changed {target.name} to {body.role}',
               memberId=member_id, role=body.role)
    db.commit()
    return member_json(member, target)


@router.delete('/{project_id}/members/{member_id}')
def remove_member(project_id: str, member_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, _ = membership(db, project_id, user, lead=True)
    member = db.get(ProjectMember, (project_id, member_id))
    if not member:
        raise HTTPException(404, 'Member not found.')
    if member.role == LEAD and lead_count(db, project_id) == 1:
        raise HTTPException(409, 'A project needs at least one lead. Make someone else a lead first.')
    target = db.get(User, member_id)
    db.delete(member)
    db.execute(delete(UserProjectSetting).where(UserProjectSetting.project_id == project_id,
                                                UserProjectSetting.user_id == member_id))
    record(db, project, user, 'member.removed', f'{user.name} removed {target.name} from the project', memberId=member_id)
    db.commit()
    return {'ok': True}


# --- Activity ----------------------------------------------------------------

@router.get('/{project_id}/activity')
def activity(project_id: str, limit: int = Query(default=100, ge=1, le=500), db: DbSession = Depends(get_db),
             user: User = Depends(current_user)):
    membership(db, project_id, user)
    rows = db.execute(select(Activity, User.name).outerjoin(User, User.id == Activity.actor_id)
                      .where(Activity.project_id == project_id).order_by(Activity.created_at.desc()).limit(limit)).all()
    return [{'id': a.id, 'action': a.action, 'summary': a.summary, 'actorName': name or 'System',
             'createdAt': a.created_at} for a, name in rows]


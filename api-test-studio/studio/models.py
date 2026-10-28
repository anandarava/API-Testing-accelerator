import time
import uuid

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def uid():
    return uuid.uuid4().hex


def now():
    return time.time()


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[float] = mapped_column(Float, default=now)


class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # browser | helper
    label: Mapped[str] = mapped_column(String(200), default='')
    created_at: Mapped[float] = mapped_column(Float, default=now)
    expires_at: Mapped[float] = mapped_column(Float)


class PairingCode(Base):
    __tablename__ = 'pairing_codes'
    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    expires_at: Mapped[float] = mapped_column(Float)


class HelperStatus(Base):
    __tablename__ = 'helper_status'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    last_seen: Mapped[float] = mapped_column(Float, default=now)
    hostname: Mapped[str] = mapped_column(String(200), default='')
    helper_version: Mapped[str] = mapped_column(String(40), default='')
    claude: Mapped[dict] = mapped_column(JSON, default=dict)
    local_llm: Mapped[dict] = mapped_column(JSON, default=dict)  # the helper's local AI server, without its key


class Project(Base):
    __tablename__ = 'projects'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(1000), default='')
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Float, default=now)
    updated_at: Mapped[float] = mapped_column(Float, default=now)


class ProjectMember(Base):
    __tablename__ = 'project_members'
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    role: Mapped[str] = mapped_column(String(10))  # lead | employee
    added_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    added_at: Mapped[float] = mapped_column(Float, default=now)


class Spec(Base):
    __tablename__ = 'specs'
    __table_args__ = (UniqueConstraint('project_id', 'version'),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), index=True)
    version: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64))
    spec_format: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(300), default='')
    api_version: Mapped[str] = mapped_column(String(100), default='')
    description: Mapped[str] = mapped_column(Text, default='')
    servers: Mapped[list] = mapped_column(JSON, default=list)
    security_schemes: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    changes: Mapped[dict] = mapped_column(JSON, default=dict)
    endpoint_count: Mapped[int] = mapped_column(Integer, default=0)
    raw_text: Mapped[str] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    uploaded_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Float, default=now)


class Endpoint(Base):
    __tablename__ = 'endpoints'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), index=True)
    spec_id: Mapped[str] = mapped_column(ForeignKey('specs.id', ondelete='CASCADE'), index=True)
    operation_id: Mapped[str] = mapped_column(String(300))
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(1000))
    summary: Mapped[str] = mapped_column(String(1000), default='')
    tags: Mapped[list] = mapped_column(JSON, default=list)
    deprecated: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    fingerprint: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class FrameworkProfileRecord(Base):
    __tablename__ = 'framework_profiles'
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True)
    profile: Mapped[dict] = mapped_column(JSON)
    scan: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(10), default='draft')  # draft | confirmed
    source_job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    updated_at: Mapped[float] = mapped_column(Float, default=now)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class UserProjectSetting(Base):
    __tablename__ = 'user_project_settings'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True)
    framework_path: Mapped[str] = mapped_column(String(1000), default='')


class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(12), default='queued', index=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(Text, default='')
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[float] = mapped_column(Float, default=now)
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class Activity(Base):
    __tablename__ = 'activity'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    summary: Mapped[str] = mapped_column(String(500))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=now, index=True)


class TestCase(Base):
    __tablename__ = 'test_cases'
    __table_args__ = (UniqueConstraint('project_id', 'number'),)
    __test__ = False  # not a pytest class
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), index=True)
    module: Mapped[str] = mapped_column(String(10), default='unit')  # unit | flow | role
    number: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(1000))
    operation_id: Mapped[str] = mapped_column(String(300), default='')
    spec_version: Mapped[int] = mapped_column(Integer, default=1)
    scenario_key: Mapped[str] = mapped_column(String(10), default='')
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(20))
    priority: Mapped[str] = mapped_column(String(2))
    status: Mapped[str] = mapped_column(String(15), default='in_review', index=True)
    needs_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    review_comment: Mapped[str] = mapped_column(Text, default='')
    source_job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Float, default=now)
    updated_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    updated_at: Mapped[float] = mapped_column(Float, default=now)
    reviewed_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reviewed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class EndpointCoverage(Base):
    """Latest generation result per endpoint (keyed by method + path so it survives spec re-uploads)."""
    __tablename__ = 'endpoint_coverage'
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True)
    method: Mapped[str] = mapped_column(String(10), primary_key=True)
    path: Mapped[str] = mapped_column(String(1000), primary_key=True)
    spec_version: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64), default='')
    requirements: Mapped[list] = mapped_column(JSON, default=list)
    checklist: Mapped[list] = mapped_column(JSON, default=list)
    gaps: Mapped[list] = mapped_column(JSON, default=list)
    review: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rounds: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str] = mapped_column(Text, default='')
    job_id: Mapped[str] = mapped_column(String(32))
    generated_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    generated_at: Mapped[float] = mapped_column(Float, default=now)


class ScriptRecord(Base):
    """The latest generated spec file per endpoint (keyed by method + path)."""
    __tablename__ = 'scripts'
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True)
    method: Mapped[str] = mapped_column(String(10), primary_key=True)
    path: Mapped[str] = mapped_column(String(1000), primary_key=True)
    file_path: Mapped[str] = mapped_column(String(300), default='')
    content: Mapped[str] = mapped_column(Text, default='')
    sha256: Mapped[str] = mapped_column(String(64), default='')
    diff: Mapped[str] = mapped_column(Text, default='')
    case_fingerprints: Mapped[dict] = mapped_column(JSON, default=dict)  # case id -> fingerprint when scripted
    checks: Mapped[list] = mapped_column(JSON, default=list)
    fix_rounds: Mapped[int] = mapped_column(Integer, default=0)
    env_variables: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default='')
    error: Mapped[str] = mapped_column(Text, default='')
    profile_revision: Mapped[int] = mapped_column(Integer, default=0)
    job_id: Mapped[str] = mapped_column(String(32))
    generated_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    generated_at: Mapped[float] = mapped_column(Float, default=now)


class Counter(Base):
    """Monotonic per-project counters, so ids such as TC-0042 are never reused."""
    __tablename__ = 'counters'
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True)
    name: Mapped[str] = mapped_column(String(30), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class FlowAnalysis(Base):
    """The latest whole-API flow analysis: domain model, dependencies, coverage and review."""
    __tablename__ = 'flow_analysis'
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True)
    spec_version: Mapped[int] = mapped_column(Integer)
    spec_sha256: Mapped[str] = mapped_column(String(64), default='')
    domain: Mapped[dict] = mapped_column(JSON, default=dict)
    dependencies: Mapped[list] = mapped_column(JSON, default=list)
    requirements: Mapped[list] = mapped_column(JSON, default=list)
    gaps: Mapped[list] = mapped_column(JSON, default=list)
    review: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rounds: Mapped[int] = mapped_column(Integer, default=1)
    job_id: Mapped[str] = mapped_column(String(32))
    generated_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    generated_at: Mapped[float] = mapped_column(Float, default=now)


class UserPreference(Base):
    """Per-user settings that follow the person across projects, such as the AI model (Claude or local:<model>)."""
    __tablename__ = 'user_preferences'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    claude_model: Mapped[str] = mapped_column(String(60), default='default')
    writer_model: Mapped[str] = mapped_column(String(60), default='')  # no longer used; kept so older databases stay valid
    last_models: Mapped[list] = mapped_column(JSON, default=list)  # models Claude reported for the latest job
    last_used_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class AccessDocument(Base):
    """The project's roles file (roles and what each may do; never credentials), stored as extracted text."""
    __tablename__ = 'access_documents'
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True)
    filename: Mapped[str] = mapped_column(String(300))
    size: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default='')
    sha256: Mapped[str] = mapped_column(String(64))
    uploaded_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    uploaded_at: Mapped[float] = mapped_column(Float, default=now)


class AccessAnalysis(Base):
    """The permission grid Claude built from the roles file and the spec; the QA can correct it."""
    __tablename__ = 'access_analysis'
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True)
    document_sha: Mapped[str] = mapped_column(String(64))
    spec_sha: Mapped[str] = mapped_column(String(64), default='')
    model: Mapped[dict] = mapped_column(JSON, default=dict)
    edited_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    edited_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    job_id: Mapped[str] = mapped_column(String(32))
    generated_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    generated_at: Mapped[float] = mapped_column(Float, default=now)


class RoleCoverage(Base):
    """Latest role-case generation per endpoint; `access` is the permission row the cases were built from."""
    __tablename__ = 'role_coverage'
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True)
    method: Mapped[str] = mapped_column(String(10), primary_key=True)
    path: Mapped[str] = mapped_column(String(1000), primary_key=True)
    access: Mapped[str] = mapped_column(String(64), default='')
    requirements: Mapped[list] = mapped_column(JSON, default=list)
    gaps: Mapped[list] = mapped_column(JSON, default=list)
    review: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(Text, default='')
    job_id: Mapped[str] = mapped_column(String(32))
    generated_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    generated_at: Mapped[float] = mapped_column(Float, default=now)


class AssistantMessage(Base):
    """One message of a user's conversation with the project assistant (each user has their own per project)."""
    __tablename__ = 'assistant_messages'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    text: Mapped[str] = mapped_column(Text, default='')
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # the reply, its actions and drafts with their state
    context: Mapped[dict] = mapped_column(JSON, default=dict)  # the page the user asked from
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=now)


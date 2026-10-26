import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from .. import config
from ..db import get_db
from ..deps import current_user, membership, record
from ..models import Endpoint, Spec, User
from ..openapi import SpecError, compare, fingerprint, parse_spec
from .projects import current_spec

router = APIRouter(prefix='/api/projects/{project_id}', tags=['API specs'])


def spec_json(spec: Spec, uploader: str | None = None) -> dict:
    return {'id': spec.id, 'version': spec.version, 'filename': spec.filename, 'format': spec.spec_format,
            'title': spec.title, 'apiVersion': spec.api_version, 'description': spec.description,
            'servers': spec.servers, 'securitySchemes': spec.security_schemes, 'warnings': spec.warnings,
            'changes': spec.changes, 'endpointCount': spec.endpoint_count, 'isCurrent': spec.is_current,
            'uploadedBy': uploader, 'createdAt': spec.created_at}


@router.get('/specs')
def list_specs(project_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    rows = db.execute(select(Spec, User.name).join(User, User.id == Spec.uploaded_by)
                      .where(Spec.project_id == project_id).order_by(Spec.version.desc())).all()
    return [spec_json(spec, name) for spec, name in rows]


@router.post('/specs')
async def upload_spec(project_id: str, file: UploadFile = File(...), db: DbSession = Depends(get_db),
                      user: User = Depends(current_user)):
    project, _ = membership(db, project_id, user)
    filename = Path(file.filename or 'openapi.json').name
    if Path(filename).suffix.lower() not in ('.json', '.yaml', '.yml'):
        raise HTTPException(400, 'Upload an OpenAPI or Swagger file in JSON or YAML format.')
    raw = await file.read(config.MAX_SPEC_BYTES + 1)
    if len(raw) > config.MAX_SPEC_BYTES:
        raise HTTPException(413, f'The file is larger than {config.MAX_SPEC_BYTES // 1_000_000} MB.')
    try:
        text = raw.decode('utf-8-sig')
        parsed = parse_spec(text)
    except UnicodeDecodeError as exc:
        raise HTTPException(400, 'The file must be UTF-8 text.') from exc
    except SpecError as exc:
        raise HTTPException(400, str(exc)) from exc

    previous = current_spec(db, project_id)
    before = {}
    if previous:
        before = {(e.method, e.path): e.fingerprint for e in
                  db.scalars(select(Endpoint).where(Endpoint.spec_id == previous.id))}
        if previous.sha256 == hashlib.sha256(raw).hexdigest():
            raise HTTPException(409, f'This file is identical to the current version (v{previous.version}).')
    db.execute(update(Spec).where(Spec.project_id == project_id).values(is_current=False))
    endpoints = parsed['endpoints']
    after = {(e['method'], e['path']): fingerprint(e) for e in endpoints}
    latest = db.scalar(select(Spec.version).where(Spec.project_id == project_id).order_by(Spec.version.desc()).limit(1))
    version = (latest or 0) + 1
    spec = Spec(project_id=project_id, version=version, filename=filename, sha256=hashlib.sha256(raw).hexdigest(),
                spec_format=parsed['format'], title=parsed['title'][:300], api_version=parsed['version'][:100],
                description=parsed['description'], servers=parsed['servers'], security_schemes=parsed['securitySchemes'],
                warnings=parsed['warnings'], changes=compare(before, after) if previous else {},
                endpoint_count=len(endpoints), raw_text=text, uploaded_by=user.id, is_current=True)
    db.add(spec)
    db.flush()
    for position, endpoint in enumerate(endpoints):
        db.add(Endpoint(project_id=project_id, spec_id=spec.id, operation_id=endpoint['operationId'][:300],
                        method=endpoint['method'], path=endpoint['path'][:1000], summary=endpoint['summary'][:1000],
                        tags=endpoint['tags'], deprecated=endpoint['deprecated'], position=position,
                        fingerprint=after[(endpoint['method'], endpoint['path'])], details=endpoint))
    title = spec.title or filename
    record(db, project, user, 'spec.uploaded', f'{user.name} uploaded {title} (v{version}, {len(endpoints)} endpoints)',
           specId=spec.id, version=version)
    db.commit()
    return spec_json(spec, user.name)


@router.get('/endpoints')
def list_endpoints(project_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    spec = current_spec(db, project_id)
    if not spec:
        return {'spec': None, 'endpoints': []}
    rows = db.scalars(select(Endpoint).where(Endpoint.spec_id == spec.id).order_by(Endpoint.position)).all()
    return {'spec': spec_json(spec), 'endpoints': [
        {'id': e.id, 'operationId': e.operation_id, 'method': e.method, 'path': e.path, 'summary': e.summary,
         'tags': e.tags, 'deprecated': e.deprecated} for e in rows]}


@router.get('/endpoints/{endpoint_id}')
def get_endpoint(project_id: str, endpoint_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    endpoint = db.get(Endpoint, endpoint_id)
    if not endpoint or endpoint.project_id != project_id:
        raise HTTPException(404, 'Endpoint not found.')
    return {'id': endpoint.id, **endpoint.details}

"""The project assistant: conversations, actions the user confirms, and flows drafted on request.

Answers are computed on the user's own Local Helper. Every action goes through the same functions (and permission
checks) as the buttons on the pages, and only after the user confirms it.
"""
import copy
import re
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from contracts.assistant import ASSISTANT_KIND, AssistantResult
from contracts.cases import validate_detailed_flow
from contracts.flows import JOURNEYS, gaps, validate_plan

from ..db import get_db
from ..deps import LEAD, current_user, membership, record
from ..models import AssistantMessage, Endpoint, FlowAnalysis, Job, TestCase, User
from .helper import ACTIVE, helper_state
from .projects import current_spec

router = APIRouter(prefix='/api/projects/{project_id}/assistant', tags=['Assistant'])
HISTORY = 10  # earlier messages sent with a question
CODE_IN_TEXT = re.compile(r'\bTC-\d{4,}\b')
STATUS_WORDS = {'approve': 'approved', 'reject': 'rejected', 'needs_changes': 'sent back for changes', 'reopen': 'moved back to review'}


class MessageInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=4000)
    context: dict = Field(default_factory=dict, description='The page the user asked from, e.g. {"page": "flows"}')


def _code(case: TestCase) -> str:
    return f'TC-{case.number:04d}'


def _cases_by_code(db: DbSession, project_id: str, codes: list[str]) -> dict[str, TestCase]:
    numbers = {int(c[3:]) for c in codes if isinstance(c, str) and c.startswith('TC-') and c[3:].isdigit()}
    if not numbers:
        return {}
    found = db.scalars(select(TestCase).where(TestCase.project_id == project_id, TestCase.number.in_(numbers))).all()
    return {_code(c): c for c in found}


def _case_ref(case: TestCase, endpoint_ids: dict) -> dict:
    return {'code': _code(case), 'id': case.id, 'module': case.module, 'title': case.title, 'status': case.status,
            'needsConfirmation': case.needs_confirmation, 'endpointId': endpoint_ids.get((case.method, case.path))}


def _endpoint_ids(db: DbSession, project_id: str) -> dict:
    spec = current_spec(db, project_id)
    if not spec:
        return {}
    return {(e.method, e.path): e.id for e in db.scalars(select(Endpoint).where(Endpoint.spec_id == spec.id))}


def _draft_json(draft: dict, ops: dict) -> dict:
    flow, outline = draft['flow'], draft['outline']
    return {'title': flow['title'], 'type': flow['type'], 'priority': flow['priority'], 'area': draft.get('area', ''),
            'objective': flow.get('objective', ''), 'needsConfirmation': flow['needsConfirmation'] or outline['needsConfirmation'],
            'confirmationNote': flow.get('confirmationNote') or outline.get('confirmationNote', ''),
            'steps': [f"{ops[s['operationId']].method} {ops[s['operationId']].path}" if s['operationId'] in ops else s['operationId']
                      for s in flow['steps']],
            'state': draft.get('state', 'pending'), 'caseCode': draft.get('caseCode')}


def message_json(db: DbSession, message: AssistantMessage, jobs: dict, endpoint_ids: dict, ops: dict) -> dict:
    out = {'id': message.id, 'role': message.role, 'text': message.text, 'createdAt': message.created_at, 'status': 'done'}
    if message.role == 'user':
        return out
    job = jobs.get(message.job_id)
    payload = message.payload or {}
    if not payload.get('reply'):
        if job and job.status in ACTIVE:
            return {**out, 'status': 'pending', 'progress': (job.progress or {}).get('message', '')}
        return {**out, 'status': 'failed', 'error': (job.error if job else '') or 'The assistant did not answer. Ask again.'}
    reply = payload['reply']
    codes = set(reply.get('caseCodes', [])) | {c for a in reply.get('actions', []) for c in a.get('caseCodes', [])}
    cases = _cases_by_code(db, message.project_id, sorted(codes))
    actions = [{**{k: a.get(k) for k in ('kind', 'title', 'reviewAction', 'comment', 'instruction', 'exportFormat', 'exportStatus',
                                          'module', 'page')},
                'state': a.get('state', 'proposed'), 'result': a.get('result', ''),
                'cases': [_case_ref(cases[c], endpoint_ids) for c in a.get('caseCodes', []) if c in cases]}
               for a in reply.get('actions', [])]
    return {**out, 'text': reply.get('answer', ''),
            'cases': [_case_ref(cases[c], endpoint_ids) for c in reply.get('caseCodes', []) if c in cases],
            'actions': actions, 'drafts': [_draft_json(d, ops) for d in payload.get('drafts', [])],
            'draftError': payload.get('draftError', ''), 'followUps': reply.get('followUps', []),
            'models': (job.progress or {}).get('models', []) if job else []}


def _conversation(db: DbSession, project_id: str, user: User) -> list[AssistantMessage]:
    return db.scalars(select(AssistantMessage).where(AssistantMessage.project_id == project_id, AssistantMessage.user_id == user.id)
                      .order_by(AssistantMessage.created_at)).all()


def conversation_json(db: DbSession, project_id: str, user: User) -> dict:
    messages = _conversation(db, project_id, user)
    job_ids = [m.job_id for m in messages if m.job_id]
    jobs = {j.id: j for j in db.scalars(select(Job).where(Job.id.in_(job_ids)))} if job_ids else {}
    spec = current_spec(db, project_id)
    ops = {e.operation_id: e for e in db.scalars(select(Endpoint).where(Endpoint.spec_id == spec.id))} if spec else {}
    endpoint_ids = {(e.method, e.path): e.id for e in ops.values()}
    return {'messages': [message_json(db, m, jobs, endpoint_ids, ops) for m in messages],
            'helperConnected': helper_state(db, user.id)['connected']}


@router.get('')
def conversation(project_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    return conversation_json(db, project_id, user)


@router.post('/messages')
def ask(project_id: str, body: MessageInput, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, member = membership(db, project_id, user)
    if not helper_state(db, user.id)['connected']:
        raise HTTPException(409, 'Your Local Helper is not connected. Start it on your computer to use the assistant.')
    earlier = _conversation(db, project_id, user)
    jobs = {j.id: j for j in db.scalars(select(Job).where(Job.id.in_([m.job_id for m in earlier if m.job_id])))}
    if any(m.role == 'assistant' and not (m.payload or {}).get('reply') and m.job_id in jobs and jobs[m.job_id].status in ACTIVE
           for m in earlier):
        raise HTTPException(409, 'The assistant is still answering your last message.')
    history = [{'role': m.role, 'text': (m.payload or {}).get('reply', {}).get('answer', '') if m.role == 'assistant' else m.text}
               for m in earlier[-HISTORY:]]
    context = {k: str(v)[:200] for k, v in body.context.items() if k in ('page', 'area', 'caseCode', 'endpoint')}
    question = AssistantMessage(project_id=project_id, user_id=user.id, role='user', text=body.text.strip(), context=context)
    db.add(question)
    db.flush()
    answer = AssistantMessage(project_id=project_id, user_id=user.id, role='assistant', created_at=time.time() + 0.001)
    db.add(answer)
    db.flush()
    job = Job(project_id=project_id, kind=ASSISTANT_KIND, requested_by=user.id,
              input={'messageId': answer.id, 'question': question.text, 'history': history, 'context': context,
                     'user': {'name': user.name, 'role': member.role}},
              progress={'message': 'Waiting for your Local Helper', 'percent': 0})
    db.add(job)
    db.flush()
    answer.job_id = job.id
    db.commit()
    return conversation_json(db, project_id, user)


@router.delete('/messages')
def clear(project_id: str, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    for message in _conversation(db, project_id, user):
        job = db.get(Job, message.job_id) if message.job_id else None
        if job and job.status in ACTIVE:
            job.status, job.finished_at, job.lease_until, job.error = 'cancelled', time.time(), 0, 'Conversation cleared'
    db.execute(delete(AssistantMessage).where(AssistantMessage.project_id == project_id, AssistantMessage.user_id == user.id))
    db.commit()
    return conversation_json(db, project_id, user)


def store_reply(db: DbSession, job: Job, user: User, result: dict):
    """The helper's answer: kept on the assistant message; actions and drafts wait for the user."""
    try:
        parsed = AssistantResult.model_validate(result).model_dump()
    except ValidationError as exc:
        raise HTTPException(400, 'The assistant answer does not match the expected format: ' + str(exc)[:500]) from exc
    message = db.get(AssistantMessage, job.input.get('messageId'))
    if not message or message.job_id != job.id:
        return  # the conversation was cleared meanwhile
    reply = parsed['reply']
    reply['caseCodes'] = reply['caseCodes'] + CODE_IN_TEXT.findall(reply['answer'])  # every code the answer mentions is a link
    known = _cases_by_code(db, job.project_id, reply['caseCodes'] + [c for a in reply['actions'] for c in a['caseCodes']])
    reply['caseCodes'] = [c for c in dict.fromkeys(reply['caseCodes']) if c in known]
    for action in reply['actions']:
        action['caseCodes'] = [c for c in dict.fromkeys(action['caseCodes']) if c in known]
        action['state'] = 'proposed'
    message.payload = {'reply': reply, 'drafts': [{**d, 'state': 'pending'} for d in parsed['drafts']],
                       'draftError': parsed['draftError']}


def _message(db: DbSession, project_id: str, message_id: str, user: User) -> AssistantMessage:
    message = db.get(AssistantMessage, message_id)
    if not message or message.project_id != project_id or message.user_id != user.id or not (message.payload or {}).get('reply'):
        raise HTTPException(404, 'Message not found.')
    return message


def _save(message: AssistantMessage, payload: dict):
    message.payload = {**payload}  # a new dict, so the JSON column is written


@router.post('/messages/{message_id}/actions/{index}')
def confirm_action(project_id: str, message_id: str, index: int, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, _ = membership(db, project_id, user)
    message = _message(db, project_id, message_id, user)
    payload = copy.deepcopy(message.payload)  # changed in place below, so never the loaded value
    actions = payload['reply']['actions']
    if not 0 <= index < len(actions) or actions[index].get('state') != 'proposed':
        raise HTTPException(409, 'This action was already done or dismissed.')
    action = dict(actions[index])
    cases = list(_cases_by_code(db, project_id, action['caseCodes']).values())
    extra = {}
    if action['kind'] == 'review':
        from .unit import ReviewAction, review_cases
        if not cases or not action.get('reviewAction'):
            raise HTTPException(400, 'The cases of this action no longer exist.')
        done = review_cases(project_id, ReviewAction(caseIds=[c.id for c in cases], action=action['reviewAction'],
                                                     comment=action.get('comment', '')), db, user)
        result = f"{done['updated']} test case{'s' if done['updated'] != 1 else ''} {STATUS_WORDS[action['reviewAction']]}."
    elif action['kind'] == 'regenerate':
        from .cases import RegenerateInput, regenerate
        if not cases:
            raise HTTPException(400, 'The case of this action no longer exists.')
        regenerate(project_id, cases[0].id, RegenerateInput(instruction=action.get('instruction', '')), db, user)
        result = f'Regenerating {_code(cases[0])} on your computer. It goes back to review when it is done.'
    elif action['kind'] == 'fill_gaps':
        from .flows import fill_gaps
        fill_gaps(project_id, db, user)
        result = 'Filling the coverage gaps on your computer. Watch the Flow test cases page.'
    elif action['kind'] == 'export':
        module, fmt = action.get('module') or 'all', action.get('exportFormat') or 'xlsx'
        if fmt == 'csv' and module == 'all':
            module = 'flow'
        extra['download'] = f"/api/projects/{project_id}/export?module={module}&format={fmt}&status={action.get('exportStatus') or 'all'}"
        result = 'Download started.'
    else:
        extra['navigate'] = action.get('page') or 'flows'
        result = 'Opened.'
    message = _message(db, project_id, message_id, user)
    payload = copy.deepcopy(message.payload)  # changed in place below, so never the loaded value
    payload['reply']['actions'][index] = {**payload['reply']['actions'][index], 'state': 'done', 'result': result}
    _save(message, payload)
    record(db, project, user, 'assistant.action', f'{user.name} confirmed an assistant action: {action["title"]}')
    db.commit()
    return {**conversation_json(db, project_id, user), **extra}


@router.post('/messages/{message_id}/actions/{index}/dismiss')
def dismiss_action(project_id: str, message_id: str, index: int, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    message = _message(db, project_id, message_id, user)
    payload = copy.deepcopy(message.payload)  # changed in place below, so never the loaded value
    if not 0 <= index < len(payload['reply']['actions']):
        raise HTTPException(404, 'Action not found.')
    payload['reply']['actions'][index] = {**payload['reply']['actions'][index], 'state': 'dismissed'}
    _save(message, payload)
    db.commit()
    return conversation_json(db, project_id, user)


@router.post('/messages/{message_id}/drafts/{index}/accept')
def accept_draft(project_id: str, message_id: str, index: int, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    project, _ = membership(db, project_id, user)
    message = _message(db, project_id, message_id, user)
    payload = copy.deepcopy(message.payload)  # changed in place below, so never the loaded value
    drafts = payload.get('drafts', [])
    if not 0 <= index < len(drafts) or drafts[index].get('state') != 'pending':
        raise HTTPException(409, 'This draft was already added or discarded.')
    spec = current_spec(db, project_id)
    analysis = db.get(FlowAnalysis, project_id)
    if not spec or not analysis:
        raise HTTPException(409, 'Design the flows of this project first.')
    endpoints = [e.details for e in db.scalars(select(Endpoint).where(Endpoint.spec_id == spec.id))]
    by_id = {e['operationId']: e for e in endpoints}
    draft = drafts[index]
    outline, flow = draft['outline'], draft['flow']
    # Checked again here: the spec may have changed since the draft was made.
    problems = validate_plan([outline], endpoints) + validate_detailed_flow(flow, by_id)
    if [s['operationId'] for s in flow['steps']] != [s['operationId'] for s in outline['steps']]:
        problems.append('The detailed steps do not follow the outline.')
    if problems:
        raise HTTPException(400, 'The draft no longer passes the checks: ' + '; '.join(problems[:5]))
    areas = {a['name'] for a in (analysis.domain or {}).get('areas', [])}
    area = draft.get('area') if draft.get('area') in areas else JOURNEYS
    from .flows import add_flow_case, _outlines
    case = add_flow_case(db, project_id, user, outline, flow, area, spec.version, None, [], source='assistant', requestedBy=user.name)
    db.flush()
    analysis.gaps = [r['id'] for r in gaps(analysis.requirements or [], _outlines(db, project_id))]
    drafts[index] = {**draft, 'state': 'added', 'caseCode': _code(case)}
    _save(message, {**payload, 'drafts': drafts})
    record(db, project, user, 'flows.case_requested', f'{user.name} added {_code(case)} {case.title} through the assistant', caseId=case.id)
    db.commit()
    return conversation_json(db, project_id, user)


@router.post('/messages/{message_id}/drafts/{index}/discard')
def discard_draft(project_id: str, message_id: str, index: int, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    membership(db, project_id, user)
    message = _message(db, project_id, message_id, user)
    payload = copy.deepcopy(message.payload)  # changed in place below, so never the loaded value
    drafts = payload.get('drafts', [])
    if not 0 <= index < len(drafts):
        raise HTTPException(404, 'Draft not found.')
    drafts[index] = {**drafts[index], 'state': 'discarded'}
    _save(message, {**payload, 'drafts': drafts})
    db.commit()
    return conversation_json(db, project_id, user)

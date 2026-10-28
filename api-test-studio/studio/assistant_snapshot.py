"""The project as small text files for the assistant: an index to search, one file per flow, and the analysis.

Counts the assistant reports come from `stats.md`, which the portal computes, so numbers never depend on the model
counting search results.
"""
import re
import time
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from contracts.flows import JOURNEYS

from .models import Activity, Endpoint, FlowAnalysis, Project, TestCase, User

STATUS = {'in_review': 'In review', 'approved': 'Approved', 'needs_changes': 'Needs changes', 'rejected': 'Rejected'}
FLOW_TYPE = {'happy_path': 'Happy path', 'alternate_path': 'Alternate path', 'negative': 'Negative',
             'state_transition': 'State transition', 'role_based': 'Role based', 'end_to_end': 'End to end',
             'data_integrity': 'Data integrity'}
EXTRA = 'Additional coverage'
MAX_ACTIVITY = 80


def case_code(case: TestCase) -> str:
    return f'TC-{case.number:04d}'


def area_name(case: TestCase) -> str:
    area = (case.content or {}).get('area') or ''
    return EXTRA if not area or area == 'Coverage gaps' else area


def _slug(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:60] or 'other'


def _line(*cells) -> str:
    return ' | '.join(str(c).replace('|', '/').replace('\n', ' ') for c in cells)


def _flow_file(case: TestCase, ops: dict[str, Endpoint], people: dict) -> str:
    c = case.content or {}
    lines = [f'# {case_code(case)} {case.title}', '',
             f'- Area: {area_name(case)} · Type: {FLOW_TYPE.get(case.category, case.category)} · Status: {STATUS.get(case.status, case.status)}'
             f' · Priority: {case.priority}',
             f"- Created by: {people.get(case.created_by, 'unknown')}" + (' (requested through the assistant)' if c.get('source') == 'assistant' else '')]
    if case.needs_confirmation:
        lines.append(f"- Needs confirmation: {c.get('confirmationNote') or 'results the contract does not state exactly'}")
    lines += ['', '## Goal', c.get('objective') or c.get('goal') or '', '', '## Steps']
    for i, step in enumerate(c.get('steps', []), 1):
        op = ops.get(step.get('operationId'))
        where = f'{op.method} {op.path}' if op else step.get('operationId', '?')
        expected = (step.get('expected') or {}).get('status')
        saves = ', '.join(cap['name'] for cap in step.get('captures', []))
        lines.append(f"{i}. {step.get('key', '')} {where} → {expected} — {step.get('purpose', '')}" + (f' (saves {saves})' if saves else ''))
    if c.get('covers'):
        lines += ['', '## Covers', ', '.join(c['covers'])]
    if case.findings:
        lines += ['', '## AI review notes'] + [f"- [{f.get('severity')}] {f.get('issue')} — {f.get('suggestion', '')}" for f in case.findings]
    if case.review_comment:
        lines += ['', '## Reviewer comment', case.review_comment]
    return '\n'.join(lines) + '\n'


def build_snapshot(db: DbSession, project_id: str, user: User) -> dict:
    project = db.get(Project, project_id)
    from .routers.projects import current_spec
    spec = current_spec(db, project_id)
    endpoints = db.scalars(select(Endpoint).where(Endpoint.spec_id == spec.id).order_by(Endpoint.position)).all() if spec else []
    ops = {e.operation_id: e for e in endpoints}
    cases = db.scalars(select(TestCase).where(TestCase.project_id == project_id).order_by(TestCase.number)).all()
    people = dict(db.execute(select(User.id, User.name)).all())
    analysis = db.get(FlowAnalysis, project_id)
    flows = [c for c in cases if c.module == 'flow']
    units = [c for c in cases if c.module == 'unit']
    roles = [c for c in cases if c.module == 'role']
    files: dict[str, str] = {}

    files['README.md'] = '\n'.join([
        f'# {project.name}: project snapshot', '',
        f"Taken {time.strftime('%Y-%m-%d %H:%M')}. API spec: {spec.title if spec else 'none'} "
        f"{('v' + spec.api_version) if spec and spec.api_version else ''} ({len(endpoints)} operations).", '',
        'Files:',
        '- stats.md: counts by module, status, area and type. Use these for every number you report.',
        '- flows/index.md: one line per flow test case: code | title | area | type | status | priority | operations.',
        '- flows/<area>/<code>.md: one file per flow with steps, expected statuses, covers and review notes.',
        '- unit/index.md: one line per unit test case. roles/index.md: role-based test cases.',
        '- analysis/domain.md: what the API does, business areas, entities, status lifecycles, business rules.',
        '- analysis/processes.md: end-to-end business processes and whether a flow covers each one.',
        '- analysis/coverage.md: coverage per category and every requirement that is not covered.',
        '- endpoints.md: every operation (operationId METHOD path summary).',
        '- activity.md: recent activity in the project.']) + '\n'

    stats = ['# Counts', '', '## Test cases by module and status']
    for module, items in (('Unit', units), ('Flow', flows), ('Role', roles)):
        by_status = Counter(STATUS.get(c.status, c.status) for c in items)
        stats.append(f"- {module}: {len(items)} total" + ''.join(f', {n} {s}' for s, n in by_status.most_common()))
    stats += ['', '## Flows by business area and type']
    by_area: dict[str, list[TestCase]] = {}
    for case in flows:
        by_area.setdefault(area_name(case), []).append(case)
    for area, items in by_area.items():
        types = Counter(FLOW_TYPE.get(c.category, c.category) for c in items)
        approved = sum(c.status == 'approved' for c in items)
        stats.append(f"- {area}: {len(items)} flows ({approved} approved): " + ', '.join(f'{t} {n}' for t, n in types.most_common()))
    stats += ['', f'- Flows that need confirmation: {sum(c.needs_confirmation for c in flows)}',
              f'- Flows with AI review notes: {sum(bool(c.findings) for c in flows)}',
              f'- Unit cases that need confirmation: {sum(c.needs_confirmation for c in units)}']
    files['stats.md'] = '\n'.join(stats) + '\n'

    index = ['# Flow test cases', '', _line('code', 'title', 'area', 'type', 'status', 'priority', 'operations')]
    for case in flows:
        steps = [s.get('operationId', '') for s in (case.content or {}).get('steps', [])]
        index.append(_line(case_code(case), case.title, area_name(case), FLOW_TYPE.get(case.category, case.category),
                           STATUS.get(case.status, case.status), case.priority, ' > '.join(steps)))
        files[f'flows/{_slug(area_name(case))}/{case_code(case)}.md'] = _flow_file(case, ops, people)
    files['flows/index.md'] = '\n'.join(index) + '\n'

    unit = ['# Unit test cases', '', _line('code', 'endpoint', 'category', 'priority', 'status', 'title', 'expected status')]
    for case in units:
        expected = ((case.content or {}).get('expected') or {}).get('status')
        unit.append(_line(case_code(case), f'{case.method} {case.path}', case.category, case.priority,
                          STATUS.get(case.status, case.status), case.title, expected))
    files['unit/index.md'] = '\n'.join(unit) + '\n'
    files['roles/index.md'] = '\n'.join(['# Role-based test cases', '', _line('code', 'endpoint', 'kind', 'status', 'title')] +
                                        [_line(case_code(c), f'{c.method} {c.path}', c.category, STATUS.get(c.status, c.status), c.title)
                                         for c in roles]) + '\n'
    files['endpoints.md'] = '\n'.join(['# Operations', ''] + [_line(e.operation_id, e.method, e.path, e.summary) for e in endpoints]) + '\n'

    if analysis and analysis.domain:
        domain = analysis.domain
        missing = set(analysis.gaps or [])
        doc = ['# How the API works', '', domain.get('summary', ''), '', '## Business areas']
        doc += [f"- {a['name']}: {a.get('description', '')} ({len(a['operations'])} operations: {', '.join(a['operations'])})"
                for a in domain.get('areas', [])]
        doc += ['', '## Entities'] + [f"- {e['name']}: {e.get('description', '')} States: {', '.join(e.get('states', [])) or '-'}"
                                      for e in domain.get('entities', [])]
        doc += ['', '## Status changes'] + [f"- {t['entity']}: {t['fromState']} -> {t['toState']} by {t['operationId']}"
                                           for t in domain.get('transitions', [])]
        doc += ['', '## Business rules'] + [f"- {r['key']} ({r.get('kind', 'other')}): {r['rule']}"
                                           + (' [covered]' if f"rule:{r['key']}" not in missing else ' [NOT covered]')
                                           for r in domain.get('businessRules', [])]
        doc += ['', '## Assumptions the analysis made'] + [f'- {a}' for a in domain.get('assumptions', [])]
        files['analysis/domain.md'] = '\n'.join(doc) + '\n'
        processes = ['# Business processes (end to end)', '']
        for p in domain.get('processes', []):
            state = 'covered' if f"process:{p['key']}" not in missing else 'NOT covered: no end-to-end flow yet'
            processes.append(f"- {p['key']} {p['name']} [{state}]: {' > '.join(p['steps'])}. Outcome: {p.get('outcome', '')}")
        if not domain.get('processes'):
            processes.append('No business processes have been listed yet. "Add end-to-end journeys" finds them.')
        files['analysis/processes.md'] = '\n'.join(processes) + '\n'
        required = analysis.requirements or []
        coverage = ['# Coverage', '', f'{len(required) - len(missing)} of {len(required)} requirements covered.', '']
        for category, items in Counter(r['category'] for r in required).items():
            open_items = [r for r in required if r['category'] == category and r['id'] in missing]
            coverage.append(f'- {category}: {items - len(open_items)} of {items} covered')
        coverage += ['', '## Not covered'] + [f"- {r['id']}: {r['description']}" for r in required if r['id'] in missing]
        files['analysis/coverage.md'] = '\n'.join(coverage) + '\n'

    recent = db.scalars(select(Activity).where(Activity.project_id == project_id).order_by(Activity.created_at.desc()).limit(MAX_ACTIVITY)).all()
    files['activity.md'] = '\n'.join(['# Recent activity (newest first)', ''] +
                                     [f"- {time.strftime('%Y-%m-%d %H:%M', time.localtime(a.created_at))} {a.summary}" for a in recent]) + '\n'

    design = None
    if analysis and analysis.domain and spec:
        design = {'api': {'title': spec.title, 'version': spec.api_version, 'description': spec.description[:2000],
                          'servers': spec.servers, 'securitySchemes': spec.security_schemes},
                  'endpoints': [e.details for e in endpoints], 'domain': analysis.domain,
                  'outlines': [c.content['outline'] for c in flows if (c.content or {}).get('outline')]}
    summary = {'name': project.name, 'operations': len(endpoints), 'unitCases': len(units), 'flows': len(flows),
               'roleCases': len(roles), 'areas': [a['name'] for a in (analysis.domain.get('areas', []) if analysis and analysis.domain else [])],
               'journeysArea': JOURNEYS}
    return {'files': files, 'project': summary, 'design': design}

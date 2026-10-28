"""Role-based test cases: the permission model built from the project's roles file, and the role cases per endpoint."""
import re
from typing import Literal

from pydantic import Field

from . import Strict
from .unit import CaseReview, Expected, Priority, RequestSpec

Access = Literal['allowed', 'own', 'denied', 'unknown']
RoleCaseKind = Literal['allowed', 'denied', 'ownership', 'hidden_data', 'protected_field']
ACCESS_LISTS = ('allowed', 'own', 'denied', 'unknown')


# --- access-control-analyst output ----------------------------------------------------------------

class Role(Strict):
    name: str = Field(min_length=1, max_length=60, description='Role name as the roles file calls it, e.g. "Lab Technician"')
    description: str = Field(default='', max_length=500)
    users: int = Field(default=1, ge=1, le=3, description='Test users needed; 2 when ownership checks need a second user')
    source: Literal['file', 'spec', 'both'] = 'file'


class OperationAccess(Strict):
    operationId: str
    allowed: list[str] = Field(default_factory=list, description='Roles that may call it for any record')
    own: list[str] = Field(default_factory=list, description='Roles that may call it only for their own records')
    denied: list[str] = Field(default_factory=list, description='Roles that must be refused')
    unknown: list[str] = Field(default_factory=list, description='Roles the file and the spec do not decide')
    evidence: str = Field(default='', max_length=400, description='The roles-file or spec text the decision is based on')
    source: Literal['file', 'spec', 'both', 'inferred'] = 'inferred'


class AccessRule(Strict):
    rule: str = Field(max_length=500, description='e.g. "Customers see only PUBLISHED documents"')
    kind: Literal['ownership', 'hidden_data', 'protected_field', 'other']
    operations: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    source: str = Field(default='', max_length=300)


class AccessModel(Strict):
    summary: str = Field(max_length=1500, description='How access works in this API, in two to four sentences')
    roles: list[Role] = Field(min_length=1, max_length=30)
    operations: list[OperationAccess] = Field(default_factory=list, max_length=600)
    rules: list[AccessRule] = Field(default_factory=list, max_length=150)
    systemCallers: list[str] = Field(default_factory=list, max_length=20,
                                     description='Non-user callers such as "Payment gateway (signed webhook)"')
    missingFromFile: list[str] = Field(default_factory=list, max_length=30,
                                       description='Roles the spec mentions that the roles file does not list')
    questions: list[str] = Field(default_factory=list, max_length=40, description='What the QA should confirm')


class AccessAnalysisResult(Strict):
    model: AccessModel


# --- role-case-designer output ---------------------------------------------------------------------

class RoleTestCase(Strict):
    key: str = Field(pattern=r'^R\d{2,3}$', description='R01, R02, ... unique within the endpoint')
    title: str = Field(min_length=3, max_length=200)
    objective: str = Field(max_length=1000)
    kind: RoleCaseKind
    roles: list[str] = Field(min_length=1, max_length=30, description='The case runs once per listed role')
    userSlot: Literal['first', 'second'] = Field(default='first', description='"second": another user of the same role')
    priority: Priority
    preconditions: list[str] = Field(default_factory=list, max_length=20,
                                     description='Setup, naming the role that does it, e.g. "As Lab Technician: add a DRAFT result"')
    request: RequestSpec
    expected: Expected
    verifyUnchanged: str = Field(default='', max_length=500,
                                 description='After a refused request: how to prove nothing changed (read back as a permitted role)')
    testData: str = Field(default='', max_length=1500)
    cleanup: list[str] = Field(default_factory=list, max_length=10)
    needsConfirmation: bool = False
    confirmationNote: str = Field(default='', max_length=500)


class RoleCaseSet(Strict):
    cases: list[RoleTestCase] = Field(min_length=1, max_length=80)


class RoleEndpointResult(Strict):
    """Sent by the helper after each endpoint's role cases are finished."""
    endpointId: str
    cases: list[RoleTestCase] = Field(default_factory=list)
    review: CaseReview | None = None
    error: str = ''


# --- Normalising the analysis --------------------------------------------------------------------------

def env_prefix(role: str) -> str:
    """'Lab Technician' -> 'LAB_TECHNICIAN': how the framework's credentials file is expected to name a role."""
    return re.sub(r'[^A-Z0-9]+', '_', role.upper()).strip('_') or 'ROLE'


def normalise(model: dict, operation_ids: list[str]) -> dict:
    """Every operation once, every role in exactly one list, unknown names dropped. Code, not trust."""
    names = [r['name'] for r in model['roles']]
    canonical = {n.casefold(): n for n in names}
    by_op = {}
    for row in model.get('operations', []):
        if row['operationId'] in operation_ids and row['operationId'] not in by_op:
            by_op[row['operationId']] = row
    rows = []
    for op in operation_ids:
        row = by_op.get(op, {'operationId': op, 'evidence': '', 'source': 'inferred'})
        placed, out = {}, {'operationId': op, 'evidence': row.get('evidence', ''), 'source': row.get('source', 'inferred')}
        for access in ('denied', 'own', 'allowed'):  # a role listed twice keeps the strictest answer
            for name in row.get(access, []):
                role = canonical.get(str(name).casefold())
                if role and role not in placed:
                    placed[role] = access
        for access in ACCESS_LISTS:
            out[access] = [n for n in names if placed.get(n, 'unknown') == access]
        rows.append(out)
    rules = [{**r, 'roles': [canonical[n.casefold()] for n in r.get('roles', []) if n.casefold() in canonical],
              'operations': [o for o in r.get('operations', []) if o in operation_ids]} for r in model.get('rules', [])]
    return {**model, 'operations': rows, 'rules': rules}


def access_row(model: dict, operation_id: str) -> dict | None:
    return next((row for row in model.get('operations', []) if row['operationId'] == operation_id), None)


# --- Coverage of one endpoint, computed from the cases themselves ---------------------------------------

def role_requirements(model: dict, operation_id: str) -> list[dict]:
    row = access_row(model, operation_id)
    if not row:
        return []
    items = []
    for role in row['allowed']:
        items.append({'id': f'role:{operation_id}:{role}:allowed', 'category': 'allowed', 'role': role,
                      'description': f'{role} can call it and succeeds'})
    for role in row['own']:
        items.append({'id': f'role:{operation_id}:{role}:own', 'category': 'ownership', 'role': role,
                      'description': f'{role} succeeds on their own records and is refused on another user\'s'})
    for role in row['denied']:
        items.append({'id': f'role:{operation_id}:{role}:denied', 'category': 'denied', 'role': role,
                      'description': f'{role} is refused and nothing changes'})
    for i, rule in enumerate(model.get('rules', []), 1):
        if operation_id in rule.get('operations', []) and rule['kind'] in ('hidden_data', 'protected_field'):
            items.append({'id': f'rule:{operation_id}:{i}', 'category': rule['kind'], 'role': ', '.join(rule.get('roles', [])),
                          'description': rule['rule']})
    return items


def _status(case: dict) -> int:
    return int((case.get('expected') or {}).get('status') or 0)


def covered(requirement: dict, cases: list[dict]) -> bool:
    role, category = requirement.get('role', ''), requirement['category']
    ok = lambda c: 200 <= _status(c) < 300  # noqa: E731
    refused = lambda c: 400 <= _status(c) < 500  # noqa: E731
    mine = [c for c in cases if role in c.get('roles', [])]
    if category == 'allowed':
        return any(c['kind'] == 'allowed' and ok(c) for c in mine)
    if category == 'denied':
        return any(c['kind'] == 'denied' and refused(c) for c in mine)
    if category == 'ownership':
        return (any(c['kind'] == 'allowed' and ok(c) and c.get('userSlot', 'first') == 'first' for c in mine)
                and any(c['kind'] == 'ownership' and refused(c) and c.get('userSlot') == 'second' for c in mine))
    return any(c['kind'] == category for c in cases)


def contributes(requirement: dict, case: dict) -> bool:
    """Whether a case is part of the proof of a requirement (an ownership check needs two cases together)."""
    role, category = requirement.get('role', ''), requirement['category']
    if category == 'ownership':
        return role in case.get('roles', []) and case['kind'] in ('allowed', 'ownership')
    return covered(requirement, [case])


def role_gaps(requirements: list[dict], cases: list[dict]) -> list[dict]:
    return [r for r in requirements if not covered(r, cases)]


def validate_role_cases(cases: list[dict], endpoint: dict, roles: list[str]) -> list[str]:
    """Problems the designer must fix: unknown roles, undocumented statuses, a refusal expected to succeed."""
    from .checks import credential_header_problems, placeholder_problems
    problems, known, documented = [], set(roles), set(endpoint.get('responses', {}))
    for case in cases:
        where = case['key']
        request = case.get('request') or {}
        problems += [f'{where}: {p}' for p in credential_header_problems(request) + placeholder_problems(request)]
        for role in case.get('roles', []):
            if role not in known:
                problems.append(f'{where}: role "{role}" is not one of the project roles ({", ".join(roles)}).')
        status = _status(case)
        if status and str(status) not in documented:
            problems.append(f'{where}: status {status} is not documented for this operation.')
        if case['kind'] in ('denied', 'ownership') and status and not 400 <= status < 500:
            problems.append(f'{where}: a {case["kind"]} case must expect a 4xx refusal, not {status}.')
        if case['kind'] == 'allowed' and status and not 200 <= status < 300:
            problems.append(f'{where}: an allowed case must expect a 2xx status, not {status}.')
    return problems

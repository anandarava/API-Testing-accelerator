"""Flow test cases: compact API context, dependency evidence, coverage requirements and validation."""
import re
from typing import Literal

from pydantic import Field

from . import Strict
from .unit import Expected, Priority, RequestSpec

FlowType = Literal['happy_path', 'alternate_path', 'negative', 'state_transition', 'role_based', 'end_to_end', 'data_integrity']


# --- Agent outputs ---------------------------------------------------------------------------------

class Entity(Strict):
    name: str = Field(max_length=80)
    description: str = Field(max_length=600)
    identifier: str = Field(default='', max_length=80, description='Field that identifies it, e.g. id or orderId')
    operations: list[str] = Field(default_factory=list, description='operationIds that create, read, change or delete it')
    states: list[str] = Field(default_factory=list, description='Lifecycle states, e.g. available, pending, sold')
    lockedStates: list[str] = Field(default_factory=list, max_length=20,
                                    description='States in which the record can no longer be changed (final or locked), '
                                                'e.g. COMPLETED, CANCELLED, SIGNED')


class Transition(Strict):
    entity: str = Field(max_length=80)
    fromState: str = Field(max_length=60)
    toState: str = Field(max_length=60)
    operationId: str
    condition: str = Field(default='', max_length=400)


RuleKind = Literal['validation', 'uniqueness', 'state', 'ownership', 'role', 'idempotency', 'concurrency', 'time',
                   'money', 'side_effect', 'external', 'other']


class BusinessRule(Strict):
    key: str = Field(pattern=r'^R\d{1,3}$')
    rule: str = Field(max_length=500)
    source: str = Field(max_length=300, description='Where the contract states it')
    operations: list[str] = Field(default_factory=list)
    kind: RuleKind = Field(default='other', description='Which testing technique the rule needs')
    needsSupport: str = Field(default='', max_length=300,
                              description='Test support the rule needs to be tested, e.g. a test clock or a webhook '
                                          'signing secret; empty when none')


class SideEffect(Strict):
    operationId: str
    effect: str = Field(max_length=300, description='What else changes, e.g. "a notification is created for the owner"')
    verifyWith: str = Field(default='', description='operationId that shows the effect, empty when none does')


class Area(Strict):
    name: str = Field(min_length=1, max_length=80, description='Business area, e.g. Accounts, Orders, Billing')
    description: str = Field(default='', max_length=500)
    operations: list[str] = Field(min_length=1, description='operationIds that belong to this area')


class DomainAnalysis(Strict):
    """What the domain analyst returns."""
    summary: str = Field(max_length=3000, description='What the API is for, in business terms')
    entities: list[Entity] = Field(default_factory=list, max_length=200)
    relationships: list[str] = Field(default_factory=list, max_length=300, description='e.g. "An order references one customer"')
    transitions: list[Transition] = Field(default_factory=list, max_length=400)
    businessRules: list[BusinessRule] = Field(default_factory=list, max_length=400)
    areas: list[Area] = Field(default_factory=list, max_length=40,
                              description='Business areas that together contain every operation exactly once')
    sideEffects: list[SideEffect] = Field(default_factory=list, max_length=150)
    assumptions: list[str] = Field(default_factory=list, max_length=60)


class BusinessProcess(Strict):
    """One end-to-end business process: what a real user or system does from start to outcome, across areas."""
    key: str = Field(pattern=r'^P\d{1,3}$')
    name: str = Field(min_length=3, max_length=120, description='e.g. "Order fulfilled from inventory and invoiced"')
    actors: list[str] = Field(default_factory=list, max_length=8, description='Who takes part, e.g. Customer, Agent, Administrator')
    description: str = Field(default='', max_length=600, description='What happens, start to finish, in business terms')
    steps: list[str] = Field(min_length=2, max_length=20,
                             description='operationIds of the key calls, in the order the process makes them')
    outcome: str = Field(default='', max_length=300, description='The end state that proves the process worked')


class ProcessCatalog(Strict):
    processes: list[BusinessProcess] = Field(min_length=1, max_length=80)


class DomainModel(DomainAnalysis):
    processes: list[BusinessProcess] = Field(default_factory=list, max_length=80,
                                             description='End-to-end business processes, found after the areas are known')


class StepInput(Strict):
    target: str = Field(max_length=120, description='Where the value goes: path.orderId, query.status, body.customerId, body.items[0].sku')
    source: str = Field(max_length=200, description='steps.S1.orderId (a capture of an earlier step), env.NAME, or literal:<value>')


class Capture(Strict):
    name: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,40}$')
    path: str = Field(max_length=120, description='JSON path in the response, e.g. $.id')


class OutlineStep(Strict):
    key: str = Field(pattern=r'^S\d{1,3}$')
    operationId: str
    purpose: str = Field(max_length=300)
    expectedStatus: int = Field(ge=100, le=599)
    inputs: list[StepInput] = Field(default_factory=list)
    captures: list[Capture] = Field(default_factory=list)


class FlowOutline(Strict):
    key: str = Field(pattern=r'^F\d{2,3}$')
    title: str = Field(min_length=3, max_length=200)
    type: FlowType
    goal: str = Field(max_length=600, description='The business outcome the flow proves')
    priority: Priority
    steps: list[OutlineStep] = Field(min_length=2, description='As many steps as the journey needs')
    covers: list[str] = Field(default_factory=list, description='Coverage requirement ids this flow satisfies')
    needsConfirmation: bool = False
    confirmationNote: str = Field(default='', max_length=500)


class FlowPlan(Strict):
    flows: list[FlowOutline] = Field(min_length=1, max_length=80)


class FlowStep(Strict):
    key: str = Field(pattern=r'^S\d{1,3}$')
    operationId: str
    purpose: str = Field(max_length=300)
    request: RequestSpec
    expected: Expected
    captures: list[Capture] = Field(default_factory=list)


class FlowCaseDraft(Strict):
    flowKey: str = Field(pattern=r'^F\d{2,3}$')
    title: str = Field(min_length=3, max_length=200)
    objective: str = Field(max_length=1000)
    type: FlowType
    priority: Priority
    preconditions: list[str] = Field(default_factory=list, max_length=20)
    steps: list[FlowStep] = Field(min_length=2)
    testData: str = Field(default='', max_length=1500)
    cleanup: list[str] = Field(default_factory=list, max_length=20)
    needsConfirmation: bool = False
    confirmationNote: str = Field(default='', max_length=500)


class FlowCaseSet(Strict):
    flows: list[FlowCaseDraft] = Field(min_length=1, max_length=40)


class FlowFinding(Strict):
    flowKey: str = Field(description='Flow key the finding is about, or "plan" for missing flows')
    severity: Literal['blocker', 'major', 'minor']
    issue: str = Field(max_length=600, description='What is wrong, or for "plan": why the missing flow matters')
    suggestion: str = Field(default='', max_length=600, description='How to fix it')
    # Only for "plan" (a suggested new flow):
    title: str = Field(default='', max_length=120, description='Short name of the suggested flow')
    type: FlowType | None = Field(default=None, description='Type of the suggested flow')
    priority: Priority | None = None
    steps: list[str] = Field(default_factory=list, max_length=15, description='The suggested flow, one short step per item')


class FlowReview(Strict):
    verdict: Literal['ready', 'needs_attention']
    summary: str = Field(max_length=800, description='One or two sentences on the flows reviewed')
    strengths: list[str] = Field(default_factory=list, max_length=6, description='What the flows do well, a few words each')
    findings: list[FlowFinding] = Field(default_factory=list, max_length=60)


class FlowGroupProgress(Strict):
    """Where one design group (a business area, or the cross-area journeys) is in its pipeline."""
    name: str = Field(max_length=120)
    status: Literal['waiting', 'working', 'done', 'failed']
    step: str = Field(default='', max_length=200, description='What Claude is doing now, e.g. "reviewing"')
    flows: int = Field(default=0, ge=0, description='Flows written (working) or saved (done)')
    startedAt: float | None = None
    finishedAt: float | None = None


class FlowProgress(Strict):
    """Structured progress of a flows.generate job, shown as a stepper and an area table."""
    stage: Literal['analyze', 'design', 'coverage', 'done']
    operations: int = Field(default=0, ge=0)
    entities: int | None = None
    rules: int | None = None
    areas: int | None = None
    parallel: int = Field(default=1, ge=1)
    groups: list[FlowGroupProgress] = Field(default_factory=list, max_length=200)
    savedFlows: int = Field(default=0, ge=0)
    gapFlows: int | None = Field(default=None, description='Flows added to close coverage gaps')
    stageStartedAt: dict[str, float] = Field(default_factory=dict, max_length=4)


class FlowAnalysisResult(Strict):
    """Sent by the helper in stages so work is saved as it finishes.

    - `domain`: the domain analysis, before any flow is designed.
    - `processes`: business processes found for an existing design (adding end-to-end journeys).
    - `group`: the finished flows of one design group (a business area, or the cross-area journeys).
    - `final`: flows added by the combined coverage check, plus the overall review summary.
    """
    stage: Literal['domain', 'processes', 'group', 'final']
    group: str = Field(default='', max_length=120)
    domain: DomainModel | None = None
    processes: list[BusinessProcess] = Field(default_factory=list, max_length=80)
    dependencies: list[dict] = Field(default_factory=list)
    plan: list[FlowOutline] = Field(default_factory=list)
    flows: list[FlowCaseDraft] = Field(default_factory=list)
    review: FlowReview | None = None
    rounds: int = 1


JOURNEYS = 'Cross-area journeys'
_STEP_VALUE = re.compile(r'\{\{steps\.(S\d+)\.([A-Za-z][A-Za-z0-9_]*)\}\}')


def outline_from_steps(previous: dict | None, key: str, title: str, flow_type: str, priority: str, steps: list[dict]) -> dict:
    """Rebuild a flow's outline from its detailed steps after an edit, so coverage stays accurate."""
    locations = {'pathParams': 'path', 'query': 'query', 'headers': 'header', 'body': 'body'}
    outline_steps = []
    for step in steps:
        inputs = []
        request = step.get('request') or {}
        for field, prefix in locations.items():
            values = request.get(field)
            if isinstance(values, dict):
                for name, value in values.items():
                    match = _STEP_VALUE.search(str(value))
                    if match:
                        inputs.append({'target': f'{prefix}.{name}', 'source': f'steps.{match.group(1)}.{match.group(2)}'})
        outline_steps.append({'key': step['key'], 'operationId': step['operationId'], 'purpose': step.get('purpose', ''),
                              'expectedStatus': (step.get('expected') or {}).get('status') or 200, 'inputs': inputs,
                              'captures': step.get('captures', [])})
    base = previous or {}
    return {'key': key, 'title': title, 'type': flow_type, 'goal': base.get('goal', title), 'priority': priority,
            'steps': outline_steps, 'covers': base.get('covers', []), 'needsConfirmation': base.get('needsConfirmation', False),
            'confirmationNote': base.get('confirmationNote', '')}


def split_areas(domain: dict, endpoints: list[dict]) -> list[dict]:
    """Business areas from the domain analysis; operations it did not place are grouped by OpenAPI tag."""
    known = {ep['operationId'] for ep in endpoints}
    areas, placed = [], set()
    for area in domain.get('areas', []):
        ops = [op for op in area['operations'] if op in known and op not in placed]
        if ops:
            placed.update(ops)
            areas.append({'name': area['name'], 'description': area.get('description', ''), 'operations': ops})
    leftovers = {}
    for ep in endpoints:
        if ep['operationId'] not in placed:
            leftovers.setdefault((ep.get('tags') or ['Other'])[0], []).append(ep['operationId'])
    by_name = {a['name'].casefold(): a for a in areas}
    for tag, ops in leftovers.items():
        if tag.casefold() in by_name:
            by_name[tag.casefold()]['operations'] += ops
        else:
            areas.append({'name': tag, 'description': f'Operations tagged {tag}', 'operations': ops})
            by_name[tag.casefold()] = areas[-1]
    return areas


def relevant_requirements(required: list[dict], operations: set[str], domain: dict) -> list[dict]:
    """The coverage requirements a design group is responsible for."""
    transitions = {f"transition:{t['entity']}:{t['fromState']}->{t['toState']}": t['operationId'] for t in domain.get('transitions', [])}
    rules = {f"rule:{r['key']}": set(r.get('operations', [])) for r in domain.get('businessRules', [])}
    processes = {f"process:{p['key']}": set(p['steps']) for p in domain.get('processes', [])}
    out = []
    for item in required:
        rid = item['id']
        if rid.startswith(('op:', 'dep:')):
            keep = rid.split(':')[1] in operations
        elif rid in transitions:
            keep = transitions[rid] in operations
        elif rid in rules:
            keep = bool(rules[rid] & operations) or not rules[rid]
        elif rid in processes:
            keep = processes[rid] <= operations  # a process inside one area; cross-area ones go to the journeys call
        else:
            keep = False
        if keep:
            out.append(item)
    return out


def cross_area_requirements(required: list[dict], domain: dict, areas: list[dict]) -> list[dict]:
    """Rules, transitions and business processes that span more than one area: the cross-area call owns them."""
    area_of = {op: area['name'] for area in areas for op in area['operations']}
    spanning = {f"rule:{r['key']}" for r in domain.get('businessRules', [])
                if len({area_of.get(op) for op in r.get('operations', []) if op in area_of}) > 1}
    spanning |= {f"process:{p['key']}" for p in domain.get('processes', []) if len(process_areas(p, areas)) > 1}
    return [item for item in required if item['id'] in spanning or item['category'] == 'lifecycle']


# --- Business processes (end-to-end coverage) --------------------------------------------------------

def process_areas(process: dict, areas: list[dict]) -> list[str]:
    """The business areas a process passes through, in the order it reaches them."""
    area_of = {op: area['name'] for area in areas for op in area['operations']}
    return list(dict.fromkeys(area_of[op] for op in process['steps'] if op in area_of))


def validate_processes(processes: list[dict], endpoints: list[dict]) -> list[dict]:
    """Keep the processes whose steps are real operations; drop repeats; number them P1, P2, ..."""
    known = {ep['operationId'] for ep in endpoints}
    out, seen = [], set()
    for process in processes:
        steps = [op for op in process.get('steps', []) if op in known]
        steps = [op for i, op in enumerate(steps) if i == 0 or op != steps[i - 1]]
        signature = tuple(steps)
        if len(steps) < 2 or signature in seen:
            continue
        seen.add(signature)
        out.append({**process, 'steps': steps[:20], 'key': f'P{len(out) + 1}'})
    return out


def uncovered_areas(processes: list[dict], areas: list[dict]) -> list[dict]:
    """Areas that no business process passes through: every part of the application must be in some journey."""
    reached = {name for p in processes for name in process_areas(p, areas)}
    return [area for area in areas if area['name'] not in reached]


def in_order(flow_ops: list[str], sequence: list[str]) -> bool:
    """Whether the flow makes the sequence's calls in this order (other calls may come between)."""
    position = 0
    for op in flow_ops:
        if position < len(sequence) and op == sequence[position]:
            position += 1
    return position == len(sequence)


# --- Compact API context ----------------------------------------------------------------------------

def compact_schema(schema, depth=0):
    """A small, readable summary of a JSON schema for prompts covering the whole API."""
    if not isinstance(schema, dict) or depth > 3:
        return {}
    if 'x-circular-ref' in schema:
        return {'type': 'circular'}
    if 'allOf' in schema:
        merged = {'type': 'object', 'properties': {}, 'required': []}
        for part in schema['allOf']:
            part = compact_schema(part, depth)
            merged['properties'].update(part.get('properties', {}))
            merged['required'] += part.get('required', [])
        return merged
    out = {key: schema[key] for key in ('type', 'format', 'enum', 'minimum', 'maximum', 'minLength', 'maxLength',
                                        'readOnly', 'description') if key in schema}
    if isinstance(out.get('description'), str):
        out['description'] = out['description'][:160]
    if schema.get('properties'):
        out['properties'] = {k: compact_schema(v, depth + 1) for k, v in schema['properties'].items()}
        if schema.get('required'):
            out['required'] = schema['required']
    if schema.get('items'):
        out['items'] = compact_schema(schema['items'], depth + 1)
    for key in ('oneOf', 'anyOf'):
        if schema.get(key):
            out[key] = [compact_schema(s, depth + 1) for s in schema[key][:5]]
    return out


def compact_endpoint(endpoint: dict) -> dict:
    body = endpoint.get('requestBody')
    return {'operationId': endpoint['operationId'], 'method': endpoint['method'], 'path': endpoint['path'],
            'summary': endpoint.get('summary', ''), 'description': (endpoint.get('description') or '')[:800],
            'tags': endpoint.get('tags', []), 'secured': bool(endpoint.get('security')),
            'parameters': [{'name': p['name'], 'in': p['in'], 'required': p['required'], **compact_schema(p.get('schema', {}))}
                           for p in endpoint.get('parameters', [])],
            'requestBody': {'required': body.get('required', False), 'schema': compact_schema(body.get('schema', {}))} if body else None,
            'responses': {status: _compact_response(status, detail) for status, detail in endpoint.get('responses', {}).items()}}


def _compact_response(status: str, detail: dict) -> dict:
    out = {'description': (detail.get('description') or '')[:200]}
    if status.startswith('2'):
        out['schema'] = compact_schema(detail.get('schema', {}))
    elif _top_fields(detail.get('schema')):
        out['fields'] = _top_fields(detail.get('schema'))  # error bodies: which fields to assert, not their schema
    return out


def _top_fields(schema) -> list[str]:
    schema = schema if isinstance(schema, dict) else {}
    if schema.get('type') == 'array' and isinstance(schema.get('items'), dict):
        schema = schema['items']
    fields = dict(compact_schema(schema).get('properties') or {})
    return list(fields)[:40]


def operation_index(endpoint: dict) -> str:
    """One line per operation, enough to use it as a setup step: id, method, path, documented statuses."""
    statuses = ','.join(sorted(endpoint.get('responses', {})))
    summary = (endpoint.get('summary') or '').strip()
    return f"{endpoint['operationId']}: {endpoint['method']} {endpoint['path']} [{statuses}]" + (f' {summary[:100]}' if summary else '')


def brief_endpoint(endpoint: dict) -> dict:
    """What a flow planner needs from an operation: inputs, documented statuses and the fields it returns."""
    body = endpoint.get('requestBody')
    schema = compact_schema((body or {}).get('schema', {}))
    out = {'operationId': endpoint['operationId'], 'method': endpoint['method'], 'path': endpoint['path'],
           'summary': (endpoint.get('summary') or '')[:160], 'secured': bool(endpoint.get('security')),
           'inputs': [f"{p['in']}.{p['name']}" + ('*' if p.get('required') else '') for p in endpoint.get('parameters', [])],
           'statuses': sorted(endpoint.get('responses', {}))}
    if body:
        required = set(schema.get('required', []))
        out['body'] = [name + ('*' if name in required else '') for name in (schema.get('properties') or {})][:40]
    returns = {status: _top_fields(detail.get('schema')) for status, detail in endpoint.get('responses', {}).items()
               if status.startswith('2') and _top_fields(detail.get('schema'))}
    if returns:
        out['returns'] = returns
    return out


# --- Dependency evidence (no path enumeration) --------------------------------------------------------

def _singular(word: str) -> str:
    word = re.sub(r'[^a-z0-9]', '', word.lower())
    if word.endswith('ies'):
        return word[:-3] + 'y'
    return word[:-1] if word.endswith('s') and not word.endswith(('ss', 'us')) else word


def _resource(path: str) -> str:
    static = [s for s in path.split('/') if s and not s.startswith('{') and not re.fullmatch(r'v\d+', s)]
    return _singular(static[-1]) if static else ''


def _concept(name: str, owner: str) -> str | None:
    key = re.sub(r'[^a-z0-9]', '', name.lower())
    if key in ('id', 'uuid'):
        return owner or None
    if key.endswith('id') and len(key) > 2:
        return _singular(key[:-2])
    return None


def _fields(schema, prefix='$', depth=0):
    schema = compact_schema(schema) if depth == 0 else schema
    if not isinstance(schema, dict) or depth > 2:
        return
    for name, child in (schema.get('properties') or {}).items():
        yield f'{prefix}.{name}', name, child
        if child.get('properties'):
            yield from _fields(child, f'{prefix}.{name}', depth + 1)


def dependencies(endpoints: list[dict]) -> list[dict]:
    """Which documented response identifiers can feed which request inputs."""
    producers = {}
    for ep in endpoints:
        owner = _resource(ep['path'])
        for status, detail in ep.get('responses', {}).items():
            if not status.startswith('2'):
                continue
            schema = detail.get('schema') or {}
            if schema.get('type') == 'array' and isinstance(schema.get('items'), dict):
                schema = schema['items']
            for path, name, _ in _fields(schema):
                concept = _concept(name, owner if path.count('.') == 1 else '')
                if concept:
                    producers.setdefault(concept, []).append((ep['operationId'], path))
    edges, seen = [], set()
    for ep in endpoints:
        inputs = [(f"{p['in']}.{p['name']}", p['name'], p['in'] == 'path') for p in ep.get('parameters', [])]
        body = ep.get('requestBody') or {}
        inputs += [(f'body.{path[2:]}', name, False) for path, name, child in _fields(body.get('schema') or {})
                   if not child.get('readOnly')]
        for target, name, in_path in inputs:
            owner = _resource(ep['path'].split('{' + name + '}')[0]) if in_path else ''
            concept = _concept(name, owner)
            for producer, response_path in producers.get(concept, []):
                if producer == ep['operationId']:
                    continue
                key = (producer, ep['operationId'], target)
                if key not in seen:
                    seen.add(key)
                    edges.append({'from': producer, 'to': ep['operationId'], 'value': response_path, 'target': target,
                                  'resource': concept, 'required': in_path})
    return edges


def _source_rank(edge: dict, methods: dict) -> tuple:
    """Prefer creating the value (POST) and top-level identifiers over values nested in other records."""
    return (0 if methods.get(edge['from']) == 'POST' else 1, edge['value'].count('.'), edge['from'])


def dependency_hints(edges: list[dict], endpoints: list[dict], operations: set[str] | None = None, limit: int = 3) -> list[dict]:
    """Where each required input (a path id) can come from: a short, ranked list instead of every possible pair."""
    methods = {ep['operationId']: ep['method'] for ep in endpoints}
    grouped: dict[tuple, list[dict]] = {}
    for edge in edges:
        if edge['required'] and (operations is None or edge['to'] in operations):
            grouped.setdefault((edge['to'], edge['target']), []).append(edge)
    return [{'operation': to, 'input': target,
             'from': [f"{e['from']} {e['value']}" for e in sorted(found, key=lambda e: _source_rank(e, methods))[:limit]]}
            for (to, target), found in grouped.items()]


def requirement_operations(item: dict, domain: dict) -> set[str]:
    """The operations a coverage requirement is about."""
    rid = item['id']
    if rid.startswith(('op:', 'dep:')):
        return {rid.split(':')[1]}
    for t in domain.get('transitions', []):
        if rid == f"transition:{t['entity']}:{t['fromState']}->{t['toState']}":
            return {t['operationId']}
    for rule in domain.get('businessRules', []):
        if rid == f"rule:{rule['key']}":
            return set(rule.get('operations', []))
    for process in domain.get('processes', []):
        if rid == f"process:{process['key']}":
            return set(process['steps'])
    return set()


def domain_for(domain: dict, operations: set[str], covers: set[str] = frozenset()) -> dict:
    """The part of the domain analysis that concerns some operations: their records, status changes and rules."""
    entities = [e for e in domain.get('entities', []) if set(e.get('operations', [])) & operations]
    names = {e['name'] for e in entities}
    transitions = [t for t in domain.get('transitions', []) if t['operationId'] in operations
                   or f"transition:{t['entity']}:{t['fromState']}->{t['toState']}" in covers]
    names |= {t['entity'] for t in transitions}
    entities += [e for e in domain.get('entities', []) if e['name'] in names and e not in entities]
    rules = [r for r in domain.get('businessRules', []) if set(r.get('operations', [])) & operations or f"rule:{r['key']}" in covers]
    out = {'summary': domain.get('summary', ''),
           'entities': [{k: e.get(k) for k in ('name', 'description', 'identifier', 'states')} for e in entities],
           'relationships': [r for r in domain.get('relationships', []) if any(name in r for name in names)],
           'transitions': transitions, 'businessRules': rules}
    processes = [p for p in domain.get('processes', []) if f"process:{p['key']}" in covers]
    if processes:
        out['processes'] = processes
    return out


# --- Coverage requirements and validation --------------------------------------------------------------

def requirements(endpoints: list[dict], edges: list[dict], domain: dict) -> list[dict]:
    items, ids = [], set()

    def add(rid, category, description, check=None):
        if rid not in ids:
            ids.add(rid)
            items.append({'id': rid, 'category': category, 'description': description, **({'check': check} if check else {})})

    for ep in endpoints:
        add(f"op:{ep['operationId']}", 'operation', f"{ep['method']} {ep['path']} is used in at least one flow")
    consumers = {}
    for edge in edges:
        if edge['required']:
            consumers.setdefault((edge['to'], edge['target']), []).append(edge)
    methods = {ep['operationId']: ep['method'] for ep in endpoints}
    for (operation, target), sources in consumers.items():
        ranked = sorted(sources, key=lambda e: _source_rank(e, methods))
        names = list(dict.fromkeys(e['from'] for e in ranked))[:3]
        add(f'dep:{operation}:{target}', 'dependency',
            f"{operation} receives {target} from an earlier step (e.g. {', '.join(names)})")
    for t in domain.get('transitions', []):
        add(f"transition:{t['entity']}:{t['fromState']}->{t['toState']}", 'lifecycle',
            f"{t['entity']} moves from {t['fromState']} to {t['toState']} ({t['operationId']})",
            {'ops': [t['operationId']], 'status': '2xx'})
    for entity in domain.get('entities', []):
        for state in entity.get('lockedStates', []):
            reach = sorted({t['operationId'] for t in domain.get('transitions', [])
                            if t['entity'] == entity['name'] and t['toState'] == state})
            add(f"locked:{entity['name']}:{state}", 'locked_state',
                f"A {entity['name']} that is {state} cannot be changed any more",
                {'reach': reach, 'ops': entity.get('operations', []), 'status': '4xx'})
    for rule in domain.get('businessRules', []):
        ops, kind = rule.get('operations', []), rule.get('kind', 'other')
        if kind in ('validation', 'uniqueness', 'state', 'ownership', 'role', 'concurrency'):
            check = {'ops': ops, 'status': '4xx'}
        elif kind == 'idempotency':
            check = {'ops': ops, 'repeat': True}
        elif kind == 'side_effect':
            check = {'ops': ops, 'thenStep': True}
        else:
            check = {'ops': ops}
        add(f"rule:{rule['key']}", 'business_rule', rule['rule'], check)
    for i, effect in enumerate(domain.get('sideEffects', []), 1):
        add(f"effect:{effect['operationId']}:{i}", 'side_effect', f"After {effect['operationId']}: {effect['effect']}",
            {'after': effect['operationId'], 'read': effect.get('verifyWith') or ''})
    for process in domain.get('processes', []):
        add(f"process:{process['key']}", 'process', f"{process['name']}: {' -> '.join(process['steps'])}",
            {'sequence': key_steps(process['steps'], methods)})
    return items


def key_steps(steps: list[str], methods: dict[str, str]) -> list[str]:
    """The calls a process cannot do without: every state change in order, then the read that shows the outcome.

    Look-ups along the way (list the options, read a related record) are good practice but not required for coverage.
    """
    changes = [op for op in steps if methods.get(op, 'GET') != 'GET']
    if steps and methods.get(steps[-1], 'GET') == 'GET':
        changes.append(steps[-1])
    changes = [op for i, op in enumerate(changes) if i == 0 or op != changes[i - 1]]
    return changes if len(changes) >= 2 else list(steps)


def proof(check: dict | None) -> str:
    """What a flow must contain for its `covers` claim to count, in words the designer can follow."""
    if not check:
        return ''
    if 'sequence' in check:
        return f"steps of {', then '.join(check['sequence'])}, in this order (other steps may come between)"
    ops = ', '.join(check.get('ops') or []) or 'any operation'
    if 'after' in check:
        then = f"a later {check['read']} step" if check.get('read') else 'a later step that shows the effect'
        return f"a successful {check['after']} step followed by {then}"
    if check.get('reach') is not None:
        reach = ' or '.join(check['reach']) or 'the steps that put it in this state'
        return f"a successful step of {reach}, then a later step (one of: {ops}) that expects a 4xx refusal"
    if check.get('status') == '4xx':
        return f'a step of {ops} that expects a documented 4xx status'
    if check.get('repeat'):
        return f'the same request to one of {ops} sent twice (a retry)'
    if check.get('thenStep'):
        return f'a step of {ops} followed by a step that verifies the result'
    if check.get('status') == '2xx':
        return f'a successful step of {ops}'
    return f'a step of {ops}' if check.get('ops') else ''


def for_prompt(required: list[dict]) -> list[dict]:
    """Requirements as the agents see them: the machine check becomes a sentence."""
    out = []
    for item in required:
        entry = {k: item[k] for k in ('id', 'category', 'description') if k in item}
        if proof(item.get('check')):
            entry['proof'] = proof(item.get('check'))
        out.append({**entry, **({'covered': item['covered']} if 'covered' in item else {})})
    return out


def _ok(step) -> bool:
    return 200 <= int(step.get('expectedStatus', 0)) < 300


def _refused(step) -> bool:
    return 400 <= int(step.get('expectedStatus', 0)) < 500


def claim_holds(flow: dict, check: dict | None) -> bool:
    """Whether a flow really contains what a requirement needs; claims without a check are trusted."""
    if not check:
        return True
    steps = flow.get('steps', [])
    if 'sequence' in check:
        return in_order([st['operationId'] for st in steps], check['sequence'])
    ops = set(check.get('ops') or [])
    uses = (lambda st: st['operationId'] in ops) if ops else (lambda st: True)
    if 'after' in check:
        for i, st in enumerate(steps):
            if st['operationId'] == check['after'] and _ok(st):
                later = steps[i + 1:]
                if later and (not check.get('read') or any(x['operationId'] == check['read'] for x in later)):
                    return True
        return False
    if check.get('reach') is not None:
        reach = set(check['reach'])
        for i, st in enumerate(steps):
            if (not reach or st['operationId'] in reach) and _ok(st) and any(_refused(x) for x in steps[i + 1:]):
                return True
        return False
    if check.get('status') == '4xx':
        return any(uses(st) and _refused(st) for st in steps)
    if check.get('repeat'):
        counts = {}
        for st in steps:
            if uses(st):
                counts[st['operationId']] = counts.get(st['operationId'], 0) + 1
        return any(n > 1 for n in counts.values())
    if check.get('thenStep'):
        return any(uses(st) for st in steps[:-1])
    if check.get('status') == '2xx':
        return any(uses(st) and _ok(st) for st in steps)
    return any(uses(st) for st in steps) if ops else True


def validate_plan(plan: list[dict], endpoints: list[dict]) -> list[str]:
    """Return human-readable problems the designer must fix."""
    known = {ep['operationId']: ep for ep in endpoints}
    problems = []
    for flow in plan:
        captured, keys = set(), set()
        for step in flow['steps']:
            where = f"{flow['key']}/{step['key']}"
            if step['key'] in keys:
                problems.append(f'{where}: duplicate step key.')
            keys.add(step['key'])
            endpoint = known.get(step['operationId'])
            if not endpoint:
                problems.append(f"{where}: operation {step['operationId']} does not exist.")
                continue
            if str(step['expectedStatus']) not in endpoint.get('responses', {}):
                problems.append(f"{where}: {step['expectedStatus']} is not documented for {step['operationId']}.")
            for item in step['inputs']:
                if item['source'].startswith('steps.'):
                    parts = item['source'].split('.')
                    if len(parts) != 3 or f'{parts[1]}.{parts[2]}' not in captured:
                        problems.append(f"{where}: input {item['target']} uses {item['source']}, which no earlier step captures.")
            for capture in step['captures']:
                captured.add(f"{step['key']}.{capture['name']}")
                problem = _capture_problem(capture, endpoint)
                if problem:
                    problems.append(f'{where}: {problem}')
    return problems


def _capture_problem(capture: dict, endpoint: dict) -> str:
    """A capture path whose first field is not in any documented success response."""
    match = re.match(r'^\$(?:\[\d+\])?\.([A-Za-z_][A-Za-z0-9_]*)', capture.get('path', ''))
    if not match:
        return ''
    fields = {f for status, detail in endpoint.get('responses', {}).items() if status.startswith('2')
              for f in _top_fields(detail.get('schema'))}
    if not fields or match.group(1) in fields:
        return ''
    shown = ', '.join(sorted(fields)[:12])
    return (f"capture {capture['name']} reads {capture['path']}, but {endpoint['operationId']} does not return "
            f"a field '{match.group(1)}' (documented: {shown}).")


def flow_signature(flow: dict) -> tuple:
    """Flows of the same type with the same steps and statuses prove the same journey."""
    return (flow.get('type'), tuple((st['operationId'], int(st.get('expectedStatus', 0))) for st in flow.get('steps', [])))


def satisfied(plan: list[dict], checks: dict | None = None) -> set[str]:
    """Requirement ids proven by the plan's structure (operations used, ids chained) or declared in covers.

    A declared id counts only when the flow contains what the requirement's check needs (see `claim_holds`).
    """
    checks = checks or {}
    done = {rid for flow in plan for rid in flow.get('covers', []) if claim_holds(flow, checks.get(rid))}
    # A business process is proven by any flow that makes its calls in order, whether or not it claims it.
    sequences = {rid: check['sequence'] for rid, check in checks.items() if check and 'sequence' in check}
    for flow in plan:
        ops = [step['operationId'] for step in flow['steps']]
        done |= {rid for rid, sequence in sequences.items() if rid not in done and in_order(ops, sequence)}
        for step in flow['steps']:
            done.add(f"op:{step['operationId']}")
            for item in step['inputs']:
                if item['source'].startswith('steps.'):
                    done.add(f"dep:{step['operationId']}:{item['target']}")
    return done


def unproven_claims(plan: list[dict], required: list[dict]) -> dict[str, list[str]]:
    """Per flow, the requirement ids it lists in `covers` but does not actually prove."""
    checks = {r['id']: r.get('check') for r in required}
    out = {}
    for flow in plan:
        bad = [rid for rid in flow.get('covers', []) if rid in checks and not claim_holds(flow, checks[rid])]
        if bad:
            out[flow['key']] = bad
    return out


def gaps(required: list[dict], plan: list[dict]) -> list[dict]:
    done = satisfied(plan, {r['id']: r.get('check') for r in required})
    return [item for item in required if item['id'] not in done]


# --- Splitting a large API into parts that are analysed in parallel ---------------------------------------

def chunk_operations(endpoints: list[dict], size: int = 50) -> list[list[dict]]:
    """Operations grouped by their first tag, packed into parts of at most `size` (a big tag is split)."""
    by_tag: dict[str, list[dict]] = {}
    for ep in endpoints:
        by_tag.setdefault((ep.get('tags') or ['Other'])[0], []).append(ep)
    parts, current = [], []
    for ops in sorted(by_tag.values(), key=len, reverse=True):
        for start in range(0, len(ops), size):
            piece = ops[start:start + size]
            if current and len(current) + len(piece) > size:
                parts.append(current)
                current = []
            current = current + piece
    return parts + ([current] if current else [])


def _unique(items, key=lambda x: x):
    seen, out = set(), []
    for item in items:
        k = key(item)
        if k not in seen:
            seen.add(k)
            out.append(item)
    return out


def merge_domains(parts: list[dict]) -> dict:
    """One domain model from the analyses of several parts of the API: entities and areas merged by name, rules renumbered."""
    entities: dict[str, dict] = {}
    for part in parts:
        for entity in part.get('entities', []):
            key = entity['name'].casefold()
            if key not in entities:
                entities[key] = json_copy(entity)
                continue
            merged = entities[key]
            merged['operations'] = _unique(merged.get('operations', []) + entity.get('operations', []))
            merged['states'] = _unique(merged.get('states', []) + entity.get('states', []))
            merged['lockedStates'] = _unique(merged.get('lockedStates', []) + entity.get('lockedStates', []))
            if len(entity.get('description', '')) > len(merged.get('description', '')):
                merged['description'] = entity['description']
            merged['identifier'] = merged.get('identifier') or entity.get('identifier', '')
    rules = _unique([r for part in parts for r in part.get('businessRules', [])], key=lambda r: ' '.join(r['rule'].casefold().split()))
    areas: dict[str, dict] = {}
    for part in parts:
        for area in part.get('areas', []):
            key = area['name'].casefold()
            if key in areas:
                areas[key]['operations'] = _unique(areas[key]['operations'] + area['operations'])
            else:
                areas[key] = json_copy(area)
    return {
        'summary': max((p.get('summary', '') for p in parts), key=len, default=''),
        'entities': list(entities.values()),
        'relationships': _unique([r for p in parts for r in p.get('relationships', [])]),
        'transitions': _unique([t for p in parts for t in p.get('transitions', [])],
                               key=lambda t: (t['entity'], t['fromState'], t['toState'], t['operationId'])),
        'businessRules': [{**r, 'key': f'R{i}'} for i, r in enumerate(rules, 1)],
        'sideEffects': _unique([e for p in parts for e in p.get('sideEffects', [])], key=lambda e: (e['operationId'], e['effect'])),
        'areas': list(areas.values()),
        'assumptions': _unique([a for p in parts for a in p.get('assumptions', [])]),
    }


def json_copy(value):
    import json
    return json.loads(json.dumps(value))

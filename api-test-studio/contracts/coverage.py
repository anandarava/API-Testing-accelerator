"""Minimum coverage requirements derived from an endpoint's contract.

The scenario-planner agent designs the checklist. This module only lists what the contract makes
mandatory, so the server and the Local Helper can verify the agent did not skip anything.
"""

SCALAR_TYPES = {'string', 'integer', 'number', 'boolean'}
STRING_FORMATS = {'email', 'uuid', 'date', 'date-time', 'time', 'uri', 'url', 'ipv4', 'ipv6', 'hostname', 'byte'}
LIMITS = ('minLength', 'maxLength', 'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'minItems', 'maxItems')
MAX_DEPTH = 3


def _merge(schema):
    if not isinstance(schema, dict):
        return {}
    if 'allOf' not in schema:
        return schema
    merged = {k: v for k, v in schema.items() if k != 'allOf'}
    merged['properties'] = dict(schema.get('properties', {}))
    merged['required'] = list(schema.get('required', []))
    for part in schema['allOf']:
        part = _merge(part)
        merged['properties'].update(part.get('properties', {}))
        merged['required'] += part.get('required', [])
        merged.setdefault('type', part.get('type'))
    return merged


def _type(schema):
    kind = schema.get('type')
    if isinstance(kind, list):
        kind = next((k for k in kind if k != 'null'), None)
    if kind is None and 'properties' in schema:
        kind = 'object'
    return kind


def _nullable(schema):
    kind = schema.get('type')
    return bool(schema.get('nullable')) or (isinstance(kind, list) and 'null' in kind)


def _is_json(media_type):
    return bool(media_type) and 'json' in media_type


class _Collector:
    def __init__(self):
        self.items, self.ids = [], set()

    def add(self, oid, category, description, source):
        if oid not in self.ids:
            self.ids.add(oid)
            self.items.append({'id': oid, 'category': category, 'description': description, 'source': source})

    def field(self, path, label, schema, source, check_type=True):
        kind = _type(schema)
        if check_type and kind:
            self.add(f'type:{path}', 'type', f'{label} with the wrong data type (expected {kind})', source)
        for limit in LIMITS:
            value = schema.get(limit)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                self.add(f'boundary:{path}:{limit}', 'boundary', f'{label} at and just beyond {limit} {value}', source)
        if schema.get('enum'):
            values = ', '.join(str(v) for v in schema['enum'][:10])
            self.add(f'enum:{path}', 'enum', f'{label} with a value outside the allowed values ({values})', source)
        if kind == 'string' and schema.get('format') in STRING_FORMATS:
            self.add(f'format:{path}', 'format', f'{label} with an invalid {schema["format"]} value', source)
        if kind == 'string' and schema.get('pattern'):
            self.add(f'pattern:{path}', 'format', f'{label} that does not match the pattern {schema["pattern"]}', source)

    def body(self, schema, path, source, depth=0):
        schema = _merge(schema)
        if depth > MAX_DEPTH or 'x-circular-ref' in schema:
            return
        required = set(schema.get('required', []))
        for name, child in (schema.get('properties') or {}).items():
            child = _merge(child)
            if not isinstance(child, dict) or 'x-circular-ref' in child:
                continue
            field_path = f'{path}.{name}'
            label = 'Field ' + field_path.removeprefix('body.')
            if child.get('readOnly'):
                self.add(f'readonly:{field_path}', 'security', f'Read-only {label.lower()} sent in the request is ignored or rejected', source)
                continue
            if name in required:
                self.add(f'required:{field_path}', 'required', f'Required {label.lower()} is missing', source)
                if not _nullable(child):
                    self.add(f'null:{field_path}', 'required', f'Required {label.lower()} is null', source)
            self.field(field_path, label, child, source)
            kind = _type(child)
            if kind == 'object':
                self.body(child, field_path, source, depth + 1)
            elif kind == 'array':
                items = _merge(child.get('items', {}))
                if _type(items) == 'object':
                    self.body(items, field_path + '[]', source, depth + 1)


def obligations(endpoint: dict, security_schemes: dict | None = None) -> list[dict]:
    """Return the requirements every unit checklist for this endpoint must cover."""
    out = _Collector()
    pointer = endpoint.get('pointer', '')
    responses = endpoint.get('responses', {})
    success = sorted(s for s in responses if s.startswith('2') and s.isdigit())
    body = endpoint.get('requestBody') or None
    schema = _merge(body.get('schema', {})) if body else {}

    if success:
        out.add('positive:minimal', 'positive', f'Valid request with only the required inputs returns {success[0]}', pointer)
    optional_inputs = any(not p.get('required') for p in endpoint.get('parameters', []) if p.get('in') != 'path') or \
        any(name not in schema.get('required', []) and not _merge(child).get('readOnly')
            for name, child in (schema.get('properties') or {}).items())
    if success and optional_inputs:
        out.add('positive:full', 'positive', 'Valid request with all optional inputs populated', pointer)
    for status, detail in responses.items():
        if status.isdigit() and not status.startswith('5'):
            text = (detail.get('description') or '').strip()
            out.add(f'status:{status}', 'status', f'Documented response {status}' + (f' ({text[:80]})' if text else '') + ' is produced',
                    f'{pointer}/responses/{status}')

    for param in endpoint.get('parameters', []):
        where, name = param.get('in'), param.get('name', '')
        if where not in ('path', 'query', 'header'):
            continue
        path, label = f'{where}.{name}', f'{where.capitalize()} parameter {name}'
        param_schema = _merge(param.get('schema', {}))
        source = f'{pointer}/parameters/{name}'
        if where == 'path':
            out.add(f'invalid:{path}', 'path_params', f'{label} with an invalid value', source)
            if '404' in responses:
                out.add(f'notfound:{path}', 'path_params', f'{label} that refers to a resource that does not exist', source)
            out.field(path, label, param_schema, source, check_type=False)
            continue
        if param.get('required'):
            out.add(f'required:{path}', 'required', f'Required {label.lower()} is missing', source)
        out.field(path, label, param_schema, source, check_type=where == 'query')

    if body and _is_json(body.get('mediaType')):
        source = f'{pointer}/requestBody'
        if body.get('required'):
            out.add('required:body', 'required', 'Request without a body', source)
        out.add('type:body', 'type', 'Body that is malformed JSON or the wrong JSON type', source)
        out.add('header:content-type', 'headers', 'Request with an unsupported Content-Type', source)
        out.body(schema, 'body', source)

    security = endpoint.get('security') or []
    if security and all(requirement for requirement in security):
        names = sorted({name for requirement in security for name in requirement})
        out.add('auth:missing', 'auth', 'Request without credentials (' + ', '.join(names) + ')', f'{pointer}/security')
        out.add('auth:invalid', 'auth', 'Request with invalid or expired credentials', f'{pointer}/security')
        if '403' in responses:
            out.add('auth:forbidden', 'auth', 'Authenticated caller without permission for this operation', f'{pointer}/security')
    return out.items


# What a scenario must be to prove a requirement: (allowed categories, expected status rule).
# Status rules: '2xx', '4xx', an exact code such as '403', 'same' (the code in the id), or None (any).
_PROOF = {
    'positive': (('positive',), '2xx'),
    'status': (None, 'same'),
    'invalid': (('path_params',), '4xx'),
    'notfound': (('path_params',), '404'),
    'required': (('required',), '4xx'),
    'null': (('required', 'type'), '4xx'),
    'type': (('type',), '4xx'),
    'boundary': (('boundary',), None),
    'enum': (('enum',), '4xx'),
    'format': (('format',), '4xx'),
    'pattern': (('format',), '4xx'),
    'readonly': (('security',), None),
    'header': (('headers',), '4xx'),
}
_AUTH = {'auth:missing': '401', 'auth:invalid': '401', 'auth:forbidden': '403'}


def proof(requirement_id: str) -> str:
    """What a scenario must contain for its `covers` claim to count, in words the planner can follow."""
    kind = requirement_id.split(':', 1)[0]
    if requirement_id in _AUTH:
        return f'a scenario of category auth that expects {_AUTH[requirement_id]}'
    categories, status = _PROOF.get(kind, (None, None))
    if status == 'same':
        return f'a scenario that expects status {requirement_id.split(":", 1)[1]}'
    parts = [f'category {" or ".join(categories)}' if categories else 'a scenario']
    if status:
        parts.append(f'expecting {status}' if status in ('2xx', '4xx') else f'expecting {status}')
    return ' '.join(parts)


def claim_holds(requirement_id: str, scenario: dict) -> bool:
    """Whether a scenario that lists the requirement in `covers` really tests it."""
    status = scenario.get('expectedStatus')
    category = scenario.get('category')
    if requirement_id in _AUTH:
        return category == 'auth' and str(status) in (_AUTH[requirement_id], 'None') and status is not None
    kind = requirement_id.split(':', 1)[0]
    if kind not in _PROOF:
        return True
    categories, rule = _PROOF[kind]
    if categories and category not in categories:
        return False
    if rule is None:
        return True
    if status is None:
        return False
    if rule == '2xx':
        return 200 <= int(status) < 300
    if rule == '4xx':
        return 400 <= int(status) < 500
    if rule == 'same':
        return str(status) == requirement_id.split(':', 1)[1]
    return str(status) == rule


def gaps(required: list[dict], scenarios: list[dict]) -> list[dict]:
    covered = {oid for scenario in scenarios for oid in scenario.get('covers', []) if claim_holds(oid, scenario)}
    return [item for item in required if item['id'] not in covered]


def unproven(scenarios: list[dict]) -> dict[str, list[str]]:
    """Per scenario key, the requirement ids it claims but does not test."""
    out = {}
    for scenario in scenarios:
        bad = [oid for oid in scenario.get('covers', []) if not claim_holds(oid, scenario)]
        if bad:
            out[scenario['key']] = bad
    return out


def with_proof(required: list[dict]) -> list[dict]:
    return [{**item, 'proof': proof(item['id'])} for item in required]

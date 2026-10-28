"""Code checks on written test cases, so mistakes are fixed before a QA reviewer or the script writer sees them."""
import re

# The placeholders the script writer knows how to turn into code (see the playwright-script-standards skill).
PLACEHOLDER = re.compile(r'\{\{([^{}]*)\}\}')
KNOWN_PLACEHOLDER = re.compile(r'^(env\.[A-Za-z_][A-Za-z0-9_]*|unique\.[A-Za-z][A-Za-z0-9_]*|repeat:[^:{}]{1,5}:\d{1,6}|uuid\.random'
                               r'|created\.[A-Za-z][A-Za-z0-9_.]*|steps\.S\d+\.[A-Za-z][A-Za-z0-9_]*)$')
CREDENTIAL_HEADERS = {'authorization', 'cookie', 'x-api-key', 'api-key', 'apikey', 'x-auth-token', 'proxy-authorization'}
TYPES = {'string': str, 'integer': int, 'number': (int, float), 'boolean': bool, 'array': list, 'object': dict}


def placeholder_problems(value, where: str = 'request') -> list[str]:
    found = PLACEHOLDER.findall(repr(value))
    unknown = sorted({p for p in found if not KNOWN_PLACEHOLDER.match(p.strip())})
    return [f'{where} uses the unknown placeholder {{{{{p}}}}}; use env.NAME, unique.name, repeat:x:N, uuid.random, '
            f'created.field or steps.Sx.name.' for p in unknown]


def credential_header_problems(request: dict, security_schemes: dict | None = None) -> list[str]:
    names = set(CREDENTIAL_HEADERS)
    for scheme in (security_schemes or {}).values():
        if isinstance(scheme, dict) and scheme.get('type') == 'apiKey' and scheme.get('in') == 'header' and scheme.get('name'):
            names.add(str(scheme['name']).casefold())
    bad = [h for h in (request.get('headers') or {}) if str(h).casefold() in names]
    return [f'request header "{h}" carries credentials; use request.auth instead.' for h in bad]


def _is_placeholder(value) -> bool:
    return isinstance(value, str) and bool(PLACEHOLDER.fullmatch(value.strip()))


def schema_problems(value, schema: dict | None, path: str = 'body', depth: int = 0) -> list[str]:
    """Where a value breaks its JSON schema: required fields, types, enums, lengths and ranges (a light check)."""
    if not isinstance(schema, dict) or depth > 6 or 'x-circular-ref' in schema or _is_placeholder(value):
        return []
    if 'allOf' in schema:
        merged = {'type': 'object', 'properties': {}, 'required': []}
        for part in schema['allOf']:
            if isinstance(part, dict):
                merged['properties'].update(part.get('properties', {}))
                merged['required'] += part.get('required', [])
                merged['type'] = part.get('type', merged['type'])
        schema = {**merged, **{k: v for k, v in schema.items() if k != 'allOf'}}
    if 'oneOf' in schema or 'anyOf' in schema:
        return []
    kind = schema.get('type')
    if isinstance(kind, list):
        if value is None and 'null' in kind:
            return []
        kind = next((k for k in kind if k != 'null'), None)
    if value is None:
        return [] if schema.get('nullable') else ([f'{path} is null'] if kind else [])
    if kind in TYPES:
        expected = TYPES[kind]
        if (kind in ('integer', 'number') and isinstance(value, bool)) or not isinstance(value, expected):
            if not (kind == 'integer' and isinstance(value, float) and value.is_integer()):
                return [f'{path} should be {kind}, not {type(value).__name__}']
    problems = []
    if schema.get('enum') and value not in schema['enum']:
        problems.append(f'{path} is not one of the allowed values {schema["enum"][:8]}')
    if isinstance(value, str) and not PLACEHOLDER.search(value):
        if isinstance(schema.get('minLength'), int) and len(value) < schema['minLength']:
            problems.append(f'{path} is shorter than {schema["minLength"]} characters')
        if isinstance(schema.get('maxLength'), int) and len(value) > schema['maxLength']:
            problems.append(f'{path} is longer than {schema["maxLength"]} characters')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(schema.get('minimum'), (int, float)) and value < schema['minimum']:
            problems.append(f'{path} is below the minimum {schema["minimum"]}')
        if isinstance(schema.get('maximum'), (int, float)) and value > schema['maximum']:
            problems.append(f'{path} is above the maximum {schema["maximum"]}')
    if isinstance(value, dict):
        properties = schema.get('properties') or {}
        for name in schema.get('required', []):
            if name not in value and not (properties.get(name) or {}).get('readOnly'):
                problems.append(f'{path}.{name} is required but missing')
        for name, item in value.items():
            if name in properties:
                problems += schema_problems(item, properties[name], f'{path}.{name}', depth + 1)
            elif schema.get('additionalProperties') is False and properties:
                problems.append(f'{path}.{name} is not a documented field')
    if isinstance(value, list) and isinstance(schema.get('items'), dict):
        for index, item in enumerate(value[:20]):
            problems += schema_problems(item, schema['items'], f'{path}[{index}]', depth + 1)
    return problems


def response_check_problems(expected: dict, endpoint: dict) -> list[str]:
    """A success whose body the contract documents must check that body, not only the status code."""
    status = str(expected.get('status') or '')
    if not status.startswith('2') or not (endpoint.get('responses', {}).get(status) or {}).get('schema'):
        return []
    problems = []
    if expected.get('responseSchema') != 'success':
        problems.append(f'the {status} response has a documented body; set responseSchema to "success".')
    if not expected.get('bodyChecks'):
        problems.append(f'the {status} response has a documented body; add bodyChecks for the fields this case is about, '
                        'not only the status code.')
    return problems


def unit_case_problems(case: dict, endpoint: dict, security_schemes: dict | None = None) -> list[str]:
    """Problems in one written unit case; an empty list means it may go to the reviewer."""
    request, expected = case.get('request') or {}, case.get('expected') or {}
    problems = credential_header_problems(request, security_schemes) + placeholder_problems(request)
    status = expected.get('status')
    if status and str(status) not in endpoint.get('responses', {}):
        problems.append(f'status {status} is not documented for this endpoint.')
    problems += response_check_problems(expected, endpoint)
    if case.get('category') == 'positive' and request.get('body') is not None:
        schema = (endpoint.get('requestBody') or {}).get('schema')
        problems += [f'the valid request breaks the schema: {p}.' for p in schema_problems(request['body'], schema)[:8]]
    return problems

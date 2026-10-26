"""Parse OpenAPI 3.x and Swagger 2.0 documents into a normalized endpoint inventory.

Nothing here makes network requests: external $refs are rejected and must be bundled first.
"""
import datetime
import hashlib
import json
import math
import re

import yaml

HTTP_METHODS = ('get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace')
NODE_BUDGET = 400_000
MAX_DEPTH = 100
SCHEMA_KEYS = ('type', 'format', 'items', 'enum', 'default', 'minimum', 'maximum', 'exclusiveMinimum',
               'exclusiveMaximum', 'minLength', 'maxLength', 'pattern', 'minItems', 'maxItems',
               'uniqueItems', 'multipleOf', 'collectionFormat')


class SpecError(ValueError):
    """A user-facing problem with the uploaded document."""


def digest(value) -> str:
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()


# --- Loading --------------------------------------------------------------

def _normalize(node, ancestors, depth, budget):
    budget[0] += 1
    if budget[0] > NODE_BUDGET or depth > MAX_DEPTH:
        raise SpecError('The document is too large or too deeply nested to process.')
    if isinstance(node, dict):
        if id(node) in ancestors:
            raise SpecError('The document contains a recursive YAML alias.')
        inner = ancestors | {id(node)}
        return {str(key): _normalize(value, inner, depth + 1, budget) for key, value in node.items()}
    if isinstance(node, list):
        if id(node) in ancestors:
            raise SpecError('The document contains a recursive YAML alias.')
        inner = ancestors | {id(node)}
        return [_normalize(value, inner, depth + 1, budget) for value in node]
    if isinstance(node, (datetime.date, datetime.datetime)):
        return node.isoformat()
    if isinstance(node, float) and (math.isnan(node) or math.isinf(node)):
        return str(node)
    if node is None or isinstance(node, (str, int, float, bool)):
        return node
    return str(node)


def load_document(text: str) -> tuple[dict, str]:
    """Return (document, format) or raise SpecError with a readable message."""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SpecError('The file is not valid JSON or YAML.') from exc
    if not isinstance(raw, dict):
        raise SpecError('The file does not contain an OpenAPI or Swagger document.')
    doc = _normalize(raw, frozenset(), 0, [0])
    if str(doc.get('openapi', '')).startswith('3.'):
        spec_format = 'openapi-' + str(doc['openapi'])
    elif str(doc.get('swagger', '')) == '2.0':
        spec_format = 'swagger-2.0'
    else:
        raise SpecError('Only OpenAPI 3.x and Swagger 2.0 documents are supported.')
    if not isinstance(doc.get('paths'), dict) or not doc['paths']:
        raise SpecError('The document has no API paths.')
    _check_refs(doc, doc)
    return doc, spec_format


def resolve_ref(doc: dict, ref) -> object:
    if not isinstance(ref, str) or not ref.startswith('#/'):
        raise SpecError(f'External reference "{ref}" is not supported. Bundle the spec into a single file first.')
    current = doc
    try:
        for part in ref[2:].split('/'):
            part = part.replace('~1', '/').replace('~0', '~')
            current = current[int(part)] if isinstance(current, list) else current[part]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise SpecError(f'Reference "{ref}" points to nothing in this document.') from exc
    return current


def _check_refs(doc, node):
    if isinstance(node, dict):
        if '$ref' in node:
            resolve_ref(doc, node['$ref'])
        for value in node.values():
            _check_refs(doc, value)
    elif isinstance(node, list):
        for value in node:
            _check_refs(doc, value)


def deref(doc, node, stack=(), budget=None, depth=0):
    """Inline local $refs. Circular references become a marker instead of recursing forever."""
    budget = budget if budget is not None else [0]
    budget[0] += 1
    if budget[0] > NODE_BUDGET or depth > MAX_DEPTH:
        raise SpecError('Schema references expand beyond the supported size.')
    if isinstance(node, dict):
        if '$ref' in node:
            ref = node['$ref']
            if ref in stack:
                return {'x-circular-ref': ref, 'description': f'Circular reference to {ref.rsplit("/", 1)[-1]}'}
            target = resolve_ref(doc, ref)
            merged = {**target, **{k: v for k, v in node.items() if k != '$ref'}} if isinstance(target, dict) else target
            return deref(doc, merged, (*stack, ref), budget, depth + 1)
        return {key: deref(doc, value, stack, budget, depth + 1) for key, value in node.items()}
    if isinstance(node, list):
        return [deref(doc, value, stack, budget, depth + 1) for value in node]
    return node


# --- Inventory ------------------------------------------------------------

def _pick_media(content: dict) -> str | None:
    if not content:
        return None
    if 'application/json' in content:
        return 'application/json'
    return next((m for m in content if 'json' in m), next(iter(content)))


def _first_example(media: dict):
    if 'example' in media:
        return media['example']
    examples = media.get('examples')
    if isinstance(examples, dict) and examples:
        first = next(iter(examples.values()))
        return first.get('value') if isinstance(first, dict) else first
    return None


def _parameter(param: dict, swagger: bool) -> dict:
    schema = param.get('schema')
    if schema is None and swagger:
        schema = {key: param[key] for key in SCHEMA_KEYS if key in param}
    return {'name': param.get('name', ''), 'in': param.get('in', ''), 'required': bool(param.get('required', param.get('in') == 'path')),
            'description': param.get('description', ''), 'deprecated': bool(param.get('deprecated', False)),
            'schema': schema or {}, 'example': param.get('example', param.get('x-example'))}


def _request_body(op: dict, params: list, swagger: bool, consumes: list) -> dict | None:
    if not swagger:
        body = op.get('requestBody')
        if not isinstance(body, dict):
            return None
        content = body.get('content', {}) or {}
        media_type = _pick_media(content)
        media = content.get(media_type, {}) if media_type else {}
        return {'required': bool(body.get('required', False)), 'description': body.get('description', ''),
                'mediaType': media_type, 'contentTypes': list(content), 'schema': media.get('schema', {}) or {},
                'example': _first_example(media)}
    body_param = next((p for p in params if p.get('in') == 'body'), None)
    if body_param:
        media_type = next((m for m in consumes if 'json' in m), consumes[0] if consumes else 'application/json')
        return {'required': bool(body_param.get('required', False)), 'description': body_param.get('description', ''),
                'mediaType': media_type, 'contentTypes': consumes, 'schema': body_param.get('schema', {}) or {},
                'example': body_param.get('x-example')}
    form = [p for p in params if p.get('in') == 'formData']
    if form:
        media_type = 'multipart/form-data' if any(p.get('type') == 'file' for p in form) or 'multipart/form-data' in consumes \
            else 'application/x-www-form-urlencoded'
        schema = {'type': 'object', 'properties': {p['name']: {k: p[k] for k in SCHEMA_KEYS if k in p} | (
            {'description': p['description']} if p.get('description') else {}) for p in form},
            'required': [p['name'] for p in form if p.get('required')]}
        return {'required': any(p.get('required') for p in form), 'description': '', 'mediaType': media_type,
                'contentTypes': [media_type], 'schema': schema, 'example': None}
    return None


def _responses(op: dict, swagger: bool, produces: list) -> dict:
    result = {}
    for status, response in (op.get('responses') or {}).items():
        if not isinstance(response, dict):
            continue
        if swagger:
            schema = response.get('schema', {}) or {}
            examples = response.get('examples') or {}
            example = next((v for k, v in examples.items() if 'json' in k), None) if isinstance(examples, dict) else None
            media_type = next((m for m in produces if 'json' in m), produces[0] if produces else None) if schema else None
        else:
            content = response.get('content', {}) or {}
            media_type = _pick_media(content)
            media = content.get(media_type, {}) if media_type else {}
            schema, example = media.get('schema', {}) or {}, _first_example(media)
        headers = sorted((response.get('headers') or {}).keys())
        result[str(status)] = {'description': response.get('description', ''), 'mediaType': media_type,
                               'schema': schema, 'example': example, 'headers': headers}
    return result


def _servers(doc: dict, swagger: bool) -> list[str]:
    if swagger:
        host = doc.get('host', '')
        if not host:
            return [doc.get('basePath', '/')] if doc.get('basePath') else []
        return [f"{scheme}://{host}{doc.get('basePath', '')}" for scheme in (doc.get('schemes') or ['https'])]
    return [s.get('url', '') for s in doc.get('servers', []) if isinstance(s, dict) and s.get('url')]


def parse_spec(text: str) -> dict:
    doc, spec_format = load_document(text)
    swagger = spec_format == 'swagger-2.0'
    info = doc.get('info') or {}
    security_schemes = deref(doc, (doc.get('securityDefinitions') if swagger else (doc.get('components') or {}).get('securitySchemes')) or {})
    global_security = doc.get('security', [])
    consumes, produces = doc.get('consumes', ['application/json']), doc.get('produces', ['application/json'])
    endpoints, warnings, seen_ids = [], [], set()
    for path, raw_item in doc['paths'].items():
        if not str(path).startswith('/'):
            raise SpecError(f'Path "{path}" must start with "/".')
        item = deref(doc, raw_item)
        if not isinstance(item, dict):
            raise SpecError(f'Path "{path}" is not a valid path item.')
        shared = [p for p in item.get('parameters', []) if isinstance(p, dict)]
        for method in HTTP_METHODS:
            op = item.get(method)
            if op is None:
                continue
            if not isinstance(op, dict):
                raise SpecError(f'{method.upper()} {path} is not a valid operation.')
            merged = {(p.get('in'), p.get('name')): p for p in shared}
            merged.update({(p.get('in'), p.get('name')): p for p in op.get('parameters', []) if isinstance(p, dict)})
            raw_params = list(merged.values())
            responses = _responses(op, swagger, op.get('produces', produces))
            if not responses:
                raise SpecError(f'{method.upper()} {path} does not document any responses.')
            operation_id = str(op.get('operationId') or (method + '_' + re.sub(r'\W+', '_', path).strip('_')))
            if operation_id in seen_ids:
                warnings.append(f'Duplicate operationId "{operation_id}" was renamed for {method.upper()} {path}.')
                suffix = 2
                while f'{operation_id}_{suffix}' in seen_ids:
                    suffix += 1
                operation_id = f'{operation_id}_{suffix}'
            seen_ids.add(operation_id)
            pointer = '#/paths/' + str(path).replace('~', '~0').replace('/', '~1') + '/' + method
            endpoint = {
                'operationId': operation_id, 'method': method.upper(), 'path': str(path),
                'summary': str(op.get('summary', '') or ''), 'description': str(op.get('description', '') or ''),
                'tags': [str(t) for t in op.get('tags', [])] or ['Other'], 'deprecated': bool(op.get('deprecated', False)),
                'parameters': [_parameter(p, swagger) for p in raw_params if p.get('in') in ('path', 'query', 'header', 'cookie')],
                'requestBody': _request_body(op, raw_params, swagger, op.get('consumes', consumes)),
                'responses': responses, 'security': op.get('security', global_security), 'pointer': pointer,
            }
            endpoints.append(endpoint)
    if not endpoints:
        raise SpecError('The document does not contain any operations.')
    return {'format': spec_format, 'title': str(info.get('title', '') or ''), 'version': str(info.get('version', '') or ''),
            'description': str(info.get('description', '') or ''), 'servers': _servers(doc, swagger),
            'securitySchemes': security_schemes, 'endpoints': endpoints, 'warnings': warnings}


def fingerprint(endpoint: dict) -> str:
    return digest(endpoint)


def compare(before: dict[tuple[str, str], str], after: dict[tuple[str, str], str]) -> dict:
    """Summarize endpoint changes between two versions; maps are (method, path) -> fingerprint."""
    def label(key):
        return f'{key[0]} {key[1]}'
    return {'added': sorted(label(k) for k in after.keys() - before.keys()),
            'removed': sorted(label(k) for k in before.keys() - after.keys()),
            'changed': sorted(label(k) for k in after.keys() & before.keys() if after[k] != before[k])}

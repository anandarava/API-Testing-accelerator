import json

import pytest

from studio.openapi import SpecError, parse_spec

from .conftest import EXAMPLES, upload

YAML_SPEC = """
openapi: 3.0.3
info: {title: Shop, version: '2.1'}
servers: [{url: https://api.shop.test/v1}]
components:
  securitySchemes:
    bearer: {type: http, scheme: bearer}
  schemas:
    Category:
      type: object
      properties:
        name: {type: string}
        parent: {$ref: '#/components/schemas/Category'}
security: [{bearer: []}]
paths:
  /orders/{orderId}:
    parameters:
      - {name: orderId, in: path, required: true, schema: {type: string, format: uuid}}
    get:
      operationId: getOrder
      summary: Get an order
      description: Returns the order. Cancelled orders are still returned.
      tags: [Orders]
      responses:
        200:
          description: Order found
          content:
            application/json:
              schema: {type: object, properties: {id: {type: string}, created: {type: string}}}
              example: {id: abc, created: 2026-01-01}
        404: {description: Not found}
  /categories:
    post:
      requestBody:
        required: true
        content:
          application/json:
            schema: {$ref: '#/components/schemas/Category'}
      responses:
        '201': {description: Created}
"""

SWAGGER = {
    'swagger': '2.0', 'info': {'title': 'Legacy', 'version': '1'}, 'host': 'legacy.test', 'basePath': '/api',
    'securityDefinitions': {'key': {'type': 'apiKey', 'in': 'header', 'name': 'X-Key'}},
    'paths': {
        '/users': {'post': {'operationId': 'createUser', 'consumes': ['application/json'],
                            'parameters': [{'in': 'body', 'name': 'body', 'required': True,
                                            'schema': {'type': 'object', 'required': ['email'],
                                                       'properties': {'email': {'type': 'string', 'format': 'email'}}}}],
                            'responses': {'201': {'description': 'Created', 'schema': {'type': 'object'}}}}},
        '/avatars': {'post': {'operationId': 'uploadAvatar',
                              'parameters': [{'in': 'formData', 'name': 'file', 'type': 'file', 'required': True},
                                             {'in': 'query', 'name': 'size', 'type': 'integer', 'maximum': 512}],
                              'responses': {'200': {'description': 'OK'}}}},
    },
}


def test_openapi_yaml_with_int_status_codes_dates_and_circular_refs():
    parsed = parse_spec(YAML_SPEC)
    assert parsed['title'] == 'Shop' and parsed['servers'] == ['https://api.shop.test/v1']
    order, category = parsed['endpoints']
    assert order['operationId'] == 'getOrder' and order['method'] == 'GET'
    assert order['description'].startswith('Returns the order')
    assert set(order['responses']) == {'200', '404'}
    assert order['responses']['200']['example'] == {'id': 'abc', 'created': '2026-01-01'}
    assert order['parameters'][0] | {} == {'name': 'orderId', 'in': 'path', 'required': True, 'description': '',
                                          'deprecated': False, 'schema': {'type': 'string', 'format': 'uuid'}, 'example': None}
    assert order['security'] == [{'bearer': []}]
    assert category['operationId'] == 'post_categories' and category['tags'] == ['Other']
    parent = category['requestBody']['schema']['properties']['parent']
    assert parent['x-circular-ref'] == '#/components/schemas/Category'


def test_swagger_2_body_and_form_data():
    parsed = parse_spec(json.dumps(SWAGGER))
    assert parsed['format'] == 'swagger-2.0' and parsed['servers'] == ['https://legacy.test/api']
    create, avatar = parsed['endpoints']
    assert create['requestBody']['schema']['required'] == ['email']
    assert create['responses']['201']['schema'] == {'type': 'object'}
    assert avatar['requestBody']['mediaType'] == 'multipart/form-data'
    assert avatar['parameters'][0]['schema'] == {'type': 'integer', 'maximum': 512}
    assert parsed['securitySchemes']['key']['name'] == 'X-Key'


@pytest.mark.parametrize('text, message', [
    ('not: [valid', 'not valid JSON or YAML'),
    ('{"openapi": "3.0.0", "paths": {}}', 'no API paths'),
    ('{"asyncapi": "2.0"}', 'Only OpenAPI 3.x and Swagger 2.0'),
    ('{"openapi": "3.0.0", "paths": {"/a": {"get": {"responses": {"200": {"$ref": "other.yaml#/x"}}}}}}', 'External reference'),
    ('{"openapi": "3.0.0", "paths": {"/a": {"get": {"responses": {}}}}}', 'does not document any responses'),
    ('a: &a [*a]', 'recursive YAML alias'),
])
def test_invalid_documents_have_clear_errors(text, message):
    with pytest.raises(SpecError, match=message):
        parse_spec(text)


def test_upload_versions_and_change_summary(project):
    lead, pid = project
    first = upload(lead, pid, 'shop.yaml', YAML_SPEC, 'application/yaml')
    assert first.status_code == 200 and first.json()['version'] == 1 and first.json()['endpointCount'] == 2
    assert upload(lead, pid, 'shop.yaml', YAML_SPEC, 'application/yaml').status_code == 409

    # v2: one endpoint edited, /categories removed, /orders added.
    changed = YAML_SPEC.replace('summary: Get an order', 'summary: Fetch an order').split('  /categories:')[0]
    changed += "  /orders:\n    get:\n      responses: {'200': {description: ok}}\n"
    second = upload(lead, pid, 'shop.yaml', changed, 'application/yaml').json()
    assert second['version'] == 2
    assert second['changes'] == {'added': ['GET /orders'], 'removed': ['POST /categories'],
                                 'changed': ['GET /orders/{orderId}']}

    listing = lead.get(f'/api/projects/{pid}/endpoints').json()
    assert listing['spec']['version'] == 2
    assert [e['path'] for e in listing['endpoints']] == ['/orders/{orderId}', '/orders']
    detail = lead.get(f'/api/projects/{pid}/endpoints/{listing["endpoints"][0]["id"]}').json()
    assert detail['summary'] == 'Fetch an order' and '404' in detail['responses']
    assert [s['version'] for s in lead.get(f'/api/projects/{pid}/specs').json()] == [2, 1]


def test_upload_rejects_wrong_file_type_and_bad_content(project):
    lead, pid = project
    assert upload(lead, pid, 'notes.txt', 'hello').status_code == 400
    response = upload(lead, pid, 'bad.json', '{"openapi": "3.0.0"}')
    assert response.status_code == 400 and 'no API paths' in response.json()['detail']


def test_example_specs_parse():
    for path in EXAMPLES.glob('*.yaml'):
        assert parse_spec(path.read_text(encoding='utf-8'))['endpoints'], path

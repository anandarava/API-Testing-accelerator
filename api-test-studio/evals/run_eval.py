"""Measure the agents and skills on a fixed API, so every prompt change is compared on the same input.

Runs the real unit, flow and role pipelines with the Claude Code you are signed in to (this spends Claude
usage), scores the results with the same code checks the portal uses, and compares with the previous run.

    .venv\\Scripts\\python -m evals.run_eval                       # Petstore, unit + flows + roles
    .venv\\Scripts\\python -m evals.run_eval --modules unit --endpoints 3 --model sonnet
    .venv\\Scripts\\python -m evals.run_eval --spec my-api.yaml --roles my-roles.csv
"""
import argparse
import json
import sys
import time
from pathlib import Path

from contracts.coverage import gaps as unit_gaps, obligations
from contracts.flows import dependencies, gaps as flow_gaps, operation_index, requirements, unproven_claims
from contracts.roles import role_gaps, role_requirements
from helper import claude, flow_cases, role_cases, unit_cases
from studio.documents import extract_text
from studio.openapi import parse_spec

HERE = Path(__file__).resolve().parent
RESULTS = HERE / 'results'
SERIOUS = ('blocker', 'major')


def _quiet(message, percent=None, detail=None):
    print(f'  {message}', file=sys.stderr)


def run_unit(parsed: dict, endpoints: list[dict]) -> dict:
    results = []
    job = {'api': {'title': parsed['title'], 'securitySchemes': parsed['securitySchemes']},
           'endpoints': [{'id': e['operationId'], 'details': e} for e in endpoints]}
    unit_cases.generate(job, _quiet, results.append)
    rows = []
    for result in results:
        endpoint = next(e for e in endpoints if e['operationId'] == result['endpointId'])
        if result.get('error'):
            rows.append({'endpoint': endpoint['operationId'], 'error': result['error'][:200]})
            continue
        required = obligations(endpoint, parsed['securitySchemes'])
        missing = unit_gaps(required, result['checklist'])
        review = result.get('review') or {}
        rows.append({'endpoint': endpoint['operationId'], 'requirements': len(required), 'covered': len(required) - len(missing),
                     'scenarios': len(result['checklist']), 'cases': len(result['cases']),
                     'flaggedByCode': sum(1 for c in result['cases'] if c.get('confirmationNote', '').startswith('Code check:')),
                     'reviewSerious': sum(1 for f in review.get('findings', []) if f['severity'] in SERIOUS)})
    return {'endpoints': rows, 'results': results}


def run_flows(parsed: dict) -> dict:
    submitted = []
    endpoints = parsed['endpoints']
    flow_cases.generate({'api': {'title': parsed['title']}, 'endpoints': [{'id': e['operationId'], 'details': e} for e in endpoints]},
                        _quiet, submitted.append)
    domain = next(s['domain'] for s in submitted if s['stage'] == 'domain')
    plan = [o for s in submitted for o in s.get('plan', [])]
    required = requirements(endpoints, dependencies(endpoints), domain)
    missing = flow_gaps(required, plan)
    by_category = {}
    for item in required:
        row = by_category.setdefault(item['category'], {'total': 0, 'covered': 0})
        row['total'] += 1
        row['covered'] += item not in missing
    final = next((s for s in submitted if s['stage'] == 'final'), {})
    return {'flows': len(plan), 'requirements': len(required), 'covered': len(required) - len(missing), 'byCategory': by_category,
            'unprovenClaims': sum(len(v) for v in unproven_claims(plan, required).values()),
            'entities': len(domain.get('entities', [])), 'rules': len(domain.get('businessRules', [])),
            'reviewSerious': sum(1 for f in (final.get('review') or {}).get('findings', []) if f['severity'] in SERIOUS)}


def run_roles(parsed: dict, roles_file: Path, unit: dict | None, limit: int) -> dict:
    text = extract_text(roles_file.name, roles_file.read_bytes())
    views = [{'operationId': e['operationId'], 'method': e['method'], 'path': e['path'], 'summary': e.get('summary', ''),
              'description': (e.get('description') or '')[:400], 'tags': e.get('tags', []), 'security': e.get('security', []),
              'statuses': sorted(e.get('responses', {}))} for e in parsed['endpoints']]
    model = role_cases.analyze({'document': {'filename': roles_file.name, 'text': text},
                                'api': {'title': parsed['title'], 'securitySchemes': parsed['securitySchemes']},
                                'operations': views}, _quiet)['model']
    unknown = sum(len(row['unknown']) for row in model['operations'])
    base = {}
    for result in (unit or {}).get('results', []):
        positive = next((c for c in result.get('cases', []) if c['category'] == 'positive'
                         and 200 <= int(c['expected'].get('status') or 0) < 300), None)
        if positive:
            base[result['endpointId']] = {'code': positive['scenarioKey'], 'title': positive['title'], 'approved': False,
                                          **{k: positive.get(k) for k in ('objective', 'preconditions', 'request', 'expected', 'testData', 'cleanup')}}
    chosen = [e for e in parsed['endpoints'] if role_requirements(model, e['operationId'])][:limit]
    submitted = []
    role_cases.generate({'model': model, 'operationIndex': [operation_index(e) for e in parsed['endpoints']],
                         'endpoints': [{'id': e['operationId'], 'details': e, **({'baseCase': base[e['operationId']]}
                                                                                 if e['operationId'] in base else {})} for e in chosen]},
                        _quiet, submitted.append)
    rows = []
    for result in submitted:
        required = role_requirements(model, result['endpointId'])
        rows.append({'endpoint': result['endpointId'], 'checks': len(required), 'error': result.get('error', '')[:200],
                     'covered': len(required) - len(role_gaps(required, result.get('cases', []))), 'cases': len(result.get('cases', []))})
    return {'roles': [r['name'] for r in model['roles']], 'unknownPermissions': unknown, 'endpoints': rows}


def summary(report: dict) -> dict:
    """The few numbers compared between runs."""
    out = {'tokensSent': report['usage']['inputTokens'] + report['usage']['cacheReadTokens'] + report['usage']['cacheWriteTokens'],
           'outputTokens': report['usage']['outputTokens'], 'calls': report['usage']['calls'], 'seconds': report['seconds']}
    unit = report.get('unit')
    if unit:
        ok = [r for r in unit['endpoints'] if 'error' not in r]
        out['unitCoverage%'] = round(100 * sum(r['covered'] for r in ok) / max(1, sum(r['requirements'] for r in ok)), 1)
        out['unitCases'] = sum(r['cases'] for r in ok)
        out['unitFlaggedByCode'] = sum(r['flaggedByCode'] for r in ok)
        out['unitReviewSerious'] = sum(r['reviewSerious'] for r in ok)
    flows = report.get('flows')
    if flows:
        out['flowCoverage%'] = round(100 * flows['covered'] / max(1, flows['requirements']), 1)
        out['flows'] = flows['flows']
        out['flowUnprovenClaims'] = flows['unprovenClaims']
    roles = report.get('roles')
    if roles:
        rows = [r for r in roles['endpoints'] if not r['error']]
        out['roleCoverage%'] = round(100 * sum(r['covered'] for r in rows) / max(1, sum(r['checks'] for r in rows)), 1)
        out['roleCases'] = sum(r['cases'] for r in rows)
    for agent, stats in report['usage'].get('agents', {}).items():
        if stats.get('checked'):
            out[f'{agent} check failures %'] = round(100 * stats['checkFailed'] / stats['checked'], 1)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--spec', type=Path, default=HERE / 'petstore.yaml')
    parser.add_argument('--roles', type=Path, default=HERE / 'petstore-roles.csv')
    parser.add_argument('--modules', default='unit,flows,roles', help='Comma separated: unit, flows, roles')
    parser.add_argument('--endpoints', type=int, default=5, help='How many endpoints for unit and role cases')
    parser.add_argument('--model', default='', help='Claude model alias or id; empty = account default')
    parser.add_argument('--writer-model', default='', help='Model for writing case details; empty = same model')
    args = parser.parse_args(argv)
    modules = {m.strip() for m in args.modules.split(',') if m.strip()}
    parsed = parse_spec(args.spec.read_text(encoding='utf-8'))
    claude.job_model.begin(args.model or None, args.writer_model or None)
    started = time.time()
    report = {'spec': args.spec.name, 'modules': sorted(modules), 'model': args.model or 'default', 'startedAt': started}
    if 'unit' in modules:
        print('Unit test cases...', file=sys.stderr)
        report['unit'] = run_unit(parsed, parsed['endpoints'][:args.endpoints])
    if 'flows' in modules:
        print('Flow test cases...', file=sys.stderr)
        report['flows'] = run_flows(parsed)
    if 'roles' in modules and args.roles.is_file():
        print('Role test cases...', file=sys.stderr)
        report['roles'] = run_roles(parsed, args.roles, report.get('unit'), args.endpoints)
    report['seconds'] = round(time.time() - started)
    report['usage'] = claude.job_model.usage()
    report['summary'] = summary(report)
    if 'unit' in report:
        report['unit'].pop('results', None)
    RESULTS.mkdir(exist_ok=True)
    previous = sorted(RESULTS.glob('*.json'))
    path = RESULTS / time.strftime('%Y%m%d-%H%M%S.json')
    path.write_text(json.dumps(report, indent=1), encoding='utf-8')
    before = json.loads(previous[-1].read_text(encoding='utf-8'))['summary'] if previous else {}
    print(f'\nSaved {path}\n')
    width = max(len(k) for k in report['summary'])
    for key, value in report['summary'].items():
        delta = ''
        if isinstance(before.get(key), (int, float)) and isinstance(value, (int, float)):
            change = value - before[key]
            delta = f'   ({"+" if change >= 0 else ""}{round(change, 1)} vs previous run)'
        print(f'{key.ljust(width)}  {value}{delta}')


if __name__ == '__main__':
    main()

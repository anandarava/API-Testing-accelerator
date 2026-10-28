"""Regenerating a single unit case or flow with Claude."""
import re

from pydantic import Field

from . import Strict
from .checks import response_check_problems
from .flows import FlowCaseDraft
from .unit import TestCaseDraft

PLACEHOLDER = re.compile(r'\{\{steps\.(S\d+)\.([A-Za-z][A-Za-z0-9_]*)\}\}')


class RegenerateResult(Strict):
    caseId: str
    unitCase: TestCaseDraft | None = None
    flowCase: FlowCaseDraft | None = None
    notes: str = Field(default='', max_length=2000)


def validate_detailed_flow(flow: dict, operations: dict[str, dict]) -> list[str]:
    """Problems in a detailed flow: unknown operations, undocumented statuses, unchecked success bodies,
    values used before capture."""
    problems, captured, keys = [], set(), set()
    for step in flow['steps']:
        where = step['key']
        if step['key'] in keys:
            problems.append(f'{where}: duplicate step key.')
        keys.add(step['key'])
        operation = operations.get(step['operationId'])
        if not operation:
            problems.append(f"{where}: operation {step['operationId']} does not exist.")
        elif step['expected'].get('status') and str(step['expected']['status']) not in operation.get('responses', {}):
            problems.append(f"{where}: status {step['expected']['status']} is not documented for {step['operationId']}.")
        else:
            problems += [f'{where}: {p}' for p in response_check_problems(step['expected'], operation)]
        for source, name in PLACEHOLDER.findall(repr(step['request'])):
            if f'{source}.{name}' not in captured:
                problems.append(f'{where}: uses {{{{steps.{source}.{name}}}}} before any earlier step captures it.')
        for capture in step.get('captures', []):
            captured.add(f"{step['key']}.{capture['name']}")
    return problems

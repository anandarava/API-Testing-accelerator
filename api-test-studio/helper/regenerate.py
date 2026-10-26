"""Regenerate one unit case or flow, following the QA's instruction and earlier review notes."""
import tempfile

from contracts.cases import validate_detailed_flow
from contracts.flows import FlowCaseSet
from contracts.unit import CaseSet

from .claude import ClaudeError, run_agent


def _instruction_findings(job_input: dict, key: str) -> list[dict]:
    findings = []
    if job_input.get('instruction'):
        findings.append({'severity': 'major', 'issue': 'QA instruction: ' + job_input['instruction'], 'suggestion': job_input['instruction']})
    if job_input.get('reviewComment'):
        findings.append({'severity': 'major', 'issue': 'Reviewer comment: ' + job_input['reviewComment'], 'suggestion': ''})
    for finding in job_input.get('findings', []):
        findings.append({'severity': finding.get('severity', 'minor'), 'issue': finding.get('issue', ''), 'suggestion': finding.get('suggestion', '')})
    if not findings:
        findings.append({'severity': 'major', 'issue': 'Rewrite this case so it is as precise, realistic and executable as possible.', 'suggestion': ''})
    return [{**f, 'scenarioKey' if job_input['module'] == 'unit' else 'flowKey': key} for f in findings]


def regenerate_unit(job_input: dict, agent, workspace) -> dict:
    case = job_input['case']
    key = case['scenarioKey']
    scenario = {'key': key, 'title': case['title'], 'category': case['category'], 'condition': case['content'].get('condition', ''),
                'expectedStatus': case['content']['expected'].get('status'), 'covers': case['content'].get('covers', []),
                'source': case['content'].get('source', ''), 'priority': case['priority'],
                'needsConfirmation': case['needsConfirmation'], 'confirmationNote': case['content'].get('confirmationNote', '')}
    current = {'scenarioKey': key, 'title': case['title'], 'category': case['category'], 'priority': case['priority'],
               'needsConfirmation': case['needsConfirmation'], 'confirmationNote': case['content'].get('confirmationNote', ''),
               **{k: case['content'][k] for k in ('objective', 'preconditions', 'request', 'expected', 'testData', 'cleanup')}}
    task = {'mode': 'revise', 'endpoint': job_input['endpoint'], 'api': job_input['api'], 'scenarios': [scenario],
            'onlyKeys': [key], 'currentCases': [current], 'reviewFindings': _instruction_findings(job_input, key)}
    cases = agent('unit-case-writer', task, CaseSet, cwd=workspace, max_turns=4)['cases']
    match = next((c for c in cases if c['scenarioKey'] == key), None)
    if not match:
        raise ClaudeError('Claude did not return the regenerated case.')
    return match


def regenerate_flow(job_input: dict, agent, workspace) -> dict:
    case = job_input['case']
    key = case['scenarioKey']
    content = case['content']
    outline = {'key': key, 'title': case['title'], 'type': case['category'], 'goal': content.get('goal') or content.get('objective', ''),
               'priority': case['priority'], 'covers': content.get('covers', []),
               'steps': [{'key': s['key'], 'operationId': s['operationId'], 'purpose': s['purpose'],
                          'expectedStatus': s['expected'].get('status'), 'captures': s.get('captures', [])} for s in content['steps']]}
    current = {'flowKey': key, 'title': case['title'], 'type': case['category'], 'priority': case['priority'],
               'needsConfirmation': case['needsConfirmation'], 'confirmationNote': content.get('confirmationNote', ''),
               **{k: content[k] for k in ('objective', 'preconditions', 'steps', 'testData', 'cleanup')}}
    operations = {op['operationId']: op for op in job_input['operations']}
    task = {'mode': 'revise', 'allowStepChanges': True, 'outlines': [outline], 'operations': job_input['operations'],
            'domain': job_input.get('domain'), 'currentFlows': [current], 'reviewFindings': _instruction_findings(job_input, key)}
    problems = []
    for _attempt in range(2):
        if problems:
            task['reviewFindings'] = task['reviewFindings'] + [{'flowKey': key, 'severity': 'blocker', 'issue': p, 'suggestion': ''} for p in problems]
        flows = agent('flow-case-writer', task, FlowCaseSet, cwd=workspace, max_turns=4)['flows']
        match = next((f for f in flows if f['flowKey'] == key), None)
        if not match:
            raise ClaudeError('Claude did not return the regenerated flow.')
        problems = validate_detailed_flow(match, operations)
        if not problems:
            return match
    raise ClaudeError('The regenerated flow is still invalid: ' + ' '.join(problems[:5]))


def generate(job_input: dict, report, submit=None, agent=run_agent) -> dict:
    label = job_input['case']['code']
    report(f'Claude is rewriting {label}', 10)
    with tempfile.TemporaryDirectory(prefix='studio-regenerate-') as workspace:
        if job_input['module'] == 'unit':
            result = {'caseId': job_input['caseId'], 'unitCase': regenerate_unit(job_input, agent, workspace)}
        else:
            result = {'caseId': job_input['caseId'], 'flowCase': regenerate_flow(job_input, agent, workspace)}
    if submit:
        submit(result)
    report('Finished', 100)
    return {'caseId': job_input['caseId']}

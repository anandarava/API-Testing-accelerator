"""Project assistant messages: answers from a snapshot of the project, and drafts of flows the user says are missing.

The portal sends the project as small text files (an index, flows, unit cases, coverage, activity, rules). The
agent reads them with Read/Glob/Grep, so the same works on Claude Code and on a local model. Actions are only
proposed here; the portal runs them after the user confirms.
"""
import functools
import tempfile
from pathlib import Path

from contracts.assistant import AssistantReply
from contracts.flows import JOURNEYS, FlowPlan, process_areas, validate_plan

from . import claude
from .claude import ClaudeError, run_agent
from .flow_cases import FlowPipeline

TOOLS = ('Read', 'Glob', 'Grep')
MAX_TURNS = 30
MAX_DRAFTS = 6


def write_snapshot(root: Path, files: dict[str, str]):
    """Write the project files; paths that would leave the folder are skipped."""
    for relative, text in files.items():
        target = (root / relative).resolve()
        if root not in target.parents:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(text), encoding='utf-8')


def area_of(outline: dict, areas: list[dict]) -> str:
    """The business area a drafted flow belongs to: its only area, or the cross-area journeys."""
    reached = process_areas({'steps': [s['operationId'] for s in outline['steps']]}, areas)
    return reached[0] if len(reached) == 1 else JOURNEYS


def draft_flows(requests: list[dict], design: dict | None, call, meter) -> list[dict]:
    """Design, check and write the flows the user asked for, with the same pipeline as a full design."""
    if not design:
        raise ClaudeError('Design the flows of this project first; requested flows build on that analysis.')
    with tempfile.TemporaryDirectory(prefix='studio-drafts-') as workspace:
        pipeline = FlowPipeline(design['api'], design['endpoints'], call, workspace, lambda *args: None, meter=meter)
        outlines = design.get('outlines', [])
        pipeline.restore(design['domain'], outlines)
        group = pipeline.journeys([])
        suggestions = [{'flowKey': 'plan', 'severity': 'major', 'issue': f"{r['title']}: {r['description']}",
                        'suggestion': r['description']} for r in requests]
        existing = [{'key': o['key'], 'title': o['title']} for o in outlines][:400]
        planned = pipeline.keys.renumber(pipeline.call('flow-designer', pipeline.context(
            group, mode='add-suggested', reviewSuggestions=suggestions, existingFlows=existing), FlowPlan)['flows'])
        structure = validate_plan(planned, design['endpoints'])
        checked = pipeline.clean_covers(pipeline.repair(planned, group))[:MAX_DRAFTS]
        if not checked:
            raise ClaudeError('The drafted flow failed the structure checks even after a fix: ' + '; '.join(structure[:3]))
        written = pipeline.write(checked, attempts=3)  # a requested flow is often long; give the writer one more try
        if not written:
            found = [p for problems in pipeline.write_problems.values() for p in problems]
            raise ClaudeError('The drafted flow could not be written so that it passes the checks: ' + '; '.join(found[:3]))
        return [{'outline': o, 'flow': written[o['key']], 'area': area_of(o, pipeline.areas)} for o in checked if o['key'] in written]


def answer(job_input: dict, report, submit=None, meter=None, agent=run_agent) -> dict:
    meter = meter or claude.job_model
    call = functools.partial(agent, meter=meter)
    snapshot = job_input.get('snapshot') or {}
    with tempfile.TemporaryDirectory(prefix='studio-assistant-') as folder:
        root = Path(folder).resolve()
        write_snapshot(root, snapshot.get('files') or {})
        report('Reading the project', 20)
        task = {'question': job_input['question'], 'history': job_input.get('history', []),
                'context': job_input.get('context', {}), 'project': snapshot.get('project', {}),
                'user': job_input.get('user', {})}
        reply = call('project-assistant', task, AssistantReply, cwd=root, tools=TOOLS, max_turns=MAX_TURNS)
    drafts, error = [], ''
    if reply.get('flowRequests'):
        count = len(reply['flowRequests'])
        report(f'Designing and checking the {"flow" if count == 1 else f"{count} flows"} you described', 55)
        try:
            drafts = draft_flows(reply['flowRequests'], snapshot.get('design'), call, meter)
        except ClaudeError as exc:
            error = str(exc)[:600]
        if not drafts and not error:
            error = 'The flow could not be designed so that it passes the checks. Describe it in more detail and try again.'
    report('Done', 100)
    return {'reply': reply, 'drafts': drafts, 'draftError': error}

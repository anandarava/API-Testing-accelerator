"""Flow test case generation for a whole API.

1. dependencies (code) + domain analysis (Claude), saved to the portal at once;
2. design groups run in parallel (PARALLEL_GROUPS at a time): one for cross-area end-to-end
   journeys and one per business area. Each group designs, validates, writes, reviews and fixes its
   flows, then saves them;
3. the combined coverage check over all flows fills any remaining gaps, then the final save.
"""
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from contracts.cases import validate_detailed_flow
from contracts.checks import credential_header_problems, placeholder_problems
from contracts.flows import (JOURNEYS, DomainModel, FlowCaseSet, FlowPlan, FlowReview, brief_endpoint, compact_endpoint,
                             chunk_operations, cross_area_requirements, dependencies, dependency_hints, domain_for, flow_signature,
                             for_prompt, merge_domains,
                             gaps, operation_index, relevant_requirements, requirement_operations, requirements, satisfied,
                             split_areas, unproven_claims, validate_plan)

from . import claude
from .claude import ClaudeError, run_agent

PARALLEL_GROUPS = 5
ANALYST_SPLIT = 80  # APIs with more operations are analysed in parts ...
ANALYST_PART = 50  # ... of about this many operations each
MAX_GAP_ROUNDS = 2
WRITER_BATCH = 5  # at most this many flows per writer call ...
WRITER_STEPS = 40  # ... and at most about this many steps, so long journeys get calls of their own
MAX_FINDINGS = 15
SERIOUS = ('blocker', 'major')
SEVERITY_ORDER = {'blocker': 0, 'major': 1, 'minor': 2}


class KeyAllocator:
    """Hands out unique flow keys (F01, F02, ...) across groups running in parallel."""

    def __init__(self, start: int = 1):
        self.lock, self.next = threading.Lock(), start

    def renumber(self, flows: list[dict]) -> list[dict]:
        with self.lock:
            out = []
            for flow in flows:
                out.append({**flow, 'key': f'F{self.next:02d}'})
                self.next += 1
            return out


def _problems_by_flow(problems: list[str]) -> dict:
    grouped = {}
    for problem in problems:
        grouped.setdefault(problem.split('/', 1)[0], []).append(problem)
    return grouped


class FlowPipeline:
    def __init__(self, api: dict, endpoints: list[dict], agent, workspace, report):
        self.api, self.endpoints, self.agent, self.workspace, self.report = api, endpoints, agent, workspace, report
        self.operations = [compact_endpoint(e) for e in endpoints]
        self.by_id = {op['operationId']: op for op in self.operations}
        self.index = [operation_index(e) for e in endpoints]  # one line per operation, for setup steps
        self.edges = dependencies(endpoints)
        self.hints = dependency_hints(self.edges, endpoints)
        self.keys = KeyAllocator()
        self.domain, self.required, self.areas = None, [], []
        self.endpoint_by_id = {e['operationId']: e for e in endpoints}
        self.seen, self.seen_lock = {}, threading.Lock()  # flow signature -> key, across groups running in parallel

    def call(self, agent, task, schema):
        return self.agent(agent, task, schema, cwd=self.workspace, max_turns=4)

    # --- analysis -------------------------------------------------------------------------------

    def analyze(self):
        if len(self.endpoints) <= ANALYST_SPLIT:
            self.domain = self.call('flow-domain-analyst', {'api': self.api, 'operations': self.operations,
                                                            'dependencies': self.hints}, DomainModel)
        else:
            # Large APIs: each part is analysed in parallel with a one-line index of the whole API, then merged in code.
            parts = chunk_operations(self.endpoints, ANALYST_PART)

            def one(index_part):
                index, part = index_part
                ops = {e['operationId'] for e in part}
                return self.call('flow-domain-analyst', {
                    'api': self.api, 'part': {'number': index + 1, 'of': len(parts)},
                    'operations': self.details(ops), 'operationIndex': self.index,
                    'dependencies': dependency_hints(self.edges, self.endpoints, ops)}, DomainModel)
            with ThreadPoolExecutor(max_workers=min(len(parts), PARALLEL_GROUPS), thread_name_prefix='analyst') as pool:
                self.domain = merge_domains(list(pool.map(one, enumerate(parts))))
        self.required = requirements(self.endpoints, self.edges, self.domain)
        self.areas = split_areas(self.domain, self.endpoints)
        self.domain['areas'] = self.areas
        return self.domain

    def restore(self, domain: dict, outlines: list[dict]):
        """Continue a stopped design from its saved analysis; new flow keys follow the existing ones."""
        self.domain = domain
        self.required = requirements(self.endpoints, self.edges, self.domain)
        self.areas = split_areas(self.domain, self.endpoints)
        self.domain['areas'] = self.areas
        numbers = [int(o['key'][1:]) for o in outlines if str(o.get('key', ''))[1:].isdigit()]
        self.keys = KeyAllocator(max(numbers, default=0) + 1)
        self.unique(outlines)  # flows that already exist count as seen
        return self.domain

    def unique(self, flows: list[dict]) -> list[dict]:
        """Drop flows that repeat an earlier flow's journey (same type, steps and statuses), in any group."""
        out = []
        with self.seen_lock:
            for flow in flows:
                signature = flow_signature(flow)
                if signature in self.seen and self.seen[signature] != flow['key']:
                    continue
                self.seen[signature] = flow['key']
                out.append(flow)
        return out

    def groups(self) -> list[dict]:
        """The cross-area journeys group first (when there is more than one area), then one group per area."""
        out = []
        if len(self.areas) > 1:
            out.append({'name': JOURNEYS, 'kind': 'journeys', 'operations': set(self.by_id),
                        'requirements': cross_area_requirements(self.required, self.domain, self.areas),
                        'scope': {'kind': 'journeys', 'name': JOURNEYS, 'areas': [{'name': a['name'], 'description': a['description'],
                                                                                    'operations': a['operations']} for a in self.areas]}})
        for area in self.areas:
            ops = set(area['operations'])
            out.append({'name': area['name'], 'kind': 'area', 'operations': ops,
                        'requirements': relevant_requirements(self.required, ops, self.domain),
                        'scope': {'kind': 'area', 'name': area['name'], 'description': area['description'], 'operations': area['operations']}})
        return out

    def details(self, operations) -> list[dict]:
        return [self.by_id[op] for op in self.by_id if op in operations]

    def context(self, group: dict | None, **extra):
        """What one designer call needs. Full contracts only for the operations it designs; a one-line index for the rest."""
        if group and group['kind'] == 'area':
            ops = group['operations']
            return {'domain': domain_for(self.domain, ops, {r['id'] for r in group['requirements']}),
                    'operations': self.details(ops), 'operationIndex': self.index,
                    'dependencies': dependency_hints(self.edges, self.endpoints, ops),
                    'requirements': for_prompt(group['requirements']), 'scope': group['scope'], **extra}
        if group:  # cross-area journeys: every operation briefly, and how ids pass between them
            core = {k: v for k, v in self.domain.items() if k not in ('areas', 'assumptions')}
            return {'domain': core, 'operations': [brief_endpoint(e) for e in self.endpoints], 'dependencies': self.hints,
                    'requirements': for_prompt(group['requirements']), 'scope': group['scope'], **extra}
        missing = extra.get('missingRequirements')
        focus = set().union(*(requirement_operations(r, self.domain) for r in missing)) if missing else set(self.by_id)
        task = {'domain': domain_for(self.domain, focus, {r['id'] for r in missing or self.required}),
                'operations': self.details(focus), 'operationIndex': self.index,
                'dependencies': dependency_hints(self.edges, self.endpoints, focus), **extra}
        if missing:
            task['missingRequirements'] = for_prompt(missing)
        else:
            task['requirements'] = for_prompt(self.required)
        return task

    # --- design -----------------------------------------------------------------------------------

    def repair(self, flows: list[dict], group: dict | None) -> list[dict]:
        """Ask the designer to fix structural problems once; drop flows that are still broken."""
        problems = _problems_by_flow(validate_plan(flows, self.endpoints))
        claude.job_model.check('flow-designer', len(flows), len(problems))
        if not problems:
            return flows
        broken = [f for f in flows if f['key'] in problems]
        fixed = self.call('flow-designer', self.context(group, mode='fix', flows=broken,
                                                        problems=[p for f in broken for p in problems[f['key']]]), FlowPlan)['flows']
        replacement = {f['key']: f for f in fixed if f['key'] in problems}
        flows = [replacement.get(f['key'], f) for f in flows]
        still = _problems_by_flow(validate_plan(flows, self.endpoints))
        return [f for f in flows if f['key'] not in still]

    def clean_covers(self, flows: list[dict]) -> list[dict]:
        known = {r['id'] for r in self.required}
        for flow in flows:
            flow['covers'] = [rid for rid in flow['covers'] if rid in known]
        return flows

    def design(self, group: dict) -> list[dict]:
        flows = self.keys.renumber(self.call('flow-designer', self.context(group, mode='plan'), FlowPlan)['flows'])
        return self.unique(self.clean_covers(self.repair(flows, group)))

    def fill_gaps(self, outlines: list[dict]) -> tuple[list[dict], int]:
        """Combined coverage check over every group's flows; uncovered requirements go back to Claude."""
        added, rounds = [], 1
        for _ in range(MAX_GAP_ROUNDS):
            missing = gaps(self.required, outlines + added)
            if not missing:
                break
            rounds += 1
            unproven = unproven_claims(outlines + added, self.required)
            existing = [{**{k: f[k] for k in ('key', 'title', 'covers')}, **({'unprovenCovers': unproven[f['key']]} if f['key'] in unproven else {})}
                        for f in outlines + added]
            extra = self.call('flow-designer', self.context(
                None, mode='fill-gaps', missingRequirements=missing, existingFlows=existing), FlowPlan)['flows']
            added += self.unique(self.clean_covers(self.repair(self.keys.renumber(extra), None)))
        return added, rounds

    # --- writing, review, fixes ---------------------------------------------------------------------

    @staticmethod
    def batches(outlines: list[dict]) -> list[list[dict]]:
        """Writer calls of at most WRITER_BATCH flows and about WRITER_STEPS steps each."""
        out, current, steps = [], [], 0
        for outline in outlines:
            size = len(outline['steps'])
            if current and (len(current) >= WRITER_BATCH or steps + size > WRITER_STEPS):
                out.append(current)
                current, steps = [], 0
            current.append(outline)
            steps += size
        return out + ([current] if current else [])

    def write(self, outlines: list[dict], mode='write', current=None, findings=None) -> dict:
        written = {}
        by_key = {o['key']: o for o in outlines}
        for batch in self.batches(outlines):
            problems: dict[str, list[str]] = {}
            for _attempt in range(2):
                pending = [o for o in batch if o['key'] not in written]
                if not pending:
                    break
                used = {s['operationId'] for o in pending for s in o['steps']}
                covers = {rid for o in pending for rid in o.get('covers', [])}
                task = {'mode': mode, 'outlines': pending, 'domain': domain_for(self.domain, used, covers),
                        'operations': self.details(used)}
                if mode == 'revise':
                    task.update(currentFlows=[current[o['key']] for o in pending],
                                reviewFindings=[f for f in findings if f['flowKey'] in {o['key'] for o in pending}])
                if problems:
                    task['previousProblems'] = {key: found for key, found in problems.items() if key in by_key}
                problems = {}
                for flow in self.call('flow-case-writer', task, FlowCaseSet)['flows']:
                    outline = by_key.get(flow['flowKey'])
                    if not outline:
                        continue
                    # The detailed flow must keep the validated operation sequence and be executable as written.
                    if [s['operationId'] for s in flow['steps']] != [s['operationId'] for s in outline['steps']]:
                        problems[flow['flowKey']] = ['The steps must follow the outline exactly: same operations in the same order.']
                        continue
                    found = validate_detailed_flow(flow, self.endpoint_by_id)
                    for st in flow['steps']:
                        found += [f"{st['key']}: {p}" for p in credential_header_problems(st.get('request') or {})
                                  + placeholder_problems(st.get('request') or {})]
                    if found:
                        problems[flow['flowKey']] = found
                    else:
                        written[flow['flowKey']] = flow
                claude.job_model.check('flow-case-writer', len(pending), len(problems) + len([o for o in pending if o['key'] not in written and o['key'] not in problems]))
        return written

    def review(self, outlines: list[dict], flows: list[dict], group: dict | None, mode: str = 'review') -> dict:
        scope_requirements = group['requirements'] if group else self.required
        done = satisfied(outlines, {r['id']: r.get('check') for r in scope_requirements})
        coverage = for_prompt([{**r, 'covered': r['id'] in done} for r in scope_requirements])
        used = {s['operationId'] for f in flows for s in f['steps']}
        scope_ops = used | (group['operations'] if group and group['kind'] == 'area' else set())
        task = {'mode': mode, 'domain': domain_for(self.domain, scope_ops, {r['id'] for r in scope_requirements}),
                'requirements': coverage, 'flows': flows, 'operations': self.details(used)}
        if group:
            task['scope'] = group['scope']
        verdict = self.call('flow-reviewer', task, FlowReview)
        verdict['findings'] = sorted(verdict.get('findings', []), key=lambda f: SEVERITY_ORDER.get(f.get('severity'), 3))[:MAX_FINDINGS]
        return verdict

    def improve(self, outlines, flows, verdict, group):
        """Fix serious findings; returns the outlines, the flows and the keys of the flows that changed."""
        serious = [f for f in verdict.get('findings', []) if f['severity'] in SERIOUS]
        suggestions = [f for f in serious if f['flowKey'] == 'plan']
        current = {f['flowKey']: f for f in flows}
        flagged = [f for f in serious if f['flowKey'] in current]
        changed: set[str] = set()
        if not suggestions and not flagged:
            return outlines, flows, changed
        if suggestions:
            extra = self.call('flow-designer', self.context(
                group, mode='add-suggested', reviewSuggestions=suggestions,
                existingFlows=[{k: o[k] for k in ('key', 'title', 'covers')} for o in outlines]), FlowPlan)['flows']
            extra = self.unique(self.clean_covers(self.repair(self.keys.renumber(extra), group)))
            outlines = outlines + extra
            added = self.write(extra)
            current.update(added)
            changed |= set(added)
        if flagged:
            keys = list(dict.fromkeys(f['flowKey'] for f in flagged))
            targets = [o for o in outlines if o['key'] in keys]
            revised = self.write(targets, mode='revise', current=current, findings=flagged)
            current.update(revised)
            changed |= set(revised)
        return outlines, [current[o['key']] for o in outlines if o['key'] in current], changed

    def finish(self, outlines: list[dict], group: dict | None, step) -> tuple[list[dict], list[dict], dict]:
        """Write, review and fix a set of outlines; returns the outlines that were written, their flows and the review."""
        step(f'writing {len(outlines)} flows', 0.4)
        written = self.write(outlines)
        outlines = [o for o in outlines if o['key'] in written]
        flows = [written[o['key']] for o in outlines]
        if not flows:
            return [], [], {'verdict': 'ready', 'summary': '', 'findings': []}
        step('reviewing', 0.7)
        verdict = self.review(outlines, flows, group)
        step('fixing what the reviewer found', 0.8)
        outlines, flows, changed = self.improve(outlines, flows, verdict, group)
        if changed:
            step('final review', 0.9)
            # Re-check only the flows that changed; keep the first review's notes on the others.
            changed_outlines = [o for o in outlines if o['key'] in changed]
            recheck = self.review(changed_outlines, [f for f in flows if f['flowKey'] in changed], group, mode='recheck')
            kept = [f for f in verdict.get('findings', []) if f['flowKey'] not in changed
                    and not (f['flowKey'] == 'plan' and f['severity'] in SERIOUS)]  # serious suggestions were added
            findings = sorted(kept + recheck.get('findings', []), key=lambda f: SEVERITY_ORDER.get(f.get('severity'), 3))
            ready = not any(f['severity'] in SERIOUS for f in findings)
            verdict = {'verdict': 'ready' if ready else 'needs_attention',
                       'summary': recheck.get('summary') or verdict.get('summary', ''), 'findings': findings[:MAX_FINDINGS * 2]}
        written_keys = {f['flowKey'] for f in flows}
        return [o for o in outlines if o['key'] in written_keys], flows, verdict


def _combined_review(reviews: dict[str, dict]) -> dict:
    ready = all(r.get('verdict') == 'ready' for r in reviews.values())
    summary = ' '.join(f"{name}: {r['summary']}" for name, r in reviews.items() if r.get('summary'))
    findings = [f for r in reviews.values() for f in r.get('findings', [])]
    return {'verdict': 'ready' if ready else 'needs_attention', 'summary': summary[:800], 'findings': findings[:60]}


def generate(job_input: dict, report, submit=None, agent=run_agent, parallel: int = PARALLEL_GROUPS) -> dict:
    endpoints = [item['details'] for item in job_input['endpoints']]
    send = submit or (lambda result: None)
    with tempfile.TemporaryDirectory(prefix='studio-flows-') as workspace:
        pipeline = FlowPipeline(job_input['api'], endpoints, agent, workspace, report)
        lock = threading.Lock()
        # Structured progress for the portal's stepper and area table; changed only under `lock`.
        track = {'stage': 'analyze', 'operations': len(endpoints), 'parallel': 1, 'groups': [], 'savedFlows': 0,
                 'stageStartedAt': {'analyze': time.time()}}
        rows: dict[str, dict] = {}

        def snapshot() -> dict:
            with lock:
                return {**track, 'stageStartedAt': dict(track['stageStartedAt']),
                        'groups': [dict(row) for row in track['groups']]}

        def enter(stage: str):
            with lock:
                track['stage'] = stage
                track['stageStartedAt'][stage] = time.time()

        def tell(message: str, percent: int):
            report(message, percent, snapshot())

        resume = job_input.get('resume')
        if resume:
            # Continue a stopped design: reuse its analysis and skip the groups that were already saved.
            domain = pipeline.restore(resume['domain'], resume.get('outlines', []))
            track['stageStartedAt'] = {}
        else:
            tell(f'Understanding the business domain across {len(endpoints)} operations', 3)
            domain = pipeline.analyze()
            send({'stage': 'domain', 'domain': domain, 'dependencies': pipeline.edges})
        all_groups = pipeline.groups()
        done = {item['name']: item.get('flows', 0) for item in (resume or {}).get('doneGroups', [])}
        groups = [group for group in all_groups if group['name'] not in done]
        with lock:
            track.update(entities=len(domain['entities']), rules=len(domain['businessRules']), areas=len(pipeline.areas),
                         parallel=max(1, min(parallel, len(groups) or 1)), savedFlows=sum(done.values()))
            track['groups'] = [{'name': group['name'], 'status': 'done', 'step': 'saved earlier', 'flows': done[group['name']]}
                               if group['name'] in done else {'name': group['name'], 'status': 'waiting', 'step': '', 'flows': 0}
                               for group in all_groups]
            rows.update({row['name']: row for row in track['groups']})
        enter('design')
        if resume:
            tell(f'Continuing: {len(all_groups) - len(groups)} of {len(all_groups)} groups were already done · '
                 f'designing the remaining {len(groups)}, up to {min(parallel, max(1, len(groups)))} at a time', 10)
        else:
            tell(f'{len(domain["entities"])} entities, {len(domain["businessRules"])} business rules, {len(pipeline.areas)} areas · '
                 f'designing {len(groups)} groups, up to {min(parallel, len(groups))} at a time', 10)

        active: dict[str, tuple[str, float]] = {}
        state = {'finished': len(all_groups) - len(groups), 'flows': sum(done.values())}
        all_outlines: list[dict] = list((resume or {}).get('outlines', []))
        reviews: dict[str, dict] = {}
        stop: list[Exception] = []

        def publish():
            with lock:
                progress = state['finished'] + sum(fraction for _, fraction in active.values())
                working = '; '.join(f'{name}: {message}' for name, (message, _) in active.items())
                text = f"{state['finished']} of {len(all_groups)} groups done, {state['flows']} flows" + (f' · {working}' if working else '')
            tell(text, 10 + int(75 * progress / max(1, len(all_groups))))

        def run(group: dict):
            name = group['name']
            with lock:
                if stop:
                    return
                active[name] = ('designing flows', 0.05)
                rows[name].update(status='working', step='designing flows', startedAt=time.time())

            def step(message, fraction):
                words = message.split()
                with lock:
                    active[name] = (message, fraction)
                    rows[name]['step'] = message
                    if words[0] == 'writing' and len(words) > 1 and words[1].isdigit():
                        rows[name]['flows'] = int(words[1])
                publish()

            try:
                outlines = pipeline.design(group)
                outlines, flows, verdict = pipeline.finish(outlines, group, step)
                if flows:
                    send({'stage': 'group', 'group': name, 'plan': outlines, 'flows': flows, 'review': verdict})
            except ClaudeError as exc:
                if 'usage limit' in str(exc) or 'not signed in' in str(exc):
                    with lock:
                        stop.append(exc)
                        active.pop(name, None)
                        rows[name].update(status='failed', step='stopped', finishedAt=time.time())
                    return
                outlines, verdict = [], {'verdict': 'needs_attention', 'summary': f'Design failed for {name}: {str(exc)[:300]}', 'findings': []}
                flows = []
                failed = True
            except Exception as exc:  # the portal rejected a result or the job was cancelled
                with lock:
                    stop.append(exc)
                    active.pop(name, None)
                    rows[name].update(status='failed', step='stopped', finishedAt=time.time())
                return
            else:
                failed = False
            with lock:
                all_outlines.extend(outlines)
                reviews[name] = verdict
                state['finished'] += 1
                state['flows'] += len(flows)
                track['savedFlows'] += len(flows)
                active.pop(name, None)
                rows[name].update(status='failed' if failed else 'done', step='design failed' if failed else 'saved',
                                  flows=len(flows), finishedAt=time.time())
            publish()

        with ThreadPoolExecutor(max_workers=max(1, min(parallel, len(groups) or 1)), thread_name_prefix='flows') as pool:
            for future in [pool.submit(run, group) for group in groups]:
                future.result()
        if stop:
            error = stop[0]
            if isinstance(error, ClaudeError):
                raise ClaudeError(f"{error} {state['flows']} flows from {state['finished']} of {len(all_groups)} groups are saved; "
                                  'use Continue generation to design the rest.') from error
            raise error

        enter('coverage')
        tell(f"Checking coverage across all {state['flows']} flows", 88)
        extra, rounds = pipeline.fill_gaps(all_outlines)
        flows = []
        if extra:
            with lock:
                track['gapFlows'] = len(extra)
            tell(f'Writing {len(extra)} flows that close coverage gaps', 92)
            extra, flows, verdict = pipeline.finish(extra, None, lambda message, fraction: tell(f'Coverage gaps: {message}', 92))
            reviews['Coverage gaps'] = verdict
        if not all_outlines and not extra:
            raise ClaudeError('No flows could be designed. See the analysis in the portal.')
        # A continued design already holds the earlier reviews on the portal; send only this job's coverage step there.
        final_review = _combined_review({k: v for k, v in reviews.items() if k == 'Coverage gaps'} if resume else reviews)
        send({'stage': 'final', 'plan': extra, 'flows': flows, 'review': final_review, 'rounds': rounds})
        with lock:
            track['savedFlows'] += len(flows)
            track['gapFlows'] = len(flows)
        enter('done')
        tell('Finished', 100)
    return {'flows': state['flows'] + len(flows)}

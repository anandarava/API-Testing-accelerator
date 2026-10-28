"""Connects to the portal, reports presence and runs jobs assigned to the signed-in user."""
import json
import socket
import threading
import time

import httpx

from contracts import ASSISTANT_KINDS, VERSION, HelperHeartbeat
from contracts.fingerprint import CONTRACT_FINGERPRINT

from . import assistant, claude, config, flow_cases, framework, local_llm, regenerate, role_cases, scripts, unit_cases

HEARTBEAT_SECONDS = 10
CLAUDE_REFRESH_SECONDS = 60
CLAIM_SECONDS = 3
ASSISTANT_CLAIM_SECONDS = 1  # questions should feel quick
LEASE_RENEW_SECONDS = 30

HANDLERS = {'framework.analyze': framework.analyze, 'unit.generate': unit_cases.generate, 'scripts.generate': scripts.generate,
            'flows.generate': flow_cases.generate, 'case.regenerate': regenerate.generate,
            'access.analyze': role_cases.analyze, 'roles.generate': role_cases.generate,
            'assistant.message': assistant.answer}


class PairingRevoked(RuntimeError):
    pass


class VersionMismatch(RuntimeError):
    pass


def check(response: httpx.Response) -> httpx.Response:
    if response.status_code == 401:
        raise PairingRevoked('This computer is no longer connected to the portal. Run "pair" again with a new code.')
    if response.is_error:
        try:
            detail = response.json().get('detail', response.text)
        except ValueError:
            detail = response.text
        raise RuntimeError(f'Portal returned HTTP {response.status_code}: {str(detail)[:500]}')
    return response


class Helper:
    """Claims and runs jobs. The ``main`` lane runs generation jobs one at a time; the ``assistant`` lane answers
    project-assistant messages in parallel with it, each with its own model and usage."""

    def __init__(self, client: httpx.Client, log=print, handlers=None, claude_status=claude.status, local_status=local_llm.status,
                 lane: str = 'main'):
        self.client, self.log, self.lane = client, log, lane
        self.handlers = handlers or HANDLERS
        self.claude_status, self.local_status = claude_status, local_status
        self._status, self._local, self._status_at, self._beat_at = None, None, 0.0, 0.0
        self.hostname = socket.gethostname()

    def heartbeat(self, force=False):
        now = time.time()
        if not force and now - self._beat_at < HEARTBEAT_SECONDS:
            return
        if self._status is None or now - self._status_at > CLAUDE_REFRESH_SECONDS:
            self._status, self._local, self._status_at = self.claude_status(), self.local_status(), now
        body = HelperHeartbeat(hostname=self.hostname, helperVersion=VERSION, claude=self._status, local=self._local)
        response = self.client.post('/api/helper/heartbeat', json=body.model_dump())
        if response.status_code == 422:
            # An older portal rejects fields this helper sends.
            raise VersionMismatch('This Local Helper is newer than the portal. Restart the portal with the same version of '
                                  'API Test Studio, then start the helper again.')
        reply = check(response).json()
        self._beat_at = now
        if reply.get('contracts') != CONTRACT_FINGERPRINT:
            raise VersionMismatch('This Local Helper and the portal are different versions. Update both to the same '
                                  'version of API Test Studio, then start the helper again.')

    def run_once(self) -> bool:
        """Claim and run at most one job. Returns True when a job was processed."""
        if self.lane == 'main':
            self.heartbeat()
        job = check(self.client.post('/api/helper/jobs/claim', params={'lane': self.lane})).json()['job']
        if not job:
            return False
        self.process(job)
        return True

    def process(self, job: dict):
        job_id, kind = job['id'], job['kind']
        model = job.get('model') or 'default'
        self.log(f'> {kind} for project "{job.get("projectName", "")}" on model: {model}')
        meter = claude.job_model if self.lane == 'main' else claude.JobModel()
        meter.begin(model)
        state = {'message': 'Starting', 'percent': 0, 'models': [], 'usage': meter.usage()}
        stop = threading.Event()

        def report(message, percent=None, detail=None):
            state.update(message=message, percent=percent, models=meter.models(), usage=meter.usage())
            if detail is not None:
                state['detail'] = detail
            self.log(f'  {message}')
            try:
                self.client.post(f'/api/helper/jobs/{job_id}/progress', json=state)
            except httpx.HTTPError:
                pass

        def keep_lease():
            while not stop.wait(LEASE_RENEW_SECONDS):
                try:
                    state.update(models=meter.models(), usage=meter.usage())
                    self.client.post(f'/api/helper/jobs/{job_id}/progress', json=state)
                except httpx.HTTPError:
                    pass

        submit_lock = threading.Lock()

        def submit(partial):
            try:
                with submit_lock:  # endpoints finish in parallel; send results one at a time
                    check(self.client.post(f'/api/helper/jobs/{job_id}/partial', json={'result': partial}))
            except RuntimeError:
                # Keep the AI output so the work is not lost; the job still fails visibly.
                folder = config.HOME / 'unsent-results'
                folder.mkdir(parents=True, exist_ok=True)
                saved = folder / f'{job_id}-{int(time.time())}.json'
                saved.write_text(json.dumps(partial, indent=1), encoding='utf-8')
                self.log(f'  The portal rejected a result; a copy was saved to {saved}')
                raise

        renewer = threading.Thread(target=keep_lease, daemon=True)
        renewer.start()
        try:
            handler = self.handlers.get(kind)
            if not handler:
                raise RuntimeError(f'This helper version cannot run "{kind}" jobs. Update the Local Helper.')
            extra = {'meter': meter} if kind in ASSISTANT_KINDS else {}
            result = handler(job['input'], report, submit=submit, **extra)
            used = meter.models()
            check(self.client.post(f'/api/helper/jobs/{job_id}/complete',
                                   json={'result': result, 'models': used, 'usage': meter.usage()}))
            self.log(f"  Done. AI ran on: {', '.join(used) or 'no AI call was needed'}")
        except (PairingRevoked, VersionMismatch):
            raise
        except Exception as exc:  # report every failure to the portal so the user can see it
            message = str(exc) or exc.__class__.__name__
            self.log(f'  Failed: {message}')
            try:
                self.client.post(f'/api/helper/jobs/{job_id}/fail', json={'error': message[:4000], 'models': meter.models(),
                                                                       'usage': meter.usage()})
            except httpx.HTTPError:
                pass
        finally:
            stop.set()
            renewer.join(timeout=2)

    def run_forever(self):
        backoff = 0
        while True:
            try:
                if not self.run_once():
                    time.sleep(CLAIM_SECONDS if self.lane == 'main' else ASSISTANT_CLAIM_SECONDS)
                if backoff:
                    self.log('Reconnected to the portal.')
                backoff = 0
            except httpx.HTTPError as exc:
                backoff = min(30, max(2, backoff * 2))
                self.log(f'Cannot reach the portal ({exc.__class__.__name__}). Retrying in {backoff}s...')
                time.sleep(backoff)

"""Local Helper command line.

    python -m helper pair ABCD-EFGH [--server http://127.0.0.1:8000]
    python -m helper start
    python -m helper status
    python -m helper unpair
"""
import argparse
import socket
import threading
import sys
from urllib.parse import urlparse

import httpx

from contracts import VERSION

from . import claude, config, local_llm
from .runner import Helper, PairingRevoked, VersionMismatch, check

DEFAULT_SERVER = 'http://127.0.0.1:8000'


def _server(url: str) -> str:
    url = url.rstrip('/')
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        sys.exit(f'Invalid portal address: {url}')
    if parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', 'localhost'):
        print('Warning: the portal is not using HTTPS. Use HTTPS when the portal is on another machine.')
    return url


def pair(args):
    server = _server(args.server)
    try:
        response = httpx.post(server + '/api/helper/pair', json={'code': args.code, 'hostname': socket.gethostname()}, timeout=30)
        data = check(response).json()
    except (httpx.HTTPError, RuntimeError) as exc:
        sys.exit(f'Pairing failed: {exc}')
    config.save({'server': server, 'token': data['token'], 'user': data['user']})
    print(f"Connected as {data['user']['name']} ({data['user']['email']}). Now run:  python -m helper start")


def status(_args):
    saved = config.load()
    print(f'Local Helper {VERSION}')
    print(f"Portal: {saved.get('server', 'not paired')}")
    if saved.get('user'):
        print(f"Paired as: {saved['user']['name']} ({saved['user']['email']})")
    info = claude.status()
    if not info.installed:
        print(f'Claude Code: not found - {info.error}')
    else:
        signed_in = f'signed in as {info.email} ({info.subscriptionType})' if info.loggedIn else 'NOT signed in'
        print(f'Claude Code {info.version}: {signed_in}')
    local = local_llm.status()
    if not local.configured:
        print('Local AI server: not set up (add STUDIO_LLM_BASE_URL and STUDIO_LLM_API_KEY to .env)')
    elif local.reachable:
        print(f"Local AI server {local.server}: models {', '.join(local.models) or 'none listed'}")
    else:
        print(f'Local AI server {local.server}: {local.error}')


def unpair(_args):
    config.clear()
    print('This computer is disconnected. Pair again from the portal when needed.')


def start(_args):
    saved = config.load()
    if not saved.get('token'):
        sys.exit('This computer is not paired yet. In the portal, click "Connect this computer" and run the pair command.')
    info, local = claude.status(), local_llm.status()
    if not info.loggedIn and not local.reachable:
        print(f'Warning: {info.error or "Claude Code is not ready."} Jobs will fail until this is fixed, '
              'unless you set up a local AI server in .env.')
    elif not info.loggedIn:
        print(f'Claude Code is not ready; only local models ({local.server}) can run jobs.')
    elif local.configured and not local.reachable:
        print(f'Note: {local.error} Jobs on local models will fail until this is fixed.')
    print(f"Local Helper {VERSION} connected to {saved['server']} as {saved['user']['name']}. Press Ctrl+C to stop.")
    with httpx.Client(base_url=saved['server'], headers={'Authorization': 'Bearer ' + saved['token']}, timeout=60) as client:
        # The project assistant answers on its own lane, so questions never wait for a long generation.
        lane = Helper(client, log=lambda message: print(f'[assistant] {message.strip()}'), lane='assistant')
        threading.Thread(target=lane.run_forever, daemon=True, name='assistant-lane').start()
        try:
            Helper(client).run_forever()
        except (PairingRevoked, VersionMismatch) as exc:
            sys.exit(str(exc))
        except KeyboardInterrupt:
            print('\nLocal Helper stopped.')


def main():
    parser = argparse.ArgumentParser(prog='python -m helper', description='API Test Studio Local Helper')
    commands = parser.add_subparsers(dest='command', required=True)
    pair_cmd = commands.add_parser('pair', help='Connect this computer using a code from the portal')
    pair_cmd.add_argument('code')
    pair_cmd.add_argument('--server', default=DEFAULT_SERVER)
    pair_cmd.set_defaults(run=pair)
    commands.add_parser('start', help='Run jobs from the portal').set_defaults(run=start)
    commands.add_parser('status', help='Show pairing, Claude and local AI server status').set_defaults(run=status)
    commands.add_parser('unpair', help='Disconnect this computer').set_defaults(run=unpair)
    args = parser.parse_args()
    config.load_env()
    args.run(args)


if __name__ == '__main__':
    main()

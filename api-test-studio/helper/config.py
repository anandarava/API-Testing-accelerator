import json
import os
from pathlib import Path

HOME = Path(os.environ.get('STUDIO_HELPER_HOME', Path.home() / '.api-test-studio' / 'helper'))
CONFIG_FILE = HOME / 'helper.json'


def load() -> dict:
    if not CONFIG_FILE.is_file():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save(data: dict):
    HOME.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG_FILE.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    if os.name != 'nt':
        temporary.chmod(0o600)
    temporary.replace(CONFIG_FILE)


def clear():
    CONFIG_FILE.unlink(missing_ok=True)

"""The helper's pairing file and its .env settings (for example the local AI server)."""
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


def load_env(*files: Path):
    """Read KEY=VALUE lines from .env files into the environment. Variables already set win."""
    files = files or (Path.cwd() / '.env', Path(__file__).resolve().parents[1] / '.env')
    for file in dict.fromkeys(path.resolve() for path in files):
        if not file.is_file():
            continue
        for line in file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.removeprefix('export ').split('=', 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)

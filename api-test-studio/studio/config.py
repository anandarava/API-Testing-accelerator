"""Server settings, read from environment variables at start-up."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Keep data outside synced folders such as OneDrive by default.
DATA_DIR = Path(os.environ.get('STUDIO_DATA_DIR', Path.home() / '.api-test-studio' / 'server'))
DATABASE_URL = os.environ.get('STUDIO_DATABASE_URL') or 'sqlite:///' + (DATA_DIR / 'studio.db').as_posix()
COOKIE_SECURE = os.environ.get('STUDIO_COOKIE_SECURE', 'false') == 'true'
WEB_DIST = ROOT / 'web' / 'dist'

SESSION_SECONDS = 12 * 3600
HELPER_TOKEN_SECONDS = 30 * 86400
PAIRING_CODE_SECONDS = 600
HELPER_ONLINE_SECONDS = 25
JOB_LEASE_SECONDS = 120
MAX_SPEC_BYTES = 10_000_000

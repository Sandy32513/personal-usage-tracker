"""
Configuration Management for Personal Usage Tracker V3
Centralized configuration for all components
"""

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Determine base directory
# Always use ProgramData for runtime data to unify paths across dev/prod
# Override with USAGE_TRACKER_BASE_DIR env var (e.g., for development)
_base_dir_env = os.getenv('USAGE_TRACKER_BASE_DIR', '').strip()

if _base_dir_env:
    # Use custom base directory from environment
    BASE_DIR = Path(_base_dir_env)
else:
    # Default: Use ProgramData (production behavior)
    PROGRAMDATA = os.getenv('PROGRAMDATA', 'C:\\ProgramData')
    BASE_DIR = Path(PROGRAMDATA) / 'PersonalUsageTracker'

# ─── Security: Credential Storage ─────────────────────────────────────────────
# Option 1: Use Windows Credential Manager (recommended for production)
#   Store credentials once: cmdkey /add:UsageTrackerDB /user:username /pass:password
#   Then set USE_CREDENTIAL_MANAGER = True
# Option 2: Plaintext in config (development only)
USE_CREDENTIAL_MANAGER = os.getenv('USE_CREDENTIAL_MANAGER', 'false').lower() == 'true'
CREDENTIAL_TARGET = 'UsageTrackerDB'

def _get_password_via_credmanager() -> str:
    """Retrieve password from Windows Credential Manager"""
    try:
        import win32cred
        cred = win32cred.CredCredential(CREDENTIAL_TARGET)
        return cred.CredentialBlob.decode('utf-8')
    except Exception as e:
        logger.critical(
            f"Credential Manager lookup failed for '{CREDENTIAL_TARGET}'. "
            f"Error: {e}. "
            f"REFUSING to fall back to plaintext. "
            f"Set USE_CREDENTIAL_MANAGER=false in config.py to allow plaintext (insecure)."
        )
        raise RuntimeError(f"Credential Manager lookup failed: {e}") from e

# Resolve password
if USE_CREDENTIAL_MANAGER:
    DB_PASSWORD = _get_password_via_credmanager()
else:
    # No fallback - fail loudly if no credential manager and no env var set
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    if not DB_PASSWORD:
        raise RuntimeError(
            "No DB password configured. "
            "Set USE_CREDENTIAL_MANAGER=true and store credentials, "
            "or set DB_PASSWORD environment variable."
        )

# SQL Server Configuration
SQL_SERVER_CONFIG = {
    'driver': '{ODBC Driver 17 for SQL Server}',
    'server': 'localhost',  # Change to your SQL Server instance
    'database': 'UsageTracker',
    'username': 'usage_tracker_user',  # SQL Auth user
    'password': DB_PASSWORD,  # From secure storage or config
    'trusted_connection': 'no',  # Set to 'yes' for Windows Auth
    'autocommit': False,
}

# Connection string builder
def get_connection_string():
    """Build ODBC connection string from config"""
    if SQL_SERVER_CONFIG['trusted_connection'] == 'yes':
        return f"DRIVER={SQL_SERVER_CONFIG['driver']};SERVER={SQL_SERVER_CONFIG['server']};DATABASE={SQL_SERVER_CONFIG['database']};Trusted_Connection=yes;"
    else:
        return f"DRIVER={SQL_SERVER_CONFIG['driver']};SERVER={SQL_SERVER_CONFIG['server']};DATABASE={SQL_SERVER_CONFIG['database']};UID={SQL_SERVER_CONFIG['username']};PWD={SQL_SERVER_CONFIG['password']};"

# SQLite Queue Database Path (persistent queue)
QUEUE_DB_PATH = os.path.join(BASE_DIR, 'data', 'queue.db')
os.makedirs(os.path.dirname(QUEUE_DB_PATH), exist_ok=True)

# Chrome History Path (default Windows location)
CHROME_HISTORY_PATH = r'C:\Users\{}\AppData\Local\Google\Chrome\User Data\Default\History'.format(os.getenv('USERNAME', 'Default'))

# Tracking Intervals (seconds)
TRACK_INTERVAL = 5  # How often to capture active window (seconds)
BROWSER_SCAN_INTERVAL = 30  # How often to scan Chrome history (seconds)
PROCESSOR_INTERVAL = 10  # Queue processor poll interval (seconds)
EXPORT_INTERVAL = 600  # CSV export every 10 minutes (600 seconds)

# Retry Configuration
MAX_RETRY_COUNT = 5          # Max retry attempts before marking failed
INITIAL_RETRY_DELAY = 2      # Initial backoff (seconds)
MAX_RETRY_DELAY = 300        # Max backoff (5 minutes max)

# Queue Configuration
MAX_QUEUE_SIZE = 1_000_000   # Max events in persistent queue (prevent disk exhaustion)
DATABASE_CONNECTION_TIMEOUT = 30  #seconds backoff

# Queue Constants
QUEUE_STATUS = {
    'PENDING': 'pending',
    'PROCESSING': 'processing',
    'FAILED': 'failed',
    'COMPLETED': 'completed'
}

# Event Types
EVENT_TYPE = {
    'APP': 'app',
    'WEB': 'web'
}

# CSV Export Paths
EXPORT_DIR = os.path.join(BASE_DIR, 'exports')
os.makedirs(EXPORT_DIR, exist_ok=True)
APP_USAGE_CSV = os.path.join(EXPORT_DIR, 'app_usage.csv')
WEB_USAGE_CSV = os.path.join(EXPORT_DIR, 'web_usage.csv')

# Logging Configuration
LOG_LEVEL = 'INFO'
LOG_FILE = os.path.join(BASE_DIR, 'logs', 'tracker.log')
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# Windows Service Configuration
SERVICE_NAME = 'PersonalUsageTrackerV3'
SERVICE_DISPLAY_NAME = 'Personal Usage Tracker V3'
SERVICE_DESCRIPTION = 'Tracks application usage and browser activity for productivity analytics'

# Data Retention (days)
DATA_RETENTION_DAYS = 90  # Keep data for 90 days before archiving/purging

# ─── Timezone Configuration ─────────────────────────────────────────────────
USE_UTC = True  # Store timestamps in UTC (recommended for global deployments)
# If False, uses local system timezone (legacy behavior)

# Privacy / Redaction
ENABLE_REDACTION = True   # Enable PII redaction in window titles and URLs
REDACT_PATTERNS = [
    r'(password|passwd|pwd)\s*[=:]\s*\S+',
    r'(username|user|login|email)\s*[=:]\s*\S+',
    r'\b(?:\d{4}[-\s]?){4}\b',  # Credit cards
    r'\b\d{3}-\d{2}-\d{4}\b',  # SSN
    r'bearer\s+\S+',
    r'api[-_]?key\s*[=:]\s*\S+',
    r'secret\s*[=:]\s*\S+',
    r'token\s*[=:]\s*\S+',
]


def get_timestamp() -> str:
    """Get current timestamp in ISO format (UTC or local based on config)"""
    from datetime import datetime, timezone
    if USE_UTC:
        return datetime.now(timezone.utc).isoformat()
    else:
        return datetime.now().isoformat()

# Chrome History Query
CHROME_HISTORY_QUERY = """
SELECT 
    url,
    title,
    last_visit_time as visit_time,
    visit_count
FROM urls
WHERE last_visit_time > ?
ORDER BY last_visit_time DESC
LIMIT 100
"""

# Log config at startup instead of import time
def log_config():
    logger.info(f"Base directory: {BASE_DIR}")
    logger.info(f"Queue DB: {QUEUE_DB_PATH}")
    logger.info(f"Export dir: {EXPORT_DIR}")
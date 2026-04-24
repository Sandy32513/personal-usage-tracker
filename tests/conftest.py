"""
Pytest configuration and fixtures for integration tests.
"""

import os
import sys
from pathlib import Path

# Set test environment variables BEFORE any app imports
os.environ.setdefault('DB_PASSWORD', 'test-password-for-ci-only')
os.environ.setdefault('USE_CREDENTIAL_MANAGER', 'false')
os.environ.setdefault('LOG_LEVEL', 'INFO')
os.environ.setdefault('HEALTH_API_KEY', 'test-api-key')

# Ensure project root in path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

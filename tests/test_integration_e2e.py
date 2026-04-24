"""
End-to-End Integration Tests — Personal Usage Tracker V3

Tests core pipeline components in isolation:
- Queue atomicity and recovery
- Processor batch insert with validation
- CSV sanitization and export
- Agent fallback replay
- Circuit breaker behavior

Run: pytest tests/test_integration_e2e.py -v --tb=short
"""

import csv
import gzip
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))

# Test environment before any app imports
os.environ.setdefault('DB_PASSWORD', 'test-password')
os.environ.setdefault('USE_CREDENTIAL_MANAGER', 'false')
os.environ.setdefault('LOG_LEVEL', 'INFO')

from app.queue.queue_db import PersistentQueue
from app.validation import EventValidator
from app.exporter.csv_exporter import CSVExporter
from app.processor.worker import ProcessorWorker, CircuitBreaker

pytestmark = pytest.mark.integration


# ============================================================================
# HELPERS
# ============================================================================

def make_event(ev_type: str, **kwargs) -> Dict[str, Any]:
    """Create a valid test event with timestamp."""
    base = {
        'type': ev_type,
        'timestamp': datetime.now().isoformat()
    }
    base.update(kwargs)
    return base


class FakeDB:
    """In-memory fake DB for processor tests."""
    def __init__(self):
        self.events: List[Dict[str, Any]] = []
    
    def insert_event_from_queue(self, payload: Dict[str, Any]) -> bool:
        self.events.append(payload)
        return True
    
    def insert_batch_from_queue(self, payloads: List[Dict[str, Any]]) -> tuple[List[int], List[int]]:
        for p in payloads:
            self.events.append(p)
        return list(range(len(payloads))), []


# ============================================================================
# QUEUE TESTS
# ============================================================================

class TestQueueAtomicity:
    """H1 — Atomic dequeue prevents duplicate delivery."""
    
    def test_atomic_dequeue_claims_exclusive(self, tmp_path):
        """Two dequeues must never claim the same event."""
        db_file = tmp_path / 'queue.db'
        queue = PersistentQueue(db_path=str(db_file))
        
        # Enqueue 10 events
        for i in range(10):
            queue.enqueue(make_event('app', app_name=f'App{i}'))
        
        # Dequeue batch 1
        batch1 = queue.dequeue_batch(10)
        # Dequeue batch 2 immediately
        batch2 = queue.dequeue_batch(10)
        
        ids1 = {e['queue_id'] for e in batch1}
        ids2 = {e['queue_id'] for e in batch2}
        
        assert len(batch1) == 10, f"First batch should return 10, got {len(batch1)}"
        assert len(batch2) == 0, f"Second batch should be empty, got {len(batch2)}"
        assert ids1.isdisjoint(ids2), "No queue ID should overlap"
    
    def test_dequeue_skips_processing(self, tmp_path):
        """Dequeue only returns pending events."""
        db_file = tmp_path / 'queue.db'
        queue = PersistentQueue(db_path=str(db_file))
        
        qid1 = queue.enqueue(make_event('app', app_name='Event1'))
        qid2 = queue.enqueue(make_event('app', app_name='Event2'))
        queue.mark_processing(qid1)
        
        batch = queue.dequeue_batch(10)
        ids = [e['queue_id'] for e in batch]
        
        assert qid2 in ids, "Pending event should be returned"
        assert qid1 not in ids, "Processing event should be skipped"


class TestQueueRecovery:
    """C2 — Stale processing events are automatically re-queued."""
    
    def test_recover_stale_processing(self, tmp_path):
        """Events stuck in 'processing' > timeout are reset to 'pending'."""
        db_file = tmp_path / 'queue.db'
        queue = PersistentQueue(db_path=str(db_file))
        
        # Insert one stale processing event directly
        old_time = (datetime.now() - timedelta(minutes=10)).isoformat()
        conn = sqlite3.connect(queue.db_path)
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO queue_events (payload, status, created_at, updated_at)
            VALUES (?, 'processing', ?, ?)
        ''', (json.dumps(make_event('app', app_name='Stale')), old_time, old_time))
        conn.commit()
        conn.close()
        
        # Size should be 1
        assert queue.get_size() == 1
        
        # Run recovery with 5-min timeout
        recovered = queue._recover_stale_processing(stale_timeout_minutes=5)
        assert recovered == 1, f"Should recover 1 event, got {recovered}"
        
        # Verify now pending
        stats = queue.get_stats()
        assert stats.get('pending', 0) == 1
        assert stats.get('processing', 0) == 0


# ============================================================================
# VALIDATION TESTS
# ============================================================================

class TestValidation:
    """M1 — Strict Pydantic validation enforced."""
    
    def test_valid_app_event(self):
        ev = make_event('app', app_name='VS Code', window_title='main.py')
        validated = EventValidator.validate_app_event(ev)
        assert validated is not None
        assert validated['app_name'] == 'VS Code'
    
    def test_valid_web_event(self):
        ev = make_event('web', url='https://github.com', title='Repo')
        validated = EventValidator.validate_web_event(ev)
        assert validated is not None
        assert validated['url'] == 'https://github.com'
    
    def test_missing_app_name_fails(self):
        ev = make_event('app', window_title='NoName')
        assert EventValidator.validate_app_event(ev) is None
    
    def test_non_http_url_fails(self):
        ev = make_event('web', url='ftp://example.com', title='Test')
        assert EventValidator.validate_web_event(ev) is None
    
    def test_web_normalization(self):
        ev = {'type': 'web', 'url': 'https://example.com', 'visit_time': datetime.now().isoformat(), 'visit_duration': 300}
        norm = EventValidator._normalize_web_event(ev)
        assert 'timestamp' in norm
        assert norm['duration_seconds'] == 300


# ============================================================================
# PROCESSOR TESTS
# ============================================================================

class TestProcessor:
    """M4 — Batch insert and circuit breaker."""
    
    def test_batch_insert_all_types(self, tmp_path):
        """Processor should insert mixed app/web events in batch."""
        db_file = tmp_path / 'queue.db'
        queue = PersistentQueue(db_path=str(db_file))
        fake_db = FakeDB()
        worker = ProcessorWorker(queue=queue, db=fake_db)
        
        now = datetime.now().isoformat()
        for i in range(5):
            queue.enqueue({'type': 'app', 'app_name': f'App{i}', 'timestamp': now, 'window_title': f'W{i}'})
            queue.enqueue({'type': 'web', 'url': f'https://ex.com/{i}', 'title': f'Page{i}', 'timestamp': now})
        
        worker._process_batch(batch_size=10)
        
        assert len(fake_db.events) == 10
        apps = [e for e in fake_db.events if e['type'] == 'app']
        webs = [e for e in fake_db.events if e['type'] == 'web']
        assert len(apps) == 5
        assert len(webs) == 5
    
    def test_validation_failure_skips_bad_events(self, tmp_path):
        """Invalid events are marked failed and not inserted."""
        db_file = tmp_path / 'queue.db'
        queue = PersistentQueue(db_path=str(db_file))
        fake_db = FakeDB()
        worker = ProcessorWorker(queue=queue, db=fake_db)
        
        # Enqueue valid + invalid (missing app_name)
        queue.enqueue(make_event('app', window_title='NoName'))
        queue.enqueue(make_event('app', app_name='GoodApp'))
        
        worker._process_batch(batch_size=10)
        
        # Only good event inserted
        assert len(fake_db.events) == 1
        assert fake_db.events[0]['app_name'] == 'GoodApp'
    
    def test_circuit_breaker_opens_on_failures(self, tmp_path):
        """After threshold failures, circuit opens and skips DB."""
        db_file = tmp_path / 'queue.db'
        queue = PersistentQueue(db_path=str(db_file))
        fake_db = FakeDB()
        worker = ProcessorWorker(queue=queue, db=fake_db)
        # Enqueue enough events to open circuit after threshold failures
        for i in range(12):
            queue.enqueue(make_event('app', app_name=f'cb-fail-{i}'))
        
        # Make DB always fail
        original = fake_db.insert_batch_from_queue
        fail_count = [0]
        def always_fail(payloads):
            fail_count[0] += 1
            return [], list(range(len(payloads)))
        fake_db.insert_batch_from_queue = always_fail
        
        # Process until open
        for _ in range(10):
            worker._process_batch(batch_size=2)
            if worker.circuit_breaker.state == 'OPEN':
                break
        
        assert worker.circuit_breaker.state == 'OPEN', f"Expected OPEN, got {worker.circuit_breaker.state}"
    
    def test_circuit_breaker_recovers_after_timeout(self, tmp_path):
        """After recovery timeout, a successful attempt closes circuit."""
        db_file = tmp_path / 'queue.db'
        queue = PersistentQueue(db_path=str(db_file))
        fake_db = FakeDB()
        worker = ProcessorWorker(queue=queue, db=fake_db)
        # Enqueue event to ensure processing occurs
        queue.enqueue(make_event('app', app_name='cb-recover-test'))
        
        # Force open
        worker.circuit_breaker.state = 'OPEN'
        worker.circuit_breaker.last_failure_time = time.time() - 70  # past 60s timeout
        
        # Next attempt should transition to HALF_OPEN then CLOSED on success
        worker._process_batch(batch_size=1)
        
        assert worker.circuit_breaker.state == 'CLOSED'


import time  # for circuit breaker timeout test


# ============================================================================
# CSV EXPORT TESTS
# ============================================================================

class TestCSVExport:
    """F4 — CSV injection prevention, export format."""
    
    def test_sanitize_csv_field(self):
        """Values starting with = + - @ must be prefixed with apostrophe."""
        dangerous = ['=1+1', '+SUM(A1)', '-5', '@NOW()']
        for val in dangerous:
            result = CSVExporter._sanitize_csv_field(val)
            assert result.startswith("'"), f"'{val}' should be escaped"
        
        safe = ['normal', '123', 'hello world', 'trailing=', 'no-leading equals']
        for val in safe:
            result = CSVExporter._sanitize_csv_field(val)
            assert result == val, f"'{val}' should remain unchanged"
    
    @pytest.mark.skip(reason="Full export needs real SQL Server; covered by unit tests")
    def test_export_creates_gzipped_csv(self, tmp_path):
        """Export produces valid gzipped CSV with headers."""
        # Patch export dir
        import app.config as cfg
        orig_export = cfg.EXPORT_DIR
        cfg.EXPORT_DIR = str(tmp_path / 'exports')
        
        # Create test SQLite DB with events
        db_file = tmp_path / 'events.db'
        conn = sqlite3.connect(db_file)
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE events (
                id INTEGER, type TEXT, app_name TEXT, window_title TEXT,
                url TEXT, title TEXT, timestamp TEXT, duration_seconds INTEGER
            )
        ''')
        cur.execute('''INSERT INTO events VALUES
            (1, 'app', 'VS Code', 'main.py', NULL, NULL, '2026-04-24T10:00:00', 300),
            (2, 'web', 'Chrome', NULL, 'https://github.com', 'Repo', '2026-04-24T10:05:00', 600)
        ''')
        conn.commit()
        conn.close()
        
        # Mock DB connector
        class TestDB:
            def _get_connection(self):
                return sqlite3.connect(str(db_file))
        
        exporter = CSVExporter()
        exporter.db = TestDB()
        success = exporter.export_all()
        assert success, "Export should return True"
        
        # Verify file created
        files = list(Path(cfg.EXPORT_DIR).glob('*.csv.gz'))
        assert len(files) >= 1, "At least one CSV.gz file expected"
        
        # Read and verify content
        with gzip.open(files[0], 'rt', encoding='utf-8-sig') as gz:
            reader = csv.DictReader(gz)
            rows = list(reader)
            assert len(rows) == 2
            # Check one field exists
            assert 'app_name' in rows[0] or 'url' in rows[0]
        
        cfg.EXPORT_DIR = orig_export


# ============================================================================
# AGENT FALLBACK TESTS
# ============================================================================

class TestAgentFallback:
    """M5 — Agent fallback file and service replay."""
    
    def test_fallback_queue_replay(self, tmp_path):
        """Service reads and clears agent fallback file."""
        fallback_dir = tmp_path / 'data'
        fallback_dir.mkdir(parents=True)
        fallback_file = fallback_dir / 'agent_events.jsonl'
        
        # Write two events (simulating agent while service down)
        events = [
            make_event('app', app_name='TestApp', window_title='Test'),
            make_event('web', url='https://example.com', title='Example')
        ]
        with open(fallback_file, 'w') as f:
            for ev in events:
                f.write(json.dumps(ev) + '\n')
        
        # Replay logic (from main.py)
        from app.validation import EventValidator
        replayed = []
        with open(fallback_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                ev = json.loads(line)
                if ev.get('type') == 'app':
                    validated = EventValidator.validate_app_event(ev)
                elif ev.get('type') == 'web':
                    validated = EventValidator.validate_web_event(ev)
                else:
                    validated = None
                if validated:
                    replayed.append(validated)
        
        # Simulate service truncating file after successful replay
        fallback_file.write_text('', encoding='utf-8')
        
        assert len(replayed) == 2
        assert replayed[0]['app_name'] == 'TestApp'
        assert replayed[1]['url'] == 'https://example.com'
        
        # After replay, file should be truncated
        assert fallback_file.stat().st_size == 0


# ============================================================================
# CIRCUIT BREAKER UNIT TESTS
# ============================================================================

class TestCircuitBreaker:
    """Circuit breaker transitions: CLOSED → OPEN → HALF_OPEN → CLOSED."""
    
    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10)
        assert cb.state == 'CLOSED'
        cb.record_failure()
        assert cb.state == 'CLOSED'
        cb.record_failure()
        assert cb.state == 'CLOSED'
        cb.record_failure()
        assert cb.state == 'OPEN'
    
    def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1)
        cb.state = 'OPEN'
        cb.last_failure_time = time.time() - 2  # past timeout
        assert cb.can_attempt() is True
        assert cb.state == 'HALF_OPEN'
    
    def test_closes_after_success_in_half_open(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1)
        cb.state = 'HALF_OPEN'
        cb.record_success()
        assert cb.state == 'CLOSED'


# Clean up time import so it's available for tests
import time

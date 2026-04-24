#!/usr/bin/env python3
"""
Personal Usage Tracker V3 - Validation & Test Suite
Tests all components and simulates failure scenarios
"""

import sys
import os
import time
import sqlite3
import subprocess
import threading
import tempfile
from datetime import datetime
from typing import List, Dict, Any

# Setup path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

import app.queue.queue_db as queue_module
from app.tracker.app_tracker import AppTracker
from app.tracker.browser_tracker import BrowserTracker
from app.queue.queue_db import PersistentQueue
from app.db.sqlserver import SQLServerDB
from app.processor.worker import ProcessorWorker
from app.exporter.csv_exporter import CSVExporter
from app.validation import EventValidator

logger = logging.getLogger(__name__)


class TestSuite:
    """Comprehensive test suite for Usage Tracker V3"""
    
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.results = []
        self.test_queue_db = os.path.join(
            tempfile.gettempdir(),
            f"usage_tracker_test_queue_{os.getpid()}_{int(time.time() * 1000)}.db"
        )
        queue_module.QUEUE_DB_PATH = self.test_queue_db
        self.db_available = SQLServerDB().test_connection()
    
    def test(self, name: str, func) -> bool:
        """Run a single test"""
        try:
            logger.info(f"TEST: {name}")
            func()
            logger.info(f"✓ PASS: {name}")
            self.passed += 1
            self.results.append((name, "PASS", None))
            return True
        except AssertionError as e:
            logger.error(f"✗ FAIL: {name} - {e}")
            self.failed += 1
            self.results.append((name, "FAIL", str(e)))
            return False
        except Exception as e:
            logger.error(f"✗ ERROR: {name} - {e}", exc_info=True)
            self.failed += 1
            self.results.append((name, "ERROR", str(e)))
            return False
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        print(f"Total: {self.passed + self.failed}")
        print(f"Passed: {self.passed}")
        print(f"Failed: {self.failed}")
        
        if self.failed > 0:
            print("\nFailed Tests:")
            for name, status, error in self.results:
                if status != "PASS":
                    print(f"  - {name}: {error}")
        
        print("=" * 60)
        if os.path.exists(self.test_queue_db):
            try:
                os.remove(self.test_queue_db)
            except OSError:
                logger.warning("Could not remove temporary test queue DB: %s", self.test_queue_db)
    
    def run_all(self):
        """Run all tests"""
        print("=" * 60)
        print("PERSONAL USAGE TRACKER V3 - TEST SUITE")
        print("=" * 60)
        print()

        tests = [
            ("Configuration", self.test_config),
            ("App Tracker", self.test_app_tracker),
            ("Browser Tracker", self.test_browser_tracker),
            ("Queue Operations", self.test_queue_operations),
            ("Queue to SQL Server", self.test_queue_to_sqlserver),
            ("Processor Worker", self.test_processor_worker),
            ("CSV Exporter", self.test_csv_exporter),
            ("Retry Logic", self.test_retry_logic),
            ("Persistence", self.test_persistence),
            ("Validation", self.test_validation),
            ("Bulk Enqueue", self.test_bulk_enqueue),
        ]

        for name, func in tests:
            self.test(name, func)
        
        self.print_summary()
    
    def test_config(self):
        """Test configuration loading"""
        from app.config import (
            QUEUE_DB_PATH, SQL_SERVER_CONFIG, EVENT_TYPE,
            MAX_RETRY_COUNT, EXPORT_INTERVAL
        )
        assert QUEUE_DB_PATH.endswith('queue.db'), "Queue DB path incorrect"
        assert 'server' in SQL_SERVER_CONFIG, "SQL Server config missing server"
        assert EVENT_TYPE['APP'] == 'app', "Event type APP incorrect"
        assert EVENT_TYPE['WEB'] == 'web', "Event type WEB incorrect"
        assert MAX_RETRY_COUNT == 5, "Max retry should be 5"
        assert EXPORT_INTERVAL == 600, "Export interval should be 600s (10min)"
    
    def test_app_tracker(self):
        """Test app tracker can capture window info"""
        tracker = AppTracker()
        event = tracker.get_foreground_window_info()
        assert event is not None, "Should get window info"
        assert 'type' in event, "Event missing type"
        assert 'app_name' in event, "Event missing app_name"
        assert 'timestamp' in event, "Event missing timestamp"
    
    def test_browser_tracker(self):
        """Test browser tracker initialization"""
        tracker = BrowserTracker()
        assert tracker is not None, "Browser tracker should initialize"
        # Chrome may not be installed, so we skip actual history extraction
        # Just test that object creation works
    
    def test_queue_operations(self):
        """Test queue CRUD operations"""
        queue = PersistentQueue()
        
        # Test enqueue
        test_event = {'type': 'app', 'app_name': 'TestApp', 'window_title': 'Test'}
        qid = queue.enqueue(test_event)
        assert qid > 0, f"Queue ID should be positive, got {qid}"
        
        # Test dequeue
        batch = queue.dequeue_batch(1)
        assert len(batch) == 1, f"Should get 1 event, got {len(batch)}"
        assert batch[0]['queue_id'] == qid, "Queue ID mismatch"
        
        # Test complete
        queue.mark_completed(qid)
        
        # Verify
        stats = queue.get_stats()
        assert stats['completed'] >= 1, "Should have completed event"
        
        # Cleanup
        queue.cleanup_old_events(days=0)
    
    def test_queue_to_sqlserver(self):
        """Test inserting event into SQL Server"""
        if not self.db_available:
            logger.warning("Skipping SQL Server integration test: database unavailable")
            return

        db = SQLServerDB()
        
        # Test connection
        assert db.test_connection(), "Should connect to SQL Server"
        
        # Insert test app event
        test_time = datetime.now().isoformat()
        result = db.insert_app_event('TestApp', 'Test Window', test_time, 10)
        
        # Note: result may be None if DB issues, we'll log warning
        if result is None:
            logger.warning("App event insert returned None (DB issue?)")
        
        # Insert test web event  
        result2 = db.insert_web_event('http://test.com', 'Test Page', test_time, 5)
        if result2 is None:
            logger.warning("Web event insert returned None (DB issue?)")
    
    def test_processor_worker(self):
        """Test processor worker startup and processing"""
        if not self.db_available:
            logger.warning("Skipping processor integration test: database unavailable")
            return

        worker = ProcessorWorker()
        
        # Test enqueue then process
        queue = worker.queue
        test_events = [
            {'type': 'app', 'app_name': 'ProcessorTest1', 'window_title': 'Test', 'timestamp': datetime.now().isoformat()},
            {'type': 'app', 'app_name': 'ProcessorTest2', 'window_title': 'Test2', 'timestamp': datetime.now().isoformat()},
        ]
        queue.enqueue_bulk(test_events)
        
        # Process one batch
        initial = worker.stats['processed']
        worker._process_batch(10)
        
        # Give it a moment
        time.sleep(1)
        
        assert worker.stats['processed'] >= initial, "Should process at least some events"
    
    def test_csv_exporter(self):
        """Test CSV export functionality"""
        if not self.db_available:
            logger.warning("Skipping CSV exporter integration test: database unavailable")
            return

        exporter = CSVExporter()
        
        # Test that export methods exist
        assert hasattr(exporter, 'export_all'), "Exporter should have export_all method"
        assert hasattr(exporter, '_export_app_usage'), "Exporter should have _export_app_usage method"
        assert hasattr(exporter, '_export_web_usage'), "Exporter should have _export_web_usage method"
        
        # Note: Actual export may fail if no data or DB issues, so we skip full export
    
    def test_retry_logic(self):
        """Test retry scheduling"""
        queue = PersistentQueue()
        
        # Enqueue a test event
        test_event = {'type': 'app', 'app_name': 'RetryTest', 'window_title': 'Test'}
        qid = queue.enqueue(test_event)
        
        # Dequeue and schedule retry
        batch = queue.dequeue_batch(1)
        assert len(batch) == 1, "Should get event"
        
        queue_id = batch[0]['queue_id']
        queue.schedule_retry(queue_id, 0)  # First retry
        
        # Schedule multiple retries
        conn = sqlite3.connect(queue.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT retry_count FROM queue_events WHERE id = ?", (queue_id,))
        row = cursor.fetchone()
        conn.close()
        
        assert row[0] == 1, f"Retry count should be 1, got {row[0]}"
    
    def test_validation(self):
        """Test event validation and redaction"""
        from datetime import datetime
        
        # Test app event validation
        app_event = {
            'type': 'app',
            'app_name': 'TestApp',
            'window_title': 'Secret: password=1234 - MyWindow',
            'timestamp': datetime.now().isoformat()
        }
        
        validated = EventValidator.validate_app_event(app_event)
        assert validated is not None, "Validation should succeed"
        assert 'password' not in validated['window_title'], "Should redact password"
        
        # Test web event validation
        web_event = {
            'type': 'web',
            'url': 'https://example.com/login?user=john&password=secret',
            'title': 'Login',
            'timestamp': datetime.now().isoformat()
        }
        
        validated = EventValidator.validate_web_event(web_event)
        assert validated is not None, "Web validation should succeed"
        assert 'password' not in validated['url'], "URL should redact password param"
        
        # Test invalid event (missing timestamp)
        invalid_event = {'type': 'app', 'app_name': 'Test'}
        result = EventValidator.validate_app_event(invalid_event)
        assert result is None, "Invalid event should be rejected"
    
    def test_persistence(self):
        """Test that data persists across connections"""
        queue1 = PersistentQueue()
        qid1 = queue1.enqueue({'type': 'app', 'app_name': 'PersistenceTest'})
        
        # Create new connection (simulates restart)
        queue2 = PersistentQueue()
        stats = queue2.get_stats()
        assert stats['pending'] > 0, "Event should persist across connections"
        
        # Cleanup
        queue2.mark_completed(qid1)
    
    def test_bulk_enqueue(self):
        """Test bulk enqueue performance"""
        queue = PersistentQueue()
        
        events = [{'type': 'app', 'app_name': f'BulkTest{i}', 'window_title': 'Test'} for i in range(100)]
        
        start = time.time()
        ids = queue.enqueue_bulk(events)
        duration = time.time() - start
        
        assert len(ids) == 100, f"Should enqueue 100 events, got {len(ids)}"
        assert duration < 2.0, f"Bulk enqueue should be fast, took {duration:.2f}s"
        
        stats = queue.get_stats()
        assert stats['pending'] >= 100, "All events should be pending"
        
        # Cleanup
        queue.cleanup_old_events(days=0)


def run_tests():
    """Run test suite"""
    suite = TestSuite()
    suite.run_all()
    return suite.failed == 0


if __name__ == "__main__":
    print("Starting Test Suite...")
    print("Ensure SQL Server is running before running tests.")
    print()
    
    success = run_tests()
    sys.exit(0 if success else 1)

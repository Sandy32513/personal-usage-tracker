"""
Persistent Queue Module
SQLite-based queue with retry logic and guaranteed delivery
All events are persisted before processing to ensure zero data loss
"""

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List

from app.config import INITIAL_RETRY_DELAY, MAX_QUEUE_SIZE, MAX_RETRY_COUNT, MAX_RETRY_DELAY, QUEUE_DB_PATH, QUEUE_STATUS

logger = logging.getLogger(__name__)


class QueueFullError(Exception):
    """Raised when queue is at capacity"""
    pass


class QueueCorruptionError(Exception):
    """Raised when queue database is corrupted"""
    pass


class PersistentQueue:
    """
    Persistent queue using SQLite with retry logic
    Ensures no data loss during system failures
    Max size prevents disk exhaustion
    WAL mode for better concurrency
    """
    
    def __init__(self, max_size: int = None):
        self.db_path = QUEUE_DB_PATH
        self.max_size = max_size if max_size is not None else MAX_QUEUE_SIZE
        self._write_lock = threading.Lock()  # Atomic check+insert
        self._init_db()
    
    def _init_db(self):
        """Initialize queue database with required tables"""
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            
            conn = sqlite3.connect(self.db_path, isolation_level=None)
            cursor = conn.cursor()
            
            # Enable WAL mode for better concurrency
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.execute('PRAGMA synchronous=NORMAL')
            cursor.execute('PRAGMA busy_timeout=5000')
            
            # Create queue_events table with schema version
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS queue_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_message TEXT,
                    next_retry_at TEXT
                )
            ''')
            
            # Create indexes for performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_status_retry ON queue_events(status, retry_count, next_retry_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON queue_events(created_at)')
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS idx_next_retry ON queue_events(next_retry_at) "
                f"WHERE status = '{QUEUE_STATUS['PENDING']}'"
            )
            
            conn.commit()
            conn.close()
            logger.info(f"Queue database initialized at {self.db_path}")
            
            # Recover any orphaned processing events on startup
            self._recover_stale_processing()
            
        except Exception as e:
            logger.error(f"Failed to initialize queue DB: {e}")
            raise

    def _recover_stale_processing(self, stale_timeout_minutes: int = 5, conn: sqlite3.Connection = None):
        """
        Reset events stuck in 'processing' state back to 'pending'.
        Called on startup and periodically by processor worker.
        Returns number of recovered events.
        If conn is provided, use it; otherwise create a new connection.
        """
        should_close = False
        try:
            if conn is None:
                conn = sqlite3.connect(self.db_path)
                should_close = True

            cursor = conn.cursor()

            # Calculate cutoff time in ISO format
            from datetime import datetime, timedelta
            cutoff = (datetime.now() - timedelta(minutes=stale_timeout_minutes)).isoformat()

            # Reset processing events that haven't been updated since cutoff
            cursor.execute('''
                UPDATE queue_events
                SET status = 'pending', updated_at = ?
                WHERE status = 'processing' AND updated_at < ?
            ''', (datetime.now().isoformat(), cutoff))

            recovered = cursor.rowcount
            conn.commit()

            if recovered > 0:
                logger.warning(f"Recovered {recovered} stale processing events back to pending")

            return recovered

        except Exception as e:
            logger.error(f"Failed to recover stale processing events: {e}")
            return 0
        finally:
            if should_close and conn:
                conn.close()
    
    def enqueue(self, event: Dict[str, Any]) -> int:
        """
        Add an event to the queue
        Returns queue ID or raises exception
        Thread-safe: check+insert are atomic within lock
        """
        try:
            # Atomic check + insert within lock
            with self._write_lock:
                # Check queue size before inserting
                stats = self.get_stats()
                if stats['total'] >= self.max_size:
                    logger.error(f"Queue full ({self.max_size} events). Rejecting event: {event.get('type')}")
                    raise QueueFullError(f"Queue at maximum capacity ({self.max_size})")
                
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
            
            now = datetime.now().isoformat()
            payload_json = json.dumps(event, ensure_ascii=False)
            
            cursor.execute('''
                INSERT INTO queue_events (payload, status, created_at, updated_at)
                VALUES (?, ?, ?, ?)
            ''', (payload_json, QUEUE_STATUS['PENDING'], now, now))
            
            queue_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            logger.debug(f"Enqueued event ID {queue_id}: {event.get('type', 'unknown')}")
            return queue_id
            
        except QueueFullError:
            raise
        except Exception as e:
            logger.error(f"Failed to enqueue event: {e}")
            raise
    
    def enqueue_bulk(self, events: List[Dict[str, Any]]) -> List[int]:
        """Enqueue multiple events in a single transaction"""
        if not events:
            return []
        
        # Check if adding these would exceed max size
        stats = self.get_stats()
        if stats['total'] + len(events) > self.max_size:
            allowed = max(0, self.max_size - stats['total'])
            logger.error(f"Queue near capacity. Only {allowed} events allowed, {len(events)} requested")
            raise QueueFullError(f"Queue would exceed max size ({self.max_size})")
        
        ids = []
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            
            for event in events:
                payload_json = json.dumps(event, ensure_ascii=False)
                cursor.execute('''
                    INSERT INTO queue_events (payload, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                ''', (payload_json, QUEUE_STATUS['PENDING'], now, now))
                ids.append(cursor.lastrowid)
            
            conn.commit()
            conn.close()
            logger.info(f"Enqueued {len(ids)} events in bulk")
            return ids
            
        except Exception as e:
            logger.error(f"Failed to enqueue bulk events: {e}")
            raise
    
    def dequeue_batch(self, batch_size: int = 10) -> List[Dict[str, Any]]:
        """
        Atomically claim a batch of pending events for processing.
        Uses single UPDATE...RETURNING transaction to avoid race conditions.
        Returns list of claimed event payloads with queue_id.
        """
        try:
            conn = sqlite3.connect(self.db_path, isolation_level='DEFERRED')
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            
            # Atomically claim batch using UPDATE...RETURNING (SQLite 3.35+)
            cursor.execute('''
                UPDATE queue_events
                SET status = ?, updated_at = ?
                WHERE id IN (
                    SELECT id FROM queue_events
                    WHERE status = ?
                    AND (next_retry_at IS NULL OR next_retry_at <= ?)
                    ORDER BY created_at ASC
                    LIMIT ?
                )
                RETURNING id, payload, retry_count
            ''', (QUEUE_STATUS['PROCESSING'], now, QUEUE_STATUS['PENDING'], now, batch_size))
            
            rows = cursor.fetchall()
            conn.commit()
            conn.close()
            
            events = []
            for row in rows:
                queue_id, payload_json, retry_count = row
                try:
                    payload = json.loads(payload_json)
                    events.append({
                        'queue_id': queue_id,
                        'payload': payload,
                        'retry_count': retry_count
                    })
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON in queue ID {queue_id}, skipping")
                    # Mark as failed to remove from queue
                    self.mark_failed(queue_id, "JSON decode error")
            
            if events:
                logger.debug(f"Atomically claimed {len(events)} events")
            return events
            
        except Exception as e:
            logger.error(f"Failed to dequeue batch: {e}")
            return []
    
    def mark_processing(self, queue_id: int):
        """Mark event as processing"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            
            cursor.execute('''
                UPDATE queue_events 
                SET status = ?, updated_at = ?
                WHERE id = ?
            ''', (QUEUE_STATUS['PROCESSING'], now, queue_id))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Failed to mark processing for queue ID {queue_id}: {e}")
    
    def mark_completed(self, queue_id: int):
        """Mark event as completed"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            
            cursor.execute('''
                UPDATE queue_events 
                SET status = ?, updated_at = ?
                WHERE id = ?
            ''', (QUEUE_STATUS['COMPLETED'], now, queue_id))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Failed to mark completed for queue ID {queue_id}: {e}")
    
    def mark_failed(self, queue_id: int, error_message: str = None):
        """Mark event as failed after exhausting retries"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            
            cursor.execute('''
                UPDATE queue_events 
                SET status = ?, updated_at = ?, error_message = ?
                WHERE id = ?
            ''', (QUEUE_STATUS['FAILED'], now, error_message, queue_id))
            
            conn.commit()
            conn.close()
            logger.warning(f"Marked queue ID {queue_id} as failed: {error_message}")
            
        except Exception as e:
            logger.error(f"Failed to mark failed for queue ID {queue_id}: {e}")
    
    def schedule_retry(self, queue_id: int, current_retry_count: int = None) -> bool:
        """
        Schedule a retry with exponential backoff
        Returns True if retry should be attempted, False if max retries exceeded
        Pass current_retry_count for efficiency, or it will be fetched from DB
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Fetch current retry_count if not provided
            if current_retry_count is None:
                cursor.execute("SELECT retry_count FROM queue_events WHERE id = ?", (queue_id,))
                row = cursor.fetchone()
                if row:
                    current_retry_count = row[0]
                else:
                    logger.error(f"Queue ID {queue_id} not found for retry")
                    conn.close()
                    return False
            
            new_retry_count = current_retry_count + 1
            
            if new_retry_count >= MAX_RETRY_COUNT:
                now = datetime.now().isoformat()
                cursor.execute('''
                    UPDATE queue_events 
                    SET status = ?, updated_at = ?, error_message = ?
                    WHERE id = ?
                ''', (QUEUE_STATUS['FAILED'], now, f"Max retries ({MAX_RETRY_COUNT}) exceeded", queue_id))
                conn.commit()
                conn.close()
                logger.error(f"Queue ID {queue_id} exceeded max retries ({MAX_RETRY_COUNT})")
                return False
            
            # Calculate next retry time with exponential backoff
            delay = min(INITIAL_RETRY_DELAY * (2 ** current_retry_count), MAX_RETRY_DELAY)
            next_retry_timestamp = datetime.now().timestamp() + delay
            next_retry_str = datetime.fromtimestamp(next_retry_timestamp).isoformat()
            
            now = datetime.now().isoformat()
            
            cursor.execute('''
                UPDATE queue_events 
                SET status = ?, 
                    retry_count = ?,
                    updated_at = ?,
                    next_retry_at = ?
                WHERE id = ?
            ''', (QUEUE_STATUS['PENDING'], new_retry_count, now, next_retry_str, queue_id))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Scheduled retry {new_retry_count}/{MAX_RETRY_COUNT} for queue ID {queue_id} in {delay:.1f}s")
            return True
            
        except Exception as e:
            logger.error(f"Failed to schedule retry for queue ID {queue_id}: {e}")
            return False
    
    def get_stats(self) -> Dict[str, int]:
        """Get queue statistics"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT status, COUNT(*) 
                FROM queue_events 
                GROUP BY status
            ''')
            
            stats = {row[0]: row[1] for row in cursor.fetchall()}
            conn.close()
            
            return {
                'pending': stats.get(QUEUE_STATUS['PENDING'], 0),
                'processing': stats.get(QUEUE_STATUS['PROCESSING'], 0),
                'failed': stats.get(QUEUE_STATUS['FAILED'], 0),
                'completed': stats.get(QUEUE_STATUS['COMPLETED'], 0),
                'total': sum(stats.values())
            }
            
        except Exception as e:
            logger.error(f"Failed to get queue stats: {e}")
            return {'pending': 0, 'processing': 0, 'failed': 0, 'completed': 0, 'total': 0}

    def get_size(self) -> int:
        """Return the total number of queued records."""
        return self.get_stats()['total']
    
    # ===== New v3.1 Features =====
    
    def check_backpressure(self) -> Dict[str, Any]:
        """Check if backpressure is needed - returns warning if queue is backing up"""
        stats = self.get_stats()
        pending = stats.get('pending', 0)
        
        warnings = []
        if pending > 100000:
            warnings.append(f"Severe backlog: {pending} pending events")
        elif pending > 50000:
            warnings.append(f"Moderate backlog: {pending} pending events")
        
        return {
            'backpressure_needed': pending > 50000,
            'pending': pending,
            'warnings': warnings,
        }
    
    def deduplicate(self, event_signature_fields: List[str] = None) -> int:
        """Remove duplicate events based on signature fields. Returns count removed."""
        if event_signature_fields is None:
            event_signature_fields = ['type', 'app_name', 'window_title']
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Find duplicates
            placeholders = ', '.join(['payload LIKE ?'] * len(event_signature_fields))
            cursor.execute(f'''
                SELECT payload FROM queue_events 
                WHERE status = 'pending'
            ''')
            
            seen = set()
            duplicates = []
            for row in cursor.fetchall():
                payload = json.loads(row[0])
                sig = tuple(payload.get(f) for f in event_signature_fields)
                if sig in seen:
                    duplicates.append(payload.get('id') or payload.get('_queue_id'))
                seen.add(sig)
            
            # Remove duplicates
            if duplicates:
                placeholders = ','.join('?' * len(duplicates))
                cursor.execute(f'DELETE FROM queue_events WHERE id IN ({placeholders})', duplicates)
                conn.commit()
            
            conn.close()
            logger.info(f"Deduplication removed {len(duplicates)} duplicate events")
            return len(duplicates)
            
        except Exception as e:
            logger.error(f"Deduplication failed: {e}")
            return 0
    
    def repair_corruption(self) -> Dict[str, Any]:
        """Attempt to repair corrupted queue database. Returns repair report."""
        report = {'checked': False, 'repaired': False, 'issues': []}
        
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            report['checked'] = True
            
            # Check table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='queue_events'")
            if not cursor.fetchone():
                report['issues'].append("Table missing - recreating")
                self._init_db()
                report['repaired'] = True
                return report
            
            # Check for invalid JSON in payload
            cursor.execute('SELECT id, payload FROM queue_events')
            invalid = []
            for row in cursor.fetchall():
                try:
                    json.loads(row[1])
                except:
                    invalid.append(row[0])
            
            if invalid:
                report['issues'].append(f"{len(invalid)} invalid JSON payloads")
                cursor.execute(f'DELETE FROM queue_events WHERE id IN ({",".join("?" * len(invalid))})', invalid)
                conn.commit()
                report['repaired'] = True
            
            # Use the dedicated method for stale processing recovery, pass existing connection
            stale_count = self._recover_stale_processing(conn=conn)
            if stale_count > 0:
                report['issues'].append(f"Released {stale_count} orphaned processing events")
                report['repaired'] = True
            
            logger.info(f"Queue repair report: {report}")
            return report
            
        except Exception as e:
            logger.error(f"Queue repair failed: {e}")
            report['issues'].append(str(e))
            return report
        finally:
            if conn:
                conn.close()
    
    def cleanup_old_events(self, days: int = 30):
        """Remove completed events older than specified days"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            
            cursor.execute('''
                DELETE FROM queue_events 
                WHERE status = ? AND updated_at < ?
            ''', (QUEUE_STATUS['COMPLETED'], cutoff))
            
            deleted = cursor.rowcount
            conn.commit()
            conn.close()
            
            logger.info(f"Cleaned up {deleted} old events")
            return deleted
            
        except Exception as e:
            logger.error(f"Failed to cleanup old events: {e}")
            return 0


# Standalone test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    queue = PersistentQueue()
    
    print("Testing PersistentQueue...")
    print("-" * 50)
    
    # Test enqueue
    test_events = [
        {'type': 'app', 'app_name': 'Chrome', 'window_title': 'Test'},
        {'type': 'web', 'url': 'https://google.com', 'title': 'Google'}
    ]
    
    for event in test_events:
        qid = queue.enqueue(event)
        print(f"Enqueued event ID: {qid}")
    
    # Test dequeue
    batch = queue.dequeue_batch(5)
    print(f"\nDequeued {len(batch)} events")
    
    # Test stats
    stats = queue.get_stats()
    print(f"\nQueue stats: {stats}")
    
    print("-" * 50)
    print("Test complete.")

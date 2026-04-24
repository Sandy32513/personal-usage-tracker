"""
Queue Processor Worker
Continuously processes events from persistent queue to SQL Server
Implements retry logic with exponential backoff
Ensures zero data loss during DB outages
Circuit breaker prevents thundering herd during prolonged outages
"""

import time
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from app.config import PROCESSOR_INTERVAL, QUEUE_STATUS
from app.queue.queue_db import PersistentQueue, QueueFullError
from app.db.sqlserver import SQLServerDB
from app.validation import EventValidator
import threading

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """
    Circuit breaker to prevent overwhelming DB during outages
    Opens after threshold failures, stays open for recovery_timeout
    Thread-safe implementation with lock protection
    """
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout  # seconds
        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF_OPEN
        self._lock = threading.Lock()  # Thread-safe access
    
    def record_failure(self):
        """Record a failure and potentially open circuit"""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold and self.state == 'CLOSED':
                self.state = 'OPEN'
                logger.error(f"Circuit breaker OPEN after {self.failure_count} failures. Pausing {self.recovery_timeout}s")
    
    def record_success(self):
        """Record a success, reset if was OPEN"""
        with self._lock:
            if self.state == 'OPEN':
                # Only close after waiting recovery_timeout
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = 'HALF_OPEN'
                    logger.info("Circuit breaker HALF_OPEN — testing DB connectivity")
            
            elif self.state == 'HALF_OPEN':
                # Successful call in HALF_OPEN closes circuit
                self.state = 'CLOSED'
                self.failure_count = 0
                self.last_failure_time = None
                logger.info("Circuit breaker CLOSED — DB recovered")
    
    def can_attempt(self) -> bool:
        """Check if we should attempt DB call"""
        with self._lock:
            if self.state == 'CLOSED':
                return True

            if self.state == 'OPEN':
                # Check if recovery timeout elapsed
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = 'HALF_OPEN'
                    logger.info("Circuit breaker transitioning to HALF_OPEN")
                    return True
                return False

            if self.state == 'HALF_OPEN':
                return True

            return False


class ProcessorWorker:
    """
    Worker that processes events from the queue and inserts into SQL Server.
    Supports circuit breaker, retry scheduling, and batch processing.
    """
    
    def __init__(self, num_workers: int = 1, queue: PersistentQueue = None, db = None):
        self.num_workers = num_workers
        self.queue = queue if queue is not None else PersistentQueue()
        self.db = db if db is not None else SQLServerDB()
        self.running = False
        self.threads = []
        self.stats = {
            'processed': 0,
            'failed': 0,
            'retried': 0,
            'last_error': None
        }
        self.last_cleanup_time = time.time()
        self.cleanup_interval = 86400  # Once per day
        self.last_recovery_time = time.time()
        self.recovery_interval = 300  # Every 5 minutes
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
    
    def start(self):
        """Start the processor worker(s) in background thread(s)"""
        if self.running:
            logger.warning("Processor already running")
            return
        
        self.running = True
        
        # Start worker threads
        for i in range(self.num_workers):
            t = threading.Thread(target=self._run, daemon=True, args=(i,))
            t.start()
            self.threads.append(t)
        
        logger.info(f"Processor worker started with {self.num_workers} workers")
    
    def stop(self):
        """Stop the processor worker(s) gracefully"""
        self.running = False
        for t in self.threads:
            t.join(timeout=10)
        self.threads.clear()
        logger.info("Processor worker stopped")
    
    def _run(self, worker_id: int = 0):
        """Main processing loop"""
        logger.info(f"Processor worker-{worker_id} started")
        
        while self.running:
            try:
                current_time = time.time()
                
                # Periodic cleanup of old completed events
                if current_time - self.last_cleanup_time >= self.cleanup_interval:
                    try:
                        cleaned = self.queue.cleanup_old_events(days=30)
                        if cleaned > 0:
                            logger.info(f"Cleaned up {cleaned} old queue events")
                    except Exception as e:
                        logger.error(f"Queue cleanup failed: {e}")
                    self.last_cleanup_time = current_time
                
                # Periodic recovery of stale processing events (C2 fix)
                if current_time - self.last_recovery_time >= self.recovery_interval:
                    try:
                        recovered = self.queue._recover_stale_processing(stale_timeout_minutes=5)
                        if recovered > 0:
                            logger.info(f"Recovered {recovered} stale processing events")
                    except Exception as e:
                        logger.error(f"Recovery failed: {e}")
                    self.last_recovery_time = current_time
                
                # Process batch of events
                self._process_batch()
                
                # Log stats periodically
                self._log_stats()
                
                # Sleep before next batch
                time.sleep(PROCESSOR_INTERVAL)
                
            except Exception as e:
                logger.error(f"Processor error: {e}", exc_info=True)
                self.stats['last_error'] = str(e)
                time.sleep(PROCESSOR_INTERVAL * 2)  # Longer backoff on error
    
    def _process_batch(self, batch_size: int = 10):
        """Process a batch of events from queue with circuit breaker protection"""
        try:
            # Check circuit breaker before attempting DB operations
            if not self.circuit_breaker.can_attempt():
                logger.warning("Circuit breaker OPEN — skipping DB operations")
                time.sleep(self.circuit_breaker.recovery_timeout)
                return
            
            # Get batch of pending events
            events = self.queue.dequeue_batch(batch_size)
            if not events:
                return
            
            logger.debug(f"Processing batch of {len(events)} events")
            
            # Validate all events first (collect valid ones with their queue_ids)
            valid_entries = []  # List of (queue_id, validated_payload)
            validation_failures = 0
            
            for event_data in events:
                queue_id = event_data['queue_id']
                payload = event_data['payload']
                retry_count = event_data.get('retry_count', 0)
                
                # Validate event before processing
                event_type = payload.get('type')
                if event_type == 'app':
                    validated_payload = EventValidator.validate_app_event(payload)
                elif event_type == 'web':
                    validated_payload = EventValidator.validate_web_event(payload)
                else:
                    logger.error(f"Unknown event type '{event_type}' for queue ID {queue_id}")
                    self.queue.mark_failed(queue_id, f"Unknown event type: {event_type}")
                    self.stats['failed'] += 1
                    continue
                
                if not validated_payload:
                    logger.error(f"Event validation failed for queue ID {queue_id}")
                    self.queue.mark_failed(queue_id, "Validation failed")
                    self.stats['failed'] += 1
                    continue
                
                # Mark as processing (must do before batch to avoid re-queue on crash)
                self.queue.mark_processing(queue_id)
                
                valid_entries.append((queue_id, validated_payload))
            
            if not valid_entries:
                return
            
            # Extract payloads for batch insert
            payloads = [entry[1] for entry in valid_entries]
            queue_ids = [entry[0] for entry in valid_entries]
            
            # Batch insert all valid events at once (M4 performance fix)
            success_count = 0
            try:
                # Use batch insert method for performance
                success_indices, failed_indices = self.db.insert_batch_from_queue(payloads)
                
                if success_indices:
                    for idx in success_indices:
                        self.queue.mark_completed(queue_ids[idx])
                        self.stats['processed'] += 1
                        success_count += 1
                
                if failed_indices:
                    for idx in failed_indices:
                        qid = queue_ids[idx]
                        if self.queue.schedule_retry(qid, 0):
                            self.stats['retried'] += 1
                        else:
                            self.stats['failed'] += 1
                
            except Exception as e:
                logger.error(f"Batch insert error: {e}", exc_info=True)
                # If batch fails as a whole, retry all
                self.circuit_breaker.record_failure()
                for qid, _ in valid_entries:
                    if self.queue.schedule_retry(qid, 0):
                        self.stats['retried'] += 1
                    else:
                        self.stats['failed'] += 1
            
            # Record circuit breaker success if at least partial success
            if success_count > 0:
                self.circuit_breaker.record_success()
            else:
                self.circuit_breaker.record_failure()
                
        except Exception as e:
            logger.error(f"Error processing batch: {e}", exc_info=True)
            self.circuit_breaker.record_failure()
            self.stats['last_error'] = str(e)
    
    def _log_stats(self):
        """Log processing statistics"""
        # Only log every 5 minutes (300 seconds worth of cycles)
        if int(time.time()) % 300 < PROCESSOR_INTERVAL:
            logger.info(f"Processor stats - Processed: {self.stats['processed']}, "
                       f"Retried: {self.stats['retried']}, "
                       f"Failed: {self.stats['failed']}")
    
    def process_single_now(self):
        """
        Process one batch immediately (useful for testing)
        Returns number of events processed
        """
        initial_count = self.stats['processed']
        self._process_batch()
        return self.stats['processed'] - initial_count


# Standalone test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("Testing ProcessorWorker...")
    print("-" * 50)
    
    worker = ProcessorWorker()
    worker.start()
    
    # Let it run for 15 seconds
    time.sleep(15)
    
    # Stop
    worker.stop()
    
    print(f"\nFinal stats: {worker.stats}")
    print("-" * 50)
    print("Test complete.")
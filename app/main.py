"""
Main Entry Point — Personal Usage Tracker V3
Supports three modes:
  1. service  — Runs data pipeline (queue, DB insert, export). For Windows Service.
  2. agent     — Runs capture only (app+browser) and forwards to service via IPC.
  3. combined  — Legacy single-process mode (both capture + pipeline in one).
"""

import sys
import time
import logging
import argparse
import asyncio
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import BROWSER_SCAN_INTERVAL, LOG_FILE, LOG_LEVEL, TRACK_INTERVAL, log_config
from app.tracker.app_tracker import AppTracker
from app.tracker.browser_tracker import BrowserTracker
from app.queue.queue_db import PersistentQueue
from app.processor.worker import ProcessorWorker
from app.exporter.csv_exporter import CSVExporter
from app.db.sqlserver import SQLServerDB
from app.health import HealthServer

logger = logging.getLogger(__name__)


class UsageTrackerService:
    """Data pipeline service: receives events (from agent or local), queues, processes, exports."""
    
    def __init__(self):
        self.db = None
        self.queue = PersistentQueue()
        self.processor = None
        self.exporter = None
        self.health_server = None
        self.ipc_server = None
        self.ipc_thread = None
        self.running = False
    
    def initialize(self):
        """Initialize all components with fail-fast on DB errors"""
        logger.info("Initializing Personal Usage Tracker Service...")
        
        # 1. Test DB connection and schema (C4 fix)
        logger.info("Testing SQL Server connection and schema...")
        self.db = SQLServerDB()
        if not self.db.test_connection():
            logger.critical("Database unavailable or schema missing — service cannot start")
            raise RuntimeError("Database connection/schema validation failed")
        logger.info("Database OK")
        
        # 2. Start processor
        self.processor = ProcessorWorker()
        self.processor.start()
        logger.info("Processor worker started")
        
        # 3. Start exporter
        self.exporter = CSVExporter()
        self.exporter.start()
        logger.info("CSV exporter started")
        
        # 4. Start health endpoint
        self.health_server = HealthServer()
        self.health_server.start()
        logger.info("Health server started")
        
        # 5. Start IPC listener for agent events
        self._start_ipc_server()
        logger.info("IPC server started — waiting for agent connections")
    
    def _start_ipc_server(self):
        """Start TCP socket server on 127.0.0.1:8766 to accept events from agent."""
        import socket
        import threading
        import json
        
        def client_handler(conn, addr):
            logger.info(f"Agent connected from {addr}")
            try:
                buffer = b''
                while self.running:
                    data = conn.recv(4096)
                    if not data:
                        break
                    buffer += data
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        try:
                            event = json.loads(line.decode('utf-8'))
                            # Determine validator
                            from app.validation import EventValidator
                            ev_type = event.get('type', 'app')
                            if ev_type == 'app':
                                validated = EventValidator.validate_app_event(event)
                            elif ev_type == 'web':
                                validated = EventValidator.validate_web_event(event)
                            else:
                                validated = None
                            
                            if validated:
                                queue_id = self.queue.enqueue(validated)
                                logger.debug(f"Enqueued event ID={queue_id} from agent")
                            else:
                                logger.warning(f"Invalid event from agent: {event}")
                        except json.JSONDecodeError:
                            logger.error(f"Malformed JSON from agent")
                conn.close()
                logger.info(f"Agent disconnected: {addr}")
            except Exception as e:
                logger.error(f"Client handler error: {e}")
        
        def server_loop():
            host = '127.0.0.1'
            port = 8766
            self.ipc_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.ipc_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self.ipc_server.bind((host, port))
                self.ipc_server.listen(5)
                self.ipc_server.settimeout(1)
                logger.info(f"IPC server listening on {host}:{port}")
                while self.running:
                    try:
                        conn, addr = self.ipc_server.accept()
                        t = threading.Thread(target=client_handler, args=(conn, addr), daemon=True)
                        t.start()
                    except socket.timeout:
                        continue
            except Exception as e:
                logger.error(f"IPC server failed: {e}")
            finally:
                self.ipc_server.close()
        
        self.ipc_thread = threading.Thread(target=server_loop, daemon=True)
        self.ipc_thread.start()
    
    def run(self):
        """Main service loop."""
        logger.info("UsageTracker Service starting...")
        self.running = True
        
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutdown requested")
            self.stop()
    
    def stop(self):
        """Stop all components."""
        logger.info("Stopping service...")
        self.running = False
        if self.processor:
            self.processor.stop()
        if self.exporter:
            self.exporter.stop()
        if self.health_server:
            self.health_server.stop()
        if self.ipc_server:
            self.ipc_server.close()
        logger.info("Service stopped")


class UsageTrackerAgent:
    """User-session agent: captures app/browser events and forwards to service."""
    
    def __init__(self, service_host='127.0.0.1', service_port=8766):
        self.service_host = service_host
        self.service_port = service_port
        self.app_tracker = AppTracker()
        self.browser_tracker = BrowserTracker()
        self.running = False
        self.last_browser_scan = time.time()
    
    def _send_event(self, event: dict) -> bool:
        """Send event to service via TCP socket."""
        import socket
        try:
            payload = json.dumps(event, ensure_ascii=False) + '\n'
            with socket.create_connection((self.service_host, self.service_port), timeout=2) as sock:
                sock.sendall(payload.encode('utf-8'))
            return True
        except Exception as e:
            logger.error(f"Failed to send to service: {e}")
            return False
    
    def run(self):
        """Main capture loop."""
        logger.info("UsageTracker Agent starting capture loop...")
        self.running = True
        last_scan = time.time()
        
        while self.running:
            try:
                current_time = time.time()
                
                # Capture app event
                app_event = self.app_tracker.capture_event()
                if app_event:
                    self._send_event(app_event)
                    logger.debug(f"Sent app: {app_event.get('app_name')}")
                
                # Capture browser events periodically
                if current_time - last_scan >= BROWSER_SCAN_INTERVAL:
                    try:
                        browser_events = self.browser_tracker.capture_events()
                        for bev in browser_events:
                            self._send_event(bev)
                        logger.debug(f"Sent {len(browser_events)} browser events")
                    except Exception as e:
                        logger.error(f"Browser capture error: {e}")
                    last_scan = current_time
                
                time.sleep(TRACK_INTERVAL)
            except Exception as e:
                logger.error(f"Agent loop error: {e}", exc_info=True)
                time.sleep(5)
    
    def stop(self):
        self.running = False
        logger.info("Agent stopped")


def main():
    parser = argparse.ArgumentParser(description="Personal Usage Tracker V3")
    parser.add_argument('mode', choices=['service', 'agent', 'combined', 'run'], 
                        default='run', nargs='?',
                        help='Run mode: service (data pipeline), agent (capture only), combined (all-in-one, legacy)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()
    
    # Setup logging
    setup_logging()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info(f"Starting in '{args.mode}' mode")
    
    if args.mode == 'service':
        svc = UsageTrackerService()
        svc.initialize()
        svc.run()
    elif args.mode == 'agent':
        agent = UsageTrackerAgent()
        try:
            agent.run()
        except KeyboardInterrupt:
            agent.stop()
    elif args.mode in ['run', 'combined']:
        # Legacy combined mode (single process)
        logger.warning("'combined' mode is deprecated; use 'service'+'agent' for production")
        run_combined_mode()


def run_combined_mode():
    """Legacy single-process mode (all components in one)."""
    from app.validation import EventValidator
    validator = EventValidator()
    
    queue = PersistentQueue()
    processor = ProcessorWorker()
    exporter = CSVExporter()
    app_tracker = AppTracker()
    browser_tracker = BrowserTracker()
    
    processor.start()
    exporter.start()
    exporter.run_once()  # initial export
    
    last_browser = time.time()
    logger.info("Combined mode started")
    
    try:
        while True:
            # App capture
            app_event = app_tracker.capture_event()
            if app_event:
                validated = validator.validate_app_event(app_event)
                if validated:
                    queue.enqueue(validated)
            
            # Browser capture
            if time.time() - last_browser >= BROWSER_SCAN_INTERVAL:
                try:
                    events = browser_tracker.capture_events()
                    for ev in events:
                        v = validator.validate_web_event(ev)
                        if v:
                            queue.enqueue(v)
                    last_browser = time.time()
                except Exception as e:
                    logger.error(f"Browser capture error: {e}")
            
            time.sleep(TRACK_INTERVAL)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        processor.stop()
        exporter.stop()


def setup_logging():
    """Configure logging."""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    handlers = [logging.StreamHandler(sys.stdout)]
    try:
        from logging.handlers import RotatingFileHandler
        handlers.append(RotatingFileHandler(
            LOG_FILE, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
        ))
    except Exception:
        try:
            handlers.append(logging.FileHandler(LOG_FILE, encoding='utf-8'))
        except:
            pass
    
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format=log_format,
        handlers=handlers
    )
    logging.getLogger('pyodbc').setLevel(logging.WARNING)


if __name__ == '__main__':
    main()

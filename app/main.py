"""
Main Entry Point
Coordinates all components of Personal Usage Tracker V3
Can run as console app or Windows Service
"""

import sys
import time
import logging
import argparse
from app.config import BROWSER_SCAN_INTERVAL, LOG_FILE, LOG_LEVEL, TRACK_INTERVAL, log_config
from app.tracker.app_tracker import AppTracker
from app.tracker.browser_tracker import BrowserTracker
from app.queue.queue_db import PersistentQueue, QueueFullError
from app.processor.worker import ProcessorWorker
from app.exporter.csv_exporter import CSVExporter
from app.service.windows_service import ServiceManager
from app.db.sqlserver import SQLServerDB
from app.health import HealthServer

# Configure logging
def setup_logging():
    """Configure logging for the application with rotation"""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Create handlers
    handlers = [logging.StreamHandler(sys.stdout)]
    
    # Add rotating file handler if log path is writable
    try:
        from logging.handlers import RotatingFileHandler
        max_bytes = 10 * 1024 * 1024  # 10MB max per file
        backup_count = 5  # Keep 5 backup files
        handlers.append(RotatingFileHandler(
            LOG_FILE, 
            maxBytes=max_bytes, 
            backupCount=backup_count,
            encoding='utf-8'
        ))
    except Exception:
        # Fallback to basic file handler
        try:
            handlers.append(logging.FileHandler(LOG_FILE, encoding='utf-8'))
        except:
            pass
    
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format=log_format,
        handlers=handlers
    )
    
    # Reduce noise from some libraries
    logging.getLogger('pyodbc').setLevel(logging.WARNING)
    logging.getLogger('pandas').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


class UsageTrackerApp:
    """
    Main application coordinator
    Manages all components and their lifecycles
    """
    
    def __init__(self):
        self.app_tracker = None
        self.browser_tracker = None
        self.queue = None
        self.processor = None
        self.exporter = None
        self.db = None
        self.health_server = None
        self.running = False
    
    def initialize(self):
        """Initialize all components"""
        logger.info("Initializing Personal Usage Tracker V3...")
        
        # Test database connection first
        logger.info("Testing SQL Server connection...")
        try:
            self.db = SQLServerDB()
            if not self.db.test_connection():
                logger.warning("SQL Server is currently unavailable. Tracking will continue and the queue will buffer events.")
        except Exception as e:
            logger.warning(f"Database initialization warning: {e}")
        
        # Initialize components
        self.app_tracker = AppTracker()
        logger.info("App tracker initialized")
        
        self.browser_tracker = BrowserTracker()
        logger.info("Browser tracker initialized")
        
        self.queue = PersistentQueue()
        logger.info("Persistent queue initialized")
        
        self.processor = ProcessorWorker()
        logger.info("Processor worker initialized")
        
        self.exporter = CSVExporter()
        logger.info("CSV exporter initialized")
        
        logger.info("All components initialized successfully")
        return True
    
    def start(self):
        """Start all components"""
        if not self.initialize():
            logger.error("Initialization failed, cannot start")
            return False
        
        logger.info("Starting all components...")
        
        # Start health server
        self.health_server = HealthServer()
        if self.health_server.start():
            logger.info("Health server started")
        else:
            logger.warning("Health server failed to start")
        
        # Start processor (reads from queue -> DB)
        self.processor.start()
        logger.info("Processor started")
        
        # Start exporter (writes CSV from DB)
        self.exporter.start()
        logger.info("Exporter started")
        
        self.running = True
        logger.info("✓ Personal Usage Tracker V3 is now running")
        return True
    
    def stop(self):
        """Stop all components"""
        self.running = False
        
        if self.health_server:
            self.health_server.stop()
            logger.info("Health server stopped")
        
        if self.exporter:
            self.exporter.stop()
            logger.info("Exporter stopped")
        
        if self.processor:
            self.processor.stop()
            logger.info("Processor stopped")
        
        logger.info("All components stopped")
    
    def run_forever(self):
        """Main tracking loop - runs forever"""
        if not self.start():
            return
        
        last_browser_scan = time.time()
        
        try:
            while self.running:
                try:
                    current_time = time.time()
                    
                    # Capture and queue active application
                    app_event = self.app_tracker.capture_event()
                    if app_event:
                        try:
                            self.queue.enqueue(app_event)
                            logger.debug(f"Queued: {app_event['app_name']} - {app_event['window_title'][:50]}")
                        except QueueFullError:
                            logger.error("Queue is full! Event dropped. Check processor/DB performance.")
                    
                    # Capture browser history every 30 seconds
                    if current_time - last_browser_scan >= BROWSER_SCAN_INTERVAL:
                        try:
                            browser_events = self.browser_tracker.capture_events()
                            if browser_events:
                                try:
                                    self.queue.enqueue_bulk(browser_events)
                                    logger.debug(f"Queued {len(browser_events)} browser events")
                                except QueueFullError:
                                    logger.error(f"Queue full! Dropped {len(browser_events)} browser events")
                        except Exception as e:
                            logger.error(f"Browser tracking error: {e}")
                        
                        last_browser_scan = current_time
                    
                    # Sleep for track interval
                    time.sleep(TRACK_INTERVAL)
                    
                except KeyboardInterrupt:
                    logger.info("Keyboard interrupt received")
                    break
                except Exception as e:
                    logger.error(f"Error in tracking loop: {e}", exc_info=True)
                    time.sleep(5)  # Error backoff
        
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down...")
        self.running = False
        
        # Stop components
        if self.processor:
            self.processor.stop()
        
        if self.exporter:
            self.exporter.stop()
        
        logger.info("Shutdown complete")


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Personal Usage Tracker V3 - Track app usage and browser activity'
    )
    parser.add_argument(
        'command',
        choices=['run', 'export', 'install', 'remove', 'start', 'stop', 'status'],
        help='Command to execute'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Run in debug mode (console output)'
    )
    return parser.parse_args()


def main():
    """Main entry point"""
    if getattr(sys, 'frozen', False) and len(sys.argv) == 1:
        import win32serviceutil
        from app.service.windows_service import UsageTrackerService

        win32serviceutil.HandleCommandLine(UsageTrackerService)
        return

    args = parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if args.command == 'run':
        app = UsageTrackerApp()
        app.run_forever()
    
    elif args.command == 'export':
        setup_logging()
        logger.info("CSV Export command invoked")
        
        # Connect to DB
        db = SQLServerDB()
        if not db.test_connection():
            logger.error("Cannot connect to SQL Server")
            sys.exit(1)
        
        exporter = CSVExporter()
        result = exporter.export_manual()
        
        if result.get('app') and result.get('web'):
            logger.info("CSV export completed successfully")
            sys.exit(0)
        else:
            logger.error("CSV export failed")
            sys.exit(1)
    
    elif args.command == 'install':
        ServiceManager.install()
    
    elif args.command == 'remove':
        ServiceManager.remove()
    
    elif args.command == 'start':
        ServiceManager.start()
    
    elif args.command == 'stop':
        ServiceManager.stop()
    
    elif args.command == 'status':
        ServiceManager.status()


if __name__ == "__main__":
    setup_logging()
    log_config()
    main()

"""
Windows Service Module
Implements Windows Service using pywin32
Allows the application to run as a background Windows Service
"""

import win32serviceutil
import win32service
import win32event
import servicemanager
import socket
import time
import logging
import sys
from typing import Optional

from app.config import BROWSER_SCAN_INTERVAL, SERVICE_DESCRIPTION, SERVICE_DISPLAY_NAME, SERVICE_NAME
from app.exporter.csv_exporter import CSVExporter
from app.tracker.app_tracker import AppTracker
from app.tracker.browser_tracker import BrowserTracker
from app.queue.queue_db import PersistentQueue
from app.processor.worker import ProcessorWorker

logger = logging.getLogger(__name__)


class UsageTrackerService(win32serviceutil.ServiceFramework):
    """
    Windows Service for Personal Usage Tracker V3
    Manages tracking and processing in background
    """
    
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY_NAME
    _svc_description_ = SERVICE_DESCRIPTION
    
    def __init__(self, args):
        """Initialize the service"""
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        
        # Set service type to allow interactive (for debugging)
        socket.setdefaulttimeout(60)
        
        # Service state
        self.running = False
        self.tracker_thread = None
        self.processor_thread = None
        
        # Components
        self.app_tracker = None
        self.browser_tracker = None
        self.queue = None
        self.processor = None
        self.exporter = None
        
        logger.info("Service initialized")
    
    def SvcStop(self):
        """Service stop handler"""
        logger.info("Service stop requested")
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)
        
        self.running = False
        
        # Stop components
        if hasattr(self, 'processor') and self.processor:
            self.processor.stop()
        
        if hasattr(self, 'exporter') and self.exporter:
            self.exporter.stop()
        
        logger.info("Service stopped")
    
    def SvcDoRun(self):
        """Service main entry point"""
        logger.info("Service starting")
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )
        
        try:
            self.main()
        except Exception as e:
            logger.error(f"Service failed: {e}", exc_info=True)
            self.SvcStop()
    
    def main(self):
        """Main service logic"""
        logger.info("Initializing components...")
        
        # Initialize components
        self.app_tracker = AppTracker()
        self.browser_tracker = BrowserTracker()
        self.queue = PersistentQueue()
        self.processor = ProcessorWorker()
        self.exporter = CSVExporter()
        
        # Start processor worker (reads from queue -> SQL Server)
        self.processor.start()
        logger.info("Processor worker started")
        
        # Start exporter worker (exports to CSV periodically)
        self.exporter.start()
        logger.info("CSV exporter started")
        
        # Service loop - track events
        self.running = True
        last_browser_scan = time.time()
        
        logger.info("Service entering main tracking loop")
        
        while self.running:
            try:
                current_time = time.time()
                
                # Track active application
                app_event = self.app_tracker.capture_event()
                if app_event:
                    self.queue.enqueue(app_event)
                    logger.debug(f"Queued app event: {app_event['app_name']}")
                
                # Track browser activity periodically
                if current_time - last_browser_scan >= BROWSER_SCAN_INTERVAL:
                    try:
                        browser_events = self.browser_tracker.capture_events()
                        if browser_events:
                            self.queue.enqueue_bulk(browser_events)
                            logger.debug(f"Queued {len(browser_events)} browser events")
                    except Exception as e:
                        logger.error(f"Browser tracking error: {e}")
                    
                    last_browser_scan = current_time
                
                # Check for stop event
                if win32event.WaitForSingleObject(self.hWaitStop, 5000) == win32event.WAIT_OBJECT_0:
                    logger.info("Stop event received")
                    break
                
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(5)  # Error backoff
        
        logger.info("Service main loop exited")
    
    @staticmethod
    def install_service():
        """Static method to install the service"""
        logger.info("Installing service...")
        win32serviceutil.InstallService(
            None,
            SERVICE_NAME,
            SERVICE_DISPLAY_NAME,
            startType=win32service.SERVICE_AUTO_START,
            exeArgs="",
            description=SERVICE_DESCRIPTION
        )
        logger.info("Service installed successfully")
    
    @staticmethod
    def remove_service():
        """Static method to remove the service"""
        logger.info("Removing service...")
        win32serviceutil.RemoveService(SERVICE_NAME)
        logger.info("Service removed successfully")


# Standalone service manager class for command-line operations
class ServiceManager:
    """
    Helper class for managing the Windows Service
    Provides install/start/stop/remove operations
    """
    
    @staticmethod
    def install():
        """Install the Windows Service"""
        try:
            UsageTrackerService.install_service()
            print(f"Service '{SERVICE_NAME}' installed successfully")
            return True
        except Exception as e:
            print(f"Failed to install service: {e}")
            return False
    
    @staticmethod
    def remove():
        """Remove the Windows Service"""
        try:
            UsageTrackerService.remove_service()
            print(f"Service '{SERVICE_NAME}' removed successfully")
            return True
        except Exception as e:
            print(f"Failed to remove service: {e}")
            return False
    
    @staticmethod
    def start():
        """Start the service"""
        try:
            win32serviceutil.StartService(SERVICE_NAME)
            print(f"Service '{SERVICE_NAME}' started")
            return True
        except Exception as e:
            print(f"Failed to start service: {e}")
            return False
    
    @staticmethod
    def stop():
        """Stop the service"""
        try:
            win32serviceutil.StopService(SERVICE_NAME)
            print(f"Service '{SERVICE_NAME}' stopped")
            return True
        except Exception as e:
            print(f"Failed to stop service: {e}")
            return False
    
    @staticmethod
    def status():
        """Get service status"""
        try:
            status = win32serviceutil.QueryServiceStatus(SERVICE_NAME)
            status_map = {
                win32service.SERVICE_STOPPED: 'STOPPED',
                win32service.SERVICE_START_PENDING: 'START PENDING',
                win32service.SERVICE_STOP_PENDING: 'STOP PENDING',
                win32service.SERVICE_RUNNING: 'RUNNING',
                win32service.SERVICE_CONTINUE_PENDING: 'CONTINUE PENDING',
                win32service.SERVICE_PAUSE_PENDING: 'PAUSE PENDING',
                win32service.SERVICE_PAUSED: 'PAUSED'
            }
            print(f"Service status: {status_map.get(status[1], 'UNKNOWN')}")
            return status[1]
        except Exception as e:
            print(f"Service not found or error: {e}")
            return None


if __name__ == "__main__":
    # Handle command line args for service operations
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == 'install':
            ServiceManager.install()
        elif command == 'remove':
            ServiceManager.remove()
        elif command == 'start':
            ServiceManager.start()
        elif command == 'stop':
            ServiceManager.stop()
        elif command == 'status':
            ServiceManager.status()
        else:
            print("Usage: python windows_service.py [install|remove|start|stop|status]")
    else:
        # Run as service
        win32serviceutil.HandleCommandLine(UsageTrackerService)

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
import json
from typing import Optional

from app.config import SERVICE_DESCRIPTION, SERVICE_DISPLAY_NAME, SERVICE_NAME
from app.exporter.csv_exporter import CSVExporter
from app.queue.queue_db import PersistentQueue
from app.processor.worker import ProcessorWorker
from app.db.sqlserver import SQLServerDB
from app.health import HealthServer

logger = logging.getLogger(__name__)


class UsageTrackerService(win32serviceutil.ServiceFramework):
    """
    Windows Service for Personal Usage Tracker V3
    Manages queue processing and export; receives events from user-session agent via IPC.
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
        self.processor_thread = None
        
        # Components
        self.db = None
        self.queue = None
        self.processor = None
        self.exporter = None
        self.health_server = None
        self.ipc_server = None
        self.ipc_thread = None
        
        logger.info("Service initialized")
    
    def _start_ipc_server(self):
        """Start TCP socket server to receive events from user-session agent."""
        import socket
        import threading
        
        self.ipc_server = None
        self.ipc_thread = None
        
        def client_handler(conn, addr):
            """Handle incoming agent connection."""
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
                            # Validate and enqueue
                            from app.validation import EventValidator
                            if event.get('type') == 'app':
                                validated = EventValidator.validate_app_event(event)
                            elif event.get('type') == 'web':
                                validated = EventValidator.validate_web_event(event)
                            else:
                                validated = None
                            
                            if validated:
                                queue_id = self.queue.enqueue(validated)
                                logger.debug(f"Queued event from agent ID={queue_id} type={validated.get('type')}")
                            else:
                                logger.warning(f"Invalid event from agent: {event}")
                        except json.JSONDecodeError:
                            logger.error(f"Invalid JSON from agent: {line}")
                conn.close()
                logger.info(f"Agent disconnected from {addr}")
            except Exception as e:
                logger.error(f"Client handler error: {e}")
        
        def server_loop():
            """Server listening loop."""
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
                        client_thread = threading.Thread(target=client_handler, args=(conn, addr), daemon=True)
                        client_thread.start()
                    except socket.timeout:
                        continue
            except Exception as e:
                logger.error(f"IPC server failed: {e}")
            finally:
                self.ipc_server.close()
        
        self.ipc_thread = threading.Thread(target=server_loop, daemon=True)
        self.ipc_thread.start()
    
    def SvcStop(self):
        """Service stop handler"""
        logger.info("Service stop requested")
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)
        
        self.running = False
        
        # Stop components in reverse order
        if hasattr(self, 'processor') and self.processor:
            self.processor.stop()
        
        if hasattr(self, 'exporter') and self.exporter:
            self.exporter.stop()
        
        if hasattr(self, 'health_server') and self.health_server:
            self.health_server.stop()
        
        if hasattr(self, 'ipc_server') and self.ipc_server:
            try:
                self.ipc_server.close()
            except:
                pass
        
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
         logger.info("Initializing Personal Usage Tracker Service...")
         
         # 1. Test DB connection and schema (fail fast)
         logger.info("Testing SQL Server connection...")
         self.db = SQLServerDB()
         if not self.db.test_connection():
             logger.critical("Database unavailable or schema invalid — service cannot start")
             raise RuntimeError("Database connection/schema validation failed")
         logger.info("Database OK")
         
         # 2. Initialize components
         self.queue = PersistentQueue()
         logger.info("Persistent queue initialized")
         
         self.processor = ProcessorWorker()
         self.processor.start()
         logger.info("Processor worker started")
         
         self.exporter = CSVExporter()
         self.exporter.start()
         logger.info("CSV exporter started")
         
         self.health_server = HealthServer()
         self.health_server.start()
         logger.info("Health server started")
         
         # 3. Start IPC server to receive events from user-session agent
         self._start_ipc_server()
         logger.info("IPC server started — waiting for agent connections")
         
         # 4. Service monitoring loop
         self.running = True
         logger.info("Service entering main monitoring loop")
         
         while self.running:
             try:
                 if win32event.WaitForSingleObject(self.hWaitStop, 5000) == win32event.WAIT_OBJECT_0:
                     logger.info("Stop event received")
                     break
                 
                 queue_size = self.queue.get_size()
                 if queue_size > 100000:
                     logger.warning(f"High queue backpressure: {queue_size} events")
                 
             except Exception as e:
                 logger.error(f"Error in main loop: {e}", exc_info=True)
                 time.sleep(5)
         
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

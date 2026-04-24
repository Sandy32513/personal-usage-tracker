"""
Health Check Module for Personal Usage Tracker V3
Provides HTTP health endpoint for monitoring
"""

import json
import socket
import base64
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from typing import Optional
import logging

from app.queue.queue_db import PersistentQueue
from app.config import MAX_QUEUE_SIZE

logger = logging.getLogger(__name__)

# Health endpoint security
# Require API key by default - set via environment variable
HEALTH_API_KEY = os.getenv('HEALTH_API_KEY', None)
# If not set, generate a warning but allow localhost-only access
if HEALTH_API_KEY is None:
    logger.warning("HEALTH_API_KEY not set - health endpoint accessible without authentication from localhost. "
                   "Set HEALTH_API_KEY environment variable to enable authentication.")

class HealthHandler(BaseHTTPRequestHandler):
    """HTTP handler for health checks with optional auth"""
    
    def do_GET(self):
        # Check auth if enabled
        if HEALTH_API_KEY and not self._check_auth():
            return

        if self.path == '/health' or self.path == '/metrics':
            try:
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()

                health_data = get_health_data()
                self.wfile.write(json.dumps(health_data, indent=2).encode())
            except Exception as e:
                logger.error(f"Health check failed: {e}")
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                # Don't leak exception details - return generic error
                error_resp = json.dumps({"status": "error", "message": "Internal server error"})
                self.wfile.write(error_resp.encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def _check_auth(self) -> bool:
        """Verify API key"""
        if HEALTH_API_KEY is None:
            return True
        
        auth_header = self.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            return auth_header[7:] == HEALTH_API_KEY
        return False
    
    def log_message(self, format, *args):
        pass


class HealthServer:
    """HTTP health check server"""
    
    def __init__(self, host: str = 'localhost', port: int = 8765):
        self.host = host
        self.port = port
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[Thread] = None
    
    def start(self):
        """Start the health server"""
        try:
            self.server = HTTPServer((self.host, self.port), HealthHandler)
            self.thread = Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            logger.info(f"Health server started at http://{self.host}:{self.port}/health")
            return True
        except Exception as e:
            logger.error(f"Failed to start health server: {e}")
            return False
    
    def stop(self):
        """Stop the health server"""
        if self.server:
            self.server.shutdown()
            logger.info("Health server stopped")


def get_health_data() -> dict:
    """Get health data from all components"""
    data = {
        'service': 'PersonalUsageTrackerV3',
        'status': 'healthy',
        'timestamp': None,
    }
    
    try:
        from datetime import datetime
        data['timestamp'] = datetime.now().isoformat()
    except:
        pass
    
    # Queue health with backpressure detection
    try:
        queue = PersistentQueue()
        queue_size = queue.get_size()
        
        # Check backpressure
        bp = queue.check_backpressure() if hasattr(queue, 'check_backpressure') else {'backpressure_needed': False}
        warnings = bp.get('warnings', [])
        
        data['queue'] = {
            'size': queue_size,
            'max_size': MAX_QUEUE_SIZE,
            'status': 'ok' if queue_size < 100000 else ('warning' if queue_size < MAX_QUEUE_SIZE else 'critical'),
            'backpressure': bp.get('backpressure_needed', False),
            'warnings': warnings,
        }
        
        # Add alerts for critical conditions
        if warnings:
            data['alerts'] = data.get('alerts', []) + warnings
            
    except Exception as e:
        data['queue'] = {'status': 'error', 'error': str(e)}
    
    data['processor'] = {
        'status': 'unknown',
        'detail': 'health endpoint is not attached to a live worker instance',
    }
    
    # Network check
    localhost_ip = socket.gethostbyname('localhost')
    data['network'] = {
        'localhost_resolvable': bool(localhost_ip),
        'resolved_address': localhost_ip,
    }
    
    # System resources (memory + CPU)
    try:
        import psutil
        mem = psutil.virtual_memory()
        data['system'] = {
            'memory': {
                'total_mb': round(mem.total / 1024 / 1024, 0),
                'available_mb': round(mem.available / 1024 / 1024, 0),
                'percent_used': mem.percent,
            },
            'cpu': {
                'percent': psutil.cpu_percent(interval=0.1),
            },
        }
        # Warn on high usage
        if mem.percent > 85:
            data['warnings'] = data.get('warnings', [])
            data['warnings'].append(f"High memory usage: {mem.percent}%")
    except ImportError:
        pass

    return data


# Standalone health check for testing
if __name__ == '__main__':
    print("Health Check Server Test")
    print("-" * 40)
    
    server = HealthServer()
    if server.start():
        print(f"Health server running at http://localhost:{server.port}/health")
        print("Press Ctrl+C to stop")
        
        import time
        try:
            time.sleep(5)
        except KeyboardInterrupt:
            pass
        
        server.stop()
        print("Health server stopped")

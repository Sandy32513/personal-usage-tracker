"""
Personal Usage Tracker — User Agent
Runs in user session, captures app/browser activity, sends to service via IPC.
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Add parent directory to path for imports
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.tracker.app_tracker import AppTracker
from app.tracker.browser_tracker import BrowserTracker
from app.validation import EventValidator

logger = logging.getLogger(__name__)


class UsageTrackerAgent:
    """Lightweight agent that runs in user session and forwards events to service."""
    
    def __init__(self, service_host: str = 'localhost', service_port: int = 8766):
        self.service_host = service_host
        self.service_port = service_port
        self.app_tracker = AppTracker()
        self.browser_tracker = BrowserTracker()
        self.validator = EventValidator()
        self.running = False
        self.last_browser_scan = time.time()
        
    async def send_event_to_service(self, event: dict) -> bool:
        """Send event to service via TCP socket."""
        try:
            # Use simple TCP socket to send JSON line
            import socket
            payload = json.dumps(event) + '\n'
            with socket.create_connection((self.service_host, self.service_port), timeout=2) as sock:
                sock.sendall(payload.encode('utf-8'))
            return True
        except Exception as e:
            logger.error(f"Failed to send event to service: {e}")
            # Fallback: write to local queue file (will be picked up by service)
            return self._fallback_queue(event)
    
    def _fallback_queue(self, event: dict) -> bool:
        """Write event to shared queue file if service unreachable."""
        try:
            import json
            from app.config import BASE_DIR
            queue_dir = Path(BASE_DIR) / 'data'
            queue_dir.mkdir(parents=True, exist_ok=True)
            queue_file = queue_dir / 'agent_events.jsonl'
            with open(queue_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(event) + '\n')
            return True
        except Exception as e:
            logger.error(f"Fallback queue failed: {e}")
            return False
    
    def capture_and_forward(self):
        """Main capture loop."""
        logger.info("Agent starting capture loop...")
        
        while self.running:
            try:
                current_time = time.time()
                
                # 1. Capture active app
                app_event = self.app_tracker.capture_event()
                if app_event:
                    validated = self.validator.validate_app_event(app_event)
                    if validated:
                        asyncio.run(self.send_event_to_service(validated))
                        logger.debug(f"Sent app event: {validated.get('app_name')}")
                
                # 2. Capture browser history periodically
                if current_time - self.last_browser_scan >= 30:
                    try:
                        browser_events = self.browser_tracker.capture_events()
                        for bev in browser_events:
                            validated = self.validator.validate_web_event(bev)
                            if validated:
                                asyncio.run(self.send_event_to_service(validated))
                        logger.debug(f"Sent {len(browser_events)} browser events")
                    except Exception as e:
                        logger.error(f"Browser capture error: {e}")
                    self.last_browser_scan = current_time
                
                time.sleep(5)
                
            except Exception as e:
                logger.error(f"Agent loop error: {e}", exc_info=True)
                time.sleep(5)
    
    def start(self):
        """Start the agent."""
        self.running = True
        logger.info("UsageTracker Agent started")
        self.capture_and_forward()
    
    def stop(self):
        """Stop the agent."""
        self.running = False
        logger.info("Agent stopped")


def main():
    """Entry point for user-session agent."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Personal Usage Tracker - User Agent")
    parser.add_argument('--host', default='localhost', help='Service host')
    parser.add_argument('--port', type=int, default=8766, help='Service port')
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )
    
    agent = UsageTrackerAgent(service_host=args.host, service_port=args.port)
    
    try:
        agent.start()
    except KeyboardInterrupt:
        agent.stop()


if __name__ == '__main__':
    main()

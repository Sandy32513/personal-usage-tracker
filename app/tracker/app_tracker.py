"""
Application Tracker Module
Tracks active window and application usage on Windows
Uses psutil and win32gui to detect foreground window and process info
"""

import psutil
import win32gui
import win32process
import time
import json
from datetime import datetime
from typing import Optional, Dict, Any
from app.config import LOG_LEVEL, get_timestamp
import logging

logger = logging.getLogger(__name__)


class AppTracker:
    """Tracks active application usage on Windows"""
    
    def __init__(self):
        self.last_window_title = ""
        self.last_process_name = ""
        self.last_monotonic = time.monotonic()
        self.last_timestamp = time.time()
        
    def get_foreground_window_info(self) -> Optional[Dict[str, Any]]:
        """
        Get information about the currently active foreground window
        Returns dict with app_name, window_title, process_id, timestamp
        """
        try:
            # Get foreground window handle
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return None
            
            # Get window title
            window_title = win32gui.GetWindowText(hwnd)
            
            # Get process ID
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            
            # Get process name
            try:
                process = psutil.Process(pid)
                app_name = process.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                app_name = "Unknown"
            
            # Build payload
            timestamp = get_timestamp()
            
            return {
                'type': 'app',
                'app_name': app_name,
                'window_title': window_title,
                'process_id': pid,
                'timestamp': timestamp
            }
            
        except Exception as e:
            logger.error(f"Error getting foreground window: {e}")
            return None
    
    def capture_event(self) -> Optional[Dict[str, Any]]:
        """
        Capture a single application usage event
        Returns None if no change detected or error occurred
        Uses monotonic clock to detect system sleep/hibernate
        """
        current_mono = time.monotonic()
        current_time = time.time()
        
        # Detect if system was asleep (time jump > 2x interval)
        elapsed_mono = current_mono - self.last_monotonic
        elapsed_wall = current_time - self.last_timestamp
        
        # If wall time elapsed is much larger than monotonic, system likely slept
        if elapsed_wall > elapsed_mono * 2 and elapsed_wall > 60:
            logger.warning(f"System sleep detected (wall:{elapsed_wall:.0f}s vs mono:{elapsed_mono:.0f}s). Skipping duplicate detection.")
            # Reset last timestamp to avoid artificial gap
            self.last_timestamp = current_time
            self.last_monotonic = current_mono
            # Return None but don't deduplicate — treat as new session start
            info = self.get_foreground_window_info()
            if info:
                # Force update last_* to current
                self.last_window_title = info['window_title']
                self.last_process_name = info['app_name']
                return info
            return None
        
        info = self.get_foreground_window_info()
        if not info:
            return None
        
        # Deduplication: only capture if window or app changed
        current_window = info['window_title']
        current_app = info['app_name']
        
        if (current_window == self.last_window_title and 
            current_app == self.last_process_name):
            return None  # No change
        
        # Update last seen
        self.last_window_title = current_window
        self.last_process_name = current_app
        self.last_monotonic = current_mono
        self.last_timestamp = current_time
        
        return info
    
    def get_current_state(self) -> Dict[str, Any]:
        """Get current active window state without deduplication"""
        info = self.get_foreground_window_info()
        return info if info else {
            'type': 'app',
            'app_name': 'Unknown',
            'window_title': '',
            'process_id': 0,
            'timestamp': datetime.now().isoformat()
        }


# Standalone test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    tracker = AppTracker()
    
    print("Testing AppTracker for 10 seconds...")
    print("-" * 50)
    
    for i in range(10):
        event = tracker.capture_event()
        if event:
            print(f"[{event['timestamp']}] {event['app_name']} - {event['window_title']}")
        time.sleep(1)
    
    print("-" * 50)
    print("Test complete.")
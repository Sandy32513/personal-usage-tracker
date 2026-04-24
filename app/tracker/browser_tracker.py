"""
Browser Tracker Module
Tracks Chrome browser activity by reading history SQLite database
Safely copies DB before reading to avoid locks
Supports multiple user profiles and service account context
"""

import sqlite3
import shutil
import tempfile
import os
import time
import win32com.client
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from app.config import CHROME_HISTORY_PATH
import logging

logger = logging.getLogger(__name__)


def get_active_console_username() -> Optional[str]:
    """
    Get the username of the actively logged-in console user.
    Returns None if no user logged in.
    Works even when running as SYSTEM.
    """
    try:
        wmi = win32com.client.GetObject("winmgmts://")
        query = "SELECT UserName FROM Win32_ComputerSystem"
        result = wmi.ExecQuery(query)
        for cs in result:
            if cs.UserName:
                # Returns DOMAIN\Username
                return cs.UserName.split('\\')[-1].lower()
    except Exception as e:
        logger.debug(f"Could not detect active user via WMI: {e}")
    
    return None


def find_chrome_history_path() -> Optional[str]:
    """
    Find Chrome History file for active user.
    Checks all profiles (Default, Profile 1, Profile 2, ...)
    Returns path to most recently modified History file.
    """
    # Allow manual override via environment variable (for testing/custom installs)
    override_path = os.getenv('CHROME_HISTORY_PATH')
    if override_path and os.path.exists(override_path):
        logger.debug(f"Using Chrome history from env override: {override_path}")
        return override_path
    
    active_user = get_active_console_username()
    
    if active_user:
        # Try active user first
        base_path = fr'C:\Users\{active_user}\AppData\Local\Google\Chrome\User Data'
        if os.path.exists(base_path):
            # Check all profiles
            profiles = ['Default'] + [f'Profile {i}' for i in range(1, 10)]
            latest_mtime = 0
            latest_path = None
            
            for profile in profiles:
                path = os.path.join(base_path, profile, 'History')
                if os.path.exists(path):
                    mtime = os.path.getmtime(path)
                    if mtime > latest_mtime:
                        latest_mtime = mtime
                        latest_path = path
            
            if latest_path:
                logger.debug(f"Found Chrome history at: {latest_path}")
                return latest_path
    
    # Fallback to hardcoded path (for non-service/debug mode)
    default_path = CHROME_HISTORY_PATH.format(os.getenv('USERNAME', 'Default'))
    if os.path.exists(default_path):
        return default_path
    
    logger.warning("Chrome history file not found in any known location")
    return None


class BrowserTracker:
    """Tracks Chrome browsing history"""
    
    def __init__(self, history_path: str = None):
        # Resolve path if not provided
        self.history_path = history_path or find_chrome_history_path()
        self.last_check_time = datetime.now()
        
        if not self.history_path:
            logger.warning("BrowserTracker: Chrome history path not found. Web tracking will be disabled.")
        
    def _get_chrome_history_copy(self) -> Optional[str]:
        """
        Create a safe temporary copy of Chrome's History SQLite DB
        Returns path to temp copy or None if failed
        Implements retry for locked files
        """
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                if not os.path.exists(self.history_path):
                    logger.warning(f"Chrome history DB not found at: {self.history_path}")
                    return None
                
                # Create temp copy to avoid locking Chrome's DB
                temp_dir = tempfile.gettempdir()
                temp_copy = os.path.join(temp_dir, f'chrome_history_{os.getpid()}_{int(time.time())}.db')
                
                shutil.copy2(self.history_path, temp_copy)
                logger.debug(f"Chrome history copied to: {temp_copy}")
                return temp_copy
                
            except PermissionError as e:
                logger.warning(f"Permission denied copying Chrome history (attempt {attempt+1}/{max_attempts}): {e}")
                if attempt < max_attempts - 1:
                    time.sleep(1 * (attempt + 1))  # Exponential-ish backoff
                else:
                    logger.error("Chrome history DB locked after retries. Chrome may be running.")
                    return None
            except Exception as e:
                logger.error(f"Error copying Chrome history: {e}")
                return None
    
    def _convert_chrome_time(self, chrome_time: int) -> datetime:
        """
        Convert Chrome's unique time format to Python datetime
        Chrome time: microseconds since Jan 1, 1601 (UTC)
        """
        if chrome_time == 0:
            return datetime.now()
        
        # Chrome epoch starts at 1601-01-01
        chrome_epoch = datetime(1601, 1, 1)
        try:
            microseconds = chrome_time
            return chrome_epoch + timedelta(microseconds=microseconds)
        except Exception:
            return datetime.now()
    
    def extract_recent_history(self, minutes: int = 10, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        Extract recent browser history from Chrome
        Returns list of visit records with url, title, timestamp
        """
        results = []
        temp_copy = None
        
        try:
            # Get safe copy of DB
            temp_copy = self._get_chrome_history_copy()
            if not temp_copy:
                return results
            
            # Connect to copy
            conn = sqlite3.connect(temp_copy)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Calculate cutoff time
            cutoff_time = since if since is not None else datetime.now() - timedelta(minutes=minutes)
            chrome_cutoff = int((cutoff_time - datetime(1601, 1, 1)).total_seconds() * 1000000)
            
            # Query recent visits (no LIMIT to avoid data loss)
            query = """
                SELECT 
                    u.url,
                    u.title,
                    v.visit_time,
                    v.visit_duration
                FROM visits v
                JOIN urls u ON v.url = u.id
                WHERE v.visit_time > ?
                ORDER BY v.visit_time ASC
            """
            
            cursor.execute(query, (chrome_cutoff,))
            rows = cursor.fetchall()
            
            for row in rows:
                visit_time = self._convert_chrome_time(row['visit_time'])
                
                # Skip if title is empty (often indicates background requests)
                if not row['title'] or row['title'].strip() == '':
                    continue
                
                results.append({
                    'type': 'web',
                    'url': row['url'],
                    'title': row['title'],
                    'timestamp': visit_time.isoformat(),
                    'duration_seconds': row['visit_duration'] or 0
                })
            
            conn.close()
            logger.info(f"Extracted {len(results)} browser history records")
            
        except sqlite3.Error as e:
            logger.error(f"SQLite error reading Chrome history: {e}")
        except Exception as e:
            logger.error(f"Error extracting browser history: {e}")
        finally:
            # Clean up temp file
            if temp_copy and os.path.exists(temp_copy):
                try:
                    os.remove(temp_copy)
                except:
                    pass
        
        return results
    
    def capture_events(self) -> List[Dict[str, Any]]:
        """
        Capture all browser events since last check
        Returns list of event dicts ready for queue insertion
        """
        events = self.extract_recent_history(since=self.last_check_time)
        if events:
            self.last_check_time = max(datetime.fromisoformat(event['timestamp']) for event in events)
        else:
            self.last_check_time = datetime.now()
        return events


# Standalone test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    tracker = BrowserTracker()
    
    print("Testing BrowserTracker...")
    print("-" * 50)
    
    events = tracker.capture_events()
    for event in events[:10]:  # Show up to 10
        print(f"[{event['timestamp']}] {event['title'][:50]}...")
        print(f"  URL: {event['url'][:80]}...")
    
    print("-" * 50)
    print(f"Found {len(events)} recent browser visits.")

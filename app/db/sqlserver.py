"""
SQL Server Database Module
Handles all SQL Server connections and data insertion
Single source of truth for usage data
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import pyodbc

from app.config import DATABASE_CONNECTION_TIMEOUT, EVENT_TYPE, get_connection_string

# Enable connection pooling
pyodbc.pooling = True

logger = logging.getLogger(__name__)


class SQLServerDB:
    """
    SQL Server database handler for usage tracking
    Manages connections with retry logic and proper transaction handling
    """
    
    def __init__(self, test_on_init: bool = False):
        self.conn_str = get_connection_string()
        self.timeout = DATABASE_CONNECTION_TIMEOUT
        if test_on_init:
            self._test_connection()
    
    def test_connection(self) -> bool:
        """Test initial connection to SQL Server and verify schema availability"""
        try:
            conn = pyodbc.connect(self.conn_str, autocommit=False, timeout=self.timeout)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            
            # Also verify critical table exists (C4 fix)
            cursor.execute("""
                SELECT COUNT(*) FROM sys.tables 
                WHERE name = 'events'
            """)
            if cursor.fetchone()[0] == 0:
                logger.critical("Database schema not initialized: 'events' table missing. "
                               "Run installer/schema.sql to create schema.")
                cursor.close()
                conn.close()
                return False
            
            cursor.close()
            conn.close()
            logger.info("Successfully connected to SQL Server (schema validated)")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to SQL Server: {e}")
            logger.warning("Ensure SQL Server is running and credentials are correct")
            return False
    
    def _get_connection(self) -> Optional[pyodbc.Connection]:
        """Get a fresh database connection"""
        try:
            conn = pyodbc.connect(self.conn_str, autocommit=False, timeout=self.timeout)
            return conn
        except Exception as e:
            logger.error(f"Failed to create DB connection: {e}")
            return None
    
    def insert_app_event(self, 
                        app_name: str, 
                        window_title: str, 
                        timestamp: str,
                        duration_seconds: int = 0) -> Optional[int]:
        """
        Insert application usage event into SQL Server
        Returns inserted row ID or None on failure
        """
        conn: Optional[pyodbc.Connection] = None
        try:
            conn = self._get_connection()
            if not conn:
                return None
            
            cursor = conn.cursor()
            
            query = '''
                INSERT INTO events 
                (type, app_name, window_title, url, title, timestamp, duration_seconds)
                OUTPUT INSERTED.id
                VALUES (?, ?, ?, ?, ?, ?, ?)
            '''
            
            cursor.execute(query, (
                EVENT_TYPE['APP'],
                app_name,
                window_title,
                None,  # url
                None,  # title
                timestamp,
                duration_seconds
            ))
            event_id = cursor.fetchone()[0]
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.debug(f"Inserted app event ID: {event_id} for {app_name}")
            return event_id
            
        except Exception as e:
            logger.error(f"Failed to insert app event: {e}")
            if conn:
                try:
                    conn.rollback()
                    conn.close()
                except:
                    pass
            return None
    
    def insert_web_event(self,
                        url: str,
                        title: str,
                        visit_time: str,
                        duration_seconds: int = 0) -> Optional[int]:
        """
        Insert browser visit event into SQL Server
        Returns inserted row ID or None on failure
        """
        conn: Optional[pyodbc.Connection] = None
        try:
            conn = self._get_connection()
            if not conn:
                return None
            
            cursor = conn.cursor()
            
            query = '''
                INSERT INTO events 
                (type, app_name, window_title, url, title, timestamp, duration_seconds)
                OUTPUT INSERTED.id
                VALUES (?, ?, ?, ?, ?, ?, ?)
            '''
            
            cursor.execute(query, (
                EVENT_TYPE['WEB'],
                'Chrome',
                None,
                url,
                title,
                visit_time,
                duration_seconds
            ))
            event_id = cursor.fetchone()[0]
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.debug(f"Inserted web event ID: {event_id} for {title[:50]}")
            return event_id
            
        except Exception as e:
            logger.error(f"Failed to insert web event: {e}")
            if conn:
                try:
                    conn.rollback()
                    conn.close()
                except:
                    pass
            return None
    
    def insert_event_from_queue(self, payload: Dict[str, Any]) -> bool:
        """
        Insert event from queue payload
        Returns True on success, False on failure
        """
        try:
            event_type = payload.get('type')
            
            if event_type == EVENT_TYPE['APP']:
                result = self.insert_app_event(
                    app_name=payload.get('app_name', 'Unknown'),
                    window_title=payload.get('window_title', ''),
                    timestamp=payload.get('timestamp', datetime.now().isoformat()),
                    duration_seconds=payload.get('duration_seconds', 0)
                )
                return result is not None
                
            elif event_type == EVENT_TYPE['WEB']:
                event_timestamp = payload.get('timestamp', payload.get('visit_time', datetime.now().isoformat()))
                event_duration = payload.get('duration_seconds', payload.get('visit_duration', 0))
                result = self.insert_web_event(
                    url=payload.get('url', ''),
                    title=payload.get('title', ''),
                    visit_time=event_timestamp,
                    duration_seconds=event_duration
                )
                return result is not None
            
            else:
                logger.error(f"Unknown event type: {event_type}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to insert event: {e}")
            return False

    def insert_batch_from_queue(self, payloads: List[Dict[str, Any]]) -> Tuple[List[int], List[int]]:
        """
        Batch insert multiple events from queue in a single transaction.
        Uses connection reuse for performance.
        
        Args:
            payloads: List of event payload dictionaries
            
        Returns:
            (success_ids, failed_queue_ids) — lists of queue IDs (simulated)
            Note: Since batch doesn't return individual IDs easily, we return
            full success/failure at transaction level for now.
        """
        if not payloads:
            return [], []
        
        conn = None
        try:
            conn = self._get_connection()
            if not conn:
                return [], [i for i in range(len(payloads))]
            
            cursor = conn.cursor()
            
            # Build batch parameters for app and web events separately
            app_params = []
            web_params = []
            
            for payload in payloads:
                event_type = payload.get('type')
                if event_type == EVENT_TYPE['APP']:
                    app_params.append((
                        EVENT_TYPE['APP'],
                        payload.get('app_name', 'Unknown'),
                        payload.get('window_title', ''),
                        None,  # url
                        None,  # title
                        payload.get('timestamp', datetime.now().isoformat()),
                        payload.get('duration_seconds', 0)
                    ))
                elif event_type == EVENT_TYPE['WEB']:
                    ts = payload.get('timestamp', payload.get('visit_time', datetime.now().isoformat()))
                    dur = payload.get('duration_seconds', payload.get('visit_duration', 0))
                    web_params.append((
                        EVENT_TYPE['WEB'],
                        'Chrome',
                        None,  # window_title
                        payload.get('url', ''),
                        payload.get('title', ''),
                        ts,
                        dur
                    ))
                else:
                    logger.warning(f"Skipping unknown event type: {event_type}")
            
            success_count = 0
            
            # Insert app events in batch
            if app_params:
                app_query = '''
                    INSERT INTO events 
                    (type, app_name, window_title, url, title, timestamp, duration_seconds)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                '''
                cursor.executemany(app_query, app_params)
                success_count += len(app_params)
            
            # Insert web events in batch
            if web_params:
                web_query = '''
                    INSERT INTO events 
                    (type, app_name, window_title, url, title, timestamp, duration_seconds)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                '''
                cursor.executemany(web_query, web_params)
                success_count += len(web_params)
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info(f"Batch inserted {success_count} events (app={len(app_params)}, web={len(web_params)})")
            return list(range(success_count)), []  # All succeeded
            
        except Exception as e:
            logger.error(f"Batch insert failed: {e}")
            if conn:
                try:
                    conn.rollback()
                    conn.close()
                except:
                    pass
            return [], list(range(len(payloads)))  # All failed
            
            else:
                logger.error(f"Unknown event type: {event_type}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to insert event from queue: {e}")
            return False
    
    def test_connection(self) -> bool:
        """Test database connectivity"""
        try:
            conn = self._get_connection()
            if not conn:
                return False
            
            cursor = conn.cursor()
            cursor.execute("SELECT GETDATE()")
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            
            logger.info(f"Database test successful. Server time: {row[0]}")
            return True
            
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics"""
        try:
            conn = self._get_connection()
            if not conn:
                return {}
            
            cursor = conn.cursor()
            
            # Total events
            cursor.execute("SELECT COUNT(*) FROM events")
            total = cursor.fetchone()[0]
            
            # Events by type
            cursor.execute("SELECT type, COUNT(*) FROM events GROUP BY type")
            type_counts = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Date range
            cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM events")
            min_date, max_date = cursor.fetchone()
            
            cursor.close()
            conn.close()
            
            return {
                'total_events': total,
                'app_events': type_counts.get(EVENT_TYPE['APP'], 0),
                'web_events': type_counts.get(EVENT_TYPE['WEB'], 0),
                'oldest_record': min_date,
                'newest_record': max_date
            }
            
        except Exception as e:
            logger.error(f"Failed to get DB stats: {e}")
            return {}


# Standalone test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("Testing SQLServerDB...")
    print("-" * 50)
    
    db = SQLServerDB()
    
    # Test connection
    if db.test_connection():
        print("✓ Connection successful")
    else:
        print("✗ Connection failed")
    
    # Get stats
    stats = db.get_stats()
    print(f"\nCurrent stats: {stats}")
    
    print("-" * 50)
    print("Test complete.")

"""
CSV Export Module
Exports usage data from SQL Server to CSV files periodically
Runs in background thread, separate from main tracking

Note: Uses built-in csv module instead of pandas to keep executable small
"""

import csv
import os
import logging
import time
import threading
from datetime import date, datetime
from typing import Dict

from app.config import APP_USAGE_CSV, DATA_RETENTION_DAYS, EVENT_TYPE, EXPORT_DIR, EXPORT_INTERVAL, WEB_USAGE_CSV
from app.db.sqlserver import SQLServerDB

logger = logging.getLogger(__name__)


class CSVExporter:
    """
    Periodically exports SQL Server data to CSV files
    Runs in background thread, supports manual trigger too
    Files are dated: app_usage_YYYY-MM-DD.csv, web_usage_YYYY-MM-DD.csv
    """
    
    def __init__(self):
        self.db = SQLServerDB()
        self.running = False
        self.thread = None
        self.last_export = None
        self.stop_event = threading.Event()
    
    def _get_dated_filename(self, base_name: str) -> str:
        """Generate filename with current date"""
        today = date.today().isoformat()
        name_without_ext = base_name.rsplit('.', 1)[0]  # Remove .csv if present
        return os.path.join(EXPORT_DIR, f"{name_without_ext}_{today}.csv")
    
    def start(self):
        """Start the periodic export in background thread"""
        if self.running:
            logger.warning("Exporter already running")
            return
        
        self.running = True
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info(f"CSV Exporter started (interval: {EXPORT_INTERVAL}s)")
    
    def stop(self):
        """Stop the exporter thread"""
        self.running = False
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)
        logger.info("CSV Exporter stopped")
    
    def _run(self):
        """Main export loop"""
        logger.info("Exporter loop starting")
        
        while self.running:
            try:
                # Perform export
                self.export_all()
                self.last_export = datetime.now()
                
                # Wait for next interval
                if self.stop_event.wait(EXPORT_INTERVAL):
                    break
                
            except Exception as e:
                logger.error(f"Exporter error: {e}", exc_info=True)
                if self.stop_event.wait(60):
                    break
    
    def export_all(self):
        """Export all data to CSV files"""
        logger.info("Starting CSV export...")
        
        try:
            # Export app usage
            app_success = self._export_app_usage()
            
            # Export web usage
            web_success = self._export_web_usage()
            
            if app_success and web_success:
                logger.info("CSV export completed successfully")
            else:
                logger.warning("CSV export partially completed")
                
        except Exception as e:
            logger.error(f"Export failed: {e}", exc_info=True)
    
    def _export_app_usage(self) -> bool:
        """Export application usage to CSV using built-in csv module"""
        try:
            conn = self.db._get_connection()
            if not conn:
                return False
            
            query = '''
                SELECT 
                    id,
                    app_name,
                    window_title,
                    timestamp,
                    duration_seconds
                FROM events
                WHERE type = ?
                AND timestamp > DATEADD(day, -?, GETDATE())
                ORDER BY timestamp DESC
            '''
            
            cursor = conn.cursor()
            cursor.execute(query, (EVENT_TYPE['APP'], DATA_RETENTION_DAYS))
            
            rows = cursor.fetchall()
            if not rows:
                logger.info("No app usage data to export")
                conn.close()
                return True
            
            # Ensure directory exists
            os.makedirs(EXPORT_DIR, exist_ok=True)
            
            # Generate date-stamped filename
            output_file = self._get_dated_filename(os.path.basename(APP_USAGE_CSV))
            gzip_file = output_file + '.gz'
            
            # Write to CSV with gzip compression
            import gzip
            with gzip.open(gzip_file, 'wt', newline='', encoding='utf-8-sig') as gz:
                writer = csv.writer(gz)
                # Header
                writer.writerow(['id', 'app_name', 'window_title', 'timestamp', 'duration_seconds'])
                # Data rows
                for row in rows:
                    writer.writerow(row)
            
            logger.info(f"Exported {len(rows)} app usage records to {gzip_file}")
            
            conn.close()
            return True
            
        except Exception as e:
            logger.error(f"Failed to export app usage: {e}")
            return False
    
    def _export_web_usage(self) -> bool:
        """Export web usage to CSV using built-in csv module"""
        try:
            conn = self.db._get_connection()
            if not conn:
                return False
            
            query = '''
                SELECT 
                    id,
                    app_name,
                    url,
                    title,
                    timestamp,
                    duration_seconds
                FROM events
                WHERE type = ?
                AND timestamp > DATEADD(day, -?, GETDATE())
                ORDER BY timestamp DESC
            '''
            
            cursor = conn.cursor()
            cursor.execute(query, (EVENT_TYPE['WEB'], DATA_RETENTION_DAYS))
            
            rows = cursor.fetchall()
            if not rows:
                logger.info("No web usage data to export")
                conn.close()
                return True
            
            # Ensure directory exists
            os.makedirs(EXPORT_DIR, exist_ok=True)
            
            # Generate date-stamped filename
            output_file = self._get_dated_filename(os.path.basename(WEB_USAGE_CSV))
            gzip_file = output_file + '.gz'
            
            # Write to CSV with gzip compression
            import gzip
            with gzip.open(gzip_file, 'wt', newline='', encoding='utf-8-sig') as gz:
                writer = csv.writer(gz)
                # Header
                writer.writerow(['id', 'app_name', 'url', 'title', 'timestamp', 'duration_seconds'])
                # Data rows
                for row in rows:
                    writer.writerow(row)
            
            conn.close()
            logger.info(f"Exported {len(rows)} web records to {gzip_file}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to export web usage: {e}")
            return False
    
    def export_manual(self) -> Dict[str, bool]:
        """
        Manually trigger export
        Returns dict with export results for app and web
        """
        logger.info("Manual export triggered")
        return {
            'app': self._export_app_usage(),
            'web': self._export_web_usage()
        }


# Standalone test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("Testing CSVExporter...")
    print("-" * 50)
    
    exporter = CSVExporter()
    
    # Test single export
    result = exporter.export_manual()
    print(f"Export result: {result}")
    
    # Check if files exist
    app_output = exporter._get_dated_filename(os.path.basename(APP_USAGE_CSV)) + '.gz'
    web_output = exporter._get_dated_filename(os.path.basename(WEB_USAGE_CSV)) + '.gz'
    print(f"\nApp CSV exists: {os.path.exists(app_output)}")
    print(f"Web CSV exists: {os.path.exists(web_output)}")
    
    print("-" * 50)
    print("Test complete.")

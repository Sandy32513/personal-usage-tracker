#!/usr/bin/env python3
"""
Standalone CSV Export Script
Runs a single export operation and exits.
Designed to be called by Windows Task Scheduler every 10 minutes.
"""

import sys
import os
import logging
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.config import LOG_LEVEL, LOG_FILE
from app.exporter.csv_exporter import CSVExporter
from app.db.sqlserver import SQLServerDB

# Setup logging
def setup_logging():
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    handlers = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.append(logging.FileHandler(LOG_FILE, encoding='utf-8'))
    except:
        pass
    logging.basicConfig(level=getattr(logging, LOG_LEVEL.upper(), logging.INFO), format=log_format, handlers=handlers)

logger = logging.getLogger(__name__)

def main():
    """Run a single CSV export"""
    setup_logging()
    
    logger.info("CSV Export task started")
    start_time = datetime.now()
    
    try:
        # Test DB connection
        db = SQLServerDB()
        if not db.test_connection():
            logger.error("Cannot connect to SQL Server. Aborting export.")
            sys.exit(1)
        
        # Run export
        exporter = CSVExporter()
        result = exporter.export_manual()
        
        if result['app'] and result['web']:
            logger.info("CSV export completed successfully")
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"Export took {duration:.2f} seconds")
            sys.exit(0)
        else:
            logger.warning("CSV export partially completed")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"CSV export failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
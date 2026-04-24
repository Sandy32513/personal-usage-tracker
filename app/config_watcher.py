"""
Config Hot-Reload Module
Watches config file for changes and reloads automatically
"""

import os
import time
import logging
from threading import Thread, Event
from typing import Optional, Callable, Dict, Any

logger = logging.getLogger(__name__)


class ConfigWatcher:
    """Watches config file for changes and triggers reload"""
    
    def __init__(self, config_path: str, reload_callback: Callable[[], None], 
                 poll_interval: float = 5.0):
        self.config_path = config_path
        self.reload_callback = reload_callback
        self.poll_interval = poll_interval
        self.last_modified: Optional[float] = None
        self.running = False
        self.thread: Optional[Thread] = None
        self.stop_event = Event()
    
    def start(self):
        """Start watching the config file"""
        if not os.path.exists(self.config_path):
            logger.warning(f"Config file not found: {self.config_path}")
            return False
        
        # Get initial modification time
        self.last_modified = os.path.getmtime(self.config_path)
        self.running = True
        self.stop_event.clear()
        
        self.thread = Thread(target=self._watch_loop, daemon=True)
        self.thread.start()
        logger.info(f"Config watcher started for {self.config_path}")
        return True
    
    def stop(self):
        """Stop watching the config file"""
        self.running = False
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        logger.info("Config watcher stopped")
    
    def _watch_loop(self):
        """Main watch loop"""
        while self.running and not self.stop_event.is_set():
            try:
                if os.path.exists(self.config_path):
                    current_modified = os.path.getmtime(self.config_path)
                    
                    if current_modified != self.last_modified:
                        logger.info(f"Config file modified, reloading...")
                        self.last_modified = current_modified
                        
                        try:
                            self.reload_callback()
                            logger.info("Config reloaded successfully")
                        except Exception as e:
                            logger.error(f"Config reload failed: {e}")
                
                # Wait for next poll
                self.stop_event.wait(self.poll_interval)
                
            except Exception as e:
                logger.error(f"Config watcher error: {e}")
                time.sleep(1)
    
    def force_reload(self):
        """Force a reload without checking modification time"""
        logger.info("Forcing config reload...")
        try:
            self.reload_callback()
            # Update modification time to prevent reload immediately after
            if os.path.exists(self.config_path):
                self.last_modified = os.path.getmtime(self.config_path)
            logger.info("Config force reload complete")
        except Exception as e:
            logger.error(f"Config force reload failed: {e}")


class ReloadableConfig:
    """Wrapper that provides hot-reload functionality for config"""
    
    def __init__(self, original_config: Dict[str, Any]):
        self._config = original_config
        self._watcher: Optional[ConfigWatcher] = None
    
    def start_watching(self, config_path: str, poll_interval: float = 5.0):
        """Start watching config for changes"""
        def reload():
            # Reload config module
            import importlib
            import app.config as config_module
            try:
                importlib.reload(config_module)
                # Update our cached config
                for key in dir(config_module):
                    if not key.startswith('_'):
                        self._config[key] = getattr(config_module, key)
                logger.info("Config values updated from reload")
            except Exception as e:
                logger.error(f"Failed to reload config: {e}")
        
        self._watcher = ConfigWatcher(config_path, reload, poll_interval)
        self._watcher.start()
    
    def stop_watching(self):
        """Stop watching config"""
        if self._watcher:
            self._watcher.stop()
            self._watcher = None
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get config value"""
        return self._config.get(key, default)
    
    def __getitem__(self, key: str) -> Any:
        return self._config[key]
    
    def __setitem__(self, key: str, value: Any):
        self._config[key] = value


# Example usage:
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    test_config = {'TEST_VALUE': 'original'}
    
    def on_reload():
        test_config['TEST_VALUE'] = 'reloaded'
        print(f"Config reloaded! New value: {test_config['TEST_VALUE']}")
    
    watcher = ConfigWatcher('app/config.py', on_reload, poll_interval=2)
    watcher.start()
    
    print("Config watcher started. Modify app/config.py to test...")
    print("Press Ctrl+C to stop")
    
    import time
    try:
        time.sleep(60)
    except KeyboardInterrupt:
        pass
    
    watcher.stop()
    print("Watcher stopped")
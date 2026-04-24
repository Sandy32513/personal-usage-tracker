"""
Data Validation Module
Validates and sanitizes tracking events before insertion into database
Prevents corrupt data, SQL injection, and PII leaks
"""

import re
import logging
from datetime import datetime
from typing import Any, Dict, Optional
from app.config import ENABLE_REDACTION, REDACT_PATTERNS

logger = logging.getLogger(__name__)


class ValidationConfig:
    """Configuration for validation from app/config.py"""
    MAX_APP_NAME_LENGTH = 255
    MAX_WINDOW_TITLE_LENGTH = 1000
    MAX_URL_LENGTH = 2000
    MAX_TITLE_LENGTH = 1000
    MAX_DURATION_SECONDS = 86400
    
    # Use patterns from config
    SENSITIVE_PATTERNS = [(pattern, '[REDACTED]') for pattern in REDACT_PATTERNS]


# Pydantic models (require pydantic, fallback to manual validation if unavailable)
try:
    from pydantic import BaseModel, Field, ValidationError, validator
    
    class AppEvent(BaseModel):
        """Validated app event model"""
        type: str = 'app'
        app_name: str = Field(..., max_length=ValidationConfig.MAX_APP_NAME_LENGTH)
        window_title: Optional[str] = Field(None, max_length=ValidationConfig.MAX_WINDOW_TITLE_LENGTH)
        process_id: Optional[int] = None
        timestamp: str
        
        @validator('type')
        def validate_type(cls, v):
            if v not in ('app', 'app_v2'):
                raise ValueError('Invalid event type')
            return v
        
        @validator('timestamp')
        def validate_timestamp(cls, v):
            # Ensure valid ISO format
            try:
                datetime.fromisoformat(v)
            except:
                raise ValueError('Invalid timestamp format')
            return v
        
        def redact(self) -> 'AppEvent':
            """Return copy with sensitive content redacted if enabled"""
            if ENABLE_REDACTION:
                if self.window_title:
                    self.window_title = self._redact_text(self.window_title)
            return self
        
        @staticmethod
        def _redact_text(text: str) -> str:
            result = text
            for pattern, replacement in ValidationConfig.SENSITIVE_PATTERNS:
                result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
            return result
    
    class WebEvent(BaseModel):
        """Validated web event model"""
        type: str = 'web'
        url: str = Field(..., max_length=ValidationConfig.MAX_URL_LENGTH)
        title: Optional[str] = Field(None, max_length=ValidationConfig.MAX_TITLE_LENGTH)
        timestamp: str
        duration_seconds: Optional[int] = Field(0, ge=0, le=ValidationConfig.MAX_DURATION_SECONDS)
        
        @validator('type')
        def validate_type(cls, v):
            if v != 'web':
                raise ValueError('Invalid event type')
            return v

        @validator('timestamp')
        def validate_timestamp(cls, v):
            try:
                datetime.fromisoformat(v)
            except ValueError as exc:
                raise ValueError('Invalid timestamp format') from exc
            return v
        
        @validator('url')
        def validate_url(cls, v):
            if not v.startswith(('http://', 'https://')):
                raise ValueError('URL must start with http:// or https://')
            return v
        
        def redact(self) -> 'WebEvent':
            """Redact sensitive data from URL and title if enabled"""
            if ENABLE_REDACTION:
                self.url = self._redact_url(self.url)
                if self.title:
                    self.title = self._redact_text(self.title)
            return self
        
        @staticmethod
        def _redact_url(url: str) -> str:
            # Redact query parameters with sensitive names
            import urllib.parse
            parsed = urllib.parse.urlparse(url)
            if parsed.query:
                params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
                sensitive_keys = {'password', 'passwd', 'token', 'api_key', 'key', 'secret'}
                rebuilt_params = []
                for key, values in params.items():
                    if any(sens in key.lower() for sens in sensitive_keys):
                        rebuilt_params.append(('redacted', '[REDACTED]'))
                    else:
                        for value in values:
                            rebuilt_params.append((key, value))
                # Rebuild query
                new_query = urllib.parse.urlencode(rebuilt_params, doseq=True)
                parsed = parsed._replace(query=new_query)
                return urllib.parse.urlunparse(parsed)
            return url
        
        @staticmethod
        def _redact_text(text: str) -> str:
            result = text
            for pattern, replacement in ValidationConfig.SENSITIVE_PATTERNS:
                result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
            return result
    
    PYODANTIC_AVAILABLE = True
    logger.info("Pydantic available - using strict validation")

except ImportError:
    PYODANTIC_AVAILABLE = False
    logger.warning("Pydantic not installed - using basic validation")


class EventValidator:
    """Validates and sanitizes events"""

    @staticmethod
    def _model_dump(model: Any) -> Dict[str, Any]:
        """Support both Pydantic v1 and v2."""
        if hasattr(model, 'model_dump'):
            return model.model_dump()
        return model.dict()

    @staticmethod
    def _normalize_web_event(event: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize browser payloads to the canonical web event schema."""
        normalized = dict(event)
        if 'timestamp' not in normalized and 'visit_time' in normalized:
            normalized['timestamp'] = normalized['visit_time']
        if 'duration_seconds' not in normalized and 'visit_duration' in normalized:
            normalized['duration_seconds'] = normalized['visit_duration']
        return normalized
    
    @staticmethod
    def validate_app_event(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Validate and sanitize app event"""
        if PYODANTIC_AVAILABLE:
            try:
                validated = AppEvent(**event)
                validated.redact()
                return EventValidator._model_dump(validated)
            except ValidationError as e:
                logger.error(f"App event validation failed: {e}")
                return None
        else:
            return EventValidator._basic_app_validation(event)
    
    @staticmethod
    def validate_web_event(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Validate and sanitize web event"""
        normalized_event = EventValidator._normalize_web_event(event)
        if PYODANTIC_AVAILABLE:
            try:
                validated = WebEvent(**normalized_event)
                validated.redact()
                return EventValidator._model_dump(validated)
            except ValidationError as e:
                logger.error(f"Web event validation failed: {e}")
                return None
        else:
            return EventValidator._basic_web_validation(normalized_event)
    
    @staticmethod
    def _basic_app_validation(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Fallback validation without pydantic"""
        required = ['type', 'app_name', 'timestamp']
        for field in required:
            if field not in event:
                logger.error(f"Missing required field: {field}")
                return None
        
        if event.get('type') != 'app':
            logger.error("Invalid event type for app event")
            return None
        
        app_name = str(event['app_name'])[:ValidationConfig.MAX_APP_NAME_LENGTH]
        window_title = str(event.get('window_title', ''))[:ValidationConfig.MAX_WINDOW_TITLE_LENGTH]
        
        if ENABLE_REDACTION:
            window_title = EventValidator._redact_text(window_title)
        
        try:
            datetime.fromisoformat(event['timestamp'])
        except:
            logger.error("Invalid timestamp format")
            return None
        
        return {
            'type': 'app',
            'app_name': app_name,
            'window_title': window_title,
            'timestamp': event['timestamp'],
            'duration_seconds': min(int(event.get('duration_seconds', 0)), ValidationConfig.MAX_DURATION_SECONDS)
        }
    
    @staticmethod
    def _basic_web_validation(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Fallback validation without pydantic"""
        required = ['type', 'url', 'timestamp']
        for field in required:
            if field not in event:
                logger.error(f"Missing required field: {field}")
                return None
        
        if event.get('type') != 'web':
            logger.error("Invalid event type for web event")
            return None
        
        url = str(event['url'])[:ValidationConfig.MAX_URL_LENGTH]
        if not url.startswith(('http://', 'https://')):
            logger.error("Invalid URL scheme")
            return None
        
        title = str(event.get('title', ''))[:ValidationConfig.MAX_TITLE_LENGTH]
        if ENABLE_REDACTION:
            title = EventValidator._redact_text(title)
            url = EventValidator._redact_url(url)
        
        try:
            datetime.fromisoformat(event['timestamp'])
        except:
            logger.error("Invalid timestamp format")
            return None
        
        return {
            'type': 'web',
            'url': url,
            'title': title,
            'timestamp': event['timestamp'],
            'duration_seconds': min(int(event.get('duration_seconds', 0)), ValidationConfig.MAX_DURATION_SECONDS)
        }
    
    @staticmethod
    def _redact_text(text: str) -> str:
        result = text
        for pattern, replacement in ValidationConfig.SENSITIVE_PATTERNS:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        return result
    
    @staticmethod
    def _redact_url(url: str) -> str:
        import urllib.parse
        parsed = urllib.parse.urlparse(url)
        if parsed.query:
            params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            sensitive_keys = {'password', 'passwd', 'token', 'api_key', 'key', 'secret', 'auth'}
            rebuilt_params = []
            for key, values in params.items():
                if any(sens in key.lower() for sens in sensitive_keys):
                    rebuilt_params.append(('redacted', '[REDACTED]'))
                else:
                    for value in values:
                        rebuilt_params.append((key, value))
            parsed = parsed._replace(query=urllib.parse.urlencode(rebuilt_params, doseq=True))
            return urllib.parse.urlunparse(parsed)
        return url


# Standalone test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("Testing EventValidator...")
    print("-" * 50)
    
    # Test app event with sensitive title
    test_app = {
        'type': 'app',
        'app_name': 'Chrome',
        'window_title': 'Login - password=secret123 - Google Chrome',
        'timestamp': datetime.now().isoformat()
    }
    
    validated = EventValidator.validate_app_event(test_app)
    if validated:
        print(f"✓ App event validated: {validated['window_title']}")
    else:
        print("✗ App event validation failed")
    
    # Test web event with sensitive URL
    test_web = {
        'type': 'web',
        'url': 'https://example.com/login?username=john&password=hunter2',
        'title': 'Dashboard',
        'timestamp': datetime.now().isoformat()
    }
    
    validated = EventValidator.validate_web_event(test_web)
    if validated:
        print(f"✓ Web event validated: {validated['url']}")
    else:
        print("✗ Web event validation failed")
    
    # Test invalid event
    test_invalid = {'type': 'app', 'app_name': 'Test'}  # Missing timestamp
    result = EventValidator.validate_app_event(test_invalid)
    if result is None:
        print("✓ Correctly rejected invalid event")
    else:
        print("✗ Should have rejected invalid event")
    
    print("-" * 50)
    print("Test complete.")

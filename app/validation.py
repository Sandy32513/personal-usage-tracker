"""
Data Validation Module — Strict schema enforcement with Pydantic
Validates and sanitizes tracking events before insertion into database.
Prevents corrupt data, SQL injection, and PII leaks.

Requires pydantic>=2.5.0. Install: pip install "pydantic>=2.5.0,<2.14"
"""

import re
import logging
from datetime import datetime
from typing import Any, Dict, Optional
from app.config import ENABLE_REDACTION, REDACT_PATTERNS

logger = logging.getLogger(__name__)


class ValidationConfig:
    """Validation limits from config"""
    MAX_APP_NAME_LENGTH = 255
    MAX_WINDOW_TITLE_LENGTH = 1000
    MAX_URL_LENGTH = 2000
    MAX_TITLE_LENGTH = 1000
    MAX_DURATION_SECONDS = 86400
    
    SENSITIVE_PATTERNS = [(pattern, '[REDACTED]') for pattern in REDACT_PATTERNS]


# === PYDANTIC MODELS (Required) ===
try:
    from pydantic import BaseModel, Field, ValidationError, validator
except ImportError as e:
    raise ImportError(
        "Pydantic is required for validation. "
        "Install: pip install 'pydantic>=2.5.0,<2.14'"
    ) from e


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
        try:
            datetime.fromisoformat(v)
        except Exception:
            raise ValueError('Invalid timestamp format')
        return v
    
    def redact(self) -> 'AppEvent':
        """Redact sensitive data if enabled"""
        if ENABLE_REDACTION and self.window_title:
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
    
    @staticmethod
    def _redact_text(text: str) -> str:
        result = text
        for pattern, replacement in ValidationConfig.SENSITIVE_PATTERNS:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        return result


PYODANTIC_AVAILABLE = True
logger.info("Pydantic available - using strict validation")


class EventValidator:
    """Validates and sanitizes events using Pydantic models"""
    
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
        try:
            validated = AppEvent(**event)
            validated.redact()
            return EventValidator._model_dump(validated)
        except ValidationError as e:
            logger.error(f"App event validation failed: {e}")
            return None
    
    @staticmethod
    def validate_web_event(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Validate and sanitize web event (with normalization)"""
        normalized_event = EventValidator._normalize_web_event(event)
        try:
            validated = WebEvent(**normalized_event)
            validated.redact()
            return EventValidator._model_dump(validated)
        except ValidationError as e:
            logger.error(f"Web event validation failed: {e}")
            return None

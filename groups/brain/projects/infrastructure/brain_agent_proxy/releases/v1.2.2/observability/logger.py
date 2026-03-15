"""Logging utilities."""
import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict


def setup_logger(name: str = "brain_agent_proxy", level: str = "INFO") -> logging.Logger:
    """Setup logger."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))

    # Console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, level.upper()))

    # JSON formatter
    class JSONFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            data: Dict[str, Any] = {
                "timestamp": datetime.utcnow().isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info:
                data["exception"] = self.formatException(record.exc_info)
            return json.dumps(data)

    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)

    return logger


# Default logger
logger = setup_logger()

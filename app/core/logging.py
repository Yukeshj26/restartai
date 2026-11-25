import os
import sys
import logging
from typing import Any


import os
import sys
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_SYSTEM_LOG_BUFFER: deque = deque(maxlen=2000)


class StructuredFormatter(logging.Formatter):
    """Clean, structured terminal log formatter with timestamps and component tags."""

    LEVEL_COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        color = self.LEVEL_COLORS.get(record.levelname, "")
        reset = self.RESET if color else ""
        levelname = f"{color}{record.levelname:<7}{reset}"
        name = f"\033[34m{record.name}\033[0m" if color else record.name
        message = record.getMessage()
        return f"[{timestamp}] [{levelname}] [{name}] {message}"


class BufferLogHandler(logging.Handler):
    """Stores structured log records in a fixed-size ring buffer for API/UI retrieval."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            timestamp_utc = datetime.now(timezone.utc).isoformat()
            time_str = datetime.fromtimestamp(record.created).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            _SYSTEM_LOG_BUFFER.append(
                {
                    "timestamp": timestamp_utc,
                    "time_str": time_str,
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }
            )
        except Exception:
            self.handleError(record)


def get_system_logs(
    limit: int = 200, min_level: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Returns captured system log events in chronological order."""
    levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    min_idx = (
        levels.index(min_level.upper())
        if min_level and min_level.upper() in levels
        else 0
    )
    allowed = set(levels[min_idx:])

    filtered = [l for l in _SYSTEM_LOG_BUFFER if l["level"] in allowed]
    return filtered[-limit:] if limit else filtered


def clear_system_logs() -> None:
    _SYSTEM_LOG_BUFFER.clear()


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configures root logger with structured formatting and in-memory buffer."""
    log_level = getattr(logging, os.getenv("LOG_LEVEL", level).upper(), logging.INFO)
    logger = logging.getLogger("restartai")
    logger.setLevel(log_level)

    if not any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, BufferLogHandler)
        for h in logger.handlers
    ):
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(log_level)
        handler.setFormatter(StructuredFormatter())
        logger.addHandler(handler)

    if not any(isinstance(h, BufferLogHandler) for h in logger.handlers):
        buf_handler = BufferLogHandler()
        buf_handler.setLevel(logging.DEBUG)
        buf_handler.setFormatter(StructuredFormatter())
        logger.addHandler(buf_handler)

    logger.propagate = False
    return logger

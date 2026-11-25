import os
import sys
import logging
from typing import Any


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


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configures root logger with structured formatting."""
    log_level = getattr(logging, os.getenv("LOG_LEVEL", level).upper(), logging.INFO)
    logger = logging.getLogger("restartai")
    logger.setLevel(log_level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(log_level)
        handler.setFormatter(StructuredFormatter())
        logger.addHandler(handler)
        logger.propagate = False

    return logger

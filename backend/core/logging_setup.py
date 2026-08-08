"""Rich console logging for the resume maker API."""

from __future__ import annotations

import logging
import sys


class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        # Avoid Unicode in stream for Windows cp1252 consoles
        try:
            color = self.COLORS.get(record.levelno, "")
            record.levelname = f"{color}{record.levelname}{self.RESET}"
            return super().format(record)
        except Exception:
            return f"{record.levelname} | {record.getMessage()}"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    root = logging.getLogger("resume_maker")
    if root.handlers:
        return root

    root.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    try:
        handler.stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    handler.setLevel(level)
    handler.setFormatter(
        ColorFormatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.addHandler(handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)

    return root


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(f"resume_maker.{name}")

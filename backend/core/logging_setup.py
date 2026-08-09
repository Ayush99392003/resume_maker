"""Rich console + file logging for resume maker debugging."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

_CONFIGURED = False
_CONSOLE = None


def _log_level_from_env() -> int:
    raw = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    return getattr(logging, raw, logging.INFO)


def get_console():
    """Shared Rich Console (lazy)."""
    global _CONSOLE
    if _CONSOLE is None:
        from rich.console import Console

        _CONSOLE = Console(
            stderr=False,
            force_terminal=True,
            soft_wrap=True,
            highlight=True,
        )
    return _CONSOLE


def setup_logging(level: Optional[int] = None) -> logging.Logger:
    """
    Configure resume_maker logging with RichHandler (+ optional file sink).

    Env:
      LOG_LEVEL=DEBUG|INFO|WARNING|ERROR
      LOG_FILE=backend/data/logs/app.log   (optional)
      LOG_RICH=0                          (disable rich, plain stream)
    """
    global _CONFIGURED
    root = logging.getLogger("resume_maker")
    if _CONFIGURED and root.handlers:
        return root

    level = _log_level_from_env() if level is None else level
    root.setLevel(level)
    root.handlers.clear()

    use_rich = os.getenv("LOG_RICH", "1").strip() not in {"0", "false", "False"}

    if use_rich:
        try:
            from rich.logging import RichHandler

            handler = RichHandler(
                console=get_console(),
                rich_tracebacks=True,
                tracebacks_show_locals=os.getenv("LOG_LOCALS", "0") in {
                    "1",
                    "true",
                    "True",
                },
                markup=True,
                show_time=True,
                show_path=True,
                enable_link_path=True,
                log_time_format="%H:%M:%S",
            )
            handler.setLevel(level)
            handler.setFormatter(logging.Formatter("%(message)s"))
            root.addHandler(handler)
        except Exception:
            use_rich = False

    if not use_rich:
        handler = logging.StreamHandler(sys.stdout)
        try:
            handler.stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        handler.setLevel(level)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        root.addHandler(handler)

    # Optional rotating-ish file log for debugging sessions
    log_file = (os.getenv("LOG_FILE") or "").strip()
    if not log_file:
        default = (
            Path(__file__).resolve().parent.parent / "data" / "logs" / "app.log"
        )
        # Enable file log by default in development
        if os.getenv("ENVIRONMENT", "development") != "production":
            log_file = str(default)

    if log_file:
        try:
            path = Path(log_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(path, encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(
                logging.Formatter(
                    fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
            root.addHandler(fh)
        except Exception as e:
            root.warning("file log disabled: %s", e)

    # Quiet noisy libs; keep our DEBUG if requested
    for name in ("httpx", "httpcore", "openai", "urllib3", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(max(level, logging.INFO))

    _CONFIGURED = True
    root.debug(
        "logging ready level=%s rich=%s file=%s",
        logging.getLevelName(level),
        use_rich,
        log_file or "(none)",
    )
    return root


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(f"resume_maker.{name}")


def debug_panel(title: str, data: Any, *, logger: Optional[logging.Logger] = None) -> None:
    """Pretty-print a debug panel to the Rich console + logger."""
    log = logger or get_logger("debug")
    try:
        from rich.panel import Panel
        from rich.pretty import Pretty

        get_console().print(Panel(Pretty(data), title=title, expand=False))
    except Exception:
        log.debug("%s: %r", title, data)
    else:
        log.debug("%s (see console panel)", title)


def debug_exception(exc: BaseException, *, logger: Optional[logging.Logger] = None) -> None:
    """Print a rich traceback for debugging."""
    log = logger or get_logger("debug")
    try:
        get_console().print_exception(show_locals=False)
    except Exception:
        log.exception("exception: %s", exc)
    else:
        log.error("%s: %s", type(exc).__name__, exc)

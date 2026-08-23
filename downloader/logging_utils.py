"""Small logging helpers for command-line and bot downloader output."""

import logging
import threading
from datetime import datetime
from typing import Callable, Optional

_log_callback: Optional[Callable[[str], None]] = None
_callback_lock: threading.Lock = threading.Lock()
_logger: logging.Logger = logging.getLogger("downloader")


def timestamp() -> str:
    """Return current timestamp in HH:MM:SS format.

    Returns:
        The current local time formatted for log output.
    """

    return datetime.now().strftime("%H:%M:%S")


def set_log_callback(callback: Optional[Callable[[str], None]]) -> None:
    """Set a thread-safe callback to receive log messages.

    Args:
        callback: Function that accepts a string log message, or None to clear.
    """
    global _log_callback
    with _callback_lock:
        _log_callback = callback


def log(message: str) -> None:
    """Print a message prefixed with timestamp and trigger callback if set.

    Args:
        message: Message to print.
    """
    formatted_msg = f"[{timestamp()}] {message}"

    # The bot configures the downloader logger with a FileHandler, so all
    # downloader output is retained in the same runtime log as bot output.
    # Keep the CLI behavior when no logging configuration is installed.
    if _logger.hasHandlers():
        _logger.info(formatted_msg)
    else:
        print(formatted_msg)
    
    with _callback_lock:
        if _log_callback:
            try:
                _log_callback(formatted_msg)
            except Exception:
                pass

"""Small logging helpers for command-line downloader output."""

from datetime import datetime


def timestamp() -> str:
    """Return current timestamp in HH:MM:SS format.

    Returns:
        The current local time formatted for log output.
    """

    return datetime.now().strftime("%H:%M:%S")


def log(message: str) -> None:
    """Print a message prefixed with timestamp.

    Args:
        message: Message to print.
    """

    print(f"[{timestamp()}] {message}")

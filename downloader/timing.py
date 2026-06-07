"""Timing helpers for rate-limit friendly downloader delays."""

import time

from downloader.logging_utils import log


def sleep_with_countdown(
    delay: int,
    initial_message_template: str,
    countdown_message_template: str,
) -> None:
    """Sleep with periodic countdown log messages.

    Args:
        delay: Total number of seconds to sleep.
        initial_message_template: Format string with ``delay`` placeholder.
        countdown_message_template: Format string with ``remaining`` placeholder.
    """

    log(initial_message_template.format(delay=delay))
    for remaining in range(delay, 0, -10):
        log(countdown_message_template.format(remaining=remaining))
        time.sleep(min(10, remaining))

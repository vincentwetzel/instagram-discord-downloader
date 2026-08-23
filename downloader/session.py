"""Download session orchestration."""

import random
import time
from datetime import datetime
from typing import Optional

from downloader.downloads import download_saved_posts
from downloader.history import get_history_db_path
from downloader.logging_utils import log
from downloader.reporting import DownloadStats, build_report
from downloader.timing import sleep_with_countdown


def run_download_session(max_posts: Optional[int] = None) -> str:
    """Run the Playwright download session and return a report string.

    Args:
        max_posts: Optional maximum number of posts to download this session.

    Returns:
        Text report describing the session outcome.

    Raises:
        RuntimeError: If authentication fails.
    """

    log("")

    start_time = datetime.now()
    log(f"Script started at {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 60)
    log("\n>>> Starting session (discovering account from Firefox) <<<")
    sleep_with_countdown(
        random.randint(5, 15),
        "Sleeping for {delay} seconds before starting browser session...",
        "  Starting downloads in {remaining} seconds...",
    )

    stats = _run_with_browser_recovery(max_posts)
    end_time = datetime.now()

    account = stats.account_name or "Unknown"
    db_path = get_history_db_path(account)

    return build_report(
        account,
        start_time,
        end_time,
        max_posts,
        db_path,
        stats,
    )


def _run_with_browser_recovery(max_posts: Optional[int]) -> DownloadStats:
    """Relaunch the browser after a recoverable failure.

    Successful posts are committed to account history as they complete, so a
    fresh attempt resumes at the first shortcode not in SQLite.

    Args:
        max_posts: Optional maximum number of posts to download this session.

    Returns:
        Aggregate statistics from all browser attempts.
    """
    max_attempts = 3
    attempts: list[DownloadStats] = []

    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            log(
                f"Retrying download session after browser recovery "
                f"(attempt {attempt}/{max_attempts})..."
            )
            time.sleep(5)

        completed_count = sum(item.download_count for item in attempts)
        remaining_limit = (
            None
            if max_posts is None
            else max(0, max_posts - completed_count)
        )
        if remaining_limit == 0:
            return _combine_attempt_stats(attempts)
        current_stats = download_saved_posts(remaining_limit)
        attempts.append(current_stats)
        if not current_stats.session_failure or attempt == max_attempts:
            return _combine_attempt_stats(attempts)

        log(
            "Browser session became unavailable. Completed posts were saved; "
            "restarting the browser to resume remaining posts."
        )

    return _combine_attempt_stats(attempts)


def _combine_attempt_stats(attempts: list[DownloadStats]) -> DownloadStats:
    """Combine counters from browser attempts into one session result.

    Args:
        attempts: Statistics returned by each browser attempt.

    Returns:
        Aggregate statistics suitable for report generation.
    """
    result = attempts[-1]
    first = attempts[0]
    result.download_count = sum(item.download_count for item in attempts)
    result.download_errors = sum(item.download_errors for item in attempts)
    result.skip_count = sum(item.skip_count for item in attempts)
    result.pruned_count = sum(item.pruned_count for item in attempts)
    result.error_details = [
        detail for item in attempts for detail in item.error_details
    ]
    result.history_db_size_before = first.history_db_size_before
    result.remaining_before = first.remaining_before
    if first.remaining_before is not None:
        result.remaining_after = max(
            0,
            first.remaining_before - result.download_count,
        )
    result.session_failure = False
    return result


def prompt_for_max_posts() -> Optional[int]:
    """Prompt the user for an optional maximum number of posts.

    Returns:
        Optional positive post limit, or None for unlimited.
    """

    while True:
        try:
            max_posts_input = input(
                "\nEnter maximum number of posts to download this session "
                "(or press Enter for unlimited): "
            ).strip()
            if max_posts_input == "":
                return None
            max_posts = int(max_posts_input)
            if max_posts <= 0:
                log("Please enter a positive number.")
                continue
            return max_posts
        except ValueError:
            log("Please enter a valid integer.")

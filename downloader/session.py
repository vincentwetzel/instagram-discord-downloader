"""Download session orchestration."""

import random
from datetime import datetime
from typing import Optional

from downloader.downloads import download_saved_posts
from downloader.history import get_history_db_path
from downloader.logging_utils import log
from downloader.reporting import build_report
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

    stats = download_saved_posts(max_posts)
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

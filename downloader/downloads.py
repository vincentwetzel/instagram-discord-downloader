"""Saved-post download workflow."""

import random
from pathlib import Path
from typing import Optional

import instaloader

from downloader.history import (
    init_history_db,
    load_downloaded_shortcodes_db,
    prune_stale_shortcodes_db,
    save_downloaded_shortcode_db,
)
from downloader.logging_utils import log
from downloader.reporting import DownloadStats
from downloader.timing import sleep_with_countdown

HISTORY_DB_PATH = Path("download_history.db")


def download_saved_posts(
    loader: instaloader.Instaloader,
    account_name: str,
    max_posts: Optional[int],
) -> DownloadStats:
    """Download saved posts for the configured account.

    Args:
        loader: Authenticated Instaloader instance.
        account_name: Instagram account to download saved posts for.
        max_posts: Optional maximum number of posts to download.

    Returns:
        Download counters and error details.

    Raises:
        instaloader.exceptions.LoginRequiredException: If the session requires login.
        instaloader.exceptions.BadCredentialsException: If credentials are invalid.
    """

    init_history_db(HISTORY_DB_PATH)
    downloaded_shortcodes = load_downloaded_shortcodes_db(HISTORY_DB_PATH)
    stats = DownloadStats()
    stats.history_db_size_before = len(downloaded_shortcodes)

    log("Retrieving saved posts...")
    try:
        profile = instaloader.Profile.from_username(
            loader.context,
            account_name,
        )
        posts_list = list(profile.get_saved_posts())

        prepare_posts(
            posts_list,
            downloaded_shortcodes,
            max_posts,
            stats,
        )
        download_remaining_posts(
            loader,
            account_name,
            posts_list,
            downloaded_shortcodes,
            max_posts,
            stats,
        )
    except (
        instaloader.exceptions.LoginRequiredException,
        instaloader.exceptions.BadCredentialsException,
        instaloader.exceptions.ConnectionException,
    ):
        # Allow critical authentication errors to bubble up and safely abort
        # the session
        raise
    except instaloader.exceptions.InstaloaderException as exc:
        stats.download_errors += 1
        stats.error_details.append(f"Instagram error: {exc}")
        log(f"\nFailed to download saved posts: {exc}")
        log(
            "Instagram might be temporarily rate-limiting you, or your session expired. "
            "Please wait a few minutes before trying again."
        )
    finally:
        stats.history_db_size_after = len(downloaded_shortcodes)
        if stats.remaining_before is not None:
            stats.remaining_after = max(0, stats.remaining_before - stats.download_count)

    return stats


def prepare_posts(
    posts_list: list[instaloader.Post],
    downloaded_shortcodes: set[str],
    max_posts: Optional[int],
    stats: DownloadStats,
) -> None:
    """Sync history state and log post counts before downloads begin.

    Args:
        posts_list: Saved posts fetched from Instagram.
        downloaded_shortcodes: In-memory set of tracked shortcodes.
        max_posts: Optional maximum number of posts to download.
        stats: Mutable download counters.
    """

    stats.total_posts_available = len(posts_list)
    log(f"Fetched {stats.total_posts_available} saved posts for this session.")
    log(f"Already downloaded historically: {len(downloaded_shortcodes)}")

    posts_shortcodes = {post.shortcode for post in posts_list}
    stats.pruned_count = prune_stale_shortcodes_db(
        HISTORY_DB_PATH,
        posts_shortcodes,
    )
    if stats.pruned_count > 0:
        log(f"Pruned {stats.pruned_count} stale shortcode(s) (unsaved from IG)")
        downloaded_shortcodes.intersection_update(posts_shortcodes)

    remaining_total = count_remaining_posts(posts_list, downloaded_shortcodes)
    stats.remaining_before = remaining_total
    log(f"Remaining to download in this batch: {remaining_total}")
    log(f"Session limit: {max_posts if max_posts else 'unlimited'}")
    log("-" * 60)


def download_remaining_posts(
    loader: instaloader.Instaloader,
    account_name: str,
    posts_list: list[instaloader.Post],
    downloaded_shortcodes: set[str],
    max_posts: Optional[int],
    stats: DownloadStats,
) -> None:
    """Download posts that are not already tracked in history.

    Args:
        loader: Authenticated Instaloader instance.
        account_name: Instagram account used as download target.
        posts_list: Saved posts fetched from Instagram.
        downloaded_shortcodes: In-memory set of tracked shortcodes.
        max_posts: Optional maximum number of posts to download.
        stats: Mutable download counters.

    Raises:
        instaloader.exceptions.LoginRequiredException: If the session requires login.
        instaloader.exceptions.BadCredentialsException: If credentials are invalid.
        instaloader.exceptions.ConnectionException: If a connection or rate-limit error occurs.
    """

    remaining_total = count_remaining_posts(posts_list, downloaded_shortcodes)
    download_position = 0
    for post in posts_list:
        if post.shortcode in downloaded_shortcodes:
            stats.skip_count += 1
            continue

        download_position += 1

        try_download_post(
            loader,
            account_name,
            post,
            download_position,
            remaining_total,
            max_posts,
            downloaded_shortcodes,
            stats,
        )

        if max_posts is not None and stats.download_count >= max_posts:
            log(
                f"Reached maximum post limit ({max_posts}). "
                "Stopping download session."
            )
            break

        if download_position < remaining_total:
            sleep_between_downloads(random.randint(60, 120))


def try_download_post(
    loader: instaloader.Instaloader,
    account_name: str,
    post: instaloader.Post,
    download_position: int,
    remaining_total: int,
    max_posts: Optional[int],
    downloaded_shortcodes: set[str],
    stats: DownloadStats,
) -> None:
    """Download a single post and update history or error details.

    Args:
        loader: Authenticated Instaloader instance.
        account_name: Instagram account used as download target.
        post: Post to download.
        download_position: One-based position among remaining posts.
        remaining_total: Number of posts remaining at session start.
        max_posts: Optional maximum number of posts to download.
        downloaded_shortcodes: In-memory set of tracked shortcodes.
        stats: Mutable download counters.

    Raises:
        instaloader.exceptions.LoginRequiredException: If the session requires login.
        instaloader.exceptions.BadCredentialsException: If the credentials are invalid.
        instaloader.exceptions.ConnectionException: If a connection or rate-limit error occurs.
    """

    try:
        log(f"Downloading post {download_position}/{remaining_total}...")
        loader.download_post(post, target=account_name)
        stats.download_count += 1
        downloaded_shortcodes.add(post.shortcode)
        save_downloaded_shortcode_db(HISTORY_DB_PATH, post.shortcode)
        max_display = str(max_posts) if max_posts else "unlimited"
        archive_count = len(downloaded_shortcodes)
        total_avail = stats.total_posts_available if stats.total_posts_available is not None else "unknown"
        log(
            f"Downloaded {expected_filename(account_name, post)} "
            f"({stats.download_count}/{max_display} this session - "
            f"Archive: {archive_count}/{total_avail})"
        )
    except (
        instaloader.exceptions.LoginRequiredException,
        instaloader.exceptions.BadCredentialsException,
        instaloader.exceptions.ConnectionException,
    ):
        # Bubble up critical auth and connection failures to abort the
        # entire session immediately
        raise
    except Exception as post_error:
        stats.download_errors += 1
        error_msg = f"Post {post.shortcode}: {post_error}"
        stats.error_details.append(error_msg)
        log(f"Error downloading post {post.shortcode}: {post_error}")


def expected_filename(account_name: str, post: instaloader.Post) -> str:
    """Return the expected media filename for a downloaded post.

    Args:
        account_name: Instagram account used as download target.
        post: Downloaded post.

    Returns:
        Expected file path for display in logs.
    """

    extension = "mp4" if post.is_video else "jpg"
    timestamp_str = post.date_utc.strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{post.owner_username}_{timestamp_str}.{extension}"
    return str(Path(account_name) / filename)


def count_remaining_posts(
    posts_list: list[instaloader.Post],
    downloaded_shortcodes: set[str],
) -> int:
    """Count posts that have not yet been downloaded.

    Args:
        posts_list: Saved posts fetched from Instagram.
        downloaded_shortcodes: In-memory set of tracked shortcodes.

    Returns:
        Number of posts not present in history.
    """

    return sum(
        1 for post in posts_list if post.shortcode not in downloaded_shortcodes
    )


def sleep_between_downloads(delay: int) -> None:
    """Sleep between post downloads with a countdown.

    Args:
        delay: Total number of seconds to sleep.
    """

    sleep_with_countdown(
        delay,
        "  Next download in {delay} seconds...",
        "    {remaining}s remaining...",
    )

"""Saved-post download workflow."""

import random
from typing import Iterable, Optional, Set

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

HISTORY_DB_PATH = "download_history.db"


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
    """

    init_history_db(HISTORY_DB_PATH)
    downloaded_shortcodes = load_downloaded_shortcodes_db(HISTORY_DB_PATH)
    stats = DownloadStats()

    log("Retrieving saved posts...")
    try:
        profile = instaloader.Profile.from_username(
            loader.context,
            account_name,
        )
        posts_list = list(profile.get_saved_posts())
        prepare_posts(posts_list, downloaded_shortcodes, max_posts, stats)
        download_remaining_posts(
            loader,
            account_name,
            posts_list,
            downloaded_shortcodes,
            max_posts,
            stats,
        )
    except instaloader.exceptions.ConnectionException as exc:
        stats.download_errors += 1
        stats.error_details.append(f"Connection error: {exc}")
        log(f"\nFailed to download saved posts: {exc}")
        log(
            "Instagram might be temporarily rate-limiting you. "
            "Please wait a few minutes before trying again."
        )

    return stats


def prepare_posts(
    posts_list: list[instaloader.Post],
    downloaded_shortcodes: Set[str],
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
    log(f"Found {stats.total_posts_available} saved posts to download.")
    log(f"Already downloaded: {len(downloaded_shortcodes)}")

    posts_shortcodes = {post.shortcode for post in posts_list}
    stats.pruned_count = prune_stale_shortcodes_db(
        HISTORY_DB_PATH,
        posts_shortcodes,
    )
    if stats.pruned_count > 0:
        log(f"Pruned {stats.pruned_count} stale shortcode(s) (unsaved from IG)")
        downloaded_shortcodes.intersection_update(posts_shortcodes)

    remaining_total = count_remaining_posts(posts_list, downloaded_shortcodes)
    log(f"Remaining to download: {remaining_total}")
    log(f"Session limit: {max_posts if max_posts else 'unlimited'}")
    log("-" * 60)


def download_remaining_posts(
    loader: instaloader.Instaloader,
    account_name: str,
    posts_list: Iterable[instaloader.Post],
    downloaded_shortcodes: Set[str],
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
    """

    remaining_total = count_remaining_posts(posts_list, downloaded_shortcodes)
    download_position = 0
    for index, post in enumerate(posts_list):
        if post.shortcode in downloaded_shortcodes:
            stats.skip_count += 1
            continue

        download_position += 1
        if max_posts is not None and stats.download_count >= max_posts:
            log(
                f"Reached maximum post limit ({max_posts}). "
                "Stopping download session."
            )
            break

        try_download_post(
            loader,
            account_name,
            post,
            index,
            download_position,
            remaining_total,
            max_posts,
            downloaded_shortcodes,
            stats,
        )
        sleep_between_downloads(random.randint(60, 120))


def try_download_post(
    loader: instaloader.Instaloader,
    account_name: str,
    post: instaloader.Post,
    index: int,
    download_position: int,
    remaining_total: int,
    max_posts: Optional[int],
    downloaded_shortcodes: Set[str],
    stats: DownloadStats,
) -> None:
    """Download a single post and update history or error details.

    Args:
        loader: Authenticated Instaloader instance.
        account_name: Instagram account used as download target.
        post: Post to download.
        index: Zero-based index in the saved post list.
        download_position: One-based position among remaining posts.
        remaining_total: Number of posts remaining at session start.
        max_posts: Optional maximum number of posts to download.
        downloaded_shortcodes: In-memory set of tracked shortcodes.
        stats: Mutable download counters.
    """

    try:
        log(f"Downloading post {download_position}/{remaining_total}...")
        loader.download_post(post, target=account_name)
        stats.download_count += 1
        downloaded_shortcodes.add(post.shortcode)
        save_downloaded_shortcode_db(HISTORY_DB_PATH, post.shortcode)
        max_display = str(max_posts) if max_posts else "unlimited"
        log(
            f"Downloaded {expected_filename(account_name, post)} "
            f"({stats.download_count}/{max_display} this session)"
        )
    except Exception as post_error:
        stats.download_errors += 1
        error_msg = f"Post {index + 1}: {post_error}"
        stats.error_details.append(error_msg)
        log(f"Error downloading post {index + 1}: {post_error}")


def expected_filename(account_name: str, post: instaloader.Post) -> str:
    """Return the expected media filename for a downloaded post.

    Args:
        account_name: Instagram account used as download target.
        post: Downloaded post.

    Returns:
        Expected file path for display in logs.
    """

    extension = "mp4" if post.is_video else "jpg"
    return (
        f"{account_name}/{account_name}_"
        f"{post.date_utc.strftime('%Y-%m-%d_%H-%M-%S')}.{extension}"
    )


def count_remaining_posts(
    posts_list: Iterable[instaloader.Post],
    downloaded_shortcodes: Set[str],
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

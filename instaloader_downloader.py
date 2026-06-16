"""Compatibility entry point for the Instagram downloader."""

from typing import Optional

from downloader.auth import get_cookiefile
from downloader.history import (
    init_history_db,
    load_downloaded_shortcodes_db,
    prune_stale_shortcodes_db,
    save_downloaded_shortcode_db,
)
from downloader.logging_utils import log, timestamp
from downloader.session import prompt_for_max_posts, run_download_session

__all__ = [
    "get_cookiefile",
    "init_history_db",
    "load_downloaded_shortcodes_db",
    "log",
    "prompt_for_max_posts",
    "prune_stale_shortcodes_db",
    "run_download_session",
    "save_downloaded_shortcode_db",
    "timestamp",
]


if __name__ == "__main__":
    try:
        from downloader.config import load_downloader_config
        config = load_downloader_config()
        print("Configured accounts:", ", ".join(config.ig_names))
        target_input = input("Enter specific account to target (or press Enter for all): ").strip()
        target_account = target_input if target_input else None

        max_posts: Optional[int] = prompt_for_max_posts()
        report = run_download_session(max_posts, target_account)
        print(f"\n{report}")
    except KeyboardInterrupt:
        print("\n\nSession interrupted by user. Exiting.")
    except Exception as exc:
        print(f"\n❌ Error running download session: {exc}")

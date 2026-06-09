"""SQLite-backed download history tracking."""

from contextlib import closing
from pathlib import Path
from sqlite3 import OperationalError, connect
from typing import Union


def init_history_db(filepath: Union[str, Path]) -> None:
    """Initialize SQLite database with the download history table.

    Args:
        filepath: Path to the SQLite database file.
    """

    with closing(connect(filepath)) as conn:
        with conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS downloaded_posts (
                    shortcode TEXT PRIMARY KEY,
                    downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )"""
            )


def load_downloaded_shortcodes_db(filepath: Union[str, Path]) -> set[str]:
    """Load already-downloaded post shortcodes from SQLite database.

    Args:
        filepath: Path to the SQLite database file.

    Returns:
        Set of post shortcodes that have been downloaded.
    """

    with closing(connect(filepath)) as conn:
        try:
            cursor = conn.execute("SELECT shortcode FROM downloaded_posts")
            return {row[0] for row in cursor}
        except OperationalError:
            return set()


def save_downloaded_shortcode_db(filepath: Union[str, Path], shortcode: str) -> None:
    """Save one downloaded post shortcode to SQLite database.

    Uses INSERT OR IGNORE to avoid duplicates and ensure idempotency.

    Args:
        filepath: Path to the SQLite database file.
        shortcode: The post shortcode to save.
    """

    with closing(connect(filepath)) as conn:
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO downloaded_posts (shortcode) VALUES (?)",
                (shortcode,),
            )


def prune_stale_shortcodes_db(
    filepath: Union[str, Path],
    current_shortcodes: set[str],
) -> int:
    """Remove tracked shortcodes no longer in the current saved-post list.

    If a user unsaves a post from Instagram, its shortcode is removed from
    the database so re-saving it later does not cause an incorrect skip.

    Args:
        filepath: Path to the SQLite database file.
        current_shortcodes: Shortcodes currently in Instagram saved posts.

    Returns:
        Number of stale entries removed.
    """

    with closing(connect(filepath)) as conn:
        try:
            cursor = conn.execute("SELECT shortcode FROM downloaded_posts")
            all_tracked = {row[0] for row in cursor}
        except OperationalError:
            return 0
            
        stale = all_tracked - current_shortcodes
        if stale:
            with conn:
                conn.executemany(
                    "DELETE FROM downloaded_posts WHERE shortcode = ?",
                    ((shortcode,) for shortcode in stale),
                )
        return len(stale)

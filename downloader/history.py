"""SQLite-backed download history tracking."""

from sqlite3 import connect
from typing import Set


def init_history_db(filepath: str) -> None:
    """Initialize SQLite database with the download history table.

    Args:
        filepath: Path to the SQLite database file.
    """

    conn = connect(filepath)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS downloaded_posts ("
            "shortcode TEXT PRIMARY KEY, "
            "downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
        conn.commit()
    finally:
        conn.close()


def load_downloaded_shortcodes_db(filepath: str) -> Set[str]:
    """Load already-downloaded post shortcodes from SQLite database.

    Args:
        filepath: Path to the SQLite database file.

    Returns:
        Set of post shortcodes that have been downloaded.
    """

    conn = connect(filepath)
    try:
        cursor = conn.execute("SELECT shortcode FROM downloaded_posts")
        return {row[0] for row in cursor.fetchall()}
    finally:
        conn.close()


def save_downloaded_shortcode_db(filepath: str, shortcode: str) -> None:
    """Save one downloaded post shortcode to SQLite database.

    Uses INSERT OR IGNORE to avoid duplicates and ensure idempotency.

    Args:
        filepath: Path to the SQLite database file.
        shortcode: The post shortcode to save.
    """

    conn = connect(filepath)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO downloaded_posts (shortcode) VALUES (?)",
            (shortcode,),
        )
        conn.commit()
    finally:
        conn.close()


def prune_stale_shortcodes_db(
    filepath: str,
    current_shortcodes: Set[str],
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

    conn = connect(filepath)
    try:
        cursor = conn.execute("SELECT shortcode FROM downloaded_posts")
        all_tracked = {row[0] for row in cursor.fetchall()}
        stale = all_tracked - current_shortcodes
        if stale:
            conn.executemany(
                "DELETE FROM downloaded_posts WHERE shortcode = ?",
                [(shortcode,) for shortcode in stale],
            )
            conn.commit()
        return len(stale)
    finally:
        conn.close()

import random
import time
import sys
import json
import subprocess
import urllib.request
import urllib.error
from typing import Optional, Set
from datetime import datetime
from glob import glob
from os.path import expanduser
from platform import system
from sqlite3 import OperationalError, connect

import configparser

import instaloader


def timestamp() -> str:
    """Return current timestamp in HH:MM:SS format."""
    return datetime.now().strftime("%H:%M:%S")


def log(message: str) -> None:
    """Print a message prefixed with timestamp."""
    print(f"[{timestamp()}] {message}")


def init_history_db(filepath: str) -> None:
    """Initialize SQLite database with the download history table.

    Args:
        filepath: Path to the SQLite database file.
    """
    conn = connect(filepath)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS downloaded_posts ("
        "shortcode TEXT PRIMARY KEY, "
        "downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ")"
    )
    conn.commit()
    conn.close()


def load_downloaded_shortcodes_db(filepath: str) -> Set[str]:
    """Load set of already-downloaded post shortcodes from SQLite database.

    Args:
        filepath: Path to the SQLite database file.

    Returns:
        Set of post shortcodes that have been downloaded.
    """
    conn = connect(filepath)
    cursor = conn.execute("SELECT shortcode FROM downloaded_posts")
    shortcodes: Set[str] = {row[0] for row in cursor.fetchall()}
    conn.close()
    return shortcodes


def save_downloaded_shortcode_db(filepath: str, shortcode: str) -> None:
    """Save a single downloaded post shortcode to SQLite database.

    Uses INSERT OR IGNORE to avoid duplicates and ensure idempotency.

    Args:
        filepath: Path to the SQLite database file.
        shortcode: The post shortcode to save.
    """
    conn = connect(filepath)
    conn.execute(
        "INSERT OR IGNORE INTO downloaded_posts (shortcode) VALUES (?)",
        (shortcode,)
    )
    conn.commit()
    conn.close()


def prune_stale_shortcodes_db(filepath: str, current_shortcodes: Set[str]) -> int:
    """Remove shortcodes from the database that are no longer in the current saved posts list.

    This keeps the database in sync with what's actually on Instagram.
    If a user unsaves a post from IG, its shortcode will be removed from the DB
    so that re-saving it later won't cause it to be incorrectly skipped.

    Args:
        filepath: Path to the SQLite database file.
        current_shortcodes: Set of shortcodes that are currently in the IG saved posts list.

    Returns:
        Number of stale entries removed.
    """
    conn = connect(filepath)
    cursor = conn.execute("SELECT shortcode FROM downloaded_posts")
    all_tracked = {row[0] for row in cursor.fetchall()}
    stale = all_tracked - current_shortcodes
    if stale:
        conn.executemany(
            "DELETE FROM downloaded_posts WHERE shortcode = ?",
            [(s,) for s in stale]
        )
        conn.commit()
    conn.close()
    return len(stale)


def check_instaloader_version() -> None:
    """Check if instaloader is up to date. Auto-upgrade if outdated.

    Queries PyPI for the latest version and compares it to the installed
    version. If outdated, attempts to auto-upgrade via pip. Exits the
    script if upgrade is needed but fails.
    """
    try:
        current_version: str = instaloader.__version__
        log("Checking Instaloader version...")

        # Query PyPI for latest version
        url: str = "https://pypi.org/pypi/instaloader/json"
        req = urllib.request.Request(
            url, headers={"User-Agent": "Instaloader-Version-Checker"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data: dict = json.loads(response.read().decode())
            latest_version: str = data["info"]["version"]

        if current_version != latest_version:
            log("⚠ Outdated Instaloader detected!")
            log(f"   Current version: {current_version}")
            log(f"   Latest version:  {latest_version}")
            log("Attempting to upgrade automatically...")

            try:
                result: subprocess.CompletedProcess = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--upgrade", "instaloader"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )

                if result.returncode == 0:
                    log(f"✓ Successfully upgraded to Instaloader v{latest_version}")
                    log("Please restart the script to use the new version.")
                    sys.exit(0)
                else:
                    log("❌ Auto-upgrade failed!")
                    log(f"   pip output: {result.stderr.strip()}")
                    log("Please upgrade manually by running:")
                    log("   pip install --upgrade instaloader")
                    sys.exit(1)

            except subprocess.TimeoutExpired:
                log("❌ Auto-upgrade timed out. Please upgrade manually:")
                log("   pip install --upgrade instaloader")
                sys.exit(1)
            except Exception as e:
                log(f"❌ Auto-upgrade failed: {e}")
                log("Please upgrade manually by running:")
                log("   pip install --upgrade instaloader")
                sys.exit(1)
        else:
            log(f"✓ Instaloader is up to date (v{current_version})")

    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        log("⚠ Could not reach PyPI to verify version. Continuing...")
    except Exception as e:
        log(f"⚠ Version check failed: {e}. Continuing...")

# Run version check
check_instaloader_version()
print()

def get_cookiefile() -> Optional[str]:
    """Locate Firefox cookies.sqlite file for cookie extraction.

    Searches the default Firefox profile directory for cookies.sqlite
    based on the operating system.

    Returns:
        Path to cookies.sqlite file, or None if not found.
    """
    default_cookiefile: dict[str, str] = {
        "Windows": "~/AppData/Roaming/Mozilla/Firefox/Profiles/*/cookies.sqlite",
        "Darwin": "~/Library/Application Support/Firefox/Profiles/*/cookies.sqlite",
    }
    cookiefile_pattern: str = default_cookiefile.get(
        system(), "~/.mozilla/firefox/*/cookies.sqlite"
    )
    cookiefiles: list[str] = glob(expanduser(cookiefile_pattern))
    if not cookiefiles:
        return None
    return cookiefiles[0]


def import_session(
    cookiefile: str, instaloader_instance: instaloader.Instaloader
) -> instaloader.Instaloader:
    """Import Instagram session from Firefox cookies.

    Extracts Instagram cookies from Firefox's cookies.sqlite database
    and injects them into the Instaloader session to authenticate without
    requiring username/password login.

    Args:
        cookiefile: Path to Firefox cookies.sqlite file.
        instaloader_instance: Instaloader instance to inject cookies into.

    Returns:
        The authenticated Instaloader instance with username set.

    Raises:
        SystemExit: If not logged in to Instagram in Firefox.
    """
    log(f"Using cookies from {cookiefile}.")
    conn = connect(f"file:{cookiefile}?immutable=1", uri=True)
    try:
        cookie_data = conn.execute(
            "SELECT name, value FROM moz_cookies WHERE baseDomain='instagram.com'"
        )
    except OperationalError:
        cookie_data = conn.execute(
            "SELECT name, value FROM moz_cookies WHERE host LIKE '%instagram.com'"
        )
    instaloader_instance.context._session.cookies.update(cookie_data)
    username: Optional[str] = instaloader_instance.test_login()
    if not username:
        raise SystemExit(
            "Not logged in. Are you logged in successfully in Firefox?"
        )
    log(f"Imported session cookie for {username}.")
    instaloader_instance.context.username = username
    return instaloader_instance


# Load configuration
config: configparser.ConfigParser = configparser.ConfigParser()
config.read("settings.ini")

ig_name: str = config.get("Credentials", "ig_name", fallback="vincentwetzel")
pw: Optional[str] = config.get("Credentials", "pw", fallback=None)

# Get max posts limit from user
max_posts: Optional[int] = None
while True:
    try:
        max_posts_input: str = input(
            "\nEnter maximum number of posts to download this session "
            "(or press Enter for unlimited): "
        ).strip()
        if max_posts_input == "":
            max_posts = None
            break
        max_posts = int(max_posts_input)
        if max_posts <= 0:
            log("Please enter a positive number.")
            continue
        break
    except ValueError:
        log("Please enter a valid integer.")

# Record start time
start_time: datetime = datetime.now()
log(f"Script started at {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
log("=" * 60)

# Initialize Instaloader instance
L: instaloader.Instaloader = instaloader.Instaloader(
    download_video_thumbnails=False,
    download_geotags=False,
    download_comments=False,
    save_metadata=False,
    post_metadata_txt_pattern="",
    filename_pattern="{profile}_{date}",
)

try:
    L.load_session_from_file(ig_name)
    # NOTE: Default session file location:
    # LINUX: ~/.config/instaloader/session-YOUR-USERNAME
    # WINDOWS: AppData/Local/Instaloader/session-YOUR-USERNAME

    # Check if the loaded session is still valid
    if not L.test_login():
        raise instaloader.exceptions.BadCredentialsException(
            "Session expired or invalid."
        )

    log("Session successfully loaded and verified from file...")
except (
    FileNotFoundError,
    instaloader.exceptions.BadCredentialsException,
    instaloader.exceptions.ConnectionException,
) as e:
    # No user session found or session is invalid, need to create a session then save it to a file
    log(f"No valid session found ({e}), attempting manual login...")
    try:
        if not pw:
            raise instaloader.exceptions.BadCredentialsException(
                "No password provided in settings.ini"
            )
        L.login(ig_name, pw)
    except instaloader.exceptions.TwoFactorAuthRequiredException:
        while True:
            try:
                two_fa_code = input(
                    "Enter 6-digit 2 Factor Authentication code "
                    "from authenticator app: "
                )
                L.two_factor_login(two_fa_code)
                break
            except instaloader.exceptions.BadCredentialsException:
                pass
    except (
        instaloader.exceptions.BadCredentialsException,
        instaloader.exceptions.ConnectionException,
        instaloader.exceptions.LoginException,
    ) as e:
        log(f"Login failed ({e}). Attempting to extract Firefox cookies...")
        cookiefile = get_cookiefile()
        if cookiefile:
            import_session(cookiefile, L)
        else:
            raise SystemExit(
                "No Firefox cookies found and manual login failed."
            )

    # Save session to file
    # This defaults to the username
    L.save_session_to_file()

# Sleep before downloading to avoid rate limits
initial_delay: int = random.randint(15, 60)
log(f"Sleeping for {initial_delay} seconds before starting downloads...")
for remaining in range(initial_delay, 0, -10):
    log(f"  Starting downloads in {remaining} seconds...")
    time.sleep(min(10, remaining))

# Load download history for resuming across sessions
shortcodes_file: str = "download_history.db"
init_history_db(shortcodes_file)
downloaded_shortcodes: Set[str] = load_downloaded_shortcodes_db(shortcodes_file)

# Download saved posts
log("Retrieving saved posts...")
download_count: int = 0
skip_count: int = 0
download_errors: int = 0
error_details: list[str] = []
try:
    profile: instaloader.Profile = instaloader.Profile.from_username(
        L.context, ig_name
    )
    posts_list = list(profile.get_saved_posts())
    total_posts_available: int = len(posts_list)

    log(f"Found {total_posts_available} saved posts to download.")
    log(f"Already downloaded: {len(downloaded_shortcodes)}")

    # Count how many posts are actually remaining (not in database)
    # We need to iterate since posts is a generator
    posts_shortcodes: Set[str] = {p.shortcode for p in posts_list}

    # Remove stale entries from DB (posts that are no longer in IG saved list)
    pruned_count: int = prune_stale_shortcodes_db(shortcodes_file, posts_shortcodes)
    if pruned_count > 0:
        log(f"Pruned {pruned_count} stale shortcode(s) (unsaved from IG)")
        # Update in-memory set to match DB
        downloaded_shortcodes = downloaded_shortcodes & posts_shortcodes

    posts_to_download_count = sum(
        1 for p in posts_list if p.shortcode not in downloaded_shortcodes
    )
    remaining_total: int = posts_to_download_count
    log(f"Remaining to download: {remaining_total}")
    log(f"Session limit: {max_posts if max_posts else 'unlimited'}")
    log("-" * 60)

    posts_to_download_display: int = 0
    for i, post in enumerate(posts_list):
        if post.shortcode in downloaded_shortcodes:
            skip_count += 1
            continue
        posts_to_download_display += 1
        if max_posts is not None and download_count >= max_posts:
            log(
                f"Reached maximum post limit ({max_posts}). "
                f"Stopping download session."
            )
            break
        try:
            log(f"Downloading post {posts_to_download_display}/{remaining_total}...")
            L.download_post(post, target=ig_name)
            download_count += 1
            downloaded_shortcodes.add(post.shortcode)
            save_downloaded_shortcode_db(shortcodes_file, post.shortcode)
            # Construct expected filename based on filename_pattern
            ext: str = "mp4" if post.is_video else "jpg"
            expected_filename: str = (
                f"{ig_name}/{ig_name}_"
                f"{post.date_utc.strftime('%Y-%m-%d_%H-%M-%S')}.{ext}"
            )
            max_display: str = str(max_posts) if max_posts else "∞"
            log(
                f"✓ Downloaded {expected_filename} "
                f"({download_count}/{max_display} this session)"
            )
        except Exception as post_error:
            download_errors += 1
            error_msg: str = f"Post {i + 1}: {post_error}"
            error_details.append(error_msg)
            log(f"✗ Error downloading post {i + 1}: {post_error}")

        delay: int = random.randint(60, 120)
        log(f"  Next download in {delay} seconds...")
        for remaining in range(delay, 0, -10):
            log(f"    {remaining}s remaining...")
            time.sleep(min(10, remaining))
            
except instaloader.exceptions.ConnectionException as e:
    download_errors += 1
    error_details.append(f"Connection error: {e}")
    log(f"\nFailed to download saved posts: {e}")
    log(
        "Instagram might be temporarily rate-limiting you. "
        "Please wait a few minutes before trying again."
    )

# Final report
end_time: datetime = datetime.now()
duration: float = (end_time - start_time).total_seconds()
minutes: int = int(duration // 60)
seconds: int = int(duration % 60)

log("=" * 60)
log("DOWNLOAD SESSION REPORT")
log("=" * 60)
log(f"  Account:              {ig_name}")
log(f"  Session started:      {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
log(f"  Session ended:        {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
log(f"  Total duration:       {minutes}m {seconds}s")
log(f"  Posts found:          {total_posts_available if 'total_posts_available' in locals() else 'unknown'}")
log(f"  Posts skipped:        {skip_count} (already downloaded)")
log(f"  Posts downloaded:     {download_count}")
log(f"  Stale entries pruned: {pruned_count if 'pruned_count' in locals() else 0}")
log(f"  Errors encountered:   {download_errors}")
if error_details:
    log("  Error details:")
    for detail in error_details:
        log(f"    - {detail}")
log(f"  Session limit set:    {max_posts if max_posts else 'unlimited'}")
log(f"  Tracking file:        {shortcodes_file}")
log("=" * 60)

L.save_session_to_file()
log("Session saved successfully.")
log("Done!")

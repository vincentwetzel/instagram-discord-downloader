"""Download session orchestration."""

import random
from datetime import datetime
from typing import Optional

import instaloader

from downloader.auth import get_cookiefile, import_session
from downloader.config import DownloaderConfig, load_downloader_config
from downloader.downloads import HISTORY_DB_PATH, download_saved_posts
from downloader.logging_utils import log
from downloader.reporting import build_report
from downloader.timing import sleep_with_countdown
from downloader.version import check_instaloader_version


def run_download_session(max_posts: Optional[int] = None) -> str:
    """Run the download session and return a report string.

    Args:
        max_posts: Optional maximum number of posts to download this session.

    Returns:
        Text report describing the session outcome.
    """

    check_instaloader_version()
    print()

    config = load_downloader_config()
    start_time = datetime.now()
    log(f"Script started at {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 60)

    loader = _create_instaloader()
    _authenticate_loader(loader, config)
    sleep_with_countdown(
        random.randint(15, 60),
        "Sleeping for {delay} seconds before starting downloads...",
        "  Starting downloads in {remaining} seconds...",
    )

    stats = download_saved_posts(loader, config.ig_name, max_posts)
    end_time = datetime.now()
    loader.save_session_to_file()
    return build_report(
        config.ig_name,
        start_time,
        end_time,
        max_posts,
        HISTORY_DB_PATH,
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


def _create_instaloader() -> instaloader.Instaloader:
    """Create the configured Instaloader instance.

    Returns:
        Instaloader instance configured for this project.
    """

    return instaloader.Instaloader(
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        post_metadata_txt_pattern="",
        filename_pattern="{profile}_{date}",
    )


def _authenticate_loader(
    loader: instaloader.Instaloader,
    config: DownloaderConfig,
) -> None:
    """Authenticate an Instaloader instance.

    Args:
        loader: Instaloader instance to authenticate.
        config: Downloader credentials.

    Raises:
        SystemExit: If no authentication method succeeds.
    """

    try:
        loader.load_session_from_file(config.ig_name)
        if not loader.test_login():
            raise instaloader.exceptions.BadCredentialsException(
                "Session expired or invalid."
            )
        log("Session successfully loaded and verified from file...")
    except (
        FileNotFoundError,
        instaloader.exceptions.BadCredentialsException,
        instaloader.exceptions.ConnectionException,
    ) as exc:
        log(f"No valid session found ({exc}), attempting manual login...")
        _login_and_save_session(loader, config)


def _login_and_save_session(
    loader: instaloader.Instaloader,
    config: DownloaderConfig,
) -> None:
    """Login manually or through Firefox cookies, then save the session.

    Args:
        loader: Instaloader instance to authenticate.
        config: Downloader credentials.

    Raises:
        SystemExit: If login and cookie extraction fail.
    """

    try:
        if not config.password:
            raise instaloader.exceptions.BadCredentialsException(
                "No password provided in settings.ini"
            )
        loader.login(config.ig_name, config.password)
    except instaloader.exceptions.TwoFactorAuthRequiredException:
        _complete_two_factor_login(loader)
    except (
        instaloader.exceptions.BadCredentialsException,
        instaloader.exceptions.ConnectionException,
        instaloader.exceptions.LoginException,
    ) as exc:
        log(f"Login failed ({exc}). Attempting to extract Firefox cookies...")
        cookiefile = get_cookiefile()
        if cookiefile:
            import_session(cookiefile, loader)
        else:
            raise SystemExit(
                "No Firefox cookies found and manual login failed."
            ) from exc

    loader.save_session_to_file()


def _complete_two_factor_login(loader: instaloader.Instaloader) -> None:
    """Prompt until two-factor authentication succeeds.

    Args:
        loader: Instaloader instance waiting for two-factor auth.
    """

    while True:
        try:
            two_fa_code = input(
                "Enter 6-digit 2 Factor Authentication code "
                "from authenticator app: "
            )
            loader.two_factor_login(two_fa_code)
            return
        except instaloader.exceptions.BadCredentialsException:
            pass


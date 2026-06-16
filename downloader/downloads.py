"""Saved-post download workflow."""

import configparser
import logging
import os
import random
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

from playwright.sync_api import sync_playwright, Page, BrowserContext
# Resilient import block to handle varying packaging structures of playwright-stealth
inject_stealth = None

try:
    from playwright_stealth import stealth_sync
    if callable(stealth_sync):
        inject_stealth = stealth_sync
except (ImportError, AttributeError):
    pass

if not inject_stealth:
    try:
        from playwright_stealth import stealth
        if callable(stealth):
            inject_stealth = stealth
        elif hasattr(stealth, "stealth_sync") and callable(stealth.stealth_sync):
            inject_stealth = stealth.stealth_sync
        elif hasattr(stealth, "stealth") and callable(stealth.stealth):
            inject_stealth = stealth.stealth
    except (ImportError, AttributeError):
        pass

if not inject_stealth:
    def inject_stealth(page: Any) -> None:
        pass

logger = logging.getLogger("downloader")

from downloader.auth import get_cookiefile
from downloader.history import (
    get_history_db_path,
    init_history_db,
    load_downloaded_shortcodes_db,
    prune_stale_shortcodes_db,
    save_downloaded_shortcode_db,
)
from downloader.logging_utils import log
from downloader.reporting import DownloadStats
from downloader.timing import sleep_with_countdown


def _extract_playwright_cookies(cookiefile_path: Path) -> list[dict[str, Any]]:
    """Extract Firefox cookies for Instagram and format them for Playwright.

    Args:
        cookiefile_path: Path to Firefox's cookies.sqlite file.

    Returns:
        List of cookies dictionaries compatible with Playwright.
    """
    cookies = []
    conn = sqlite3.connect(cookiefile_path)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT name, value, host, path, isSecure, expiry "
            "FROM moz_cookies WHERE host LIKE ?",
            ("%instagram.com%",)
        )
        for name, value, host, path, is_secure, expiry in cursor.fetchall():
            cookie = {
                "name": name,
                "value": value,
                "domain": host,
                "path": path,
                "secure": bool(is_secure),
            }
            if isinstance(expiry, (int, float)) and expiry > 0:
                # Cap the expiry at Year 2038 (32-bit signed int max) to prevent overflows
                cookie["expires"] = min(int(expiry), 2147483647)
            cookies.append(cookie)
    finally:
        conn.close()
    return cookies


def download_saved_posts(account_name: str, max_posts: Optional[int]) -> DownloadStats:
    """Download saved posts for the configured account.

    Args:
        account_name: Target Instagram username.
        max_posts: Optional maximum number of posts to download.

    Returns:
        Download counters and error details.
    """

    db_path = get_history_db_path(account_name)
    init_history_db(db_path)
    downloaded_shortcodes = load_downloaded_shortcodes_db(db_path)
    stats = DownloadStats()
    stats.history_db_size_before = len(downloaded_shortcodes)

    cookiefile_str = get_cookiefile()
    if not cookiefile_str:
        raise RuntimeError("No active Firefox session profile found. Please login to Firefox first.")

    cookies = _extract_playwright_cookies(Path(cookiefile_str))
    if not cookies:
        raise RuntimeError("No cookies found for instagram.com in Firefox profile.")

    log("Launching automated stealth browser...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800}
        )
        context.add_cookies(cookies)
        page = context.new_page()
        inject_stealth(page)

        # Intercept and store video URLs to resolve blob video sources
        captured_video_urls: list[str] = []
        def _capture_video_responses(response):
            try:
                url = response.url
                content_type = response.headers.get("content-type", "")
                if "video" in content_type or "mime=video" in url:
                    # Ignore segmented DASH stream chunks, HLS fragments, and byte-range streams
                    if any(chunk in url for chunk in ["bytestart=", "byteend=", ".m4s", "seg-", "fragment", "chunk"]):
                        return
                    if url not in captured_video_urls:
                        captured_video_urls.append(url)
            except Exception:
                pass
        page.on("response", _capture_video_responses)

        log("Accessing saved posts index...")
        try:
            page.goto(f"https://www.instagram.com/{account_name}/saved/all-posts/", wait_until="networkidle")
            
            # Verify if login succeeded
            if "login" in page.url:
                raise RuntimeError("Session expired or invalid. Please refresh Firefox login.")

            # Verify that the active session matches the requested account
            if f"/{account_name}/" not in page.url:
                raise RuntimeError(
                    f"Account mismatch! The loaded Firefox cookies belong to a different account. "
                    f"Expected to access '/{account_name}/saved/', but landed on '{page.url}'. "
                    f"Please log into '{account_name}' in Firefox first."
                )

            # Gather visible post links
            shortcodes = _gather_saved_shortcodes(page)
            stats.total_posts_available = len(shortcodes)
            
            prepare_posts(shortcodes, downloaded_shortcodes, max_posts, stats, db_path)
            
            download_remaining_posts(
                page,
                context,
                account_name,
                shortcodes,
                downloaded_shortcodes,
                max_posts,
                stats,
                db_path,
                captured_video_urls,
            )
        except Exception as exc:
            stats.download_errors += 1
            stats.error_details.append(f"Automation failure: {exc}")
            log(f"\nFailed during download session: {exc}")
            logger.error(f"Failed during download session for {account_name}: {exc}", exc_info=True)
        finally:
            browser.close()
            stats.history_db_size_after = len(downloaded_shortcodes)
            if stats.remaining_before is not None:
                stats.remaining_after = max(0, stats.remaining_before - stats.download_count)

    return stats


def _gather_saved_shortcodes(page: Page) -> list[str]:
    """Extract post shortcodes from the loaded Saved feed page.

    Args:
        page: Loaded Playwright Page context.

    Returns:
        List of shortcodes found on the page.
    """
    # Wait up to 10 seconds for standard post elements to render in the DOM
    try:
        page.wait_for_selector("a[href*='/p/'], a[href*='/reel/']", timeout=10000)
    except Exception as e:
        log("Warning: Timed out waiting for post grid elements to appear on the page.")
        logger.warning("Timed out waiting for post grid elements to appear", exc_info=True)

    shortcodes = []
    last_count = 0
    no_change_count = 0
    max_scroll_attempts = 150  # Safety limit supporting ~1500+ saved posts

    log("Scrolling to retrieve all saved posts index...")
    for attempt in range(max_scroll_attempts):
        links = page.query_selector_all("a[href*='/p/'], a[href*='/reel/']")
        for link in links:
            href = link.get_attribute("href")
            if href:
                parts = [p for p in href.split("/") if p]
                if len(parts) >= 2:
                    shortcode = parts[1]
                    if shortcode not in shortcodes:
                        shortcodes.append(shortcode)

        current_count = len(shortcodes)
        if current_count > last_count:
            no_change_count = 0
            last_count = current_count
        else:
            no_change_count += 1

        if no_change_count >= 3:
            break

        # Scroll to the bottom to trigger lazy loading of next batch
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(random.randint(1500, 2500))

    log(f"Finished index extraction. Discovered {len(shortcodes)} total saved posts.")
    return shortcodes


def prepare_posts(
    shortcodes: list[str],
    downloaded_shortcodes: set[str],
    max_posts: Optional[int],
    stats: DownloadStats,
    db_path: Path,
) -> None:
    """Sync history state and log post counts before downloads begin."""
    stats.total_posts_available = len(shortcodes)
    log(f"Fetched {stats.total_posts_available} saved posts for this session.")
    log(f"Already downloaded historically: {len(downloaded_shortcodes)}")

    posts_shortcodes = set(shortcodes)
    stats.pruned_count = prune_stale_shortcodes_db(db_path, posts_shortcodes)
    if stats.pruned_count > 0:
        log(f"Pruned {stats.pruned_count} stale shortcode(s) (unsaved from IG)")
        downloaded_shortcodes.intersection_update(posts_shortcodes)

    remaining_total = sum(1 for sc in shortcodes if sc not in downloaded_shortcodes)
    stats.remaining_before = remaining_total
    log(f"Remaining to download in this batch: {remaining_total}")
    log(f"Session limit: {max_posts if max_posts else 'unlimited'}")
    log("-" * 60)


def _find_next_button(page: Page) -> Optional[Any]:
    """Locate the Next chevron button in the carousel area using geometry coordinates or attributes.

    This is language/locale-agnostic and immune to changes in button label translations.
    """
    try:
        # Strategy 1: Look for common aria-labels or classes first
        for selector in [
            "button[aria-label*='Next']", 
            "button[aria-label*='next']", 
            "[role='button'][aria-label*='Next']", 
            "[role='button'][aria-label*='next']",
            "button._afxp",
        ]:
            btn = page.query_selector(selector)
            if btn and btn.is_visible():
                return btn
    except Exception:
        pass

    try:
        # Strategy 2: Look for button elements on the middle-right side of the viewport
        buttons = page.query_selector_all("button, [role='button']")
        for btn in buttons:
            box = btn.bounding_box()
            if box:
                # Next button sits in the middle-right area of the page viewport
                viewport = page.viewport_size
                width = viewport["width"] if viewport else 1280
                if box["x"] > (width / 2) and 200 < box["y"] < 600:
                    if btn.query_selector("svg"):
                        return btn
    except Exception:
        pass
    return None


def _extract_owner_username(page: Page, fallback_account: str) -> str:
    """Extract the original post owner's username using robust page-meta and DOM fallback strategies.

    Args:
        page: Loaded Playwright Page context.
        fallback_account: Fallback username if extraction fails.

    Returns:
        The extracted username.
    """
    # Locate the main layout container to exclude navigation sidebars completely
    main_elem = page.query_selector("main, [role='main']") or page
    candidates = []

    # Strategy 1: Check semantic h2 links inside main (extremely high confidence on Instagram Web)
    try:
        h2_links = main_elem.query_selector_all("h2 a[href]")
        for link in h2_links:
            href = link.get_attribute("href")
            if href:
                cleaned = href.strip("/")
                if (
                    cleaned 
                    and "/" not in cleaned 
                    and cleaned not in ["explore", "reels", "direct", "stories", "emails", "locations"]
                    and re.match(r"^[a-zA-Z0-9._\-]+$", cleaned)
                ):
                    candidates.append(cleaned.lower())
    except Exception:
        pass

    # Strategy 2: Check standard headers inside main (Reels fallback)
    try:
        headers = main_elem.query_selector_all("header")
        for h in headers:
            links = h.query_selector_all("a[href]")
            for link in links:
                href = link.get_attribute("href")
                if href:
                    cleaned = href.strip("/")
                    if (
                        cleaned 
                        and "/" not in cleaned 
                        and cleaned not in ["explore", "reels", "direct", "stories", "emails", "locations"]
                        and re.match(r"^[a-zA-Z0-9._\-]+$", cleaned)
                    ):
                        candidates.append(cleaned.lower())
    except Exception:
        pass

    # Strategy 3: Check any generic links inside main (scraped in order of appearance)
    try:
        links = main_elem.query_selector_all("a[href]")
        for link in links:
            href = link.get_attribute("href")
            if href:
                cleaned = href.strip("/")
                if (
                    cleaned 
                    and "/" not in cleaned 
                    and cleaned not in ["explore", "reels", "direct", "stories", "emails", "locations"]
                    and re.match(r"^[a-zA-Z0-9._\-]+$", cleaned)
                ):
                    candidates.append(cleaned.lower())
    except Exception:
        pass

    # Strategy 4: Fallback Metadata parsing (kept strictly as candidates)
    meta_candidates = []
    for selector in ["meta[property='og:description']", "meta[name='description']"]:
        try:
            elem = page.query_selector(selector)
            if elem:
                content = elem.get_attribute("content")
                if content:
                    m = re.search(r'\(@([a-zA-Z0-9._\-]+)\)', content)
                    if m:
                        meta_candidates.append(m.group(1).lower())
        except Exception:
            pass

    try:
        titles_to_check = []
        title_val = page.title()
        if title_val:
            titles_to_check.append(title_val)
        meta_title_elem = page.query_selector("meta[property='og:title']")
        if meta_title_elem:
            content = meta_title_elem.get_attribute("content")
            if content:
                titles_to_check.append(content)
        for text in titles_to_check:
            m = re.search(r'\(@([a-zA-Z0-9._\-]+)\)', text)
            if m:
                meta_candidates.append(m.group(1).lower())
            m = re.search(r'@([a-zA-Z0-9._\-]+)', text)
            if m:
                meta_candidates.append(m.group(1).lower())
            m = re.search(r'^([a-zA-Z0-9._\-]+)\s+on\s+Instagram', text, re.IGNORECASE)
            if m:
                meta_candidates.append(m.group(1).lower())
    except Exception:
        pass

    # Prioritization Phase
    # Rule 1: Find first DOM candidate that is NOT the logged-in user
    for c in candidates:
        if c != fallback_account.lower():
            return c

    # Rule 2: Find first meta candidate that is NOT the logged-in user
    for c in meta_candidates:
        if c != fallback_account.lower():
            return c

    # Rule 3: If only the logged-in user remains as a valid candidate, return it
    if candidates:
        return candidates[0]
    if meta_candidates:
        return meta_candidates[0]

    return fallback_account


def _has_aria_hidden_parent(elem: Any, page: Page) -> bool:
    """Check if the element or any of its parent elements has aria-hidden='true'.

    Args:
        elem: Playwright ElementHandle.
        page: Loaded Playwright Page context.

    Returns:
        True if aria-hidden='true' is found on the element or any parent, else False.
    """
    try:
        return page.evaluate(
            "(element) => {"
            "  let current = element;"
            "  while (current) {"
            "    if (current.getAttribute && current.getAttribute('aria-hidden') === 'true') {"
            "      return true;"
            "    }"
            "    current = current.parentElement;"
            "  }"
            "  return false;"
            "}",
            elem
        )
    except Exception:
        return False


def _find_active_media_element(page: Page) -> tuple[Optional[Any], Optional[str]]:
    """Find the currently active video or image element that is not hidden by aria-hidden
    and is currently positioned within the visible viewport (active carousel slide).

    Args:
        page: Loaded Playwright Page context.

    Returns:
        A tuple of (ElementHandle, type_str) where type_str is "video" or "image", or (None, None).
    """
    viewport = page.viewport_size
    viewport_width = viewport["width"] if viewport else 1280

    try:
        videos = page.query_selector_all("video")
        for v in videos:
            if v.is_visible() and not _has_aria_hidden_parent(v, page):
                box = v.bounding_box()
                if box and box["width"] > 200:
                    # Ensure the media element's horizontal center is within the visible viewport
                    center_x = box["x"] + (box["width"] / 2)
                    if 0 <= center_x <= viewport_width:
                        return v, "video"
    except Exception:
        pass

    try:
        imgs = page.query_selector_all("div._aagv img, img[style*='object-fit'], img[decoding='auto'], img")
        for img in imgs:
            if img.is_visible() and not _has_aria_hidden_parent(img, page):
                box = img.bounding_box()
                if box and box["width"] > 200:
                    # Ensure the media element's horizontal center is within the visible viewport
                    center_x = box["x"] + (box["width"] / 2)
                    if 0 <= center_x <= viewport_width:
                        return img, "image"
    except Exception:
        pass

    return None, None


def download_remaining_posts(
    page: Page,
    context: BrowserContext,
    account_name: str,
    shortcodes: list[str],
    downloaded_shortcodes: set[str],
    max_posts: Optional[int],
    stats: DownloadStats,
    db_path: Path,
    captured_video_urls: list[str],
) -> None:
    """Download posts that are not already tracked in history."""
    remaining_total = sum(1 for sc in shortcodes if sc not in downloaded_shortcodes)
    download_position = 0
    for shortcode in shortcodes:
        if shortcode in downloaded_shortcodes:
            stats.skip_count += 1
            continue

        download_position += 1
        try_download_post(
            page,
            context,
            account_name,
            shortcode,
            download_position,
            remaining_total,
            max_posts,
            downloaded_shortcodes,
            stats,
            db_path,
            captured_video_urls,
        )

        if max_posts is not None and stats.download_count >= max_posts:
            log(f"Reached maximum post limit ({max_posts}). Stopping download session.")
            break

        if download_position < remaining_total:
            sleep_between_downloads(random.randint(15, 30))


def try_download_post(
    page: Page,
    context: BrowserContext,
    account_name: str,
    shortcode: str,
    download_position: int,
    remaining_total: int,
    max_posts: Optional[int],
    downloaded_shortcodes: set[str],
    stats: DownloadStats,
    db_path: Path,
    captured_video_urls: list[str],
) -> None:
    """Download a single post (supporting carousels) using Playwright DOM queries."""
    try:
        log(f"Loading post {download_position}/{remaining_total} (shortcode: {shortcode})...")
        page.goto(f"https://www.instagram.com/p/{shortcode}/", wait_until="networkidle")

        # Verify if we got redirected to a login wall
        if "login" in page.url:
            raise RuntimeError("Session expired or redirected to login page. Please refresh Firefox cookies.")

        # Wait up to 10 seconds for main media elements to render
        try:
            page.wait_for_selector(
                "video, div._aagv img, img[style*='object-fit'], img[decoding='auto']",
                timeout=10000
            )
        except Exception as wait_exc:
            logger.warning(f"Timeout waiting for media on post {shortcode}: {wait_exc}")

        # Determine if this is a carousel post (has a visible 'Next' button or indicator dots)
        next_button = _find_next_button(page)
        is_carousel = (
            (page.query_selector("div[role='tablist'], ._ap30, ._acpx, ._acpw") is not None)
            or (next_button is not None)
            or (page.query_selector("button[aria-label*='Next'], button[aria-label*='next'], [role='button'][aria-label*='Next']") is not None)
        )
        max_slides = 30 if is_carousel else 1

        media_items = []
        video_counter = 0

        # Traverse carousel slides
        for slide_idx in range(max_slides):
            active_elem, elem_type = _find_active_media_element(page)
            if not active_elem:
                break

            video_elem = active_elem if elem_type == "video" else None
            img_elem = active_elem if elem_type == "image" else None

            if video_elem:
                media_url = video_elem.get_attribute("src")
                if media_url and media_url.startswith("blob:"):
                    # Force video elements to play (muted) to trigger browser streaming requests
                    try:
                        page.evaluate("const v = document.querySelector('video'); if (v) { v.muted = true; v.play().catch(() => {}); }")
                        page.wait_for_timeout(2000)
                    except Exception:
                        pass

                    if video_counter < len(captured_video_urls):
                        media_url = captured_video_urls[video_counter]
                    elif captured_video_urls:
                        media_url = captured_video_urls[-1]
                    else:
                        meta_video = page.query_selector("meta[property='og:video']")
                        if meta_video:
                            media_url = meta_video.get_attribute("content")
                        
                        # Fallback: Parse progressive mp4 CDN streams directly from hydrated page metadata
                        if not media_url or media_url.startswith("blob:"):
                            try:
                                html_content = page.content()
                                # Normalize JSON-escaped slashes before decoding
                                normalized_html = html_content.replace("\\/", "/")
                                decoded_content = normalized_html.encode('utf-8').decode('unicode_escape', errors='ignore')
                                mp4_matches = re.findall(
                                    r'https://[a-zA-Z0-9.-]+\.(?:cdninstagram\.com|fbcdn\.net)/[^\s"\'\\,]+\.mp4[^\s"\'\\,]*',
                                    decoded_content
                                )
                                if mp4_matches:
                                    media_url = mp4_matches[0]
                            except Exception as parse_exc:
                                logger.warning(f"Failed to parse progressive mp4 from page content: {parse_exc}")
                        
                        if not media_url or media_url.startswith("blob:"):
                            raise ValueError("Video source is a blob and no direct stream URL was intercepted.")
                ext = "mp4"
                video_counter += 1
            elif img_elem:
                media_url = img_elem.get_attribute("src")
                ext = "jpg"
            else:
                break

            if not media_url:
                break

            # Prevent double-processing or infinite loops on same item
            if any(item["url"] == media_url for item in media_items):
                break

            media_items.append({"url": media_url, "ext": ext})

            # Slide to the next media item if we are in a carousel
            if is_carousel:
                next_btn = _find_next_button(page)
                moved = False
                if next_btn and next_btn.is_visible():
                    try:
                        next_btn.click(force=True)
                        page.wait_for_timeout(1500)
                        moved = True
                    except Exception:
                        pass
                
                if not moved:
                    try:
                        # Focus on main presentation/media element to ensure keys target the post slider
                        media_container = page.query_selector("article, div._aagw, div[role='presentation']")
                        if media_container:
                            media_container.focus()
                        page.keyboard.press("ArrowRight")
                        page.wait_for_timeout(1500)
                    except Exception:
                        pass

        if not media_items:
            raise ValueError("No media element found for this post structure.")

        # Extract original post owner username (Instaloader legacy standard)
        owner_username = _extract_owner_username(page, account_name)

        # Extract original post creation timestamp (Instaloader legacy standard)
        timestamp_str = None
        time_elem = page.query_selector("time")
        if time_elem:
            datetime_str = time_elem.get_attribute("datetime")
            if datetime_str:
                try:
                    # Parse ISO UTC string (e.g., '2024-06-16T01:34:00.000Z')
                    clean_dt = datetime_str.replace("Z", "+00:00")
                    dt = datetime.fromisoformat(clean_dt)
                    timestamp_str = dt.strftime("%Y-%m-%d_%H-%M-%S")
                except Exception:
                    pass
        if not timestamp_str:
            timestamp_str = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")

        # Load storage configuration from settings.ini
        config = configparser.ConfigParser(interpolation=None)
        config.read(Path("settings.ini"))
        base_path_template = config.get("Storage", "base_download_path", fallback=None)

        if base_path_template:
            interpolated_path = base_path_template
            for placeholder in ["{account_name}", "{username}"]:
                interpolated_path = interpolated_path.replace(placeholder, account_name)
            output_dir = Path(interpolated_path)
        else:
            output_dir = Path("downloads") / account_name

        output_dir.mkdir(parents=True, exist_ok=True)

        for idx, item in enumerate(media_items):
            response = context.request.get(item["url"])
            if response.status != 200:
                raise RuntimeError(f"Failed to fetch media payload (status {response.status})")

            if len(media_items) > 1:
                filename = f"{owner_username}_{timestamp_str}_{idx + 1}.{item['ext']}"
            else:
                filename = f"{owner_username}_{timestamp_str}.{item['ext']}"
            
            file_path = output_dir / filename
            with open(file_path, "wb") as f:
                f.write(response.body())
            log(f"Downloaded {file_path}")

        stats.download_count += 1
        downloaded_shortcodes.add(shortcode)
        save_downloaded_shortcode_db(db_path, shortcode)
        
        max_display = str(max_posts) if max_posts else "unlimited"
        archive_count = len(downloaded_shortcodes)
        total_avail = stats.total_posts_available if stats.total_posts_available else "unknown"
        
        log(
            f"Completed download of post {shortcode} with {len(media_items)} items "
            f"({stats.download_count}/{max_display} this session - "
            f"Archive: {archive_count}/{total_avail})"
        )
    except Exception as exc:
        stats.download_errors += 1
        stats.error_details.append(f"Post {shortcode}: {exc}")
        log(f"Error downloading post {shortcode}: {exc}")
        logger.error(f"Error downloading post {shortcode}: {exc}", exc_info=True)


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

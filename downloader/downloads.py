"""Saved-post download workflow."""

import html
import json
import json
import base64
import configparser
import logging
import os
import random
import re
import sqlite3
import time # Added import for polling loop
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


def _extract_playwright_cookie_jars(cookiefile_path: Path) -> list[list[dict[str, Any]]]:
    """Extract Firefox cookies for Instagram, grouping them by Firefox container partition.

    Args:
        cookiefile_path: Path to Firefox's cookies.sqlite file.

    Returns:
        List of cookie list jars, sorted by most recently accessed.
    """
    import collections
    jars = collections.defaultdict(list)
    jar_latest_access = collections.defaultdict(int)

    conn = sqlite3.connect(cookiefile_path)
    cursor = conn.cursor()
    try:
        cursor.execute("PRAGMA table_info(moz_cookies)")
        columns = [col[1] for col in cursor.fetchall()]
        has_origin_attrs = "originAttributes" in columns
        has_last_accessed = "lastAccessed" in columns

        query_cols = ["name", "value", "host", "path", "isSecure", "expiry"]
        if has_origin_attrs:
            query_cols.append("originAttributes")
        if has_last_accessed:
            query_cols.append("lastAccessed")

        query = f"SELECT {', '.join(query_cols)} FROM moz_cookies WHERE host LIKE ?"
        cursor.execute(query, ("%instagram.com%",))
        
        for row in cursor.fetchall():
            row_dict = dict(zip(query_cols, row))
            name = row_dict["name"]
            value = row_dict["value"]
            host = row_dict["host"]
            path = row_dict["path"]
            is_secure = row_dict["isSecure"]
            expiry = row_dict["expiry"]
            
            origin_attr = row_dict.get("originAttributes", "")
            last_accessed = row_dict.get("lastAccessed", 0)
            
            cookie = {
                "name": name,
                "value": value,
                "domain": host,
                "path": path,
                "secure": bool(is_secure),
            }
            if isinstance(expiry, (int, float)) and expiry > 0:
                cookie["expires"] = min(int(expiry), 2147483647)
                
            jars[origin_attr].append(cookie)
            if last_accessed > jar_latest_access[origin_attr]:
                jar_latest_access[origin_attr] = last_accessed
    finally:
        conn.close()

    sorted_keys = sorted(jars.keys(), key=lambda k: jar_latest_access[k], reverse=True)
    return [jars[k] for k in sorted_keys]

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

    cookie_jars = _extract_playwright_cookie_jars(Path(cookiefile_str))
    if not cookie_jars:
        raise RuntimeError("No Instagram cookies found in the selected Firefox profile.")

    log("Launching automated stealth browser...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-web-security"])
        
        active_context = None
        active_page = None
        active_captured_video_urls = None
        active_captured_responses = None

        for jar_idx, jar_cookies in enumerate(cookie_jars):
            logger.debug(f"Testing cookie jar {jar_idx + 1}/{len(cookie_jars)}...")
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                bypass_csp=True
            )
            context.add_cookies(jar_cookies)
            page = context.new_page()
            inject_stealth(page)

            captured_video_urls = []
            captured_responses = {}

            def _capture_responses(response, urls_ref=captured_video_urls, resps_ref=captured_responses):
                try:
                    url = response.url
                    if not ("instagram.com" in url or "fbcdn.net" in url):
                        return

                    content_type = response.headers.get("content-type", "")
                    is_video = "video" in content_type or "mime=video" in url or any(url.endswith(ext) for ext in [".mp4", ".mov", ".webm"])
                    is_image = "image" in content_type

                    if is_video or is_image:
                        if any(chunk in url for chunk in ["bytestart=", "byteend=", ".m4s", "seg-", "fragment", "chunk"]):
                            return

                        if is_video and url not in urls_ref:
                            urls_ref.append(url)
                            logger.info(f"Added video stream URL to captured_video_urls: {url[:100]}...")
                        
                        resps_ref[url] = response
                except Exception:
                    pass

            page.on("response", _capture_responses)

            try:
                page.goto(f"https://www.instagram.com/{account_name}/saved/all-posts/", wait_until="networkidle")
                
                if "login" in page.url:
                    logger.debug(f"Cookie jar {jar_idx + 1} redirected to login.")
                    context.close()
                    continue

                if f"/{account_name}/saved/" not in page.url:
                    logger.debug(f"Cookie jar {jar_idx + 1} mismatch: expected '/{account_name}/saved/', landed on '{page.url}'.")
                    context.close()
                    continue
                
                # Successfully authenticated with this container!
                log(f"Successfully authenticated as '{account_name}' using cookie container {jar_idx + 1}!")
                active_context = context
                active_page = page
                active_captured_video_urls = captured_video_urls
                active_captured_responses = captured_responses
                break
            except Exception as test_exc:
                logger.debug(f"Cookie jar {jar_idx + 1} test raised an exception: {test_exc}")
                context.close()
                continue

        if not active_context or not active_page:
            raise RuntimeError(
                f"Could not log in as '{account_name}' using your Firefox session.\n\n"
                f"To fix this, please follow these quick steps:\n"
                f"1. Open your Firefox browser and go to https://www.instagram.com\n"
                f"2. Make sure you are logged into the account '{account_name}'.\n"
                f"3. If you have multiple logged-in accounts, click 'Switch Accounts' on Instagram and select '{account_name}' to make it the active profile.\n"
                f"4. (Advanced) If you use Firefox Multi-Account Containers, verify you have logged into '{account_name}' inside one of your container tabs.\n"
                f"5. Once verified, run this command again!"
            )

        context = active_context
        page = active_page
        captured_video_urls = active_captured_video_urls
        captured_responses = active_captured_responses

        log("Accessing saved posts index...")
        try:
            page.goto(f"https://www.instagram.com/{account_name}/saved/all-posts/", wait_until="networkidle")
            
            # Verify if login succeeded
            if "login" in page.url:
                raise RuntimeError("Session expired or invalid. Please refresh Firefox login.")

            # Verify that the active session matches the requested account and we are on the saved posts page
            if f"/{account_name}/saved/" not in page.url:
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
                captured_responses,
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
        page.wait_for_selector("a[href*='/p/'], a[href*='/reel/'], a[href*='/reels/']", timeout=10000)
    except Exception as e:
        log("Warning: Timed out waiting for post grid elements to appear on the page.")
        logger.warning("Timed out waiting for post grid elements to appear")

    shortcodes = []
    last_count = 0
    no_change_count = 0
    max_scroll_attempts = 150  # Safety limit supporting ~1500+ saved posts

    log("Scrolling to retrieve all saved posts index...")
    for attempt in range(max_scroll_attempts):
        links = page.query_selector_all("a[href*='/p/'], a[href*='/reel/'], a[href*='/reels/']")
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


def _find_next_button(page: Page, active_elem: Optional[Any] = None) -> Optional[Any]:
    """Locate the Next chevron button in the carousel area relative to the active media element.

    This is completely language-agnostic, layout-agnostic, and immune to class name changes.
    """
    if active_elem:
        try:
            media_box = active_elem.bounding_box()
            if media_box:
                media_right = media_box["x"] + media_box["width"]
                media_center_y = media_box["y"] + (media_box["height"] / 2)

                article_container = page.query_selector("article") or page.query_selector("body")
                if article_container:
                    buttons = article_container.query_selector_all("button, [role='button']")
                    best_btn = None
                    min_dist = float("inf")

                    for btn in buttons:
                        if not btn.is_visible():
                            continue
                        btn_box = btn.bounding_box()
                        if not btn_box or btn_box["width"] == 0 or btn_box["height"] == 0:
                            continue

                        # Skip large layout wrappers, slide overlays, or presentation buttons
                        if btn_box["width"] > 80 or btn_box["height"] > 80:
                            continue

                        # Next button must sit strictly on the right half of the active media element
                        btn_center_x = btn_box["x"] + (btn_box["width"] / 2)
                        media_center_x = media_box["x"] + (media_box["width"] / 2)
                        if btn_center_x <= media_center_x:
                            continue

                        btn_right = btn_box["x"] + btn_box["width"]
                        btn_center_y = btn_box["y"] + (btn_box["height"] / 2)

                        dist_from_right = abs(btn_right - media_right)
                        dist_from_center_y = abs(btn_center_y - media_center_y)

                        # Next button sits right inside/outside the right edge of the media, vertically centered
                        if dist_from_right < 80 and dist_from_center_y < 100:
                            total_dist = dist_from_right + dist_from_center_y
                            if total_dist < min_dist:
                                min_dist = total_dist
                                best_btn = btn

                    if best_btn:
                        logger.debug(f"Found carousel Next button via media-relative geometry. Distance: {min_dist}")
                        return best_btn
        except Exception as e:
            logger.debug(f"Error finding next button via media-relative geometry: {e}")

    # Fallback to general selectors if geometry strategy fails or active_elem is None
    try:
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
    return None


def _extract_owner_username(page: Page, fallback_account: str) -> str:
    """Extract the original post owner's username using robust page-meta and DOM fallback strategies.

    Args:
        page: Loaded Playwright Page context.
        fallback_account: Fallback username if extraction fails.

    Returns:
        The extracted username.
    """
    # Priority 1: URL path extraction (extremely reliable on redirected desktop page)
    try:
        url_parts = [p for p in page.url.split("/") if p]
        # Expected format: ['https:', 'www.instagram.com', 'username', 'p' or 'reel' or 'reels', 'shortcode']
        if len(url_parts) >= 5 and url_parts[3] in ["p", "reel", "reels"]:
            candidate = url_parts[2].lower()
            if candidate not in ["p", "reel", "reels", "explore", "stories", "direct", "emails", "locations"]:
                logger.debug(f"Extracted original post owner '{candidate}' via Priority 1 (URL Path)")
                return candidate
    except Exception as e:
        logger.debug(f"Failed to parse username from URL: {e}")

    json_candidates = []
    title_meta_candidates = [] # For high-confidence meta tags (titles)
    dom_confident_candidates = []
    fallback_candidates = []

    # Priority 2: JSON-LD & Page Source JSON state metadata (highest confidence, 100% author-specific)
    try:
        scripts = page.query_selector_all("script[type='application/ld+json']")
        for script in scripts:
            text = script.text_content()
            if text:
                try:
                    data = json.loads(text)
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        author = item.get("author")
                        if author and isinstance(author, dict):
                            name = author.get("name") or author.get("alternateName")
                            if name:
                                clean_name = name.replace("@", "").strip().lower()
                                if clean_name:
                                    json_candidates.append(clean_name)
                except Exception:
                    pass
    except Exception:
        pass

    # Parse raw page HTML source for hydrated state JSON patterns (extremely robust fallback)
    try:
        html_content = page.content()
        owner_matches = re.findall(r'"owner"\s*:\s*\{[^}]*?"username"\s*:\s*"([a-zA-Z0-9._\-]+)"', html_content)
        for m in owner_matches:
            json_candidates.append(m.lower())
        author_matches = re.findall(r'"author"\s*:\s*\{[^}]*?"username"\s*:\s*"([a-zA-Z0-9._\-]+)"', html_content)
        for m in author_matches:
            json_candidates.append(m.lower())
    except Exception as e:
        logger.debug(f"Failed to parse raw HTML JSON state: {e}")

    # Priority 3: Strict Meta Titles (og:title, twitter:title, page.title()) - highly reliable for author
    # Check titles first as they are highly reliable for the main author
    for selector in ["meta[property='og:title']", "meta[name='twitter:title']"]:
        try:
            elem = page.query_selector(selector)
            if elem:
                content = elem.get_attribute("content")
                if content:
                    m = re.search(r'\(@([a-zA-Z0-9._\-]+)\)', content)
                    if m:
                        title_meta_candidates.append(m.group(1).lower())
                    m = re.search(r'^@?([a-zA-Z0-9._\-]+)\s+on\s+Instagram', content, re.IGNORECASE)
                    if m:
                        title_meta_candidates.append(m.group(1).lower())
                    m = re.search(r'^@?([a-zA-Z0-9._\-]+)\s+•\s+Instagram', content, re.IGNORECASE)
                    if m:
                        title_meta_candidates.append(m.group(1).lower())
        except Exception:
            pass

    try:
        title_val = page.title()
        if title_val:
            m = re.search(r'\(@([a-zA-Z0-9._\-]+)\)', title_val)
            if m:
                title_meta_candidates.append(m.group(1).lower())
            m = re.search(r'^@?([a-zA-Z0-9._\-]+)\s+on\s+Instagram', title_val, re.IGNORECASE)
            if m:
                title_meta_candidates.append(m.group(1).lower())
            m = re.search(r'^@?([a-zA-Z0-9._\-]+)\s+•\s+Instagram', title_val, re.IGNORECASE)
            if m:
                title_meta_candidates.append(m.group(1).lower())
    except Exception:
        pass

    # Priority 3 (Strict Author Prefix from descriptions) & Priority 5 (Loose Meta Descriptions)
    for selector in ["meta[property='og:description']", "meta[name='description']"]:
        try:
            elem = page.query_selector(selector)
            if elem:
                content = elem.get_attribute("content")
                if content:
                    # Match strict parenthesized author handle prefix (e.g. "Name (@username) on Instagram:")
                    m = re.search(r'\((@[a-zA-Z0-9._\-]+)\)\s+(?:on\s+Instagram|•\s+Instagram)', content, re.IGNORECASE)
                    if m:
                        title_meta_candidates.append(m.group(1).replace("@", "").lower())

                    # Match strict post owner signature from metadata block (e.g. "- arvidhestner on April 7, 2022")
                    m = re.search(r'-\s*([a-zA-Z0-9._\-]+)\s+on\s+[A-Za-z]+\s+\d{1,2},\s+\d{4}', content)
                    if m:
                        title_meta_candidates.append(m.group(1).lower())

                    # Relegate general description mentions to Priority 5 fallbacks
                    m = re.search(r'\(@([a-zA-Z0-9._\-]+)\)', content)
                    if m:
                        fallback_candidates.append(m.group(1).lower())
                    m = re.search(r'@([a-zA-Z0-9._\-]+)', content)
                    if m:
                        fallback_candidates.append(m.group(1).lower())
        except Exception:
            pass

    # Priority 4: Semantic header and h2 elements (poster's username is in h2 or header)
    main_elem = page.query_selector("main, [role='main']") or page
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
                        dom_confident_candidates.append(cleaned.lower())
    except Exception:
        pass

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
                    dom_confident_candidates.append(cleaned.lower())
    except Exception:
        pass

    # Priority 4 Fallback: Extract the absolute first valid profile link inside `<article>`.
    # On Instagram post pages, the top-left post header contains the poster's profile picture and link.
    # This is guaranteed to be the first standard link inside `<article>`.
    try:
        article = page.query_selector("article")
        if article:
            links = article.query_selector_all("a[href]")
            seen_candidates = []
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
                        try:
                            is_tag_overlay = page.evaluate(
                                "(el) => { return !!el.closest('div._aagw, div._aagv, div[role=\"presentation\"]'); }",
                                link
                            )
                            if is_tag_overlay:
                                continue
                        except Exception:
                            pass
                        
                        if cleaned.lower() not in seen_candidates:
                            seen_candidates.append(cleaned.lower())
            if seen_candidates:
                dom_confident_candidates.append(seen_candidates[0])
    except Exception as e:
        logger.debug(f"Failed to extract first article link: {e}")

    # Priority 5: Generic DOM links (fallback last resort, might contain tagged/commented users)
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
                    # Tagged user links on Instagram usually appear inside the image overlay.
                    # Exclude links that reside inside the media container/carousel viewport to prevent tagged user pollution.
                    try:
                        is_tag_overlay = page.evaluate(
                            "(el) => { return !!el.closest('div._aagw, div._aagv, div[role=\"presentation\"]'); }",
                            link
                        )
                        if is_tag_overlay:
                            continue
                    except Exception:
                        pass
                    fallback_candidates.append(cleaned.lower())
    except Exception:
        pass

    # Prioritization filtering - find the first candidate that is NOT the logged-in user
    logged_in_user = fallback_account.lower()

    for c in json_candidates:
        if c != logged_in_user:
            logger.debug(f"Extracted original post owner '{c}' via Priority 2 (JSON-LD)")
            return c

    for c in title_meta_candidates: # New evaluation point for strict meta titles
        if c != logged_in_user:
            logger.debug(f"Extracted original post owner '{c}' via Priority 3 (Strict Meta Titles)")
            return c

    for c in dom_confident_candidates:
        if c != logged_in_user:
            logger.debug(f"Extracted original post owner '{c}' via Priority 4 (DOM semantic elements)")
            return c

    for c in fallback_candidates: # Now includes all description meta tags and generic DOM links
        if c != logged_in_user:
            logger.debug(f"Extracted original post owner '{c}' via Priority 5 (Loose Meta Descriptions / DOM general links)")
            return c

    # Final fallbacks if everything else is logged_in_user or empty
    for group, label in [
        (json_candidates, "JSON-LD"), # Priority 2
        (title_meta_candidates, "Strict Meta Titles"), # Priority 3
        (dom_confident_candidates, "DOM semantic elements"),
        (fallback_candidates, "Loose Meta Descriptions / DOM general links") # Priority 5
    ]:
        if group:
            logger.debug(f"Extracted original post owner '{group[0]}' via final fallback for {label}")
            return group[0]

    logger.debug(f"Extracted original post owner '{fallback_account}' via default fallback_account")
    return fallback_account


def _is_element_horizontally_centered(elem_box: dict, scope_box: dict) -> bool:
    """Check if an element is horizontally aligned/centered within the search scope box."""
    elem_center_x = elem_box["x"] + (elem_box["width"] / 2)
    scope_left = scope_box["x"]
    scope_right = scope_box["x"] + scope_box["width"]
    # Allow a small 15px alignment tolerance
    return (scope_left - 15) <= elem_center_x <= (scope_right + 15)


def _find_active_media_element(page: Page) -> tuple[Optional[Any], Optional[str]]:
    """Find the currently active video or image element within the main media container."""
    article_container = page.query_selector("article") or page.query_selector("body")
    if not article_container:
        logger.debug("No article or body container found.")
        return None, None

    # Try to find the specific carousel viewport within the main content area to get the alignment box
    carousel_viewport = None
    try:
        carousel_viewport = article_container.query_selector(
            "div[role='presentation'], div[role='group'][aria-label*='Carousel']"
        )
        if not carousel_viewport:
            carousel_viewport = article_container.query_selector("div[style*='aspect-ratio']")
    except Exception as e:
        logger.debug(f"Error finding carousel viewport: {e}")

    scope_element = carousel_viewport or article_container
    scope_box = scope_element.bounding_box()
    if not scope_box:
        return None, None

    scope_center_x = scope_box["x"] + (scope_box["width"] / 2)

    # Query candidates globally within article_container to prevent container sibling/overlay exclusions
    candidate_videos = []
    try:
        videos = article_container.query_selector_all("video")
        for v in videos:
            if v.is_visible():
                box = v.bounding_box()
                if box and box["width"] > 0 and _is_element_horizontally_centered(box, scope_box):
                    # Exclude videos that are inside suggestion links (e.g. recommendation grid)
                    try:
                        is_suggestion = page.evaluate(
                            "(el) => { return !!el.closest('a[href*=\"/p/\"], a[href*=\"/reel/\"], a[href*=\"/reels/\"]'); }",
                            v
                        )
                        if is_suggestion:
                            continue
                    except Exception:
                        pass
                    candidate_videos.append((v, box))
    except Exception as e:
        logger.debug(f"Error querying videos: {e}")

    candidate_images = []
    try:
        imgs = article_container.query_selector_all("div._aagv img, img[style*='object-fit'], img[decoding='auto'], img")
        for img in imgs:
            if img.is_visible():
                box = img.bounding_box()
                if box and box["width"] > 200 and _is_element_horizontally_centered(box, scope_box):
                    # Exclude images that are inside suggestion links (e.g. recommendation grid)
                    try:
                        is_suggestion = page.evaluate(
                            "(el) => { return !!el.closest('a[href*=\"/p/\"], a[href*=\"/reel/\"], a[href*=\"/reels/\"]'); }",
                            img
                        )
                        if is_suggestion:
                            continue
                    except Exception:
                        pass
                    candidate_images.append((img, box))
    except Exception as e:
        logger.debug(f"Error querying images: {e}")


    best_elem = None
    best_type = None
    min_dist = float("inf")

    for idx, (v, box) in enumerate(candidate_videos):
        center_x = box["x"] + (box["width"] / 2)
        dist = abs(center_x - scope_center_x)
        if dist < min_dist:
            min_dist = dist
            best_elem = v
            best_type = "video"

    for idx, (img, box) in enumerate(candidate_images):
        center_x = box["x"] + (box["width"] / 2)
        dist = abs(center_x - scope_center_x)
        if dist < min_dist:
            min_dist = dist
            best_elem = img
            best_type = "image"

    # Confirm the selected element is reasonably centered inside the boundaries of the card
    if best_elem:
        if min_dist < (scope_box["width"] / 2):
            return best_elem, best_type

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
    captured_responses: dict[str, Any],
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
            captured_responses,
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
    captured_responses: dict[str, Any],
) -> None:
    """Download a single post (supporting carousels) using Playwright DOM queries."""
    try:
        # Clear intercepted resources from previous post runs to avoid mismatched references
        captured_video_urls.clear()
        captured_responses.clear()

        log(f"Loading post {download_position}/{remaining_total} (shortcode: {shortcode})...")
        page.goto(f"https://www.instagram.com/p/{shortcode}/", wait_until="networkidle")

        # Verify if we got redirected to a login wall
        if "login" in page.url:
            raise RuntimeError("Session expired or redirected to login page. Please refresh Firefox cookies.")

        # Verify that we actually landed on the post page and weren't redirected away (e.g., due to rate limit or session loss)
        if f"/{shortcode}/" not in page.url:
            raise RuntimeError(
                f"Redirected away from post page! Expected URL to contain '/{shortcode}/', "
                f"but landed on '{page.url}'. Your session may have expired or been rate-limited."
            )

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

        try:
            user_agent = page.evaluate("navigator.userAgent")
        except Exception:
            user_agent = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )

        media_items_data = []
        video_counter = 0

        # Traverse carousel slides and download payloads on-the-fly
        for slide_idx in range(max_slides):
            if is_carousel and slide_idx > 0:
                last_active_src = active_elem.get_attribute("src") if active_elem else None
                logger.debug(f"Transition check: waiting for slide {slide_idx+1}. Last active src: {last_active_src[:100] if last_active_src else 'None'}...")
                transitioned = False
                active_elem = None
                elem_type = None
                for poll_idx in range(25):  # Poll up to 5 seconds
                    new_active_elem, new_elem_type = _find_active_media_element(page)
                    if new_active_elem:
                        new_src = new_active_elem.get_attribute("src")
                        if new_src != last_active_src:
                            active_elem = new_active_elem
                            elem_type = new_elem_type
                            transitioned = True
                            logger.debug(f"Transition successful! Slide {slide_idx+1} loaded on poll {poll_idx+1}.")
                            break
                    page.wait_for_timeout(200)
                if not transitioned or not active_elem:
                    logger.info("Reached the end of the carousel or slide transition stalled. Stopping traversal.")
                    break
            else:
                active_elem, elem_type = _find_active_media_element(page)
                if not active_elem:
                    break

            video_elem = active_elem if elem_type == "video" else None
            img_elem = active_elem if elem_type == "image" else None

            # Wait up to 5 seconds for the active element's src attribute to be populated with a valid URL
            media_url = None
            for _ in range(50):
                media_url = active_elem.get_attribute("src")
                if media_url and (media_url.startswith("http") or media_url.startswith("blob:")):
                    break
                page.wait_for_timeout(100)

            logger.info(f"Slide {slide_idx + 1} active element: {elem_type}, initial media_url: {media_url}")

            if video_elem:
                if media_url and media_url.startswith("blob:"):
                    logger.info("Muted blob URL detected, triggering video playback to capture streaming assets...")
                    # Force video elements to play (muted) to trigger browser streaming requests
                    try:
                        page.evaluate("(v) => { if (v) { v.muted = true; v.play().catch(() => {}); } }", video_elem)
                        # Give some time for network requests to fire and be captured
                        page.wait_for_timeout(1000) # Initial wait
                        
                        # Poll captured_video_urls for up to 5 seconds
                        start_time = time.time()
                        while (len(captured_video_urls) <= video_counter) and (time.time() - start_time < 5):
                            page.wait_for_timeout(200) # Poll every 200ms
                        
                        if not captured_video_urls:
                            logger.warning("No video URLs were captured after triggering playback and polling.")
                        else:
                            logger.info(f"Video URLs captured after playback: {captured_video_urls}")
                    except Exception as e:
                        logger.warning(f"Failed to trigger video playback or poll for video response: {e}")

                    # After attempting to trigger playback and capture, check captured_video_urls
                    logger.info(f"Captured video URLs so far: {captured_video_urls}")
                    if video_counter < len(captured_video_urls):
                        media_url = captured_video_urls[video_counter]
                        logger.info(f"Resolved blob to captured URL: {media_url}")
                    elif captured_video_urls:
                        # Try to find a captured video URL that hasn't been used yet
                        unused_captured = [u for u in captured_video_urls if not any(item["url"] == u for item in media_items_data)]
                        if unused_captured:
                            media_url = unused_captured[0]
                            logger.info(f"Resolved blob to unused captured URL: {media_url}")
                        else:
                            logger.info("All captured video URLs already used. Proceeding to other fallbacks.")

                    if not media_url or media_url.startswith("blob:"):
                        meta_video = page.query_selector("meta[property='og:video']")
                        if meta_video:
                            candidate_meta = meta_video.get_attribute("content")
                            if candidate_meta and not any(item["url"] == candidate_meta for item in media_items_data):
                                media_url = candidate_meta
                                logger.info(f"Resolved blob to meta property og:video: {media_url}")
                        
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
                                    # Deduplicate matches while preserving order
                                    seen_matches = []
                                    for match in mp4_matches:
                                        cleaned = re.split(r'(?:&lt;|&gt;|<|>|\\u|\\n|\\t|")', match)[0]
                                        unescaped = html.unescape(cleaned)
                                        if unescaped not in seen_matches:
                                            seen_matches.append(unescaped)

                                    # Find the first unused mp4 match
                                    unused_matches = [m for m in seen_matches if not any(item["url"] == m for item in media_items_data)]
                                    if unused_matches:
                                        media_url = unused_matches[0]
                                        logger.info(f"Resolved blob to parsed HTML match (unused): {media_url}")
                                    elif len(seen_matches) > video_counter:
                                        media_url = seen_matches[video_counter]
                                        logger.info(f"Resolved blob to parsed HTML match at index {video_counter}: {media_url}")
                                    else:
                                        media_url = seen_matches[0]
                                        logger.info(f"Resolved blob to first parsed HTML match fallback: {media_url}")
                            except Exception as parse_exc:
                                logger.warning(f"Failed to parse progressive mp4 from page content: {parse_exc}")
                        
                        if not media_url or media_url.startswith("blob:"):
                            raise ValueError("Video source is a blob and no direct stream URL was intercepted.")
                ext = "mp4"
                video_counter += 1
            elif img_elem:
                ext = "jpg"
            else:
                break

            if not media_url:
                break

            # Prevent double-processing or infinite loops on same item
            if any(item["url"] == media_url for item in media_items_data):
                logger.info("Duplicate media item detected after transition. Stopping traversal.")
                break

            # Download media bytes immediately while the element is active and mounted
            media_bytes = None
            tier_reports = []

            # Tier 1: Check captured network responses (direct hit!)
            if media_url in captured_responses:
                try:
                    media_bytes = captured_responses[media_url].body()
                    logger.info(f"Retrieved {media_url[:100]}... directly from captured network responses.")
                    tier_reports.append("Tier 1 (Direct Cache): Success")
                except Exception as body_exc:
                    logger.info(f"Failed to get body from captured response for {media_url[:100]}...: {body_exc}")
                    tier_reports.append(f"Tier 1 (Direct Cache): Failed to read body - {body_exc}")
            else:
                tier_reports.append("Tier 1 (Direct Cache): URL not captured in network events")

            if media_bytes is None:
                # Fuzzy path match in case of minor query param discrepancies
                try:
                    item_path = media_url.split('?')[0]
                    matched_fuzzy = False
                    for cap_url, cap_resp in captured_responses.items():
                        if cap_url.split('?')[0] == item_path:
                            media_bytes = cap_resp.body()
                            logger.info(f"Retrieved {media_url[:100]}... via fuzzy path match from captured responses.")
                            tier_reports.append("Tier 1 (Fuzzy Match): Success")
                            matched_fuzzy = True
                            break
                    if not matched_fuzzy:
                        tier_reports.append("Tier 1 (Fuzzy Match): No matching URL path found in cache")
                except Exception as fuzzy_exc:
                    logger.info(f"Fuzzy match body retrieval failed: {fuzzy_exc}")
                    tier_reports.append(f"Tier 1 (Fuzzy Match): Failure - {fuzzy_exc}")

            # Tier 2: Canvas extraction for the active image element
            if ext == "jpg":
                if media_bytes is None:
                    try:
                        js_canvas = """
                        (img) => {
                            if (!img) return null;
                            const canvas = document.createElement('canvas');
                            canvas.width = img.naturalWidth || img.width;
                            canvas.height = img.naturalHeight || img.height;
                            const ctx = canvas.getContext('2d');
                            ctx.drawImage(img, 0, 0);
                            return canvas.toDataURL('image/jpeg').split(',')[1];
                        }
                        """
                        base64_data = page.evaluate(js_canvas, active_elem)
                        if base64_data:
                            media_bytes = base64.b64decode(base64_data)
                            logger.info(f"Retrieved {media_url[:100]}... via Canvas extraction.")
                            tier_reports.append("Tier 2 (Canvas Read): Success")
                        else:
                            tier_reports.append("Tier 2 (Canvas Read): Canvas returned empty data")
                    except Exception as canvas_exc:
                        logger.info(f"Canvas extraction failed for active element: {canvas_exc}")
                        tier_reports.append(f"Tier 2 (Canvas Read): Failed - {canvas_exc}")
            else:
                tier_reports.append("Tier 2 (Canvas Read): Skipped (not a JPEG)")

            # Tier 3: In-page fetch fallback
            if media_bytes is None:
                try:
                    js_fetch = """
                    async (url) => {
                        const response = await fetch(url);
                        if (!response.ok) {
                            throw new Error(`HTTP ${response.status}`);
                        }
                        const blob = await response.blob();
                        return new Promise((resolve, reject) => {
                            const reader = new FileReader();
                            reader.onloadend = () => {
                                const base64Str = reader.result.split(',')[1];
                                resolve(base64Str);
                            };
                            reader.onerror = () => reject(new Error('FileReader failed'));
                            reader.readAsDataURL(blob);
                        });
                    }
                    """
                    base64_data = page.evaluate(js_fetch, media_url)
                    media_bytes = base64.b64decode(base64_data)
                    logger.info(f"Retrieved {media_url[:100]}... via in-page fetch.")
                    tier_reports.append("Tier 3 (In-page Fetch): Success")
                except Exception as fetch_exc:
                    logger.info(f"In-page fetch failed for {media_url[:100]}...: {fetch_exc}")
                    tier_reports.append(f"Tier 3 (In-page Fetch): Failed - {fetch_exc}")

            # Tier 4: Background Context fetch fallback (last resort)
            if media_bytes is None:
                try:
                    response = context.request.get(
                        media_url,
                        headers={"Referer": "https://www.instagram.com/", "User-Agent": user_agent}
                    )
                    if response.status == 200:
                        media_bytes = response.body()
                        logger.info(f"Retrieved {media_url[:100]}... via Tier 4 context fetch.")
                        tier_reports.append("Tier 4 (Context Request): Success")
                    else:
                        tier_reports.append(f"Tier 4 (Context Request): HTTP {response.status}")
                except Exception as req_exc:
                    logger.info(f"Tier 4 context fetch failed for {media_url[:100]}...: {req_exc}")
                    tier_reports.append(f"Tier 4 (Context Request): Failed - {req_exc}")

            # Tier 5: Element screenshot fallback (absolute failsafe for images)
            if ext == "jpg":
                if media_bytes is None:
                    try:
                        media_bytes = active_elem.screenshot(type="jpeg", quality=95)
                        logger.info(f"Retrieved {media_url[:100]}... via Tier 5 element screenshot fallback.")
                        tier_reports.append("Tier 5 (Screenshot Failsafe): Success")
                    except Exception as ss_exc:
                        logger.info(f"Tier 5 element screenshot fallback failed: {ss_exc}")
                        tier_reports.append(f"Tier 5 (Screenshot Failsafe): Failed - {ss_exc}")
            else:
                tier_reports.append("Tier 5 (Screenshot Failsafe): Skipped (not a JPEG)")

            if media_bytes is None:
                reports_summary = " -> ".join(tier_reports)
                raise RuntimeError(f"All retrieval tiers exhausted. Details: {reports_summary}")

            media_items_data.append({"bytes": media_bytes, "ext": ext, "url": media_url})

            # Slide to the next media item if we are in a carousel
            if is_carousel:
                next_btn = _find_next_button(page, active_elem)
                moved = False
                if next_btn and next_btn.is_visible():
                    try:
                        logger.debug("Attempting to click Next button...")
                        next_btn.click(force=True)
                        page.wait_for_timeout(1500)
                        moved = True
                        logger.debug("Successfully clicked Next button.")
                    except Exception as click_err:
                        logger.debug(f"Failed to click Next button: {click_err}")
                else:
                    logger.debug(f"Next button visible check: {next_btn.is_visible() if next_btn else 'No button found'}")
                
                if not moved:
                    try:
                        logger.debug("Attempting keyboard ArrowRight fallback...")
                        # Focus on main presentation/media element to ensure keys target the post slider
                        media_container = page.query_selector("article, div._aagw, div[role='presentation']")
                        if media_container:
                            media_container.focus()
                        page.keyboard.press("ArrowRight")
                        page.wait_for_timeout(1500)
                        logger.debug("Keyboard ArrowRight event sent.")
                    except Exception as kb_err:
                        logger.debug(f"Keyboard fallback failed: {kb_err}")

        if not media_items_data:
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

        for idx, item in enumerate(media_items_data):
            if len(media_items_data) > 1:
                filename = f"{owner_username}_{timestamp_str}_{idx + 1}.{item['ext']}"
            else:
                filename = f"{owner_username}_{timestamp_str}.{item['ext']}"
            
            file_path = output_dir / filename
            with open(file_path, "wb") as f:
                f.write(item["bytes"])
            file_size_kb = len(item["bytes"]) / 1024
            log(f"Downloaded {file_path} ({file_size_kb:.1f} KB)")

        stats.download_count += 1
        downloaded_shortcodes.add(shortcode)
        save_downloaded_shortcode_db(db_path, shortcode)
        
        max_display = str(max_posts) if max_posts else "unlimited"
        archive_count = len(downloaded_shortcodes)
        total_avail = stats.total_posts_available if stats.total_posts_available else "unknown"
        
        log(
                f"Completed download of post {shortcode} with {len(media_items_data)} items "
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

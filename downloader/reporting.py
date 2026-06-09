"""Download session report generation."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from downloader.logging_utils import log


@dataclass
class DownloadStats:
    """Mutable counters collected during a download session."""

    total_posts_available: Optional[int] = None
    skip_count: int = 0
    download_count: int = 0
    download_errors: int = 0
    pruned_count: int = 0
    error_details: list[str] = field(default_factory=list)
    history_db_size_before: int = 0
    history_db_size_after: int = 0
    remaining_before: Optional[int] = None
    remaining_after: Optional[int] = None


def build_report(
    account_name: str,
    start_time: datetime,
    end_time: datetime,
    max_posts: Optional[int],
    tracking_file: Union[str, Path],
    stats: DownloadStats,
) -> str:
    """Build and log the final download session report.

    Args:
        account_name: Instagram account used for the download.
        start_time: Session start time.
        end_time: Session end time.
        max_posts: Optional session post limit.
        tracking_file: SQLite database path used for tracking.
        stats: Download counters and error details.

    Returns:
        Text report for console and Discord output.
    """

    duration = (end_time - start_time).total_seconds()
    minutes = int(duration // 60)
    seconds = int(duration % 60)
    report_lines: list[str] = []

    def log_report(message: str) -> None:
        log(message)
        report_lines.append(message)

    log_report("=" * 60)
    log_report("DOWNLOAD SESSION REPORT")
    log_report("=" * 60)
    log_report(f"  Account:              {account_name}")
    log_report(
        f"  Session started:      {start_time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    log_report(
        f"  Session ended:        {end_time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    log_report(f"  Total duration:       {minutes}m {seconds}s")
    log_report(f"  Total posts saved:    {stats.total_posts_available if stats.total_posts_available is not None else 'unknown'}")
    log_report(f"  Archive size before:  {stats.history_db_size_before} posts")
    log_report(f"  Archive size now:     {stats.history_db_size_after} posts")
    log_report(f"  Remaining before:     {stats.remaining_before if stats.remaining_before is not None else 'unknown'} posts")
    log_report(f"  Remaining to download:{stats.remaining_after if stats.remaining_after is not None else 'unknown'} posts")
    log_report(f"  Posts skipped:        {stats.skip_count} this session")
    log_report(f"  Posts downloaded:     {stats.download_count}")
    log_report(f"  Stale entries pruned: {stats.pruned_count}")
    log_report(f"  Errors encountered:   {stats.download_errors}")
    if stats.error_details:
        log_report("  Error details:")
        for detail in stats.error_details:
            log_report(f"    - {detail}")
    log_report(f"  Session limit set:    {max_posts if max_posts else 'unlimited'}")
    log_report(f"  Tracking file:        {tracking_file}")
    log_report("=" * 60)
    log_report("Session saved successfully.")
    log_report("Done!")
    return "\n".join(report_lines)

"""Instaloader version checking and upgrade support."""

import json
import subprocess
import sys
import urllib.error
import urllib.request

import instaloader

from downloader.logging_utils import log


def check_instaloader_version() -> None:
    """Check whether Instaloader is current and auto-upgrade if outdated.

    Raises:
        SystemExit: If an upgrade is needed but cannot be completed.
    """

    try:
        current_version = instaloader.__version__
        log("Checking Instaloader version...")

        req = urllib.request.Request(
            "https://pypi.org/pypi/instaloader/json",
            headers={"User-Agent": "Instaloader-Version-Checker"},
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data: dict[str, object] = json.loads(response.read().decode())
            info = data["info"]
            if not isinstance(info, dict):
                raise ValueError("Unexpected PyPI response format.")
            latest_version = str(info["version"])

        if current_version == latest_version:
            log(f"Instaloader is up to date (v{current_version})")
            return

        log("Outdated Instaloader detected!")
        log(f"   Current version: {current_version}")
        log(f"   Latest version:  {latest_version}")
        log("Attempting to upgrade automatically...")
        _upgrade_instaloader(latest_version)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        log("Could not reach PyPI to verify version. Continuing...")
    except Exception as exc:
        log(f"Version check failed: {exc}. Continuing...")


def _upgrade_instaloader(latest_version: str) -> None:
    """Upgrade Instaloader using pip.

    Args:
        latest_version: Latest version string reported by PyPI.

    Raises:
        SystemExit: Always exits after an attempted upgrade.
    """

    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "instaloader",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            log(f"Successfully upgraded to Instaloader v{latest_version}")
            log("Please restart the script to use the new version.")
            raise SystemExit(0)

        log("Auto-upgrade failed!")
        log(f"   pip output: {result.stderr.strip()}")
        log("Please upgrade manually by running:")
        log("   pip install --upgrade instaloader")
        raise SystemExit(1)
    except subprocess.TimeoutExpired as exc:
        log("Auto-upgrade timed out. Please upgrade manually:")
        log("   pip install --upgrade instaloader")
        raise SystemExit(1) from exc
    except SystemExit:
        raise
    except Exception as exc:
        log(f"Auto-upgrade failed: {exc}")
        log("Please upgrade manually by running:")
        log("   pip install --upgrade instaloader")
        raise SystemExit(1) from exc

"""Locate an existing Chromium for Playwright on this workstation."""

from pathlib import Path


def chromium_executable(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    browser_root = Path.home() / "AppData" / "Local" / "ms-playwright"
    installed = list(browser_root.glob("chromium-*/chrome-win64/chrome.exe"))
    if not installed:
        return None
    return str(max(installed, key=lambda path: path.stat().st_mtime))

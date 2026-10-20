"""Safe Asset Downloader with SSRF protection, size limits, and download telemetry."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import SSRFSecurityError, is_safe_remote_url

logger = get_logger("arya.utils.asset_downloader")

DEFAULT_MAX_IMAGE_BYTES = 50 * 1024 * 1024  # 50 MB
DEFAULT_MAX_VIDEO_BYTES = 200 * 1024 * 1024  # 200 MB


class AssetDownloadError(RuntimeError, ValueError):
    """Raised when an asset download fails or exceeds limits."""


async def download_media_asset(
    url: str,
    dest_dir: str | Path | None = None,
    max_bytes: int = DEFAULT_MAX_VIDEO_BYTES,
    timeout_seconds: float = 60.0,
    allowed_extensions: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov"),
) -> tuple[str, dict]:
    """Safely stream-download a remote media asset with SSRF checks and size limits.

    Returns:
        tuple of (local_file_path, telemetry_dict)
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string")

    # If it's already a local file
    if not url.startswith(("http://", "https://")):
        if os.path.exists(url):
            stat = os.stat(url)
            return url, {"bytes": stat.st_size, "download_seconds": 0.0, "content_type": "application/octet-stream"}
        raise RuntimeError(f"Local file does not exist: {url}")

    # SSRF Protection
    if not is_safe_remote_url(url):
        logger.warning("asset_download_ssrf_rejected", url=url)
        raise SSRFSecurityError(f"Insecure or internal network URL blocked by SSRF guard: {url}")

    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    if not ext or (allowed_extensions and ext not in allowed_extensions):
        ext = ".png" if "image" in url.lower() else ".mp4"

    target_dir = Path(dest_dir) if dest_dir else Path(tempfile.gettempdir())
    target_dir.mkdir(parents=True, exist_ok=True)

    fd, local_path = tempfile.mkstemp(
        suffix=ext,
        prefix="arya_media_",
        dir=str(target_dir),
    )

    start_time = time.perf_counter()
    total_bytes = 0
    content_type = ""
    download_success = False

    MAX_REDIRECTS = 3
    current_url = url
    visited_urls = {current_url}
    redirect_count = 0

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False) as client:
            while True:
                async with client.stream("GET", current_url) as response:
                    is_redirect = (300 <= getattr(response, "status_code", 200) < 400) or (
                        getattr(response, "is_redirect", False) is True
                    )
                    if is_redirect:
                        redirect_count += 1
                        if redirect_count > MAX_REDIRECTS:
                            raise SSRFSecurityError(
                                f"Too many redirects downloading asset (exceeded limit of {MAX_REDIRECTS}): {url}"
                            )
                        location = response.headers.get("Location")
                        if not location:
                            raise AssetDownloadError(f"Redirect missing Location header: {current_url}")
                        next_url = urljoin(current_url, location)
                        if next_url in visited_urls:
                            raise SSRFSecurityError(f"Redirect loop detected downloading asset: {next_url}")
                        if not is_safe_remote_url(next_url):
                            logger.warning(
                                "asset_download_redirect_ssrf_rejected",
                                redirect_url=next_url,
                                initial_url=url,
                            )
                            raise SSRFSecurityError(
                                f"Insecure or internal redirect URL blocked by SSRF guard: {next_url}"
                            )
                        visited_urls.add(next_url)
                        current_url = next_url
                        continue

                    if response.status_code == 401 or response.status_code == 403:
                        raise AssetDownloadError(f"Remote asset download unauthorized ({response.status_code}): {current_url}")
                    if response.status_code >= 400:
                        raise AssetDownloadError(f"Remote asset download failed ({response.status_code}): {current_url}")

                    content_type = response.headers.get("Content-Type", "")

                    with os.fdopen(fd, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            total_bytes += len(chunk)
                            if total_bytes > max_bytes:
                                raise AssetDownloadError(
                                    f"Downloaded asset exceeded maximum limit of {max_bytes} bytes: {current_url}"
                                )
                            f.write(chunk)

                    download_success = True
                    break

    except Exception:
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
            except OSError:
                pass
        raise

    if total_bytes == 0:
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
            except OSError:
                pass
        raise AssetDownloadError(f"Downloaded asset is empty (0 bytes): {url}")

    elapsed = time.perf_counter() - start_time
    telemetry = {
        "bytes": total_bytes,
        "download_seconds": round(elapsed, 3),
        "content_type": content_type,
        "url": url,
    }
    logger.info("asset_download_completed", local_path=local_path, **telemetry)
    return local_path, telemetry


async def download_remote_asset(
    url: str,
    dest_path: str | Path,
    max_bytes: int = DEFAULT_MAX_VIDEO_BYTES,
    timeout_seconds: float = 60.0,
) -> Path:
    """Download a remote asset directly to a destination path with SSRF check and size limits."""
    dest = Path(dest_path)
    if not is_safe_remote_url(url):
        logger.warning("asset_download_ssrf_rejected", url=url)
        raise SSRFSecurityError(f"Insecure or internal network URL blocked by SSRF guard: {url}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    total_bytes = 0

    MAX_REDIRECTS = 3
    current_url = url
    visited_urls = {current_url}
    redirect_count = 0

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False) as client:
            while True:
                async with client.stream("GET", current_url) as response:
                    is_redirect = (300 <= getattr(response, "status_code", 200) < 400) or (
                        getattr(response, "is_redirect", False) is True
                    )
                    if is_redirect:
                        redirect_count += 1
                        if redirect_count > MAX_REDIRECTS:
                            raise SSRFSecurityError(
                                f"Too many redirects downloading asset (exceeded limit of {MAX_REDIRECTS}): {url}"
                            )
                        location = response.headers.get("Location")
                        if not location:
                            raise AssetDownloadError(f"Redirect missing Location header: {current_url}")
                        next_url = urljoin(current_url, location)
                        if next_url in visited_urls:
                            raise SSRFSecurityError(f"Redirect loop detected downloading asset: {next_url}")
                        if not is_safe_remote_url(next_url):
                            logger.warning(
                                "asset_download_redirect_ssrf_rejected",
                                redirect_url=next_url,
                                initial_url=url,
                            )
                            raise SSRFSecurityError(
                                f"Insecure or internal redirect URL blocked by SSRF guard: {next_url}"
                            )
                        visited_urls.add(next_url)
                        current_url = next_url
                        continue

                    if response.status_code in (401, 403):
                        raise AssetDownloadError(f"Remote asset download unauthorized ({response.status_code}): {current_url}")
                    if response.status_code >= 400:
                        raise AssetDownloadError(f"Remote asset download failed ({response.status_code}): {current_url}")

                    content_len = response.headers.get("Content-Length")
                    if content_len and int(content_len) > max_bytes:
                        raise AssetDownloadError(f"Asset Content-Length ({content_len}) exceeds maximum allowed size ({max_bytes})")

                    with open(dest, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            total_bytes += len(chunk)
                            if total_bytes > max_bytes:
                                raise AssetDownloadError(f"Downloaded asset exceeds maximum allowed size ({max_bytes})")
                            f.write(chunk)
                    break
    except Exception:
        if dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        raise

    return dest

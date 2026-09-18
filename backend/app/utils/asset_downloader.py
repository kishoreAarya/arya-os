"""Safe Asset Downloader with SSRF protection, size limits, and download telemetry."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("arya.utils.asset_downloader")

DEFAULT_MAX_IMAGE_BYTES = 50 * 1024 * 1024  # 50 MB
DEFAULT_MAX_VIDEO_BYTES = 200 * 1024 * 1024  # 200 MB


class SSRFSecurityError(ValueError):
    """Raised when an asset URL targets private or restricted IP ranges."""


class AssetDownloadError(RuntimeError, ValueError):
    """Raised when an asset download fails or exceeds limits."""


def is_safe_remote_url(url: str) -> bool:
    """Validate that the remote asset URL is safe from SSRF attacks.
    
    Checks that scheme is http/https and resolved IP is not loopback, private,
    link-local, multicast, or reserved.
    """
    if not url or not isinstance(url, str):
        return False

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    lower_host = hostname.lower()
    if lower_host in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal"):
        return False

    # Check direct IP address
    try:
        ip = ipaddress.ip_address(lower_host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
        return True
    except ValueError:
        pass

    # Resolve domain to IP to verify it does not point to private/internal network
    try:
        resolved_ips = socket.getaddrinfo(hostname, None)
        for family, socktype, proto, canonname, sockaddr in resolved_ips:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
    except (socket.gaierror, ValueError):
        # If DNS cannot be resolved (e.g. offline testing/mocking)
        # reject un-dotted hostnames or local/internal suffixes
        if "." not in lower_host or lower_host.endswith((".local", ".internal", ".lan", ".localhost", ".test")):
            return False
        return True

    return True


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

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            async with client.stream("GET", url) as response:
                if response.status_code == 401 or response.status_code == 403:
                    raise AssetDownloadError(f"Remote asset download unauthorized ({response.status_code}): {url}")
                if response.status_code >= 400:
                    raise AssetDownloadError(f"Remote asset download failed ({response.status_code}): {url}")

                content_type = response.headers.get("Content-Type", "")

                with os.fdopen(fd, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        total_bytes += len(chunk)
                        if total_bytes > max_bytes:
                            raise AssetDownloadError(
                                f"Downloaded asset exceeded maximum limit of {max_bytes} bytes: {url}"
                            )
                        f.write(chunk)

                download_success = True

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

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            async with client.stream("GET", url) as response:
                if response.status_code in (401, 403):
                    raise AssetDownloadError(f"Remote asset download unauthorized ({response.status_code}): {url}")
                if response.status_code >= 400:
                    raise AssetDownloadError(f"Remote asset download failed ({response.status_code}): {url}")

                content_len = response.headers.get("Content-Length")
                if content_len and int(content_len) > max_bytes:
                    raise AssetDownloadError(f"Asset Content-Length ({content_len}) exceeds maximum allowed size ({max_bytes})")

                with open(dest, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        total_bytes += len(chunk)
                        if total_bytes > max_bytes:
                            raise AssetDownloadError(f"Downloaded asset exceeds maximum allowed size ({max_bytes})")
                        f.write(chunk)
    except Exception:
        if dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        raise

    return dest

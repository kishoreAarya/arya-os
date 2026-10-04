"""
Asset manager — converts remote storage URLs into local filesystem paths.

Adapters that expect local files (e.g. YouTubeAdapter via MediaFileUpload)
call this helper so they can consume remote assets without modification.
"""
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.utils.asset_downloader import (
    SSRFSecurityError,
    is_safe_remote_url,
    open_validated_stream,
)

logger = get_logger(__name__)


def is_safe_asset_url(url: str) -> bool:
    """Validate that the remote asset URL is safe from SSRF attacks.

    Delegates to the DNS-aware ``is_safe_remote_url`` guard in
    ``asset_downloader`` so hostname targets that resolve to private,
    loopback, link-local, reserved, or multicast ranges (including
    cloud metadata hosts) are rejected — not just literal IP hosts.
    Single validator, shared by every asset URL entry point.
    """
    return is_safe_remote_url(url)


async def ensure_local_asset(
    storage_path: str | None,
    *,
    timeout_seconds: float | None = None,
    max_bytes: int = 50 * 1024 * 1024,
) -> str | None:
    """Return a local filesystem path for the given storage path.

    * If ``storage_path`` is ``None``, return ``None``.
    * If it is already a valid local path, return it unchanged.
    * If it is an HTTP(S) URL, validate against SSRF, stream-download
      it up to ``max_bytes`` to a temporary file via bounded, revalidated
      redirects (Phase 47A), and return the path.
    * On download or write failure the partially-written file is deleted.
    * If the downloaded file is zero bytes it is deleted and a
      RuntimeError is raised.
    """
    if storage_path is None:
        return None

    # Already local — nothing to do.
    if not storage_path.startswith(("http://", "https://")):
        if os.path.exists(storage_path):
            return storage_path
        # Check if it resolves via StorageProvider (e.g. LocalStorageProvider base_path)
        try:
            from app.storage import get_storage_provider
            storage = get_storage_provider()
            resolved = storage.get_url(storage_path)
            if resolved and os.path.exists(resolved):
                return resolved
        except Exception:
            pass
        logger.warning("asset_local_path_missing", path=storage_path)
        raise RuntimeError(f"Local asset not found: {storage_path}")

    # Remote URL — SSRF validation
    if not is_safe_asset_url(storage_path):
        log = logger.bind(url=storage_path)
        log.warning("asset_url_rejected_ssrf")
        raise ValueError(f"Insecure or invalid remote asset URL: {storage_path}")

    # Stream-download to temp dir.
    parsed = urlparse(storage_path)
    original_name = Path(parsed.path).name or "asset"
    suffix = Path(original_name).suffix or ""
    temp_dir = tempfile.gettempdir()

    log = logger.bind(
        url=storage_path,
        original_name=original_name,
        temp_dir=temp_dir,
    )
    log.info("asset_download_started")

    settings = get_settings()
    local_path: str | None = None
    total_bytes = 0
    download_ok = False
    effective_timeout = timeout_seconds if timeout_seconds is not None else float(settings.api_timeout_seconds)

    try:
        # Phase 47A: never follow redirects automatically. Reuse the shared
        # bounded redirect walker so every redirect Location is revalidated
        # with the DNS-aware SSRF guard BEFORE it is requested; loops and
        # chains longer than the walker's hop limit are rejected there.
        async with httpx.AsyncClient(
            timeout=effective_timeout,
            follow_redirects=False,
        ) as client:
            response = await open_validated_stream(client, storage_path)
            try:
                response.raise_for_status()

                fd, local_path = tempfile.mkstemp(
                    suffix=suffix,
                    prefix="arya_asset_",
                    dir=temp_dir,
                )

                with os.fdopen(fd, "wb") as f:
                    async for chunk in response.aiter_bytes():
                        total_bytes += len(chunk)
                        if total_bytes > max_bytes:
                            raise RuntimeError(
                                f"Asset exceeds maximum allowed size of {max_bytes} bytes: {storage_path}"
                            )
                        f.write(chunk)

                download_ok = True
            finally:
                await response.aclose()

    except SSRFSecurityError:
        # Unsafe redirect destination (or initial URL race): re-raise the
        # distinct security signal unwrapped so callers can classify it.
        log.warning("asset_redirect_rejected_ssrf")
        raise
    except httpx.TimeoutException as exc:
        log.error("asset_download_timeout", error=str(exc))
        raise RuntimeError(f"Asset download timed out: {storage_path}") from exc
    except httpx.HTTPStatusError as exc:
        log.error(
            "asset_download_http_error",
            status_code=exc.response.status_code,
            error=str(exc),
        )
        raise RuntimeError(
            f"Asset download failed with status {exc.response.status_code}: {storage_path}"
        ) from exc
    except httpx.HTTPError as exc:
        log.error("asset_download_network_error", error=str(exc))
        raise RuntimeError(f"Asset download network error: {storage_path}") from exc
    except RuntimeError:
        # Re-raise our own zero-byte error without wrapping.
        raise
    except Exception as exc:
        log.error("asset_download_unexpected_error", error=str(exc))
        raise RuntimeError(f"Asset download failed: {storage_path}") from exc
    finally:
        if not download_ok and local_path is not None and os.path.exists(local_path):
            try:
                os.remove(local_path)
            except OSError:
                pass

    # Validate: zero-byte guard.
    if total_bytes == 0:
        log.error("asset_download_zero_bytes", local_path=local_path)
        if local_path is not None and os.path.exists(local_path):
            try:
                os.remove(local_path)
            except OSError:
                pass
        raise RuntimeError(f"Downloaded asset is zero bytes: {storage_path}")

    log.info(
        "asset_download_succeeded",
        local_path=local_path,
        size_bytes=total_bytes,
    )
    return local_path
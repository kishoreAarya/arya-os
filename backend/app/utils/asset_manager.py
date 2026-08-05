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

logger = get_logger(__name__)


async def ensure_local_asset(storage_path: str | None) -> str | None:
   """Return a local filesystem path for the given storage path.

   * If ``storage_path`` is ``None``, return ``None``.
   * If it is already a valid local path, return it unchanged.
   * If it is an HTTP(S) URL, stream-download it to a temporary file,
     preserve the original extension, and return the local path.
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
       logger.warning("asset_local_path_missing", path=storage_path)
       raise RuntimeError(f"Local asset not found: {storage_path}")

   # Remote URL — stream-download to temp dir.
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

   try:
      async with httpx.AsyncClient(
    timeout=settings.api_timeout_seconds,
    follow_redirects=True,
) as client:

        async with client.stream("GET", storage_path) as response:
            response.raise_for_status()

            fd, local_path = tempfile.mkstemp(
                suffix=suffix,
                prefix="arya_asset_",
                dir=temp_dir,
            )

            with os.fdopen(fd, "wb") as f:
                async for chunk in response.aiter_bytes():
                    f.write(chunk)
                    total_bytes += len(chunk)

            download_ok = True

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
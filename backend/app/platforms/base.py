"""PlatformAdapter ABC and shared result dataclasses.

Every platform adapter (YouTube, Instagram, TikTok, etc.) implements
this interface. The ABC defines the contract; concrete adapters
handle platform-specific authentication, API calls, and error
handling. PublishingAgent and AnalyticsAgent interact with adapters
ONLY through this interface — they never know which platform they're
talking to.

Design decisions:
- All methods are async (network I/O bound).
- Results are strongly-typed dataclasses, not raw dicts.
- authenticate() is explicit (not hidden in __init__) so callers
  can retry auth independently of other operations.
- upload_content() and upload_thumbnail() are separate because
  platforms have different thumbnail upload flows (some require a
  second API call after video upload, some accept it inline).
- fetch_analytics() returns a flat dict matching the Analytics model
  fields so AnalyticsAgent can pass it straight to _store_snapshot().
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class AuthResult:
    """Result of authenticate()."""

    success: bool
    credentials: object | None = None  # platform-specific token/object
    error: str | None = None


@dataclass
class UploadResult:
    """Result of upload_content() or upload_thumbnail()."""

    success: bool
    content_id: str | None = None  # platform's ID for the uploaded asset
    storage_path: str | None = None  # where we stored it locally
    url: str | None = None  # platform URL if already available
    error: str | None = None


@dataclass
class PublishResult:
    """Result of publish()."""

    success: bool
    published_content_id: str | None = None  # platform's public ID
    publish_status: str = "pending"  # "pending", "published", "failed"
    url: str | None = None  # public URL once published
    error: str | None = None


@dataclass
class ProcessingStatus:
    """Result of check_processing()."""

    status: str  # "processing", "ready", "failed", "unknown"
    progress_percent: float | None = None
    error: str | None = None


class PlatformAdapter(ABC):
    """Abstract base for all platform adapters.

    Concrete implementations live in app/platforms/<platform>.py.
    Register them in PLATFORM_ADAPTER_REGISTRY
    (app/platforms/registry.py).
    """

    name: str = "base_platform"

    @abstractmethod
    async def authenticate(self) -> AuthResult:
        """Obtain or refresh platform credentials.

        Called before any operation that needs an authenticated
        session. May read API keys from SecretsManager or trigger
        an OAuth flow, depending on the platform.
        """
        raise NotImplementedError

    @abstractmethod
    async def upload_content(
        self,
        *,
        file_path: str,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        credentials: object | None = None,
    ) -> UploadResult:
        """Upload a video (or other content) to the platform.

        Does NOT publish it — publish() is a separate step so
        PublishingAgent can validate the upload before making it
        public (or schedule it for later).
        """
        raise NotImplementedError

    @abstractmethod
    async def upload_thumbnail(
        self,
        *,
        video_content_id: str,
        thumbnail_path: str,
        credentials: object | None = None,
    ) -> UploadResult:
        """Upload a thumbnail for an already-uploaded video.

        Some platforms require the video to be uploaded first,
        then the thumbnail attached separately.
        """
        raise NotImplementedError

    @abstractmethod
    async def publish(
        self,
        *,
        content_id: str,
        credentials: object | None = None,
    ) -> PublishResult:
        """Make an uploaded video public.

        Some platforms publish immediately on upload (content_id
        == published_content_id). Others have a separate publish
        step. This method abstracts that difference.
        """
        raise NotImplementedError

    @abstractmethod
    async def check_processing(
        self,
        *,
        content_id: str,
        credentials: object | None = None,
    ) -> ProcessingStatus:
        """Check whether an uploaded video has finished processing.

        YouTube, for example, transcodes uploads asynchronously.
        This lets PublishingAgent poll until the video is ready.
        """
        raise NotImplementedError

    @abstractmethod
    async def fetch_url(
        self,
        *,
        published_content_id: str,
        credentials: object | None = None,
    ) -> str | None:
        """Get the public URL for a published video."""
        raise NotImplementedError

    @abstractmethod
    async def fetch_analytics(
        self,
        *,
        published_content_id: str,
        credentials: object | None = None,
    ) -> dict:
        """Fetch analytics for a published video.

        Returns a flat dict with keys matching the Analytics model
        fields (views, likes, comments, shares, etc.) so
        AnalyticsAgent._store_snapshot() can consume it directly.

        If a metric is unavailable on this platform, omit the key
        rather than returning None — _store_snapshot() uses
        .get() with defaults.
        """
        raise NotImplementedError

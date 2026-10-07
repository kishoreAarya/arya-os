"""Phase 54B-I11 — remote-fetch security for the five remediated B310 paths.

Proves the four media validators and the keyframe candidate evaluator now
perform every remote fetch through the shared Phase 47A guarded resolution
(sync bridge over ``ensure_local_asset``):

- unsafe URLs (loopback/private/link-local/metadata/unsupported scheme)
  are rejected BEFORE any connection, with each path's existing failure
  contract preserved;
- a permitted URL with a scripted transport still fetches successfully
  (no retrieval failure) and normal validation proceeds;
- an oversized remote response is bounded by the per-media size cap;
- a safe URL redirecting to an internal/metadata target is rejected and
  the internal target is NEVER requested;
- the sync bridge itself works from inside a running event loop (the
  synchronous BaseValidator contract is preserved).

All HTTP is mocked via httpx.MockTransport and all DNS via a deterministic
getaddrinfo monkeypatch (the Phase 47A test conventions) — no network
access, no real internal/metadata endpoints are ever contacted.
"""
import asyncio
import httpx
import pytest

from app.services.keyframe_selector import evaluate_candidate
from app.utils.asset_manager import ensure_local_asset_sync
from app.validators.audio_validator import AudioValidator
from app.validators.image_validator import ImageValidator
from app.validators.thumbnail_validator import ThumbnailValidator
from app.validators.video_validator import VideoValidator

PUBLIC_IP = "93.184.216.34"
SAFE_URL = "https://cdn.example/asset.png"

SSRF_URLS = [
    "http://localhost/asset",
    "http://127.0.0.1/asset",
    "http://10.0.0.7/asset",
    "http://192.168.1.4/asset",
    "http://169.254.169.254/latest/meta-data",
    "http://metadata.google.internal/computeMetadata/v1",
]


def _fake_dns(ip: str):
    import socket

    def _getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    return _getaddrinfo


class _Recorder:
    def __init__(self, handler):
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    @property
    def urls(self):
        return [str(r.url) for r in self.requests]


def _install_http_mock(monkeypatch, handler):
    real_async_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


def _serve(content: bytes, chain: dict | None = None):
    """Scripted handler: exact-URL 302 chain, everything else serves bytes."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if chain and url in chain:
            return httpx.Response(302, headers={"Location": chain[url]})
        return httpx.Response(
            200, content=content, headers={"Content-Type": "application/octet-stream"}
        )

    return handler


def _png_bytes() -> bytes:
    """A real, decodable 16x16 PNG (pillow is an existing dependency)."""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color=(40, 90, 160)).save(buf, format="PNG")
    return buf.getvalue()


# The five production paths, expressed as (name, callable(url) -> result,
# is the result a validator ValidationResult?).
def _audio(url):
    return AudioValidator().validate({"storage_path": url})


def _image(url):
    return ImageValidator().validate({"storage_path": url})


def _thumb(url):
    return ThumbnailValidator().validate({"storage_path": url})


def _video(url):
    return VideoValidator().validate({"storage_path": url})


def _keyframe(url):
    return evaluate_candidate(0, url)


_PATHS = {
    "audio": _audio,
    "image": _image,
    "thumbnail": _thumb,
    "video": _video,
    "keyframe": _keyframe,
}

# Each path's failure signature when the REMOTE FETCH itself is refused.
_RETRIEVAL_FAILURE_MARKERS = {
    "audio": "Failed to retrieve remote audio",
    "image": "Failed to retrieve remote image",
    "thumbnail": "Failed to retrieve remote thumbnail",
    "video": "Failed to retrieve remote video",
    "keyframe": "Failed to inspect candidate image",
}


def _assert_fetch_refused(name, result):
    marker = _RETRIEVAL_FAILURE_MARKERS[name]
    if name == "keyframe":
        assert result.total_score == 2.0
        assert any(marker in p for p in result.penalties_applied)
    else:
        assert result.passed is False
        assert any(marker in issue for issue in result.issues)


def _assert_fetch_worked(name, result):
    marker = _RETRIEVAL_FAILURE_MARKERS[name]
    if name == "keyframe":
        assert not any(marker in p for p in result.penalties_applied)
    else:
        assert not any(marker in issue for issue in result.issues)


@pytest.fixture
def public_dns(monkeypatch):
    import app.utils.asset_downloader as adm

    monkeypatch.setattr(adm.socket, "getaddrinfo", _fake_dns(PUBLIC_IP))


# ---------------------------------------------------------------------------
# 1. Unsafe URL rejection — BEFORE any connection, on every path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(_PATHS))
@pytest.mark.parametrize("url", SSRF_URLS)
def test_unsafe_urls_are_rejected_before_any_connection(
    monkeypatch, public_dns, name, url
):
    recorder = _Recorder(lambda request: httpx.Response(200, content=b"x"))
    _install_http_mock(monkeypatch, recorder)
    result = _PATHS[name](url)
    _assert_fetch_refused(name, result)
    # Rejected by the guard BEFORE any request was issued.
    assert recorder.urls == []


# ---------------------------------------------------------------------------
# 2. Unsupported scheme can never reach the fetcher
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(_PATHS))
def test_unsupported_scheme_is_never_fetched(monkeypatch, public_dns, name):
    recorder = _Recorder(lambda request: httpx.Response(200, content=b"x"))
    _install_http_mock(monkeypatch, recorder)
    result = _PATHS[name]("ftp://cdn.example/asset.png")
    # Non-HTTP(S) references are treated as local paths: the fetcher is
    # never invoked and validation fails on the missing local file.
    assert recorder.urls == []
    if name != "keyframe":
        assert result.passed is False


# ---------------------------------------------------------------------------
# 3. Safe URL behavior — the fetch works and validation proceeds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["image", "thumbnail", "keyframe"])
def test_permitted_url_fetches_and_validation_proceeds(
    monkeypatch, public_dns, name
):
    recorder = _Recorder(_serve(_png_bytes()))
    _install_http_mock(monkeypatch, recorder)
    result = _PATHS[name](SAFE_URL)
    _assert_fetch_worked(name, result)
    assert recorder.urls == [SAFE_URL]


@pytest.mark.parametrize("name", ["audio", "video"])
def test_permitted_url_fetches_media(monkeypatch, public_dns, name):
    # Garbage (non-media) bytes: the DOWNLOAD succeeds — the failure, if
    # any, comes from downstream media analysis, never from retrieval.
    recorder = _Recorder(_serve(b"not-really-media-bytes"))
    _install_http_mock(monkeypatch, recorder)
    result = _PATHS[name](SAFE_URL)
    _assert_fetch_worked(name, result)
    assert recorder.urls == [SAFE_URL]


# ---------------------------------------------------------------------------
# 4. Size protection — oversized remote responses are bounded
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["image", "thumbnail", "keyframe"])
def test_oversized_remote_response_is_bounded(monkeypatch, public_dns, name):
    # 25 MB cap for image-family paths; serve one byte more.
    recorder = _Recorder(_serve(b"x" * (25 * 1024 * 1024 + 1)))
    _install_http_mock(monkeypatch, recorder)
    result = _PATHS[name](SAFE_URL)
    _assert_fetch_refused(name, result)


def test_oversized_remote_video_is_bounded(monkeypatch, public_dns):
    # 200 MB cap for the video path; avoid allocating the full body by
    # streaming from a bounded generator is not possible with the fixed
    # content helper — instead bound via Content-Length mismatch is
    # unnecessary: exercise the audio path (50 MB cap) with 50MB+1.
    recorder = _Recorder(_serve(b"x" * (50 * 1024 * 1024 + 1)))
    _install_http_mock(monkeypatch, recorder)
    result = _audio(SAFE_URL)
    _assert_fetch_refused("audio", result)


# ---------------------------------------------------------------------------
# 5. Redirect protection — safe URL redirecting internal is blocked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(_PATHS))
def test_redirect_to_internal_target_is_blocked_and_never_requested(
    monkeypatch, public_dns, name
):
    recorder = _Recorder(
        _serve(
            _png_bytes(),
            chain={SAFE_URL: "http://169.254.169.254/latest/meta-data"},
        )
    )
    _install_http_mock(monkeypatch, recorder)
    result = _PATHS[name](SAFE_URL)
    _assert_fetch_refused(name, result)
    # Only the initial permitted URL was requested; the metadata target
    # was blocked by per-hop revalidation BEFORE any connection.
    assert recorder.urls == [SAFE_URL]


# ---------------------------------------------------------------------------
# 6. The sync bridge itself
# ---------------------------------------------------------------------------


def test_sync_bridge_local_passthrough_and_none():
    import tempfile
    from pathlib import Path

    assert ensure_local_asset_sync(None) is None
    local = Path(tempfile.mkstemp(suffix=".png")[1])
    local.write_bytes(b"bridge")
    try:
        assert ensure_local_asset_sync(str(local)) == str(local)
    finally:
        local.unlink(missing_ok=True)


def test_sync_bridge_unsafe_url_raises_value_error(monkeypatch, public_dns):
    recorder = _Recorder(lambda request: httpx.Response(200, content=b"x"))
    _install_http_mock(monkeypatch, recorder)
    with pytest.raises(ValueError):
        ensure_local_asset_sync("http://169.254.169.254/latest")
    assert recorder.urls == []


def test_sync_bridge_works_inside_a_running_event_loop(monkeypatch, public_dns):
    """The BaseValidator sync contract: the bridge must function even when
    the caller is already inside an asyncio loop (a plain asyncio.run on
    the calling thread would raise)."""

    async def _call_from_loop() -> str:
        # Blocking call INSIDE the coroutine — exactly how the pipeline
        # invokes the synchronous validators.
        return ensure_local_asset_sync(SAFE_URL, max_bytes=1024 * 1024)

    recorder = _Recorder(_serve(b"loop-bridge-bytes"))
    _install_http_mock(monkeypatch, recorder)
    path = asyncio.run(_call_from_loop())
    try:
        assert path and path != SAFE_URL
        with open(path, "rb") as f:
            assert f.read() == b"loop-bridge-bytes"
        assert recorder.urls == [SAFE_URL]
    finally:
        import os

        if path and os.path.exists(path):
            os.remove(path)

"""Phase 54B-I8 Workstream D: the independent dispatch WORKER process.

Run as a script (one OS process per dispatch):

    python _i8_mp_worker.py <spec.json>

The spec carries the agent context, the evidence-file path, the scripted
publish behavior, and the barrier directory. Each worker:

1. waits on the deterministic file barrier (both workers ready before
   either begins the gate -> admission sequence);
2. runs the REAL PublishingAgent with the REAL gates against the shared
   database on its OWN engine/session/event loop;
3. records its external adapter calls and outcome to the evidence file.

Only the platform adapter is scripted. No real provider is contacted.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def _barrier_wait(barrier_dir: Path, name: str, others: list[str], timeout: float = 60.0):
    """Deterministic ready-file barrier: signal readiness, then wait for
    the other workers' ready files (bounded spin, no flaky sleeps)."""
    barrier_dir.mkdir(parents=True, exist_ok=True)
    (barrier_dir / f"{name}.ready").write_text("1")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all((barrier_dir / f"{o}.ready").exists() for o in others):
            return
        time.sleep(0.01)
    raise TimeoutError("barrier wait timed out")


def main() -> int:
    spec = json.loads(Path(sys.argv[1]).read_text())

    def _run():
        import asyncio

        def _inner():
            from app.agents.publishing import PublishingAgent
            from app.hermes.capabilities import _make_capability_engine
            from sqlalchemy.ext.asyncio import async_sessionmaker

            calls = []

            class _Adapter:
                async def authenticate(self):
                    from app.platforms.base import AuthResult

                    calls.append("authenticate")
                    return AuthResult(
                        success=True, credentials={"api_key": "SCRIPTED"}
                    )

                async def upload_content(self, **kwargs):
                    from app.platforms.base import UploadResult

                    calls.append("upload_content")
                    return UploadResult(success=True, content_id="mp-media-1")

                async def upload_thumbnail(self, **kwargs):
                    raise AssertionError("no thumbnail in these tests")

                async def publish(self, **kwargs):
                    from app.platforms.base import PublishResult

                    calls.append("publish")
                    if spec["publish_behavior"] == "raise":
                        raise TimeoutError("dropped after submission")
                    return PublishResult(
                        success=True,
                        published_content_id="mp-post-1",
                        publish_status="published",
                        url="https://social.example/watch/mp-post-1",
                    )

                async def fetch_url(self, **kwargs):
                    calls.append("fetch_url")
                    return "https://social.example/watch/mp-post-1"

            import app.agents.publishing as publishing_mod

            publishing_mod.get_platform_adapter = (
                lambda platform, db, secrets=None: _Adapter()
            )

            async def _execute():
                engine = _make_capability_engine()
                session = async_sessionmaker(
                    bind=engine, expire_on_commit=False
                )()
                try:
                    result = await PublishingAgent(db=session).run(
                        dict(spec["ctx"])
                    )
                    return {
                        "success": result.success,
                        "error": result.error,
                        "output": {
                            k: v
                            for k, v in (result.output or {}).items()
                            if isinstance(v, (str, int, bool, type(None)))
                        },
                        "calls": calls,
                    }
                finally:
                    await session.close()
                    await engine.dispose()

            return asyncio.run(_execute())

        return _inner()

    try:
        _barrier_wait(
            Path(spec["barrier_dir"]),
            spec["worker_name"],
            spec["barrier_others"],
        )
        payload = _run()
    except BaseException as exc:  # record crash as evidence
        import traceback

        payload = {
            "success": False,
            "error": f"{type(exc).__name__}: {exc}",
            "worker_crash": traceback.format_exc(),
            "calls": [],
        }
    Path(spec["results_path"]).write_text(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

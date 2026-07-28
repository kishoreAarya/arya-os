"""
Shared fixtures for Workflow Run tests.

Integration tests need a real Postgres (UUID + native Enum columns
don't behave the same on SQLite), which is exactly what test.yml's CI
job already provisions as a service container and applies migrations
against. These fixtures assume that same setup locally: a reachable
DATABASE_URL with migrations already applied.

Uses an async httpx client (not FastAPI's sync TestClient) so that the
test body, its fixtures, and the app's own async DB engine all run on
the SAME event loop — asyncpg connections are loop-bound, and mixing
a sync TestClient's internal loop with async fixtures on another loop
causes cross-loop connection errors.
"""

import uuid
from collections.abc import AsyncGenerator

import httpx
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import AsyncSessionLocal, engine
from app.main import app
from app.models.core import Project


@pytest_asyncio.fixture(loop_scope="module", autouse=True)
async def _reset_engine_pool_for_this_module():
    """Test-infrastructure fix, unrelated to Issues 1/2: when the full
    suite runs in one pytest session, test_health.py's separate sync
    TestClient opens/closes its own event loop first. asyncpg
    connections are loop-bound, so any connection it left pooled on
    the shared module-level `engine` becomes invalid the moment that
    loop closes — surfacing as "Event loop is closed" the next time
    this module's (different, module-scoped) loop tries to reuse one.
    Disposing the pool once before this module's tests run forces
    fresh connections on the correct loop. Scoped to this module only;
    does not change any application code or the engine's configuration.
    """
    await engine.dispose()
    yield


# loop_scope="module": app/database/session.py's `engine` (and its
# asyncpg connection pool) is a module-level singleton created once at
# import time. asyncpg connections are bound to the event loop they
# were created on, so if each test function got its own fresh event
# loop (pytest-asyncio's default), connections pooled during test A
# become unusable once test A's loop closes, breaking test B. Scoping
# every fixture here to one shared loop for the whole test module
# keeps that pool valid for the module's entire run.
@pytest_asyncio.fixture(loop_scope="module")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture(loop_scope="module")
async def test_project(db_session: AsyncSession) -> AsyncGenerator[uuid.UUID, None]:
    """A real Project row so WorkflowRun's project_id FK is satisfiable.
    Deleted at teardown; cascade="all, delete-orphan" on
    Project.workflow_runs takes any WorkflowRun rows created during the
    test down with it.

    NOT part of the Issue 1/2 fix, purely test cleanup: SystemLog rows
    (written by pipeline_state.advance_stage()'s log_event() call, now
    exercised for the first time by these tests) have a FK to
    workflow_runs.id with no ON DELETE CASCADE configured at the model
    level. Deleting a WorkflowRun that has any SystemLog pointing at it
    fails with a Postgres FK violation unless those rows are cleared
    first. This is a pre-existing schema gap, out of scope for Issues
    1/2 (no schema changes permitted) — worked around here in test
    teardown only, not in application code.
    """
    project = Project(name=f"test-project-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    yield project.id

    from sqlalchemy import delete, select

    from app.models.core import WorkflowRun
    from app.models.system import SystemLog

    workflow_run_ids = (
        (
            await db_session.execute(
                select(WorkflowRun.id).where(WorkflowRun.project_id == project.id)
            )
        )
        .scalars()
        .all()
    )
    if workflow_run_ids:
        await db_session.execute(
            delete(SystemLog).where(SystemLog.workflow_run_id.in_(workflow_run_ids))
        )
        await db_session.commit()

    await db_session.delete(project)
    await db_session.commit()


@pytest_asyncio.fixture(loop_scope="module")
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac

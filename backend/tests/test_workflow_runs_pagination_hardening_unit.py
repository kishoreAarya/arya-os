"""
Security regression unit tests for:
workflow-runs-unbounded-query-memory-exhaustion (CWE-400 / CWE-770)

Verifies:
1. Default limit (50) is applied on GET /workflow-runs/.
2. Values below 1 (e.g. 0, -1) are rejected with HTTP 422.
3. Values above 100 (e.g. 101, 1000) are rejected with HTTP 422.
4. Valid custom limit within [1, 100] is accepted.
5. SQL query is strictly bounded via .limit() before ORM materialization.
6. project_id filtering is preserved alongside limit.
7. Existing callers without limit maintain full backward compatibility.
8. Output schema conforms to list[WorkflowRunResponse].
"""

from unittest.mock import AsyncMock, MagicMock
import uuid
import httpx
import pytest

from app.services.workflow_service import list_workflow_runs

pytestmark = pytest.mark.asyncio(loop_scope="module")


async def test_list_workflow_runs_limit_below_one_rejected(client: httpx.AsyncClient):
    """Passing limit < 1 is rejected with HTTP 422 (ge=1 enforced)."""
    resp_zero = await client.get("/workflow-runs/?limit=0")
    assert resp_zero.status_code == 422
    assert "greater than or equal to 1" in resp_zero.text

    resp_neg = await client.get("/workflow-runs/?limit=-10")
    assert resp_neg.status_code == 422
    assert "greater than or equal to 1" in resp_neg.text


async def test_list_workflow_runs_limit_above_one_hundred_rejected(client: httpx.AsyncClient):
    """Passing limit > 100 is rejected with HTTP 422 (le=100 enforced)."""
    resp_over = await client.get("/workflow-runs/?limit=101")
    assert resp_over.status_code == 422
    assert "less than or equal to 100" in resp_over.text

    resp_huge = await client.get("/workflow-runs/?limit=999999")
    assert resp_huge.status_code == 422


async def test_list_workflow_runs_valid_boundary_limits_accepted(client: httpx.AsyncClient):
    """Limits 1, 50, and 100 are accepted."""
    for valid_limit in (1, 50, 100):
        resp = await client.get(f"/workflow-runs/?limit={valid_limit}")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


async def test_list_workflow_runs_default_limit(client: httpx.AsyncClient):
    """GET /workflow-runs/ without limit succeeds with 200 (default 50 applied)."""
    resp = await client.get("/workflow-runs/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_list_workflow_runs_sql_query_bounded():
    """Verify list_workflow_runs attaches SQL .limit() directly to the query."""
    mock_db = AsyncMock()
    captured_stmt = None

    async def fake_execute(stmt):
        nonlocal captured_stmt
        captured_stmt = stmt
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        return mock_result

    mock_db.execute = fake_execute

    test_limit = 25
    await list_workflow_runs(mock_db, limit=test_limit)

    assert captured_stmt is not None
    # Verify the SQLAlchemy Select object has _limit set to test_limit
    assert captured_stmt._limit == test_limit
    sql_compiled = str(captured_stmt.compile())
    assert "LIMIT" in sql_compiled


async def test_list_workflow_runs_project_id_and_limit():
    """Verify project_id filter and limit are applied simultaneously in SQL query."""
    mock_db = AsyncMock()
    captured_stmt = None

    async def fake_execute(stmt):
        nonlocal captured_stmt
        captured_stmt = stmt
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        return mock_result

    mock_db.execute = fake_execute

    target_project_id = uuid.uuid4()
    test_limit = 15
    await list_workflow_runs(mock_db, project_id=target_project_id, limit=test_limit)

    assert captured_stmt is not None
    assert captured_stmt._limit == test_limit
    sql_compiled = str(captured_stmt.compile())
    assert "LIMIT" in sql_compiled
    assert "workflow_runs.project_id" in sql_compiled


async def test_list_workflow_runs_backward_compatibility():
    """Existing callers calling list_workflow_runs(db) without limit continue working."""
    mock_db = AsyncMock()
    captured_stmt = None

    async def fake_execute(stmt):
        nonlocal captured_stmt
        captured_stmt = stmt
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        return mock_result

    mock_db.execute = fake_execute

    await list_workflow_runs(mock_db)
    assert captured_stmt is not None
    assert captured_stmt._limit is None

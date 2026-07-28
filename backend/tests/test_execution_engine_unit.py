"""
Unit tests for ExecutionEngine — Milestone 2 (Provider Execution
Integration) scope: verifies the public execute() interface, provider
success/failure paths, ExecutionResult field population (including
the still-unpopulated `model` field — see execution_engine.py's module
docstring for why), and that the expected log calls actually happen.
_validate/_persist remain no-ops this milestone (tested to confirm
they're genuinely no-ops, not silently half-implemented).

No real provider or database call — the provider call is a plain
async callable, same as ProviderRouter's own tests.
"""

from unittest.mock import AsyncMock, patch

import pytest
from app.providers.capabilities import Capability, providers_for
from app.services.execution_engine import (
    ExecutionContext,
    ExecutionEngine,
    ExecutionResult,
)


@pytest.mark.asyncio
async def test_execute_success_path_returns_populated_result():
    engine = ExecutionEngine(db=AsyncMock())

    async def fake_call(provider):
        return "generated text", 0.002

    result = await engine.execute(
        capability=Capability.TEXT_GENERATION,
        call=fake_call,
        workflow_run_id=None,
        stage="script_generation",
    )

    assert isinstance(result, ExecutionResult)
    assert result.success is True
    assert result.output == "generated text"
    assert result.provider is not None
    assert result.cost_usd == 0.002
    assert result.elapsed_time >= 0
    assert result.error is None


@pytest.mark.asyncio
async def test_execute_model_field_is_none_pending_router_result_support():
    """Per Milestone 2's spec, ExecutionResult has a `model` field —
    but neither RouterResult nor the provider adapters carry which
    model was actually used yet. This must stay None, not a fabricated
    value, until that's added to the Provider Router's own contract."""
    engine = ExecutionEngine(db=AsyncMock())

    async def fake_call(provider):
        return "text", 0.001

    result = await engine.execute(
        capability=Capability.TEXT_GENERATION,
        call=fake_call,
        workflow_run_id=None,
        stage="script_generation",
    )

    assert result.model is None


@pytest.mark.asyncio
async def test_execute_failure_path_returns_clean_error_not_an_exception():
    engine = ExecutionEngine(db=AsyncMock())

    async def always_fails(provider):
        raise RuntimeError("simulated provider outage")

    result = await engine.execute(
        capability=Capability.TEXT_GENERATION,
        call=always_fails,
        workflow_run_id=None,
        stage="script_generation",
    )

    assert result.success is False
    assert result.error is not None
    assert result.output is None


@pytest.mark.asyncio
async def test_execute_does_not_retry_on_failure():
    """Milestone 2 explicitly has no retry loop — a failing call
    should be attempted exactly once per candidate provider (via
    call_with_fallback's existing provider-to-provider fallback, not a
    NEW retry loop), then return failure immediately."""
    engine = ExecutionEngine(db=AsyncMock())
    call_count = 0

    async def counting_failure(provider):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("fails every time")

    result = await engine.execute(
        capability=Capability.TEXT_GENERATION,
        call=counting_failure,
        workflow_run_id=None,
        stage="script_generation",
    )

    assert result.success is False
    expected_attempts = len(providers_for(Capability.TEXT_GENERATION))
    assert call_count == expected_attempts


@pytest.mark.asyncio
async def test_context_reflects_provider_and_cost_on_success():
    engine = ExecutionEngine(db=AsyncMock())

    async def fake_call(provider):
        return "output", 0.01

    result = await engine.execute(
        capability=Capability.TEXT_GENERATION,
        call=fake_call,
        workflow_run_id=None,
        stage="script_generation",
        running_cost_usd=0.05,
    )

    ctx = result.context
    assert isinstance(ctx, ExecutionContext)
    assert ctx.stage == "script_generation"
    assert ctx.provider == result.provider
    assert ctx.accumulated_cost == pytest.approx(0.06)


@pytest.mark.asyncio
async def test_validate_is_a_noop_in_milestone_2():
    engine = ExecutionEngine(db=AsyncMock())
    assert await engine._validate("anything") is None


@pytest.mark.asyncio
async def test_persist_is_a_noop_in_milestone_2():
    engine = ExecutionEngine(db=AsyncMock())
    ctx = ExecutionContext(workflow_run_id=None, stage="x")

    class _FakeRouterResult:
        output = "x"
        provider_used = "x"
        attempts: list = []  # noqa: RUF012 — plain test double, not a real dataclass
        cost_usd = 0.0
        duration_seconds = 0.0

    assert await engine._persist(ctx, _FakeRouterResult()) is None


# --- Logging path (Milestone 2 requirement 4) -----------------------------


@pytest.mark.asyncio
async def test_execute_logs_start_event():
    engine = ExecutionEngine(db=AsyncMock())

    async def fake_call(provider):
        return "text", 0.001

    with patch(
        "app.services.execution_engine.log_event", new=AsyncMock()
    ) as mock_log_event:
        await engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=fake_call,
            workflow_run_id=None,
            stage="script_generation",
        )

    start_calls = [
        c
        for c in mock_log_event.call_args_list
        if "starting" in c.kwargs.get("message", "")
    ]
    assert len(start_calls) == 1


@pytest.mark.asyncio
async def test_execute_logs_success_on_success():
    """This is the log line Milestone 1 was missing — Milestone 2
    adds it explicitly."""
    engine = ExecutionEngine(db=AsyncMock())

    async def fake_call(provider):
        return "text", 0.001

    with patch("app.services.execution_engine.logger") as mock_logger:
        result = await engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=fake_call,
            workflow_run_id=None,
            stage="script_generation",
        )

    assert result.success is True
    mock_logger.info.assert_called_once()
    call_args = mock_logger.info.call_args
    assert call_args.args[0] == "execution_engine_call_succeeded"
    assert call_args.kwargs["provider"] == result.provider
    mock_logger.error.assert_not_called()


@pytest.mark.asyncio
async def test_execute_logs_failure_on_provider_exception():
    engine = ExecutionEngine(db=AsyncMock())

    async def always_fails(provider):
        raise RuntimeError("down")

    with patch("app.services.execution_engine.logger") as mock_logger:
        result = await engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=always_fails,
            workflow_run_id=None,
            stage="script_generation",
        )

    assert result.success is False
    mock_logger.error.assert_called_once()
    assert mock_logger.error.call_args.args[0] == "execution_engine_call_failed"
    mock_logger.info.assert_not_called()

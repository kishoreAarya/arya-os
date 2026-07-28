"""
Unit tests for ExecutionEngine — Milestone 1 scope only: verifies the
public execute() interface, the one-call-no-retry path, and that
_validate/_persist are genuinely no-ops this milestone (not silently
half-implemented). No real provider or database call — the provider
call is a plain async callable, same as ProviderRouter's own tests.
"""

from unittest.mock import AsyncMock

import pytest
from app.providers.capabilities import Capability
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
    assert result.provider_used is not None
    assert result.cost_usd == 0.002
    assert result.duration_seconds >= 0
    assert result.error is None


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
    """Milestone 1 explicitly has no retry loop — a failing call
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
    # Called once per candidate TEXT_GENERATION provider in the
    # registry, NOT repeated after all candidates are exhausted —
    # there is no re-attempt loop around the whole capability.
    from app.providers.capabilities import providers_for

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
    assert ctx.provider == result.provider_used
    assert ctx.accumulated_cost == pytest.approx(0.06)


@pytest.mark.asyncio
async def test_validate_is_a_noop_in_milestone_1():
    engine = ExecutionEngine(db=AsyncMock())
    assert await engine._validate("anything") is None


@pytest.mark.asyncio
async def test_persist_is_a_noop_in_milestone_1():
    engine = ExecutionEngine(db=AsyncMock())
    ctx = ExecutionContext(workflow_run_id=None, stage="x")

    class _FakeRouterResult:
        output = "x"
        provider_used = "x"
        attempts: list = []  # noqa: RUF012 — plain test double, not a real dataclass
        cost_usd = 0.0
        duration_seconds = 0.0

    # Must not raise, must not touch the (mocked) db.
    assert await engine._persist(ctx, _FakeRouterResult()) is None


@pytest.mark.asyncio
async def test_execute_raises_all_providers_failed_is_caught_cleanly():
    """AllProvidersFailedError (raised by call_with_fallback itself,
    not a new error type) must come back as a clean ExecutionResult,
    same as any other provider-layer failure."""
    engine = ExecutionEngine(db=AsyncMock())

    async def always_fails(provider):
        raise RuntimeError("down")

    result = await engine.execute(
        capability=Capability.TEXT_GENERATION,
        call=always_fails,
        workflow_run_id=None,
        stage="script_generation",
    )

    assert result.success is False
    assert "failed" in result.error.lower() or "down" in result.error.lower()

"""
Unit tests for ExecutionEngine — Milestone 3 (Validation Integration)
scope: extends Milestone 1/2 coverage (provider success/failure,
ExecutionResult field population, logging) with real validator
discovery/execution/logging, now that `_validate()` is implemented for
real instead of being a no-op stub.

No real provider or database call — the provider call is a plain
async callable, same as ProviderRouter's own tests. Validators are the
REAL registered stub validators (app/validators/__init__.py) — not
mocked, since requirement 1/2 forbid creating or modifying validators,
and testing against the real (if stub) implementations is what
actually proves the wiring works.
"""

from unittest.mock import AsyncMock, patch

import pytest
from app.providers.capabilities import Capability, providers_for
from app.services.execution_engine import (
    ExecutionContext,
    ExecutionEngine,
    ExecutionResult,
    UnknownValidatorError,
)
from app.validators import VALIDATOR_REGISTRY


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
    """Per the spec, ExecutionResult has a `model` field — but neither
    RouterResult nor the provider adapters carry which model was
    actually used yet. This must stay None, not a fabricated value,
    until that's added to the Provider Router's own contract."""
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
    """No retry loop anywhere — a failing call should be attempted
    exactly once per candidate provider (via call_with_fallback's
    existing provider-to-provider fallback, not a NEW retry loop),
    then return failure immediately."""
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
async def test_persist_is_a_noop_in_milestone_3():
    engine = ExecutionEngine(db=AsyncMock())
    ctx = ExecutionContext(workflow_run_id=None, stage="x")

    class _FakeRouterResult:
        output = "x"
        provider_used = "x"
        attempts: list = []  # noqa: RUF012 — plain test double, not a real dataclass
        cost_usd = 0.0
        duration_seconds = 0.0

    assert await engine._persist(ctx, _FakeRouterResult()) is None


# --- Logging path (Milestone 2 requirement, unchanged) --------------------


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


# --- Validation integration (Milestone 3) ---------------------------------


@pytest.mark.asyncio
async def test_execute_with_passing_validator_succeeds():
    """StoryValidator (a real registered stub, not mocked) passes for
    content longer than 50 characters — see script_story_validator.py."""
    engine = ExecutionEngine(db=AsyncMock())
    long_content = "x" * 60

    async def fake_call(provider):
        return {"content": long_content}, 0.001

    result = await engine.execute(
        capability=Capability.TEXT_GENERATION,
        call=fake_call,
        workflow_run_id=None,
        stage="script_generation",
        validator_name="story",
    )

    assert result.success is True
    assert result.context.validation_result is not None
    assert result.context.validation_result.passed is True


@pytest.mark.asyncio
async def test_execute_with_failing_validator_marks_result_failed():
    """StoryValidator fails for content under 50 characters — requirement
    7: success=False, validation result attached, returned immediately."""
    engine = ExecutionEngine(db=AsyncMock())
    short_content = "too short"

    async def fake_call(provider):
        return {"content": short_content}, 0.001

    result = await engine.execute(
        capability=Capability.TEXT_GENERATION,
        call=fake_call,
        workflow_run_id=None,
        stage="script_generation",
        validator_name="story",
    )

    assert result.success is False
    assert result.context.validation_result is not None
    assert result.context.validation_result.passed is False
    assert result.error is not None
    assert "Validation" in result.error


@pytest.mark.asyncio
async def test_validator_lookup_finds_real_registry_entry():
    """Direct test of discovery: _validate() must look the validator up
    in the actual VALIDATOR_REGISTRY, not a private copy of it — proven
    by confirming the result matches calling the registered validator
    directly for the same input."""
    engine = ExecutionEngine(db=AsyncMock())
    artifact = {"content": "x" * 60}

    expected = VALIDATOR_REGISTRY["story"].validate(artifact)
    result = await engine._validate("story", artifact)

    assert result.passed == expected.passed
    assert result.score == expected.score


@pytest.mark.asyncio
async def test_execute_with_unknown_validator_name_returns_clean_failure():
    """Requirement: unknown validator must be a clean ExecutionResult
    failure, not an unhandled exception escaping execute()."""
    engine = ExecutionEngine(db=AsyncMock())

    async def fake_call(provider):
        return {"content": "x" * 60}, 0.001

    result = await engine.execute(
        capability=Capability.TEXT_GENERATION,
        call=fake_call,
        workflow_run_id=None,
        stage="script_generation",
        validator_name="not_a_real_validator",
    )

    assert result.success is False
    assert "Unknown validator" in result.error


@pytest.mark.asyncio
async def test_validate_raises_unknown_validator_error_directly():
    engine = ExecutionEngine(db=AsyncMock())

    with pytest.raises(UnknownValidatorError):
        await engine._validate("not_a_real_validator", {"content": "x"})


@pytest.mark.asyncio
async def test_provider_failure_skips_validation_entirely():
    """Requirement: validation must happen only after successful
    provider execution — a failing provider call must never reach
    validator lookup/execution at all."""
    engine = ExecutionEngine(db=AsyncMock())

    async def always_fails(provider):
        raise RuntimeError("provider down")

    with patch.object(ExecutionEngine, "_validate", new=AsyncMock()) as mock_validate:
        result = await engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=always_fails,
            workflow_run_id=None,
            stage="script_generation",
            validator_name="story",
        )

    assert result.success is False
    mock_validate.assert_not_called()


@pytest.mark.asyncio
async def test_execute_logs_validation_start_and_success():
    engine = ExecutionEngine(db=AsyncMock())

    async def fake_call(provider):
        return {"content": "x" * 60}, 0.001

    with patch("app.services.execution_engine.logger") as mock_logger:
        result = await engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=fake_call,
            workflow_run_id=None,
            stage="script_generation",
            validator_name="story",
        )

    assert result.success is True
    logged_events = [c.args[0] for c in mock_logger.info.call_args_list]
    assert "execution_engine_validation_started" in logged_events
    assert "execution_engine_validation_succeeded" in logged_events


@pytest.mark.asyncio
async def test_execute_logs_validation_failure():
    engine = ExecutionEngine(db=AsyncMock())

    async def fake_call(provider):
        return {"content": "too short"}, 0.001

    with patch("app.services.execution_engine.logger") as mock_logger:
        result = await engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=fake_call,
            workflow_run_id=None,
            stage="script_generation",
            validator_name="story",
        )

    assert result.success is False
    logged_start = [c.args[0] for c in mock_logger.info.call_args_list]
    logged_warn = [c.args[0] for c in mock_logger.warning.call_args_list]
    assert "execution_engine_validation_started" in logged_start
    assert "execution_engine_validation_failed" in logged_warn


@pytest.mark.asyncio
async def test_execute_skips_validation_when_validator_name_is_none():
    """Backward compatibility with Milestone 2: no validator_name means
    no validation, exactly like before this milestone existed."""
    engine = ExecutionEngine(db=AsyncMock())

    async def fake_call(provider):
        return "unvalidated output", 0.001

    result = await engine.execute(
        capability=Capability.TEXT_GENERATION,
        call=fake_call,
        workflow_run_id=None,
        stage="script_generation",
    )

    assert result.success is True
    assert result.context.validation_result is None

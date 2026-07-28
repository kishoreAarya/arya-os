"""
Unit tests for ExecutionEngine — Milestone 4 (Retry Integration)
scope: extends Milestone 1-3 coverage (provider success/failure,
validation, logging, field population) with retry-on-transient-failure,
exponential backoff, attempt tracking, and the one non-transient case
(CostLimitExceededError) that must never be retried.

`asyncio.sleep` is patched in every retry test so backoff delays don't
actually slow the test suite down — the delay VALUES are still
asserted against, just not actually waited out.

No real provider or database call — the provider call is a plain
async callable, same as ProviderRouter's own tests. Validators are the
REAL registered stub validators (app/validators/__init__.py) — not
mocked, since prior milestones forbid creating or modifying validators,
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
async def test_execute_retries_transient_failure_across_full_attempt_budget():
    """Was 'does not retry' pre-Milestone-4 — now retries ARE
    implemented, so a persistently-failing transient error should be
    attempted (1 + max_retry_attempts) times, each attempt itself
    trying every candidate provider once (call_with_fallback's
    pre-existing, unchanged per-provider fallback)."""
    from app.core.config import get_settings

    engine = ExecutionEngine(db=AsyncMock())
    call_count = 0

    async def counting_failure(provider):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("fails every time")

    with patch("app.services.execution_engine.asyncio.sleep", new=AsyncMock()):
        result = await engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=counting_failure,
            workflow_run_id=None,
            stage="script_generation",
        )

    assert result.success is False
    max_retries = get_settings().max_retry_attempts
    providers_per_attempt = len(providers_for(Capability.TEXT_GENERATION))
    assert call_count == providers_per_attempt * (1 + max_retries)
    assert result.attempts == 1 + max_retries


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
    """Persistent RuntimeError is transient -> retried to exhaustion,
    so logger.error is now called more than once (once per exhausted
    retry chain internally, once for the final call-failed summary) —
    the LAST error call is what execute()'s own docstring promises."""
    engine = ExecutionEngine(db=AsyncMock())

    async def always_fails(provider):
        raise RuntimeError("down")

    with (
        patch("app.services.execution_engine.asyncio.sleep", new=AsyncMock()),
        patch("app.services.execution_engine.logger") as mock_logger,
    ):
        result = await engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=always_fails,
            workflow_run_id=None,
            stage="script_generation",
        )

    assert result.success is False
    assert mock_logger.error.call_args.args[0] == "execution_engine_call_failed"
    assert mock_logger.warning.call_count > 0  # at least one retry attempt was logged
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
    provider execution — a failing provider call, even after being
    retried to exhaustion, must never reach validator lookup/execution
    at all."""
    engine = ExecutionEngine(db=AsyncMock())

    async def always_fails(provider):
        raise RuntimeError("provider down")

    with (
        patch("app.services.execution_engine.asyncio.sleep", new=AsyncMock()),
        patch.object(ExecutionEngine, "_validate", new=AsyncMock()) as mock_validate,
    ):
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


# --- Retry integration (Milestone 4) --------------------------------------


@pytest.mark.asyncio
async def test_execute_succeeds_after_transient_failures_then_recovery():
    """call_with_fallback already tries every candidate provider
    within a SINGLE retry-wrapper attempt (pre-existing, unchanged
    behavior) — so to actually exercise a second retry-wrapper
    attempt, every provider in the first attempt must fail, not just
    one. This fails all providers for one full attempt, then
    succeeds on the first provider tried in the second attempt."""
    engine = ExecutionEngine(db=AsyncMock())
    providers_per_attempt = len(providers_for(Capability.TEXT_GENERATION))
    call_count = 0

    async def flaky_call(provider):
        nonlocal call_count
        call_count += 1
        if call_count <= providers_per_attempt:
            raise RuntimeError("transient blip")
        return "recovered output", 0.002

    with patch("app.services.execution_engine.asyncio.sleep", new=AsyncMock()):
        result = await engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=flaky_call,
            workflow_run_id=None,
            stage="script_generation",
        )

    assert result.success is True
    assert result.output == "recovered output"
    assert result.attempts == 2
    assert result.context.attempt_number == 2


@pytest.mark.asyncio
async def test_execute_fails_after_exhausting_max_retry_attempts():
    """Default Settings.max_retry_attempts=3 -> 1 initial + 3 retries =
    4 total attempts before giving up."""
    from app.core.config import get_settings

    engine = ExecutionEngine(db=AsyncMock())
    call_count = 0

    async def always_fails(provider):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("persistent failure")

    with patch("app.services.execution_engine.asyncio.sleep", new=AsyncMock()):
        result = await engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=always_fails,
            workflow_run_id=None,
            stage="script_generation",
        )

    max_retries = get_settings().max_retry_attempts
    assert result.success is False
    assert result.attempts == 1 + max_retries
    assert result.context.attempt_number == 1 + max_retries
    # call_with_fallback wraps the underlying RuntimeError into its own
    # AllProvidersFailedError message (provider names, not the
    # original exception text) — that's pre-existing router.py
    # behavior, unchanged by this milestone.
    assert "failed or were skipped" in result.error


@pytest.mark.asyncio
async def test_cost_limit_exceeded_is_never_retried():
    """CostLimitExceededError is the one explicitly non-transient
    case — it must fail on the very first attempt, no retries, no
    backoff sleep at all."""
    engine = ExecutionEngine(db=AsyncMock())
    call_count = 0

    async def call_that_would_hit_cost_ceiling(provider):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("should never be called")

    with patch(
        "app.services.execution_engine.asyncio.sleep", new=AsyncMock()
    ) as mock_sleep:
        result = await engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=call_that_would_hit_cost_ceiling,
            workflow_run_id=None,
            stage="script_generation",
            # Setting running_cost_usd above the ceiling makes
            # call_with_fallback raise CostLimitExceededError before
            # ever invoking `call` at all.
            running_cost_usd=999_999.0,
        )

    assert result.success is False
    assert result.attempts == 1
    assert call_count == 0  # the provider callable itself was never reached
    mock_sleep.assert_not_called()  # never backed off, because it never retried


@pytest.mark.asyncio
async def test_retry_uses_exponential_backoff():
    """0.1s, 0.2s, 0.4s — doubling each retry, per the module's
    documented _RETRY_BACKOFF_BASE_SECONDS formula."""
    engine = ExecutionEngine(db=AsyncMock())

    async def always_fails(provider):
        raise RuntimeError("down")

    with patch(
        "app.services.execution_engine.asyncio.sleep", new=AsyncMock()
    ) as mock_sleep:
        await engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=always_fails,
            workflow_run_id=None,
            stage="script_generation",
        )

    sleep_durations = [c.args[0] for c in mock_sleep.call_args_list]
    assert sleep_durations == [0.1, 0.2, 0.4]


@pytest.mark.asyncio
async def test_every_retry_attempt_is_logged():
    engine = ExecutionEngine(db=AsyncMock())

    async def always_fails(provider):
        raise RuntimeError("down")

    with (
        patch("app.services.execution_engine.asyncio.sleep", new=AsyncMock()),
        patch("app.services.execution_engine.logger") as mock_logger,
    ):
        await engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=always_fails,
            workflow_run_id=None,
            stage="script_generation",
        )

    retry_log_calls = [
        c
        for c in mock_logger.warning.call_args_list
        if c.args[0] == "execution_engine_retry_attempt"
    ]
    # 3 retries logged (the 4th, final failed attempt has nothing left
    # to retry into, so it's logged as an error, not another retry warning).
    assert len(retry_log_calls) == 3
    attempt_numbers = [c.kwargs["attempt"] for c in retry_log_calls]
    assert attempt_numbers == [1, 2, 3]


@pytest.mark.asyncio
async def test_validation_runs_after_provider_succeeds_following_retries():
    """Validation must still only run after a genuinely successful
    provider call — including one that only succeeded after a
    retry-wrapper-level retry (every provider failing once, then
    succeeding on the first provider of the second attempt)."""
    engine = ExecutionEngine(db=AsyncMock())
    providers_per_attempt = len(providers_for(Capability.TEXT_GENERATION))
    call_count = 0

    async def flaky_then_valid(provider):
        nonlocal call_count
        call_count += 1
        if call_count <= providers_per_attempt:
            raise RuntimeError("transient blip")
        return {"content": "x" * 60}, 0.001

    with patch("app.services.execution_engine.asyncio.sleep", new=AsyncMock()):
        result = await engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=flaky_then_valid,
            workflow_run_id=None,
            stage="script_generation",
            validator_name="story",
        )

    assert result.success is True
    assert result.attempts == 2
    assert result.context.validation_result is not None
    assert result.context.validation_result.passed is True


# --- Decision Engine integration (Milestone 5) ------------------------------


@pytest.mark.asyncio
async def test_retry_decision_is_delegated_to_decision_engine():
    """The transient/exhausted classification now goes through
    DecisionEngine.decide_retry() instead of an inline check —
    confirmed by patching it and verifying it's actually called with
    the right arguments, not just that behavior happens to match."""

    engine = ExecutionEngine(db=AsyncMock())

    async def always_fails(provider):
        raise RuntimeError("down")

    with (
        patch("app.services.execution_engine.asyncio.sleep", new=AsyncMock()),
        patch.object(
            engine._decision_engine,
            "decide_retry",
            wraps=engine._decision_engine.decide_retry,
        ) as mock_decide,
    ):
        result = await engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=always_fails,
            workflow_run_id=None,
            stage="script_generation",
        )

    assert result.success is False
    assert mock_decide.call_count == result.attempts
    first_call_kwargs = mock_decide.call_args_list[0].kwargs
    assert first_call_kwargs["attempt_number"] == 1
    assert first_call_kwargs["is_transient"] is True


@pytest.mark.asyncio
async def test_decision_engine_stop_decision_is_honored_immediately():
    """If DecisionEngine ever returns STOP on the very first attempt
    (e.g. a non-transient failure), ExecutionEngine must not retry at
    all, regardless of how much retry budget remains."""
    from unittest.mock import MagicMock

    from app.services.decision_engine import Decision, DecisionAction

    engine = ExecutionEngine(db=AsyncMock())
    call_count = 0

    async def fails_once(provider):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("down")

    stop_decision = Decision(action=DecisionAction.STOP, reason="forced stop for test")
    with (
        patch(
            "app.services.execution_engine.asyncio.sleep", new=AsyncMock()
        ) as mock_sleep,
        patch.object(
            engine._decision_engine,
            "decide_retry",
            MagicMock(return_value=stop_decision),
        ),
    ):
        result = await engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=fails_once,
            workflow_run_id=None,
            stage="script_generation",
        )

    assert result.success is False
    assert result.attempts == 1
    mock_sleep.assert_not_called()
    # Only the first attempt's providers were tried, no second
    # retry-wrapper attempt happened.
    providers_per_attempt = len(providers_for(Capability.TEXT_GENERATION))
    assert call_count == providers_per_attempt


@pytest.mark.asyncio
async def test_provider_fallback_is_never_invoked_this_milestone():
    """Confirms the Part 3 'stopped, not implemented' claim is
    honestly reflected in the code: decide_provider_fallback must
    never be called anywhere in execute()'s control flow, even on a
    fully-exhausted failure."""
    engine = ExecutionEngine(db=AsyncMock())

    async def always_fails(provider):
        raise RuntimeError("down")

    with (
        patch("app.services.execution_engine.asyncio.sleep", new=AsyncMock()),
        patch.object(
            engine._decision_engine, "decide_provider_fallback"
        ) as mock_fallback,
    ):
        result = await engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=always_fails,
            workflow_run_id=None,
            stage="script_generation",
        )

    assert result.success is False
    mock_fallback.assert_not_called()


@pytest.mark.asyncio
async def test_provider_and_execution_history_preserved_across_retries():
    """'Preserve provider execution history' — after retries, the
    final context/result must reflect the ACTUAL provider that
    eventually succeeded and the true attempt count, not just the
    first attempt's state getting silently overwritten or lost."""
    engine = ExecutionEngine(db=AsyncMock())
    providers_per_attempt = len(providers_for(Capability.TEXT_GENERATION))
    call_count = 0

    async def flaky_call(provider):
        nonlocal call_count
        call_count += 1
        if call_count <= providers_per_attempt:
            raise RuntimeError("transient blip")
        return "recovered", 0.003

    with patch("app.services.execution_engine.asyncio.sleep", new=AsyncMock()):
        result = await engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=flaky_call,
            workflow_run_id=None,
            stage="script_generation",
            running_cost_usd=0.1,
        )

    assert result.success is True
    assert result.attempts == 2
    assert result.context.attempt_number == 2
    assert result.context.accumulated_cost == pytest.approx(0.103)
    assert result.provider is not None
    assert result.context.provider == result.provider

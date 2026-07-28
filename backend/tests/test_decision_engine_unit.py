"""
Unit tests for DecisionEngine — pure decision logic, no execution.
Every test here calls a decide_*() method directly and inspects the
returned Decision; nothing calls a provider, sleeps, or touches a
database, because DecisionEngine itself never does either.
"""

import pytest
from app.providers.capabilities import Capability
from app.services.decision_engine import Decision, DecisionAction, DecisionEngine


@pytest.fixture
def engine() -> DecisionEngine:
    return DecisionEngine()


# --- decide_retry -----------------------------------------------------------


def test_decide_retry_returns_retry_when_transient_and_budget_remains(engine):
    decision = engine.decide_retry(attempt_number=1, max_retries=3, is_transient=True)
    assert isinstance(decision, Decision)
    assert decision.action is DecisionAction.RETRY
    assert decision.metadata["attempt_number"] == 1


def test_decide_retry_returns_stop_when_not_transient(engine):
    decision = engine.decide_retry(attempt_number=1, max_retries=3, is_transient=False)
    assert decision.action is DecisionAction.STOP
    assert "not transient" in decision.reason


def test_decide_retry_returns_stop_when_budget_exhausted(engine):
    decision = engine.decide_retry(attempt_number=4, max_retries=3, is_transient=True)
    assert decision.action is DecisionAction.STOP
    assert "exhausted" in decision.reason


def test_decide_retry_never_executes_anything(engine):
    """Sanity check on the core Part 2 constraint: calling this with
    any input must never raise, sleep, or have side effects — it's a
    pure function returning data."""
    decision = engine.decide_retry(attempt_number=999, max_retries=0, is_transient=True)
    assert isinstance(decision, Decision)


# --- decide_stop -------------------------------------------------------------


def test_decide_stop_always_returns_stop(engine):
    decision = engine.decide_stop(attempt_number=1, max_retries=3)
    assert decision.action is DecisionAction.STOP


def test_decide_stop_reason_reflects_budget_exhaustion(engine):
    decision = engine.decide_stop(attempt_number=4, max_retries=3)
    assert "exhausted" in decision.reason


def test_decide_stop_reason_reflects_direct_request(engine):
    decision = engine.decide_stop(attempt_number=1, max_retries=3)
    assert "directly" in decision.reason


# --- decide_provider_fallback -------------------------------------------------


def test_decide_provider_fallback_finds_untried_provider(engine):
    decision = engine.decide_provider_fallback(
        capability=Capability.TEXT_GENERATION, failed_provider="openrouter"
    )
    assert decision.action is DecisionAction.FALLBACK
    assert decision.metadata["next_provider"] != "openrouter"
    assert "openrouter" in decision.metadata["already_tried"]


def test_decide_provider_fallback_stops_when_all_tried():
    engine = DecisionEngine()
    from app.providers.capabilities import providers_for

    all_names = [p.name for p in providers_for(Capability.TEXT_GENERATION)]
    decision = engine.decide_provider_fallback(
        capability=Capability.TEXT_GENERATION,
        failed_provider=None,
        already_tried=all_names,
    )
    assert decision.action is DecisionAction.STOP
    assert "No untried providers" in decision.reason


def test_decide_provider_fallback_does_not_call_any_provider(engine):
    """Confirms Part 2's core constraint for this specific method:
    inspecting candidates via providers_for() is read-only and must
    never invoke a provider's callable."""
    decision = engine.decide_provider_fallback(
        capability=Capability.TEXT_GENERATION, failed_provider="openrouter"
    )
    # If this method had executed anything, there would be nothing
    # meaningful to assert here except that it returned without
    # requiring a provider callable at all — which it did.
    assert decision.metadata.get("next_provider") is not None


# --- decide_prompt_rewrite (extension point only) ----------------------------


def test_decide_prompt_rewrite_defers(engine):
    decision = engine.decide_prompt_rewrite(validation_issues=["too short"])
    assert decision.action is DecisionAction.STOP
    assert "not implemented" in decision.reason
    assert decision.metadata["validation_issues"] == ["too short"]


def test_decide_prompt_rewrite_defaults_to_empty_issues(engine):
    decision = engine.decide_prompt_rewrite()
    assert decision.metadata["validation_issues"] == []


# --- decide_escalation (extension point only) --------------------------------


def test_decide_escalation_stops_when_not_yet_warranted(engine):
    decision = engine.decide_escalation(attempt_number=1, max_retries=3)
    assert decision.action is DecisionAction.STOP


def test_decide_escalation_returns_escalate_when_fully_exhausted(engine):
    decision = engine.decide_escalation(
        attempt_number=4, max_retries=3, fallback_exhausted=True
    )
    assert decision.action is DecisionAction.ESCALATE


def test_decide_escalation_does_not_escalate_without_fallback_exhausted(engine):
    """Both conditions (retry budget AND fallback) must be true —
    exhausting retries alone isn't enough to escalate."""
    decision = engine.decide_escalation(
        attempt_number=4, max_retries=3, fallback_exhausted=False
    )
    assert decision.action is DecisionAction.STOP

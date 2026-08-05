"""
Provider Router — the ONE place fallback logic lives.

Beginner note: without this, every agent would need its own
try-Gemini-then-Anthropic-then-give-up code, copy-pasted seven times
and drifting out of sync. Instead an agent asks the router for a
capability ("I need text_generation") and hands it a callable per
provider; the router tries them in order, logging every attempt as a
GenerationAttempt row and a SystemLog event, and stops at the first
success, a per-video cost ceiling, or the end of the chain.

This does NOT replace n8n as orchestrator — the router picks a
provider for a single step; n8n still sequences the pipeline.
"""
import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.core.config import get_settings
from app.events.log import EventType, log_event
from app.providers.capabilities import Capability, ProviderCapability, providers_for


class AllProvidersFailedError(RuntimeError):
    def __init__(self, capability: Capability, attempts: list[str]):
        self.capability = capability
        self.attempts = attempts
        super().__init__(
            f"All providers for '{capability.value}' failed or were skipped: {attempts}"
        )


class CostLimitExceededError(RuntimeError):
    pass


@dataclass
class RouterResult:
    output: object
    provider_used: str
    attempts: list[str]
    cost_usd: float
    duration_seconds: float


ProviderCall = Callable[[ProviderCapability], Awaitable[tuple[object, float]]]
# A ProviderCall takes the chosen provider's capability entry and
# returns (result, cost_usd). Raising = failure, triggers fallback.


async def call_with_fallback(
    capability: Capability,
    call: ProviderCall,
    *,
    workflow_run_id: str | None = None,
    stage: str | None = None,
    priority: list[str] | None = None,
    running_cost_usd: float = 0.0,
    timeout_seconds: float | None = None,
) -> RouterResult:
    """Try providers for `capability` in priority order (default:
    cheapest first, from the capability registry) until one succeeds.

    `running_cost_usd` is the WorkflowRun's total_cost_usd so far —
    pass it in so the router can refuse to start a call that would
    blow the max_cost_per_video_usd ceiling, per item #3's config.
    """
    settings = get_settings()

    if timeout_seconds is not None:
        timeout = timeout_seconds
    elif capability == Capability.VIDEO_GENERATION:
        timeout = 360  # 6 minutes
    elif capability == Capability.IMAGE_GENERATION:
        timeout = 120  # 2 minutes
    else:
        timeout = settings.api_timeout_seconds

    candidates = providers_for(capability)
    if priority:
        order = {name: i for i, name in enumerate(priority)}
        candidates = sorted(candidates, key=lambda p: order.get(p.name, len(order)))

    if not candidates:
        raise AllProvidersFailedError(capability, [])

    if running_cost_usd >= settings.max_cost_per_video_usd:
        await log_event(
            EventType.RETRY_TRIGGERED,
            message=f"Cost ceiling hit (${running_cost_usd:.2f}) before trying {capability.value}",
            workflow_run_id=workflow_run_id,
            level="warning",
        )
        raise CostLimitExceededError(
            f"Running cost ${running_cost_usd:.2f} already at/over "
            f"max_cost_per_video_usd=${settings.max_cost_per_video_usd:.2f}"
        )

    attempts: list[str] = []
    for provider in candidates:
        attempts.append(provider.name)
        started = time.monotonic()
        await log_event(
            EventType.PROVIDER_CALLED,
            message=f"Calling {provider.name} for {capability.value}",
            workflow_run_id=workflow_run_id,
            metadata={"stage": stage, "provider": provider.name},
        )
        try:
            output, cost_usd = await asyncio.wait_for(call(provider), timeout=timeout)
            duration = time.monotonic() - started
            return RouterResult(
                output=output,
                provider_used=provider.name,
                attempts=attempts,
                cost_usd=cost_usd,
                duration_seconds=duration,
            )
        except Exception as exc:  # noqa: BLE001 — any failure triggers fallback, by design
            duration = time.monotonic() - started
            await log_event(
                EventType.RETRY_TRIGGERED,
                message=f"{provider.name} failed for {capability.value}: {exc}",
                workflow_run_id=workflow_run_id,
                level="warning",
                metadata={"stage": stage, "provider": provider.name, "duration_seconds": duration},
            )
            continue

    raise AllProvidersFailedError(capability, attempts)

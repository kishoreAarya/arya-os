"""
Shared media-provider dispatch (IMAGE_GENERATION, VIDEO_GENERATION,
TTS, GPU_EXECUTION).

Same idea as `app/providers/text_dispatch.py`, extended to cover more
than one method name per adapter: a text-generation `ProviderCall`
only ever needs to call `generate_text`, but the media providers each
implement different capabilities with different method names
(`generate_image`, `generate_video`, `generate_speech`, `run_gpu_job`)
— this module is the one place that maps a `(provider.name,
capability)` pair to the right adapter function, so ImageAgent,
VideoAgent, VoiceAgent, or any future media-consuming agent can build
a `ProviderCall` without knowing which providers implement which
capability by name.

None of the adapter modules (fal.py, comfyui.py, replicate.py,
runpod.py) are modified here — each already exposes plain
`async def generate_x(...) -> tuple[dict, float]` functions; this
module only routes to them.

Nothing about ProviderRouter's contract changes:
`build_media_generation_call` returns a `ProviderCall` (the same
`Callable[[ProviderCapability], Awaitable[tuple[object, float]]]`
shape `call_with_fallback`/`ExecutionEngine.execute` already expect),
so it drops straight into the existing `call=...` parameter any agent
already passes to `ExecutionEngine.execute`.

TrendAgent and StoryboardAgent are TEXT_GENERATION-only and are not
touched by this module or by this change — this file exists
independently of `text_dispatch.py`, for the media capabilities only.
"""
from inspect import signature

from app.core.secrets import SecretNotConfigured, get_secrets_manager
from app.providers import comfyui, fal, replicate, runpod
from app.providers.capabilities import Capability, ProviderCapability
from app.providers.router import ProviderCall

# Every provider capable of a media capability (per capabilities.py's
# PROVIDER_CAPABILITIES) must have an entry here, or the fallback
# chain will reach it, find no adapter, and raise — indistinguishable
# from a real provider failure, which is the correct behavior for a
# provider that's registered but genuinely not wired in yet.
_MEDIA_ADAPTERS = {
    "fal": fal,
    "comfyui": comfyui,
    "replicate": replicate,
    "runpod": runpod,
}

# Which adapter method a given capability dispatches to. One adapter
# module can implement more than one of these (fal.py and comfyui.py
# both implement generate_image + generate_video; replicate.py
# implements all three non-GPU methods).
_CAPABILITY_METHODS: dict[Capability, str] = {
    Capability.IMAGE_GENERATION: "generate_image",
    Capability.VIDEO_GENERATION: "generate_video",
    Capability.TTS: "generate_speech",
    Capability.GPU_EXECUTION: "run_gpu_job",
}


def _accepts_image_url(method) -> bool:
    return "image_url" in signature(method).parameters


def build_media_generation_call(
    capability: Capability,
    *,
    prompt: str | None = None,
    image_url: str | None = None,
    payload: dict | None = None,
) -> ProviderCall:
    """Returns a `call_provider` closure suitable for
    `ExecutionEngine.execute(capability=..., call=..., ...)`.

    Pass whichever of `prompt` / `image_url` / `payload` the target
    capability actually needs:
    - IMAGE_GENERATION: `prompt` (required)
    - VIDEO_GENERATION: `prompt` (required), `image_url` (optional,
      only meaningful for providers/models that support
      image-to-video — passed through as-is, unused otherwise)
    - TTS: `prompt` (required) — used as the text to synthesize
    - GPU_EXECUTION: `payload` (required) — an arbitrary job payload,
      typically `{"endpoint_id": ..., "input": {...}}` (see
      app/providers/runpod.py)

    Raises RuntimeError (never returns a failing tuple) for:
    - a capability with no method mapping in `_CAPABILITY_METHODS`
    - a provider name with no adapter in `_MEDIA_ADAPTERS`
    - an adapter that doesn't implement the method this capability
      needs (e.g. if `capabilities.py` ever registers a provider for a
      capability its adapter module hasn't caught up to yet)
    - a configured `secret_name` whose value isn't set in
      Settings/.env — providers with `secret_name=None` (self-hosted,
      e.g. "comfyui") skip the secret lookup entirely and get
      `api_key=None`, same as their adapter's own docstring documents

    All of these are treated as an ordinary per-provider failure by
    `call_with_fallback` (any exception triggers fallback to the next
    candidate) — same taxonomy the adapters themselves already use.
    """

    async def call_provider(provider: ProviderCapability) -> tuple[dict, float]:
        method_name = _CAPABILITY_METHODS.get(capability)
        if method_name is None:
            raise RuntimeError(
                f"No media dispatch method mapped for capability '{capability.value}'"
            )

        adapter = _MEDIA_ADAPTERS.get(provider.name)
        if adapter is None:
            raise RuntimeError(
                f"No media adapter implemented yet for provider '{provider.name}'"
            )

        method = getattr(adapter, method_name, None)
        if method is None:
            raise RuntimeError(
                f"Provider '{provider.name}' has no '{method_name}' implementation "
                f"for capability '{capability.value}'"
            )

        api_key = None
        if provider.secret_name:
            try:
                api_key = get_secrets_manager().get(provider.secret_name)
            except SecretNotConfigured as exc:
                raise RuntimeError(str(exc)) from exc

        model = provider.supported_models[0] if provider.supported_models else None

        if method_name == "run_gpu_job":
            return await method(payload=payload or {}, api_key=api_key, model=model)
        if method_name == "generate_speech":
            return await method(text=prompt, api_key=api_key, model=model)
        if method_name == "generate_video":
            if _accepts_image_url(method):
                return await method(
                    prompt=prompt, api_key=api_key, model=model, image_url=image_url
                )
            # comfyui.generate_video doesn't take image_url (no
            # image-to-video graph implemented yet) — call without it
            # rather than forcing every adapter to accept a parameter
            # it can't use.
            return await method(prompt=prompt, api_key=api_key, model=model)
        # generate_image
        return await method(prompt=prompt, api_key=api_key, model=model)

    return call_provider

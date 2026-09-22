from typing import Any
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
from app.providers import comfyui, elevenlabs, fal, replicate, runpod, together
from app.providers.capabilities import Capability, ProviderCapability
from app.providers.router import ProviderCall

# Every provider capable of a media capability (per capabilities.py's
# PROVIDER_CAPABILITIES) must have an entry here, or the fallback
# chain will reach it, find no adapter, and raise — indistinguishable
# from a real provider failure, which is the correct behavior for a
# provider that's registered but genuinely not wired in yet.
_MEDIA_ADAPTERS = {
    "fal": fal,
    "together": together,
    "comfyui": comfyui,
    "replicate": replicate,
    "runpod": runpod,
    "elevenlabs": elevenlabs,
    "kling": replicate,
}


def get_media_adapter(provider_name: str):
    """Retrieve the adapter module for a registered media provider."""
    return _MEDIA_ADAPTERS.get(provider_name)

# Which adapter method a given capability dispatches to. One adapter
# module can implement more than one of these (fal.py and comfyui.py
# both implement generate_image + generate_video; replicate.py
# implements all three non-GPU methods).
_CAPABILITY_METHODS: dict[Capability, str] = {
    Capability.IMAGE_GENERATION: "generate_image",
    Capability.VIDEO_GENERATION: "generate_video",
    Capability.TTS: "generate_speech",
    Capability.MUSIC_GENERATION: "generate_music",
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
    aspect_ratio: str | None = None,
    duration_seconds: int | float | None = None,
    **kwargs: Any,
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

        model = provider.get_model(capability)

        if method_name == "run_gpu_job":
            return await method(payload=payload or {}, api_key=api_key, model=model)
        if method_name == "generate_speech":
            call_kwargs = {}
            if provider.name == "elevenlabs":
                effective_model = kwargs.get("model") or kwargs.get("voice_model") or model
                voice_id = kwargs.get("voice_id")
                if not voice_id:
                    from app.core.config import get_settings
                    settings = get_settings()
                    voice_id = getattr(settings, "elevenlabs_voice_id", None)
                if voice_id:
                    call_kwargs["voice_id"] = voice_id
            elif provider.name == "replicate":
                # Ensure model is valid for Replicate (do not forward elevenlabs model strings)
                candidate_model = kwargs.get("model") or kwargs.get("voice_model")
                if candidate_model and not str(candidate_model).startswith("eleven_") and "kokoro" in str(candidate_model):
                    effective_model = candidate_model
                else:
                    effective_model = model
                # Check voice parameter for Replicate / Kokoro
                raw_voice = kwargs.get("voice") or kwargs.get("voice_id")
                if raw_voice:
                    # Kokoro voices typically have underscores like af_bella, am_fenrir, bm_george
                    if "_" in str(raw_voice) or str(raw_voice) in ("af", "am", "bf", "bm"):
                        call_kwargs["voice_id"] = raw_voice
                    else:
                        # Fallback Kokoro voice for cinematic narrative
                        call_kwargs["voice_id"] = "bm_george"
                if "speed" in kwargs and kwargs["speed"] is not None:
                    call_kwargs["speed"] = kwargs["speed"]
            else:
                effective_model = kwargs.get("model") or kwargs.get("voice_model") or model
                if "voice_id" in signature(method).parameters and kwargs.get("voice_id"):
                    call_kwargs["voice_id"] = kwargs.get("voice_id")

            return await method(text=prompt, api_key=api_key, model=effective_model, **call_kwargs)
        if method_name == "generate_music":
            call_kwargs = {}
            if "duration_seconds" in signature(method).parameters and duration_seconds is not None:
                call_kwargs["duration_seconds"] = duration_seconds
            return await method(
                prompt=prompt, api_key=api_key, model=model, **call_kwargs
            )
        if method_name == "generate_video":
            call_kwargs = {}
            if _accepts_image_url(method):
                call_kwargs["image_url"] = image_url
            if "aspect_ratio" in signature(method).parameters and aspect_ratio:
                call_kwargs["aspect_ratio"] = aspect_ratio
            effective_model = kwargs.get("model") or kwargs.get("video_model") or model
            return await method(
                prompt=prompt, api_key=api_key, model=effective_model, **call_kwargs
            )
        # generate_image
        req_provider = kwargs.get("image_provider") or kwargs.get("provider")
        req_model = kwargs.get("model") or kwargs.get("image_model")
        if req_provider and provider.name != req_provider:
            # Fallback provider: check if requested model is supported by this provider, otherwise use provider default
            supported = list(provider.supported_models or ())
            if capability in provider.capability_models:
                supported.extend(provider.capability_models[capability])
            if req_model and any(req_model.lower() in s.lower() or s.lower() in req_model.lower() for s in supported):
                effective_model = req_model
            else:
                effective_model = model
        else:
            effective_model = req_model or model

        call_kwargs = {}
        if "num_outputs" in signature(method).parameters:
            if "num_outputs" in kwargs and kwargs["num_outputs"] is not None:
                call_kwargs["num_outputs"] = kwargs["num_outputs"]

        if "aspect_ratio" in signature(method).parameters and aspect_ratio:
            res, cost = await method(
                prompt=prompt, api_key=api_key, model=effective_model, aspect_ratio=aspect_ratio, **call_kwargs
            )
            if isinstance(res, dict):
                if "aspect_ratio" not in res:
                    res["aspect_ratio"] = aspect_ratio
                if req_provider or req_model:
                    res.setdefault("provider_used", provider.name)
                    res.setdefault("model_used", effective_model)
                    res.setdefault("provider", provider.name)
                    res.setdefault("model", effective_model)
            return res, cost

        res, cost = await method(prompt=prompt, api_key=api_key, model=effective_model, **call_kwargs)
        if isinstance(res, dict):
            if aspect_ratio and "aspect_ratio" not in res:
                res["aspect_ratio"] = aspect_ratio
            if req_provider or req_model:
                res.setdefault("provider_used", provider.name)
                res.setdefault("model_used", effective_model)
                res.setdefault("provider", provider.name)
                res.setdefault("model", effective_model)
        return res, cost

    return call_provider

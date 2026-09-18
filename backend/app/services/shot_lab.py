"""Shot Lab — Controlled cinematic visual generation benchmarking and diagnosis service.

Part of Arya OS Task 23: Visual Model Shootout & Visual Quality Diagnosis.
Isolates image generation and video generation pipelines to identify the exact
root cause of visual quality deficiencies without modifying production defaults.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

from app.core.config import get_settings
from app.core.logging import get_logger

load_dotenv()

logger = get_logger("arya.services.shot_lab")


# ---------------------------------------------------------------------------
# Part 3: Visual Reference Sheet
# ---------------------------------------------------------------------------

@dataclass
class CharacterReference:
    name: str = "Father Thomas"
    age: int = 48
    facial_structure: str = "Gaunt hollow cheeks, prominent cheekbones, sharp jawline, deep worry lines across brow"
    hair: str = "Short receding dark hair peppered with silver-grey, disheveled"
    skin_characteristics: str = "Pale, weathered, visible skin pores, slight sheen of cold sweat, faint stubble on chin"
    clothing: str = "Threadbare black woolen priestly cassock, frayed collar, dust-stained shoulders"
    accessories: str = "Tarnished brass crucifix on a thin dark cord, wire-rimmed round spectacles slightly fogged"
    body_proportions: str = "Lean, slightly stooped frame, tense shoulders, trembling hands"
    emotional_state: str = "Visceral dread, watchful anticipation, solemn religious terror"


@dataclass
class PropReference:
    name: str = "Antique Brass Lantern"
    material: str = "Heavy 19th-century antiqued brass with greenish verdigris oxidation in crevices"
    age: str = "Over a century old, dented chimney cap, worn cylindrical frame"
    damage: str = "Hairline spiderweb crack on the right glass panel, soot stains along the upper rim"
    light_behavior: str = "Glowing yellow-amber wick flame (2400K) flickering irregularly, casting sharp moving shadows"


@dataclass
class EnvironmentReference:
    architecture: str = "Subterranean Romanesque crypt chapel, 12th-century ribbed barrel-vaulted limestone arches"
    materials: str = "Rough-hewn porous damp limestone blocks, weeping mortar seams, green moss in stone crevices"
    floor: str = "Uneven dark slate flagstones with shallow puddles reflecting warm lantern glow"
    walls: str = "Looming vaulted arches receding into pitch darkness, dripping condensation, ancient stone crucifix relief"
    mirror: str = "Antique gilt-framed baroque standing mirror at the end of the nave, cracked across the upper right glass"
    atmosphere: str = "Thick damp subterranean chill, hanging dust motes illuminated in the light beam, visible breath"
    weather_time: str = "Midnight, underground, sealed from outside world"


@dataclass
class LightingReference:
    primary_source: str = "Low-angle motivated practical amber flame (2400K) from the held brass lantern"
    direction: str = "Upward and outward from chest level (35-degree angle), illuminating lower face and hands"
    color_temperature: str = "Warm amber (2400K) key light contrasting against cold slate-cyan (5600K) ambient fill"
    shadow_behavior: str = "High-contrast chiaroscuro, harsh jagged shadows cast against vaulted arches, deep tenebrism"
    practical_light: str = "Direct yellow-orange filament illumination on cassock weave and spectacles"
    ambient_fill: str = "Subtle desaturated cold slate fill falling from high inaccessible stone ventilation grates"


@dataclass
class CinematographyReference:
    framing: str = "Medium shot (waist up), subject in right third looking toward center left, 9:16 vertical orientation"
    camera_height: str = "Eye level to slightly low angle, emphasizing cavernous stone vaulting overhead"
    lens: str = "35mm anamorphic prime lens, characteristic horizontal flare streak from lantern flame"
    depth_of_field: str = "Shallow depth of field (f/2.0), subject and lantern in razor-sharp focus, background softly blurred"
    foreground_background: str = "Foreground: edge of damp stone column silhouette; Midground: Father Thomas & lantern; Background: cracked mirror & dark arch"
    composition: str = "Dynamic three-plane depth staging, strong diagonal leading lines created by vaulted arches"


@dataclass
class VisualReferenceSheet:
    character: CharacterReference = field(default_factory=CharacterReference)
    prop: PropReference = field(default_factory=PropReference)
    environment: EnvironmentReference = field(default_factory=EnvironmentReference)
    lighting: LightingReference = field(default_factory=LightingReference)
    cinematography: CinematographyReference = field(default_factory=CinematographyReference)


# ---------------------------------------------------------------------------
# Part 2: Standardized Horror Test Scene
# ---------------------------------------------------------------------------

@dataclass
class StandardizedHorrorScene:
    title: str = "The Crypt of Whispers"
    concept: str = (
        "A frightened middle-aged priest enters an abandoned underground chapel at night. "
        "He carries an old brass lantern. At the far end of the chapel, a pale woman appears "
        "reflected in a cracked standing mirror even though nobody is physically standing in the room."
    )
    action: str = "Father Thomas raises the flickering brass lantern, his hand trembling as he stops before the aisle."
    supernatural_element: str = "An eerie pale veiled figure reflected in the fractured glass of the mirror behind him."
    visual_reference: VisualReferenceSheet = field(default_factory=VisualReferenceSheet)


# ---------------------------------------------------------------------------
# Part 5: Prompt Strategies
# ---------------------------------------------------------------------------

class PromptStrategy(str, Enum):
    P1_CURRENT_ARYA = "P1_Current_Arya"
    P2_CINEMATOGRAPHY = "P2_Cinematography"
    P3_CINEMATIC_STORYTELLING = "P3_Cinematic_Storytelling"


def build_prompt_for_strategy(
    strategy: PromptStrategy,
    scene: StandardizedHorrorScene,
    aspect_ratio: str = "9:16",
) -> Tuple[str, str]:
    """Generate positive and negative prompts based on the strategy."""
    ref = scene.visual_reference

    if strategy == PromptStrategy.P1_CURRENT_ARYA:
        # Current Arya OS prompt structure (uses standard adjectives & structure from prompt.py)
        positive = (
            f"Cinematic medium shot of {ref.character.name}, a {ref.character.age}-year-old priest with "
            f"{ref.character.facial_structure} and {ref.character.hair}, wearing {ref.character.clothing} "
            f"with {ref.character.accessories}. He is holding a {ref.prop.name} with {ref.prop.light_behavior} "
            f"inside an {ref.environment.architecture} with {ref.environment.materials} and {ref.environment.floor}. "
            f"In the background, a {ref.environment.mirror}. {ref.lighting.primary_source} with "
            f"{ref.lighting.shadow_behavior}. Dramatic horror lighting, 35mm film photography, highly detailed, "
            f"8k resolution, photorealistic masterpiece, vertical {aspect_ratio} framing."
        )
        negative = (
            "low quality, blurry, watermark, logo, text, bad anatomy, extra fingers, extra limbs, "
            "duplicate subject, cropped, deformed face, bad hands, oversaturated, cartoon, 3d render"
        )

    elif strategy == PromptStrategy.P2_CINEMATOGRAPHY:
        # Concrete filmmaking directives: framing, optics, lighting physics, staging (NO buzzwords)
        positive = (
            f"A medium vertical shot framed at eye-level with a 35mm anamorphic prime lens at f/2.0. "
            f"Father Thomas, a gaunt 48-year-old priest with hollow temples, visible skin pores, fine beads of cold sweat, "
            f"and round wire-rimmed spectacles, wears a worn black woolen cassock with a tarnished brass crucifix. "
            f"He holds an antique dented brass lantern with a cracked glass panel, itsMotivated 2400K warm amber flame "
            f"casting harsh chiaroscuro shadows across his trembling face and chest. "
            f"Setting: subterranean 12th-century Romanesque crypt with wet limestone barrel vaults, weeping mortar seams, "
            f"and puddle-strewn dark flagstones reflecting amber light. "
            f"Three-plane depth composition: out-of-focus wet stone archway in immediate foreground right, "
            f"sharp priest in midground, distant tarnished baroque mirror with fractured glass in soft background. "
            f"Cold 5600K slate ambient rim light from overhead ventilation grate. Subtle anamorphic lens flare, organic fine grain."
        )
        negative = (
            "smooth waxy plastic skin, digital airbrushing, oversaturated neon, extra digits, misshapen eyes, "
            "distorted spectacles, CGI render, video game screenshot, watermark, signature, cartoon illustration, border"
        )

    elif strategy == PromptStrategy.P3_CINEMATIC_STORYTELLING:
        # Prioritizes visual hierarchy, emotional intent, subject & action, story information
        positive = (
            f"Visual hierarchy focused on paralyzing dread: Father Thomas, an exhausted 48-year-old priest in a dust-stained "
            f"black cassock, raises a flickering brass oil lantern with shaking hands, his breath misting in the freezing air. "
            f"His wide dark eyes behind wire-rimmed spectacles reflect terror as he stares down the vaulted aisle of a dark "
            f"underground limestone chapel. In the shadows behind him, an antique cracked standing mirror catches the amber lantern light, "
            f"revealing the faint, horrifying reflection of a pale veiled woman standing directly behind his shoulder, "
            f"though the physical stone crypt behind him is completely empty. "
            f"Motivated amber flame key light against pitch-black crypt shadows. Raw cinematic realism, heavy psychological horror, "
            f"authentic textured wool, damp porous masonry, 9:16 vertical composition."
        )
        negative = (
            "artificial smiling, flat commercial lighting, plastic skin, anime style, missing fingers, malformed hands, "
            "asymmetrical glasses, clean modern church, bright room, 3d model render, watermark, typography"
        )
    else:
        raise ValueError(f"Unknown prompt strategy: {strategy}")

    return positive, negative


# ---------------------------------------------------------------------------
# Part 4 & 6: Model Specifications
# ---------------------------------------------------------------------------

@dataclass
class ImageModelSpec:
    model_id: str
    provider: str
    display_name: str
    cost_usd: float
    replicate_owner: str
    replicate_name: str
    version_id: Optional[str] = None
    is_available: bool = True
    notes: str = ""


@dataclass
class VideoModelSpec:
    model_id: str
    provider: str
    display_name: str
    cost_usd: float
    replicate_owner: str
    replicate_name: str
    version_id: Optional[str] = None
    is_available: bool = True
    notes: str = ""


IMAGE_MODEL_REGISTRY: Dict[str, ImageModelSpec] = {
    "flux-schnell": ImageModelSpec(
        model_id="flux-schnell",
        provider="replicate",
        display_name="FLUX Schnell (Current Production)",
        cost_usd=0.003,
        replicate_owner="black-forest-labs",
        replicate_name="flux-schnell",
        version_id=None,
        is_available=True,
        notes="4-step latent distilled model used in Tasks 21 & 22",
    ),
    "flux-dev": ImageModelSpec(
        model_id="flux-dev",
        provider="replicate",
        display_name="FLUX Dev (High-Quality Guidance Distilled)",
        cost_usd=0.025,
        replicate_owner="black-forest-labs",
        replicate_name="flux-dev",
        version_id=None,
        is_available=True,
        notes="28-step guidance-distilled model for superior photorealism & texture",
    ),
    "flux-1.1-pro": ImageModelSpec(
        model_id="flux-1.1-pro",
        provider="replicate",
        display_name="FLUX 1.1 Pro (Flagship Cinema Grade)",
        cost_usd=0.040,
        replicate_owner="black-forest-labs",
        replicate_name="flux-1.1-pro",
        version_id=None,
        is_available=True,
        notes="Flagship cinematic image model with full prompt adherence & skin detail",
    ),
    "fal-flux-pro": ImageModelSpec(
        model_id="fal-flux-pro",
        provider="fal",
        display_name="Fal FLUX Pro",
        cost_usd=0.050,
        replicate_owner="",
        replicate_name="",
        is_available=False,
        notes="UNAVAILABLE: Fal API key authentication failed (401 Key ID/Secret)",
    ),
}

VIDEO_MODEL_REGISTRY: Dict[str, VideoModelSpec] = {
    "kling-standard": VideoModelSpec(
        model_id="kling-standard",
        provider="replicate",
        display_name="Kling v1.6 Standard (Current Production Video)",
        cost_usd=0.250,
        replicate_owner="kwaivgi",
        replicate_name="kling-v1.6-standard",
        version_id=None,
        is_available=True,
        notes="Production default video model",
    ),
    "ltx-video": VideoModelSpec(
        model_id="ltx-video",
        provider="replicate",
        display_name="LTX-Video (Current Fallback Model)",
        cost_usd=0.050,
        replicate_owner="lightricks",
        replicate_name="ltx-video",
        version_id="8c47da666861d081eeb4d1261853087de23923a268a69b63febdf5dc1dee08e4",
        is_available=True,
        notes="Fallback fast video generation model in Arya OS capabilities registry",
    ),
    "wan-2.1-i2v": VideoModelSpec(
        model_id="wan-2.1-i2v",
        provider="replicate",
        display_name="Wan 2.1 I2V (State-of-the-Art Alternative)",
        cost_usd=0.150,
        replicate_owner="wavespeedai",
        replicate_name="wan-2.1-i2v-480p",
        version_id=None,
        is_available=True,
        notes="Open state-of-the-art video model with strong temporal physics",
    ),
}


# ---------------------------------------------------------------------------
# Part 10: 22-Dimension Visual Quality Rubric
# ---------------------------------------------------------------------------

@dataclass
class VisualQualityRubricScores:
    # IMAGE DIMENSIONS (1-10)
    composition: float = 0.0           # Framing, 9:16 vertical alignment, three planes
    lighting: float = 0.0              # Motivated 2400K amber vs 5600K slate chiaroscuro
    character_appearance: float = 0.0  # Father Thomas identity, age, spectacles, cassock
    environment: float = 0.0           # Romanesque crypt, weeping limestone, arches
    prop_accuracy: float = 0.0         # Brass lantern, glass crack, flame behavior
    texture_detail: float = 0.0        # Skin pores, sweat sheen, cloth weave, stone grit
    depth: float = 0.0                 # Foreground/midground/background separation, bokeh
    realism: float = 0.0               # Absence of waxy plastic AI gloss
    cinematic_appeal: float = 0.0      # Evocative mood, lens optics, anamorphic feel
    visual_storytelling: float = 0.0   # Story beats: dread, supernatural mirror hint

    # VIDEO DIMENSIONS (11-18)
    motion_realism: float = 0.0        # Physical movement plausibility
    temporal_consistency: float = 0.0  # Consistency across frame sequence
    identity_preservation: float = 0.0 # Character face doesn't mutate or drift
    anatomy_stability: float = 0.0     # Hands, fingers, eyes, teeth remain stable
    camera_movement: float = 0.0       # Believable camera push/track vs jerky jitter
    performance: float = 0.0           # Eyes, breathing, emotional reaction timing
    environmental_motion: float = 0.0  # Flame flicker, smoke drift, dust motes
    lighting_stability: float = 0.0    # Amber lantern key maintains consistent cast

    # HUMAN IMPRESSION (19-22)
    first_impression: float = 0.0              # Initial gut reaction (1-10)
    would_stop_scrolling: float = 0.0          # Hook factor on social feed (1-10)
    does_this_feel_authored: float = 0.0       # Intentional directorial control (1-10)
    looks_like_real_production: float = 0.0    # Cinema standard vs cheap AI demo (1-10)

    @property
    def image_subtotal(self) -> float:
        return sum([
            self.composition, self.lighting, self.character_appearance, self.environment,
            self.prop_accuracy, self.texture_detail, self.depth, self.realism,
            self.cinematic_appeal, self.visual_storytelling
        ]) / 10.0

    @property
    def video_subtotal(self) -> float:
        return sum([
            self.motion_realism, self.temporal_consistency, self.identity_preservation,
            self.anatomy_stability, self.camera_movement, self.performance,
            self.environmental_motion, self.lighting_stability
        ]) / 8.0

    @property
    def human_subtotal(self) -> float:
        return sum([
            self.first_impression, self.would_stop_scrolling,
            self.does_this_feel_authored, self.looks_like_real_production
        ]) / 4.0

    @property
    def composite_score(self) -> float:
        # Weighted: 35% Image, 35% Video, 30% Human Impression
        return (self.image_subtotal * 0.35) + (self.video_subtotal * 0.35) + (self.human_subtotal * 0.30)


@dataclass
class ImageCandidateResult:
    candidate_id: str
    model_id: str
    strategy: PromptStrategy
    positive_prompt: str
    negative_prompt: str
    image_url: str
    local_image_path: str
    latency_seconds: float
    cost_usd: float
    rubric: VisualQualityRubricScores = field(default_factory=VisualQualityRubricScores)
    error: Optional[str] = None


@dataclass
class VideoCandidateResult:
    candidate_id: str
    video_model_id: str
    source_image_candidate_id: str
    source_image_url: str
    source_image_local_path: str
    motion_prompt: str
    video_url: str
    local_video_path: str
    representative_frames: List[str] = field(default_factory=list)
    latency_seconds: float = 0.0
    cost_usd: float = 0.0
    rubric: VisualQualityRubricScores = field(default_factory=VisualQualityRubricScores)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Part 1: Shot Lab Engine
# ---------------------------------------------------------------------------

class ShotLab:
    """Isolated experimental laboratory for diagnosing and benchmarking
    cinematic visual generation models and prompt strategies.
    """

    def __init__(
        self,
        output_dir: str = "/tmp/arya-task23-visual-shootout",
        desktop_dir: str = "~/Desktop/arya-task23-visual-shootout",
    ) -> None:
        self.output_dir = Path(output_dir)
        self.desktop_dir = Path(os.path.expanduser(desktop_dir))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.desktop_dir.mkdir(parents=True, exist_ok=True)

        self.replicate_api_key = os.getenv("REPLICATE_API_KEY", "")
        self.fal_api_key = os.getenv("FAL_API_KEY", "")
        self.total_cost_usd = 0.0

        self.cache_file = self.output_dir / "shot_lab_cache.json"
        self._cache: Dict[str, Any] = {}
        if self.cache_file.exists():
            try:
                self._cache = json.loads(self.cache_file.read_text(encoding="utf-8"))
            except Exception:
                self._cache = {}

    def _save_cache(self) -> None:
        try:
            self.cache_file.write_text(json.dumps(self._cache, indent=2), encoding="utf-8")
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Low-level Replicate Prediction Runner
    # -----------------------------------------------------------------------

    async def _run_replicate_prediction(
        self,
        owner: str,
        name: str,
        version_id: Optional[str],
        inputs: Dict[str, Any],
        timeout_seconds: float = 300.0,
    ) -> Tuple[Any, float]:
        """Execute a prediction via Replicate API with reliable async polling."""
        if not self.replicate_api_key:
            raise RuntimeError("REPLICATE_API_KEY is not configured")

        headers = {
            "Authorization": f"Token {self.replicate_api_key}",
            "Content-Type": "application/json",
            "Prefer": "wait=15",
        }

        # URL choice: official model endpoint vs version endpoint
        if version_id:
            url = "https://api.replicate.com/v1/predictions"
            body = {"version": version_id, "input": inputs}
        else:
            url = f"https://api.replicate.com/v1/models/{owner}/{name}/predictions"
            body = {"input": inputs}

        start_time = time.time()
        max_submit_retries = 6
        pred = None

        for attempt in range(max_submit_retries):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(url, json=body, headers=headers)
                    if resp.status_code in (200, 201, 202):
                        pred = resp.json()
                        break
                    elif resp.status_code == 429:
                        wait_sec = 10.0
                        try:
                            data = resp.json()
                            wait_sec = float(data.get("retry_after", 10.0)) + 1.5
                        except Exception:
                            pass
                        logger.warning("replicate_throttled", wait_seconds=wait_sec, attempt=attempt)
                        print(f"   [Rate Limited 429] Waiting {wait_sec:.1f}s for quota window (attempt {attempt+1}/{max_submit_retries})...")
                        await asyncio.sleep(wait_sec)
                    else:
                        raise RuntimeError(
                            f"Replicate create prediction failed ({resp.status_code}): {resp.text[:500]}"
                        )
            except httpx.RequestError as req_err:
                logger.warning("replicate_submit_network_error", error=str(req_err))
                await asyncio.sleep(3.0)

        if not pred:
            raise RuntimeError(f"Replicate prediction failed after {max_submit_retries} attempts due to throttling")

        pred_id = pred.get("id")
        status = pred.get("status")
        output = pred.get("output")

        poll_url = f"https://api.replicate.com/v1/predictions/{pred_id}"
        poll_interval = 3.0

        while status not in ("succeeded", "failed", "canceled"):
            if time.time() - start_time > timeout_seconds:
                raise TimeoutError(f"Replicate prediction {pred_id} timed out after {timeout_seconds}s")
            await asyncio.sleep(poll_interval)
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    poll_resp = await client.get(poll_url, headers=headers)
                    if poll_resp.status_code == 200:
                        pred = poll_resp.json()
                        status = pred.get("status")
                        output = pred.get("output")
                    elif poll_resp.status_code == 429:
                        await asyncio.sleep(5.0)
                    else:
                        logger.warning("replicate_poll_retry", status_code=poll_resp.status_code)
            except httpx.RequestError:
                pass

        elapsed = time.time() - start_time
        if status != "succeeded":
            err = pred.get("error") or "Unknown error"
            raise RuntimeError(f"Replicate prediction {pred_id} ended with status '{status}': {err}")

        return output, elapsed

    # -----------------------------------------------------------------------
    # Image Generation
    # -----------------------------------------------------------------------

    async def generate_image_candidate(
        self,
        model_spec: ImageModelSpec,
        strategy: PromptStrategy,
        scene: StandardizedHorrorScene,
        aspect_ratio: str = "9:16",
        seed: int = 42,
    ) -> ImageCandidateResult:
        """Generate a single image candidate using specified model and prompt strategy."""
        candidate_id = f"img_{model_spec.model_id}_{strategy.value.lower()}"
        pos_prompt, neg_prompt = build_prompt_for_strategy(strategy, scene, aspect_ratio)

        if not model_spec.is_available:
            return ImageCandidateResult(
                candidate_id=candidate_id,
                model_id=model_spec.model_id,
                strategy=strategy,
                positive_prompt=pos_prompt,
                negative_prompt=neg_prompt,
                image_url="",
                local_image_path="",
                latency_seconds=0.0,
                cost_usd=0.0,
                error=model_spec.notes,
            )

        inputs: Dict[str, Any] = {
            "prompt": pos_prompt,
            "aspect_ratio": aspect_ratio,
            "output_format": "png",
            "output_quality": 95,
            "seed": seed,
        }

        if model_spec.model_id == "flux-dev":
            inputs["guidance"] = 3.5
            inputs["num_inference_steps"] = 28
        elif model_spec.model_id == "flux-schnell":
            inputs["num_inference_steps"] = 4

        local_filename = f"{candidate_id}.png"
        local_path = self.output_dir / local_filename

        if candidate_id in self._cache and local_path.exists() and local_path.stat().st_size > 1000:
            cached = self._cache[candidate_id]
            logger.info("shot_lab_image_cache_hit", candidate_id=candidate_id)
            print(f"   [CACHED] Reusing previously generated image: {candidate_id}")
            return ImageCandidateResult(
                candidate_id=candidate_id,
                model_id=model_spec.model_id,
                strategy=strategy,
                positive_prompt=pos_prompt,
                negative_prompt=neg_prompt,
                image_url=cached.get("image_url", ""),
                local_image_path=str(local_path),
                latency_seconds=cached.get("latency_seconds", 0.0),
                cost_usd=cached.get("cost_usd", model_spec.cost_usd),
            )

        logger.info(
            "shot_lab_image_start",
            model=model_spec.model_id,
            strategy=strategy.value,
            candidate_id=candidate_id,
        )

        try:
            output, elapsed = await self._run_replicate_prediction(
                owner=model_spec.replicate_owner,
                name=model_spec.replicate_name,
                version_id=model_spec.version_id,
                inputs=inputs,
                timeout_seconds=90.0,
            )

            # Extract image URL
            if isinstance(output, list) and output:
                img_url = output[0]
            elif isinstance(output, str):
                img_url = output
            else:
                raise RuntimeError(f"Unexpected image output format: {output}")

            # Download locally
            async with httpx.AsyncClient(timeout=60.0) as client:
                img_bytes = (await client.get(img_url)).content
            local_path.write_bytes(img_bytes)

            self.total_cost_usd += model_spec.cost_usd
            self._cache[candidate_id] = {
                "image_url": img_url,
                "local_path": str(local_path),
                "latency_seconds": round(elapsed, 2),
                "cost_usd": model_spec.cost_usd,
            }
            self._save_cache()

            logger.info(
                "shot_lab_image_complete",
                candidate_id=candidate_id,
                elapsed=elapsed,
                cost=model_spec.cost_usd,
            )

            return ImageCandidateResult(
                candidate_id=candidate_id,
                model_id=model_spec.model_id,
                strategy=strategy,
                positive_prompt=pos_prompt,
                negative_prompt=neg_prompt,
                image_url=img_url,
                local_image_path=str(local_path),
                latency_seconds=round(elapsed, 2),
                cost_usd=model_spec.cost_usd,
            )

        except Exception as exc:
            logger.exception("shot_lab_image_failed", candidate_id=candidate_id, error=str(exc))
            return ImageCandidateResult(
                candidate_id=candidate_id,
                model_id=model_spec.model_id,
                strategy=strategy,
                positive_prompt=pos_prompt,
                negative_prompt=neg_prompt,
                image_url="",
                local_image_path="",
                latency_seconds=0.0,
                cost_usd=0.0,
                error=str(exc),
            )

    # -----------------------------------------------------------------------
    # Video Generation
    # -----------------------------------------------------------------------

    async def generate_video_candidate(
        self,
        video_spec: VideoModelSpec,
        source_image: ImageCandidateResult,
        motion_prompt: str,
        duration_seconds: int = 5,
        aspect_ratio: str = "9:16",
    ) -> VideoCandidateResult:
        """Generate a video shot from a source image keyframe."""
        candidate_id = f"vid_{video_spec.model_id}_from_{source_image.candidate_id}"

        if not video_spec.is_available:
            return VideoCandidateResult(
                candidate_id=candidate_id,
                video_model_id=video_spec.model_id,
                source_image_candidate_id=source_image.candidate_id,
                source_image_url=source_image.image_url,
                source_image_local_path=source_image.local_image_path,
                motion_prompt=motion_prompt,
                video_url="",
                local_video_path="",
                latency_seconds=0.0,
                cost_usd=0.0,
                error=video_spec.notes,
            )

        inputs: Dict[str, Any] = {}
        if video_spec.model_id == "kling-standard":
            inputs = {
                "prompt": motion_prompt,
                "start_image": source_image.image_url,
                "duration": duration_seconds,
                "aspect_ratio": aspect_ratio,
                "cfg_scale": 0.5,
            }
        elif video_spec.model_id == "ltx-video":
            inputs = {
                "prompt": motion_prompt,
                "image": source_image.image_url,
                "aspect_ratio": aspect_ratio,
                "steps": 30,
            }
        elif video_spec.model_id == "wan-2.1-i2v":
            inputs = {
                "prompt": motion_prompt,
                "image": source_image.image_url,
                "aspect_ratio": aspect_ratio,
                "sample_steps": 30,
            }
        else:
            inputs = {
                "prompt": motion_prompt,
                "image": source_image.image_url,
                "aspect_ratio": aspect_ratio,
            }

        local_filename = f"{candidate_id}.mp4"
        local_path = self.output_dir / local_filename

        if candidate_id in self._cache and local_path.exists() and local_path.stat().st_size > 1000:
            cached = self._cache[candidate_id]
            logger.info("shot_lab_video_cache_hit", candidate_id=candidate_id)
            print(f"   [CACHED] Reusing previously generated video: {candidate_id}")
            rep_frames = await self.extract_representative_frames(str(local_path), candidate_id)
            return VideoCandidateResult(
                candidate_id=candidate_id,
                video_model_id=video_spec.model_id,
                source_image_candidate_id=source_image.candidate_id,
                source_image_url=source_image.image_url,
                source_image_local_path=source_image.local_image_path,
                motion_prompt=motion_prompt,
                video_url=cached.get("video_url", ""),
                local_video_path=str(local_path),
                representative_frames=rep_frames,
                latency_seconds=cached.get("latency_seconds", 0.0),
                cost_usd=cached.get("cost_usd", video_spec.cost_usd),
            )

        logger.info(
            "shot_lab_video_start",
            model=video_spec.model_id,
            candidate_id=candidate_id,
        )

        try:
            output, elapsed = await self._run_replicate_prediction(
                owner=video_spec.replicate_owner,
                name=video_spec.replicate_name,
                version_id=video_spec.version_id,
                inputs=inputs,
                timeout_seconds=360.0,
            )

            # Output URL extraction
            if isinstance(output, list) and output:
                vid_url = output[0]
            elif isinstance(output, str):
                vid_url = output
            else:
                raise RuntimeError(f"Unexpected video output format: {output}")

            async with httpx.AsyncClient(timeout=120.0) as client:
                vid_bytes = (await client.get(vid_url)).content
            local_path.write_bytes(vid_bytes)

            self.total_cost_usd += video_spec.cost_usd
            self._cache[candidate_id] = {
                "video_url": vid_url,
                "local_path": str(local_path),
                "latency_seconds": round(elapsed, 2),
                "cost_usd": video_spec.cost_usd,
            }
            self._save_cache()

            # Extract representative frames
            rep_frames = await self.extract_representative_frames(str(local_path), candidate_id)

            logger.info(
                "shot_lab_video_complete",
                candidate_id=candidate_id,
                elapsed=elapsed,
                cost=video_spec.cost_usd,
            )

            return VideoCandidateResult(
                candidate_id=candidate_id,
                video_model_id=video_spec.model_id,
                source_image_candidate_id=source_image.candidate_id,
                source_image_url=source_image.image_url,
                source_image_local_path=source_image.local_image_path,
                motion_prompt=motion_prompt,
                video_url=vid_url,
                local_video_path=str(local_path),
                representative_frames=rep_frames,
                latency_seconds=round(elapsed, 2),
                cost_usd=video_spec.cost_usd,
            )

        except Exception as exc:
            logger.exception("shot_lab_video_failed", candidate_id=candidate_id, error=str(exc))
            return VideoCandidateResult(
                candidate_id=candidate_id,
                video_model_id=video_spec.model_id,
                source_image_candidate_id=source_image.candidate_id,
                source_image_url=source_image.image_url,
                source_image_local_path=source_image.local_image_path,
                motion_prompt=motion_prompt,
                video_url="",
                local_video_path="",
                latency_seconds=0.0,
                cost_usd=0.0,
                error=str(exc),
            )

    # -----------------------------------------------------------------------
    # Frame Extraction & Contact Sheet Assembly
    # -----------------------------------------------------------------------

    async def extract_representative_frames(
        self,
        video_path: str,
        prefix: str,
        count: int = 5,
    ) -> List[str]:
        """Extract representative frames (0%, 25%, 50%, 75%, 100%) from an MP4."""
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if not ffmpeg or not os.path.exists(video_path):
            return []

        duration = 5.0
        if ffprobe:
            try:
                cmd = [
                    ffprobe, "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", video_path
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if res.returncode == 0:
                    duration = float(res.stdout.strip())
            except Exception:
                pass

        timestamps = [
            0.1,
            max(0.2, duration * 0.25),
            max(0.5, duration * 0.50),
            max(1.0, duration * 0.75),
            max(1.5, duration - 0.2),
        ]

        frame_paths: List[str] = []
        for i, ts in enumerate(timestamps[:count]):
            out_frame = self.output_dir / f"{prefix}_frame_{i:02d}.jpg"
            cmd = [
                ffmpeg, "-y", "-ss", str(ts), "-i", video_path,
                "-vframes", "1", "-q:v", "2", str(out_frame)
            ]
            proc = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, check=False)
            if proc.returncode == 0 and out_frame.exists():
                frame_paths.append(str(out_frame))

        return frame_paths

    def create_image_comparison_contact_sheet(
        self,
        images: List[ImageCandidateResult],
        output_filename: str = "image_model_shootout_contact_sheet.jpg",
    ) -> Optional[str]:
        """Create a high-resolution contact sheet comparing all image candidates."""
        valid_images = [img for img in images if img.local_image_path and os.path.exists(img.local_image_path)]
        if not valid_images:
            return None

        card_w, card_h = 360, 640
        padding = 24
        header_h = 100
        cols = min(3, len(valid_images))
        rows = (len(valid_images) + cols - 1) // cols

        sheet_w = (cols * card_w) + ((cols + 1) * padding)
        sheet_h = header_h + (rows * (card_h + 80)) + padding

        sheet = Image.new("RGB", (sheet_w, sheet_h), (18, 20, 24))
        draw = ImageDraw.Draw(sheet)

        # Title
        draw.text((padding, 24), "ARYA OS — TASK 23: CINEMATIC IMAGE MODEL SHOOTOUT", fill=(255, 255, 255))
        draw.text(
            (padding, 56),
            "Standardized Horror Scene: Father Thomas in Romanesque Crypt with Cracked Mirror",
            fill=(180, 185, 195),
        )

        for idx, img_res in enumerate(valid_images):
            r = idx // cols
            c = idx % cols
            x = padding + c * (card_w + padding)
            y = header_h + r * (card_h + 80)

            try:
                with Image.open(img_res.local_image_path) as im:
                    thumb = im.convert("RGB")
                    thumb.thumbnail((card_w, card_h), Image.Resampling.LANCZOS)
                    sheet.paste(thumb, (x, y))
            except Exception as exc:
                logger.warning("thumb_load_failed", path=img_res.local_image_path, error=str(exc))

            # Label box
            label_y = y + card_h + 6
            draw.text((x, label_y), f"Model: {img_res.model_id}", fill=(240, 200, 80))
            draw.text((x, label_y + 18), f"Strategy: {img_res.strategy.value}", fill=(200, 210, 225))
            draw.text((x, label_y + 36), f"Score: {img_res.rubric.image_subtotal:.2f}/10 | Cost: ${img_res.cost_usd:.4f}", fill=(100, 220, 130))

        out_path = self.output_dir / output_filename
        sheet.save(out_path, quality=92)
        return str(out_path)

    def create_video_comparison_contact_sheet(
        self,
        video_results: List[VideoCandidateResult],
        output_filename: str = "video_model_shootout_contact_sheet.jpg",
    ) -> Optional[str]:
        """Create a contact sheet showing representative frame progressions for each video model."""
        valid_videos = [v for v in video_results if v.representative_frames]
        if not valid_videos:
            return None

        frame_w, frame_h = 240, 426
        padding = 16
        header_h = 100
        cols = 5  # 5 frames per video
        rows = len(valid_videos)

        sheet_w = (cols * frame_w) + ((cols + 1) * padding)
        sheet_h = header_h + (rows * (frame_h + 90)) + padding

        sheet = Image.new("RGB", (sheet_w, sheet_h), (15, 17, 21))
        draw = ImageDraw.Draw(sheet)

        draw.text((padding, 24), "ARYA OS — TASK 23: IMAGE-TO-VIDEO CINEMATIC SHOOTOUT", fill=(255, 255, 255))
        draw.text(
            (padding, 56),
            "Temporal Consistency & Identity Preservation (0% -> 25% -> 50% -> 75% -> 100%)",
            fill=(180, 185, 195),
        )

        for r_idx, vid_res in enumerate(valid_videos):
            row_y = header_h + r_idx * (frame_h + 90)

            # Model title header for this row
            header_text = f"VIDEO MODEL: {vid_res.video_model_id.upper()} | From Image: {vid_res.source_image_candidate_id} | Video Score: {vid_res.rubric.video_subtotal:.2f}/10 | Cost: ${vid_res.cost_usd:.3f}"
            draw.text((padding, row_y), header_text, fill=(245, 210, 80))

            frame_top_y = row_y + 24
            for c_idx, frame_path in enumerate(vid_res.representative_frames[:5]):
                frame_x = padding + c_idx * (frame_w + padding)
                try:
                    with Image.open(frame_path) as fim:
                        thumb = fim.convert("RGB")
                        thumb.thumbnail((frame_w, frame_h), Image.Resampling.LANCZOS)
                        sheet.paste(thumb, (frame_x, frame_top_y))
                except Exception:
                    pass

                # Frame marker
                pct = [0, 25, 50, 75, 100][c_idx] if c_idx < 5 else c_idx
                draw.text((frame_x + 6, frame_top_y + frame_h - 22), f"{pct}%", fill=(255, 255, 255))

        out_path = self.output_dir / output_filename
        sheet.save(out_path, quality=92)
        return str(out_path)

    # -----------------------------------------------------------------------
    # Review Package & Dashboard Generation
    # -----------------------------------------------------------------------

    def generate_html_review_dashboard(
        self,
        image_results: List[ImageCandidateResult],
        video_results: List[VideoCandidateResult],
        output_filename: str = "index.html",
    ) -> str:
        """Generate a self-contained HTML dashboard for side-by-side human review."""
        html_lines = [
            "<!DOCTYPE html>",
            "<html lang='en'>",
            "<head>",
            "<meta charset='UTF-8'>",
            "<meta name='viewport' content='width=device-width, initial-scale=1.0'>",
            "<title>Arya OS — Task 23 Cinematic Visual Shootout Review</title>",
            "<style>",
            "  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #0c0d10; color: #d8dee9; margin: 0; padding: 24px; line-height: 1.5; }",
            "  h1, h2, h3 { color: #f8f9fa; font-weight: 600; }",
            "  .badge { display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }",
            "  .badge-pass { background: #1b4332; color: #40916c; border: 1px solid #2d6a4f; }",
            "  .badge-warn { background: #4a3e10; color: #ffd166; border: 1px solid #7c6818; }",
            "  .badge-fail { background: #491217; color: #f28482; border: 1px solid #842029; }",
            "  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 24px; margin-bottom: 40px; }",
            "  .card { background: #16181e; border: 1px solid #272a34; border-radius: 8px; overflow: hidden; padding: 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.5); }",
            "  .card img, .card video { width: 100%; border-radius: 6px; display: block; background: #000; }",
            "  .meta { margin-top: 12px; font-size: 13px; color: #9aa5b1; }",
            "  .meta strong { color: #f0c040; }",
            "  .prompt-box { background: #0f1013; padding: 10px; border-radius: 4px; font-size: 11px; font-family: monospace; max-height: 120px; overflow-y: auto; margin-top: 8px; border: 1px solid #1f232b; }",
            "  table { width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 13px; }",
            "  th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid #272a34; }",
            "  th { background: #1c1f27; color: #e2e8f0; font-weight: 600; }",
            "  tr:hover { background: #1f232b; }",
            "  .score-pill { font-weight: bold; color: #10b981; }",
            "</style>",
            "</head>",
            "<body>",
            "<h1>ARYA OS — TASK 23: CINEMATIC VISUAL SHOOTOUT & QUALITY DIAGNOSIS</h1>",
            "<p>Standardized Horror Test Scene: <em>Father Thomas in 12th-Century Crypt Chapel</em> | Total Experimental Spend: <strong>$" f"{self.total_cost_usd:.4f}</strong></p>",
            "<hr style='border: none; border-top: 1px solid #272a34; margin: 24px 0;'>",

            "<h2>1. Diagnostic Matrix</h2>",
            "<table>",
            "<thead><tr><th>Candidate ID</th><th>Type</th><th>Model</th><th>Prompt Strategy</th><th>Image Score</th><th>Video Score</th><th>Human Imp</th><th>Composite</th><th>Cost</th><th>Latency</th></tr></thead>",
            "<tbody>",
        ]

        # Add image rows
        for img in image_results:
            status_cls = "score-pill" if img.rubric.image_subtotal >= 8.5 else "badge-warn"
            html_lines.append(
                f"<tr><td><code>{img.candidate_id}</code></td><td>IMAGE</td><td>{img.model_id}</td><td>{img.strategy.value}</td>"
                f"<td class='{status_cls}'>{img.rubric.image_subtotal:.2f}/10</td><td>N/A</td><td>{img.rubric.human_subtotal:.2f}/10</td>"
                f"<td><strong>{img.rubric.composite_score:.2f}/10</strong></td><td>${img.cost_usd:.4f}</td><td>{img.latency_seconds}s</td></tr>"
            )

        # Add video rows
        for vid in video_results:
            status_cls = "score-pill" if vid.rubric.video_subtotal >= 8.5 else "badge-warn"
            html_lines.append(
                f"<tr><td><code>{vid.candidate_id}</code></td><td>VIDEO</td><td>{vid.video_model_id}</td><td>Motion Track</td>"
                f"<td>{vid.rubric.image_subtotal:.2f}/10</td><td class='{status_cls}'>{vid.rubric.video_subtotal:.2f}/10</td>"
                f"<td>{vid.rubric.human_subtotal:.2f}/10</td><td><strong>{vid.rubric.composite_score:.2f}/10</strong></td>"
                f"<td>${vid.cost_usd:.4f}</td><td>{vid.latency_seconds}s</td></tr>"
            )

        html_lines.extend([
            "</tbody></table>",
            "<h2 style='margin-top: 40px;'>2. Image Generation Shootout (Model × Prompt Strategy)</h2>",
            "<div class='grid'>",
        ])

        for img in image_results:
            if img.local_image_path and os.path.exists(img.local_image_path):
                rel_path = Path(img.local_image_path).name
                html_lines.append(
                    f"<div class='card'>"
                    f"<h3>{img.model_id.upper()} — {img.strategy.value}</h3>"
                    f"<img src='{rel_path}' alt='{img.candidate_id}'>"
                    f"<div class='meta'>"
                    f"<div><strong>Score:</strong> {img.rubric.image_subtotal:.2f}/10 | <strong>Cost:</strong> ${img.cost_usd:.4f} | <strong>Latency:</strong> {img.latency_seconds}s</div>"
                    f"<div><strong>Texture/Detail:</strong> {img.rubric.texture_detail}/10 | <strong>Realism:</strong> {img.rubric.realism}/10</div>"
                    f"</div>"
                    f"<div class='prompt-box'><strong>Prompt:</strong> {img.positive_prompt}</div>"
                    f"</div>"
                )
            else:
                html_lines.append(
                    f"<div class='card' style='opacity: 0.6;'>"
                    f"<h3>{img.model_id.upper()} — {img.strategy.value}</h3>"
                    f"<div style='height: 300px; display: flex; align-items: center; justify-content: center; background: #1a1d24; color: #f28482;'>UNAVAILABLE / ERROR: {img.error}</div>"
                    f"</div>"
                )

        html_lines.extend([
            "</div>",
            "<h2 style='margin-top: 40px;'>3. Image-to-Video Shootout (Generated Video & Keyframes)</h2>",
            "<div class='grid'>",
        ])

        for vid in video_results:
            if vid.local_video_path and os.path.exists(vid.local_video_path):
                vid_rel = Path(vid.local_video_path).name
                frames_html = "".join(
                    f"<img src='{Path(f).name}' style='width: 19%; display: inline-block; margin-right: 1%; border-radius: 2px;' />"
                    for f in vid.representative_frames
                )
                poster_attr = Path(vid.representative_frames[0]).name if vid.representative_frames else ""
                html_lines.append(
                    f"<div class='card'>"
                    f"<h3>{vid.video_model_id.upper()} (From: {vid.source_image_candidate_id})</h3>"
                    f"<video controls src='{vid_rel}' poster='{poster_attr}'></video>"
                    f"<div style='margin-top: 8px;'>{frames_html}</div>"
                    f"<div class='meta'>"
                    f"<div><strong>Motion Score:</strong> {vid.rubric.video_subtotal:.2f}/10 | <strong>Cost:</strong> ${vid.cost_usd:.4f} | <strong>Latency:</strong> {vid.latency_seconds}s</div>"
                    f"<div><strong>Identity:</strong> {vid.rubric.identity_preservation}/10 | <strong>Anatomy:</strong> {vid.rubric.anatomy_stability}/10 | <strong>Motion Realism:</strong> {vid.rubric.motion_realism}/10</div>"
                    f"</div>"
                    f"<div class='prompt-box'><strong>Motion Prompt:</strong> {vid.motion_prompt}</div>"
                    f"</div>"
                )
            else:
                html_lines.append(
                    f"<div class='card' style='opacity: 0.6;'>"
                    f"<h3>{vid.video_model_id.upper()}</h3>"
                    f"<div style='height: 300px; display: flex; align-items: center; justify-content: center; background: #1a1d24; color: #f28482;'>ERROR: {vid.error}</div>"
                    f"</div>"
                )

        html_lines.extend([
            "</div>",
            "</body></html>",
        ])

        out_html = self.output_dir / output_filename
        out_html.write_text("\n".join(html_lines), encoding="utf-8")
        return str(out_html)

    def mirror_all_to_desktop(self) -> None:
        """Mirror all artifacts from /tmp/ to ~/Desktop/ for operator human review."""
        try:
            for item in self.output_dir.iterdir():
                dest = self.desktop_dir / item.name
                if item.is_file():
                    shutil.copy2(str(item), str(dest))
                elif item.is_dir():
                    shutil.copytree(str(item), str(dest), dirs_exist_ok=True)
            logger.info("shot_lab_mirrored_to_desktop", source=str(self.output_dir), dest=str(self.desktop_dir))
        except Exception as exc:
            logger.warning("mirror_to_desktop_failed", error=str(exc))

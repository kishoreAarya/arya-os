"""Unit tests for Task 21 Visual Continuity, Narrative Story Coverage, and Keyframe Selection."""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.base import AgentResult
from app.agents.image import ImageAgent, ImageResult
from app.agents.storyboard import Shot
from app.schemas.cinematic import (
    CinematicPlan,
    CinematicShotPlan,
    GenerationClass,
    GenerationMode,
    NarrativeBeatType,
)
from app.services.keyframe_selector import (
    KeyframeSelectionResult,
    VisualCandidateScore,
    evaluate_candidate,
    select_best_keyframe,
)
from app.services.visual_continuity import (
    CharacterContinuity,
    CinematographyContinuity,
    ContinuityRisk,
    EnvironmentContinuity,
    PropContinuity,
    VisualContinuityBible,
    VisualRules,
    build_shot_continuity_context,
    check_shot_continuity_risk,
)


def test_visual_continuity_bible_schema():
    """Verify VisualContinuityBible model instantiation and validation."""
    char = CharacterContinuity(
        character_id="char_elena",
        name="Elena Vance",
        visual_description="30s, olive complexion, intense dark eyes, sharp jawline, hollow cheekbones",
        wardrobe="Charcoal wool coat over fraying burgundy knit sweater",
        anchor_details=["Silver signet ring on right thumb", "Small vertical scar across left eyebrow"],
    )
    env = EnvironmentContinuity(
        environment_id="env_cellar",
        name="Victorian Wine Cellar",
        architecture_style="19th-century vaulted brick masonry",
        key_surfaces="Damp crumbling mortar, mossy stone slabs",
        color_palette=["#0D1117", "#161B22", "#3D2B1F"],
        lighting_anchors=["Single bare incandescent bulb swinging from cloth cord", "Weak moonlight through iron grate"],
    )
    prop = PropContinuity(
        prop_id="prop_mirror",
        name="The Weeping Mirror",
        description="Tall rococo standing mirror with tarnished silver frame",
        materials="Tarnished blackened silver, mercury glass with dark age-spots",
        visual_markers=["Hairline diagonal crack from top right", "Ornate serpent crest at apex"],
    )
    cin = CinematographyContinuity(
        aspect_ratio="9:16",
        primary_lens_character="Cooke 35mm anamorphic prime with shallow DOF",
        lighting_philosophy="Motivated single-source practical key with deep shadow roll-off",
        color_grading_rules="Muted desaturated shadows with sickly cyan undertones",
    )
    rules = VisualRules(
        prohibited_elements=["text", "captions", "subtitles", "plastic CGI skin"],
        required_elements=["motivated practical lighting", "organic film grain"],
    )

    bible = VisualContinuityBible(
        title="The Mirror's Grasp",
        genre="Gothic Horror",
        characters=[char],
        environments=[env],
        props=[prop],
        cinematography=cin,
        rules=rules,
    )

    assert bible.title == "The Mirror's Grasp"
    assert len(bible.characters) == 1
    assert bible.characters[0].name == "Elena Vance"
    assert len(bible.environments) == 1
    assert len(bible.props) == 1
    assert bible.cinematography.aspect_ratio == "9:16"


def test_build_shot_continuity_context():
    """Verify compact continuity injection extracts relevant anchors without prompt bloat."""
    bible = VisualContinuityBible(
        characters=[
            CharacterContinuity(
                character_id="char_marcus",
                name="Marcus",
                visual_description="Weathered 40s man with grey-streaked beard",
                wardrobe="Heavy tweed work jacket with brass buttons",
                anchor_details=["Brass pocket watch chain visible", "Bandaged right palm"],
            )
        ],
        environments=[
            EnvironmentContinuity(
                environment_id="env_attic",
                name="Dusty Attic",
                architecture_style="Exposed timber rafters, cedar planking",
                key_surfaces="Thick dust over dark heart-pine floorboards",
                lighting_anchors=["Flickering lantern on packing crate"],
            )
        ],
        props=[
            PropContinuity(
                prop_id="prop_diary",
                name="Leather Journal",
                description="Small black leather-bound diary with brass clasp",
                materials="Cracked calfskin leather, yellowed parchment pages",
                visual_markers=["Embossed ouroboros emblem on cover"],
            )
        ],
    )

    shot = CinematicShotPlan(
        shot_number=1,
        subject="Marcus",
        environment="Dusty Attic",
        action="Marcus enters the dusty attic holding the leather journal.",
    )

    ctx = build_shot_continuity_context(bible, shot)
    assert "Visual Tone:" in ctx
    assert "Character Continuity: Marcus:" in ctx
    assert "Brass pocket watch chain" in ctx
    assert "Environment Anchors: Dusty Attic" in ctx
    assert "Prop Anchors: Leather Journal" in ctx
    # Ensure it's compact (not a massive multi-page dump)
    assert len(ctx) < 800


def test_check_shot_continuity_risk():
    """Verify continuity risk detector identifies jarring jumps."""
    shot_a = CinematicShotPlan(
        shot_number=1,
        subject="Elena Vance",
        environment="Dark stone basement at midnight",
        lighting="Flickering warm candle light, deep shadows",
    )
    # Abrupt day jump in shot B
    shot_b = CinematicShotPlan(
        shot_number=2,
        subject="Elena Vance",
        environment="Sunlit cornfield afternoon",
        lighting="Blinding bright sunlight, no shadows",
    )

    result = check_shot_continuity_risk(shot_a, shot_b)
    assert result.risk_level in (ContinuityRisk.HIGH, ContinuityRisk.MEDIUM)
    assert any("Temporal lighting shift" in m for m in result.mismatches)
    assert result.score < 8.0

    # Smooth continuity between compatible night shots
    shot_c = CinematicShotPlan(
        shot_number=3,
        subject="Elena Vance",
        environment="Dark stone cellar corridor",
        lighting="Dim amber lantern light in background, cool shadow spill",
    )
    result_smooth = check_shot_continuity_risk(shot_a, shot_c)
    assert result_smooth.risk_level == ContinuityRisk.LOW
    assert result_smooth.score >= 8.0


def test_narrative_beat_type_and_shot_plan():
    """Verify narrative beats are correctly assigned and forwarded to Storyboard Shot."""
    shot = CinematicShotPlan(
        shot_number=1,
        duration_seconds=3.5,
        narrative_beat=NarrativeBeatType.HOOK,
        visual_purpose="Visceral hook introducing the haunted artifact",
        continuity_dependency=None,
        subject="Antique mirror",
        action="Vibrates with sudden unnatural tremor",
        environment="Victorian parlor",
        generation_class=GenerationClass.A,
        generation_mode=GenerationMode.VIDEO,
    )

    assert shot.narrative_beat == NarrativeBeatType.HOOK
    assert shot.visual_purpose == "Visceral hook introducing the haunted artifact"

    sb_shot = shot.to_storyboard_shot()
    assert sb_shot.narrative_beat == "HOOK"
    assert sb_shot.visual_purpose == "Visceral hook introducing the haunted artifact"


def test_evaluate_candidate_mock_scoring():
    """Verify candidate scoring accurately rates dynamic range and penalizes defects."""
    # Ideal cinematic horror frame: good dynamic range, high edge energy, correct 9:16 aspect ratio
    good_mock = {
        "width": 1080,
        "height": 1920,
        "mean_luminance": 60.0,
        "stddev_luminance": 38.0,
        "edge_energy": 28.0,
        "has_black_bars": False,
    }
    score_good = evaluate_candidate(
        candidate_index=0,
        image_path_or_url="/mock/good.png",
        prompt="Elena in dark Victorian cellar, motivated practical candle light",
        aspect_ratio="9:16",
        continuity_context="Character Continuity: Elena [Anchors: scar on eyebrow]",
        mock_data=good_mock,
    )
    assert score_good.total_score >= 8.0
    assert score_good.artifact_penalty == 0.0

    # Defective frame: black bars (letterboxing), crushed flat pixels, wrong aspect ratio
    bad_mock = {
        "width": 1080,
        "height": 1080,  # 1:1 square instead of 9:16
        "mean_luminance": 12.0,
        "stddev_luminance": 8.0,  # flat waxy
        "edge_energy": 6.0,  # muddy/blurry
        "has_black_bars": True,
    }
    score_bad = evaluate_candidate(
        candidate_index=1,
        image_path_or_url="/mock/bad.png",
        prompt="Elena in dark cellar",
        aspect_ratio="9:16",
        mock_data=bad_mock,
    )
    assert score_bad.total_score < 6.0
    assert score_bad.artifact_penalty > 1.0
    assert any("black letterbox" in p for p in score_bad.penalties_applied)


def test_select_best_keyframe_deterministic():
    """Verify select_best_keyframe picks the highest-scoring candidate."""
    mock_candidates = [
        {"width": 1080, "height": 1920, "mean_luminance": 15.0, "stddev_luminance": 10.0, "edge_energy": 8.0, "has_black_bars": False},
        {"width": 1080, "height": 1920, "mean_luminance": 70.0, "stddev_luminance": 42.0, "edge_energy": 32.0, "has_black_bars": False},
        {"width": 1080, "height": 1920, "mean_luminance": 120.0, "stddev_luminance": 25.0, "edge_energy": 14.0, "has_black_bars": True},
    ]
    cand_urls = ["https://img.arya/cand_0.png", "https://img.arya/cand_1.png", "https://img.arya/cand_2.png"]

    sel_res = select_best_keyframe(
        candidates=cand_urls,
        prompt="Elena discovers weeping mirror in cellar",
        aspect_ratio="9:16",
        candidate_mock_data=mock_candidates,
    )

    assert isinstance(sel_res, KeyframeSelectionResult)
    # Candidate 1 has high dynamic range, sharp edge energy, no black bars
    assert sel_res.selected_index == 1
    assert sel_res.selected_candidate.candidate_url == "https://img.arya/cand_1.png"
    assert sel_res.selected_candidate.total_score > sel_res.all_candidates[0].total_score
    assert sel_res.selected_candidate.total_score > sel_res.all_candidates[2].total_score


@pytest.mark.asyncio
async def test_image_agent_multi_candidate_selection():
    """Verify ImageAgent selects the best candidate when multiple candidates are returned."""
    mock_exec_engine = AsyncMock()
    mock_exec_engine.execute.return_value = type(
        "ExecResStub",
        (),
        {
            "success": True,
            "error": None,
            "provider": "replicate",
            "cost_usd": 0.06,
            "elapsed_time": 2.1,
            "output": {
                "storage_path": "https://img.arya/cand_0.png",
                "candidate_urls": [
                    "https://img.arya/cand_0.png",
                    "https://img.arya/cand_1.png",
                    "https://img.arya/cand_2.png",
                ],
            },
        },
    )()

    mock_db = AsyncMock()
    agent = ImageAgent(db=mock_db)
    agent._execution_engine = mock_exec_engine

    with patch("app.services.keyframe_selector.select_best_keyframe") as mock_select:
        mock_winner = VisualCandidateScore(
            candidate_index=1,
            candidate_url="https://img.arya/cand_1_winner.png",
            composition_score=9.0,
            subject_quality_score=9.0,
            anatomy_score=9.0,
            lighting_score=9.0,
            realism_score=9.0,
            continuity_score=9.0,
            prompt_adherence_score=9.0,
            artifact_penalty=0.0,
            total_score=9.0,
            selection_reasons=["Optimal composition", "High contrast lighting"],
        )
        mock_select.return_value = KeyframeSelectionResult(
            selected_index=1,
            selected_candidate=mock_winner,
            all_candidates=[mock_winner],
            selection_summary="Selected candidate 1",
        )

        res = await agent.run({
            "shot_description": "Elena reaches toward the tarnished mirror",
            "num_keyframe_candidates": 3,
            "aspect_ratio": "9:16",
        })

        assert res.success is True
        img_res = res.output["image_result"]
        assert isinstance(img_res, ImageResult)
        # Verify selected winner was set as the master storage_path
        assert img_res.storage_path == "https://img.arya/cand_1_winner.png"
        assert len(img_res.candidate_urls) == 3
        assert res.output["keyframe_selection"]["selected_index"] == 1

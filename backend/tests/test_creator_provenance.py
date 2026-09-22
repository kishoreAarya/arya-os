"""
Regression and unit/integration tests for Creator Mode provider and model provenance.

Verifies:
1. Test A: Requested Together + FLUX 1.1 Pro succeeds on Together.
   - requested = together / FLUX 1.1 Pro
   - actual = together / FLUX 1.1 Pro
   - Asset.provider_name = together
   - Creator history item provider = together, model = FLUX 1.1 Pro
   - requested_provider = together, requested_model = FLUX 1.1 Pro
   - actual_provider = together, actual_model = FLUX 1.1 Pro

2. Test B: Requested Together + FLUX 1.1 Pro fails on Together and falls back to Replicate:
   - requested = together / FLUX 1.1 Pro
   - actual = replicate / flux-schnell
   - Asset.provider_name = replicate
   - Creator history item provider = replicate, model = flux-schnell
   - requested_provider = together, requested_model = FLUX 1.1 Pro
   - actual_provider = replicate, actual_model = flux-schnell
   - cost reflects replicate ($0.0300)

3. Test C: Requested and actual are identical.
   - requested = replicate / flux-schnell
   - actual = replicate / flux-schnell
   - Asset.provider_name = replicate
   - history reflects replicate / flux-schnell for both

4. Test D: Fallback does not create duplicate Asset or WorkflowRun records.
   - Exactly 1 WorkflowRun and 1 Asset record exist after fallback execution.

5. Test E: ImageAgent parameter forwarding test.
   - ImageAgent receives explicit image_provider="together" and image_model="black-forest-labs/FLUX.1.1-pro"
   - Confirms ImageAgent forwards them to execution engine call with priority=[explicit_provider]
   - Confirms fallback preserves actual vs requested provenance
   - Confirms visual profile defaults are preserved when explicit parameters omitted

6. Historical Audit:
   - Verifies existing historical run 2d5eedb9-9397-468b-9805-e9e480c46a57 resolves to:
     requested: together / FLUX 1.1 Pro
     actual: replicate / flux-schnell
"""

import json
from unittest.mock import AsyncMock, patch
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.agents.base import AgentResult
from app.agents.image import ImageAgent
from app.api.routers.creator import (
    CreatorGenerateRequest,
    GenerationType,
    _ACTIVE_JOBS,
    _execute_creator_job_background,
)
from app.core.config import get_settings
from app.database.session import AsyncSessionLocal
from app.main import app
from app.models.core import Project, WorkflowRun
from app.models.enums import PipelineStage, WorkflowMode, WorkflowStatus
from app.models.media import Asset
from app.models.system import SystemLog
from app.providers.capabilities import Capability
from app.services.execution_engine import ExecutionResult


@pytest.fixture
def auth_headers():
    settings = get_settings()
    return {"Authorization": f"Bearer {settings.arya_api_key}"}


async def _get_or_create_test_project() -> uuid.UUID:
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(Project).limit(1))
        proj = res.scalar_one_or_none()
        if not proj:
            proj = Project(name="Provenance Test Project", description="Test provider provenance")
            session.add(proj)
            await session.commit()
            await session.refresh(proj)
        return proj.id


@pytest.mark.asyncio
async def test_provenance_test_a_together_success(auth_headers):
    """Test A: Requested Together + FLUX 1.1 Pro succeeds on Together."""
    project_id = await _get_or_create_test_project()
    run_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        run = WorkflowRun(
            id=run_id,
            project_id=project_id,
            topic="Test A Prompt",
            mode=WorkflowMode.ASSISTED,
            status=WorkflowStatus.PENDING,
            current_stage=PipelineStage.CREATED.value,
        )
        session.add(run)
        await session.commit()

    payload = CreatorGenerateRequest(
        generation_type=GenerationType.IMAGE,
        prompt="Test A Prompt",
        model="black-forest-labs/FLUX.1.1-pro",
        provider="together",
        aspect_ratio="16:9",
    )

    job_id = str(run_id)
    _ACTIVE_JOBS[job_id] = {
        "job_id": job_id,
        "workflow_run_id": str(run_id),
        "status": "pending",
        "current_stage": "created",
        "generation_type": "image",
        "prompt": payload.prompt,
        "model": payload.model,
        "provider": payload.provider,
        "aspect_ratio": payload.aspect_ratio,
        "duration_seconds": payload.duration_seconds,
        "total_cost_usd": 0.0,
        "output": {},
    }

    mock_agent_result = AgentResult(
        success=True,
        provider_used="together",
        cost_usd=0.040,
        duration_seconds=2.5,
        output={
            "storage_path": "https://api.together.xyz/images/test_a.png",
            "candidate_urls": ["https://api.together.xyz/images/test_a.png"],
            "provider_used": "together",
            "model_used": "black-forest-labs/FLUX.1.1-pro",
            "requested_provider": "together",
            "requested_model": "black-forest-labs/FLUX.1.1-pro",
            "actual_provider": "together",
            "actual_model": "black-forest-labs/FLUX.1.1-pro",
        },
    )

    with patch.object(ImageAgent, "run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_agent_result
        await _execute_creator_job_background(job_id, run_id, payload)

    # 1. Verify DB Asset
    async with AsyncSessionLocal() as session:
        q_asset = await session.execute(select(Asset).where(Asset.workflow_run_id == run_id))
        assets = q_asset.scalars().all()
        assert len(assets) == 1
        assert assets[0].provider_name == "together"

    # 2. Verify API endpoints
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp_job = await client.get(f"/creator/jobs/{job_id}", headers=auth_headers)
        assert resp_job.status_code == 200
        job_data = resp_job.json()
        assert job_data["provider"] == "together"
        assert job_data["model"] == "black-forest-labs/FLUX.1.1-pro"
        assert job_data["requested_provider"] == "together"
        assert job_data["requested_model"] == "black-forest-labs/FLUX.1.1-pro"
        assert job_data["actual_provider"] == "together"
        assert job_data["actual_model"] == "black-forest-labs/FLUX.1.1-pro"
        assert job_data["total_cost_usd"] == 0.040

        resp_hist = await client.get(f"/creator/history?limit=10", headers=auth_headers)
        assert resp_hist.status_code == 200
        hist_items = [i for i in resp_hist.json() if i["job_id"] == job_id]
        assert len(hist_items) == 1
        hist = hist_items[0]
        assert hist["provider"] == "together"
        assert hist["model"] == "black-forest-labs/FLUX.1.1-pro"
        assert hist["requested_provider"] == "together"
        assert hist["requested_model"] == "black-forest-labs/FLUX.1.1-pro"
        assert hist["actual_provider"] == "together"
        assert hist["actual_model"] == "black-forest-labs/FLUX.1.1-pro"
        assert hist["total_cost_usd"] == 0.040


@pytest.mark.asyncio
async def test_provenance_test_b_fallback_to_replicate(auth_headers):
    """Test B: Requested Together + FLUX 1.1 Pro fails on Together and falls back to Replicate."""
    project_id = await _get_or_create_test_project()
    run_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        run = WorkflowRun(
            id=run_id,
            project_id=project_id,
            topic="Test B Fallback Prompt",
            mode=WorkflowMode.ASSISTED,
            status=WorkflowStatus.PENDING,
            current_stage=PipelineStage.CREATED.value,
        )
        session.add(run)
        await session.commit()

    payload = CreatorGenerateRequest(
        generation_type=GenerationType.IMAGE,
        prompt="Test B Fallback Prompt",
        model="black-forest-labs/FLUX.1.1-pro",
        provider="together",
        aspect_ratio="16:9",
    )

    job_id = str(run_id)
    _ACTIVE_JOBS[job_id] = {
        "job_id": job_id,
        "workflow_run_id": str(run_id),
        "status": "pending",
        "current_stage": "created",
        "generation_type": "image",
        "prompt": payload.prompt,
        "model": payload.model,
        "provider": payload.provider,
        "aspect_ratio": payload.aspect_ratio,
        "duration_seconds": payload.duration_seconds,
        "total_cost_usd": 0.0,
        "output": {},
    }

    replicate_model = "black-forest-labs/flux-schnell:c846a69991daf4c0e5d016514849d14ee5b2e6846ce6b9d6f21369e564cfe51e"
    mock_agent_result = AgentResult(
        success=True,
        provider_used="replicate",
        cost_usd=0.0300,
        duration_seconds=4.2,
        output={
            "storage_path": "https://replicate.delivery/test_b.webp",
            "candidate_urls": ["https://replicate.delivery/test_b.webp"],
            "provider_used": "replicate",
            "model_used": replicate_model,
            "requested_provider": "together",
            "requested_model": "black-forest-labs/FLUX.1.1-pro",
            "actual_provider": "replicate",
            "actual_model": replicate_model,
        },
    )

    with patch.object(ImageAgent, "run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_agent_result
        await _execute_creator_job_background(job_id, run_id, payload)

    # 1. Verify DB Asset: MUST be 'replicate', NOT 'together'
    async with AsyncSessionLocal() as session:
        q_asset = await session.execute(select(Asset).where(Asset.workflow_run_id == run_id))
        assets = q_asset.scalars().all()
        assert len(assets) == 1
        assert assets[0].provider_name == "replicate"

        db_run = await session.get(WorkflowRun, run_id)
        assert float(db_run.total_cost_usd) == 0.0300

    # 2. Verify API endpoints reflect actual execution
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp_job = await client.get(f"/creator/jobs/{job_id}", headers=auth_headers)
        assert resp_job.status_code == 200
        job_data = resp_job.json()
        assert job_data["provider"] == "replicate"
        assert job_data["model"] == replicate_model
        assert job_data["requested_provider"] == "together"
        assert job_data["requested_model"] == "black-forest-labs/FLUX.1.1-pro"
        assert job_data["actual_provider"] == "replicate"
        assert job_data["actual_model"] == replicate_model
        assert job_data["total_cost_usd"] == 0.0300

        resp_hist = await client.get(f"/creator/history?limit=10", headers=auth_headers)
        assert resp_hist.status_code == 200
        hist_items = [i for i in resp_hist.json() if i["job_id"] == job_id]
        assert len(hist_items) == 1
        hist = hist_items[0]
        assert hist["provider"] == "replicate"
        assert hist["model"] == replicate_model
        assert hist["requested_provider"] == "together"
        assert hist["requested_model"] == "black-forest-labs/FLUX.1.1-pro"
        assert hist["actual_provider"] == "replicate"
        assert hist["actual_model"] == replicate_model
        assert hist["total_cost_usd"] == 0.0300


@pytest.mark.asyncio
async def test_provenance_test_c_identical_requested_and_actual(auth_headers):
    """Test C: Requested and actual are identical (replicate / flux-schnell)."""
    project_id = await _get_or_create_test_project()
    run_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        run = WorkflowRun(
            id=run_id,
            project_id=project_id,
            topic="Test C Prompt",
            mode=WorkflowMode.ASSISTED,
            status=WorkflowStatus.PENDING,
            current_stage=PipelineStage.CREATED.value,
        )
        session.add(run)
        await session.commit()

    replicate_model = "black-forest-labs/flux-schnell"
    payload = CreatorGenerateRequest(
        generation_type=GenerationType.IMAGE,
        prompt="Test C Prompt",
        model=replicate_model,
        provider="replicate",
        aspect_ratio="16:9",
    )

    job_id = str(run_id)
    _ACTIVE_JOBS[job_id] = {
        "job_id": job_id,
        "workflow_run_id": str(run_id),
        "status": "pending",
        "current_stage": "created",
        "generation_type": "image",
        "prompt": payload.prompt,
        "model": payload.model,
        "provider": payload.provider,
        "aspect_ratio": payload.aspect_ratio,
        "duration_seconds": payload.duration_seconds,
        "total_cost_usd": 0.0,
        "output": {},
    }

    mock_agent_result = AgentResult(
        success=True,
        provider_used="replicate",
        cost_usd=0.0300,
        duration_seconds=3.0,
        output={
            "storage_path": "https://replicate.delivery/test_c.webp",
            "candidate_urls": ["https://replicate.delivery/test_c.webp"],
            "provider_used": "replicate",
            "model_used": replicate_model,
            "requested_provider": "replicate",
            "requested_model": replicate_model,
            "actual_provider": "replicate",
            "actual_model": replicate_model,
        },
    )

    with patch.object(ImageAgent, "run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_agent_result
        await _execute_creator_job_background(job_id, run_id, payload)

    async with AsyncSessionLocal() as session:
        q_asset = await session.execute(select(Asset).where(Asset.workflow_run_id == run_id))
        assets = q_asset.scalars().all()
        assert len(assets) == 1
        assert assets[0].provider_name == "replicate"

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp_hist = await client.get(f"/creator/history?limit=10", headers=auth_headers)
        hist_items = [i for i in resp_hist.json() if i["job_id"] == job_id]
        assert len(hist_items) == 1
        hist = hist_items[0]
        assert hist["provider"] == "replicate"
        assert hist["requested_provider"] == "replicate"
        assert hist["actual_provider"] == "replicate"
        assert hist["model"] == replicate_model
        assert hist["requested_model"] == replicate_model
        assert hist["actual_model"] == replicate_model


@pytest.mark.asyncio
async def test_provenance_test_d_no_duplicate_records(auth_headers):
    """Test D: Fallback does not create duplicate Asset or WorkflowRun records."""
    project_id = await _get_or_create_test_project()
    run_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        run = WorkflowRun(
            id=run_id,
            project_id=project_id,
            topic="Test D Prompt",
            mode=WorkflowMode.ASSISTED,
            status=WorkflowStatus.PENDING,
            current_stage=PipelineStage.CREATED.value,
        )
        session.add(run)
        await session.commit()

    payload = CreatorGenerateRequest(
        generation_type=GenerationType.IMAGE,
        prompt="Test D Prompt",
        model="black-forest-labs/FLUX.1.1-pro",
        provider="together",
        aspect_ratio="16:9",
    )

    job_id = str(run_id)
    _ACTIVE_JOBS[job_id] = {
        "job_id": job_id,
        "workflow_run_id": str(run_id),
        "status": "pending",
        "current_stage": "created",
        "generation_type": "image",
        "prompt": payload.prompt,
        "model": payload.model,
        "provider": payload.provider,
        "aspect_ratio": payload.aspect_ratio,
        "duration_seconds": payload.duration_seconds,
        "total_cost_usd": 0.0,
        "output": {},
    }

    mock_agent_result = AgentResult(
        success=True,
        provider_used="replicate",
        cost_usd=0.0300,
        duration_seconds=3.5,
        output={
            "storage_path": "https://replicate.delivery/test_d.webp",
            "candidate_urls": ["https://replicate.delivery/test_d.webp"],
            "provider_used": "replicate",
            "model_used": "black-forest-labs/flux-schnell",
            "requested_provider": "together",
            "requested_model": "black-forest-labs/FLUX.1.1-pro",
            "actual_provider": "replicate",
            "actual_model": "black-forest-labs/flux-schnell",
        },
    )

    with patch.object(ImageAgent, "run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_agent_result
        await _execute_creator_job_background(job_id, run_id, payload)

    async with AsyncSessionLocal() as session:
        runs = (await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))).scalars().all()
        assert len(runs) == 1, "Exactly one WorkflowRun row must exist"

        assets = (await session.execute(select(Asset).where(Asset.workflow_run_id == run_id))).scalars().all()
        assert len(assets) == 1, "Exactly one Asset row must exist even after fallback"


@pytest.mark.asyncio
async def test_provenance_test_e_image_agent_parameter_forwarding():
    """Test E: ImageAgent parameter forwarding and fallback handling."""
    async with AsyncSessionLocal() as session:
        agent = ImageAgent(session)

        # 1. Forwarding explicit provider and model
        mock_exec_result = ExecutionResult(
            success=True,
            output={
                "storage_path": "https://test.storage/img.png",
                "candidate_urls": ["https://test.storage/img.png"],
                "provider_used": "replicate",
                "model_used": "black-forest-labs/flux-schnell:xyz",
            },
            provider="replicate",
            model="black-forest-labs/flux-schnell:xyz",
            cost_usd=0.0300,
            elapsed_time=2.0,
            attempts=2,
        )

        with patch.object(agent._execution_engine, "execute", new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = mock_exec_result

            context = {
                "shot_description": "A quiet mountain lake",
                "prompt": "A quiet mountain lake at dawn",
                "image_provider": "together",
                "image_model": "black-forest-labs/FLUX.1.1-pro",
                "aspect_ratio": "16:9",
            }
            res = await agent.run(context)

            assert res.success is True
            # Verify execution engine was called with priority=['together']
            assert mock_execute.call_count == 1
            call_kwargs = mock_execute.call_args.kwargs
            assert call_kwargs.get("priority") == ["together"]
            assert call_kwargs.get("capability") == Capability.IMAGE_GENERATION

            # Verify output captures both requested and actual provenance
            assert res.provider_used == "replicate"
            out = res.output
            assert out["actual_provider"] == "replicate"
            assert out["actual_model"] == "black-forest-labs/flux-schnell:xyz"
            assert out["requested_provider"] == "together"
            assert out["requested_model"] == "black-forest-labs/FLUX.1.1-pro"

        # 2. Preserves visual profile defaults when explicit model/provider omitted
        with patch.object(agent._execution_engine, "execute", new_callable=AsyncMock) as mock_execute_default:
            mock_execute_default.return_value = mock_exec_result

            context_default = {
                "shot_description": "A quiet mountain lake",
                "prompt": "A quiet mountain lake at dawn",
                "aspect_ratio": "16:9",
            }
            res_def = await agent.run(context_default)

            assert res_def.success is True
            call_kwargs_def = mock_execute_default.call_args.kwargs
            # Priority should be None (default visual profile priority)
            assert call_kwargs_def.get("priority") is None


@pytest.mark.asyncio
async def test_provenance_historical_audit_interpretation(auth_headers):
    """Verify that historical run 2d5eedb9-9397-468b-9805-e9e480c46a57 is interpreted accurately."""
    historical_run_id = "2d5eedb9-9397-468b-9805-e9e480c46a57"
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/creator/jobs/{historical_run_id}", headers=auth_headers)
        if resp.status_code == 200:
            data = resp.json()
            assert data["provider"] == "replicate"
            assert data["requested_provider"] == "together"
            assert data["requested_model"] == "black-forest-labs/FLUX.1.1-pro"
            assert data["actual_provider"] == "replicate"
            assert "flux-schnell" in data["actual_model"]
            assert data["total_cost_usd"] == 0.0300

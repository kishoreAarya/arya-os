"""
Artifact lineage.

Beginner note: `Artifact` (models/system.py) already indexes every
output of a run by (reference_table, reference_id). This file is the
read side of that: given a WorkflowRun, walk every Artifact it
produced plus the provider call, quality score, and approval decision
tied to each one, so "trace this published video back to its exact
trend, prompt, model, provider, validator results, and template
version" is one function call instead of seven manual joins.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalCheckpoint, GenerationAttempt
from app.models.core import WorkflowRun
from app.models.quality import QualityScoreDetail
from app.models.system import Artifact


async def get_lineage(db: AsyncSession, workflow_run_id: uuid.UUID) -> dict:
    run = await db.get(WorkflowRun, workflow_run_id)
    if run is None:
        raise ValueError(f"WorkflowRun {workflow_run_id} not found")

    artifacts_result = await db.execute(
        select(Artifact)
        .where(Artifact.workflow_run_id == workflow_run_id)
        .order_by(Artifact.created_at.asc())
    )
    artifacts = list(artifacts_result.scalars().all())

    trace = []
    for artifact in artifacts:
        quality_result = await db.execute(
            select(QualityScoreDetail).where(
                QualityScoreDetail.reference_table == artifact.reference_table,
                QualityScoreDetail.reference_id == artifact.reference_id,
            )
        )
        attempts_result = await db.execute(
            select(GenerationAttempt)
            .where(
                GenerationAttempt.reference_table == artifact.reference_table,
                GenerationAttempt.reference_id == artifact.reference_id,
            )
            .order_by(GenerationAttempt.attempt_number.asc())
        )
        approval_result = await db.execute(
            select(ApprovalCheckpoint).where(
                ApprovalCheckpoint.reference_table == artifact.reference_table,
                ApprovalCheckpoint.reference_id == artifact.reference_id,
            )
        )

        trace.append(
            {
                "artifact_type": artifact.artifact_type.value,
                "reference_table": artifact.reference_table,
                "reference_id": str(artifact.reference_id),
                "version": artifact.version,
                "created_at": artifact.created_at.isoformat(),
                "quality_scores": [
                    {"dimension": q.dimension, "score": float(q.score), "scored_by": q.scored_by}
                    for q in quality_result.scalars().all()
                ],
                "generation_attempts": [
                    {
                        "attempt_number": a.attempt_number,
                        "succeeded": a.succeeded,
                        "failure_reason": a.failure_reason,
                        "provider_id": str(a.provider_id) if a.provider_id else None,
                        "cost_usd": float(a.cost_usd),
                    }
                    for a in attempts_result.scalars().all()
                ],
                "approval": [
                    {
                        "stage": c.stage.value,
                        "action": c.action.value if c.action else None,
                        "decided_at": c.decided_at.isoformat() if c.decided_at else None,
                    }
                    for c in approval_result.scalars().all()
                ],
            }
        )

    return {
        "workflow_run_id": str(run.id),
        "topic": run.topic,
        "status": run.status.value,
        "current_stage": run.current_stage,
        "total_cost_usd": float(run.total_cost_usd),
        "trace": trace,
    }

"""
AryaOS V1 Phase 13 — Shot Dependency Graph & Multi-Shot Scheduling Service.

Constructs, validates, and manages the temporal production graph:
- Directed dependency edges (predecessor -> successor).
- Linear shot sequences (SHOT 01 -> SHOT 02 -> SHOT 03).
- Branching trees (SHOT 01 -> SHOT 02, SHOT 01 -> SHOT 03).
- Graph cycle detection with immediate rejection of circular dependencies.
- Downstream successor unlocking upon verified predecessor completion.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.production import ProductionShot
from app.schemas.production import (
    ShotGraphEdge,
    ShotGraphNode,
    ShotGraphResponse,
    TelemetryEvent,
)
from app.services.continuity_validator import continuity_validator
from app.services.production_service import emit_telemetry_event

logger = get_logger("arya.services.shot_graph")


class ShotGraphService:
    """Manages multi-shot dependency graphs and temporal execution propagation."""

    async def build_graph(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
    ) -> ShotGraphResponse:
        """Constructs the complete dependency graph for a project."""
        stmt = select(ProductionShot).where(ProductionShot.project_id == project_id).order_by(ProductionShot.shot_number)
        shots = list((await db.execute(stmt)).scalars().all())

        nodes: list[ShotGraphNode] = []
        edges: list[ShotGraphEdge] = []
        successors_map: dict[str, list[str]] = {str(s.id): [] for s in shots}

        # First pass: map successors and edges
        for shot in shots:
            if shot.predecessor_shot_id and shot.predecessor_shot_id in successors_map:
                successors_map[shot.predecessor_shot_id].append(str(shot.id))

                pred_shot = next((s for s in shots if str(s.id) == shot.predecessor_shot_id), None)
                edge_status = "SATISFIED" if (pred_shot and pred_shot.status == "COMPLETE") else "PENDING"
                if pred_shot and pred_shot.status == "FAILED":
                    edge_status = "BLOCKED"

                edges.append(
                    ShotGraphEdge(
                        source_shot_id=shot.predecessor_shot_id,
                        target_shot_id=str(shot.id),
                        relationship_type="last_frame_to_first_frame",
                        status=edge_status,
                    )
                )

        # Detect cycles
        has_cycles, cycle_nodes = self.detect_cycles(shots)

        # Build nodes
        roots: list[str] = []
        shots_by_id = {str(s.id): s for s in shots}
        for shot in shots:
            shot_str_id = str(shot.id)
            if not shot.predecessor_shot_id:
                roots.append(shot_str_id)

            meta = shot.metadata_json or {}
            frame_anchors = meta.get("frame_anchors", {})

            can_dispatch, reason = await self.validate_can_dispatch(shot, db)
            unmet = [shot.predecessor_shot_id] if not can_dispatch and shot.predecessor_shot_id else []

            nodes.append(
                ShotGraphNode(
                    shot_id=shot_str_id,
                    sequence_id=str(shot.sequence_id),
                    shot_number=shot.shot_number,
                    title=shot.title,
                    generation_type=shot.generation_type,
                    status=shot.status,
                    dependency_state=getattr(shot, "dependency_state", "INDEPENDENT"),
                    continuity_status=shot.continuity_status,
                    predecessor_shot_id=shot.predecessor_shot_id,
                    successor_shot_ids=successors_map.get(shot_str_id, []),
                    first_frame=shot.first_frame,
                    last_frame=shot.last_frame,
                    output_asset_url=shot.output_asset_url,
                    frame_anchors=frame_anchors,
                    can_dispatch=can_dispatch,
                    is_blocked=not can_dispatch,
                    unmet_dependencies=unmet,
                )
            )

        return ShotGraphResponse(
            project_id=project_id,
            nodes=nodes,
            edges=edges,
            roots=roots,
            has_cycles=has_cycles,
            cycle_nodes=cycle_nodes,
        )

    def detect_cycles(self, shots: list[ProductionShot]) -> tuple[bool, list[str]]:
        """DFS-based cycle detection on the shot dependency graph."""
        adj: dict[str, list[str]] = {}
        for shot in shots:
            adj[str(shot.id)] = []

        for shot in shots:
            if shot.predecessor_shot_id and shot.predecessor_shot_id in adj:
                adj[shot.predecessor_shot_id].append(str(shot.id))

        visited: dict[str, int] = {}  # 0=unvisited, 1=visiting (on current path), 2=visited
        cycle_nodes: list[str] = []

        def dfs(node: str, path: list[str]) -> bool:
            visited[node] = 1
            for neighbor in adj.get(node, []):
                if visited.get(neighbor) == 1:
                    cycle_start = path.index(neighbor) if neighbor in path else 0
                    cycle_nodes.extend(path[cycle_start:] + [neighbor])
                    return True
                if visited.get(neighbor, 0) == 0:
                    if dfs(neighbor, path + [neighbor]):
                        return True
            visited[node] = 2
            return False

        for shot_id in adj:
            if visited.get(shot_id, 0) == 0:
                if dfs(shot_id, [shot_id]):
                    return True, list(set(cycle_nodes))

        return False, []

    async def validate_can_dispatch(
        self,
        shot: ProductionShot,
        db: AsyncSession,
    ) -> tuple[bool, str | None]:
        """Evaluates whether a shot is dependency-ready to be dispatched."""
        if not shot.predecessor_shot_id:
            return True, None

        # Fetch predecessor
        try:
            pred_uuid = uuid.UUID(shot.predecessor_shot_id)
            stmt = select(ProductionShot).where(ProductionShot.id == pred_uuid)
            pred = (await db.execute(stmt)).scalar_one_or_none()
        except ValueError:
            return False, f"Invalid predecessor UUID format: '{shot.predecessor_shot_id}'"

        if pred is None:
            return False, f"Predecessor shot '{shot.predecessor_shot_id}' not found in project."

        if pred.status == "FAILED":
            return False, f"Predecessor shot '{pred.title}' FAILED generation. Downstream execution blocked."

        if pred.status != "COMPLETE":
            return False, f"Predecessor shot '{pred.title}' is WAITING_FOR_PREDECESSOR: not yet COMPLETE (current status: {pred.status})."

        # Check that predecessor has verified output
        if not pred.output_asset_url:
            return False, f"Predecessor shot '{pred.title}' has no validated output asset."

        return True, None

    async def unlock_successors(
        self,
        completed_shot_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[ProductionShot]:
        """Propagates verified completion downstream, validating continuity and unlocking successors."""
        stmt = select(ProductionShot).where(ProductionShot.id == completed_shot_id)
        completed_shot = (await db.execute(stmt)).scalar_one_or_none()
        if not completed_shot:
            return []

        # Find all direct successors
        succ_stmt = select(ProductionShot).where(ProductionShot.predecessor_shot_id == str(completed_shot_id))
        successors = list((await db.execute(succ_stmt)).scalars().all())

        if not successors:
            return []

        meta = completed_shot.metadata_json or {}
        frame_anchors = meta.get("frame_anchors", {})
        last_frame_anchor = frame_anchors.get("last_frame", {})
        last_frame_url = last_frame_anchor.get("artifact_url") or completed_shot.last_frame or completed_shot.output_asset_url

        updated_successors: list[ProductionShot] = []

        for succ in successors:
            if completed_shot.status == "COMPLETE":
                # Assign predecessor's last frame to successor's first frame if not already set
                if last_frame_url and not succ.first_frame:
                    succ.first_frame = last_frame_url

                # Run deterministic continuity evaluation
                report = continuity_validator.validate(succ, completed_shot)
                succ.continuity_status = report.status
                succ_meta = dict(succ.metadata_json or {})
                succ_meta["continuity"] = {
                    "status": report.status,
                    "technical_status": report.technical_status,
                    "dependency_status": report.dependency_status,
                    "temporal_status": report.temporal_status,
                    "reasons": report.reasons,
                    "diagnostics": report.diagnostics,
                }
                succ.metadata_json = succ_meta

                if report.status in ("PASS", "WARNING"):
                    succ.dependency_state = "READY"
                    if succ.status in ("BLOCKED", "WAITING_FOR_PREDECESSOR"):
                        succ.status = "READY"
                    await emit_telemetry_event(
                        TelemetryEvent(
                            event_type="SHOT_UNLOCKED",
                            project_id=succ.project_id,
                            sequence_id=succ.sequence_id,
                            shot_id=succ.id,
                            payload={
                                "shot_id": str(succ.id),
                                "dependency_state": "READY",
                                "continuity_status": report.status,
                                "first_frame": succ.first_frame,
                                "predecessor_title": completed_shot.title,
                            },
                        )
                    )
                    await emit_telemetry_event(
                        TelemetryEvent(
                            event_type="CONTINUITY_PASSED" if report.status == "PASS" else "CONTINUITY_WARNING",
                            project_id=succ.project_id,
                            sequence_id=succ.sequence_id,
                            shot_id=succ.id,
                            payload={
                                "shot_id": str(succ.id),
                                "status": report.status,
                                "reasons": report.reasons,
                            },
                        )
                    )
                else:
                    succ.dependency_state = "CONTINUITY_BLOCKED"
                    await emit_telemetry_event(
                        TelemetryEvent(
                            event_type="SHOT_BLOCKED",
                            project_id=succ.project_id,
                            sequence_id=succ.sequence_id,
                            shot_id=succ.id,
                            payload={
                                "shot_id": str(succ.id),
                                "dependency_state": "CONTINUITY_BLOCKED",
                                "continuity_status": "BLOCKED",
                                "reasons": report.reasons,
                            },
                        )
                    )
                    await emit_telemetry_event(
                        TelemetryEvent(
                            event_type="CONTINUITY_BLOCKED",
                            project_id=succ.project_id,
                            sequence_id=succ.sequence_id,
                            shot_id=succ.id,
                            payload={
                                "shot_id": str(succ.id),
                                "status": "BLOCKED",
                                "reasons": report.reasons,
                            },
                        )
                    )

            else:
                # Predecessor failed
                succ.dependency_state = "BLOCKED"
                succ.continuity_status = "BLOCKED"
                await emit_telemetry_event(
                    TelemetryEvent(
                        event_type="SHOT_BLOCKED",
                        project_id=succ.project_id,
                        sequence_id=succ.sequence_id,
                        shot_id=succ.id,
                        payload={
                            "shot_id": str(succ.id),
                            "dependency_state": "BLOCKED",
                            "reason": f"Predecessor shot '{completed_shot.title}' failed.",
                        },
                    )
                )

            updated_successors.append(succ)

        await db.commit()
        return updated_successors


shot_graph_service = ShotGraphService()

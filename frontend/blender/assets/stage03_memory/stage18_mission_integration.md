# Stage 18: Mission Control Integration & Bounded Replanning

## 1. Overview
Stage 12 introduced long-horizon missions with explicit dependencies, checkpoints, and adaptive replanning. Stage 18 feeds verified external state changes into Mission Control without permitting untrusted events to cause uncontrolled replanning storms.

## 2. Mission Observation Recording
When an ingress event is associated with a mission (`options.missionId`):
1. `missionObservationService.recordObservation()` logs a structured `PROGRESS` observation.
2. The observation contains:
   - `summary`: "External event observed on {resourceType} ({resourceId}): {changeType}"
   - `details`: Normalized event ID, connector ID, reconciliation status, and epistemic status.
3. Observations update the mission envelope in `executionPersistence`.

## 3. Bounded Replanning Trigger
External updates only trigger mission replanning when critical dependencies are deleted or modified:
- `changeType === 'DELETED'`
- The current mission plan does not already reflect the update (`!lastPlan.changeReason?.includes(norm.normalizedEventId)`).
- If triggered, `missionReplanner.replanMission()` increments the plan version (e.g. Plan v1 -> Plan v2) and creates a new execution DAG.
- Duplicate events do NOT trigger replanning, bounded by the replay protection cache.

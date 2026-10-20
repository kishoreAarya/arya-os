# Stage 24 — Phase 8: Control Plane Integration & Acceptance
## Authoritative Integration Source Map & Architectural Boundaries

**Status:** APPROVED & AUTHORIZED  
**Phase:** Stage 24 — Phase 8: Control Plane Integration & Acceptance ONLY  
**Integration Target:** `src/components/spatial/SpatialCommandConsole.tsx` (AryaOS Command Deck)  
**Re-export Seam:** `src/components/spatial/OperatorHUD.tsx` -> `src/components/control-plane/OperatorHUD.tsx`  
**Execution Authority:** NONE (Pure DOM Observational Presentation, Zero Consequential Authority)

---

### 1. Architectural Reconnaissance & Integration Point Identification

In conformance with Phase 8.1, the repository architecture was analyzed across:
1. `src/App.tsx`: Top-level application shell hosting `SpatialWorld`, `CreatorStudio`, `PipelinesView`, `ResearchView`, `PublishingView`, `LearningView`.
2. `src/components/spatial/SpatialWorld.tsx`: Spatial 3D environment orchestrating camera rigs, Stage 03 GLB assets, and overlay systems.
3. `src/components/spatial/SpatialHudOverlay.tsx`: Viewport HUD rendering waypoint telemetry and shortcuts.
4. `src/components/spatial/SpatialCommandConsole.tsx`: **The canonical Command Deck terminal container** across all previous stages:
   - Stage 09: Durable Recovery Badge
   - Stage 10: Multi-Agent Coordination HUD
   - Stage 11: Agent Evaluation HUD
   - Stage 12: Mission Control HUD
   - Stage 13: Strategic Knowledge HUD
   - Stage 14: Decision Intelligence HUD
   - Stage 15: Action Bus HUD
   - Stage 16: Connector Fabric HUD
   - Stage 17: Connector Activation HUD
   - Stage 18: External Event HUD
   - Stage 19: Event Reaction HUD
   - Stage 20: Policy Intelligence HUD
   - Stage 21: Governance Control Plane HUD (`governance-control-plane-hud`)
   - Stage 22: Operational Audit HUD (`operational-audit-hud`)
   - Stage 23: Recovery Control Plane HUD (`recovery-control-plane-hud`)

**Single Correct Integration Point:**
`SpatialCommandConsole.tsx` is the sole unified command deck where all subsystem telemetry and stage HUDs converge. Stage 24 integrates directly into `SpatialCommandConsole.tsx` immediately following Stage 23, providing:
1. An inline summary telemetry panel (`stage24-control-plane-hud`).
2. An interactive, non-consequential toggle button (`toggle-operator-hud-btn`).
3. Full integration with the complete master `OperatorHUD` overlay modal (`operator-hud`), including all 8 panels (`overview`, `health`, `missions`, `operations`, `approvals`, `recovery`, `causal`, `resources`).

---

### 2. Integration Architecture & Data Flow

```
                                +-----------------------------------+
                                |    SpatialCommandConsole (DOM)    |
                                +-----------------------------------+
                                                  |
                     +----------------------------+----------------------------+
                     |                                                         |
                     v                                                         v
    +----------------------------------+                     +----------------------------------+
    | Stage 24 Inline Telemetry Matrix |                     |    Master OperatorHUD Overlay    |
    |  data-testid="stage24-control-   |                     |   data-testid="operator-hud"     |
    |            plane-hud"            |                     | (Mounted on toggle or show prop) |
    +----------------------------------+                     +----------------------------------+
                     |                                                         |
                     +----------------------------+----------------------------+
                                                  |
                                                  | read-only snapshot
                                                  v
                               +------------------------------------+
                               |    controlPlaneSnapshotService     |
                               |    (Frozen Stage 24 Facade)        |
                               +------------------------------------+
                                                  |
        +-----------------------+-----------------+-----------------------+
        |                       |                 |                       |
        v                       v                 v                       v
  Stage 12 / 08           Stage 23          Stage 21 / 20           Stage 09 / 22
Mission / Goals           Recovery       Governance / Policy     Audit / Persistence
```

---

### 3. Component & Property Interface Binding

| Integration File | Target Element / Prop | Canonical Source Method | Epistemic Meaning |
|---|---|---|---|
| `SpatialCommandConsole.tsx` | `data-testid="stage24-control-plane-hud"` | `controlPlaneSnapshotService.getSnapshot()` | Root Stage 24 summary container in command deck |
| `SpatialCommandConsole.tsx` | `data-testid="control-plane-hud-status"` | Hardcoded invariant | `OBSERVATIONAL_HUD` (Zero execution authority) |
| `SpatialCommandConsole.tsx` | `data-testid="toggle-operator-hud-btn"` | Local component state `isOperatorHudOpen` | Toggles full master HUD overlay |
| `SpatialCommandConsole.tsx` | `data-testid="control-plane-snapshot-id"` | `snapshot.snapshotId` | Temporal snapshot identifier (`snap-cp-...`) |
| `SpatialCommandConsole.tsx` | `data-testid="control-plane-missions-count"` | `snapshot.missions.length` | Count of known canonical missions |
| `SpatialCommandConsole.tsx` | `data-testid="control-plane-operations-count"` | `snapshot.operations.length` | Count of known canonical operations |
| `SpatialCommandConsole.tsx` | `data-testid="control-plane-approvals-count"` | `snapshot.approvals.length` | Count of pending approval requirements |
| `SpatialCommandConsole.tsx` | `data-testid="control-plane-epistemic-badge"` | Hardcoded invariant | `EPISTEMIC: STRICT_PROJECTION` |
| `SpatialCommandConsole.tsx` | `data-testid="control-plane-authority-badge"` | Hardcoded invariant | `AUTHORITY: ZERO_AUTHORITY` |
| `SpatialCommandConsole.tsx` | `<OperatorHUD ... />` | `OperatorHUD` from `./OperatorHUD` | Master Command Deck overlay composing 8 panels |

---

### 4. Absolute Architectural Boundaries & Invariants

1. **Zero New Authority Engines:** No new mission scheduler, execution engine, approval validator, recovery engine, policy store, or audit service.
2. **Zero Action Bus Dispatch:** HUD contains zero consequential triggers. No calls to `actionBusService.dispatch`, `actionBusService.execute`, `missionManager.startMission`, or `recoveryControlPlane.executeRecovery`.
3. **Pure DOM Layer:** Exactly 0 added Three.js meshes, 0 WebGL contexts, 0 HTML5 `<canvas>` elements, and 0 WebGL draw calls.
4. **Visual Baseline Preservation:**
   - Master Blender Scene SHA256: `c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f` (preserved).
   - 28 GLB assets (14 src, 14 dist) remain 100% intact.
   - Geometry metrics: 86,842 triangles, 53–54 baseline draw calls.
5. **No Direct Network / Provider Calls:** Zero `fetch()`, zero WebSocket, zero LLM provider SDK calls.
6. **Defensive Error Isolation:** Snapshot errors are caught gracefully; `OperatorHUDErrorBoundary` isolates projection failures without crashing `SpatialCommandConsole`.
7. **Security & Sanitization:** Secret scrubbing, prototype pollution defense, JSX HTML escaping, and fail-closed treatment of unknown authority remain enforced.

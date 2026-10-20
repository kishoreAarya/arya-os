# AryaOS V1 Stage 22 — Runtime Observability & Spatial Telemetry HUD

## 1. Overview & Architecture

Observability in AryaOS V1 bridges low-level operational events and human spatial interaction. The system renders real-time telemetry into the operator's viewport without altering the 3D cinematic scene graph or increasing GPU overhead.

Stage 22 implements four pure DOM-based telemetry sub-panels mounted within `SpatialCommandConsole.tsx`:
1. **`operational-audit-hud`**: Master telemetry console displaying event counts, sequence progression, and the core invariant badge (`AUTHORITY: ZERO_AUTHORITY`).
2. **`causal-graph-hud`**: Real-time causal graph topology inspector displaying nodes, edges, max depth, and cycle detection indicators.
3. **`operational-truth-hud`**: Intent vs reality status inspector displaying the `INTENT ≠ TRUTH` badge, reconciliation counters, and discrepancy logs.
4. **`audit-metrics-hud`**: Aggregated performance metrics displaying event type distributions, terminal states, and failure boundary breakdowns.

---

## 2. Spatial HUD Panels Breakdown

### 2.1 Operational Audit Master Panel (`operational-audit-hud`)
- **Location**: Top-left console drawer.
- **Key Indicators**:
  - `Total Audit Events`: Monotonic counter of registered events.
  - `Active Operations`: Number of currently running operational lifecycles.
  - `Terminal Status Rate`: Percentage of operations reaching a terminal state.
  - `Security Badge`: `AUTHORITY: ZERO_AUTHORITY` (confirming audit events carry no execution privilege).

### 2.2 Causal Graph Inspector (`causal-graph-hud`)
- **Location**: Upper-right console overlay.
- **Features**:
  - Node & edge count displays.
  - `Acyclicity Status`: Shows `ACYCLIC (VERIFIED)` or alerts if circular references are blocked.
  - Traversal depth meter bounded to $\le 10$ levels.
  - Missing evidence warnings highlighting broken causal links.

### 2.3 Operational Truth Panel (`operational-truth-hud`)
- **Location**: Lower-left diagnostic drawer.
- **Key Indicators**:
  - Master Badge: `INTENT ≠ TRUTH (FAIL-CLOSED)`.
  - Reconciled vs Unreconciled counters.
  - Mismatch warning banner with discrepancy breakdown.

### 2.4 Audit Metrics Dashboard (`audit-metrics-hud`)
- **Location**: Lower-right analytics drawer.
- **Metrics Computed**:
  - Event distribution across stages (Stage 15, 16, 18, 19, 21, 22).
  - Failure boundary distribution (`POLICY_DENIED`, `AUTHORIZATION_DENIED`, `HUMAN_APPROVAL_PENDING`, `EXTERNAL_RESULT_UNKNOWN`, `RECONCILIATION_FAILURE`).
  - Monotonic sequence health and duplicate drop rate.

---

## 3. Spatial & WebGL Performance Audit

All Stage 22 telemetry panels are rendered using standard HTML/CSS DOM overlays layered atop the Three.js canvas. This architectural decision ensures zero visual or GPU performance degradation.

| Performance Metric | Baseline (Stage 03 Reconciled) | Stage 22 Verified | Status |
|---|---|---|---|
| **WebGL Draw Calls** | 53–54 calls | **53–54 calls (0 additional)** | PASS |
| **Scene Triangle Count** | 86,842 triangles | **86,842 triangles (0 additional)** | PASS |
| **Frame Render Time** | 1.12 – 1.85 ms | **1.14 – 1.82 ms** | PASS |
| **Blender Master Scene** | `stage03_aryaos_memory_environment.blend` | **`c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f`** | PASS |
| **GLB File Count** | 14 files | **14 files (100% intact)** | PASS |

### Frozen Camera Baseline
- **`CAM_CinematicHero`**: `[-12.0, 2.3, 38.5]`, FOV `39.761°`
- **`CAM_MonumentalLowAngle`**: `[0.0, 0.65, 26.0]`, FOV `49.426°`
- **`CAM_ArchiveDetail`**: `[-16.2, 1.85, 32.8]`, FOV `35.115°`

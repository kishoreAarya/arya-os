# Stage 23 — Frontend Recovery Operational HUD Certification

**Stage**: AryaOS V1 — Stage 23: Governed Recovery & Self-Healing Control Plane  
**Phase**: Phase 13: Final Certification, Full Regression & Stage Freeze  
**Status**: CERTIFIED & FROZEN  

---

## 1. Minimal DOM-Only HUD Specification

The Stage 23 Recovery Operational HUD (`RecoveryControlHUD.tsx`) is designed as a **strictly observational, pure DOM overlay** embedded within `SpatialCommandConsole.tsx`.

### Core HUD Architecture Principles

1. **Observational Only**:
   - Zero execution buttons.
   - Zero approval triggers.
   - Zero recovery initiation controls.
   - The HUD is a read-only telemetry mirror of Stage 23 internal state.
2. **Zero 3D / WebGL Overhead**:
   - Implemented exclusively using React DOM elements (`<div>`, `<span>`, CSS styling).
   - Adds **0** draw calls to Three.js.
   - Adds **0** triangles to WebGL geometry.
   - Requires **0** GPU compute or frame re-renders.
3. **Epistemic Honesty in Presentation**:
   - Disallowed from masking `UNKNOWN` as `HEALTHY` or `SUCCESS`.
   - Distinct epistemic badges for `OBSERVED`, `CONFIRMED`, `INFERRED`, `UNKNOWN`, and `STALE`.
   - Clear visual differentiation between active recovery actions and unexecuted `PROPOSED` recommendations.

---

## 2. Telemetry DOM Layout & Test ID Contracts

| Element Test ID | Rendered Telemetry | Epistemic / Safety Guarantee | Test Verification |
|---|---|---|---|
| `recovery-control-hud` | Container DOM wrapper | Pure HTML/CSS overlay | Test 372, Test 392 |
| `hud-operation-id` | Tracked operation identifier | Full string rendering, non-truncated | Test 372 |
| `hud-operational-truth` | Stage 22 ground-truth status | Strictly mirrors Stage 22 evidence | Test 372 |
| `hud-epistemic-status` | Epistemic confidence badge | `UNKNOWN` rendered in warning amber; never green | Test 372, Test 373 |
| `hud-recovery-state` | Active recovery state | Displays current lifecycle state (`READY`, `DISPATCHED`, etc.) | Test 372 |
| `hud-failure-class` | Failure classification | Displays categorized failure taxonomy | Test 372 |
| `hud-recovery-decision` | Recovery decision action | Displays `RETRY`, `RECONCILE`, `COMPENSATE`, `ESCALATE` | Test 372 |
| `hud-epistemic-safety-notice` | Epistemic safety banner | Explicit notice when state is `UNKNOWN` or unconfirmed | Test 372, Test 373 |

---

## 3. Spatial Console Integration & Performance Proofs

- **Mount Location**: Mounted in `SpatialCommandConsole.tsx` alongside telemetry and performance monitors.
- **Rendering Benchmark**: Renders in <1ms without layout thrashing.
- **Three.js Pipeline**: Verified that WebGL render stats remain exactly at 53–54 draw calls and 86,842 triangles when the HUD is active.

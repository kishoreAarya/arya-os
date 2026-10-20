# AryaOS V1 — Stage 23: Phase 12
## Minimal DOM-Only Recovery Operational HUD Specification

**Authoritative Status:** FROZEN & COMPLETE  
**Stage:** Stage 23 — Recovery Control Plane & Autonomous Healing  
**Phase:** Phase 12 — Adversarial Security Hardening & Recovery Operational HUD  
**Date:** October 3, 2026  
**Master Blender SHA256:** `c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f`  

---

### 1. Architectural Philosophy & Zero WebGL Footprint

The Recovery Operational HUD (`RecoveryControlHUD.tsx`) is designed with strict architectural boundaries:

1. **Pure DOM Overlay**: Rendered entirely with HTML/CSS elements (`div`, `span`, `button`, `pre`) positioned over the viewport via absolute positioning (`pointer-events-auto`, `z-30`).
2. **Zero 3D/WebGL Interference**:
   - Zero Three.js meshes, geometries, or materials created.
   - Zero draw call increase (maintains 53–54 draw call baseline).
   - Zero triangle count increase (maintains 86,842 triangles baseline).
   - Zero modifications to Blender master scene or 28 GLB assets.
3. **Strictly Observational (No Ambient Mutation Authority)**:
   - The HUD displays state fetched from `recoveryControlPlane`, `operationalTruthService`, and `causalTraceService`.
   - The HUD does **not** execute recovery actions, modify policies, bypass governance, or mutate lifecycle states directly.
   - Any operator action (such as manual approval) emits a signed intent to Stage 21 `governanceControlPlane` for evaluation against the fail-closed authority intersection.

---

### 2. Epistemic Status Tags & Visual Encodings

To prevent epistemic conflation or misleading operators during crisis events, all telemetry items carry explicit epistemic certainty badges:

| Epistemic Tag | Color Code | Visual Semantics | Operational Meaning |
|---------------|------------|------------------|---------------------|
| **`UNKNOWN`** | `bg-amber-950 text-amber-300 border-amber-600` | Pulsing warning amber | External operation state unconfirmed; recovery paused pending probe |
| **`OBSERVED`** | `bg-blue-950 text-blue-300 border-blue-600` | Solid cyan-blue | Empirically captured telemetry from runtime action bus |
| **`CONFIRMED`** | `bg-emerald-950 text-emerald-300 border-emerald-600` | Solid green | Cryptographically or deterministically verified Stage 22 truth |
| **`INFERRED`** | `bg-purple-950 text-purple-300 border-purple-600` | Dotted purple | Algorithmically deduced via causal graph analysis; unverified |
| **`PROJECTED`** | `bg-slate-900 text-slate-400 border-slate-700` | Faded gray | Hypothetical simulation or anticipated consequence |

---

### 3. Component Architecture & Telemetry Panels

The HUD component is located at `src/components/spatial/RecoveryControlHUD.tsx` and mounted inside `src/components/spatial/SpatialCommandConsole.tsx`.

#### Sub-Panels:
1. **Header & Health Summary**:
   - Status badge (e.g. `NOMINAL`, `DEGRADED`, `RECOVERING`).
   - Active recovery count, pending approval count, active isolations count.
   - Quick filters (`ALL`, `CRITICAL`, `UNKNOWN`, `APPROVAL`).
2. **Recovery Control Stream**:
   - List of active/recent recovery records with `requestId`, `operationId`, and `lifecycleState`.
   - Epistemic certainty badge and risk tier indicator (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`).
   - Monotonic retry counter display (`retryCount / maxRetries`, `recoveryDepth`).
3. **Reconciliation & Compensation Monitor**:
   - Active probes and probe attempt counts.
   - Compensation plans, rollback action targets, and execution status.
4. **Blast Radius & Cascade Isolation View**:
   - Visited operation counts and cascade depth indicator.
   - Isolated subsystem indicators with reason codes.
5. **Causal Lineage & Audit Drawer**:
   - Inspects `causationId`, `correlationId`, and parent operation bindings.
   - Tamper-evident hash and timestamp verification.

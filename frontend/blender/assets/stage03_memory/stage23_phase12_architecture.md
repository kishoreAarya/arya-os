# AryaOS V1 — Stage 23: Phase 12
## Recovery Control Plane & HUD Architecture Specification

**Authoritative Status:** FROZEN & COMPLETE  
**Stage:** Stage 23 — Recovery Control Plane & Autonomous Healing  
**Phase:** Phase 12 — Adversarial Security Hardening & Recovery Operational HUD  
**Date:** October 3, 2026  
**Master Blender SHA256:** `c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f`  

---

### 1. Architectural Architecture & Subsystem Ownership

AryaOS maintains a strict separation of concerns across its core engines. No subsystem duplicates another subsystem's authority:

```
┌────────────────────────────────────────────────────────────────────────┐
│                          PRESENTATION LAYER                            │
│  src/components/spatial/RecoveryControlHUD.tsx (Pure DOM Overlay)      │
│  - Strictly Observational                                              │
│  - Epistemic Badges: UNKNOWN | OBSERVED | CONFIRMED | INFERRED         │
│  - Zero 3D Meshes / Shaders / WebGL Footprint                          │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ (Telemetry Read-Only)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        STAGE 23: RECOVERY CONTROL                      │
│  recoveryControlPlane.ts | failureClassificationService.ts             │
│  recoveryPlanService.ts  | recoverySafetyService.ts                    │
│  - Evaluates failure conditions and orchestrates recovery plans        │
│  - Enforces MAX_RECOVERY_DEPTH (3) and MAX_CASCADE_DEPTH (5)           │
│  - Maintains deterministic recovery lifecycle state machine            │
└───────┬──────────────┬──────────────────┬──────────────────┬───────────┘
        │              │                  │                  │
        ▼              ▼                  ▼                  ▼
┌──────────────┐┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│   STAGE 20   ││   STAGE 21   │   │   STAGE 22   │   │   STAGE 09   │
│ POLICY INTEL ││  GOVERNANCE  │   │ OPERATIONAL  │   │ DURABILITY & │
│ policyRegistry││authoritySvc │   │    TRUTH     │   │ PERSISTENCE  │
│ - Priorities ││ - Intersection│  │ - CausalLineage│ │ - Journal    │
│ - Safety Deny││ - Approvals  │   │ - AuditChain │   │ - RecoveryDb │
└───────┬──────┘└──────┬───────┘   └──────┬───────┘   └──────┬───────┘
        │              │                  │                  │
        └──────────────┴─────────┬────────┴──────────────────┘
                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│                         EXECUTION AUTHORITIES                          │
│  Stage 15 (Universal Action Bus) | Stage 16 (Connector Permissions)   │
│  Stage 07 (Provider Execution)   | Stage 12 (Mission Control)          │
└────────────────────────────────────────────────────────────────────────┘
```

---

### 2. Strict Subsystem Ownership Boundaries

| Stage / Component | Subsystem Responsibility | What it Must NOT Do |
|-------------------|--------------------------|---------------------|
| **Stage 09** | Durable execution journal, crash recovery mechanics, persistent storage | Formulate recovery policy or reclassify failures |
| **Stage 20** | Policy evaluation, hierarchy rules, priority weights, safety gates | Directly dispatch actions or manage recovery state machines |
| **Stage 21** | Governance intersection, human approval token validation, security contexts | Execute actions or bypass connector permissions |
| **Stage 22** | Empirical operational truth, causal trace graph, tamper-evident audit logs | Make recovery decisions or override policy |
| **Stage 23** | Recovery decision formulation, safety triage, cascade containment, retry control | Create a secondary persistence engine, policy engine, or execution bus |
| **Stage 15** | External capability dispatching and execution safety | Formulate recovery plans |
| **Stage 16** | Connector registry, credential reference management, scoped permissions | Fabricate ambient authority |
| **Stage 12** | Long-horizon mission state, objective hierarchies, budget bounds | Interfere with low-level crash persistence |
| **Recovery HUD** | Presentation-only telemetry overlay with explicit epistemic certainty badges | Mutate recovery state or execute actions directly |

---

### 3. Effective Authority Flow

```
                      [ INCOMING RECOVERY REQUEST ]
                                    │
                                    ▼
                     [ 1. INPUT SANITIZATION & BOUNDS ]
                     validateAndSanitizePayload(payload)
                     - Length check (≤64KB)
                     - Prototype pollution check (__proto__)
                     - Credential scrub (sk-, ghp_, bearer)
                     - Cycle detection (WeakSet)
                                    │
                                    ▼
                     [ 2. DETERMINISTIC STATE MACHINE ]
                     assertValidRecoveryLifecycleTransition()
                     - Terminal states immutable
                     - No speculative transitions
                                    │
                                    ▼
                  [ 3. OPERATIONAL TRUTH RECONCILIATION ]
                     Stage 22 operationalTruthService
                     - UNKNOWN requires probe
                     - Empirical evidence overrides intent
                                    │
                                    ▼
                  [ 4. CROSS-LAYER AUTHORITY EVALUATION ]
                     governanceAuthorityService.evaluateAuthorityIntersection()
                     Policy ∩ Connector ∩ ActionBus ∩ Human ∩ Mission
                                    │
                        ┌───────────┴───────────┐
                        ▼                       ▼
                   [ APPROVED ]             [ DENIED ]
                        │                       │
                        ▼                       ▼
                 [ DISPATCH VIA ]          [ ABORT / ]
                 [  STAGE 15    ]          [ ISOLATE ]
```

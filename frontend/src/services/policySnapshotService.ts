/**
 * AryaOS V1 — Stage 21: Policy Snapshot Service
 *
 * Captures consistent, immutable snapshots of active policies from Stage 20 PolicyRegistry.
 * Guarantees that a governance evaluation is evaluated against a fixed set of policies
 * without in-flight mutations altering the decision mid-evaluation.
 */

import {
  PolicySnapshot,
  PolicySnapshotEntry,
} from '../types/governanceControlPlane';
import { policyRegistry } from './policyRegistry';
import { executionPersistence } from './executionPersistence';
import { Policy } from '../types/policyIntelligence';

export class PolicySnapshotService {
  private snapshots: Map<string, PolicySnapshot> = new Map();

  public reset(): void {
    this.snapshots.clear();
  }

  /**
   * Captures an immutable snapshot of all currently ACTIVE policies.
   */
  public captureSnapshot(): PolicySnapshot {
    const activePolicies = policyRegistry.getActivePolicies();
    const registryVersion = policyRegistry.getRegistryVersion();
    const createdAt = Date.now();

    // Deep copy active policies into immutable snapshot entries
    const policies: PolicySnapshotEntry[] = activePolicies.map((p) => ({
      policyId: p.id,
      version: p.version,
      name: p.name,
      priority: p.priority,
      priorityWeight: (policyRegistry as unknown as { getPriorityWeight?: (p: Policy) => number })
        ? (p.priority === 'SYSTEM_SAFETY' ? 100 :
           p.priority === 'SECURITY' ? 90 :
           p.priority === 'HUMAN_GOVERNANCE' ? 80 :
           p.priority === 'RESOURCE_LIMITS' ? 70 :
           p.priority === 'MISSION_POLICY' ? 60 :
           p.priority === 'AGENT_POLICY' ? 50 :
           p.priority === 'TRIGGER_POLICY' ? 40 : 30)
        : 50,
      scope: JSON.parse(JSON.stringify(p.scope)),
      effect: JSON.parse(JSON.stringify(p.effect)),
      conditions: JSON.parse(JSON.stringify(p.conditions)),
    }));

    // Sort deterministically by policyId
    policies.sort((a, b) => a.policyId.localeCompare(b.policyId));

    const fingerprintRaw = policies.map((p) => `${p.policyId}:v${p.version}`).join('|');
    let hash = 0;
    for (let i = 0; i < fingerprintRaw.length; i++) {
      hash = (hash << 5) - hash + fingerprintRaw.charCodeAt(i);
      hash |= 0;
    }
    const fingerprint = `fp_${Math.abs(hash).toString(16).padStart(8, '0')}_v${registryVersion}`;
    const snapshotId = `snap_v${registryVersion}_${createdAt}_${Math.abs(hash).toString(16).slice(0, 6)}`;

    const snapshot: PolicySnapshot = {
      snapshotId,
      registryVersion,
      createdAt,
      activePolicyCount: policies.length,
      policies,
      fingerprint,
    };

    const frozenSnapshot = Object.freeze({
      ...snapshot,
      policies: Object.freeze(policies.map((p) => Object.freeze(p))),
    });

    this.snapshots.set(snapshotId, frozenSnapshot);
    executionPersistence.savePolicySnapshot?.(frozenSnapshot);

    return frozenSnapshot;
  }

  /**
   * Retrieves an immutable snapshot by ID.
   */
  public getSnapshot(snapshotId: string): PolicySnapshot | undefined {
    return this.snapshots.get(snapshotId);
  }

  /**
   * Checks if a snapshot remains aligned with current active registry version.
   */
  public isSnapshotCurrent(snapshot: PolicySnapshot): boolean {
    const currentRegistryVersion = policyRegistry.getRegistryVersion();
    return snapshot.registryVersion === currentRegistryVersion;
  }

  /**
   * Returns all stored snapshots.
   */
  public getAllSnapshots(): PolicySnapshot[] {
    return Array.from(this.snapshots.values());
  }
}

export const policySnapshotService = new PolicySnapshotService();

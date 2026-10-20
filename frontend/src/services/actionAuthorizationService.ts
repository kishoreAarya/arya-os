/**
 * AryaOS V1 — Stage 15: Action Authorization Service
 *
 * Enforces defense-in-depth authorization, risk tiering, default DENY permissions,
 * sandboxing bounds (path, domain, repository, payload size), and human governance boundaries.
 */

import {
  ActionRequest,
  ActionAuthorization,
  ActionRiskLevel,
  ActionPolicy,
  ActionPermission,
} from '../types/actionBus';
import { capabilityRegistry } from './capabilityRegistry';

export class ActionAuthorizationService {
  private defaultPolicy: ActionPolicy = {
    policyId: 'policy_default_secure',
    name: 'AryaOS Default Secure Policy',
    allowedPermissions: [
      'FILES_READ',
      'FILES_WRITE',
      'WEB_SEARCH',
      'GITHUB_READ',
      'GITHUB_WRITE',
      'EXTERNAL_HTTP',
      'NOTIFICATION_SEND',
      'WORKFLOW_TRIGGER',
    ],
    allowedPaths: ['/workspace', '/data', '/tmp/sandbox'],
    allowedDomains: ['api.github.com', 'api.weather.gov', 'api.aryaos.local'],
    allowedRepositories: ['aryaos/core', 'aryaos/frontend', 'aryaos/sandbox'],
    maxPayloadBytes: 10485760, // 10MB
    requireHumanApprovalForCritical: true,
    requireApprovalForHighRisk: true,
  };

  /**
   * Evaluates authorization for an incoming ActionRequest.
   */
  public authorize(
    request: ActionRequest,
    customPolicy?: ActionPolicy,
    operatorApproval?: { approvedBy: string; signature?: string }
  ): ActionAuthorization {
    const policy = customPolicy || this.defaultPolicy;
    const capability = capabilityRegistry.getCapability(request.capabilityId);

    if (!capability) {
      return {
        authorized: false,
        status: 'DENIED',
        riskLevel: 'HIGH',
        requiresHumanApproval: true,
        reason: `Capability '${request.capabilityId}' is not registered`,
        grantedPermissions: [],
      };
    }

    // 1. Check capability deny-list
    if (policy.deniedCapabilities && policy.deniedCapabilities.includes(request.capabilityId)) {
      return {
        authorized: false,
        status: 'DENIED',
        riskLevel: capability.riskLevel,
        requiresHumanApproval: false,
        reason: `Capability '${request.capabilityId}' is explicitly denied by active policy`,
        grantedPermissions: [],
      };
    }

    // 2. Permission check: Default DENY
    const granted = policy.allowedPermissions || [];
    const missingPermissions = capability.requiredPermissions.filter((p) => !granted.includes(p));
    if (missingPermissions.length > 0) {
      return {
        authorized: false,
        status: 'DENIED',
        riskLevel: capability.riskLevel,
        requiresHumanApproval: false,
        reason: `Permission denied. Missing required permissions: ${missingPermissions.join(', ')}`,
        grantedPermissions: granted.filter((p) => capability.requiredPermissions.includes(p)),
      };
    }

    // 3. Sandboxing Boundaries
    const sandboxCheck = this.checkSandbox(request, policy);
    if (!sandboxCheck.allowed) {
      return {
        authorized: false,
        status: 'DENIED',
        riskLevel: capability.riskLevel,
        requiresHumanApproval: false,
        reason: `Sandbox violation: ${sandboxCheck.reason}`,
        grantedPermissions: capability.requiredPermissions,
      };
    }

    // 4. Determine Dynamic Risk Level (e.g. file deletion or financial terms escalate risk)
    const effectiveRiskLevel = this.calculateEffectiveRiskLevel(request, capability.riskLevel);

    // 5. Governance & Approval Boundaries
    const requiresHumanApproval =
      effectiveRiskLevel === 'CRITICAL' ||
      (effectiveRiskLevel === 'HIGH' && policy.requireApprovalForHighRisk);

    if (requiresHumanApproval) {
      // Check if valid operator approval exists
      if (!operatorApproval || !operatorApproval.approvedBy) {
        return {
          authorized: false,
          status: 'REQUIRES_APPROVAL',
          riskLevel: effectiveRiskLevel,
          requiresHumanApproval: true,
          reason: `Action requires explicit operator review (Risk: ${effectiveRiskLevel})`,
          grantedPermissions: capability.requiredPermissions,
        };
      }

      // Prohibit autonomous approval spoofing
      if (
        operatorApproval.approvedBy === 'SYSTEM' ||
        operatorApproval.approvedBy === 'AUTONOMOUS_AGENT'
      ) {
        return {
          authorized: false,
          status: 'DENIED',
          riskLevel: effectiveRiskLevel,
          requiresHumanApproval: true,
          reason: 'Autonomous approval prohibited for consequential external action',
          grantedPermissions: capability.requiredPermissions,
        };
      }

      return {
        authorized: true,
        status: 'AUTHORIZED',
        riskLevel: effectiveRiskLevel,
        requiresHumanApproval: true,
        approvedBy: operatorApproval.approvedBy,
        reviewedAt: new Date().toISOString(),
        grantedPermissions: capability.requiredPermissions,
      };
    }

    // LOW and approved MEDIUM risk actions pass automatically
    return {
      authorized: true,
      status: 'AUTHORIZED',
      riskLevel: effectiveRiskLevel,
      requiresHumanApproval: false,
      grantedPermissions: capability.requiredPermissions,
    };
  }

  /**
   * Sandboxing enforcement across paths, domains, repositories, and payload sizes.
   */
  public checkSandbox(
    request: ActionRequest,
    policy: ActionPolicy
  ): { allowed: boolean; reason?: string } {
    const params = request.parameters;

    // A. Filesystem Path Sandboxing
    if (params.path && typeof params.path === 'string') {
      const p = params.path;
      if (p.includes('../') || p.includes('..\\')) {
        return { allowed: false, reason: 'Path traversal (..) is strictly prohibited' };
      }
      const allowedPaths = policy.allowedPaths || ['/workspace', '/data'];
      const isWithinAllowed = allowedPaths.some((allowed) => p.startsWith(allowed));
      if (!isWithinAllowed) {
        return { allowed: false, reason: `Path '${p}' is outside allowed sandboxes (${allowedPaths.join(', ')})` };
      }
    }

    // B. External HTTP Domain Sandboxing
    if (params.url && typeof params.url === 'string') {
      try {
        const parsedUrl = new URL(params.url);
        const allowedDomains = policy.allowedDomains || [];
        const isDomainAllowed = allowedDomains.some((d) => parsedUrl.hostname === d || parsedUrl.hostname.endsWith('.' + d));
        if (!isDomainAllowed) {
          return { allowed: false, reason: `Destination domain '${parsedUrl.hostname}' is not in the allowlist` };
        }
      } catch {
        return { allowed: false, reason: `Invalid HTTP URL format: '${params.url}'` };
      }
    }

    // C. GitHub Repository Sandboxing
    if (params.repository && typeof params.repository === 'string') {
      const repo = params.repository;
      const allowedRepos = policy.allowedRepositories || [];
      if (!allowedRepos.includes(repo)) {
        return { allowed: false, reason: `Repository '${repo}' is not in authorized repository allowlist` };
      }
    }

    // D. Payload Size Limits
    const maxPayload = policy.maxPayloadBytes || 10485760;
    const serialized = JSON.stringify(params);
    if (serialized.length > maxPayload) {
      return { allowed: false, reason: `Payload size (${serialized.length} bytes) exceeds limit of ${maxPayload} bytes` };
    }

    return { allowed: true };
  }

  /**
   * Escalates risk dynamically based on destructive or financial parameters.
   */
  public calculateEffectiveRiskLevel(request: ActionRequest, baseRisk: ActionRiskLevel): ActionRiskLevel {
    if (baseRisk === 'CRITICAL') return 'CRITICAL';

    const text = JSON.stringify(request.parameters).toLowerCase();

    // Financial keywords escalate to CRITICAL
    if (text.includes('credit') || text.includes('payment') || text.includes('billing') || text.includes('spend')) {
      return 'CRITICAL';
    }

    // Destructive operations escalate to CRITICAL
    if (request.operation === 'delete_file' || text.includes('destroy') || text.includes('purge')) {
      return 'CRITICAL';
    }

    // Publishing escalates to HIGH or CRITICAL
    if (text.includes('publish') || text.includes('release')) {
      return 'CRITICAL';
    }

    return baseRisk;
  }
}

export const actionAuthorizationService = new ActionAuthorizationService();

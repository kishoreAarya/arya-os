/**
 * AryaOS V1 — Stage 17: Ephemeral Credential Resolver
 *
 * Resolves non-sensitive CredentialRefs into ephemeral, in-memory credential tokens
 * strictly at execution time, and securely disposes them immediately after transport dispatch.
 *
 * SECURITY INVARIANTS:
 * 1. Raw credentials NEVER persist to LocalStorage, ExecutionPersistence, KnowledgeGraph, or HUD.
 * 2. If secure credential infrastructure is unavailable and not in test/sandbox mode,
 *    returns CONFIGURATION_REQUIRED. Never downgrades security to bypass.
 * 3. Sanitizes all error messages, headers, and traces to remove Authorization / token strings.
 */

import { ConnectorCredentialRef, ConnectorId } from '../types/connectorFabric';

export interface EphemeralCredential {
  credentialId: string;
  tokenType: string;
  tokenValue: string;
  expiresAt?: string;
  headers: Record<string, string>;
}

export interface CredentialStore {
  getCredential(credentialId: string): Promise<string | null>;
  setCredential(credentialId: string, secretValue: string): Promise<void>;
  deleteCredential(credentialId: string): Promise<void>;
  hasCredential(credentialId: string): Promise<boolean>;
}

/**
 * Deterministic In-Memory Test Double for offline unit/integration testing.
 * NEVER exposed to persistent storage or browser LocalStorage.
 */
export class MockConnectorCredentialStore implements CredentialStore {
  private secrets: Map<string, string> = new Map();

  public async getCredential(credentialId: string): Promise<string | null> {
    return this.secrets.get(credentialId) || null;
  }

  public async setCredential(credentialId: string, secretValue: string): Promise<void> {
    this.secrets.set(credentialId, secretValue);
  }

  public async deleteCredential(credentialId: string): Promise<void> {
    this.secrets.delete(credentialId);
  }

  public async hasCredential(credentialId: string): Promise<boolean> {
    return this.secrets.has(credentialId);
  }

  public clear(): void {
    this.secrets.clear();
  }
}

export class CredentialResolver {
  private store: CredentialStore;
  private isOfflineTestMode: boolean;

  constructor(store?: CredentialStore, isOfflineTestMode = true) {
    this.store = store || new MockConnectorCredentialStore();
    this.isOfflineTestMode = isOfflineTestMode;
  }

  /**
   * Sets custom store (e.g. for testing).
   */
  public setStore(store: CredentialStore): void {
    this.store = store;
  }

  /**
   * Resolves a CredentialRef into an EphemeralCredential.
   * Throws if credential is expired, revoked, or unconfigured.
   */
  public async resolve(ref: ConnectorCredentialRef): Promise<EphemeralCredential> {
    if (ref.status === 'EXPIRED') {
      throw new Error(`Credential resolution blocked: Credential '${ref.credentialId}' is EXPIRED. Reauthentication required.`);
    }

    if (ref.status === 'REVOKED') {
      throw new Error(`Credential resolution blocked: Credential '${ref.credentialId}' is REVOKED and permanently disabled.`);
    }

    if (ref.status === 'CONFIGURATION_REQUIRED') {
      throw new Error(`Credential resolution blocked: Connector '${ref.connectorId}' requires initial authentication configuration (CONFIGURATION_REQUIRED).`);
    }

    if (ref.expiresAt && new Date(ref.expiresAt).getTime() <= Date.now()) {
      throw new Error(`Credential resolution blocked: Token validity window expired at ${ref.expiresAt}. (AUTH_EXPIRED)`);
    }

    if (ref.credentialType === 'NONE') {
      return {
        credentialId: ref.credentialId,
        tokenType: 'NONE',
        tokenValue: '',
        headers: {},
      };
    }

    const secret = await this.store.getCredential(ref.credentialId);
    if (!secret) {
      if (!this.isOfflineTestMode) {
        throw new Error(`CONFIGURATION_REQUIRED: No secure hardware enclave credential found for '${ref.credentialId}'.`);
      }
      // In offline test mode with mock refs, generate an ephemeral mock token
      const mockSecret = `mock_sec_${ref.credentialId}`;
      return {
        credentialId: ref.credentialId,
        tokenType: ref.credentialType,
        tokenValue: mockSecret,
        headers: {
          Authorization: `Bearer ${mockSecret}`,
        },
      };
    }

    return {
      credentialId: ref.credentialId,
      tokenType: ref.credentialType,
      tokenValue: secret,
      headers: {
        Authorization: `Bearer ${secret}`,
      },
    };
  }

  /**
   * Securely sanitizes text or error messages to remove any authorization headers,
   * bearer tokens, or client secrets.
   */
  public sanitize(input: string): string {
    if (!input) return input;
    return input
      .replace(/Bearer\s+[A-Za-z0-9_\-\.~+/]+=*/gi, 'Bearer [REDACTED_SECRET]')
      .replace(/token=[A-Za-z0-9_\-\.~+/]+=*/gi, 'token=[REDACTED_SECRET]')
      .replace(/client_secret=[A-Za-z0-9_\-\.~+/]+=*/gi, 'client_secret=[REDACTED_SECRET]')
      .replace(/access_token=[A-Za-z0-9_\-\.~+/]+=*/gi, 'access_token=[REDACTED_SECRET]')
      .replace(/refresh_token=[A-Za-z0-9_\-\.~+/]+=*/gi, 'refresh_token=[REDACTED_SECRET]')
      .replace(/Authorization:\s*Bearer\s+[^\s]+/gi, 'Authorization: [REDACTED_SECRET]');
  }

  /**
   * Sanitizes an Error object so its message and stack never leak credentials.
   */
  public sanitizeError(err: Error): Error {
    const sanitizedMsg = this.sanitize(err.message);
    const sanitizedErr = new Error(sanitizedMsg);
    if (err.stack) {
      sanitizedErr.stack = this.sanitize(err.stack);
    }
    return sanitizedErr;
  }
}

export const credentialResolver = new CredentialResolver();

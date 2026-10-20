/**
 * AryaOS V1 — Stage 16: Credential Boundary Service
 *
 * Enforces the strict credential isolation boundary:
 * 1. Core AryaOS services NEVER receive or persist raw secrets (tokens, API keys, passwords).
 * 2. Credentials are represented internally exclusively via ConnectorCredentialRef.
 * 3. Secret storage in plaintext or localStorage is strictly forbidden. If runtime lacks secure vault,
 *    credentials are represented as CONFIGURATION_REQUIRED.
 * 4. Provides sandboxed offline test doubles (MockCredentialStore, MockOAuthProvider).
 */

import {
  ConnectorCredentialRef,
  ConnectorId,
  CredentialType,
  CredentialStatus,
} from '../types/connectorFabric';

export class CredentialBoundary {
  /**
   * Generates a non-sensitive Credential Reference for internal tracking.
   * ABSOLUTE RULE: Raw secrets are never contained in this reference.
   */
  public createCredentialRef(
    connectorId: ConnectorId,
    credentialType: CredentialType,
    options?: {
      expiresAt?: string;
      metadata?: Record<string, unknown>;
      status?: CredentialStatus;
    }
  ): ConnectorCredentialRef {
    const credentialId = `cred_ref_${connectorId}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    const status: CredentialStatus =
      options?.status ||
      (credentialType === 'NONE'
        ? 'VALID'
        : credentialType === 'LOCAL_CREDENTIAL'
        ? 'VALID'
        : 'CONFIGURATION_REQUIRED');

    return {
      credentialId,
      connectorId,
      credentialType,
      createdAt: new Date().toISOString(),
      expiresAt: options?.expiresAt,
      status,
      metadata: options?.metadata ? { ...options.metadata } : undefined,
    };
  }

  /**
   * Evaluates validity of a credential reference.
   * If expired or unconfigured, flags accordingly without fabricating validity.
   */
  public validateCredentialRef(ref: ConnectorCredentialRef | undefined): CredentialStatus {
    if (!ref || typeof ref !== 'object') {
      return 'CONFIGURATION_REQUIRED';
    }

    if (ref.status === 'REVOKED') {
      return 'REVOKED';
    }

    if (ref.status === 'CONFIGURATION_REQUIRED') {
      return 'CONFIGURATION_REQUIRED';
    }

    if (ref.expiresAt) {
      const expiry = new Date(ref.expiresAt).getTime();
      if (isNaN(expiry) || Date.now() >= expiry) {
        return 'EXPIRED';
      }
    }

    return ref.status;
  }

  /**
   * Asserts that an object or data structure contains zero raw credentials, keys, or tokens.
   * Throws an error if sensitive patterns are detected.
   */
  public assertNoRawCredentials(data: unknown, path = 'root'): void {
    if (data === null || data === undefined) return;

    if (typeof data === 'string') {
      if (
        /sk-[A-Za-z0-9\-_]{15,}/.test(data) ||
        /ghp_[A-Za-z0-9_]{15,}/.test(data) ||
        /Bearer\s+[A-Za-z0-9\-_\.=]{15,}/i.test(data) ||
        /password\s*[:=]\s*[^,\s]+/i.test(data) ||
        /eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/.test(data)
      ) {
        throw new Error(`Security Violation: Raw credential pattern detected at '${path}'`);
      }
      return;
    }

    if (typeof data === 'object') {
      for (const [key, value] of Object.entries(data as Record<string, unknown>)) {
        const lower = key.toLowerCase();
        const isMetadataKey =
          lower === 'tokentype' ||
          lower === 'token_type' ||
          lower === 'credentialtype' ||
          lower === 'credential_type' ||
          lower === 'credentialid' ||
          lower === 'credential_id' ||
          lower === 'credentialref' ||
          lower === 'credential_ref';

        const isSensitiveKey =
          !isMetadataKey &&
          (lower === 'token' ||
           lower === 'accesstoken' ||
           lower === 'access_token' ||
           lower === 'refreshtoken' ||
           lower === 'refresh_token' ||
           lower === 'authtoken' ||
           lower === 'auth_token' ||
           lower.includes('secret') ||
           lower.includes('password') ||
           lower.includes('apikey') ||
           lower.includes('api_key') ||
           lower === 'bearer');

        if (
          isSensitiveKey &&
          typeof value === 'string' &&
          value !== '[REDACTED_SECRET]' &&
          value.length > 5
        ) {
          throw new Error(`Security Violation: Raw credential detected in field '${path}.${key}'`);
        }
        this.assertNoRawCredentials(value, `${path}.${key}`);
      }
    }
  }
}

export const credentialBoundary = new CredentialBoundary();

/**
 * --- Stage 16 Offline Test Doubles ---
 */

export class MockConnectorCredentialStore {
  private secrets = new Map<string, string>();

  public storeTestSecret(credentialId: string, dummyValue: string): void {
    this.secrets.set(credentialId, dummyValue);
  }

  public getTestSecret(credentialId: string): string | null {
    return this.secrets.get(credentialId) || null;
  }

  public revoke(credentialId: string): void {
    this.secrets.delete(credentialId);
  }

  public clear(): void {
    this.secrets.clear();
  }
}

export class MockConnectorTransport {
  public async sendMockRequest(
    connectorId: string,
    endpoint: string,
    payload: Record<string, unknown>
  ): Promise<{ status: number; body: unknown }> {
    return {
      status: 200,
      body: {
        acknowledged: true,
        connectorId,
        endpoint,
        timestamp: new Date().toISOString(),
      },
    };
  }
}

export class MockOAuthProvider {
  public async simulateHandshake(
    connectorId: string,
    scopes: string[]
  ): Promise<{ credentialRef: ConnectorCredentialRef; grantedScopes: string[] }> {
    const grantedScopes = [...scopes];
    const credentialRef = credentialBoundary.createCredentialRef(connectorId, 'OAUTH2', {
      expiresAt: new Date(Date.now() + 3600000).toISOString(), // 1 hour TTL
      status: 'VALID',
      metadata: { mockProvider: 'MockOAuth', grantedScopes },
    });

    return { credentialRef, grantedScopes };
  }
}

export const mockCredentialStore = new MockConnectorCredentialStore();
export const mockConnectorTransport = new MockConnectorTransport();
export const mockOAuthProvider = new MockOAuthProvider();

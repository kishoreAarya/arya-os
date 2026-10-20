/**
 * AryaOS V1 — Stage 17: OAuth Provider Registry
 *
 * Defines OAuth 2.0 configuration blueprints for verified external services
 * (GitHub, Google Drive).
 */

import { ConnectorType } from '../types/connectorFabric';

export interface OAuthProviderConfig {
  providerType: ConnectorType;
  displayName: string;
  authorizationUrl: string;
  tokenUrl: string;
  defaultScopes: string[];
  pkceSupported: boolean;
  requiredConfiguration: string[];
}

export class OAuthProviderRegistry {
  private providers: Map<ConnectorType, OAuthProviderConfig> = new Map();

  constructor() {
    this.registerStandardProviders();
  }

  private registerStandardProviders(): void {
    // 1. GitHub OAuth
    this.providers.set('GITHUB', {
      providerType: 'GITHUB',
      displayName: 'GitHub OAuth 2.0',
      authorizationUrl: 'https://github.com/login/oauth/authorize',
      tokenUrl: 'https://github.com/login/oauth/access_token',
      defaultScopes: ['repo', 'read:org', 'read:user'],
      pkceSupported: true,
      requiredConfiguration: ['clientId'],
    });

    // 2. Google Drive OAuth
    this.providers.set('GOOGLE_DRIVE', {
      providerType: 'GOOGLE_DRIVE',
      displayName: 'Google Drive OAuth 2.0',
      authorizationUrl: 'https://accounts.google.com/o/oauth2/v2/auth',
      tokenUrl: 'https://oauth2.googleapis.com/token',
      defaultScopes: ['https://www.googleapis.com/auth/drive.readonly'],
      pkceSupported: true,
      requiredConfiguration: ['clientId'],
    });
  }

  public getProvider(type: ConnectorType): OAuthProviderConfig | null {
    return this.providers.get(type) || null;
  }

  public listProviders(): OAuthProviderConfig[] {
    return Array.from(this.providers.values());
  }
}

export const oauthProviderRegistry = new OAuthProviderRegistry();

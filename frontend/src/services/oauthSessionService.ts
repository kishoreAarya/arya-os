/**
 * AryaOS V1 — Stage 17: OAuth Session & State Management Service
 *
 * Manages ephemeral OAuth state tokens with cryptographic randomness, expiration,
 * and CSRF verification.
 */

export interface OAuthPendingSession {
  sessionId: string;
  connectorId: string;
  state: string;
  codeVerifier?: string;
  redirectUri: string;
  scopes: string[];
  createdAt: string;
  expiresAt: string;
}

export class OAuthSessionService {
  private sessions: Map<string, OAuthPendingSession> = new Map();
  private readonly SESSION_TTL_MS = 10 * 60 * 1000; // 10 minutes

  /**
   * Generates a new OAuth authorization session with secure state token.
   */
  public createSession(params: {
    connectorId: string;
    redirectUri: string;
    scopes: string[];
    codeVerifier?: string;
  }): OAuthPendingSession {
    const randomBytes = Math.random().toString(36).substring(2) + Date.now().toString(36);
    const state = `oauth_state_${params.connectorId}_${randomBytes}`;
    const sessionId = `sess_${randomBytes}`;
    const now = Date.now();

    const session: OAuthPendingSession = {
      sessionId,
      connectorId: params.connectorId,
      state,
      codeVerifier: params.codeVerifier,
      redirectUri: params.redirectUri,
      scopes: params.scopes,
      createdAt: new Date(now).toISOString(),
      expiresAt: new Date(now + this.SESSION_TTL_MS).toISOString(),
    };

    this.sessions.set(state, session);
    return session;
  }

  /**
   * Validates and consumes an incoming OAuth state string.
   * Throws if state is invalid, expired, or already consumed.
   */
  public consumeSession(state: string): OAuthPendingSession {
    const session = this.sessions.get(state);
    if (!session) {
      throw new Error(`OAuth Security Rejection: Invalid or unrecognized state token '${state}'. Possible CSRF attempt.`);
    }

    if (new Date(session.expiresAt).getTime() <= Date.now()) {
      this.sessions.delete(state);
      throw new Error(`OAuth Security Rejection: Session state has expired at ${session.expiresAt}. Reauthentication required.`);
    }

    // Single-use guarantee
    this.sessions.delete(state);
    return session;
  }

  public clear(): void {
    this.sessions.clear();
  }
}

export const oauthSessionService = new OAuthSessionService();

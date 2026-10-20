/**
 * AryaOS V1 — Stage 18: Event Payload Sanitizer
 *
 * Recursively scrubs credentials, bearer tokens, API keys, signatures, cookies,
 * client secrets, and passwords from incoming event payloads.
 * Enforces strict payload byte size limits.
 */

export class EventSanitizer {
  private readonly defaultMaxPayloadBytes = 1048576; // 1 MB

  /**
   * Sanitizes any value recursively, redacting sensitive patterns.
   */
  public sanitize<T>(data: T, maxBytes = this.defaultMaxPayloadBytes): T {
    if (data === null || data === undefined) {
      return data;
    }

    // Payload size guard
    const serialized = JSON.stringify(data);
    if (serialized && serialized.length > maxBytes) {
      throw new Error(`PayloadTooLarge: Event payload exceeds maximum allowed size of ${maxBytes} bytes (size: ${serialized.length} bytes)`);
    }

    return this.sanitizeValue(data);
  }

  private sanitizeValue(val: unknown): any {
    if (val === null || val === undefined) {
      return val;
    }

    if (typeof val === 'string') {
      return this.sanitizeString(val);
    }

    if (Array.isArray(val)) {
      return val.map((item) => this.sanitizeValue(item));
    }

    if (typeof val === 'object') {
      const sanitizedObj: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(val as Record<string, unknown>)) {
        const lowerKey = key.toLowerCase();
        const isSensitiveKey =
          lowerKey === 'authorization' ||
          lowerKey === 'token' ||
          lowerKey === 'access_token' ||
          lowerKey === 'refreshtoken' ||
          lowerKey === 'refresh_token' ||
          lowerKey === 'secret' ||
          lowerKey === 'clientsecret' ||
          lowerKey === 'client_secret' ||
          lowerKey === 'password' ||
          lowerKey === 'signature' ||
          lowerKey === 'cookie' ||
          lowerKey === 'apikey' ||
          lowerKey === 'api_key' ||
          lowerKey === 'private_key' ||
          lowerKey === 'bearer';

        if (isSensitiveKey && typeof value === 'string' && value !== '[REDACTED_SECRET]') {
          sanitizedObj[key] = '[REDACTED_SECRET]';
        } else {
          sanitizedObj[key] = this.sanitizeValue(value);
        }
      }
      return sanitizedObj;
    }

    return val;
  }

  private sanitizeString(str: string): string {
    return str
      .replace(/Bearer\s+[A-Za-z0-9\-._~+/]+=*/gi, 'Bearer [REDACTED_SECRET]')
      .replace(/ghp_[A-Za-z0-9_]{15,}/g, '[REDACTED_SECRET]')
      .replace(/sk-[A-Za-z0-9\-_]{15,}/g, '[REDACTED_SECRET]')
      .replace(/eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}(\.[A-Za-z0-9_-]+)?/g, '[REDACTED_SECRET]')
      .replace(/password\s*[:=]\s*[^,\s]+/gi, 'password=[REDACTED_SECRET]');
  }
}

export const eventSanitizer = new EventSanitizer();

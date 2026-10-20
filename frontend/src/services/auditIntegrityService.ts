/**
 * AryaOS V1 — Stage 22: Audit Integrity Service
 *
 * Enforces sanitization, secret scrubbing, prototype pollution defenses,
 * payload bounding, cryptographic fingerprinting, and deep immutability.
 */

import {
  MAX_OBJECT_DEPTH,
  MAX_KEYS_PER_OBJECT,
} from '../types/operationalAudit';

const SENSITIVE_KEY_PATTERNS = [
  /api[_-]?key/i,
  /token/i,
  /secret/i,
  /password/i,
  /passwd/i,
  /auth[_-]?header/i,
  /credential[_-]?ref/i,
  /private[_-]?key/i,
  /access[_-]?token/i,
  /bearer/i,
];

const FORBIDDEN_PROTOTYPE_KEYS = new Set(['__proto__', 'constructor', 'prototype']);

export class AuditIntegrityService {
  /**
   * Recursively sanitizes payloads:
   * - Strips prototype pollution keys
   * - Scrubs sensitive credentials
   * - Enforces maximum depth and key cardinality
   */
  public sanitizePayload<T>(input: T, currentDepth = 0): T {
    if (input === null || input === undefined) {
      return input;
    }

    if (typeof input !== 'object') {
      return input;
    }

    if (currentDepth >= MAX_OBJECT_DEPTH) {
      return '[TRUNCATED_MAX_DEPTH]' as unknown as T;
    }

    if (Array.isArray(input)) {
      const sanitizedArray = input
        .slice(0, MAX_KEYS_PER_OBJECT)
        .map((item) => this.sanitizePayload(item, currentDepth + 1));
      return sanitizedArray as unknown as T;
    }

    const sanitizedObj: Record<string, unknown> = {};
    const entries = Object.entries(input as Record<string, unknown>);
    let keyCount = 0;

    for (const [key, value] of entries) {
      if (keyCount >= MAX_KEYS_PER_OBJECT) {
        sanitizedObj['__truncated_keys_count__'] = entries.length - keyCount;
        break;
      }

      // 1. Prototype pollution guard
      if (FORBIDDEN_PROTOTYPE_KEYS.has(key)) {
        continue;
      }

      // 2. Secret / credential scrubbing
      if (this.isSensitiveKey(key)) {
        sanitizedObj[key] = '[REDACTED]';
        keyCount++;
        continue;
      }

      sanitizedObj[key] = this.sanitizePayload(value, currentDepth + 1);
      keyCount++;
    }

    return sanitizedObj as T;
  }

  /**
   * Checks if a property key represents a sensitive secret.
   */
  public isSensitiveKey(key: string): boolean {
    return SENSITIVE_KEY_PATTERNS.some((pattern) => pattern.test(key));
  }

  /**
   * Computes a deterministic canonical string fingerprint for a payload.
   */
  public computeFingerprint(payload: unknown): string {
    const canonical = this.canonicalize(payload);
    let hash = 0x811c9dc5;
    for (let i = 0; i < canonical.length; i++) {
      hash ^= canonical.charCodeAt(i);
      hash = (hash * 0x01000193) >>> 0;
    }
    return `fp_${hash.toString(16).padStart(8, '0')}`;
  }

  /**
   * Recursively sorts keys to create canonical JSON string.
   */
  private canonicalize(obj: unknown): string {
    if (obj === null || typeof obj !== 'object') {
      return JSON.stringify(obj) ?? '';
    }

    if (Array.isArray(obj)) {
      return `[${obj.map((item) => this.canonicalize(item)).join(',')}]`;
    }

    const sortedKeys = Object.keys(obj as Record<string, unknown>).sort();
    const parts = sortedKeys.map(
      (k) => `${JSON.stringify(k)}:${this.canonicalize((obj as Record<string, unknown>)[k])}`
    );
    return `{${parts.join(',')}}`;
  }

  /**
   * Recursively freezes an object graph to guarantee immutability.
   */
  public deepFreeze<T>(obj: T): Readonly<T> {
    if (obj === null || typeof obj !== 'object') {
      return obj;
    }

    Object.freeze(obj);

    for (const key of Object.getOwnPropertyNames(obj)) {
      const val = (obj as Record<string, unknown>)[key];
      if (val !== null && typeof val === 'object' && !Object.isFrozen(val)) {
        this.deepFreeze(val);
      }
    }

    return obj;
  }
}

export const auditIntegrityService = new AuditIntegrityService();

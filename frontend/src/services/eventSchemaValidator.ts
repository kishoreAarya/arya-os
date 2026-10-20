/**
 * AryaOS V1 — Stage 18: Event Schema Validator
 *
 * Enforces strict structural, type, and size constraints on inbound event payloads.
 * Prevents arbitrary or malformed external JSON from infiltrating the runtime.
 */

import { ExternalEvent, EventValidationResult } from '../types/externalEvent';
import { eventSourceRegistry } from './eventSourceRegistry';
import { eventSanitizer } from './eventSanitizer';

export class EventSchemaValidator {
  public validate(event: ExternalEvent): EventValidationResult {
    const errors: string[] = [];

    // 1. Source system support check
    if (!eventSourceRegistry.isSourceSupported(event.sourceSystem)) {
      return {
        valid: false,
        errors: [`Unsupported event source system: '${event.sourceSystem}'`],
      };
    }

    // 2. Event type support check
    const typeDef = eventSourceRegistry.getEventTypeDefinition(event.sourceSystem, event.eventType);
    if (!typeDef) {
      return {
        valid: false,
        errors: [
          `Event type '${event.eventType}' is not supported for source '${event.sourceSystem}'`,
        ],
      };
    }

    // 3. Payload size check & recursive sanitization
    let sanitizedPayload: Record<string, unknown>;
    try {
      sanitizedPayload = eventSanitizer.sanitize(
        event.payload,
        typeDef.maxPayloadBytes || 1048576
      );
    } catch (err: any) {
      return {
        valid: false,
        errors: [err.message || 'Payload sanitization failed'],
      };
    }

    // 4. Required fields check
    for (const field of typeDef.requiredFields) {
      if (
        sanitizedPayload[field] === undefined ||
        sanitizedPayload[field] === null ||
        sanitizedPayload[field] === ''
      ) {
        errors.push(`Missing required field '${field}' for event type '${event.eventType}'`);
      }
    }

    // 5. Field types check
    for (const [field, expectedType] of Object.entries(typeDef.fieldTypes)) {
      const val = sanitizedPayload[field];
      if (val !== undefined && val !== null) {
        if (expectedType === 'string' && typeof val !== 'string') {
          errors.push(`Field '${field}' must be a string, received ${typeof val}`);
        } else if (expectedType === 'number' && typeof val !== 'number') {
          errors.push(`Field '${field}' must be a number, received ${typeof val}`);
        } else if (expectedType === 'boolean' && typeof val !== 'boolean') {
          errors.push(`Field '${field}' must be a boolean, received ${typeof val}`);
        } else if (expectedType === 'array' && !Array.isArray(val)) {
          errors.push(`Field '${field}' must be an array`);
        } else if (expectedType === 'object' && (typeof val !== 'object' || Array.isArray(val))) {
          errors.push(`Field '${field}' must be an object`);
        }
      }
    }

    // 6. Schema version matching
    if (event.schemaVersion && event.schemaVersion !== typeDef.schemaVersion) {
      errors.push(
        `Schema version mismatch: event has '${event.schemaVersion}', expected '${typeDef.schemaVersion}'`
      );
    }

    return {
      valid: errors.length === 0,
      errors,
      sanitizedPayload,
    };
  }
}

export const eventSchemaValidator = new EventSchemaValidator();

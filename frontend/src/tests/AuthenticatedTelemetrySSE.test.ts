/**
 * AryaOS V1 — Authenticated SSE Telemetry Stream Tests
 * Validates:
 * 1. Authenticated fetch streaming with Authorization: Bearer <key>
 * 2. Proper parsing of SSE blocks, event types, payloads, and timestamps
 * 3. Ignoring keep-alive heartbeat comments
 * 4. Graceful fail-closed handling of 401 Unauthorized responses without infinite loops
 * 5. Stream cancellation and AbortController cleanup upon unsubscribe()
 * 6. Backward compatibility fallback to EventSource when no API key is present
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { subscribeToProjectTelemetry } from '../api/productionApi';

describe('Authenticated SSE Telemetry Streaming', () => {
  const originalFetch = globalThis.fetch;
  const originalEventSource = (globalThis as any).EventSource;

  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    (globalThis as any).EventSource = originalEventSource;
    localStorage.clear();
  });

  it('1. connects via fetch with Authorization: Bearer header when API key is configured', async () => {
    localStorage.setItem('arya_api_key', 'test-valid-arya-key-12345');

    let capturedUrl = '';
    let capturedOptions: RequestInit | undefined;

    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode('data: {"event": "CONNECTED", "project_id": "proj-auth-01"}\n\n')
        );
        controller.close();
      },
    });

    globalThis.fetch = vi.fn().mockImplementation((url, options) => {
      capturedUrl = url;
      capturedOptions = options;
      return Promise.resolve({
        ok: true,
        status: 200,
        statusText: 'OK',
        body: stream,
      });
    });

    const receivedEvents: any[] = [];
    const unsubscribe = subscribeToProjectTelemetry('proj-auth-01', (evt) => {
      receivedEvents.push(evt);
    });

    // Wait for stream to process
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(capturedUrl).toBe('/api/v1/projects/proj-auth-01/events');
    expect(capturedOptions?.headers).toMatchObject({
      'Authorization': 'Bearer test-valid-arya-key-12345',
      'Accept': 'text/event-stream',
    });
    expect(receivedEvents).toHaveLength(1);
    expect(receivedEvents[0].event_type).toBe('CONNECTED');

    unsubscribe();
  });

  it('2. correctly parses telemetry events and filters out heartbeat comments', async () => {
    localStorage.setItem('arya_api_key', 'test-valid-key');

    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        // Enqueue heartbeat and multi-event stream chunk
        controller.enqueue(encoder.encode(': heartbeat\n\n'));
        controller.enqueue(
          encoder.encode(
            'data: {"event_type": "JOB_SUBMITTED", "shot_id": "shot-101", "job_id": "job-501", "payload": {"status": "QUEUED"}}\n\n'
          )
        );
        controller.enqueue(encoder.encode(': heartbeat\n\n'));
        controller.enqueue(
          encoder.encode(
            'data: {"event_type": "JOB_PROGRESS", "shot_id": "shot-101", "job_id": "job-501", "payload": {"status": "RUNNING", "progress": 0.45}}\n\n'
          )
        );
        controller.close();
      },
    });

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: stream,
    });

    const events: any[] = [];
    const unsubscribe = subscribeToProjectTelemetry('proj-auth-02', (evt) => {
      events.push(evt);
    });

    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(events).toHaveLength(2);
    expect(events[0].event_type).toBe('JOB_SUBMITTED');
    expect(events[0].shot_id).toBe('shot-101');
    expect(events[0].data.status).toBe('QUEUED');

    expect(events[1].event_type).toBe('JOB_PROGRESS');
    expect(events[1].payload.progress).toBe(0.45);

    unsubscribe();
  });

  it('3. handles 401 Unauthorized fail-closed and calls onError without infinite reconnect loop', async () => {
    localStorage.setItem('arya_api_key', 'invalid-key');

    let fetchCallCount = 0;
    globalThis.fetch = vi.fn().mockImplementation(() => {
      fetchCallCount++;
      return Promise.resolve({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
      });
    });

    let receivedError: Error | null = null;
    const unsubscribe = subscribeToProjectTelemetry(
      'proj-unauth',
      () => {},
      (err) => {
        receivedError = err;
      }
    );

    await new Promise((resolve) => setTimeout(resolve, 100));

    expect(receivedError).toBeDefined();
    expect((receivedError as any)?.message).toContain('401');
    // Verify it did not retry after 401
    expect(fetchCallCount).toBe(1);

    unsubscribe();
  });

  it('4. aborts fetch request when unsubscribe() is called', async () => {
    localStorage.setItem('arya_api_key', 'test-valid-key');

    let aborted = false;
    const stream = new ReadableStream({
      start(controller) {
        // Keep stream open
      },
      cancel() {
        aborted = true;
      },
    });

    let signal: AbortSignal | undefined;
    globalThis.fetch = vi.fn().mockImplementation((_url, options) => {
      signal = options?.signal;
      if (signal) {
        signal.addEventListener('abort', () => {
          aborted = true;
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        body: stream,
      });
    });

    const unsubscribe = subscribeToProjectTelemetry('proj-cancel', () => {});
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(aborted).toBe(false);
    unsubscribe();
    expect(aborted).toBe(true);
    expect(signal?.aborted).toBe(true);
  });

  it('5. preserves backward-compatible EventSource fallback when no API key is configured', () => {
    // No API key in localStorage
    let messageHandler: ((e: any) => void) | null = null;
    const mockClose = vi.fn();

    class MockEventSource {
      url: string;
      constructor(url: string) {
        this.url = url;
      }
      set onmessage(fn: any) {
        messageHandler = fn;
      }
      close = mockClose;
    }

    (globalThis as any).EventSource = MockEventSource;

    const receivedEvents: any[] = [];
    const unsubscribe = subscribeToProjectTelemetry('proj-no-key', (evt) => {
      receivedEvents.push(evt);
    });

    expect(messageHandler).toBeDefined();

    messageHandler!({
      data: JSON.stringify({
        event_type: 'JOB_STATUS_CHANGED',
        data: { status: 'COMPLETED' },
      }),
    });

    expect(receivedEvents).toHaveLength(1);
    expect(receivedEvents[0].event_type).toBe('JOB_STATUS_CHANGED');

    unsubscribe();
    expect(mockClose).toHaveBeenCalled();
  });
});

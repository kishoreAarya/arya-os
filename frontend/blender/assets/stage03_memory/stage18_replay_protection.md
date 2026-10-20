# Stage 18: Replay Protection & Deduplication Architecture

## 1. Objective
To prevent duplicate webhook deliveries from causing redundant state modifications, cyclic mission replanning, or denial-of-service vulnerabilities, Stage 18 implements deterministic replay protection in `eventReplayProtection.ts`.

## 2. Deterministic Fingerprint Calculation
For any incoming `ExternalEvent`, a cryptographic SHA-256 fingerprint is generated over stable identity components:
$$\text{Fingerprint} = \text{SHA256}(\text{connectorId} \parallel \text{eventType} \parallel \text{occurredAt} \parallel \text{canonicalJSON}(\text{payload}))$$

If provider delivery IDs are present (e.g., `x-github-delivery` or `x-goog-channel-id`), they are indexed to guarantee immediate deduplication across identical deliveries.

## 3. Sliding Window Cache
- **Window Duration**: 15 minutes (900,000 ms).
- **Eviction Strategy**: Lazy TTL check and FIFO eviction when exceeding the maximum capacity (5,000 entries).
- **Persistence**: Fingerprint indices survive browser restarts and storage reloads via `eventRegistry.ts` backed by `executionPersistence`.

## 4. Behavior on Duplicate Event
When an event arrives whose fingerprint or delivery ID exists in the cache:
1. Processing terminates before state reconciliation.
2. Ingress returns `{ success: false, status: 'DUPLICATE_EVENT', isDuplicate: true }`.
3. An audit record is logged to Stage 09 Execution Journal (`EXTERNAL_EVENT_DUPLICATE`).
4. Mission Control replanning is NOT triggered, preventing infinite replanning loops.

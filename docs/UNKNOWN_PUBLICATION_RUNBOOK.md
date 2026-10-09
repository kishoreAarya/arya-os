# UNKNOWN-Publication Operator Runbook

Audience: the AryaOS operator (you). Written for non-experts; every
instruction below was verified against the actual implementation on
branch `v2`. Source files are cited so engineering can re-verify.

---

## 1. Purpose and safety principle

### What UNKNOWN means

When AryaOS publishes a video, it records a durable row in the
`publication_attempts` table **before** any external call, and moves it
through: `PENDING → IN_PROGRESS → SUCCEEDED | FAILED | UNKNOWN`
(`backend/app/services/publication_attempts.py`).

* **FAILED** = *evidence supports that no public post was created*
  (the provider explicitly rejected the request, or the request was
  provably never sent).
* **UNKNOWN** = *something went wrong at a moment when the provider may
  already have acted* — for example a network timeout **after** the
  upload/publish request was sent, or a successful upload whose
  bookkeeping write could not be confirmed
  (`backend/app/agents/publishing.py`, the branches that call
  `mark_unknown`).

### Why you must NOT blindly retry an UNKNOWN publication

Retrying means "submit again to the provider." If the first attempt
actually created a public post, a retry creates a **duplicate public
post**. The system therefore treats UNKNOWN as a **blocking** state:
the admission logic refuses any new attempt for the same publication
intent while the latest attempt is `PENDING`, `IN_PROGRESS`, `UNKNOWN`,
or `SUCCEEDED` (`publication_attempts.py`, `BLOCKING_STATUSES`). An
UNKNOWN row can only be exited **by an operator, through the resolve
API**, after gathering evidence. There is no automated retry and no
automated polling — that is a deliberate, ratified design decision
(`backend/app/services/publication_attempt_reconciliation.py`, module
docstring).

> Guarantee honesty: AryaOS does **not** guarantee exactly-once
> delivery to the provider. It guarantees that AryaOS itself will never
> *automatically* send a second publication for an intent whose outcome
> is uncertain, and that every resolution requires either verified
> provider evidence or a recorded operator attestation.

---

## 2. When to use this runbook

Use it when a publication attempt shows status **UNKNOWN**, or a
**stale PENDING / IN_PROGRESS** (the worker likely crashed — a row
untouched for 30+ minutes in those states is treated as crashed, not
live: `_ACTIVE_EXECUTION_FLOOR` in the reconciliation service).

Typical triggers visible in the attempt's `error` field (real strings
written by `backend/app/agents/publishing.py`):

* `"upload exception: …"` — the upload call raised mid-exchange.
* `"publish exception: …"` — the publish call raised after possible
  submission.
* `"upload succeeded without a provider media id; anchor impossible"`.
* `"external-content anchor persistence failed with an uncertain
  database outcome after a successful upload; publication aborted
  before publish"` — the video may exist at the provider **unpublished**
  (an "orphaned upload"; see §6).

What the code permits (the full transition matrix, enforced in
`reconciliation.resolve_attempt`):

| From | To SUCCEEDED | To FAILED |
|---|---|---|
| UNKNOWN | external post id **+** fail-closed in-resolve provider verification ("ready") | attestation required |
| IN_PROGRESS (stale ≥ 30 min) | external post id **+** provider verification **+** 30-min floor | attestation **+** `force: true` **+** 30-min floor |
| PENDING (stale ≥ 30 min) | **illegal** (no irreversible call was ever made from PENDING) | attestation **+** `force: true` **+** 30-min floor |
| SUCCEEDED / FAILED | terminal — not resolvable | terminal (FAILED already allows a fresh attempt via normal admission) |

Extra rules the code enforces:

* **Scheduled attempts** (`scheduled_at` set): a → FAILED attestation
  must contain the literal phrase **"including scheduled posts"**,
  because a provider-side scheduled publication may still fire later
  (F-14a).
* **Evidence-gated FAILED** (F-02a): if the attempt has a persisted
  provider media id (an "anchor") and the provider lookup reports the
  publication **publicly live**, the FAILED resolution is **refused** —
  your attestation is contradicted.
* Resolutions are conditional database updates (CAS): if the row moved
  underneath you (live execution or another operator), the resolve call
  fails with `409` and nothing is written.

---

## 3. Investigation procedure

All API calls below require the API key as a Bearer header
(`Authorization: Bearer $ARYA_API_KEY`) — the whole `/publishing`
router is auth-protected (`backend/app/main.py`, `include_router(
publishing.router, dependencies=[Depends(verify_api_key)])`). The
examples use `http://localhost:8000` and the environment variable
`$ARYA_API_KEY`; substitute your deployment's host. **Never paste the
real key into a shared document.**

### Step 1 — Find the attempt

```
curl -s -H "Authorization: Bearer $ARYA_API_KEY" \
  "http://localhost:8000/publishing/attempts?status=UNKNOWN&limit=50"
```

Filters supported by the implementation: `status`, `video_id` (UUID),
`limit` (1–200, default 50), newest first
(`backend/app/api/routers/publishing.py`, `GET /attempts`).

Each row (`PublicationAttemptView`) gives you the identifiers that
really exist on the model (`backend/app/models/publication.py`):
`id`, `video_id`, `workflow_run_id`, `platform`, `social_platform`,
`integration_id`, `intent_key`, `attempt_number`, `status`,
`scheduled_at`, `external_content_id` (the provider media id
"anchor"), `external_post_id`, `public_url`, `error`, `created_at`,
`updated_at`.

### Step 2 — Read the provider evidence (read-only)

```
curl -s -H "Authorization: Bearer $ARYA_API_KEY" \
  "http://localhost:8000/publishing/attempts/<attempt_id>/evidence"
```

This calls the adapter's `check_processing()` against the attempt's
persisted `external_content_id` anchor. It **never mutates** the
attempt. Response fields: `attempt_id`, `attempt_status`,
`external_content_id`, `provider_status`, `progress_percent`,
`provider_error`, `checked_at`.

* `409` "no persisted external_content_id anchor" → the attempt never
  recorded a provider media id; there is nothing to verify
  provider-side (typical for failures before/at upload).
* `provider_status` meanings (verified per adapter):
  * **`ready`** — provider confirms the publication is **publicly
    live**: for YouTube this means processing succeeded AND
    `privacyStatus == "public"` (`backend/app/platforms/youtube.py`,
    `check_processing`); for Postiz, the post state is
    `published`/`ready`.
  * **`processing`** — provider still working; re-check later.
  * **`failed`** — provider reports the publication failed.
  * **`unknown`** — provider answer unusable/absent (fail-closed
    default).

### Step 3 — Correlate before deciding

* Note `workflow_run_id` → the workflow's approval history and
  manifest binding (`GET /publishing/manifests/{manifest_id}` returns
  the approved content fingerprint and destination).
* Note `created_at`/`updated_at` — for PENDING/IN_PROGRESS rows the
  30-minute floor is computed from `updated_at`.
* If useful, cross-check the provider's own console (YouTube Studio /
  Postiz UI) using the `external_content_id` / `external_post_id`
  values. The console is an *additional* evidence source; the resolve
  API itself re-verifies with the provider for → SUCCEEDED.

---

## 4. Decision tree

```
Evidence endpoint says:
├─ provider_status = "ready"
│    → Publication is publicly live.
│      Resolve to SUCCEEDED (§5, Case A). Do NOT resolve FAILED;
│      the API will refuse it anyway (F-02a).
├─ provider_status = "failed" or provider/user confirms NO post exists
│    → Resolve to FAILED with an honest attestation (§5, Case B).
│      Scheduled attempt? Attestation must include the phrase
│      "including scheduled posts" after you cancel/verify the
│      scheduled publication with the provider.
├─ provider_status = "processing"
│    → Wait and re-run the evidence call later. Leave UNKNOWN.
├─ provider_status = "unknown" / 409 no anchor / provider unreachable
│    │
│    ├─ You can independently verify in the provider console that a
│    │  public post exists (you have its post id)
│    │    → Resolve to SUCCEEDED — the resolve call re-verifies
│    │      "ready" with the provider itself and fails closed if the
│    │      provider does not confirm. Your console check supplies
│    │      the external post id.
│    │
│    ├─ You can verify NO post exists (console shows nothing) AND the
│    │  attempt is not scheduled (or you cancelled the schedule)
│    │    → Resolve to FAILED with attestation describing your
│    │      evidence source and check time.
│    │
│    └─ Still inconclusive → LEAVE UNKNOWN. Escalate (§7). Do not
│       guess, do not retry, do not resolve "just to unblock".
└─ Evidence CONFLICTS (e.g. console shows a post but the evidence
     endpoint says failed/unknown, or two sources disagree)
       → STOP. Escalate (§7). Never resolve on conflicting evidence.
```

**A plain-language restatement:** only three safe exits exist —
*provider-confirmed live* → SUCCEEDED; *affirmatively established no
post* → FAILED with your recorded reasoning; *anything short of that*
→ leave it UNKNOWN and escalate. "Probably fine" is not a resolution.

---

## 5. Exact operational steps

### Case A — Resolve to SUCCEEDED (publication verified)

```
curl -s -X POST -H "Authorization: Bearer $ARYA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "from_status": "UNKNOWN",
        "to_status": "SUCCEEDED",
        "external_post_id": "<provider post id>",
        "public_url": "<public URL of the post>"
      }' \
  "http://localhost:8000/publishing/attempts/<attempt_id>/resolve"
```

Requirements enforced by the code: `external_post_id` is mandatory;
the provider is re-checked **inside the resolve** and must answer
`ready`, otherwise `409` and nothing is written
(`reconciliation._verify_ready_with_provider`). `public_url` is
optional. Possible errors: `404` unknown attempt; `409` (no anchor /
verification failed / inside the 30-min floor / row moved
concurrently); `422` illegal transition (e.g. PENDING → SUCCEEDED).

### Case B — Resolve to FAILED (no publication, established)

```
curl -s -X POST -H "Authorization: Bearer $ARYA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "from_status": "UNKNOWN",
        "to_status": "FAILED",
        "attestation": "Checked YouTube Studio for content <external_content_id> at 2026-10-10T09:12Z — no video exists on the channel; upload had timed out."
      }' \
  "http://localhost:8000/publishing/attempts/<attempt_id>/resolve"
```

* `attestation` (≤ 2000 chars) is **required** and becomes part of the
  immutable audit event — write what YOU checked, where, and when.
* Scheduled attempt: include the phrase **"including scheduled
  posts"** (after cancelling/verifying the schedule at the provider).
* Stale `PENDING`/`IN_PROGRESS` sources additionally require
  `"force": true` and only work past the 30-minute floor.
* If the attempt has an anchor and the provider says the post is
  publicly live, the API refuses (`409`) — the attestation was
  contradicted; go back to §4.

The request schema forbids unknown fields
(`ResolveAttemptRequest`, `extra="forbid"`), so copy the field names
exactly. On success the response is the updated `PublicationAttemptView`.

### What happens afterwards

* **Audit trail:** every successful resolution appends an immutable
  `SystemLog` event `PublicationAttemptResolved` carrying from/to
  statuses, your inputs, and the verification outcome. The attempt's
  original `error` text is never overwritten — it stays as the record
  of why the row entered its blocking state
  (`publication_attempt_reconciliation.py`, "Auditability").
* **Retry after FAILED:** once the latest attempt is FAILED, a *new*
  publication attempt (attempt_number+1) is allowed through the normal
  publish flow (`publication_attempts.admit_attempt`). You never need
  to "reset" anything to retry.
* **Missing Video-row writeback after SUCCEEDED:** if the video's
  published-id writeback was lost (crash after publish), submitting
  the **same publication request again** is safe and triggers the
  idempotent self-heal — it updates the Video row only if the field is
  still empty and never makes a provider call
  (`backend/app/agents/publishing.py`, F-10a duplicate-path heal).

---

## 6. Orphaned uploads (media at the provider, never published)

Situation: upload succeeded, `external_content_id` (anchor) exists,
but the publish step never completed — the provider holds your video
**unpublished**. AryaOS has **no API to delete provider-side media**
(NOT VERIFIED capability — adapters implement upload / publish /
check only). Until you resolve the attempt:

* it stays blocking (correct — no duplicate can be dispatched);
* practical handling: resolve per §4 once evidence establishes the
  outcome, and remove the orphaned draft/media **through the
  provider's own console** (YouTube Studio / Postiz UI) if you do not
  intend to publish it. Record what you removed in the attestation.

---

## 7. Escalation and prohibited actions

**Escalate to engineering** (placeholders — fill in your real
contacts):

* Engineering contact: `__ENGINEER_NAME__ / __CHANNEL__`
* Owner escalation: `__OWNER_NAME__ / __CHANNEL__`
* Security-sensitive findings: follow `.github/SECURITY.md`

Escalate when: evidence is inconclusive after two checks separated in
time; sources conflict; the resolve API returns an unexpected error;
or more than one attempt shows UNKNOWN for the same intent_key.

**Prohibited actions** (each would defeat a safety property the code
is built around):

1. **No manual database edits** of `publication_attempts` rows — you
   would bypass the CAS/audit machinery. All exits go through the
   resolve API.
2. **No bypassing the approval/manifest checks** to "make it publish".
3. **No fabricated evidence or copy-pasted attestations** — the
   attestation is a signed-off statement of what you personally
   verified.
4. **No state resets merely to enable a retry.** If a retry is truly
   needed, the only supported path is an evidence-based resolution to
   FAILED; admission then permits a fresh attempt.
5. **No republishing "because it probably failed"** while the row is
   UNKNOWN.

---

## 8. Worked examples (all identifiers are SYNTHETIC)

### Example 1 — Confirmed publication → SUCCEEDED

* Alert: attempt `11111111-aaaa-4bbb-8ccc-000000000001` is UNKNOWN,
  `error = "publish exception: TimeoutException"`, anchor
  `external_content_id = "vid-synth-001"`.
* Evidence call → `provider_status: "ready"`, and the YouTube Studio
  URL `https://youtu.be/vid-synth-001` shows the video public.
* Action: POST resolve with `from_status: "UNKNOWN"`,
  `to_status: "SUCCEEDED"`, `external_post_id: "vid-synth-001"`,
  `public_url: "https://youtu.be/vid-synth-001"`. The in-resolve
  provider verification confirms `ready`; status becomes SUCCEEDED.
* Verification: `GET /publishing/attempts?video_id=<uuid>` shows
  `SUCCEEDED` with the post id recorded; SystemLog carries the
  resolution event.

### Example 2 — Confirmed non-publication → FAILED

* Attempt `22222222-aaaa-4bbb-8ccc-000000000002` UNKNOWN with
  `error = "upload exception: ConnectError"`, **no anchor** (evidence
  endpoint returns `409` — nothing was ever registered provider-side;
  a connect-refused/DNS error means the request was provably never
  sent).
* Provider console shows no such media.
* Action: POST resolve `to_status: "FAILED"` with attestation:
  *"Connect-refused before send; provider console shows no media for
  this video as of 2026-10-10T10:03Z."* Not scheduled → no special
  phrase needed. A later intentional republish goes through the normal
  publish flow as attempt 2.

### Example 3 — Inconclusive evidence → stay UNKNOWN, escalate

* Attempt `33333333-aaaa-4bbb-8ccc-000000000003` UNKNOWN after
  `"publish exception: ReadTimeout"`, anchor present; evidence call →
  `provider_status: "unknown"`, `provider_error: "lookup failed"`;
  provider console temporarily unreachable.
* Action: **none** on the attempt. Re-check evidence after 30 minutes.
  Still `unknown` → escalate per §7 with the attempt id and both
  evidence timestamps. The publication stays blocked — that is the
  system working as designed.

---

## Source files this runbook is based on

* `backend/app/services/publication_attempts.py` — states, blocking
  semantics, CAS transitions.
* `backend/app/services/publication_attempt_reconciliation.py` —
  resolution rules, evidence verification, 30-min floor, scheduled
  acknowledgement, audit event.
* `backend/app/agents/publishing.py` — where UNKNOWN is recorded and
  the duplicate/self-heal path.
* `backend/app/api/routers/publishing.py` — the operator API surface
  (`/attempts`, `/attempts/{id}/evidence`, `/attempts/{id}/resolve`)
  and request/response schemas.
* `backend/app/models/publication.py` — attempt fields.
* `backend/app/platforms/youtube.py` — `check_processing` "ready"
  definition (processing succeeded AND public).

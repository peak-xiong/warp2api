# Data Storage Architecture (SSOT)

## Goal
Ensure reusable runtime/ops data is persisted in one place and accessed via unified repository interfaces.

## Single Source of Truth
- SQLite database file:
  - default: `data/token_pool.db`
  - override: `WARP_TOKEN_DB_PATH`

## Persisted Domains
1. Token accounts (`token_accounts`)
- refresh token ciphertext
- token status (`active/cooldown/blocked/quota_exhausted/disabled`)
- error and cooldown metadata
- usage counters

2. Token audit logs (`token_audit_logs`)
- admin actions
- runtime send/refresh outcomes
- operation details and timestamps

3. Monitor health snapshots (`token_health_snapshots`)
- per-token monitor status
- last check / last success
- failure streak and latency

4. App state kv (`app_state`)
- reusable runtime state entries
- future extension point for migrations/checkpoints

## Access Rules
- All read/write operations must go through:
  - `src/warp2api/infrastructure/token_pool/repository.py`
- Services must not write direct SQL outside repository.
- Monitor status API must read persisted snapshots from DB (not in-memory caches).

## In-memory Data Policy
- Allowed only for ephemeral synchronization primitives:
  - token locks
  - task handles
- Not allowed for reusable business state.


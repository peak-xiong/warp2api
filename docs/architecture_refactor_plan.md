# warp2api Architecture (Archived Snapshot)

> Status: archived design snapshot.
> Source of truth: `docs/current_architecture.md` and `docs/clean_architecture_scaffold.md`.

## Scope
- Single-path bridge runtime (no legacy adapter/runtime fallback chains)
- `src`-first package layout
- Multi refresh-token rotation + health monitoring

## Active Runtime Entry
- Bridge: `src/warp2api/app/bridge_runtime.py`
- OpenAI-compatible: `src/warp2api/app/openai_runtime.py`

## Active Code Paths

### API Layer
- `src/warp2api/app/bridge_app.py`
- `src/warp2api/api/routes/*`
- `src/warp2api/api/runtime.py`
- `src/warp2api/api/schemas.py`

### Adapter Layer
- OpenAI: `src/warp2api/adapters/openai/{app.py,router.py}`
- Anthropic: `src/warp2api/adapters/anthropic/router.py`
- Gemini: `src/warp2api/adapters/gemini/router.py`

### Application Layer
- Warp request orchestration: `src/warp2api/application/services/warp_request_service.py`
- Token rotation service: `src/warp2api/application/services/token_rotation_service.py`

### Infrastructure Layer
- Protobuf codec: `src/warp2api/infrastructure/protobuf/codec.py`
- Minimal protobuf request builder: `src/warp2api/infrastructure/protobuf/minimal_request.py`
- Warp transport: `src/warp2api/infrastructure/transport/warp_transport.py`
- Warp event parser: `src/warp2api/infrastructure/transport/event_parser.py`

### Domain Layer
- Model catalog and strict model validation:
  - `src/warp2api/domain/models/model_catalog.py`

## Token Pool / Account State
- Background monitor: `src/warp2api/infrastructure/monitoring/account_pool_monitor.py`
- Diagnostics API:
  - `GET /api/warp/token_pool/status`
  - `GET /api/warp/token_pool/health`

## Removed Legacy Trees
- Removed: `protobuf2openai/*`
- Removed: `warp2protobuf/api/*`
- Removed: old compatibility wrappers under `warp2protobuf/warp/*` (except active monitor)

## Operations
- PM2 runtime uses `uv run warp2api-bridge` and `uv run warp2api-openai`
- Cross-platform start/stop scripts updated to new entrypoints.

## Validation Baseline
- Test suite: `23 passed`
- Compile check: `python -m py_compile` over repository Python files passes.

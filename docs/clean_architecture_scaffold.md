# Clean Architecture Scaffold (warp2api)

## Goal
Keep external APIs stable while making internals maintainable and testable.

## Current Status (2026-02-19)
- New src-layout package has been introduced:
  - `src/warp2api/*`
  - unified launcher entrypoints are available via `pyproject` scripts.
- Runtime primary entry modules:
  - `src/warp2api/app/bridge_runtime.py`
  - `src/warp2api/app/openai_runtime.py`
- Phase 3 migration status:
  - Warp transport/event parsing/minimal request/token-rotation core moved into `src/warp2api`.
  - Old compatibility export files under `warp2protobuf/warp/*` have been removed.
  - Legacy route tree `warp2protobuf/api/*` and old adapter tree `protobuf2openai/*` have been removed.

## Layered Code Paths

### 1) Presentation Layer
- `src/warp2api/app/bridge_app.py` (app assembly)
- `src/warp2api/api/routes/codec_routes.py`
- `src/warp2api/api/routes/auth_routes.py`
- `src/warp2api/api/routes/model_routes.py`
- `src/warp2api/api/routes/warp_send_routes.py`
- `src/warp2api/api/routes/warp_chat_routes.py`
- `src/warp2api/api/routes/warp_token_routes.py`
- `src/warp2api/api/routes/ws_routes.py`
- `src/warp2api/api/runtime.py` (shared websocket/packet state)
- Responsibility:
  - HTTP route binding
  - request validation
  - response serialization

### 2) API Orchestration Layer
- `src/warp2api/application/services/warp_request_service.py`
- Responsibility:
  - packet sanitization
  - model/query extraction and strict validation
  - protobuf encoding
  - execution strategy (single primary path, no fallback branch)

### 3) Application Service Layer
- `src/warp2api/application/services/token_rotation_service.py`
- Responsibility:
  - retry + refresh-token rotation
  - quota-aware cooldown policy
  - call unified transport
- `src/warp2api/infrastructure/monitoring/account_pool_monitor.py`
- Responsibility:
  - background refresh-token health checks
  - account pool diagnostics snapshot for API

### 4) Infrastructure Layer
- `src/warp2api/infrastructure/transport/warp_transport.py`
- Responsibility:
  - HTTP/1.1 request
  - SSE framing and protobuf event decode

- `src/warp2api/infrastructure/transport/event_parser.py`
- Responsibility:
  - extract event type / text / tool calls from parsed events

- `src/warp2api/infrastructure/protobuf/minimal_request.py`
- Responsibility:
  - all-2-api style minimal protobuf request bytes builder

### 5) Entrypoints
- `server.py`
- `openai_compat.py`
- Both are lightweight launchers and do not contain fallback/compat routing logic.

## OpenAI Adapter Side
- `src/warp2api/application/services/chat_gateway_service.py` unified chat orchestration
- `src/warp2api/application/services/chat_gateway_support.py` shared packet/state/event/sse helpers
- `src/warp2api/application/services/openai_protocol_service.py` OpenAI Responses/model-list protocol shaping
- `src/warp2api/adapters/anthropic/router.py` Anthropic adapter
- `src/warp2api/adapters/gemini/router.py` Gemini adapter

## Configuration
- Multi-token rotation:
  - `WARP_REFRESH_TOKEN`
  - `WARP_REFRESH_TOKENS`
- Cooldown:
  - `WARP_TOKEN_COOLDOWN_SECONDS`
- Background health monitor:
  - `WARP_POOL_HEALTH_INTERVAL_SECONDS`

## Diagnostics Endpoints
- `GET /api/warp/token_pool/status`
  - Rotation pool + cooldown status.
- `GET /api/warp/token_pool/health`
  - Background health monitor status, per-token latest check results.

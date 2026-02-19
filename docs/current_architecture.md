# Current Architecture

## Layering

- `src/warp2api/adapters/*`
  - API protocol adapters only.
  - Exposes HTTP routes for OpenAI, Anthropic, Gemini.
  - Converts request/response payload formats.

- `src/warp2api/application/services/*`
  - Main orchestration logic.
  - Handles auth checks, bridge warmup, session isolation, packet assembly.
  - Handles stream/event aggregation and protocol-level response shaping.

- `src/warp2api/infrastructure/*`
  - Low-level implementations.
  - Protobuf runtime/codec, transport, auth refresh, account monitoring, settings.

- `src/warp2api/domain/*`
  - Domain models and errors (provider-agnostic constraints).

- `src/warp2api/app/*`
  - Runtime entrypoints and app bootstrap.

## Request Flow

1. Adapter route receives request (`/v1/chat/completions`, `/v1/messages`, Gemini routes).
2. Adapter normalizes protocol payload.
3. `application/services/chat_gateway_service.py` executes the unified chat flow.
4. Bridge request is sent to Warp via protobuf bridge endpoints.
5. Events are parsed and converted back to protocol-compatible outputs.

## Design Rules

- Keep protocol-specific logic in `adapters`.
- Keep orchestration logic in `application/services`.
- Keep IO/protobuf/runtime details in `infrastructure`.
- Avoid `application -> adapters/*` imports.
- Prefer strict model ID validation; do not silently fallback on unknown model IDs.


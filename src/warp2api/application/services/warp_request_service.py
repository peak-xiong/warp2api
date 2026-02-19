from __future__ import annotations

from typing import Any, Dict, Tuple

from warp2api.infrastructure.protobuf.schema_sanitizer import sanitize_mcp_input_schema_in_packet

from warp2api.domain.models.model_catalog import get_model_config, normalize_model_name
from warp2api.infrastructure.protobuf.codec import encode_request_packet
from warp2api.application.services.token_rotation_service import (
    send_protobuf_with_rotation,
)


def extract_query_and_model_from_packet(data: Dict[str, Any]) -> Tuple[str, str]:
    model_cfg = (((data or {}).get("settings") or {}).get("model_config") or {})
    model_raw = str(model_cfg.get("base") or "").strip()
    model_tag = normalize_model_name(model_raw) if model_raw else "auto"
    get_model_config(model_tag)

    inputs = (((data or {}).get("input") or {}).get("user_inputs") or {}).get("inputs") or []
    query = ""
    for item in reversed(inputs):
        user_query = (item or {}).get("user_query") or {}
        text = str((user_query or {}).get("query") or "").strip()
        if text:
            query = text
            break
    return (query or "warmup"), model_tag


async def execute_warp_packet(
    actual_data: Dict[str, Any],
    message_type: str,
    timeout_seconds: int,
    client_version: str,
    os_version: str,
) -> Dict[str, Any]:
    wrapped = sanitize_mcp_input_schema_in_packet({"json_data": actual_data})
    safe_data = wrapped.get("json_data", actual_data)

    query, model_tag = extract_query_and_model_from_packet(safe_data)
    protobuf_bytes = encode_request_packet(safe_data, message_type)

    result_raw = await send_protobuf_with_rotation(
        protobuf_bytes=protobuf_bytes,
        timeout_seconds=timeout_seconds,
        client_version=client_version,
        os_version=os_version,
        model_tag=model_tag,
    )

    return {
        "query": query,
        "model_tag": model_tag,
        "protobuf_bytes": protobuf_bytes,
        "result_raw": result_raw,
    }

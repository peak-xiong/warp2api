#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Codec controller for protobuf encode/decode endpoints.
"""

from __future__ import annotations

import base64
from typing import Any, Awaitable, Callable, Dict

from fastapi import HTTPException

from warp2api.observability.logging import logger
from warp2api.infrastructure.protobuf.utils import protobuf_to_dict, dict_to_protobuf_bytes
from warp2api.infrastructure.protobuf.schema_sanitizer import sanitize_mcp_input_schema_in_packet
from warp2api.infrastructure.protobuf.codec import encode_smd_inplace
from .schemas import EncodeRequest, DecodeRequest, StreamDecodeRequest


LogPacketFn = Callable[[str, Dict[str, Any], int], Awaitable[None]]


async def encode_request_payload(request: EncodeRequest, log_packet: LogPacketFn) -> Dict[str, Any]:
    actual_data = request.get_data()
    if not actual_data:
        raise HTTPException(400, "数据包不能为空")

    wrapped = {"json_data": actual_data}
    wrapped = sanitize_mcp_input_schema_in_packet(wrapped)
    actual_data = wrapped.get("json_data", actual_data)
    actual_data = encode_smd_inplace(actual_data)
    protobuf_bytes = dict_to_protobuf_bytes(actual_data, request.message_type)

    try:
        await log_packet("encode", actual_data, len(protobuf_bytes))
    except Exception as log_error:
        logger.warning(f"数据包记录失败: {log_error}")

    return {
        "protobuf_bytes": base64.b64encode(protobuf_bytes).decode("utf-8"),
        "size": len(protobuf_bytes),
        "message_type": request.message_type,
    }


async def decode_request_payload(request: DecodeRequest, log_packet: LogPacketFn) -> Dict[str, Any]:
    if not request.protobuf_bytes or not request.protobuf_bytes.strip():
        raise HTTPException(400, "Protobuf数据不能为空")

    try:
        protobuf_bytes = base64.b64decode(request.protobuf_bytes)
    except Exception as decode_error:
        logger.error(f"Base64解码失败: {decode_error}")
        raise HTTPException(400, f"Base64解码失败: {str(decode_error)}")

    if not protobuf_bytes:
        raise HTTPException(400, "解码后的protobuf数据为空")

    json_data = protobuf_to_dict(protobuf_bytes, request.message_type)
    try:
        await log_packet("decode", json_data, len(protobuf_bytes))
    except Exception as log_error:
        logger.warning(f"数据包记录失败: {log_error}")

    return {"json_data": json_data, "size": len(protobuf_bytes), "message_type": request.message_type}


async def decode_stream_payload(request: StreamDecodeRequest, log_packet: LogPacketFn) -> Dict[str, Any]:
    results = []
    total_size = 0

    for i, chunk_b64 in enumerate(request.protobuf_chunks):
        try:
            chunk_bytes = base64.b64decode(chunk_b64)
            chunk_json = protobuf_to_dict(chunk_bytes, request.message_type)
            chunk_result = {
                "chunk_index": i,
                "json_data": chunk_json,
                "size": len(chunk_bytes),
            }
            results.append(chunk_result)
            total_size += len(chunk_bytes)
            await log_packet(f"stream_decode_chunk_{i}", chunk_json, len(chunk_bytes))
        except Exception as e:
            logger.warning(f"数据块 {i} 解码失败: {e}")
            results.append({"chunk_index": i, "error": str(e), "size": 0})

    try:
        all_bytes = b"".join([base64.b64decode(chunk) for chunk in request.protobuf_chunks])
        complete_json = protobuf_to_dict(all_bytes, request.message_type)
        await log_packet("stream_decode_complete", complete_json, len(all_bytes))
        complete_result = {"json_data": complete_json, "size": len(all_bytes)}
    except Exception as e:
        complete_result = {"error": f"无法拼接完整消息: {e}", "size": total_size}

    return {
        "chunks": results,
        "complete": complete_result,
        "total_chunks": len(request.protobuf_chunks),
        "total_size": total_size,
        "message_type": request.message_type,
    }


def get_schemas_payload() -> Dict[str, Any]:
    from warp2api.infrastructure.protobuf.runtime import ensure_proto_runtime, ALL_MSGS, msg_cls

    ensure_proto_runtime()
    schemas = []
    for msg_name in ALL_MSGS:
        try:
            MessageClass = msg_cls(msg_name)
            descriptor = MessageClass.DESCRIPTOR
            fields = []
            for field in descriptor.fields:
                fields.append(
                    {
                        "name": field.name,
                        "type": field.type,
                        "label": getattr(field, "label", None),
                        "number": field.number,
                    }
                )
            schemas.append(
                {
                    "name": msg_name,
                    "full_name": descriptor.full_name,
                    "field_count": len(fields),
                    "fields": fields[:10],
                }
            )
        except Exception as e:
            logger.warning(f"获取schema {msg_name} 信息失败: {e}")

    return {
        "schemas": schemas,
        "total_count": len(schemas),
        "message": f"找到 {len(schemas)} 个protobuf消息类型",
    }

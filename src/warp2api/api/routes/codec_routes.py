#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from warp2api.observability.logging import logger
from ..codec_controller import (
    decode_request_payload,
    decode_stream_payload,
    encode_request_payload,
    get_schemas_payload,
)
from ..runtime import manager
from ..schemas import DecodeRequest, EncodeRequest, StreamDecodeRequest

router = APIRouter()


@router.post("/api/encode")
async def encode_json_to_protobuf(request: EncodeRequest):
    try:
        logger.info(f"收到编码请求，消息类型: {request.message_type}")
        result = await encode_request_payload(request, manager.log_packet)
        logger.info(f"✅ JSON编码为protobuf成功: {result['size']} 字节")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ JSON编码失败: {e}")
        raise HTTPException(500, f"编码失败: {str(e)}")


@router.post("/api/decode")
async def decode_protobuf_to_json(request: DecodeRequest):
    try:
        logger.info(f"收到解码请求，消息类型: {request.message_type}")
        result = await decode_request_payload(request, manager.log_packet)
        logger.info(f"✅ Protobuf解码为JSON成功: {result['size']} 字节")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Protobuf解码失败: {e}")
        raise HTTPException(500, f"解码失败: {e}")


@router.post("/api/stream-decode")
async def decode_stream_protobuf(request: StreamDecodeRequest):
    try:
        logger.info(f"收到流式解码请求，数据块数量: {len(request.protobuf_chunks)}")
        result = await decode_stream_payload(request, manager.log_packet)
        logger.info(
            f"✅ 流式protobuf解码完成: {result['total_chunks']} 块，总大小 {result['total_size']} 字节"
        )
        return result
    except Exception as e:
        logger.error(f"❌ 流式protobuf解码失败: {e}")
        raise HTTPException(500, f"流式解码失败: {e}")


@router.get("/api/schemas")
async def get_protobuf_schemas():
    try:
        result = get_schemas_payload()
        logger.info(f"✅ 返回 {result['total_count']} 个protobuf schema")
        return result
    except Exception as e:
        logger.error(f"❌ 获取protobuf schemas失败: {e}")
        raise HTTPException(500, f"获取schemas失败: {e}")


@router.get("/api/packets/history")
async def get_packet_history(limit: int = 50):
    try:
        history = manager.packet_history[-limit:] if len(manager.packet_history) > limit else manager.packet_history
        return {"packets": history, "total_count": len(manager.packet_history), "returned_count": len(history)}
    except Exception as e:
        logger.error(f"❌ 获取数据包历史失败: {e}")
        raise HTTPException(500, f"获取历史记录失败: {e}")

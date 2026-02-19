#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from typing import Dict

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from warp2api.infrastructure.settings.settings import CLIENT_VERSION, OS_VERSION
from warp2api.observability.logging import logger
from ..runtime import manager
from ..schemas import EncodeRequest
from warp2api.application.services.warp_request_service import execute_warp_packet

router = APIRouter()


async def _execute_and_format_warp_response(
    request: EncodeRequest,
    log_prefix: str,
    include_events: bool,
) -> Dict:
    actual_data = request.get_data()
    if not actual_data:
        raise HTTPException(400, "数据包不能为空")

    exec_ctx = await execute_warp_packet(
        actual_data=actual_data,
        message_type=request.message_type,
        timeout_seconds=90,
        client_version=CLIENT_VERSION,
        os_version=OS_VERSION,
    )
    query = exec_ctx["query"]
    model_tag = exec_ctx["model_tag"]
    protobuf_bytes = exec_ctx["protobuf_bytes"]
    result_raw = exec_ctx["result_raw"]
    response_text = result_raw.get("text", "")
    conversation_id = result_raw.get("conversation_id")
    task_id = result_raw.get("task_id")
    parsed_events = result_raw.get("parsed_events", []) or []

    await manager.log_packet(
        f"warp_request{log_prefix}",
        {"query": query, "model_tag": model_tag},
        len(query.encode("utf-8")),
    )
    response_data = {
        "response": response_text,
        "conversation_id": conversation_id,
        "task_id": task_id,
    }
    if include_events:
        response_data["parsed_events"] = parsed_events
    await manager.log_packet(f"warp_response{log_prefix}", response_data, len(str(response_data)))

    result = {
        "response": response_text,
        "conversation_id": conversation_id,
        "task_id": task_id,
        "request_size": len(protobuf_bytes),
        "response_size": len(response_text),
        "message_type": request.message_type,
        "model_tag": model_tag,
        "status_code": result_raw.get("status_code"),
        "attempts": result_raw.get("attempts", []),
    }
    if include_events:
        result["parsed_events"] = parsed_events
        result["events_count"] = len(parsed_events)
        event_type_counts: Dict[str, int] = {}
        for event in parsed_events:
            event_type = event.get("event_type", "UNKNOWN")
            event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
        result["events_summary"] = event_type_counts
    return result


@router.post("/api/warp/send")
async def send_to_warp_api(
    request: EncodeRequest,
    show_all_events: bool = Query(True, description="Show detailed SSE event breakdown"),
):
    _ = show_all_events
    try:
        logger.info(f"收到Warp API发送请求，消息类型: {request.message_type}")
        result = await _execute_and_format_warp_response(
            request=request,
            log_prefix="",
            include_events=False,
        )
        logger.info(f"✅ Warp API调用成功，响应长度: {result['response_size']} 字符")
        return result
    except Exception as e:
        import traceback

        actual_data = request.get_data()
        error_details = {
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc(),
            "request_info": {
                "message_type": request.message_type,
                "json_size": len(str(actual_data)),
                "has_tools": "mcp_context" in actual_data,
                "has_history": "task_context" in actual_data,
            },
        }
        logger.error(f"❌ Warp API调用失败: {e}")
        logger.error(f"错误详情: {error_details}")
        try:
            await manager.log_packet("warp_error", error_details, 0)
        except Exception as log_error:
            logger.warning(f"记录错误失败: {log_error}")
        raise HTTPException(500, detail=error_details)


@router.post("/api/warp/send_stream")
async def send_to_warp_api_parsed(request: EncodeRequest):
    try:
        logger.info(f"收到Warp API解析发送请求，消息类型: {request.message_type}")
        result = await _execute_and_format_warp_response(
            request=request,
            log_prefix="_parsed",
            include_events=True,
        )
        logger.info(
            f"✅ Warp API解析调用成功，响应长度: {result['response_size']} 字符，事件数量: {result['events_count']}"
        )
        return result
    except Exception as e:
        import traceback

        actual_data = request.get_data()
        error_details = {
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc(),
            "request_info": {
                "message_type": request.message_type,
                "json_size": len(str(actual_data)),
                "has_tools": "mcp_context" in (actual_data or {}),
                "has_history": "task_context" in (actual_data or {}),
            },
        }
        logger.error(f"❌ Warp API解析调用失败: {e}")
        logger.error(f"错误详情: {error_details}")
        try:
            await manager.log_packet("warp_error_parsed", error_details, 0)
        except Exception as log_error:
            logger.warning(f"记录错误失败: {log_error}")
        raise HTTPException(500, detail=error_details)


@router.post("/api/warp/send_stream_sse")
async def send_to_warp_api_stream_sse(request: EncodeRequest):
    try:
        actual_data = request.get_data()
        if not actual_data:
            raise HTTPException(400, "数据包不能为空")
        exec_ctx = await execute_warp_packet(
            actual_data=actual_data,
            message_type=request.message_type,
            timeout_seconds=90,
            client_version=CLIENT_VERSION,
            os_version=OS_VERSION,
        )
        result_raw_first = exec_ctx["result_raw"]

        async def _agen():
            result_raw = result_raw_first
            if not result_raw.get("ok"):
                err_obj = {"error": f"HTTP {result_raw.get('status_code')}"}
                yield f"data: {json.dumps(err_obj, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return
            parsed_events = result_raw.get("parsed_events", []) or []
            for idx, ev in enumerate(parsed_events, start=1):
                out = {
                    "event_number": idx,
                    "event_type": ev.get("event_type", "UNKNOWN_EVENT"),
                    "parsed_data": ev.get("parsed_data", {}),
                }
                yield f"data: {json.dumps(out, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            _agen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback

        error_details = {"error": str(e), "error_type": type(e).__name__, "traceback": traceback.format_exc()}
        logger.error(f"Warp SSE转发端点错误: {e}")
        raise HTTPException(500, detail=error_details)

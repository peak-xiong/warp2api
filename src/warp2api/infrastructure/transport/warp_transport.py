from __future__ import annotations

import base64
import binascii
import http.client
import ssl
import time
from typing import Any, Dict, List, Optional

from warp2api.infrastructure.settings.settings import CLIENT_VERSION, OS_CATEGORY, OS_NAME, OS_VERSION
from warp2api.observability.logging import logger
from warp2api.infrastructure.protobuf.utils import protobuf_to_dict

from .event_parser import detect_event_type, extract_text_from_event, extract_tool_calls_from_event


def _decode_payload_to_bytes(payload: str) -> Optional[bytes]:
    s = (payload or "").strip()
    if not s:
        return None

    try:
        pad = "=" * ((4 - (len(s) % 4)) % 4)
        return base64.urlsafe_b64decode(s + pad)
    except (binascii.Error, ValueError):
        try:
            pad = "=" * ((4 - (len(s) % 4)) % 4)
            return base64.b64decode(s + pad)
        except Exception:
            return None


def send_warp_protobuf_request(
    body: bytes,
    jwt: str,
    timeout_seconds: int = 90,
    client_version: Optional[str] = None,
    os_version: Optional[str] = None,
    host: str = "app.warp.dev",
    path: str = "/ai/multi-agent",
) -> Dict[str, Any]:
    headers = {
        "x-warp-client-id": "warp-app",
        "x-warp-client-version": client_version or CLIENT_VERSION,
        "x-warp-os-category": OS_CATEGORY,
        "x-warp-os-name": OS_NAME,
        "x-warp-os-version": os_version or OS_VERSION,
        "content-type": "application/x-protobuf",
        "accept": "text/event-stream",
        "accept-encoding": "identity",
        "authorization": f"Bearer {jwt}",
        "content-length": str(len(body)),
    }

    conn = http.client.HTTPSConnection(
        host,
        443,
        timeout=timeout_seconds,
        context=ssl.create_default_context(),
    )
    conn.request("POST", path, body=body, headers=headers)
    resp = conn.getresponse()

    if resp.status != 200:
        err = resp.read(4096).decode("utf-8", errors="ignore")
        return {
            "ok": False,
            "status_code": resp.status,
            "error": err,
            "text": "",
            "conversation_id": None,
            "task_id": None,
            "events_count": 0,
            "parsed_events": [],
            "tool_calls": [],
        }

    text_parts: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    parsed_events: List[Dict[str, Any]] = []
    conversation_id = None
    task_id = None
    events_count = 0
    sse_data_buf: List[str] = []
    started = time.monotonic()

    while True:
        if time.monotonic() - started > timeout_seconds:
            logger.warning("transport read timeout reached: %ss", timeout_seconds)
            break
        try:
            raw_line = resp.fp.readline()
        except TimeoutError:
            logger.warning("transport socket read timed out")
            break
        except OSError as exc:
            logger.warning("transport socket read failed: %s", exc)
            break

        if not raw_line:
            break

        line = raw_line.decode("utf-8", errors="ignore").strip()

        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload:
                sse_data_buf.append(payload)
            continue

        if line == "" and sse_data_buf:
            payload_joined = "".join(sse_data_buf)
            sse_data_buf = []
            raw_bytes = _decode_payload_to_bytes(payload_joined)
            if raw_bytes is None:
                continue

            try:
                event_data = protobuf_to_dict(raw_bytes, "warp.multi_agent.v1.ResponseEvent")
            except Exception:
                continue

            events_count += 1
            event_type = detect_event_type(event_data)
            parsed_events.append(
                {
                    "event_number": events_count,
                    "event_type": event_type,
                    "parsed_data": event_data,
                }
            )

            if "finished" in event_data:
                break

            init_data = event_data.get("init")
            if isinstance(init_data, dict):
                conversation_id = init_data.get("conversation_id", conversation_id)
                task_id = init_data.get("task_id", task_id)

            text = extract_text_from_event(event_data)
            if text:
                text_parts.append(text)

            tcalls = extract_tool_calls_from_event(event_data)
            if tcalls:
                tool_calls.extend(tcalls)

    return {
        "ok": True,
        "status_code": 200,
        "error": "",
        "text": "".join(text_parts),
        "conversation_id": conversation_id,
        "task_id": task_id,
        "events_count": events_count,
        "parsed_events": parsed_events,
        "tool_calls": tool_calls,
    }

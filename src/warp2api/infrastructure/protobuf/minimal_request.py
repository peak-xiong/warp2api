from __future__ import annotations

import time
from typing import Dict, Optional

from warp2api.infrastructure.settings.settings import CLIENT_VERSION, OS_VERSION
from warp2api.observability.logging import logger

from warp2api.infrastructure.transport.warp_transport import send_warp_protobuf_request


def _enc_varint(v: int) -> bytes:
    out = bytearray()
    x = int(v)
    while x >= 0x80:
        out.append((x & 0x7F) | 0x80)
        x >>= 7
    out.append(x)
    return bytes(out)


def _enc_field(field_no: int, wire_type: int, payload: bytes) -> bytes:
    return _enc_varint((field_no << 3) | wire_type) + payload


def _enc_string(field_no: int, s: str) -> bytes:
    b = s.encode("utf-8")
    return _enc_field(field_no, 2, _enc_varint(len(b)) + b)


def _enc_bytes(field_no: int, b: bytes) -> bytes:
    return _enc_field(field_no, 2, _enc_varint(len(b)) + b)


def _enc_message(field_no: int, payload: bytes) -> bytes:
    return _enc_field(field_no, 2, _enc_varint(len(payload)) + payload)


def _enc_varint_field(field_no: int, v: int) -> bytes:
    return _enc_field(field_no, 0, _enc_varint(v))


def _enc_fixed32(field_no: int, v: int) -> bytes:
    return _enc_field(field_no, 5, int(v).to_bytes(4, "little", signed=False))


def build_minimal_warp_request(
    query: str,
    working_dir: str = "/tmp",
    home_dir: str = "/tmp",
    model_tag: str = "auto",
    coding_tag: str = "cli-agent-auto",
) -> bytes:
    now_ms = int(time.time() * 1000)
    ts = now_ms // 1000
    nanos = (now_ms % 1000) * 1_000_000

    field1 = _enc_string(1, "")

    path_info = _enc_string(1, working_dir) + _enc_string(2, home_dir)
    os_info = _enc_message(1, _enc_fixed32(9, 0x534F6361))
    shell_info = _enc_string(1, "zsh") + _enc_string(2, "5.9")
    ts_info = _enc_varint_field(1, ts) + _enc_varint_field(2, nanos)
    field2_1 = _enc_message(1, path_info) + _enc_message(2, os_info) + _enc_message(3, shell_info) + _enc_message(4, ts_info)
    query_content = _enc_string(1, query) + _enc_string(3, "") + _enc_varint_field(4, 1)
    field2_6 = _enc_message(1, _enc_message(1, query_content))
    field2 = _enc_message(1, field2_1) + _enc_message(6, field2_6)

    model_cfg = _enc_string(1, model_tag) + _enc_string(4, coding_tag)
    caps = bytes([0x06, 0x07, 0x0C, 0x08, 0x09, 0x0F, 0x0E, 0x00, 0x0B, 0x10, 0x0A, 0x14, 0x11, 0x13, 0x12, 0x02, 0x03, 0x01, 0x0D])
    caps2 = bytes([0x0A, 0x14, 0x06, 0x07, 0x0C, 0x02, 0x01])
    field3 = (
        _enc_message(1, model_cfg)
        + _enc_varint_field(2, 1)
        + _enc_varint_field(3, 1)
        + _enc_varint_field(4, 1)
        + _enc_varint_field(6, 1)
        + _enc_varint_field(7, 1)
        + _enc_varint_field(8, 1)
        + _enc_bytes(9, caps)
        + _enc_varint_field(10, 1)
        + _enc_varint_field(11, 1)
        + _enc_varint_field(12, 1)
        + _enc_varint_field(13, 1)
        + _enc_varint_field(14, 1)
        + _enc_varint_field(15, 1)
        + _enc_varint_field(16, 1)
        + _enc_varint_field(17, 1)
        + _enc_varint_field(21, 1)
        + _enc_bytes(22, caps2)
        + _enc_varint_field(23, 1)
    )

    entry = _enc_string(1, "entrypoint") + _enc_message(2, _enc_message(3, _enc_string(1, "USER_INITIATED")))
    auto_resume = _enc_string(1, "is_auto_resume_after_error") + _enc_message(2, _enc_varint_field(4, 0))
    auto_detect = _enc_string(1, "is_autodetected_user_query") + _enc_message(2, _enc_varint_field(4, 1))
    field4 = _enc_message(2, entry) + _enc_message(2, auto_resume) + _enc_message(2, auto_detect)

    return field1 + _enc_message(2, field2) + _enc_message(3, field3) + _enc_message(4, field4)


def send_minimal_warp_query(
    query: str,
    jwt: str,
    timeout_seconds: int = 90,
    model_tag: str = "auto",
    client_version: Optional[str] = None,
    os_version: Optional[str] = None,
) -> Dict[str, object]:
    body = build_minimal_warp_request(query=query, model_tag=model_tag)
    result = send_warp_protobuf_request(
        body=body,
        jwt=jwt,
        timeout_seconds=timeout_seconds,
        client_version=client_version or CLIENT_VERSION,
        os_version=os_version or OS_VERSION,
    )
    result["model_tag"] = model_tag
    logger.info(
        "minimal proxy finished: status=%s events=%s text_len=%s",
        result.get("status_code"),
        result.get("events_count"),
        len(result.get("text") or ""),
    )
    return result

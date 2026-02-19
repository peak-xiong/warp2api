from __future__ import annotations

from typing import Any

from warp2api.infrastructure.protobuf.utils import dict_to_protobuf_bytes
from warp2api.infrastructure.protobuf.server_message_data import encode_server_message_data


def encode_smd_inplace(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if key in ("server_message_data", "serverMessageData") and isinstance(value, dict):
                try:
                    out[key] = encode_server_message_data(
                        uuid=value.get("uuid"),
                        seconds=value.get("seconds"),
                        nanos=value.get("nanos"),
                    )
                except Exception:
                    out[key] = value
            else:
                out[key] = encode_smd_inplace(value)
        return out

    if isinstance(obj, list):
        return [encode_smd_inplace(item) for item in obj]

    return obj


def encode_request_packet(data: Any, message_type: str) -> bytes:
    return dict_to_protobuf_bytes(encode_smd_inplace(data), message_type)

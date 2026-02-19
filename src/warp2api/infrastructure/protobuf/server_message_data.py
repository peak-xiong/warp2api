#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helpers for encoding/decoding server_message_data values.

These are Base64URL-encoded proto3 messages with shape:
  - field 1: string UUID (36 chars)
  - field 3: google.protobuf.Timestamp (1=seconds, 2=nanos)

Supports UUID_ONLY, TIMESTAMP_ONLY, and UUID_AND_TIMESTAMP.
"""
from typing import Dict, Optional, Tuple
import base64
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None  # type: ignore


def _b64url_decode_padded(s: str) -> bytes:
    t = s.replace("-", "+").replace("_", "/")
    pad = (-len(t)) % 4
    if pad:
        t += "=" * pad
    return base64.b64decode(t)


def _b64url_encode_nopad(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _read_varint(buf: bytes, i: int) -> Tuple[int, int]:
    shift = 0
    val = 0
    while i < len(buf):
        b = buf[i]
        i += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            return val, i
        shift += 7
        if shift > 63:
            break
    raise ValueError("invalid varint")


def _write_varint(v: int) -> bytes:
    out = bytearray()
    vv = int(v)
    while True:
        to_write = vv & 0x7F
        vv >>= 7
        if vv:
            out.append(to_write | 0x80)
        else:
            out.append(to_write)
            break
    return bytes(out)


def _make_key(field_no: int, wire_type: int) -> bytes:
    return _write_varint((field_no << 3) | wire_type)


def _decode_timestamp(buf: bytes) -> Tuple[Optional[int], Optional[int]]:
    i = 0
    seconds: Optional[int] = None
    nanos: Optional[int] = None
    while i < len(buf):
        key, i = _read_varint(buf, i)
        field_no = key >> 3
        wt = key & 0x07
        if wt == 0:
            val, i = _read_varint(buf, i)
            if field_no == 1:
                seconds = int(val)
            elif field_no == 2:
                nanos = int(val)
        elif wt == 2:
            ln, i2 = _read_varint(buf, i)
            i = i2 + ln
        elif wt == 1:
            i += 8
        elif wt == 5:
            i += 4
        else:
            break
    return seconds, nanos


def _encode_timestamp(seconds: Optional[int], nanos: Optional[int]) -> bytes:
    parts = bytearray()
    if seconds is not None:
        parts += _make_key(1, 0)
        parts += _write_varint(int(seconds))
    if nanos is not None:
        parts += _make_key(2, 0)
        parts += _write_varint(int(nanos))
    return bytes(parts)


def decode_server_message_data(b64url: str) -> Dict:
    try:
        raw = _b64url_decode_padded(b64url)
    except Exception as e:
        return {"error": f"base64url decode failed: {e}"}

    i = 0
    uuid: Optional[str] = None
    seconds: Optional[int] = None
    nanos: Optional[int] = None

    while i < len(raw):
        key, i = _read_varint(raw, i)
        field_no = key >> 3
        wt = key & 0x07
        if wt == 2:
            ln, i2 = _read_varint(raw, i)
            i = i2
            data = raw[i:i+ln]
            i += ln
            if field_no == 1:
                try:
                    uuid = data.decode("utf-8")
                except Exception:
                    uuid = None
            elif field_no == 3:
                s, n = _decode_timestamp(data)
                if s is not None:
                    seconds = s
                if n is not None:
                    nanos = n
        elif wt == 0:
            _, i = _read_varint(raw, i)
        elif wt == 1:
            i += 8
        elif wt == 5:
            i += 4
        else:
            break

    iso_utc: Optional[str] = None
    iso_ny: Optional[str] = None
    if seconds is not None:
        micros = int((nanos or 0) / 1000)
        dt = datetime.fromtimestamp(int(seconds), tz=timezone.utc).replace(microsecond=micros)
        iso_utc = dt.isoformat().replace("+00:00", "Z")
        if ZoneInfo is not None:
            try:
                iso_ny = dt.astimezone(ZoneInfo("America/New_York")).isoformat()
            except Exception:
                iso_ny = None

    if uuid and (seconds is not None or nanos is not None):
        t = "UUID_AND_TIMESTAMP"
    elif uuid:
        t = "UUID_ONLY"
    elif seconds is not None or nanos is not None:
        t = "TIMESTAMP_ONLY"
    else:
        t = "UNKNOWN"

    return {
        "uuid": uuid,
        "seconds": seconds,
        "nanos": nanos,
        "iso_utc": iso_utc,
        "iso_ny": iso_ny,
        "type": t,
    }


def encode_server_message_data(uuid: Optional[str] = None,
                               seconds: Optional[int] = None,
                               nanos: Optional[int] = None) -> str:
    parts = bytearray()
    if uuid:
        b = uuid.encode("utf-8")
        parts += _make_key(1, 2)
        parts += _write_varint(len(b))
        parts += b
    if seconds is not None or nanos is not None:
        ts = _encode_timestamp(seconds, nanos)
        parts += _make_key(3, 2)
        parts += _write_varint(len(ts))
        parts += ts
    return _b64url_encode_nopad(bytes(parts)) 
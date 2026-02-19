#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protobuf runtime for Warp API

Handles protobuf compilation, message creation, and request building.
"""
import os
import re
import json
import time
import uuid
import pathlib
import tempfile
import threading
from typing import Any, Dict, List, Optional, Tuple

from google.protobuf import descriptor_pool, descriptor_pb2
from google.protobuf.descriptor import FieldDescriptor as FD
from google.protobuf.message_factory import GetMessageClass
from google.protobuf import struct_pb2

from warp2api.infrastructure.settings.settings import (
    CLIENT_VERSION,
    OS_CATEGORY,
    OS_NAME,
    OS_VERSION,
    PATH_HINT_BONUS,
    PROTO_DIR,
    TEXT_FIELD_NAMES,
)
from warp2api.observability.logging import logger, log

# Global protobuf state
_pool: Optional[descriptor_pool.DescriptorPool] = None
ALL_MSGS: List[str] = []
_RUNTIME_LOCK = threading.RLock()
_MSG_CLASS_CACHE: Dict[str, Any] = {}


def _find_proto_files(root: pathlib.Path) -> List[str]:
    """Find necessary .proto files in the given directory, excluding problematic test files"""
    if not root.exists():
        return []
    
    essential_files = [
        "request.proto",
        "response.proto", 
        "task.proto",
        "attachment.proto",
        "file_content.proto",
        "input_context.proto",
        "citations.proto"
    ]
    
    found_files = []
    for file_name in essential_files:
        file_path = root / file_name
        if file_path.exists():
            found_files.append(str(file_path))
            logger.debug(f"Found essential proto file: {file_name}")
    
    if not found_files:
        logger.warning("Essential proto files not found, scanning all files...")
        exclude_patterns = [
            "unittest", "test", "sample_messages", "java_features", 
            "legacy_features", "descriptor_test"
        ]
        
        for proto_file in root.rglob("*.proto"):
            file_name = proto_file.name.lower()
            if not any(pattern in file_name for pattern in exclude_patterns):
                found_files.append(str(proto_file))
    
    logger.info(f"Selected {len(found_files)} proto files for compilation")
    return found_files


def _build_descset(proto_files: List[str], includes: List[str]) -> bytes:
    from grpc_tools import protoc
    try:
        from importlib.resources import files as pkg_files
        tool_inc = str(pkg_files("grpc_tools").joinpath("_proto"))
    except Exception:
        tool_inc = None

    outdir = pathlib.Path(tempfile.mkdtemp(prefix="desc_"))
    out = outdir / "bundle.pb"
    args = ["protoc", f"--descriptor_set_out={out}", "--include_imports"]
    for inc in includes:
        args.append(f"-I{inc}")
    if tool_inc:
        args.append(f"-I{tool_inc}")
    args.extend(proto_files)
    rc = protoc.main(args)
    if rc != 0 or not out.exists():
        raise RuntimeError("protoc failed to produce descriptor set")
    return out.read_bytes()


def _load_pool_from_descset(descset: bytes):
    global _pool, ALL_MSGS
    fds = descriptor_pb2.FileDescriptorSet()
    fds.ParseFromString(descset)
    pool = descriptor_pool.DescriptorPool()
    for fd in fds.file:
        pool.Add(fd)
    names: List[str] = []
    for fd in fds.file:
        pkg = fd.package
        def walk(m, prefix):
            full = f"{prefix}.{m.name}" if prefix else m.name
            names.append(full)
            for nested in m.nested_type:
                walk(nested, full)
        for m in fd.message_type:
            walk(m, pkg)
    _pool, ALL_MSGS = pool, names
    _MSG_CLASS_CACHE.clear()
    log(f"proto loaded: {len(ALL_MSGS)} message type(s)")


def ensure_proto_runtime():
    if _pool is not None:
        return
    with _RUNTIME_LOCK:
        if _pool is not None:
            return
        files = _find_proto_files(PROTO_DIR)
        if not files:
            raise RuntimeError(f"No .proto found under {PROTO_DIR}")
        desc = _build_descset(files, [str(PROTO_DIR)])
        _load_pool_from_descset(desc)


def msg_cls(full: str):
    ensure_proto_runtime()
    cls = _MSG_CLASS_CACHE.get(full)
    if cls is not None:
        return cls
    desc = _pool.FindMessageTypeByName(full)  # type: ignore
    cls = GetMessageClass(desc)
    _MSG_CLASS_CACHE[full] = cls
    return cls


def _list_text_paths(desc, max_depth=6):
    out: List[Tuple[List[FD], int]] = []
    def walk(cur_desc, cur_path: List[FD], depth: int):
        if depth > max_depth:
            return
        for f in cur_desc.fields:
            base = 0
            if f.name.lower() in TEXT_FIELD_NAMES: base += 10
            for hint in PATH_HINT_BONUS:
                if hint in f.name.lower(): base += 2
            if f.type == FD.TYPE_STRING:
                out.append((cur_path + [f], base + depth))
            elif f.type == FD.TYPE_MESSAGE:
                walk(f.message_type, cur_path + [f], depth + 1)
    walk(desc, [], 0)
    return out


def _pick_best_request_schema() -> Tuple[str, List[FD]]:
    ensure_proto_runtime()
    try:
        request_type = "warp.multi_agent.v1.Request"
        d = _pool.FindMessageTypeByName(request_type)  # type: ignore
        path_names = ["input", "user_inputs", "inputs", "user_query", "query"]
        path_fields = []
        current_desc = d
        
        for field_name in path_names:
            field = current_desc.fields_by_name.get(field_name)
            if not field:
                raise RuntimeError(f"Field '{field_name}' not found")
            path_fields.append(field)
            if field.type == FD.TYPE_MESSAGE:
                current_desc = field.message_type
        
        log("using modern request format:", request_type, " :: ", ".".join(path_names))
        return request_type, path_fields
        
    except Exception as e:
        log(f"Failed to use modern format, falling back to auto-detection: {e}")
        best: Optional[Tuple[str, List[FD], int]] = None
        for full in ALL_MSGS:
            try:
                d = _pool.FindMessageTypeByName(full)  # type: ignore
            except Exception:
                continue
            name_bias = 0
            lname = full.lower()
            for kw, w in (("request", 8), ("multi_agent", 6), ("multiagent", 6),
                          ("chat", 5), ("client", 2), ("message", 1), ("input", 1)):
                if kw in lname: name_bias += w
            for path, score in _list_text_paths(d):
                total = score + name_bias + max(0, 6 - len(path))
                if best is None or total > best[2]:
                    best = (full, path, total)
        if not best:
            raise RuntimeError("Could not auto-detect request root & text field from proto/")
        full, path, _ = best
        log("auto-detected request:", full, " :: ", ".".join(f.name for f in path))
        return full, path


_REQ_CACHE: Optional[Tuple[str, List[FD]]] = None

def get_request_schema() -> Tuple[str, List[FD]]:
    global _REQ_CACHE
    if _REQ_CACHE is None:
        _REQ_CACHE = _pick_best_request_schema()
    return _REQ_CACHE


def _set_text_at_path(msg, path_fields: List[FD], text: str):
    cur = msg
    for i, f in enumerate(path_fields):
        last = (i == len(path_fields) - 1)
        try:
            is_repeated = f.is_repeated
        except AttributeError:
            is_repeated = (f.label == FD.LABEL_REPEATED)
        
        if is_repeated:
            rep = getattr(cur, f.name)
            if f.type == FD.TYPE_MESSAGE:
                cur = rep.add()
            elif f.type == FD.TYPE_STRING:
                if not last: raise TypeError(f"path continues after repeated string field '{f.name}'")
                rep.append(text); return
            else:
                raise TypeError(f"unsupported repeated scalar at '{f.name}'")
        else:
            if f.type == FD.TYPE_MESSAGE:
                cur = getattr(cur, f.name)
                if last:
                    raise TypeError(f"last field '{f.name}' is a message, not string")
            elif f.type == FD.TYPE_STRING:
                if not last: raise TypeError(f"path continues after string field '{f.name}'")
                setattr(cur, f.name, text); return
            else:
                raise TypeError(f"unsupported scalar at '{f.name}'")
    raise RuntimeError("failed to set text")


def build_request_bytes(user_text: str, model: str = "auto") -> bytes:
    from warp2api.domain.models.model_catalog import get_model_config

    full, path = get_request_schema()
    Cls = msg_cls(full)
    msg = Cls()
    _set_text_at_path(msg, path, user_text)

    if hasattr(msg, 'settings'):
        settings = msg.settings
        if hasattr(settings, 'model_config'):
            model_config_dict = get_model_config(model)
            model_config = settings.model_config
            model_config.base = model_config_dict["base"]
            model_config.planning = model_config_dict["planning"]
            model_config.coding = model_config_dict["coding"]
            logger.debug(f"Set model config: base={model_config.base}, planning={model_config.planning}, coding={model_config.coding}")

        settings.rules_enabled = False
        settings.web_context_retrieval_enabled = False
        settings.supports_parallel_tool_calls = False
        settings.planning_enabled = False
        settings.supports_create_files = False
        settings.supports_long_running_commands = False
        settings.supports_todos_ui = False
        settings.supports_linked_code_blocks = False

        settings.use_anthropic_text_editor_tools = False
        settings.warp_drive_context_enabled = False
        settings.should_preserve_file_content_in_history = True

        try:
            tool_types = []
            settings.supported_tools[:] = tool_types
            logger.debug(f"Set supported_tools (legacy): {tool_types}")
        except Exception as e:
            logger.debug(f"Could not set supported_tools: {e}")

        logger.debug("Applied all valid Settings fields based on proto definition")

    if hasattr(msg, 'metadata'):
        metadata = msg.metadata
        metadata.conversation_id = f"rest-api-{uuid.uuid4().hex[:8]}"

    rootd = msg.DESCRIPTOR
    for fn, val in (
        ("client_version", CLIENT_VERSION),
        ("version", CLIENT_VERSION),
        ("os_name", OS_NAME),
        ("os_category", OS_CATEGORY),
        ("os_version", OS_VERSION),
    ):
        f = rootd.fields_by_name.get(fn)
        if f and f.type == FD.TYPE_STRING and f.label == FD.LABEL_OPTIONAL:
            setattr(msg, fn, val)

    return msg.SerializeToString() 

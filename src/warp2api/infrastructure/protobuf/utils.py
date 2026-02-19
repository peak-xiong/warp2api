#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protobuf utility functions

Shared functions for protobuf encoding/decoding across the application.
"""
from typing import Any, Dict
from fastapi import HTTPException
from warp2api.observability.logging import logger
from warp2api.infrastructure.protobuf.runtime import ensure_proto_runtime, msg_cls
from google.protobuf.json_format import MessageToDict
from google.protobuf import struct_pb2
from google.protobuf.descriptor import FieldDescriptor as _FD
from warp2api.infrastructure.protobuf.server_message_data import (
    decode_server_message_data,
    encode_server_message_data,
)





def protobuf_to_dict(protobuf_bytes: bytes, message_type: str) -> Dict:
    """将protobuf字节转换为字典"""
    ensure_proto_runtime()
    
    try:
        MessageClass = msg_cls(message_type)
        message = MessageClass()
        message.ParseFromString(protobuf_bytes)
        
        data = MessageToDict(message, preserving_proto_field_name=True)
        
        # 在转换阶段自动解析 server_message_data（Base64URL -> 结构化对象）
        data = _decode_smd_inplace(data)
        return data
    
    except Exception as e:
        logger.error(f"Protobuf解码失败: {e}")
        raise HTTPException(500, f"Protobuf解码失败: {e}")





def dict_to_protobuf_bytes(data_dict: Dict, message_type: str = "warp.multi_agent.v1.Request") -> bytes:
    """字典转protobuf字节的包装函数"""
    ensure_proto_runtime()
    
    try:
        MessageClass = msg_cls(message_type)
        message = MessageClass()
        
        # 在转换阶段自动处理 server_message_data（对象 -> Base64URL 字符串）
        safe_dict = _encode_smd_inplace(data_dict)
        
        _populate_protobuf_from_dict(message, safe_dict, path="$")
        
        return message.SerializeToString()
    
    except Exception as e:
        logger.error(f"Protobuf编码失败: {e}")
        raise HTTPException(500, f"Protobuf编码失败: {e}")




def _fill_google_value_dynamic(value_msg: Any, py_value: Any) -> None:
    """在动态 google.protobuf.Value 消息上填充 Python 值（不创建 struct_pb2.Value 实例）。"""
    try:
        if py_value is None:
            setattr(value_msg, "null_value", 0)
            return
        if isinstance(py_value, bool):
            setattr(value_msg, "bool_value", bool(py_value))
            return
        if isinstance(py_value, (int, float)):
            setattr(value_msg, "number_value", float(py_value))
            return
        if isinstance(py_value, str):
            setattr(value_msg, "string_value", py_value)
            return
        if isinstance(py_value, dict):
            struct_value = getattr(value_msg, "struct_value")
            _fill_google_struct_dynamic(struct_value, py_value)
            return
        if isinstance(py_value, list):
            list_value = getattr(value_msg, "list_value")
            values_rep = getattr(list_value, "values")
            for item in py_value:
                sub = values_rep.add()
                _fill_google_value_dynamic(sub, item)
            return
        setattr(value_msg, "string_value", str(py_value))
    except Exception as e:
        logger.warning(f"填充 google.protobuf.Value 失败: {e}")




def _fill_google_struct_dynamic(struct_msg: Any, py_dict: Dict[str, Any]) -> None:
    """在动态 google.protobuf.Struct 上填充 Python dict（不使用 struct_pb2.Struct.update）。"""
    try:
        fields_map = getattr(struct_msg, "fields")
        for k, v in py_dict.items():
            sub_val = fields_map[k]
            _fill_google_value_dynamic(sub_val, v)
    except Exception as e:
        logger.warning(f"填充 google.protobuf.Struct 失败: {e}")




def _python_to_struct_value(py_value: Any) -> struct_pb2.Value:
    v = struct_pb2.Value()
    if py_value is None:
        v.null_value = struct_pb2.NULL_VALUE
    elif isinstance(py_value, bool):
        v.bool_value = bool(py_value)
    elif isinstance(py_value, (int, float)):
        v.number_value = float(py_value)
    elif isinstance(py_value, str):
        v.string_value = py_value
    elif isinstance(py_value, dict):
        s = struct_pb2.Struct()
        s.update(py_value)
        v.struct_value.CopyFrom(s)
    elif isinstance(py_value, list):
        lv = struct_pb2.ListValue()
        for item in py_value:
            lv.values.append(_python_to_struct_value(item))
        v.list_value.CopyFrom(lv)
    else:
        v.string_value = str(py_value)
    return v




def _populate_protobuf_from_dict(proto_msg, data_dict: Dict, path: str = "$"):
    descriptor = getattr(proto_msg, "DESCRIPTOR", None)
    fields_by_name = descriptor.fields_by_name if descriptor is not None else {}

    for key, value in data_dict.items():
        current_path = f"{path}.{key}"
        fd = fields_by_name.get(key)
        if fd is None:
            logger.debug(f"忽略未知字段: {current_path}")
            continue

        field = getattr(proto_msg, key)

        try:
            if (
                fd is not None
                and fd.type == _FD.TYPE_MESSAGE
                and fd.message_type is not None
                and fd.message_type.full_name == "google.protobuf.Struct"
                and isinstance(value, dict)
            ):
                _fill_google_struct_dynamic(field, value)
                continue
        except Exception as e:
            logger.warning(f"处理 Struct 字段 {current_path} 失败: {e}")

        if isinstance(field, struct_pb2.Struct) and isinstance(value, dict):
            try:
                field.update(value)
            except Exception as e:
                logger.warning(f"填充Struct失败: {current_path}: {e}")
            continue

        try:
            if (
                fd is not None
                and fd.type == _FD.TYPE_MESSAGE
                and fd.message_type is not None
                and fd.message_type.GetOptions().map_entry
                and isinstance(value, dict)
            ):
                value_desc = fd.message_type.fields_by_name.get("value")
                for mk, mv in value.items():
                    try:
                        if value_desc is not None and value_desc.type == _FD.TYPE_MESSAGE:
                            if value_desc.message_type is not None and value_desc.message_type.full_name == "google.protobuf.Value":
                                _fill_google_value_dynamic(field[mk], mv)
                            else:
                                sub_msg = field[mk]
                                if isinstance(mv, dict):
                                    _populate_protobuf_from_dict(sub_msg, mv, path=f"{current_path}.{mk}")
                                else:
                                    try:
                                        logger.warning(f"map值类型不匹配，期望message: {current_path}.{mk}")
                                    except Exception:
                                        pass
                        else:
                            field[mk] = mv
                    except Exception as me:
                        logger.warning(f"设置 map 字段 {current_path}.{mk} 失败: {me}")
                continue
        except Exception as e:
            logger.warning(f"处理 map 字段 {current_path} 失败: {e}")
        
        if isinstance(value, dict):
            try:
                _populate_protobuf_from_dict(field, value, path=current_path)
            except Exception as e:
                logger.error(f"填充子消息失败: {current_path}: {e}")
                raise
        elif isinstance(value, list):
            # 处理 repeated enum：允许传入字符串名称或数字
            try:
                if fd is not None and fd.type == _FD.TYPE_ENUM:
                    enum_desc = getattr(fd, "enum_type", None)
                    resolved_values = []
                    for item in value:
                        if isinstance(item, str):
                            ev = enum_desc.values_by_name.get(item) if enum_desc is not None else None
                            if ev is not None:
                                resolved_values.append(ev.number)
                            else:
                                try:
                                    resolved_values.append(int(item))
                                except Exception:
                                    logger.warning(f"无法解析枚举值 '{item}' 为 {current_path}，已忽略")
                        else:
                            try:
                                resolved_values.append(int(item))
                            except Exception:
                                logger.warning(f"无法转换枚举值 {item} 为整数: {current_path}")
                    field.extend(resolved_values)
                    continue
            except Exception as e:
                logger.warning(f"处理 repeated enum 字段 {current_path} 失败: {e}")
            if value and isinstance(value[0], dict):
                try:
                    for idx, item in enumerate(value):
                        new_item = field.add()  # type: ignore[attr-defined]
                        _populate_protobuf_from_dict(new_item, item, path=f"{current_path}[{idx}]")
                except Exception as e:
                    logger.warning(f"填充复合数组失败 {current_path}: {e}")
            else:
                try:
                    field.extend(value)
                except Exception as e:
                    logger.warning(f"设置数组字段 {current_path} 失败: {e}")
        else:
            if key in ["in_progress", "resume_conversation"]:
                field.SetInParent()
            else:
                try:
                    # 处理标量 enum：允许传入字符串名称或数字
                    if fd is not None and fd.type == _FD.TYPE_ENUM:
                        enum_desc = getattr(fd, "enum_type", None)
                        if isinstance(value, str):
                            ev = enum_desc.values_by_name.get(value) if enum_desc is not None else None
                            if ev is not None:
                                setattr(proto_msg, key, ev.number)
                                continue
                            try:
                                setattr(proto_msg, key, int(value))
                                continue
                            except Exception:
                                pass
                        # 其余情况直接赋值，若类型不匹配由底层抛错
                    setattr(proto_msg, key, value)
                except Exception as e:
                    logger.warning(f"设置字段 {current_path} 失败: {e}")


# ===== server_message_data 递归处理 =====

def _encode_smd_inplace(obj: Any) -> Any:
    if isinstance(obj, dict):
        new_d: Dict[str, Any] = {}
        for k, v in obj.items():
            if k in ("server_message_data", "serverMessageData") and isinstance(v, dict):
                try:
                    b64 = encode_server_message_data(
                        uuid=v.get("uuid"),
                        seconds=v.get("seconds"),
                        nanos=v.get("nanos"),
                    )
                    new_d[k] = b64
                except Exception:
                    new_d[k] = v
            else:
                new_d[k] = _encode_smd_inplace(v)
        return new_d
    elif isinstance(obj, list):
        return [_encode_smd_inplace(x) for x in obj]
    else:
        return obj


def _decode_smd_inplace(obj: Any) -> Any:
    if isinstance(obj, dict):
        new_d: Dict[str, Any] = {}
        for k, v in obj.items():
            if k in ("server_message_data", "serverMessageData") and isinstance(v, str):
                try:
                    dec = decode_server_message_data(v)
                    new_d[k] = dec
                except Exception:
                    new_d[k] = v
            else:
                new_d[k] = _decode_smd_inplace(v)
        return new_d
    elif isinstance(obj, list):
        return [_decode_smd_inplace(x) for x in obj]
    else:
        return obj 

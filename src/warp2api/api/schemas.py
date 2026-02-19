#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API schemas for warp2api bridge routes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class EncodeRequest(BaseModel):
    json_data: Optional[Dict[str, Any]] = None
    message_type: str = "warp.multi_agent.v1.Request"

    task_context: Optional[Dict[str, Any]] = None
    input: Optional[Dict[str, Any]] = None
    settings: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    mcp_context: Optional[Dict[str, Any]] = None
    existing_suggestions: Optional[Dict[str, Any]] = None
    client_version: Optional[str] = None
    os_category: Optional[str] = None
    os_name: Optional[str] = None
    os_version: Optional[str] = None

    model_config = ConfigDict(extra="allow")

    def get_data(self) -> Dict[str, Any]:
        if self.json_data is not None:
            return self.json_data
        data: Dict[str, Any] = {}
        if self.task_context is not None:
            data["task_context"] = self.task_context
        if self.input is not None:
            data["input"] = self.input
        if self.settings is not None:
            data["settings"] = self.settings
        if self.metadata is not None:
            data["metadata"] = self.metadata
        if self.mcp_context is not None:
            data["mcp_context"] = self.mcp_context
        if self.existing_suggestions is not None:
            data["existing_suggestions"] = self.existing_suggestions
        if self.client_version is not None:
            data["client_version"] = self.client_version
        if self.os_category is not None:
            data["os_category"] = self.os_category
        if self.os_name is not None:
            data["os_name"] = self.os_name
        if self.os_version is not None:
            data["os_version"] = self.os_version

        skip_keys = {
            "json_data",
            "message_type",
            "task_context",
            "input",
            "settings",
            "metadata",
            "mcp_context",
            "existing_suggestions",
            "client_version",
            "os_category",
            "os_name",
            "os_version",
        }
        try:
            for k, v in self.__dict__.items():
                if v is None or k in skip_keys:
                    continue
                if k not in data:
                    data[k] = v
        except Exception:
            pass
        return data


class DecodeRequest(BaseModel):
    protobuf_bytes: str
    message_type: str = "warp.multi_agent.v1.Request"


class StreamDecodeRequest(BaseModel):
    protobuf_chunks: List[str]
    message_type: str = "warp.multi_agent.v1.Response"


class MinimalWarpChatRequest(BaseModel):
    query: str
    model: Optional[str] = None
    timeout_seconds: int = 90
    client_version: Optional[str] = None
    os_version: Optional[str] = None

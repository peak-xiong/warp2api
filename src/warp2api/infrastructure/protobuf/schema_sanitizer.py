# -*- coding: utf-8 -*-
"""
Shared utilities to validate and sanitize MCP tool input_schema in request packets.
Ensures JSON Schema correctness, removes empty values, and enforces non-empty
`type` and `description` for each property. Special handling for `headers`.
"""
from typing import Any, Dict, List


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def _deep_clean(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for k, v in value.items():
            vv = _deep_clean(v)
            if _is_empty_value(vv):
                continue
            cleaned[k] = vv
        return cleaned
    if isinstance(value, list):
        cleaned_list = []
        for item in value:
            ii = _deep_clean(item)
            if _is_empty_value(ii):
                continue
            cleaned_list.append(ii)
        return cleaned_list
    if isinstance(value, str):
        return value.strip()
    return value


def _infer_type_for_property(prop_name: str) -> str:
    name = prop_name.lower()
    if name in ("url", "uri", "href", "link"):
        return "string"
    if name in ("headers", "options", "params", "payload", "data"):
        return "object"
    return "string"


def _ensure_property_schema(name: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    prop = dict(schema) if isinstance(schema, dict) else {}
    prop = _deep_clean(prop)

    # Enforce type & description
    if "type" not in prop or not isinstance(prop.get("type"), str) or not prop["type"].strip():
        prop["type"] = _infer_type_for_property(name)
    if "description" not in prop or not isinstance(prop.get("description"), str) or not prop["description"].strip():
        prop["description"] = f"{name} parameter"

    # Special handling for headers
    if name.lower() == "headers":
        prop["type"] = "object"
        headers_props = prop.get("properties")
        if not isinstance(headers_props, dict):
            headers_props = {}
        headers_props = _deep_clean(headers_props)
        if not headers_props:
            headers_props = {
                "user-agent": {
                    "type": "string",
                    "description": "User-Agent header for the request",
                }
            }
        else:
            fixed_headers: Dict[str, Any] = {}
            for hk, hv in headers_props.items():
                sub = _deep_clean(hv if isinstance(hv, dict) else {})
                if "type" not in sub or not isinstance(sub.get("type"), str) or not sub["type"].strip():
                    sub["type"] = "string"
                if "description" not in sub or not isinstance(sub.get("description"), str) or not sub["description"].strip():
                    sub["description"] = f"{hk} header"
                fixed_headers[hk] = sub
            headers_props = fixed_headers
        prop["properties"] = headers_props
        if isinstance(prop.get("required"), list):
            req = [r for r in prop["required"] if isinstance(r, str) and r in headers_props]
            if req:
                prop["required"] = req
            else:
                prop.pop("required", None)
        if isinstance(prop.get("additionalProperties"), dict) and len(prop["additionalProperties"]) == 0:
            prop.pop("additionalProperties", None)

    return prop


def _sanitize_json_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    s = _deep_clean(schema if isinstance(schema, dict) else {})

    # If properties exist, assume object type
    if "properties" in s and not isinstance(s.get("type"), str):
        s["type"] = "object"

    # Normalize $schema
    if "$schema" in s and not isinstance(s["$schema"], str):
        s.pop("$schema", None)
    if "$schema" not in s:
        s["$schema"] = "http://json-schema.org/draft-07/schema#"

    properties = s.get("properties")
    if isinstance(properties, dict):
        fixed_props: Dict[str, Any] = {}
        for name, subschema in properties.items():
            fixed_props[name] = _ensure_property_schema(name, subschema if isinstance(subschema, dict) else {})
        s["properties"] = fixed_props

    # Clean required list
    if isinstance(s.get("required"), list):
        if isinstance(properties, dict):
            req = [r for r in s["required"] if isinstance(r, str) and r in properties]
        else:
            req = []
        if req:
            s["required"] = req
        else:
            s.pop("required", None)

    # Remove empty additionalProperties object
    if isinstance(s.get("additionalProperties"), dict) and len(s["additionalProperties"]) == 0:
        s.pop("additionalProperties", None)

    return s


def sanitize_mcp_input_schema_in_packet(body: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and sanitize mcp_context.tools[*].input_schema in the given packet.

    - Removes empty values (empty strings, lists, dicts)
    - Ensures each property has non-empty `type` and `description`
    - Special-cases `headers` to include at least `user-agent` when empty
    - Fixes `required` lists and general JSON Schema shape
    """
    try:
        body = _deep_clean(body)
        candidate_roots: List[Dict[str, Any]] = []
        if isinstance(body.get("json_data"), dict):
            candidate_roots.append(body["json_data"])
        candidate_roots.append(body)

        for root in candidate_roots:
            if not isinstance(root, dict):
                continue
            mcp_ctx = root.get("mcp_context")
            if not isinstance(mcp_ctx, dict):
                continue
            tools = mcp_ctx.get("tools")
            if not isinstance(tools, list):
                continue
            fixed_tools: List[Any] = []
            for tool in tools:
                if not isinstance(tool, dict):
                    fixed_tools.append(tool)
                    continue
                tool_copy = dict(tool)
                input_schema = tool_copy.get("input_schema") or tool_copy.get("inputSchema")
                if isinstance(input_schema, dict):
                    tool_copy["input_schema"] = _sanitize_json_schema(input_schema)
                    if "inputSchema" in tool_copy:
                        tool_copy["inputSchema"] = tool_copy["input_schema"]
                fixed_tools.append(_deep_clean(tool_copy))
            mcp_ctx["tools"] = fixed_tools
        return body
    except Exception:
        return body 
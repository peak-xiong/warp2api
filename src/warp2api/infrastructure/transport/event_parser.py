from __future__ import annotations

import json
from typing import Any, Dict, List


def _get(data: Dict[str, Any], *names: str) -> Any:
    for name in names:
        if isinstance(data, dict) and name in data:
            return data[name]
    return None


def detect_event_type(event_data: Dict[str, Any]) -> str:
    if "init" in event_data:
        return "INITIALIZATION"
    if "finished" in event_data:
        return "FINISHED"

    client_actions = _get(event_data, "client_actions", "clientActions")
    if isinstance(client_actions, dict):
        actions = _get(client_actions, "actions", "Actions") or []
        if not actions:
            return "CLIENT_ACTIONS_EMPTY"

        kinds: List[str] = []
        for action in actions:
            if _get(action, "create_task", "createTask") is not None:
                kinds.append("CREATE_TASK")
            elif _get(action, "append_to_message_content", "appendToMessageContent") is not None:
                kinds.append("APPEND_CONTENT")
            elif _get(action, "add_messages_to_task", "addMessagesToTask") is not None:
                kinds.append("ADD_MESSAGE")
            elif _get(action, "update_task_message", "updateTaskMessage") is not None:
                kinds.append("UPDATE_MESSAGE")
            else:
                kinds.append("UNKNOWN_ACTION")

        return f"CLIENT_ACTIONS({', '.join(kinds)})"

    return "UNKNOWN_EVENT"


def extract_text_from_event(event_data: Dict[str, Any]) -> str:
    parts: List[str] = []
    client_actions = _get(event_data, "client_actions", "clientActions")
    if not isinstance(client_actions, dict):
        return ""

    actions = _get(client_actions, "actions", "Actions") or []
    for action in actions:
        append_data = _get(action, "append_to_message_content", "appendToMessageContent")
        if isinstance(append_data, dict):
            message = append_data.get("message", {})
            agent_output = _get(message, "agent_output", "agentOutput") or {}
            text = str(agent_output.get("text") or "")
            if text:
                parts.append(text)

        add_messages = _get(action, "add_messages_to_task", "addMessagesToTask")
        if isinstance(add_messages, dict):
            messages = add_messages.get("messages", []) or []
            for message in messages:
                agent_output = _get(message, "agent_output", "agentOutput") or {}
                text = str(agent_output.get("text") or "")
                if text:
                    parts.append(text)

    return "".join(parts)


def extract_tool_calls_from_event(event_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    tool_calls: List[Dict[str, Any]] = []
    client_actions = _get(event_data, "client_actions", "clientActions")
    if not isinstance(client_actions, dict):
        return tool_calls

    actions = _get(client_actions, "actions", "Actions") or []
    for action in actions:
        add_messages = _get(action, "add_messages_to_task", "addMessagesToTask")
        if not isinstance(add_messages, dict):
            continue

        for message in add_messages.get("messages", []) or []:
            tool_call = _get(message, "tool_call", "toolCall") or {}
            call_mcp = _get(tool_call, "call_mcp_tool", "callMcpTool") or {}
            if isinstance(call_mcp, dict) and call_mcp.get("name"):
                try:
                    args_str = json.dumps(call_mcp.get("args", {}) or {}, ensure_ascii=False)
                except Exception:
                    args_str = "{}"
                tool_calls.append(
                    {
                        "id": tool_call.get("tool_call_id"),
                        "name": call_mcp.get("name"),
                        "arguments": args_str,
                    }
                )

    return tool_calls

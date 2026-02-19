from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from pydantic import BaseModel

from warp2api.adapters.common.logging import logger
from warp2api.adapters.common.schemas import ChatMessage
from warp2api.application.services.warp_request_service import execute_warp_packet
from warp2api.infrastructure.settings.settings import CLIENT_VERSION, OS_VERSION


def _get(d: Dict[str, Any], *names: str) -> Any:
    for name in names:
        if isinstance(d, dict) and name in d:
            return d[name]
    return None


def normalize_content_to_list(content: Any) -> List[Dict[str, Any]]:
    segments: List[Dict[str, Any]] = []
    try:
        if isinstance(content, str):
            return [{"type": "text", "text": content}]
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    tp = item.get("type") or ("text" if isinstance(item.get("text"), str) else None)
                    if tp == "text" and isinstance(item.get("text"), str):
                        segments.append({"type": "text", "text": item.get("text")})
                    else:
                        seg: Dict[str, Any] = {}
                        if tp:
                            seg["type"] = tp
                        if isinstance(item.get("text"), str):
                            seg["text"] = item.get("text")
                        if seg:
                            segments.append(seg)
            return segments
        if isinstance(content, dict) and isinstance(content.get("text"), str):
            return [{"type": "text", "text": content.get("text")}]
    except Exception:
        return []
    return []


def segments_to_text(segments: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for seg in segments:
        if isinstance(seg, dict) and seg.get("type") == "text" and isinstance(seg.get("text"), str):
            parts.append(seg.get("text") or "")
    return "".join(parts)


def segments_to_warp_results(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for seg in segments:
        if isinstance(seg, dict) and seg.get("type") == "text" and isinstance(seg.get("text"), str):
            results.append({"text": {"text": seg.get("text")}})
    return results


class BridgeState(BaseModel):
    conversation_id: Optional[str] = None
    baseline_task_id: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_message_id: Optional[str] = None


class SessionStateStore:
    def __init__(self, ttl_seconds: int = 1800):
        self._ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._states: Dict[str, Tuple[BridgeState, float]] = {}

    def _cleanup_locked(self) -> None:
        now = time.time()
        expired = [k for k, (_, exp) in self._states.items() if exp <= now]
        for key in expired:
            self._states.pop(key, None)

    def get_or_create(self, session_key: str) -> BridgeState:
        now = time.time()
        with self._lock:
            self._cleanup_locked()
            state_exp = self._states.get(session_key)
            if state_exp is None:
                st = BridgeState()
            else:
                st = state_exp[0]
            ensure_tool_ids(st)
            self._states[session_key] = (st, now + self._ttl_seconds)
            return st


def ensure_tool_ids(state: BridgeState) -> None:
    if not state.tool_call_id:
        state.tool_call_id = str(uuid.uuid4())
    if not state.tool_message_id:
        state.tool_message_id = str(uuid.uuid4())


_SESSION_TTL = int(os.getenv("WARP_COMPAT_SESSION_TTL", "1800"))
STORE = SessionStateStore(ttl_seconds=_SESSION_TTL)


def resolve_session_key(headers: Optional[Dict[str, str]]) -> Optional[str]:
    if not headers:
        return None
    return headers.get("x-warp-session-id") or headers.get("x-session-id") or headers.get("x-conversation-id")


def get_state_for_request(headers: Optional[Dict[str, str]]) -> BridgeState:
    session_key = resolve_session_key(headers)
    if session_key:
        return STORE.get_or_create(session_key)
    st = BridgeState()
    ensure_tool_ids(st)
    return st


def reorder_messages_for_anthropic(history: List[ChatMessage]) -> List[ChatMessage]:
    if not history:
        return []

    expanded: List[ChatMessage] = []
    for m in history:
        if m.role == "user":
            items = normalize_content_to_list(m.content)
            if isinstance(m.content, list) and len(items) > 1:
                for seg in items:
                    if isinstance(seg, dict) and seg.get("type") == "text" and isinstance(seg.get("text"), str):
                        expanded.append(ChatMessage(role="user", content=seg.get("text")))
                    else:
                        expanded.append(ChatMessage(role="user", content=[seg] if isinstance(seg, dict) else seg))
            else:
                expanded.append(m)
        elif m.role == "assistant" and m.tool_calls and len(m.tool_calls) > 1:
            assistant_text = segments_to_text(normalize_content_to_list(m.content))
            if assistant_text:
                expanded.append(ChatMessage(role="assistant", content=assistant_text))
            for tc in (m.tool_calls or []):
                expanded.append(ChatMessage(role="assistant", content=None, tool_calls=[tc]))
        else:
            expanded.append(m)

    last_input_tool_id: Optional[str] = None
    last_input_is_tool = False
    for m in reversed(expanded):
        if m.role == "tool" and m.tool_call_id:
            last_input_tool_id = m.tool_call_id
            last_input_is_tool = True
            break
        if m.role == "user":
            break

    tool_results_by_id: Dict[str, ChatMessage] = {}
    assistant_tc_ids: set[str] = set()
    for m in expanded:
        if m.role == "tool" and m.tool_call_id and m.tool_call_id not in tool_results_by_id:
            tool_results_by_id[m.tool_call_id] = m
        if m.role == "assistant" and m.tool_calls:
            for tc in (m.tool_calls or []):
                tc_id = (tc or {}).get("id")
                if isinstance(tc_id, str) and tc_id:
                    assistant_tc_ids.add(tc_id)

    result: List[ChatMessage] = []
    trailing_assistant_msg: Optional[ChatMessage] = None
    for m in expanded:
        if m.role == "tool":
            if not m.tool_call_id or m.tool_call_id not in assistant_tc_ids:
                result.append(m)
                if m.tool_call_id:
                    tool_results_by_id.pop(m.tool_call_id, None)
            continue
        if m.role == "assistant" and m.tool_calls:
            ids: List[str] = []
            for tc in (m.tool_calls or []):
                tc_id = (tc or {}).get("id")
                if isinstance(tc_id, str) and tc_id:
                    ids.append(tc_id)

            if last_input_is_tool and last_input_tool_id and (last_input_tool_id in ids):
                if trailing_assistant_msg is None:
                    trailing_assistant_msg = m
                continue

            result.append(m)
            for tc_id in ids:
                tr = tool_results_by_id.pop(tc_id, None)
                if tr is not None:
                    result.append(tr)
            continue
        result.append(m)

    if last_input_is_tool and last_input_tool_id and trailing_assistant_msg is not None:
        result.append(trailing_assistant_msg)
        tr = tool_results_by_id.pop(last_input_tool_id, None)
        if tr is not None:
            result.append(tr)

    return result


def packet_template() -> Dict[str, Any]:
    return {
        "task_context": {"active_task_id": ""},
        "input": {"context": {}, "user_inputs": {"inputs": []}},
        "settings": {
            "model_config": {
                "base": "claude-4.1-opus",
                "planning": "gpt-5 (high reasoning)",
                "coding": "auto",
            },
            "rules_enabled": False,
            "web_context_retrieval_enabled": False,
            "supports_parallel_tool_calls": False,
            "planning_enabled": False,
            "warp_drive_context_enabled": False,
            "supports_create_files": False,
            "use_anthropic_text_editor_tools": False,
            "supports_long_running_commands": False,
            "should_preserve_file_content_in_history": False,
            "supports_todos_ui": False,
            "supports_linked_code_blocks": False,
            "supported_tools": [9],
        },
        "metadata": {"logging": {"is_autodetected_user_query": True, "entrypoint": "USER_INITIATED"}},
    }


def map_history_to_warp_messages(
    history: List[ChatMessage],
    task_id: str,
    state: Optional[BridgeState] = None,
) -> List[Dict[str, Any]]:
    st = state or BridgeState()
    ensure_tool_ids(st)

    msgs: List[Dict[str, Any]] = []
    msgs.append(
        {
            "id": st.tool_message_id or str(uuid.uuid4()),
            "task_id": task_id,
            "tool_call": {
                "tool_call_id": st.tool_call_id or str(uuid.uuid4()),
                "server": {"payload": "IgIQAQ=="},
            },
        }
    )

    last_input_index: Optional[int] = None
    for idx in range(len(history) - 1, -1, -1):
        msg = history[idx]
        if msg.role == "user":
            last_input_index = idx
            break
        if msg.role == "tool" and msg.tool_call_id:
            last_input_index = idx
            break

    for i, m in enumerate(history):
        mid = str(uuid.uuid4())
        if (last_input_index is not None) and (i == last_input_index):
            continue
        if m.role == "user":
            user_query_obj: Dict[str, Any] = {"query": segments_to_text(normalize_content_to_list(m.content))}
            msgs.append({"id": mid, "task_id": task_id, "user_query": user_query_obj})
        elif m.role == "assistant":
            assistant_text = segments_to_text(normalize_content_to_list(m.content))
            if assistant_text:
                msgs.append({"id": mid, "task_id": task_id, "agent_output": {"text": assistant_text}})
            for tc in (m.tool_calls or []):
                msgs.append(
                    {
                        "id": str(uuid.uuid4()),
                        "task_id": task_id,
                        "tool_call": {
                            "tool_call_id": tc.get("id") or str(uuid.uuid4()),
                            "call_mcp_tool": {
                                "name": (tc.get("function", {}) or {}).get("name", ""),
                                "args": (
                                    json.loads((tc.get("function", {}) or {}).get("arguments", "{}"))
                                    if isinstance((tc.get("function", {}) or {}).get("arguments"), str)
                                    else (tc.get("function", {}) or {}).get("arguments", {})
                                )
                                or {},
                            },
                        },
                    }
                )
        elif m.role == "tool":
            if m.tool_call_id:
                msgs.append(
                    {
                        "id": str(uuid.uuid4()),
                        "task_id": task_id,
                        "tool_call_result": {
                            "tool_call_id": m.tool_call_id,
                            "call_mcp_tool": {
                                "success": {
                                    "results": segments_to_warp_results(normalize_content_to_list(m.content))
                                }
                            },
                        },
                    }
                )
    return msgs


def attach_user_and_tools_to_inputs(packet: Dict[str, Any], history: List[ChatMessage], system_prompt_text: Optional[str]) -> None:
    if not history:
        raise AssertionError("post-reorder 必须至少包含一条消息")

    last = history[-1]
    if last.role == "user":
        user_query_payload: Dict[str, Any] = {"query": segments_to_text(normalize_content_to_list(last.content))}
        if system_prompt_text:
            user_query_payload["referenced_attachments"] = {
                "SYSTEM_PROMPT": {
                    "plain_text": (
                        "<ALERT>you are not allowed to call following tools:  - `read_files`\n"
                        "- `write_files`\n"
                        "- `run_commands`\n"
                        "- `list_files`\n"
                        "- `str_replace_editor`\n"
                        "- `ask_followup_question`\n"
                        "- `attempt_completion`</ALERT>"
                        f"{system_prompt_text}"
                    )
                }
            }
        packet["input"]["user_inputs"]["inputs"].append({"user_query": user_query_payload})
        return

    if last.role == "tool" and last.tool_call_id:
        packet["input"]["user_inputs"]["inputs"].append(
            {
                "tool_call_result": {
                    "tool_call_id": last.tool_call_id,
                    "call_mcp_tool": {
                        "success": {"results": segments_to_warp_results(normalize_content_to_list(last.content))}
                    },
                }
            }
        )
        return

    raise AssertionError("post-reorder 最后一条必须是 user 或 tool 结果")


def extract_text_deltas(event_data: Dict[str, Any]) -> List[str]:
    deltas: List[str] = []
    client_actions = _get(event_data, "client_actions", "clientActions")
    if not isinstance(client_actions, dict):
        return deltas
    actions = _get(client_actions, "actions", "Actions") or []
    for action in actions:
        append_data = _get(action, "append_to_message_content", "appendToMessageContent")
        if isinstance(append_data, dict):
            message = append_data.get("message", {})
            agent_output = _get(message, "agent_output", "agentOutput") or {}
            text = str(agent_output.get("text") or "")
            if text:
                deltas.append(text)

        add_msgs = _get(action, "add_messages_to_task", "addMessagesToTask")
        if isinstance(add_msgs, dict):
            for message in add_msgs.get("messages", []) or []:
                agent_output = _get(message, "agent_output", "agentOutput") or {}
                text = str(agent_output.get("text") or "")
                if text:
                    deltas.append(text)
    return deltas


def extract_tool_call_deltas(event_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    tool_deltas: List[Dict[str, Any]] = []
    client_actions = _get(event_data, "client_actions", "clientActions")
    if not isinstance(client_actions, dict):
        return tool_deltas
    actions = _get(client_actions, "actions", "Actions") or []
    for action in actions:
        add_msgs = _get(action, "add_messages_to_task", "addMessagesToTask")
        if not isinstance(add_msgs, dict):
            continue
        for message in add_msgs.get("messages", []) or []:
            tc = _get(message, "tool_call", "toolCall") or {}
            call_mcp = _get(tc, "call_mcp_tool", "callMcpTool") or {}
            if not (isinstance(call_mcp, dict) and call_mcp.get("name")):
                continue
            try:
                args_str = json.dumps(call_mcp.get("args", {}) or {}, ensure_ascii=False)
            except Exception:
                args_str = "{}"
            tool_deltas.append(
                {
                    "id": tc.get("tool_call_id") or str(uuid.uuid4()),
                    "type": "function",
                    "function": {
                        "name": call_mcp.get("name"),
                        "arguments": args_str,
                    },
                }
            )
    return tool_deltas


def is_finished_event(event_data: Dict[str, Any]) -> bool:
    return "finished" in (event_data or {})


def _chunk(
    completion_id: str,
    created_ts: int,
    model_id: str,
    delta: Dict[str, Any],
    finish_reason: str | None = None,
) -> Dict[str, Any]:
    obj: Dict[str, Any] = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created_ts,
        "model": model_id,
        "choices": [{"index": 0, "delta": delta}],
    }
    if finish_reason is not None:
        obj["choices"][0]["finish_reason"] = finish_reason
    return obj


async def _stream_once(
    packet: Dict[str, Any],
    completion_id: str,
    created_ts: int,
    model_id: str,
) -> AsyncGenerator[str, None]:
    tool_calls_emitted = False

    exec_ctx = await execute_warp_packet(
        actual_data=packet,
        message_type="warp.multi_agent.v1.Request",
        timeout_seconds=90,
        client_version=CLIENT_VERSION,
        os_version=OS_VERSION,
    )
    result_raw = exec_ctx["result_raw"]

    if not result_raw.get("ok"):
        raise RuntimeError(f"warp HTTP {result_raw.get('status_code')}: {result_raw.get('error')}")

    parsed_events = result_raw.get("parsed_events", []) or []
    for ev in parsed_events:
        event_data = ev.get("parsed_data") or {}

        for text in extract_text_deltas(event_data):
            yield f"data: {json.dumps(_chunk(completion_id, created_ts, model_id, {'content': text}), ensure_ascii=False)}\n\n"

        tcs = extract_tool_call_deltas(event_data)
        for tc in tcs:
            tool_calls_emitted = True
            yield f"data: {json.dumps(_chunk(completion_id, created_ts, model_id, {'tool_calls': [{'index': 0, **tc}]}), ensure_ascii=False)}\n\n"

        if is_finished_event(event_data):
            finish_reason = "tool_calls" if tool_calls_emitted else "stop"
            yield f"data: {json.dumps(_chunk(completion_id, created_ts, model_id, {}, finish_reason=finish_reason), ensure_ascii=False)}\n\n"

    yield "data: [DONE]\n\n"


async def stream_openai_sse(
    packet: Dict[str, Any],
    completion_id: str,
    created_ts: int,
    model_id: str,
) -> AsyncGenerator[str, None]:
    try:
        first = _chunk(completion_id, created_ts, model_id, {"role": "assistant"})
        yield f"data: {json.dumps(first, ensure_ascii=False)}\n\n"
        async for part in _stream_once(packet, completion_id, created_ts, model_id):
            yield part
    except Exception as exc:
        logger.error("[Gateway] Stream processing failed: %s", exc)
        error_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created_ts,
            "model": model_id,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}],
            "error": {"message": str(exc)},
        }
        yield f"data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

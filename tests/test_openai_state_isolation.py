from warp2api.application.services.chat_gateway_support import get_state_for_request


def test_state_without_session_key_is_not_shared():
    s1 = get_state_for_request({})
    s2 = get_state_for_request({})
    assert s1 is not s2
    assert s1.tool_call_id
    assert s2.tool_call_id
    assert s1.tool_call_id != s2.tool_call_id


def test_state_with_same_session_key_is_shared():
    headers = {"x-warp-session-id": "session-1"}
    s1 = get_state_for_request(headers)
    s1.conversation_id = "conv-1"
    s2 = get_state_for_request(headers)
    assert s2.conversation_id == "conv-1"
    assert s1.tool_call_id == s2.tool_call_id


def test_state_with_different_session_key_is_isolated():
    s1 = get_state_for_request({"x-warp-session-id": "session-a"})
    s2 = get_state_for_request({"x-warp-session-id": "session-b"})
    s1.baseline_task_id = "task-a"
    assert s2.baseline_task_id != "task-a"

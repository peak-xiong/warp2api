import asyncio

import warp2api.application.services.warp_request_service as svc


def test_execute_warp_packet_no_fallback(monkeypatch):
    async def _fake_send_protobuf_with_rotation(**kwargs):
        return {"ok": False, "status_code": 400, "error": "start a new conversation"}

    monkeypatch.setattr(svc, "send_protobuf_with_rotation", _fake_send_protobuf_with_rotation)

    payload = {
        "task_context": {"active_task_id": "t1"},
        "input": {"context": {}, "user_inputs": {"inputs": [{"user_query": {"query": "hello"}}]}},
        "settings": {"model_config": {"base": "auto"}},
    }

    out = asyncio.run(
        svc.execute_warp_packet(
            actual_data=payload,
            message_type="warp.multi_agent.v1.Request",
            timeout_seconds=20,
            client_version="v-test",
            os_version="test",
        )
    )

    assert out["query"] == "hello"
    assert out["model_tag"] == "auto"
    assert isinstance(out["protobuf_bytes"], bytes)
    assert out["result_raw"]["ok"] is False
    assert out["result_raw"]["status_code"] == 400


def test_execute_warp_packet_invalid_model_raises():
    payload = {
        "task_context": {"active_task_id": "t1"},
        "input": {"context": {}, "user_inputs": {"inputs": [{"user_query": {"query": "hello"}}]}},
        "settings": {"model_config": {"base": "not-real"}},
    }

    try:
        asyncio.run(
            svc.execute_warp_packet(
                actual_data=payload,
                message_type="warp.multi_agent.v1.Request",
                timeout_seconds=20,
                client_version="v-test",
                os_version="test",
            )
        )
        assert False, "expected ValueError"
    except ValueError as e:
        assert "Unsupported model" in str(e)

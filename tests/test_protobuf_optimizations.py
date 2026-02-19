from warp2api.infrastructure.protobuf import runtime as pb
from warp2api.domain.models.model_catalog import get_model_config


def test_msg_cls_cache_returns_same_class():
    pb.ensure_proto_runtime()
    c1 = pb.msg_cls("warp.multi_agent.v1.Request")
    c2 = pb.msg_cls("warp.multi_agent.v1.Request")
    assert c1 is c2


def test_build_request_bytes_uses_current_model_catalog():
    model = get_model_config("auto")["base"]
    payload = pb.build_request_bytes("warmup", model=model)
    assert isinstance(payload, bytes)
    assert len(payload) > 0

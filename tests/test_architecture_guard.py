from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_no_bridge_relay_in_adapter_or_application_layers():
    targets = []
    targets.extend((ROOT / "src/warp2api/adapters").rglob("*.py"))
    targets.extend((ROOT / "src/warp2api/application").rglob("*.py"))

    forbidden = [
        "WARP_BRIDGE_URL",
        "/api/warp/send_stream",
    ]

    for path in targets:
        text = _read(path)
        for pattern in forbidden:
            assert pattern not in text, f"forbidden pattern {pattern!r} found in {path}"


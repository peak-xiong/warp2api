from __future__ import annotations

import time
from typing import Dict, List, Tuple


def _label(model_id: str) -> str:
    return model_id.replace("-", " ")


def _expand_gpt(base_id: str, with_xhigh: bool) -> List[Tuple[str, str]]:
    variants: List[Tuple[str, str]] = [(base_id, _label(base_id))]
    levels = ["low", "medium", "high"]
    if with_xhigh:
        levels.append("xhigh")
    for level in levels:
        model_id = f"{base_id}-{level}"
        variants.append((model_id, _label(model_id)))
    return variants


def _build_supported_models() -> List[Tuple[str, str, int]]:
    ordered: List[Tuple[str, str]] = [
        ("auto", "auto"),
        ("claude-4-sonnet", "claude 4 sonnet"),
        ("claude-4.1-opus", "claude 4.1 opus"),
        ("claude-4.5-haiku", "claude 4.5 haiku"),
        ("claude-4.5-opus", "claude 4.5 opus"),
        ("claude-4.5-opus-thinking", "claude 4.5 opus thinking"),
        ("claude-4.5-sonnet", "claude 4.5 sonnet"),
        ("claude-4.5-sonnet-thinking", "claude 4.5 sonnet thinking"),
        ("claude-4.6-opus", "claude 4.6 opus"),
        ("claude-4.6-opus-max", "claude 4.6 opus max"),
        ("claude-4.6-sonnet", "claude 4.6 sonnet"),
        ("claude-4.6-sonnet-max", "claude 4.6 sonnet max"),
        ("gemini-2.5-pro", "gemini 2.5 pro"),
        ("gemini-3-pro", "gemini 3 pro"),
        ("glm-4.7-us-hosted", "glm 4.7 (us-hosted)"),
    ]

    ordered.extend(_expand_gpt("gpt-5", with_xhigh=False))
    ordered.extend(_expand_gpt("gpt-5.1", with_xhigh=True))
    ordered.extend(_expand_gpt("gpt-5.1-codex", with_xhigh=True))
    ordered.extend(_expand_gpt("gpt-5.1-codex-max", with_xhigh=True))
    ordered.extend(_expand_gpt("gpt-5.2", with_xhigh=True))
    ordered.extend(_expand_gpt("gpt-5.2-codex", with_xhigh=True))
    ordered.extend(_expand_gpt("gpt-5.3-codex", with_xhigh=True))

    return [(model_id, display_name, index) for index, (model_id, display_name) in enumerate(ordered)]


SUPPORTED_MODELS = _build_supported_models()
ALL_KNOWN_MODELS = {model_id for model_id, _, _ in SUPPORTED_MODELS}


def normalize_model_name(model_name: str) -> str:
    name = (model_name or "").strip()
    if not name:
        return "auto"
    return name


def get_model_config(model_name: str) -> Dict[str, str]:
    base_model = normalize_model_name(model_name)
    if base_model not in ALL_KNOWN_MODELS:
        raise ValueError(f"Unsupported model: {base_model}")
    return {"base": base_model, "planning": "auto", "coding": "auto"}


def _model_item(model_id: str, display: str, sort: int = 0, vision: bool = True, category: str = "agent") -> Dict:
    return {
        "id": model_id,
        "display_name": display,
        "description": None,
        "vision_supported": vision,
        "usage_multiplier": 1,
        "category": category,
        "sort": sort,
    }


def get_warp_models() -> Dict[str, Dict[str, List[Dict]]]:
    return {
        "agent_mode": {
            "default": "auto",
            "models": [_model_item(mid, display, sort, category="agent") for mid, display, sort in SUPPORTED_MODELS],
        },
        "planning": {
            "default": "auto",
            "models": [_model_item(mid, display, sort, category="planning") for mid, display, sort in SUPPORTED_MODELS],
        },
        "coding": {
            "default": "auto",
            "models": [_model_item(mid, display, sort, category="coding") for mid, display, sort in SUPPORTED_MODELS],
        },
    }


def get_all_unique_models() -> List[Dict]:
    data = get_warp_models()
    unique: Dict[str, Dict] = {}
    for category_data in data.values():
        for model in category_data["models"]:
            model_id = model["id"]
            if model_id not in unique:
                unique[model_id] = {
                    "id": model_id,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "warp",
                    "display_name": model["display_name"],
                    "description": model["description"] or model["display_name"],
                    "vision_supported": model["vision_supported"],
                    "usage_multiplier": 1,
                    "categories": [model["category"]],
                }
            elif model["category"] not in unique[model_id]["categories"]:
                unique[model_id]["categories"].append(model["category"])

    return sorted(unique.values(), key=lambda x: next((m[2] for m in SUPPORTED_MODELS if m[0] == x["id"]), 999))

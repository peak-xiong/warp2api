from __future__ import annotations

from fastapi import FastAPI

from warp2api.adapters.openai.app import app

openai_app: FastAPI = app


def main() -> None:
    from .openai_runtime import run_openai_server

    run_openai_server(port=28889, reload=False)

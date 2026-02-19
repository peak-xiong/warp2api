from __future__ import annotations

from fastapi import FastAPI

from warp2api.adapters.openai.app import app

gateway_app: FastAPI = app
openai_app: FastAPI = gateway_app


def main() -> None:
    from .openai_runtime import run_gateway_server

    run_gateway_server(port=28889, reload=False)

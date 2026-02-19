from __future__ import annotations

from fastapi import FastAPI

from .bridge_app import create_app
from .bridge_runtime import run_server


app: FastAPI = create_app()


def main() -> None:
    run_server(port=28888, reload=False)

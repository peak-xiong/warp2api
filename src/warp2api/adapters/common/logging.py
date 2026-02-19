#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared logging for adapter packages."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

_logger = logging.getLogger("warp2api.adapters")
_logger.setLevel(logging.INFO)

for handler in _logger.handlers[:]:
    _logger.removeHandler(handler)

file_handler = RotatingFileHandler(
    LOG_DIR / "gateway_compat.log",
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
file_handler.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

fmt = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"
)
file_handler.setFormatter(fmt)
console_handler.setFormatter(fmt)

_logger.addHandler(file_handler)
_logger.addHandler(console_handler)

logger = _logger

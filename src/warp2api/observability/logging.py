#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Logging system for Warp API server

Provides comprehensive logging with file rotation and console output.
"""
import logging
import os
import shutil
from datetime import datetime
from logging.handlers import RotatingFileHandler
from warp2api.infrastructure.settings.settings import LOGS_DIR


def backup_existing_log():
    """Backup existing log file with timestamp"""
    log_file = LOGS_DIR / 'warp_api.log'

    if log_file.exists():
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f'warp_api_{timestamp}.log'
        backup_path = LOGS_DIR / backup_name

        try:
            shutil.move(str(log_file), str(backup_path))
            print(f"Previous log backed up as: {backup_name}")
        except Exception as e:
            print(f"Warning: Could not backup log file: {e}")


def setup_logging():
    """Configure comprehensive logging system"""
    LOGS_DIR.mkdir(exist_ok=True)

    backup_existing_log()
    
    logger = logging.getLogger('warp_api')
    logger.setLevel(logging.DEBUG)
    
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    file_handler = RotatingFileHandler(
        LOGS_DIR / 'warp_api.log',
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


# Initialize logger
logger = setup_logging()


def log(*a): 
    """Simple structured log helper."""
    logger.info(" ".join(str(x) for x in a))


def set_log_file(log_file_name: str) -> None:
    """Reconfigure the global logger to write to a specific log file."""
    try:
        LOGS_DIR.mkdir(exist_ok=True)
    except Exception:
        pass

    global logger
    target_logger = logging.getLogger('warp_api')

    for handler in target_logger.handlers[:]:
        try:
            target_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
        except Exception:
            pass

    file_handler = RotatingFileHandler(
        LOGS_DIR / log_file_name,
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    target_logger.addHandler(file_handler)
    target_logger.addHandler(console_handler)

    logger = target_logger

    try:
        logger.info(f"Logging redirected to: {LOGS_DIR / log_file_name}")
    except Exception:
        pass 

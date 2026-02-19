#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Global session management for Warp API

Manages fixed conversation_id and task context based on real packet analysis.
"""
import uuid
import time
import asyncio
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from warp2api.observability.logging import logger

# 全局固定的conversation_id - 所有请求都使用这个ID
FIXED_CONVERSATION_ID = "5b48d359-0715-479e-a158-0a00f2dfea36"


@dataclass
class SessionMessage:
    """Represents a message in the session history"""
    id: str
    role: str  # "user", "assistant", "system", "tool"
    content: str
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class SessionState:
    """Global session state for the fixed conversation"""
    conversation_id: str = FIXED_CONVERSATION_ID
    active_task_id: Optional[str] = None
    messages: List[SessionMessage] = field(default_factory=list)
    initialized: bool = False
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)


class GlobalSessionManager:
    """
    Manages the global fixed session for Warp API.
    """
    
    def __init__(self):
        self._session = SessionState()
        self._initialization_lock = asyncio.Lock()
        logger.info(f"GlobalSessionManager initialized with fixed conversation_id: {FIXED_CONVERSATION_ID}")
    
    def get_fixed_conversation_id(self) -> str:
        return FIXED_CONVERSATION_ID
    
    def add_message_from_openai(self, role: str, content: str, tool_calls: Optional[List[Dict]] = None, tool_call_id: Optional[str] = None) -> str:
        message_id = f"msg-{uuid.uuid4().hex[:8]}"
        message = SessionMessage(
            id=message_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id
        )
        
        self._session.messages.append(message)
        self._session.last_activity = time.time()
        
        logger.debug(f"Added {role} message to session: {content[:100]}...")
        return message_id
    
    def get_session_history(self) -> List[SessionMessage]:
        return self._session.messages.copy()
    
    def get_history_for_task_context(self) -> List[SessionMessage]:
        return self._session.messages.copy()
    
    def update_session_with_openai_messages(self, openai_messages: List[Dict[str, Any]]) -> None:
        self._session.messages.clear()
        for msg in openai_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls")
            tool_call_id = msg.get("tool_call_id")
            if not content and not tool_calls and role != "tool":
                continue
            self.add_message_from_openai(role, content, tool_calls, tool_call_id)
        logger.debug(f"Updated session with {len(openai_messages)} OpenAI messages")
    
    def extract_current_user_query(self, openai_messages: List[Dict[str, Any]]) -> Optional[str]:
        for msg in reversed(openai_messages):
            if msg.get("role") == "user":
                query = msg.get("content", "")
                logger.debug(f"Extracted current user query: {query[:100]}...")
                return query
        return None
    
    def get_history_messages_excluding_current(self, current_user_query: str) -> List[SessionMessage]:
        history = []
        for msg in self._session.messages:
            if msg.role == "user" and msg.content == current_user_query:
                continue
            history.append(msg)
        logger.debug(f"Retrieved {len(history)} history messages (excluding current query)")
        return history
    
    def set_active_task_id(self, task_id: str) -> None:
        self._session.active_task_id = task_id
        logger.debug(f"Set active task_id: {task_id}")
    
    def get_active_task_id(self) -> Optional[str]:
        return self._session.active_task_id
    
    def is_initialized(self) -> bool:
        return self._session.initialized
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "conversation_id": self._session.conversation_id,
            "initialized": self._session.initialized,
            "active_task_id": self._session.active_task_id,
            "message_count": len(self._session.messages),
            "created_at": self._session.created_at,
            "last_activity": self._session.last_activity
        }


# Global session manager instance
_global_session: Optional[GlobalSessionManager] = None

def get_global_session() -> GlobalSessionManager:
    global _global_session
    if _global_session is None:
        _global_session = GlobalSessionManager()
    return _global_session 

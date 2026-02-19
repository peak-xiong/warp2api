#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流式数据包处理器

处理流式protobuf数据包，支持实时解析和WebSocket推送。
"""
import asyncio
import json
import base64
from typing import AsyncGenerator, List, Dict, Any, Optional
from datetime import datetime

from warp2api.observability.logging import logger
from warp2api.infrastructure.protobuf.utils import protobuf_to_dict


class StreamProcessor:
    """流式数据包处理器"""
    
    def __init__(self, websocket_manager=None):
        self.websocket_manager = websocket_manager
        self.active_streams: Dict[str, StreamSession] = {}
        
    async def create_stream_session(self, stream_id: str, message_type: str = "warp.multi_agent.v1.Response") -> 'StreamSession':
        """创建流式会话"""
        session = StreamSession(stream_id, message_type, self.websocket_manager)
        self.active_streams[stream_id] = session
        
        logger.info(f"创建流式会话: {stream_id}, 消息类型: {message_type}")
        return session
    
    async def get_stream_session(self, stream_id: str) -> Optional['StreamSession']:
        """获取流式会话"""
        return self.active_streams.get(stream_id)
    
    async def close_stream_session(self, stream_id: str):
        """关闭流式会话"""
        if stream_id in self.active_streams:
            session = self.active_streams[stream_id]
            await session.close()
            del self.active_streams[stream_id]
            logger.info(f"关闭流式会话: {stream_id}")
    
    async def process_stream_chunk(self, stream_id: str, chunk_data: bytes) -> Dict[str, Any]:
        """处理流式数据块"""
        session = await self.get_stream_session(stream_id)
        if not session:
            raise ValueError(f"流式会话不存在: {stream_id}")
        
        return await session.process_chunk(chunk_data)
    
    async def finalize_stream(self, stream_id: str) -> Dict[str, Any]:
        """完成流式处理"""
        session = await self.get_stream_session(stream_id)
        if not session:
            raise ValueError(f"流式会话不存在: {stream_id}")
        
        result = await session.finalize()
        await self.close_stream_session(stream_id)
        return result


class StreamSession:
    """流式会话"""
    
    def __init__(self, session_id: str, message_type: str, websocket_manager=None):
        self.session_id = session_id
        self.message_type = message_type
        self.websocket_manager = websocket_manager
        
        self.chunks: List[bytes] = []
        self.chunk_count = 0
        self.total_size = 0
        self.start_time = datetime.now()
        
        self.parsed_chunks: List[Dict] = []
        self.complete_message: Optional[Dict] = None
        
    async def process_chunk(self, chunk_data: bytes) -> Dict[str, Any]:
        """处理单个数据块"""
        self.chunk_count += 1
        self.total_size += len(chunk_data)
        self.chunks.append(chunk_data)
        
        logger.debug(f"流式会话 {self.session_id}: 处理数据块 {self.chunk_count}, 大小 {len(chunk_data)} 字节")
        
        chunk_result = {
            "chunk_index": self.chunk_count - 1,
            "size": len(chunk_data),
            "timestamp": datetime.now().isoformat()
        }
        
        try:
            chunk_json = protobuf_to_dict(chunk_data, self.message_type)
            chunk_result["json_data"] = chunk_json
            chunk_result["parsed_successfully"] = True
            
            self.parsed_chunks.append(chunk_json)
            
            if self.websocket_manager:
                await self.websocket_manager.broadcast({
                    "event": "stream_chunk_parsed",
                    "stream_id": self.session_id,
                    "chunk": chunk_result
                })
                
        except Exception as e:
            chunk_result["error"] = str(e)
            chunk_result["parsed_successfully"] = False
            logger.warning(f"数据块解析失败: {e}")
            
            if self.websocket_manager:
                await self.websocket_manager.broadcast({
                    "event": "stream_chunk_error", 
                    "stream_id": self.session_id,
                    "chunk": chunk_result
                })
        
        return chunk_result
    
    async def finalize(self) -> Dict[str, Any]:
        """完成流式处理，尝试拼接完整消息"""
        duration = (datetime.now() - self.start_time).total_seconds()
        
        logger.info(f"流式会话 {self.session_id} 完成: {self.chunk_count} 块, 总大小 {self.total_size} 字节, 耗时 {duration:.2f}s")
        
        result = {
            "session_id": self.session_id,
            "chunk_count": self.chunk_count,
            "total_size": self.total_size,
            "duration_seconds": duration,
            "chunks": []
        }
        
        for i, chunk in enumerate(self.chunks):
            chunk_info = {
                "index": i,
                "size": len(chunk),
                "hex_preview": chunk[:32].hex() if len(chunk) >= 32 else chunk.hex()
            }
            
            if i < len(self.parsed_chunks):
                chunk_info["parsed_data"] = self.parsed_chunks[i]
            
            result["chunks"].append(chunk_info)
        
        try:
            complete_data = b''.join(self.chunks)
            complete_json = protobuf_to_dict(complete_data, self.message_type)
            
            result["complete_message"] = {
                "size": len(complete_data),
                "json_data": complete_json,
                "assembly_successful": True
            }
            
            self.complete_message = complete_json
            
            logger.info(f"流式消息拼接成功: {len(complete_data)} 字节")
            
        except Exception as e:
            result["complete_message"] = {
                "error": str(e),
                "assembly_successful": False
            }
            logger.warning(f"流式消息拼接失败: {e}")
        
        if self.websocket_manager:
            await self.websocket_manager.broadcast({
                "event": "stream_completed",
                "stream_id": self.session_id,
                "result": result
            })
        
        return result
    
    async def close(self):
        """关闭会话"""
        self.chunks.clear()
        self.parsed_chunks.clear()
        self.complete_message = None
        
        logger.debug(f"流式会话 {self.session_id} 已关闭")


class StreamPacketAnalyzer:
    """流式数据包分析器"""
    
    @staticmethod
    def analyze_chunk_patterns(chunks: List[bytes]) -> Dict[str, Any]:
        if not chunks:
            return {"error": "无数据块"}
        
        analysis = {
            "total_chunks": len(chunks),
            "size_distribution": {},
            "size_stats": {},
            "pattern_analysis": {}
        }
        
        sizes = [len(chunk) for chunk in chunks]
        analysis["size_stats"] = {
            "min": min(sizes),
            "max": max(sizes),
            "avg": sum(sizes) / len(sizes),
            "total": sum(sizes)
        }
        
        size_ranges = [(0, 100), (100, 500), (500, 1000), (1000, 5000), (5000, float('inf'))]
        for start, end in size_ranges:
            range_name = f"{start}-{end if end != float('inf') else '∞'}"
            count = sum(1 for size in sizes if start <= size < end)
            analysis["size_distribution"][range_name] = count
        
        if len(chunks) >= 2:
            first_bytes = [chunk[:4].hex() if len(chunk) >= 4 else chunk.hex() for chunk in chunks[:5]]
            analysis["pattern_analysis"]["first_bytes_samples"] = first_bytes
            
            if chunks:
                common_prefix_len = 0
                first_chunk = chunks[0]
                for i in range(min(len(first_chunk), 10)):
                    if all(len(chunk) > i and chunk[i] == first_chunk[i] for chunk in chunks[1:]):
                        common_prefix_len = i + 1
                    else:
                        break
                
                if common_prefix_len > 0:
                    analysis["pattern_analysis"]["common_prefix_length"] = common_prefix_len
                    analysis["pattern_analysis"]["common_prefix_hex"] = first_chunk[:common_prefix_len].hex()
        
        return analysis
    
    @staticmethod
    def extract_streaming_deltas(parsed_chunks: List[Dict]) -> List[Dict]:
        if not parsed_chunks:
            return []
        
        deltas = []
        previous_content = ""
        
        for i, chunk in enumerate(parsed_chunks):
            delta = {
                "chunk_index": i,
                "timestamp": datetime.now().isoformat()
            }
            
            current_content = StreamPacketAnalyzer._extract_text_content(chunk)
            
            if current_content and current_content != previous_content:
                if previous_content and current_content.startswith(previous_content):
                    delta["content_delta"] = current_content[len(previous_content):]
                    delta["delta_type"] = "append"
                else:
                    delta["content_delta"] = current_content
                    delta["delta_type"] = "replace"
                
                delta["total_content_length"] = len(current_content)
                previous_content = current_content
            else:
                delta["content_delta"] = ""
                delta["delta_type"] = "no_change"
            
            if i > 0:
                delta["field_changes"] = StreamPacketAnalyzer._compare_dicts(parsed_chunks[i-1], chunk)
            
            deltas.append(delta)
        
        return deltas
    
    @staticmethod
    def _extract_text_content(data: Dict) -> str:
        text_paths = [
            ["content"],
            ["text"],
            ["message"],
            ["agent_output", "text"],
            ["choices", 0, "delta", "content"],
            ["choices", 0, "message", "content"]
        ]
        
        for path in text_paths:
            try:
                current = data
                for key in path:
                    if isinstance(current, dict) and key in current:
                        current = current[key]
                    elif isinstance(current, list) and isinstance(key, int) and 0 <= key < len(current):
                        current = current[key]
                    else:
                        break
                else:
                    if isinstance(current, str):
                        return current
            except Exception:
                continue
        
        return ""
    
    @staticmethod
    def _compare_dicts(dict1: Dict, dict2: Dict, prefix: str = "") -> List[str]:
        changes = []
        
        all_keys = set(dict1.keys()) | set(dict2.keys())
        
        for key in all_keys:
            current_path = f"{prefix}.{key}" if prefix else key
            
            if key not in dict1:
                changes.append(f"添加: {current_path}")
            elif key not in dict2:
                changes.append(f"删除: {current_path}")
            elif dict1[key] != dict2[key]:
                if isinstance(dict1[key], dict) and isinstance(dict2[key], dict):
                    changes.extend(StreamPacketAnalyzer._compare_dicts(dict1[key], dict2[key], current_path))
                else:
                    changes.append(f"修改: {current_path}")
        
        return changes[:10]


_global_processor: Optional[StreamProcessor] = None

def get_stream_processor() -> StreamProcessor:
    global _global_processor
    if _global_processor is None:
        _global_processor = StreamProcessor()
    return _global_processor


def set_websocket_manager(manager):
    processor = get_stream_processor()
    processor.websocket_manager = manager 

"""
数据模型模块
定义请求和响应的数据结构
"""
from datetime import datetime
from typing import Dict, Any, Optional


class RequestMetrics:
    """请求性能指标模型"""

    def __init__(self, request_id: str):
        self.request_id = request_id
        self.request_received_time: float = 0.0
        self.forward_start_time: float = 0.0
        self.response_first_byte_time: Optional[float] = None
        self.response_complete_time: Optional[float] = None
        self.proxy_processing_time: float = 0.0
        self.time_to_first_byte: float = 0.0
        self.first_token_latency: float = 0.0
        self.model_response_time: float = 0.0
        self.total_time: float = 0.0
        self.endpoint: str = ""
        self.method: str = ""
        self.api_type: str = ""
        self.stream: bool = False
        self.status_code: int = 200
        self.has_tool_call: bool = False
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.inter_request_gap: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "request_id": self.request_id,
            "request_received_time": self.request_received_time,
            "forward_start_time": self.forward_start_time,
            "response_first_byte_time": self.response_first_byte_time,
            "response_complete_time": self.response_complete_time,
            "proxy_processing_time": self.proxy_processing_time,
            "time_to_first_byte": self.time_to_first_byte,
            "first_token_latency": self.first_token_latency,
            "model_response_time": self.model_response_time,
            "total_time": self.total_time,
            "endpoint": self.endpoint,
            "method": self.method,
            "api_type": self.api_type,
            "stream": self.stream,
            "status_code": self.status_code,
            "has_tool_call": self.has_tool_call,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "inter_request_gap": self.inter_request_gap
        }


class RequestLog:
    """请求日志模型"""

    def __init__(self, request_id: str, method: str, path: str, api_type: str):
        self.request_id = request_id
        self.timestamp = datetime.now().isoformat()
        self.method = method
        self.path = path
        self.api_type = api_type
        self.headers: Dict[str, str] = {}
        self.body: Dict[str, Any] = {}

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "method": self.method,
            "path": self.path,
            "api_type": self.api_type,
            "headers": self.headers,
            "body": self.body
        }


class ResponseLog:
    """响应日志模型"""

    def __init__(self, request_id: str, status_code: int):
        self.request_id = request_id
        self.status_code = status_code
        self.timestamp = datetime.now().isoformat()
        self.body: Any = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "request_id": self.request_id,
            "status_code": self.status_code,
            "timestamp": self.timestamp,
            "body": self.body
        }


class ConversationTrace:
    """对话追踪模型"""

    def __init__(self, storage_id: str, trace_data: dict):
        self.storage_id = storage_id
        self.trace_id = trace_data.get('trace_id', '')
        self.agent_id = trace_data.get('agent_id', '')
        self.session_id = trace_data.get('session_id', '')
        self.source = trace_data.get('source', 'agent')
        self.started_at = trace_data.get('started_at', '')
        self.duration_seconds = trace_data.get('duration_seconds', 0)
        self.steps = trace_data.get('steps', [])
        self.summary = trace_data.get('summary', {})
        self.received_at = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "storage_id": self.storage_id,
            "trace_id": self.trace_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "source": self.source,
            "started_at": self.started_at,
            "duration_seconds": self.duration_seconds,
            "steps": self.steps,
            "summary": self.summary,
            "received_at": self.received_at
        }
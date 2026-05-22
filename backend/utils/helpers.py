"""
辅助函数模块
提供各种辅助功能函数
"""
from urllib.parse import urlparse
from typing import Dict, Any


def detect_api_type(path: str) -> str:
    """检测 API 类型：openai 或 anthropic"""
    if "/v1/messages" in path or "/messages" in path:
        return "anthropic"
    return "openai"  # 默认为 OpenAI 格式


def get_api_url(api_type: str) -> str:
    """根据 API 类型获取上游地址"""
    from backend.config import Config
    if api_type == "anthropic":
        return Config.ANTHROPIC_API_URL
    return Config.REAL_API_URL


def generate_request_id() -> str:
    """生成唯一请求ID"""
    import uuid
    return f"req-{uuid.uuid4()}"


def detect_tool_call(request_body: dict, response_body: dict) -> bool:
    """检测请求或响应中是否包含工具调用"""
    # 检查请求中的 tool_calls（OpenAI 格式）
    if isinstance(request_body, dict):
        messages = request_body.get('messages', [])
        for msg in messages:
            if msg.get('tool_calls') or msg.get('content') and isinstance(msg.get('content'), list):
                # Anthropic 格式：content 是数组，检查是否有 tool_use 类型
                if isinstance(msg.get('content'), list):
                    for content_block in msg.get('content'):
                        if content_block.get('type') == 'tool_use':
                            return True
            # 检查是否有 tool_call_id（表示是工具响应）
            if msg.get('role') == 'tool' or msg.get('tool_call_id'):
                return True

    # 检查响应中的 tool_calls（OpenAI 格式）
    if isinstance(response_body, dict):
        choices = response_body.get('choices', [])
        for choice in choices:
            message = choice.get('message', {})
            if message.get('tool_calls'):
                return True
            # Anthropic 格式
            content = message.get('content', [])
            if isinstance(content, list):
                for content_block in content:
                    if content_block.get('type') == 'tool_use':
                        return True

    return False


def format_time_duration(seconds: float) -> str:
    """格式化时间时长"""
    if seconds < 1:
        return f"{seconds * 1000:.2f}ms"
    return f"{seconds:.2f}s"


def calculate_time_metrics(start_time: float, end_time: float) -> Dict[str, float]:
    """计算时间指标"""
    duration = end_time - start_time
    return {
        "duration_seconds": duration,
        "duration_ms": duration * 1000
    }
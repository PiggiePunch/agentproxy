"""
辅助函数模块
提供各种辅助功能函数
"""
import http.client
import socket
from urllib.parse import urlparse
from typing import Dict, Any, Tuple


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


def classify_proxy_exception(e: BaseException, context: str) -> Tuple[int, str, str]:
    """
    将代理抛出的异常按"发生在哪条 socket / 哪个阶段"统一分类。

    context 取值:
      "client_write"      —— 代理往客户端 socket 写数据时出错（sendall / wfile.write）
      "upstream_read"     —— 代理从上游 socket 读响应体时出错（response.read1）
      "upstream_connect"  —— 代理与上游建链/发请求/读状态行时出错（conn.request / getresponse / read）

    分类规则（与 RFC 7231 §6.6 对齐）:
      客户端断开              → 499 client_disconnected  (NGINX 事实约定，非 RFC)
      上游超时                → 504 upstream_timeout
      上游通信异常/中途断      → 502 upstream_comm_error
      代理自身代码异常        → 500 proxy_internal

    返回: (status_code, type, failed_at)
    """
    if context == "client_write":
        # 往客户端写时任何连接级/超时异常都视为客户端断开
        if isinstance(e, (ConnectionError, socket.timeout, TimeoutError)):
            return 499, "client_disconnected", "client_write"

    elif context == "upstream_read":
        if isinstance(e, (socket.timeout, TimeoutError)):
            return 504, "upstream_timeout", "upstream_read"
        if isinstance(e, (http.client.IncompleteRead,
                         ConnectionError,
                         http.client.BadStatusLine)):
            return 502, "upstream_comm_error", "upstream_read"

    elif context == "upstream_connect":
        if isinstance(e, (socket.timeout, TimeoutError)):
            return 504, "upstream_timeout", "upstream_connect"
        if isinstance(e, (ConnectionError, http.client.BadStatusLine)):
            return 502, "upstream_comm_error", "upstream_connect"

    # 其余一律视为代理自身内部异常
    return 500, "proxy_internal", context
"""
代理服务模块
处理HTTP请求转发逻辑
"""
import http.client
import json
import ssl
import time
import socket
from urllib.parse import urlparse
from typing import Tuple, Optional, Dict, Any

from backend.config import Config
from backend.utils.converters import convert_anthropic_to_openai_request, convert_openai_to_anthropic_response
from backend.utils.helpers import get_api_url, generate_request_id


class ProxyService:
    """代理服务类"""

    def __init__(self):
        self.config = Config

    def prepare_forward_headers(self, headers_dict: dict, api_type: str = "openai") -> dict:
        """准备转发请求头"""
        forward_headers = {}
        skip_headers = ['host', 'content-length', 'transfer-encoding']

        custom_headers = []

        for key, value in headers_dict.items():
            key_lower = key.lower()
            if key_lower in skip_headers:
                continue
            forward_headers[key] = value

            if key_lower not in ['authorization', 'content-type', 'user-agent',
                                  'accept', 'accept-encoding', 'connection',
                                  'x-api-key', 'x-openai-organization', 'anthropic-version']:
                custom_headers.append(f"  {key}: {value}")

        # 设置正确的 Host 头
        target_url = get_api_url(api_type)
        parsed = urlparse(target_url)
        forward_headers["Host"] = parsed.netloc

        if custom_headers:
            print(f"📋 转发 {len(custom_headers)} 个自定义/扩展请求头:")
            for header in custom_headers:
                print(header)

        return forward_headers

    def forward_request(self, method: str, path: str, headers: dict,
                       body: Optional[bytes] = None, api_type: str = "openai") -> Tuple[any, bytes]:
        """转发HTTP请求到上游服务器"""
        target_url = get_api_url(api_type)
        parsed = urlparse(target_url)

        # 确定端口
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == 'https' else 80

        # 选择连接类
        if parsed.scheme == 'https':
            ConnClass = http.client.HTTPSConnection
        else:
            ConnClass = http.client.HTTPConnection

        # 构建完整路径
        full_path = parsed.path + path
        if parsed.query:
            full_path += "?" + parsed.query

        # 创建连接
        conn = ConnClass(parsed.hostname, port, timeout=60)

        try:
            # 转发请求
            conn.request(method, full_path, body=body, headers=headers)

            # 获取响应
            response = conn.getresponse()

            # 读取响应体
            response_body = response.read()

            return response, response_body

        finally:
            conn.close()

    def extract_token_usage(self, response_body: dict, request_body: dict = None) -> tuple:
        """提取token使用量"""
        input_tokens = 0
        output_tokens = 0

        if isinstance(response_body, dict):
            usage = response_body.get('usage', {})
            input_tokens = usage.get('prompt_tokens') or usage.get('input_tokens', 0)
            output_tokens = usage.get('completion_tokens') or usage.get('output_tokens', 0)

        return input_tokens, output_tokens

    def calculate_metrics(self, request_received_time: float, forward_start_time: float,
                         response_received_time: float, inter_request_gap: Optional[float] = None,
                         status_code: int = 200, has_tool_call: bool = False,
                         input_tokens: int = 0, output_tokens: int = 0,
                         endpoint: str = "", method: str = "POST",
                         api_type: str = "", stream: bool = False) -> dict:
        """计算性能指标"""
        return {
            "request_received_time": request_received_time,
            "forward_start_time": forward_start_time,
            "response_received_time": response_received_time,
            "proxy_processing_time": max(0, forward_start_time - request_received_time),
            "first_token_latency": 0,  # 标准请求没有首token时延
            "model_response_time": max(0, response_received_time - forward_start_time),
            "total_time": max(0, response_received_time - request_received_time),
            "inter_request_gap": inter_request_gap,
            "endpoint": endpoint,
            "method": method,
            "api_type": api_type,
            "stream": stream,
            "status_code": status_code,
            "has_tool_call": has_tool_call,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens
        }
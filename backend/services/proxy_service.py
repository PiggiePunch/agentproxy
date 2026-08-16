"""
代理服务模块
处理HTTP请求转发逻辑
"""
import http.client
import json
import ssl
import time
import socket
import gzip
import zlib
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
        # accept-encoding 必须剥离：代理需解析响应体，不能让上游 gzip 压缩
        skip_headers = ['host', 'content-length', 'transfer-encoding', 'accept-encoding']

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
            print(f"转发 {len(custom_headers)} 个自定义/扩展请求头:")
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

        # 构建完整路径（智能处理各种配置格式）
        base_path = parsed.path.rstrip("/")
        endpoint_path = path

        # 情况1: base_path 已包含完整 endpoint（如 /v1/chat/completions）
        # 例如: https://api.bigmodel.cn/v1/chat/completions -> 直接使用 base_path
        if base_path.endswith('/chat/completions') and endpoint_path == '/v1/chat/completions':
            full_path = base_path
        elif base_path.endswith('/v1/messages') and endpoint_path == '/v1/messages':
            full_path = base_path
        # 情况2: base_path 以版本号结尾（如 /v1, /v2, /api/paas/v4）
        # 例如: https://api.moonshot.cn/v1 + /v1/chat/completions -> /v1/chat/completions
        else:
            import re
            if re.search(r'(/v\d+|/api/paas/v\d+)$', base_path) and endpoint_path.startswith('/v1'):
                endpoint_path = endpoint_path[3:]  # 去掉 "/v1"
            full_path = base_path + endpoint_path
            if not full_path.startswith('/'):
                full_path = '/' + full_path

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

            # 防御性解压：正常路径已剥离 accept-encoding，上游理应不压缩；
            # 但部分上游会无视协商强行压缩，这里按 Content-Encoding 兜底解压
            content_encoding = response.getheader('Content-Encoding')
            if content_encoding:
                response_body = self._decompress_body(content_encoding, response_body)

            return response, response_body

        finally:
            conn.close()

    @staticmethod
    def _decompress_body(content_encoding: str, body: bytes) -> bytes:
        """按 Content-Encoding 解压响应体（防御性，正常路径不应触发）"""
        enc = (content_encoding or '').lower().strip()
        if not enc or enc == 'identity':
            return body
        try:
            if enc == 'gzip':
                return gzip.decompress(body)
            if enc == 'deflate':
                # deflate 可能是 zlib 包装，也可能是 raw deflate
                try:
                    return zlib.decompress(body)
                except zlib.error:
                    return zlib.decompress(body, -zlib.MAX_WBITS)
            if enc == 'br':
                try:
                    import brotli
                except ImportError:
                    print("[proxy] response is brotli-compressed but brotli package not installed; returning raw")
                    return body
                try:
                    return brotli.decompress(body)
                except Exception as e:
                    print(f"[proxy] brotli decompress failed: {e}; returning raw")
                    return body
        except Exception as e:
            print(f"[proxy] decompress {enc} failed: {e}; returning raw")
        return body

    def extract_token_usage(self, response_body: dict, request_body: dict = None) -> tuple:
        """提取token使用量"""
        input_tokens = 0
        output_tokens = 0

        if isinstance(response_body, dict):
            usage = response_body.get('usage') or {}
            if isinstance(usage, dict):
                if usage.get('prompt_tokens') is not None:
                    # OpenAI格式：prompt_tokens 已包含缓存部分（cached_tokens 是其子集）
                    input_tokens = usage.get('prompt_tokens') or 0
                else:
                    # Anthropic格式：input_tokens 只是未命中缓存的部分，
                    # 加上缓存写入/读取才是模型实际接收的完整上下文
                    input_tokens = (usage.get('input_tokens') or 0) + \
                                   (usage.get('cache_creation_input_tokens') or 0) + \
                                   (usage.get('cache_read_input_tokens') or 0)
                output_tokens = usage.get('completion_tokens') or usage.get('output_tokens', 0)

        return input_tokens, output_tokens

    def calculate_metrics(self, request_received_time: float, forward_start_time: float,
                         response_received_time: float, inter_request_gap: Optional[float] = None,
                         status_code: int = 200, has_tool_call: bool = False,
                         input_tokens: int = 0, output_tokens: int = 0,
                         endpoint: str = "", method: str = "POST",
                         api_type: str = "", stream: bool = False,
                         session_id: Optional[str] = None,
                         session_source: Optional[str] = None) -> dict:
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
            "output_tokens": output_tokens,
            "session_id": session_id,
            "session_source": session_source
        }
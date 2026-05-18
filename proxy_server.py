#!/usr/bin/env python3
"""
OpenClaw Proxy Server - Python 3.8 标准库版本
无需安装任何第三方依赖
"""

import json
import time
import os
import threading
import socket
import ssl
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, ParseResult
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import urllib.request
import urllib.error
import http.client
import io

# ============= 配置区域 =============
REAL_API_URL = os.getenv("REAL_API_URL", "https://api.deepseek.com")
ANTHROPIC_API_URL = os.getenv("ANTHROPIC_API_URL", "https://open.bigmodel.cn/api/anthropic")
VERBOSE_LOGGING = os.getenv("VERBOSE_LOGGING", "true").lower() == "true"
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "3"))  # 日志保留天数

# 打印实际配置
print("\n" + "="*80)
print("🔧 代理服务器配置")
print("="*80)
print(f"REAL_API_URL: {REAL_API_URL}")
print(f"ANTHROPIC_API_URL: {ANTHROPIC_API_URL}")
print(f"解析 ANTHROPIC_API_URL.path: {urlparse(ANTHROPIC_API_URL).path}")
print("="*80 + "\n")

# 获取脚本所在目录（使用绝对路径，避免工作目录问题）
SCRIPT_DIR = Path(__file__).parent.resolve()

# 日志存储目录（使用绝对路径）
LOGS_DIR = SCRIPT_DIR / "logs"
REQUESTS_DIR = LOGS_DIR / "requests"
RESPONSES_DIR = LOGS_DIR / "responses"
METRICS_DIR = LOGS_DIR / "metrics"

# 创建日志目录
try:
    LOGS_DIR.mkdir(exist_ok=True)
    REQUESTS_DIR.mkdir(exist_ok=True)
    RESPONSES_DIR.mkdir(exist_ok=True)
    METRICS_DIR.mkdir(exist_ok=True)
    print(f"✓ 日志目录初始化成功: {LOGS_DIR}")
except PermissionError as e:
    print(f"❌ 创建日志目录失败（权限不足）: {e}")
    print(f"   目录路径: {LOGS_DIR}")
    print(f"   当前用户: {os.getenv('USER', 'unknown')}")
    import sys
    sys.exit(1)
except Exception as e:
    print(f"❌ 创建日志目录失败: {e}")
    print(f"   目录路径: {LOGS_DIR}")
    import sys
    sys.exit(1)


def cleanup_old_logs(days_to_keep=3):
    """清理指定天数前的旧日志文件"""
    try:
        cutoff_time = datetime.now().timestamp() - (days_to_keep * 24 * 60 * 60)
        total_deleted = 0

        # 清理三个子目录
        for subdir_name, subdir_path in [
            ("请求日志", REQUESTS_DIR),
            ("响应日志", RESPONSES_DIR),
            ("性能指标", METRICS_DIR)
        ]:
            if not subdir_path.exists():
                continue

            deleted_count = 0
            try:
                for file_path in subdir_path.glob("*.json"):
                    if file_path.stat().st_mtime < cutoff_time:
                        file_path.unlink()
                        deleted_count += 1
                        total_deleted += 1

                if deleted_count > 0:
                    print(f"  ✓ 已清理 {subdir_name}: {deleted_count} 个文件")
            except Exception as e:
                print(f"  ⚠️  清理 {subdir_name} 时出错: {e}")

        if total_deleted > 0:
            print(f"✓ 日志清理完成: 共删除 {total_deleted} 个 {days_to_keep} 天前的旧文件")
        else:
            print(f"✓ 日志清理完成: 无需删除的旧文件")

    except Exception as e:
        print(f"❌ 日志清理失败: {e}")


# 启动时清理旧日志
print("🔍 检查并清理旧日志文件...")
cleanup_old_logs(days_to_keep=LOG_RETENTION_DAYS)

# 全局状态
request_logs = []
performance_metrics = defaultdict(list)
session_start_time = datetime.now()
last_request_time = None
request_counter = 0
lock = threading.Lock()
MAX_RECENT_REQUESTS = 100  # 内存中保留的最近请求数量

# 累计统计数据（从启动到现在的所有统计）
cumulative_stats = {
    'total_requests': 0,
    'total_time_sum': 0.0,
    'total_proxy_time_sum': 0.0,
    'total_model_time_sum': 0.0,
    'success_requests': 0,
    'failed_requests': 0,
    'inter_request_gaps': [],
    'max_total_time': 0.0,
    'min_total_time': float('inf')
}


def sanitize_headers(headers: dict) -> dict:
    """清理敏感请求头信息"""
    sanitized = {}
    for key, value in headers.items():
        key_lower = key.lower()
        if key_lower in ["authorization", "x-api-key"]:
            if value and len(value) > 20:
                sanitized[key] = f"{value[:10]}...{value[-4:]}"
            else:
                sanitized[key] = "***"
        else:
            sanitized[key] = value
    return sanitized


def save_request_body(request_id: str, headers: dict, body: dict):
    """保存请求头和请求体到文件"""
    filename = REQUESTS_DIR / f"{request_id}.json"
    request_data = {
        "request_id": request_id,
        "timestamp": datetime.now().isoformat(),
        "headers": headers,
        "body": body
    }
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(request_data, f, ensure_ascii=False, indent=2)


def save_response_body(request_id: str, body: dict or str, status_code: int):
    """保存响应体到文件"""
    filename = RESPONSES_DIR / f"{request_id}.json"
    response_data = {
        "status_code": status_code,
        "body": body,
        "timestamp": datetime.now().isoformat()
    }
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(response_data, f, ensure_ascii=False, indent=2)


def save_metrics(request_id: str, metrics: dict):
    """保存性能指标到文件"""
    # 确保metrics包含request_id
    metrics['request_id'] = request_id

    filename = METRICS_DIR / f"{request_id}.json"
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    with lock:
        # 添加到最近请求列表（限制为MAX_RECENT_REQUESTS条）
        performance_metrics['requests'].append({
            'request_id': request_id,
            **metrics
        })

        # 如果超过最大数量，移除最老的记录
        if len(performance_metrics['requests']) > MAX_RECENT_REQUESTS:
            performance_metrics['requests'].pop(0)

        # 更新累计统计数据（用于概览统计）
        cumulative_stats['total_requests'] += 1

        # 累加时间数据
        if 'total_time' in metrics:
            cumulative_stats['total_time_sum'] += metrics['total_time']
        if 'proxy_processing_time' in metrics:
            cumulative_stats['total_proxy_time_sum'] += metrics['proxy_processing_time']
        if 'model_response_time' in metrics:
            cumulative_stats['total_model_time_sum'] += metrics['model_response_time']
        elif 'time_to_first_byte' in metrics:
            cumulative_stats['total_model_time_sum'] += metrics['time_to_first_byte']

        # 更新成功/失败统计
        status_code = metrics.get('status_code', 200)
        if status_code == 200:
            cumulative_stats['success_requests'] += 1
        else:
            cumulative_stats['failed_requests'] += 1

        # 记录请求间隔（如果有）
        if 'inter_request_gap' in metrics and metrics['inter_request_gap']:
            cumulative_stats['inter_request_gaps'].append(metrics['inter_request_gap'])

        # 更新最大最小响应时间
        if 'total_time' in metrics:
            total_time = metrics['total_time']
            if total_time > cumulative_stats['max_total_time']:
                cumulative_stats['max_total_time'] = total_time
            if total_time < cumulative_stats['min_total_time']:
                cumulative_stats['min_total_time'] = total_time


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


def log_request_info(method: str, path: str, headers: dict, body: dict, request_id: str, api_type: str = "openai"):
    """记录请求信息"""
    # 检查是否为内部管理请求（静默处理）
    # 包括：/, /dashboard, /metrics 等
    internal_paths = ["/", "/dashboard", "/metrics", "/static"]
    is_internal_request = path in internal_paths or path.startswith("/metrics") or path.startswith("/static") or path.startswith("/dashboard")

    if is_internal_request:
        # 内部请求只打印简化信息
        print("⚙️ {} {} [{}]".format(method, path, datetime.now().strftime('%H:%M:%S')))
        return

    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "request_id": request_id,
        "method": method,
        "path": path,
        "api_type": api_type,
        "headers": sanitize_headers(headers),
        "body": body
    }
    request_logs.append(log_entry)

    print("\n" + "="*80)
    print(f"📥 收到请求 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    print(f"请求ID: {request_id}")
    print("="*80)
    print(f"方法：{method}")
    print(f"路径：{path}")
    print(f"API 类型：{api_type}")

    # 根据类型显示转发目标
    target_url = get_api_url(api_type)
    print(f"转发目标：{target_url}")

    print("\n请求头:")
    print(json.dumps(sanitize_headers(headers), indent=2, ensure_ascii=False))
    if body:
        print("\n请求体:")
        print(json.dumps(body, indent=2, ensure_ascii=False))
    print("="*80)


def log_response_info(status_code: int, headers: dict, body: str = None, path: str = ""):
    """记录响应信息"""
    # 检查是否为内部管理请求（静默处理）
    internal_paths = ["/", "/dashboard", "/metrics", "/static"]
    is_internal_request = path in internal_paths or path.startswith("/metrics") or path.startswith("/static") or path.startswith("/dashboard")

    if is_internal_request:
        # 内部请求只打印简化信息
        print(f"✓ {path} → {status_code} [{datetime.now().strftime('%H:%M:%S')}]")
        return

    print("\n" + "="*80)
    print(f"📤 收到响应 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    print("="*80)
    print(f"状态码：{status_code}")
    print("\n响应头:")
    print(json.dumps(sanitize_headers(headers), indent=2, ensure_ascii=False))
    if body and VERBOSE_LOGGING:
        print("\n响应体:")
        if len(body) > 2000:
            print(f"{body[:2000]}...\n[响应体已截断，完整长度: {len(body)} 字符]")
        else:
            print(body)
    print("="*80)


def detect_api_type(path: str) -> str:
    """检测 API 类型：openai 或 anthropic"""
    if "/v1/messages" in path or "/messages" in path:
        return "anthropic"
    return "openai"  # 默认为 OpenAI 格式


def get_api_url(api_type: str) -> str:
    """根据 API 类型获取上游地址"""
    if api_type == "anthropic":
        return ANTHROPIC_API_URL
    return REAL_API_URL


def convert_anthropic_to_openai_request(anthropic_request: dict) -> dict:
    """将 Anthropic 请求格式转换为 OpenAI 格式"""
    openai_request = {
        "model": anthropic_request.get("model", ""),
        "messages": anthropic_request.get("messages", []),
        "stream": anthropic_request.get("stream", False)
    }

    # 可选参数
    if "max_tokens" in anthropic_request:
        openai_request["max_tokens"] = anthropic_request["max_tokens"]
    if "temperature" in anthropic_request:
        openai_request["temperature"] = anthropic_request["temperature"]
    if "top_p" in anthropic_request:
        openai_request["top_p"] = anthropic_request["top_p"]

    return openai_request


def convert_openai_to_anthropic_response(openai_response: dict, model: str) -> dict:
    """将 OpenAI 响应格式转换为 Anthropic 格式"""
    # 提取内容和 token 使用
    content = ""
    if "choices" in openai_response and len(openai_response["choices"]) > 0:
        choice = openai_response["choices"][0]
        if "message" in choice:
            content = choice["message"].get("content", "")

    # 构建 Anthropic 格式响应
    anthropic_response = {
        "id": f"msg-{openai_response.get('id', 'unknown')}",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": content}],
        "model": model,
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": openai_response.get("usage", {}).get("prompt_tokens", openai_response.get("usage", {}).get("input_tokens", 0)),
            "output_tokens": openai_response.get("usage", {}).get("completion_tokens", openai_response.get("usage", {}).get("output_tokens", 0))
        }
    }

    return anthropic_response


def convert_openai_to_anthropic_stream_chunk(openai_chunk: dict, model: str) -> str:
    """将 OpenAI 流式数据块转换为 Anthropic 流式事件"""
    try:
        # 检查是否是 [DONE]
        if openai_chunk == "[DONE]" or openai_chunk.get("choices", [{}])[0].get("finish_reason") == "stop":
            return "event: message_stop\ndata: {\"type\": \"message_stop\", \"stop_reason\": \"end_turn\"}\n\n"

        # 提取 delta 内容
        delta = {}
        if "choices" in openai_chunk and len(openai_chunk["choices"]) > 0:
            delta = openai_chunk["choices"][0].get("delta", {})

        content = delta.get("content", "")

        if content:
            # 构建 Anthropic 流式事件
            event_data = {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": content}
            }
            return f"event: content_block_delta\ndata: {json.dumps(event_data)}\n\n"

        return ""  # 空内容不发送事件
    except:
        return ""
    print("="*80)


class ProxyHTTPRequestHandler(BaseHTTPRequestHandler):
    """HTTP请求处理器"""

    def log_message(self, format, *args):
        """禁用默认日志"""
        pass

    def _get_request_id(self):
        """生成请求ID"""
        import uuid
        return f"req-{uuid.uuid4()}"

    def _read_request_body(self):
        """读取请求体"""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > 0:
            body = self.rfile.read(content_length)
            try:
                return json.loads(body.decode('utf-8'))
            except json.JSONDecodeError:
                return body.decode('utf-8')
        return None

    def _prepare_forward_headers(self, api_type: str = "openai"):
        """准备转发请求头 - 透传所有客户端请求头"""
        forward_headers = {}
        # 需要跳过的请求头（这些会由代理重新生成或设置）
        skip_headers = ['host', 'content-length', 'transfer-encoding']

        custom_headers = []  # 记录自定义请求头用于调试

        for key, value in self.headers.items():
            key_lower = key.lower()
            # 跳过需要重新计算的请求头
            if key_lower in skip_headers:
                continue
            # 透传所有其他请求头（包括自定义请求头）
            forward_headers[key] = value

            # 记录可能的自定义请求头（非标准HTTP头）
            if key_lower not in ['authorization', 'content-type', 'user-agent',
                                  'accept', 'accept-encoding', 'connection',
                                  'x-api-key', 'x-openai-organization', 'anthropic-version']:
                custom_headers.append(f"  {key}: {value}")

        # 根据 API 类型设置正确的 Host 头
        target_url = get_api_url(api_type)
        parsed = urlparse(target_url)
        forward_headers["Host"] = parsed.netloc

        # 调试输出：显示转发的自定义请求头
        if custom_headers:
            print(f"📋 转发 {len(custom_headers)} 个自定义/扩展请求头:")
            for header in custom_headers:
                print(header)

        return forward_headers

    def _do_forward_request(self, method: str, path: str, headers: dict, body: bytes = None, api_type: str = "openai"):
        """转发HTTP请求"""
        # 根据 API 类型选择正确的上游 URL
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

    def _send_json_response(self, status_code: int, data: dict, headers: dict = None):
        """发送JSON响应"""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')

        if headers:
            for key, value in headers.items():
                if key.lower() not in ['content-type', 'content-length', 'transfer-encoding']:
                    self.send_header(key, value)

        response_body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_header('Content-Length', len(response_body))
        self.end_headers()
        self.wfile.write(response_body)

    def _send_stream_response(self, request_id: str, forward_headers: dict, body_data: dict, request_received_time: float, forward_start_time: float = None):
        """发送流式响应（OpenAI 格式）"""
        import uuid

        print("\n🌊 检测到流式请求 (stream=true)")
        print("   客户端 → 代理 → 大模型（全程流式连接）")
        print("")

        # 准备请求数据
        request_body = json.dumps(body_data).encode('utf-8')

        # 使用 OpenAI API URL
        target_url = get_api_url("openai")
        parsed = urlparse(target_url)
        port = parsed.port if parsed.port else (443 if parsed.scheme == 'https' else 80)
        full_path = parsed.path.rstrip('/') + '/chat/completions'

        # 发送响应头
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache, no-transform')
        self.send_header('Connection', 'close')  # 改为 close，让客户端知道传输完成后会关闭
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()
        print("✓ 响应头已发送，开始流式传输...")

        # 创建HTTPS连接并流式传输 - 优化超时设置
        # timeout 参数设置为 None，表示不设置超时，避免流式传输被中断
        # 我们会在应用层处理超时逻辑

        if parsed.scheme == 'https':
            # 对于 HTTPS，不设置 socket 超时
            conn = http.client.HTTPSConnection(
                parsed.hostname,
                port,
                timeout=None,  # 不设置超时，由应用层控制
                context=ssl.create_default_context()
            )
        else:
            conn = http.client.HTTPConnection(
                parsed.hostname,
                port,
                timeout=None  # 不设置超时，由应用层控制
            )

        chunk_count = 0
        total_bytes = 0
        response_first_byte_time = None
        first_token_time = None  # 首token时间（首个实际内容）
        has_first_token = False  # 是否已收到首token
        ft_buffer = ""  # SSE行缓冲，用于跨read1()调用解析首token
        if forward_start_time is None:
            forward_start_time = time.time()
        stream_complete_time = None  # 流完成时间（收到DONE时）
        stream_chunks = []  # 存储所有chunk数据
        input_tokens = 0  # 输入token数
        output_tokens = 0  # 输出token数

        try:
            print("🔗 建立流式连接：客户端 ↔ 代理 ↔ 大模型")
            print("")

            # 发送请求
            conn.request("POST", full_path, body=request_body, headers=forward_headers)

            # 获取响应
            response = conn.getresponse()

            if response.status != 200:
                error_msg = response.read().decode('utf-8')
                print(f"❌ 上游返回错误状态码：{response.status}")
                print(f"   错误信息：{error_msg}")
                self.wfile.write(f"data: {json.dumps({'error': error_msg})}\n\n".encode('utf-8'))
                return

            # 打印响应头信息用于调试
            print(f"✅ 上游响应状态：{response.status}")
            print(f"   Content-Type: {response.getheader('Content-Type', 'N/A')}")
            print(f"   Transfer-Encoding: {response.getheader('Transfer-Encoding', 'N/A')}")
            print("="*80)

            # 流式读取并转发 - 使用 read1() 避免阻塞等待完整缓冲区
            try:
                while True:
                    if response_first_byte_time is None:
                        response_first_byte_time = time.time()

                    # 使用 read1() 而不是 read()
                    # read1() 会立即返回可用数据，即使少于指定大小
                    # read() 会阻塞直到读取到指定大小的数据或连接关闭
                    chunk_size = 4096
                    chunk = response.read1(chunk_size)

                    # 检查是否到达流末尾（上游关闭连接）
                    if not chunk:
                        print(f"\n📦 流结束：上游关闭连接（read1返回空数据）")
                        break

                    chunk_count += 1
                    total_bytes += len(chunk)

                    # 检测首token：使用 SSE 行缓冲解析，兼容跨 read1() 的不完整行
                    if not has_first_token:
                        try:
                            chunk_str = chunk.decode('utf-8', errors='ignore')
                            # 统一 \r\n → \n，兼容不同上游的行尾格式
                            ft_buffer += chunk_str.replace('\r\n', '\n')
                            # 处理完整的 SSE 事件（以 \n\n 分隔）
                            while '\n\n' in ft_buffer:
                                event_text, ft_buffer = ft_buffer.split('\n\n', 1)
                                # 跳过 [DONE] 和 ping 事件
                                if '[DONE]' in event_text or 'event: ping' in event_text:
                                    continue
                                for line in event_text.split('\n'):
                                    line = line.strip()
                                    if not line.startswith('data:'):
                                        continue
                                    data_str = line[5:].strip()  # 去掉 "data:" 前缀（兼容有/无空格）
                                    if not data_str or data_str == '[DONE]':
                                        continue
                                    try:
                                        data = json.loads(data_str)
                                        for choice in data.get('choices', []):
                                            delta = choice.get('delta', {})
                                            content = delta.get('content', '')
                                            if content:
                                                first_token_time = time.time()
                                                has_first_token = True
                                                print(f"\n✓ 首token延迟: {(first_token_time - forward_start_time)*1000:.2f}ms")
                                                break
                                    except (json.JSONDecodeError, KeyError, TypeError):
                                        pass
                                    if has_first_token:
                                        break
                                if has_first_token:
                                    break
                        except Exception:
                            pass

                    if VERBOSE_LOGGING or chunk_count % 5 == 0:
                        chunk_preview = chunk.decode('utf-8', errors='ignore')[:200]
                        print(f"📦 数据块 #{chunk_count} ({len(chunk)} bytes): {chunk_preview}")
                    else:
                        print(f"📦 #{chunk_count}: {len(chunk)}b", end="\r")

                    # 保存chunk数据用于记录
                    try:
                        chunk_text = chunk.decode('utf-8', errors='ignore')
                        stream_chunks.append({
                            "chunk_number": chunk_count,
                            "size": len(chunk),
                            "data": chunk_text,
                            "timestamp": time.time()
                        })
                        # 尝试解析usage信息（OpenAI流式格式）
                        if '"usage"' in chunk_text:
                            lines = chunk_text.split('\n')
                            for line in lines:
                                # 兼容data:和data: 两种格式，排除[DONE]
                                if (line.startswith('data:') and 'data: [DONE]' not in line and
                                    line.strip() not in ['data:', 'data: ']):
                                    try:
                                        # 去掉data:前缀（兼容"data:"和"data: "两种格式）
                                        data_content = line[5:].strip() if line.startswith('data: ') else line[5:].strip()
                                        if not data_content:  # 跳过空的data行
                                            continue
                                        data_json = json.loads(data_content)
                                        if 'usage' in data_json:
                                            usage = data_json['usage']
                                            # 兼容OpenAI格式(prompt_tokens/completion_tokens)和Anthropic格式(input_tokens/output_tokens)
                                            # 使用or运算符优先选择非零值
                                            input_tokens = usage.get('prompt_tokens') or usage.get('input_tokens', 0)
                                            output_tokens = usage.get('completion_tokens') or usage.get('output_tokens', 0)
                                    except:
                                        pass
                    except:
                        stream_chunks.append({
                            "chunk_number": chunk_count,
                            "size": len(chunk),
                            "data": f"<binary data {len(chunk)} bytes>",
                            "timestamp": time.time()
                        })

                    # 立即转发给客户端 - 使用底层 socket 避免缓冲问题
                    try:
                        if hasattr(self, 'connection'):
                            # 使用 socket.sendall() 确保所有数据都被发送
                            self.connection.sendall(chunk)
                            # sendall() 会阻塞直到所有数据都被发送到网络缓冲区
                        else:
                            # 回退到 wfile
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        print(f"✓ 转发数据块 #{chunk_count}: {len(chunk)} bytes (累计: {total_bytes} bytes)")
                    except (ConnectionResetError, BrokenPipeError) as e:
                        print(f"\n⚠️  客户端连接中断：{e}")
                        break
                    except Exception as e:
                        print(f"\n❌ 写入客户端失败：{e}")
                        import traceback
                        traceback.print_exc()
                        break

                    # 检查是否接收到结束标记 [DONE]
                    # 重要：记录完成时间，但不立即退出，继续读取直到确认上游关闭连接
                    if b'[DONE]' in chunk:
                        if stream_complete_time is None:
                            stream_complete_time = time.time()
                            print(f"\n📦 检测到流结束标记 [DONE]，模型响应耗时: {(stream_complete_time - forward_start_time)*1000:.2f}ms")
                            if first_token_time:
                                print(f"   数据传输耗时: {(stream_complete_time - first_token_time)*1000:.2f}ms")
                        print(f"   继续读取确保没有遗漏...")
                        # 不要 break，继续读取直到 response.read() 返回空

            except http.client.IncompleteRead as e:
                print(f"\n⚠️  不完整读取：已接收 {e.partial} 字节")
                if e.partial:
                    try:
                        self.wfile.write(e.partial)
                        self.wfile.flush()
                        total_bytes += len(e.partial)
                    except:
                        pass
            except ConnectionResetError as e:
                print(f"\n⚠️  上游连接被重置：{e}")
            except Exception as e:
                print(f"\n❌ 流式读取异常：{e}")
                import traceback
                traceback.print_exc()

            # 保存流式性能指标
            # 如果没有检测到 [DONE]，使用当前时间作为完成时间
            if stream_complete_time is None:
                stream_complete_time = time.time()

            # 检测是否有工具调用（检查请求body）
            has_tool_call = detect_tool_call(body_data, {})

            metrics = {
                "request_received_time": request_received_time,
                "forward_start_time": forward_start_time,
                "response_first_byte_time": response_first_byte_time,
                "response_complete_time": stream_complete_time,
                "proxy_processing_time": max(0, forward_start_time - request_received_time),
                "time_to_first_byte": max(0, (response_first_byte_time - forward_start_time) if response_first_byte_time else 0),
                "first_token_latency": max(0, (first_token_time - forward_start_time) if first_token_time else 0),
                "model_response_time": max(0, stream_complete_time - forward_start_time),  # 模型总耗时
                "total_stream_time": max(0, stream_complete_time - forward_start_time),
                "total_time": max(0, stream_complete_time - request_received_time),
                "endpoint": "/v1/chat/completions",
                "method": "POST",
                "stream": True,
                "status_code": 200,
                "has_tool_call": has_tool_call,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens
            }
            save_metrics(request_id, metrics)

            response_data = {
                "stream": True,
                "status_code": 200,
                "total_chunks": chunk_count,
                "total_bytes": total_bytes,
                "timestamp": datetime.now().isoformat(),
                "chunks": stream_chunks  # 保存完整的chunk数据
            }
            save_response_body(request_id, response_data, 200)

            print(f"\n📁 已保存流式响应: {chunk_count} 个数据块，总大小 {total_bytes} 字节")
            if response_first_byte_time:
                print(f"   首字节时间: {(response_first_byte_time - forward_start_time)*1000:.2f}ms")
            if first_token_time:
                print(f"   首token延迟: {(first_token_time - forward_start_time)*1000:.2f}ms")
                if stream_complete_time:
                    print(f"   数据传输时间: {(stream_complete_time - first_token_time)*1000:.2f}ms")
            if stream_complete_time:
                print(f"   模型总耗时: {(stream_complete_time - forward_start_time)*1000:.2f}ms")
            print("\n" + "="*80)
            print(f"✅ 流式转发完成")
            print(f"   总数据块：{chunk_count}")
            print(f"   总字节数：{total_bytes}")
            print("="*80 + "\n")

        except Exception as e:
            print(f"\n❌ 流式转发异常：{e}")
            import traceback
            traceback.print_exc()
        finally:
            conn.close()
            print("✓ 上游连接已关闭")

        # 重要：确保所有数据都被发送出去，并给客户端时间接收
        print(f"✓ 总计发送 {total_bytes} 字节给客户端")
        print("⏳ 等待客户端接收数据...")

        try:
            if hasattr(self.connection, 'shutdown'):
                # 关闭写端，告诉客户端我们不会再发送数据了
                # 这样客户端的 read() 就会返回空字符串（收到 EOF）
                self.connection.shutdown(socket.SHUT_WR)
                print("✓ 已关闭连接写端，发送 EOF 给客户端")

                # 等待一段时间，让客户端有时间读取所有数据
                # 特别是最后的 [DONE] 标记
                time.sleep(0.5)
                print("✓ 等待 0.5 秒，确保客户端接收完所有数据")

        except Exception as e:
            print(f"⚠️  关闭写端时出错：{e}")

        print("✓ do_POST 方法即将返回，流式请求处理完成\n")

    def _send_anthropic_stream_response(self, request_id: str, forward_headers: dict,
                                         openai_request: dict, model: str,
                                         parsed_url, port: int, forward_start_time: float,
                                         request_received_time: float):
        """发送 Anthropic 格式的流式响应（从 OpenAI 格式转换）"""
        print("\n🌊 开始 Anthropic 流式转换转发")

        request_body = json.dumps(openai_request).encode('utf-8')

        # 发送响应头
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache, no-transform')
        self.send_header('Connection', 'keep-alive')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()
        print("✓ 响应头已发送，开始 Anthropic 流式传输...")

        # 创建连接
        if parsed_url.scheme == 'https':
            conn = http.client.HTTPSConnection(
                parsed_url.hostname,
                port,
                timeout=None,
                context=ssl.create_default_context()
            )
        else:
            conn = http.client.HTTPConnection(
                parsed_url.hostname,
                port,
                timeout=None
            )

        chunk_count = 0
        total_bytes = 0
        response_first_byte_time = None
        first_token_time = None  # 首token时间
        has_first_token = False  # 是否已收到首token
        stream_complete_time = None
        input_tokens = 0  # 输入token数
        output_tokens = 0  # 输出token数

        try:
            print("🔗 建立流式连接：客户端 ↔ 代理 ↔ OpenAI 上游")

            # 发送请求
            full_path = parsed_url.path.rstrip('/') + '/chat/completions'
            conn.request("POST", full_path, body=request_body, headers=forward_headers)

            # 获取响应
            response = conn.getresponse()

            if response.status != 200:
                error_msg = response.read().decode('utf-8')
                print(f"❌ 上游返回错误状态码：{response.status}")
                # 发送 Anthropic 错误格式
                error_event = f"event: error\ndata: {{\"type\": \"error\", \"error\": {{\"type\": \"api_error\", \"message\": \"{error_msg}\"}}}}\n\n"
                self.wfile.write(error_event.encode('utf-8'))
                self.wfile.flush()
                return

            print(f"✅ 上游响应状态：{response.status}")

            # 流式读取并转换
            buffer = ""
            while True:
                if response_first_byte_time is None:
                    response_first_byte_time = time.time()

                chunk = response.read1(4096)
                if not chunk:
                    print(f"\n📦 OpenAI 流结束")
                    break

                total_bytes += len(chunk)
                # 统一 \r\n → \n，兼容不同上游的行尾格式
                buffer += chunk.decode('utf-8', errors='ignore').replace('\r\n', '\n')

                # 按 SSE 行分割处理
                while '\n\n' in buffer:
                    event_part, buffer = buffer.split('\n\n', 1)

                    # 解析 OpenAI SSE 事件
                    lines = event_part.split('\n')
                    for line in lines:
                        # 兼容data:和data: 两种格式
                        if line.startswith('data:'):
                            # 去掉data:前缀（兼容"data:"和"data: "两种格式）
                            data_str = line[5:].strip() if line.startswith('data: ') else line[5:].strip()
                            if data_str.strip() == '[DONE]':
                                # 转换为 Anthropic 结束事件
                                if stream_complete_time is None:
                                    stream_complete_time = time.time()
                                    print(f"\n📦 检测到 [DONE]，模型响应耗时: {(stream_complete_time - forward_start_time)*1000:.2f}ms")
                                    if first_token_time:
                                        print(f"   数据传输耗时: {(stream_complete_time - first_token_time)*1000:.2f}ms")
                                anthropic_event = "event: message_stop\ndata: {\"type\": \"message_stop\", \"stop_reason\": \"end_turn\"}\n\n"
                                self.wfile.write(anthropic_event.encode('utf-8'))
                                self.wfile.flush()
                                print("\n📦 发送 Anthropic message_stop 事件")
                                break

                            try:
                                openai_chunk = json.loads(data_str)
                                # 首token检测（在 SSE 解析循环内部，利用已缓冲的完整事件）
                                if not has_first_token:
                                    for choice in openai_chunk.get('choices', []):
                                        delta = choice.get('delta', {})
                                        content = delta.get('content', '')
                                        if content:
                                            first_token_time = time.time()
                                            has_first_token = True
                                            print(f"\n✓ 首token延迟: {(first_token_time - forward_start_time)*1000:.2f}ms")
                                            break
                                # 提取usage信息
                                if 'usage' in openai_chunk:
                                    usage = openai_chunk['usage']
                                    # 兼容OpenAI格式(prompt_tokens/completion_tokens)和Anthropic格式(input_tokens/output_tokens)
                                    # 使用or运算符优先选择非零值
                                    input_tokens = usage.get('prompt_tokens') or usage.get('input_tokens', 0)
                                    output_tokens = usage.get('completion_tokens') or usage.get('output_tokens', 0)
                                # 转换为 Anthropic 事件
                                anthropic_event = convert_openai_to_anthropic_stream_chunk(openai_chunk, model)
                                if anthropic_event:
                                    self.wfile.write(anthropic_event.encode('utf-8'))
                                    self.wfile.flush()
                                    chunk_count += 1
                                    if chunk_count % 10 == 0:
                                        print(f"📦 已转换 {chunk_count} 个事件", end="\r")
                            except json.JSONDecodeError:
                                pass

            # 如果没有检测到 [DONE]，使用当前时间作为完成时间
            if stream_complete_time is None:
                stream_complete_time = time.time()

            # 检测是否有工具调用（检查请求body）
            has_tool_call = detect_tool_call(openai_request, {})

            # 保存性能指标
            metrics = {
                "request_received_time": request_received_time,
                "forward_start_time": forward_start_time,
                "response_first_byte_time": response_first_byte_time,
                "response_complete_time": stream_complete_time,
                "proxy_processing_time": max(0, forward_start_time - request_received_time),
                "time_to_first_byte": max(0, (response_first_byte_time - forward_start_time) if response_first_byte_time else 0),
                "first_token_latency": max(0, (first_token_time - forward_start_time) if first_token_time else 0),
                "model_response_time": max(0, stream_complete_time - forward_start_time),  # 模型总耗时
                "total_stream_time": max(0, stream_complete_time - forward_start_time),
                "total_time": max(0, stream_complete_time - request_received_time),
                "endpoint": "/v1/messages",
                "method": "POST",
                "api_type": "anthropic",
                "stream": True,
                "status_code": 200,
                "has_tool_call": has_tool_call,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens
            }
            save_metrics(request_id, metrics)

            print(f"\n✅ Anthropic 流式转换完成：{chunk_count} 个事件")

        except Exception as e:
            print(f"\n❌ Anthropic 流式转换异常：{e}")
            import traceback
            traceback.print_exc()
        finally:
            conn.close()
            print("✓ 上游连接已关闭")

            # 确保所有数据都被发送出去
            try:
                if hasattr(self.connection, 'shutdown'):
                    self.connection.shutdown(socket.SHUT_WR)
                    print("✓ 已关闭连接写端")
                    time.sleep(0.5)
            except Exception as e:
                print(f"⚠️  关闭写端时出错：{e}")

    def _send_stream_response_anthropic(self, request_id: str, forward_headers: dict,
                                         body_data: dict, parsed_url, port: int,
                                         full_path: str, forward_start_time: float,
                                         request_received_time: float):
        """发送 Anthropic 格式的流式响应（直接透传，不转换）"""
        print("\n🌊 开始 Anthropic 流式转发（透传模式）")

        request_body = json.dumps(body_data).encode('utf-8')

        # 发送响应头
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache, no-transform')
        self.send_header('Connection', 'keep-alive')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()
        print("✓ 响应头已发送，开始 Anthropic 流式传输...")

        # 创建连接
        if parsed_url.scheme == 'https':
            conn = http.client.HTTPSConnection(
                parsed_url.hostname,
                port,
                timeout=None,
                context=ssl.create_default_context()
            )
        else:
            conn = http.client.HTTPConnection(
                parsed_url.hostname,
                port,
                timeout=None
            )

        chunk_count = 0
        total_bytes = 0
        response_first_byte_time = None
        first_token_time = None  # 首token时间（首个实际内容）
        has_first_token = False  # 是否已收到首token
        ft_buffer = ""  # SSE行缓冲，用于跨read1()调用解析首token
        stream_complete_time = None  # 流完成时间
        stream_chunks = []  # 存储所有chunk数据
        input_tokens = 0  # 输入token数
        output_tokens = 0  # 输出token数

        try:
            print("🔗 建立流式连接：客户端 ↔ 代理 ↔ Anthropic 上游")

            # 发送请求
            conn.request("POST", full_path, body=request_body, headers=forward_headers)

            # 获取响应
            response = conn.getresponse()

            if response.status != 200:
                error_msg = response.read().decode('utf-8')
                print(f"❌ 上游返回错误状态码：{response.status}")
                print(f"   错误信息：{error_msg}")
                self.wfile.write(f"event: error\ndata: {json.dumps({'type': 'error', 'error': {'message': error_msg}})}\n\n".encode('utf-8'))
                self.wfile.flush()
                return

            print(f"✅ 上游响应状态：{response.status}")
            print("="*80)

            # 流式读取并转发（透传，不转换）
            while True:
                if response_first_byte_time is None:
                    response_first_byte_time = time.time()

                chunk = response.read1(4096)
                if not chunk:
                    print(f"\n📦 Anthropic 流结束")
                    break

                chunk_count += 1
                total_bytes += len(chunk)

                # 检测首token：使用 SSE 行缓冲解析 Anthropic 事件格式
                if not has_first_token:
                    try:
                        chunk_str = chunk.decode('utf-8', errors='ignore')
                        # 统一 \r\n → \n，兼容不同上游的行尾格式
                        ft_buffer += chunk_str.replace('\r\n', '\n')
                        # 处理完整的 SSE 事件（以 \n\n 分隔）
                        while '\n\n' in ft_buffer:
                            event_text, ft_buffer = ft_buffer.split('\n\n', 1)
                            if 'event: message_stop' in event_text or 'event: ping' in event_text:
                                continue
                            # 解析 event:/data: 配对行
                            current_event = None
                            for line in event_text.split('\n'):
                                line = line.strip()
                                if line.startswith('event:'):
                                    current_event = line[6:].strip()
                                elif line.startswith('data:'):
                                    data_str = line[5:].strip()  # 去掉 "data:" 前缀（兼容有/无空格）
                                    if not data_str:
                                        continue
                                    try:
                                        data = json.loads(data_str)
                                    except (json.JSONDecodeError, TypeError):
                                        continue
                                    # 检查 content_block_delta 中的 text_delta
                                    if current_event == 'content_block_delta':
                                        delta = data.get('delta', {})
                                        if delta.get('type') == 'text_delta' and delta.get('text', ''):
                                            first_token_time = time.time()
                                            has_first_token = True
                                            print(f"\n✓ 首token延迟: {(first_token_time - forward_start_time)*1000:.2f}ms")
                                            break
                                    # 某些实现把 type 放在 data JSON 而非 event 行
                                    elif data.get('type') == 'content_block_delta':
                                        delta = data.get('delta', {})
                                        if delta.get('type') == 'text_delta' and delta.get('text', ''):
                                            first_token_time = time.time()
                                            has_first_token = True
                                            print(f"\n✓ 首token延迟: {(first_token_time - forward_start_time)*1000:.2f}ms")
                                            break
                            if has_first_token:
                                break
                    except Exception:
                        pass

                # 检测 message_stop 事件（流结束标记）
                if b'event: message_stop' in chunk:
                    if stream_complete_time is None:
                        stream_complete_time = time.time()
                        print(f"\n📦 检测到 message_stop 事件，模型响应耗时: {(stream_complete_time - forward_start_time)*1000:.2f}ms")
                        if first_token_time:
                            print(f"   数据传输耗时: {(stream_complete_time - first_token_time)*1000:.2f}ms")

                if VERBOSE_LOGGING or chunk_count % 5 == 0:
                    chunk_preview = chunk.decode('utf-8', errors='ignore')[:200]
                    print(f"📦 数据块 #{chunk_count} ({len(chunk)} bytes): {chunk_preview}")
                else:
                    print(f"📦 #{chunk_count}: {len(chunk)}b", end="\r")

                # 保存chunk数据用于记录
                try:
                    chunk_text = chunk.decode('utf-8', errors='ignore')
                    stream_chunks.append({
                        "chunk_number": chunk_count,
                        "size": len(chunk),
                        "data": chunk_text,
                        "timestamp": time.time()
                    })
                    # 尝试解析usage信息（Anthropic流式格式）
                    if 'message_delta' in chunk_text or '"usage"' in chunk_text:
                        lines = chunk_text.split('\n')
                        current_event = None  # 跟踪当前事件类型
                        for line in lines:
                            # 检查是否是事件行
                            if line.startswith('event:'):
                                current_event = line[6:].strip()  # 获取事件类型（如message_delta）
                            # 检查data行（兼容有/无空格）
                            elif line.startswith('data:'):
                                try:
                                    # 去掉data:前缀（兼容"data:"和"data: "两种格式）
                                    data_content = line[5:].strip() if line.startswith('data: ') else line[5:].strip()
                                    if not data_content:  # 跳过空的data行
                                        continue
                                    data_json = json.loads(data_content)
                                    if 'usage' in data_json:
                                        usage = data_json['usage']
                                        # 兼容OpenAI格式(prompt_tokens/completion_tokens)和Anthropic格式(input_tokens/output_tokens)
                                        # 使用or运算符优先选择非零值
                                        input_tokens = usage.get('input_tokens') or usage.get('prompt_tokens', 0)
                                        output_tokens = usage.get('output_tokens') or usage.get('completion_tokens', 0)
                                except:
                                    pass
                except:
                    stream_chunks.append({
                        "chunk_number": chunk_count,
                        "size": len(chunk),
                        "data": f"<binary data {len(chunk)} bytes>",
                        "timestamp": time.time()
                    })

                # 立即转发给客户端
                try:
                    if hasattr(self, 'connection'):
                        self.connection.sendall(chunk)
                    else:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except (ConnectionResetError, BrokenPipeError) as e:
                    print(f"\n⚠️  客户端连接中断：{e}")
                    break

            # 如果没有检测到 message_stop，使用当前时间作为完成时间
            if stream_complete_time is None:
                stream_complete_time = time.time()

            # 检测是否有工具调用（检查请求body）
            has_tool_call = detect_tool_call(body_data, {})

            # 保存性能指标
            metrics = {
                "request_received_time": request_received_time,
                "forward_start_time": forward_start_time,
                "response_first_byte_time": response_first_byte_time,
                "response_complete_time": stream_complete_time,
                "proxy_processing_time": max(0, forward_start_time - request_received_time),
                "time_to_first_byte": max(0, (response_first_byte_time - forward_start_time) if response_first_byte_time else 0),
                "first_token_latency": max(0, (first_token_time - forward_start_time) if first_token_time else 0),
                "model_response_time": max(0, stream_complete_time - forward_start_time),  # 模型总耗时
                "total_stream_time": max(0, stream_complete_time - forward_start_time),
                "total_time": max(0, stream_complete_time - request_received_time),
                "endpoint": "/v1/messages",
                "method": "POST",
                "api_type": "anthropic",
                "stream": True,
                "status_code": 200,
                "has_tool_call": has_tool_call,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens
            }
            save_metrics(request_id, metrics)

            # 保存流式响应数据（包含所有chunk）
            response_data = {
                "stream": True,
                "status_code": 200,
                "total_chunks": chunk_count,
                "total_bytes": total_bytes,
                "timestamp": datetime.now().isoformat(),
                "chunks": stream_chunks  # 保存完整的chunk数据
            }
            save_response_body(request_id, response_data, 200)

            print(f"\n📁 已保存 Anthropic 流式响应: {chunk_count} 个数据块，总大小 {total_bytes} 字节")
            if response_first_byte_time:
                print(f"   首字节时间: {(response_first_byte_time - forward_start_time)*1000:.2f}ms")
            if first_token_time:
                print(f"   首token延迟: {(first_token_time - forward_start_time)*1000:.2f}ms")
                if stream_complete_time:
                    print(f"   数据传输时间: {(stream_complete_time - first_token_time)*1000:.2f}ms")
            if stream_complete_time:
                print(f"   模型总耗时: {(stream_complete_time - forward_start_time)*1000:.2f}ms")
            print("\n" + "="*80)
            print(f"✅ Anthropic 流式转发完成（透传）")
            print(f"   总数据块：{chunk_count}")
            print(f"   总字节数：{total_bytes}")
            print("="*80 + "\n")

        except Exception as e:
            print(f"\n❌ Anthropic 流式转发异常：{e}")
            import traceback
            traceback.print_exc()
        finally:
            conn.close()
            print("✓ 上游连接已关闭")

            # 确保所有数据都被发送出去
            try:
                if hasattr(self.connection, 'shutdown'):
                    self.connection.shutdown(socket.SHUT_WR)
                    time.sleep(0.5)
            except Exception as e:
                print(f"⚠️  关闭写端时出错：{e}")

    def do_GET(self):
        """处理GET请求"""
        request_id = self._get_request_id()
        request_received_time = time.time()

        parsed_path = urlparse(self.path)
        path = parsed_path.path

        headers = dict(self.headers.items())
        api_type = detect_api_type(path)
        log_request_info("GET", path, headers, {}, request_id, api_type)

        # 根路径 - 健康检查
        if path == "/":
            response_data = {
                "status": "ok",
                "message": "OpenClaw Proxy Server is running",
                "real_api_url": REAL_API_URL,
                "session_start": session_start_time.isoformat(),
                "endpoints": {
                    "chat_completions": "/v1/chat/completions",
                    "models": "/v1/models",
                    "metrics": "/metrics",
                    "metrics_summary": "/metrics/summary",
                    "dashboard": "/dashboard"
                }
            }
            self._send_json_response(200, response_data)
            return

        # Dashboard页面（使用绝对路径）
        if path == "/dashboard":
            dashboard_path = SCRIPT_DIR / "dashboard.html"
            try:
                with open(dashboard_path, "r", encoding="utf-8") as f:
                    html_content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', len(html_content.encode('utf-8')))
                self.end_headers()
                self.wfile.write(html_content.encode('utf-8'))
                print(f"✓ Dashboard 已发送: {dashboard_path}")
                return
            except FileNotFoundError:
                error_msg = f"dashboard.html not found at {dashboard_path}"
                print(f"❌ {error_msg}")
                self._send_json_response(404, {"error": error_msg})
                return

        # 静态文件服务（用于 Chart.js 等本地资源）
        if path.startswith("/static/"):
            file_path = path[8:]  # 去掉 /static/ 前缀

            # 安全检查：防止路径遍历攻击
            if ".." in file_path or file_path.startswith("/"):
                self._send_json_response(403, {"error": "Forbidden"})
                return

            # 尝试多个可能的路径（优先使用脚本目录）
            possible_paths = [
                SCRIPT_DIR / "static" / file_path,  # 脚本目录（绝对路径）
                Path("static") / file_path,  # 相对路径
                Path(os.getcwd()) / "static" / file_path,  # 工作目录
            ]

            full_path = None
            for p in possible_paths:
                if p.exists() and full_path is None:
                    full_path = p

            if full_path is None:
                self._send_json_response(404, {"error": f"File not found: {file_path}"})
                return

            try:
                with open(full_path, 'rb') as f:
                    file_content = f.read()

                # 根据文件扩展名设置 Content-Type
                content_type = "application/octet-stream"
                if file_path.endswith(".js"):
                    content_type = "application/javascript; charset=utf-8"
                elif file_path.endswith(".css"):
                    content_type = "text/css; charset=utf-8"
                elif file_path.endswith(".html"):
                    content_type = "text/html; charset=utf-8"
                elif file_path.endswith(".json"):
                    content_type = "application/json; charset=utf-8"
                elif file_path.endswith(".png"):
                    content_type = "image/png"
                elif file_path.endswith(".jpg") or file_path.endswith(".jpeg"):
                    content_type = "image/jpeg"
                elif file_path.endswith(".svg"):
                    content_type = "image/svg+xml"
                elif file_path.endswith(".woff") or file_path.endswith(".woff2"):
                    content_type = "font/woff2"

                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', len(file_content))
                self.send_header('Cache-Control', 'public, max-age=86400')  # 缓存 24 小时
                self.end_headers()
                self.wfile.write(file_content)
                return
            except Exception as e:
                self._send_json_response(500, {"error": f"Error reading file: {str(e)}"})
                return

        # 日志读取接口 - 请求日志
        if path.startswith("/logs/request/"):
            request_id = path.split("/logs/request/")[1]
            file_path = REQUESTS_DIR / f"{request_id}.json"

            if not file_path.exists():
                self._send_json_response(404, {"error": f"Request log not found: {request_id}"})
                return

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    log_data = json.load(f)
                self._send_json_response(200, log_data)
                return
            except Exception as e:
                self._send_json_response(500, {"error": f"Error reading log: {str(e)}"})
                return

        # 日志读取接口 - 响应日志
        if path.startswith("/logs/response/"):
            request_id = path.split("/logs/response/")[1]
            file_path = RESPONSES_DIR / f"{request_id}.json"

            if not file_path.exists():
                self._send_json_response(404, {"error": f"Response log not found: {request_id}"})
                return

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    log_data = json.load(f)
                self._send_json_response(200, log_data)
                return
            except Exception as e:
                self._send_json_response(500, {"error": f"Error reading log: {str(e)}"})
                return

        # Metrics接口
        if path == "/metrics":
            with lock:
                response_data = {
                    "session_start": session_start_time.isoformat(),
                    "request_counter": request_counter,
                    "metrics": list(performance_metrics.get('requests', []))
                }
            self._send_json_response(200, response_data)
            return

        # Metrics summary接口
        if path == "/metrics/summary":
            with lock:
                total = cumulative_stats['total_requests']

                if total == 0:
                    response_data = {
                        "session_start": session_start_time.isoformat(),
                        "total_requests": 0,
                        "avg_total_time": 0,
                        "avg_proxy_processing_time": 0,
                        "avg_model_response_time": 0,
                        "success_requests": 0,
                        "failed_requests": 0,
                        "success_rate": 0,
                        "avg_inter_request_gap": 0,
                        "max_total_time": 0,
                        "min_total_time": 0
                    }
                else:
                    success = cumulative_stats['success_requests']
                    failed = cumulative_stats['failed_requests']
                    success_rate = (success / total * 100) if total > 0 else 0

                    response_data = {
                        "session_start": session_start_time.isoformat(),
                        "total_requests": total,
                        "avg_total_time": cumulative_stats['total_time_sum'] / total if total > 0 else 0,
                        "avg_proxy_processing_time": cumulative_stats['total_proxy_time_sum'] / total if total > 0 else 0,
                        "avg_model_response_time": cumulative_stats['total_model_time_sum'] / total if total > 0 else 0,
                        "success_requests": success,
                        "failed_requests": failed,
                        "success_rate": success_rate,
                        "avg_inter_request_gap": sum(cumulative_stats['inter_request_gaps']) / len(cumulative_stats['inter_request_gaps']) if cumulative_stats['inter_request_gaps'] else 0,
                        "max_total_time": cumulative_stats['max_total_time'],
                        "min_total_time": cumulative_stats['min_total_time'] if cumulative_stats['min_total_time'] != float('inf') else 0
                    }
            self._send_json_response(200, response_data)
            return

        # Models接口 - 转发
        if path == "/v1/models":
            forward_headers = self._prepare_forward_headers("openai")

            try:
                response, response_body = self._do_forward_request("GET", "/models", forward_headers, api_type="openai")

                response_data = json.loads(response_body.decode('utf-8'))
                self._send_json_response(response.status, response_data, dict(response.headers))

                log_response_info(response.status, dict(response.headers), path=path)

            except Exception as e:
                print(f"❌ 转发请求失败：{e}")
                self._send_json_response(502, {"error": str(e)})
            return

        # 404
        self._send_json_response(404, {"error": "Not found"})

    def do_POST(self):
        """处理POST请求"""
        global request_counter, last_request_time

        request_id = self._get_request_id()
        request_received_time = time.time()

        # 计算距上次请求的间隔
        inter_request_gap = None
        if last_request_time is not None:
            inter_request_gap = request_received_time - last_request_time

        last_request_time = request_received_time
        request_counter += 1

        parsed_path = urlparse(self.path)
        path = parsed_path.path

        # 读取请求体
        body_data = self._read_request_body()
        headers = dict(self.headers.items())

        # 检测 API 类型
        api_type = detect_api_type(path)

        log_request_info("POST", path, headers, body_data, request_id, api_type)
        save_request_body(request_id, headers, body_data)

        # Anthropic Messages API 接口 - 直接透传（上游也支持 Anthropic 格式）
        if api_type == "anthropic" and path == "/v1/messages":
            is_stream = body_data.get("stream", False) if isinstance(body_data, dict) else False

            print(f"📨 Anthropic Messages API 请求（流式: {is_stream}）")
            print(f"🔄 直接透传到上游 Anthropic API（不转换格式）")

            # 准备转发给上游的请求头
            forward_headers = self._prepare_forward_headers("anthropic")

            # 获取上游 Anthropic API URL
            api_url = get_api_url("anthropic")
            parsed = urlparse(api_url)
            port = parsed.port if parsed.port else (443 if parsed.scheme == 'https' else 80)

            # 构建路径
            endpoint = '/v1/messages'

            # 对于流式：构建完整路径
            full_path = parsed.path.rstrip('/') + endpoint

            forward_start_time = time.time()
            request_body = json.dumps(body_data).encode('utf-8')

            if is_stream:
                # 流式请求 - 直接转发
                print("🌊 Anthropic 流式请求，直接转发...")
                self._send_stream_response_anthropic(
                    request_id, forward_headers, body_data,
                    parsed, port, full_path, forward_start_time, request_received_time
                )
            else:
                # 非流式请求 - 直接转发

                try:
                    # 传递端点路径，让 _do_forward_request 拼接基础路径
                    response, response_body = self._do_forward_request(
                        "POST", endpoint, forward_headers, request_body, api_type="anthropic"
                    )

                    response_received_time = time.time()

                    # 直接返回上游响应（已经是 Anthropic 格式）
                    try:
                        anthropic_response = json.loads(response_body.decode('utf-8'))
                        save_response_body(request_id, anthropic_response, response.status)

                        # 检测是否有工具调用
                        has_tool_call = detect_tool_call(body_data, anthropic_response)

                        # 提取token使用量（Anthropic格式）
                        input_tokens = 0
                        output_tokens = 0
                        if isinstance(anthropic_response, dict):
                            usage = anthropic_response.get('usage', {})
                            # 兼容OpenAI格式(prompt_tokens/completion_tokens)和Anthropic格式(input_tokens/output_tokens)
                            # 优先尝试prompt_tokens，再尝试input_tokens（因为有些返回input_tokens=0但prompt_tokens有值）
                            input_tokens = usage.get('prompt_tokens') or usage.get('input_tokens', 0)
                            output_tokens = usage.get('completion_tokens') or usage.get('output_tokens', 0)

                        # 保存性能指标
                        metrics = {
                            "request_received_time": request_received_time,
                            "forward_start_time": forward_start_time,
                            "response_received_time": response_received_time,
                            "proxy_processing_time": max(0, forward_start_time - request_received_time),
                            "first_token_latency": 0,  # 标准请求没有首token时延
                            "model_response_time": max(0, response_received_time - forward_start_time),
                            "total_time": max(0, response_received_time - request_received_time),
                            "inter_request_gap": inter_request_gap,
                            "endpoint": "/v1/messages",
                            "method": "POST",
                            "api_type": "anthropic",
                            "stream": False,
                            "status_code": response.status,
                            "has_tool_call": has_tool_call,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens
                        }
                        save_metrics(request_id, metrics)

                        self._send_json_response(response.status, anthropic_response, dict(response.headers))
                        log_response_info(response.status, dict(response.headers), response_body.decode('utf-8'), path="/v1/messages")

                    except json.JSONDecodeError:
                        save_response_body(request_id, response_body.decode('utf-8'), response.status)
                        self._send_json_response(response.status, {"raw_response": response_body.decode('utf-8')})

                except Exception as e:
                    print(f"❌ 转发请求失败：{e}")
                    import traceback
                    traceback.print_exc()
                    self._send_json_response(502, {"error": str(e)})

            return

        # OpenAI Chat completions接口
        if path == "/v1/chat/completions":
            is_stream = body_data.get("stream", False) if isinstance(body_data, dict) else False

            forward_headers = self._prepare_forward_headers("openai")
            forward_start_time = time.time()

            if is_stream:
                # 流式请求
                self._send_stream_response(request_id, forward_headers, body_data, request_received_time, forward_start_time)
            else:
                # 非流式请求
                print("📦 非流式请求模式")

                request_body = json.dumps(body_data).encode('utf-8')

                try:
                    response, response_body = self._do_forward_request(
                        "POST", "/chat/completions", forward_headers, request_body, api_type="openai"
                    )

                    response_received_time = time.time()

                    # 解析响应
                    try:
                        response_json = json.loads(response_body.decode('utf-8'))
                        save_response_body(request_id, response_json, response.status)

                        # 检测是否有工具调用
                        has_tool_call = detect_tool_call(body_data, response_json)

                        # 提取token使用量（OpenAI格式）
                        input_tokens = 0
                        output_tokens = 0
                        if isinstance(response_json, dict):
                            usage = response_json.get('usage', {})
                            # 兼容OpenAI格式(prompt_tokens/completion_tokens)和Anthropic格式(input_tokens/output_tokens)
                            # 使用or运算符优先选择非零值
                            input_tokens = usage.get('prompt_tokens') or usage.get('input_tokens', 0)
                            output_tokens = usage.get('completion_tokens') or usage.get('output_tokens', 0)

                        # 保存性能指标
                        metrics = {
                            "request_received_time": request_received_time,
                            "forward_start_time": forward_start_time,
                            "response_received_time": response_received_time,
                            "proxy_processing_time": max(0, forward_start_time - request_received_time),
                            "first_token_latency": 0,  # 标准请求没有首token时延
                            "model_response_time": max(0, response_received_time - forward_start_time),
                            "total_time": max(0, response_received_time - request_received_time),
                            "inter_request_gap": inter_request_gap,
                            "endpoint": "/v1/chat/completions",
                            "method": "POST",
                            "stream": False,
                            "status_code": response.status,
                            "has_tool_call": has_tool_call,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens
                        }
                        save_metrics(request_id, metrics)

                        self._send_json_response(response.status, response_json, dict(response.headers))
                        log_response_info(response.status, dict(response.headers), response_body.decode('utf-8'), path="/v1/chat/completions")

                    except json.JSONDecodeError:
                        save_response_body(request_id, response_body.decode('utf-8'), response.status)
                        self._send_json_response(response.status, {"raw_response": response_body.decode('utf-8')})

                except Exception as e:
                    print(f"❌ 转发请求失败：{e}")
                    import traceback
                    traceback.print_exc()
                    self._send_json_response(502, {"error": str(e)})
            return

        # 404
        self._send_json_response(404, {"error": "Not found"})

    def do_DELETE(self):
        """处理DELETE请求"""
        request_id = self._get_request_id()

        parsed_path = urlparse(self.path)
        path = parsed_path.path

        headers = dict(self.headers.items())
        api_type = detect_api_type(path)
        log_request_info("DELETE", path, headers, {}, request_id, api_type)

        # 清除metrics
        if path == "/metrics":
            global performance_metrics, request_counter, session_start_time, cumulative_stats
            with lock:
                performance_metrics = defaultdict(list)
                request_counter = 0
                session_start_time = datetime.now()
                # 重置累计统计数据
                cumulative_stats = {
                    'total_requests': 0,
                    'total_time_sum': 0.0,
                    'total_proxy_time_sum': 0.0,
                    'total_model_time_sum': 0.0,
                    'success_requests': 0,
                    'failed_requests': 0,
                    'inter_request_gaps': [],
                    'max_total_time': 0.0,
                    'min_total_time': float('inf')
                }
            self._send_json_response(200, {"status": "ok", "message": "性能数据已清除"})
            return

        self._send_json_response(404, {"error": "Not found"})


def run_server():
    """启动服务器"""
    server_address = (SERVER_HOST, SERVER_PORT)
    httpd = ThreadingHTTPServer(server_address, ProxyHTTPRequestHandler)

    print("\n" + "="*80)
    print("🚀 OpenClaw 代理服务器启动中...")
    print("="*80)
    print(f"📂 脚本目录: {SCRIPT_DIR}")
    print(f"📂 工作目录: {os.getcwd()}")
    print(f"📂 日志目录: {LOGS_DIR}")
    if SCRIPT_DIR != Path(os.getcwd()):
        print(f"\n⚠️  警告: 工作目录与脚本目录不一致")
        print(f"   建议使用: cd {SCRIPT_DIR}")
    print("\n配置说明:")
    print(f"1. OpenAI API 地址：{REAL_API_URL}")
    print(f"2. Anthropic API 地址：{ANTHROPIC_API_URL}")
    print(f"3. 可通过环境变量 REAL_API_URL 和 ANTHROPIC_API_URL 修改")
    print(f"4. 代理监听地址：http://{SERVER_HOST}:{SERVER_PORT}")
    print(f"\n⚠️  重要提示:")
    print(f"  - 代理支持 OpenAI 和 Anthropic 两种 API 格式")
    print(f"  - 自动检测 API 类型并转发到对应的上游")
    print(f"  - 客户端的 Authorization 头会原封转发给真实 API")
    print(f"\n客户端配置:")
    print(f"  - OpenAI 格式: Base URL=http://localhost:{SERVER_PORT}/v1, Endpoint=/chat/completions")
    print(f"  - Anthropic 格式: Base URL=http://localhost:{SERVER_PORT}/v1, Endpoint=/messages")
    print(f"  - API Key: 填写真实 API 的 Key（会通过代理转发）")
    print(f"  - 模型 ID: 使用真实 API 支持的模型")
    print("\n✨ 已支持功能:")
    print("  - ✓ OpenAI API 格式支持（/v1/chat/completions）")
    print("  - ✓ Anthropic API 格式支持（/v1/messages）")
    print("  - ✓ 请求/响应拦截和日志")
    print("  - ✓ 流式和非流式转发")
    print("  - ✓ 请求和响应持久化保存")
    print("  - ✓ 性能监控和分析")
    print(f"  - ✓ 自动清理{LOG_RETENTION_DAYS}天前的旧日志")
    print("\n📁 日志存储位置:")
    print(f"  - 请求体：{REQUESTS_DIR}")
    print(f"  - 响应体：{RESPONSES_DIR}")
    print(f"  - 性能数据：{METRICS_DIR}")
    print(f"\n可用端点:")
    print(f"  - GET  /                       (健康检查)")
    print(f"  - GET  /dashboard              (数据看板)")
    print(f"  - GET  /metrics               (性能数据)")
    print(f"  - GET  /metrics/summary       (性能摘要)")
    print(f"  - DELETE /metrics             (清除性能数据)")
    print(f"\nOpenAI 格式:")
    print(f"  - POST /v1/chat/completions   (聊天补全)")
    print(f"  - GET  /v1/models             (模型列表)")
    print(f"\nAnthropic 格式:")
    print(f"  - POST /v1/messages           (消息 API)")
    print("\n所有请求和响应信息将在此控制台输出")
    print("="*80 + "\n")

    # 启动日志清理后台线程
    def periodic_cleanup():
        """定期清理旧日志的后台任务"""
        import time
        while True:
            try:
                time.sleep(24 * 60 * 60)  # 每24小时执行一次
                print("\n" + "="*80)
                print("🔍 执行定期日志清理...")
                print("="*80)
                cleanup_old_logs(days_to_keep=LOG_RETENTION_DAYS)
            except Exception as e:
                print(f"❌ 定期清理失败: {e}")

    cleanup_thread = threading.Thread(target=periodic_cleanup, daemon=True)
    cleanup_thread.start()
    print("✓ 日志清理后台任务已启动（每24小时执行一次）\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\n服务器已停止")
        httpd.server_close()


if __name__ == "__main__":
    run_server()

"""
流式请求处理器
处理流式HTTP请求和响应
"""
import codecs
import http.client
import json
import ssl
import socket
import time
import traceback
from urllib.parse import urlparse

from backend.config import Config
from backend.services.log_service import LogService
from backend.services.metrics_service import MetricsService
from backend.services.proxy_service import ProxyService
from backend.utils.helpers import get_api_url, detect_tool_call, classify_proxy_exception


class StreamHandler:
    """流式请求处理器"""

    def __init__(self, request_handler, request_id: str, forward_headers: dict,
                 body_data: dict, request_received_time: float, forward_start_time: float,
                 api_type: str, endpoint: str,
                 log_service=None, metrics_service=None, proxy_service=None):
        self.request_handler = request_handler
        self.request_id = request_id
        self.forward_headers = forward_headers
        self.body_data = body_data
        self.request_received_time = request_received_time
        self.forward_start_time = forward_start_time
        self.api_type = api_type
        self.endpoint = endpoint

        # 使用共享的服务实例，如果没有提供则创建新的
        self.log_service = log_service if log_service else LogService()
        self.metrics_service = metrics_service if metrics_service else MetricsService()
        self.proxy_service = proxy_service if proxy_service else ProxyService()

        # 状态变量
        self.chunk_count = 0
        self.total_bytes = 0
        self.response_first_byte_time = None
        self.first_token_time = None
        self.has_first_token = False
        self.stream_complete_time = None
        self.stream_chunks = []
        self.input_tokens = 0
        self.output_tokens = 0
        # SSE 事件累积缓冲区 + 增量解码器：
        # 处理 usage/首token 事件被拆分到多个 TCP chunk 的情况；
        # 增量解码避免多字节 UTF-8 字符跨 chunk 边界时被丢弃
        self._event_buffer = ""
        self._decoder = codecs.getincrementaldecoder('utf-8')('ignore')
        # usage 是否已完整提取（OpenAI: 最终 usage 事件；Anthropic: message_delta）
        self._usage_finalized = False
        # 失败分类信息（None 表示尚未失败）；由内部 catch 设置后由外层统一落库
        self._failure_info = None

    def handle_openai_stream(self):
        """处理OpenAI格式的流式请求"""
        print("\n检测到流式请求 (stream=true)")

        request_body = json.dumps(self.body_data).encode('utf-8')
        target_url = get_api_url("openai")
        parsed = urlparse(target_url)
        port = parsed.port if parsed.port else (443 if parsed.scheme == 'https' else 80)
        
        # 智能构建路径（与 proxy_service.py 保持一致）
        full_path = self._build_stream_path(parsed, "/v1/chat/completions")

        # 发送响应头
        self._send_stream_headers()

        # 创建连接并流式传输
        if parsed.scheme == 'https':
            conn = http.client.HTTPSConnection(
                parsed.hostname, port, timeout=None,
                context=ssl.create_default_context()
            )
        else:
            conn = http.client.HTTPConnection(
                parsed.hostname, port, timeout=None
            )

        try:
            print("建立流式连接：客户端 <-> 代理 <-> 大模型")

            # 发送请求
            conn.request("POST", full_path, body=request_body, headers=self.forward_headers)

            # 获取响应
            response = conn.getresponse()

            if response.status != 200:
                error_msg = response.read().decode('utf-8')
                print(f"上游返回错误状态码：{response.status}")
                self.request_handler.wfile.write(f"data: {json.dumps({'error': error_msg})}\n\n".encode('utf-8'))

                # 上游返回非 200 —— 记录真实上游状态码
                self._save_failed_stream_metrics(
                    response.status,
                    {"error": error_msg, "type": "upstream_error"},
                    failed_at="upstream_status")
                return

            print(f"上游响应状态：{response.status}")

            # 流式读取并转发（内部 catch 会把失败写入 self._failure_info）
            self._stream_openai_response(response)

            # 落库：失败则按分类记录，否则记 200 成功
            if self._failure_info is not None:
                self._save_failed_stream_metrics(
                    self._failure_info["status_code"],
                    {"error": self._failure_info["error"],
                     "type": self._failure_info["type"],
                     "traceback": self._failure_info["traceback"]},
                    failed_at=self._failure_info["failed_at"])
            else:
                # 保存指标（成功情况下status_code为200）
                self._save_stream_metrics(200)

        except Exception as e:
            print(f"\n流式转发异常：{e}")
            traceback.print_exc()

            # 建链/发请求/读状态行阶段异常 —— 按上游通信上下文分类
            status, type_, failed_at = classify_proxy_exception(e, "upstream_connect")
            self._save_failed_stream_metrics(
                status,
                {"error": str(e), "type": type_, "traceback": traceback.format_exc()},
                failed_at=failed_at)
        finally:
            conn.close()
            self._cleanup_connection()

    def handle_anthropic_stream(self):
        """处理Anthropic格式的流式请求"""
        print("\n开始 Anthropic 流式转发（透传模式）")

        request_body = json.dumps(self.body_data).encode('utf-8')
        target_url = get_api_url("anthropic")
        parsed = urlparse(target_url)
        port = parsed.port if parsed.port else (443 if parsed.scheme == 'https' else 80)
        
        # 智能构建路径（与 proxy_service.py 保持一致）
        full_path = self._build_stream_path(parsed, "/v1/messages")

        # 发送响应头
        self._send_stream_headers()

        # 创建连接
        if parsed.scheme == 'https':
            conn = http.client.HTTPSConnection(
                parsed.hostname, port, timeout=None,
                context=ssl.create_default_context()
            )
        else:
            conn = http.client.HTTPConnection(
                parsed.hostname, port, timeout=None
            )

        try:
            print("建立流式连接：客户端 <-> 代理 <-> Anthropic 上游")

            # 发送请求
            conn.request("POST", full_path, body=request_body, headers=self.forward_headers)

            # 获取响应
            response = conn.getresponse()

            if response.status != 200:
                error_msg = response.read().decode('utf-8')
                print(f"上游返回错误状态码：{response.status}")
                self.request_handler.wfile.write(
                    f"event: error\ndata: {json.dumps({'type': 'error', 'error': {'message': error_msg}})}\n\n".encode('utf-8')
                )

                # 上游返回非 200 —— 记录真实上游状态码
                self._save_failed_stream_metrics(
                    response.status,
                    {"error": error_msg, "type": "upstream_error"},
                    failed_at="upstream_status")
                return

            print(f"上游响应状态：{response.status}")

            # 流式读取并转发（内部 catch 会把失败写入 self._failure_info）
            self._stream_anthropic_response(response)

            # 落库：失败则按分类记录，否则记 200 成功
            if self._failure_info is not None:
                self._save_failed_stream_metrics(
                    self._failure_info["status_code"],
                    {"error": self._failure_info["error"],
                     "type": self._failure_info["type"],
                     "traceback": self._failure_info["traceback"]},
                    failed_at=self._failure_info["failed_at"])
            else:
                # 保存指标（成功情况下status_code为200）
                self._save_stream_metrics(200)

        except Exception as e:
            print(f"\nAnthropic 流式转发异常：{e}")
            traceback.print_exc()

            # 建链/发请求/读状态行阶段异常 —— 按上游通信上下文分类
            status, type_, failed_at = classify_proxy_exception(e, "upstream_connect")
            self._save_failed_stream_metrics(
                status,
                {"error": str(e), "type": type_, "traceback": traceback.format_exc()},
                failed_at=failed_at)
        finally:
            conn.close()
            self._cleanup_connection()

    def _send_stream_headers(self):
        """发送流式响应头"""
        self.request_handler.send_response(200)
        self.request_handler.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.request_handler.send_header('Cache-Control', 'no-cache, no-transform')
        self.request_handler.send_header('Connection', 'close')
        self.request_handler.send_header('X-Accel-Buffering', 'no')
        self.request_handler.end_headers()
        print("响应头已发送，开始流式传输...")

    def _stream_openai_response(self, response):
        """流式传输OpenAI响应"""
        try:
            while True:
                chunk = response.read1(4096)
                if not chunk:
                    print(f"\n流结束：上游关闭连接")
                    break

                # 首字节真实到达后才打点（read1 阻塞返回即代表 body 有数据到达）
                if self.response_first_byte_time is None:
                    self.response_first_byte_time = time.time()

                self.chunk_count += 1
                self.total_bytes += len(chunk)

                # 提取usage + 检测首token（跨chunk缓冲，事件被拆分也不漏检）
                if not self.has_first_token or not self._usage_finalized:
                    self._parse_openai_chunk(chunk)

                # 保存chunk数据用于日志记录
                self.stream_chunks.append(chunk.decode('utf-8', errors='ignore'))

                # 转发给客户端（失败时会把分类写入 self._failure_info）
                self._forward_chunk_to_client(chunk)
                if self._failure_info is not None:
                    # 客户端已断开，停止转发
                    break

                # 检测流结束标记
                if b'[DONE]' in chunk:
                    if self.stream_complete_time is None:
                        self.stream_complete_time = time.time()
                        print(f"\n检测到流结束标记 [DONE]")

        except http.client.IncompleteRead as e:
            self._record_failure(e, "upstream_read")
            print(f"\n[{self._failure_info['type']}] 不完整读取：已接收 {getattr(e, 'partial', '?')} 字节")
        except (ConnectionError, http.client.BadStatusLine) as e:
            self._record_failure(e, "upstream_read")
            print(f"\n[{self._failure_info['type']}] 上游读取异常：{e}")
        except (socket.timeout, TimeoutError) as e:
            self._record_failure(e, "upstream_read")
            print(f"\n[{self._failure_info['type']}] 上游读取超时：{e}")

    def _stream_anthropic_response(self, response):
        """流式传输Anthropic响应"""
        try:
            while True:
                chunk = response.read1(4096)
                if not chunk:
                    print(f"\nAnthropic 流结束")
                    break

                # 首字节真实到达后才打点（read1 阻塞返回即代表 body 有数据到达）
                if self.response_first_byte_time is None:
                    self.response_first_byte_time = time.time()

                self.chunk_count += 1
                self.total_bytes += len(chunk)

                # 提取usage + 检测首token（跨chunk缓冲，事件被拆分也不漏检）
                if not self.has_first_token or not self._usage_finalized:
                    self._parse_anthropic_chunk(chunk)

                # 保存chunk数据用于日志记录
                self.stream_chunks.append(chunk.decode('utf-8', errors='ignore'))

                # 检测message_stop事件
                if b'event: message_stop' in chunk:
                    if self.stream_complete_time is None:
                        self.stream_complete_time = time.time()
                        print(f"\n检测到 message_stop 事件")

                # 转发给客户端（失败时会把分类写入 self._failure_info）
                self._forward_chunk_to_client(chunk)
                if self._failure_info is not None:
                    # 客户端已断开，停止转发
                    break

        except http.client.IncompleteRead as e:
            self._record_failure(e, "upstream_read")
            print(f"\n[{self._failure_info['type']}] 不完整读取：已接收 {getattr(e, 'partial', '?')} 字节")
        except (ConnectionError, http.client.BadStatusLine) as e:
            self._record_failure(e, "upstream_read")
            print(f"\n[{self._failure_info['type']}] 上游读取异常：{e}")
        except (socket.timeout, TimeoutError) as e:
            self._record_failure(e, "upstream_read")
            print(f"\n[{self._failure_info['type']}] 上游读取超时：{e}")

    def _drain_complete_events(self, chunk: bytes) -> list:
        """将chunk累积进内部缓冲区，按SSE空行分隔切出完整事件返回

        处理SSE事件被拆分到多个TCP chunk的情况：不完整的事件保留在
        缓冲区中，与后续chunk拼接后再解析，避免跨chunk漏检。
        """
        try:
            self._event_buffer += self._decoder.decode(chunk)
        except Exception:
            return []

        events = []
        while '\n\n' in self._event_buffer:
            event_text, self._event_buffer = self._event_buffer.split('\n\n', 1)
            if event_text.strip():
                events.append(event_text)
        return events

    def _parse_openai_chunk(self, chunk: bytes):
        """从OpenAI chunk中提取usage并检测首token（跨chunk缓冲）"""
        for event_text in self._drain_complete_events(chunk):
            for line in event_text.split('\n'):
                line = line.strip()
                if not line.startswith('data:'):
                    continue

                data_str = line[5:].strip()
                if not data_str or data_str == '[DONE]':
                    continue

                try:
                    data = json.loads(data_str)
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue

                # 提取usage信息（通常在最后一个事件；中间事件usage可能为null）
                if not self._usage_finalized:
                    usage = data.get('usage')
                    if isinstance(usage, dict) and usage:
                        self.input_tokens = usage.get('prompt_tokens') or usage.get('input_tokens', 0)
                        self.output_tokens = usage.get('completion_tokens') or usage.get('output_tokens', 0)
                        self._usage_finalized = True
                        print(f"\n检测到token使用: 输入={self.input_tokens}, 输出={self.output_tokens}")

                # 检测首token
                if not self.has_first_token:
                    for choice in data.get('choices', []):
                        delta = choice.get('delta', {})
                        if delta.get('content'):
                            self.first_token_time = time.time()
                            self.has_first_token = True
                            print(f"\n首token延迟: {(self.first_token_time - self.forward_start_time)*1000:.2f}ms")
                            break

    @staticmethod
    def _sum_anthropic_input_tokens(usage: dict, fallback: int) -> int:
        """计算Anthropic输入token总数 = input_tokens + 缓存写入 + 缓存读取

        usage中的 input_tokens 只统计未命中缓存的部分，agent 的预置系统提示词
        通常走 cache_creation_input_tokens / cache_read_input_tokens，
        三项相加才是模型实际接收的完整上下文。
        若 usage 中没有任何输入侧字段（如标准 message_delta 只带 output_tokens），
        保留 fallback（已有值）。多个事件都上报时取最大值，防止被不完整值覆盖。
        """
        base = usage.get('input_tokens') or 0
        cache_write = usage.get('cache_creation_input_tokens') or 0
        cache_read = usage.get('cache_read_input_tokens') or 0
        total = base + cache_write + cache_read
        if total == 0:
            return fallback
        return max(total, fallback)

    def _parse_anthropic_chunk(self, chunk: bytes):
        """从Anthropic chunk中提取usage并检测首token（跨chunk缓冲）

        usage分布：input_tokens 在 message_start 事件（嵌套于 message.usage），
        最终的 output_tokens 在 message_delta 事件。
        """
        for event_text in self._drain_complete_events(chunk):
            if 'event: ping' in event_text:
                continue

            current_event = None
            for line in event_text.split('\n'):
                line = line.strip()
                if line.startswith('event:'):
                    current_event = line[6:].strip()
                    continue
                if not line.startswith('data:'):
                    continue

                data_str = line[5:].strip()
                if not data_str:
                    continue

                try:
                    data = json.loads(data_str)
                except (json.JSONDecodeError, TypeError):
                    continue

                # 提取usage信息
                if not self._usage_finalized:
                    if current_event == 'message_start':
                        usage = data.get('message', {}).get('usage') or {}
                        if usage:
                            self.input_tokens = self._sum_anthropic_input_tokens(usage, self.input_tokens)
                            print(f"\n检测到token使用(message_start): 输入={self.input_tokens}")
                    elif current_event == 'message_delta' and isinstance(data.get('usage'), dict):
                        usage = data['usage']
                        self.input_tokens = self._sum_anthropic_input_tokens(usage, self.input_tokens)
                        self.output_tokens = usage.get('output_tokens', self.output_tokens)
                        self._usage_finalized = True
                        print(f"\n检测到token使用(message_delta): 输入={self.input_tokens}, 输出={self.output_tokens}")

                # 检测首token
                if not self.has_first_token and current_event == 'content_block_delta':
                    delta = data.get('delta', {})
                    if (delta.get('type') == 'text_delta' and delta.get('text', '')) or \
                       (delta.get('type') == 'thinking_delta' and delta.get('thinking', '')):
                        self.first_token_time = time.time()
                        self.has_first_token = True
                        print(f"\n首token延迟: {(self.first_token_time - self.forward_start_time)*1000:.2f}ms")

    def _forward_chunk_to_client(self, chunk: bytes):
        """转发数据块给客户端"""
        try:
            if hasattr(self.request_handler, 'connection'):
                self.request_handler.connection.sendall(chunk)
            else:
                self.request_handler.wfile.write(chunk)
                self.request_handler.wfile.flush()

            print(f"转发数据块 #{self.chunk_count}: {len(chunk)} bytes (累计: {self.total_bytes} bytes)")
        except (ConnectionError, socket.timeout, TimeoutError) as e:
            # 客户端断开：覆盖 ConnectionAbortedError / ConnectionResetError / BrokenPipeError / 超时
            self._record_failure(e, "client_write")
            print(f"\n[{self._failure_info['type']}] 客户端断开连接：{e}")

    def _record_failure(self, e: BaseException, context: str):
        """分类并记录失败信息到 self._failure_info（不落库，由外层统一落库）"""
        status, type_, failed_at = classify_proxy_exception(e, context)
        self._failure_info = {
            "status_code": status,
            "type": type_,
            "failed_at": failed_at,
            "error": str(e),
            "traceback": traceback.format_exc()
        }

    def _save_stream_metrics(self, status_code: int = 200):
        """保存流式性能指标"""
        if self.stream_complete_time is None:
            self.stream_complete_time = time.time()

        # 检测是否有工具调用
        has_tool_call = detect_tool_call(self.body_data, {})

        # 如果流中没有提取到token，尝试从请求体中获取输入token
        if self.input_tokens == 0 and isinstance(self.body_data, dict):
            # 某些API会在请求中提供输入token
            pass  # 保持为0，因为请求体通常不包含准确token数

        metrics = {
            "request_received_time": self.request_received_time,
            "forward_start_time": self.forward_start_time,
            "response_first_byte_time": self.response_first_byte_time,
            "response_complete_time": self.stream_complete_time,
            "proxy_processing_time": max(0, self.forward_start_time - self.request_received_time),
            "time_to_first_byte": max(0, (self.response_first_byte_time - self.forward_start_time) if self.response_first_byte_time else 0),
            "first_token_latency": max(0, (self.first_token_time - self.forward_start_time) if self.first_token_time else 0),
            "model_response_time": max(0, self.stream_complete_time - self.forward_start_time),
            "total_stream_time": max(0, self.stream_complete_time - self.forward_start_time),
            "total_time": max(0, self.stream_complete_time - self.request_received_time),
            "endpoint": self.endpoint,
            "method": "POST",
            "api_type": self.api_type,
            "stream": True,
            "status_code": status_code,
            "has_tool_call": has_tool_call,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens
        }

        self.metrics_service.save_metrics(self.request_id, metrics)

        # 保存响应数据
        response_data = {
            "stream": True,
            "status_code": status_code,
            "total_chunks": self.chunk_count,
            "total_bytes": self.total_bytes,
            "timestamp": time.time(),
            "chunks": self.stream_chunks
        }
        self.log_service.save_response_log(self.request_id, response_data, status_code)

        print(f"\n已保存流式响应: {self.chunk_count} 个数据块，总大小 {self.total_bytes} 字节")
        print(f"Token统计: 输入={self.input_tokens}, 输出={self.output_tokens}")
        print("\n" + "="*80)
        if status_code == 200:
            print(f"流式转发完成")
        else:
            print(f"流式请求失败 (状态码: {status_code})")
        print(f"   总数据块：{self.chunk_count}")
        print(f"   总字节数：{self.total_bytes}")
        print("="*80 + "\n")

    def _save_failed_stream_metrics(self, status_code: int, error_data: dict, failed_at: str = "stream_setup"):
        """保存失败的流式请求指标"""
        response_complete_time = time.time()

        metrics = {
            "request_received_time": self.request_received_time,
            "forward_start_time": self.forward_start_time,
            "response_first_byte_time": None,
            "response_complete_time": response_complete_time,
            "proxy_processing_time": max(0, self.forward_start_time - self.request_received_time),
            "time_to_first_byte": 0,
            "first_token_latency": 0,
            "model_response_time": 0,
            "total_stream_time": 0,
            "total_time": max(0, response_complete_time - self.request_received_time),
            "endpoint": self.endpoint,
            "method": "POST",
            "api_type": self.api_type,
            "stream": True,
            "status_code": status_code,
            "has_tool_call": False,
            "input_tokens": 0,
            "output_tokens": 0
        }

        self.metrics_service.save_metrics(self.request_id, metrics)

        # 保存错误响应数据
        response_data = {
            "stream": True,
            "status_code": status_code,
            "error": error_data,
            "timestamp": time.time(),
            "failed_at": failed_at
        }
        self.log_service.save_response_log(self.request_id, response_data, status_code)

        print(f"\n已保存失败的流式请求 (状态码: {status_code})")
        print(f"   错误类型: {error_data.get('type', 'unknown')}")
        print("="*80 + "\n")

    def _cleanup_connection(self):
        """清理连接"""
        print("上游连接已关闭")
        print(f"总计发送 {self.total_bytes} 字节给客户端")

        try:
            if hasattr(self.request_handler.connection, 'shutdown'):
                self.request_handler.connection.shutdown(socket.SHUT_WR)
                print("已关闭连接写端，发送 EOF 给客户端")
                time.sleep(0.5)
        except Exception as e:
            print(f"关闭写端时出错：{e}")

    def _build_stream_path(self, parsed, endpoint_path: str) -> str:
        """智能构建流式请求路径（与 proxy_service.py 保持一致）"""
        import re
        base_path = parsed.path.rstrip("/")

        # 情况1: base_path 已包含完整 endpoint
        if base_path.endswith('/chat/completions') and endpoint_path == '/v1/chat/completions':
            return base_path
        elif base_path.endswith('/v1/messages') and endpoint_path == '/v1/messages':
            return base_path

        # 情况2: base_path 以版本号结尾，去掉 endpoint 的 /v1 前缀
        if re.search(r'(/v\d+|/api/paas/v\d+)$', base_path) and endpoint_path.startswith('/v1'):
            endpoint_path = endpoint_path[3:]  # 去掉 "/v1"

        full_path = base_path + endpoint_path
        if not full_path.startswith('/'):
            full_path = '/' + full_path

        if parsed.query:
            full_path += "?" + parsed.query

        return full_path
"""
流式请求处理器
处理流式HTTP请求和响应
"""
import http.client
import json
import ssl
import socket
import time
from urllib.parse import urlparse

from backend.config import Config
from backend.services.log_service import LogService
from backend.services.metrics_service import MetricsService
from backend.services.proxy_service import ProxyService
from backend.utils.helpers import get_api_url, detect_tool_call


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
        self.usage_buffer = ""  # 用于收集usage信息的buffer

    def handle_openai_stream(self):
        """处理OpenAI格式的流式请求"""
        print("\n🌊 检测到流式请求 (stream=true)")

        request_body = json.dumps(self.body_data).encode('utf-8')
        target_url = get_api_url("openai")
        parsed = urlparse(target_url)
        port = parsed.port if parsed.port else (443 if parsed.scheme == 'https' else 80)
        full_path = parsed.path.rstrip('/') + '/chat/completions'

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
            print("🔗 建立流式连接：客户端 ↔ 代理 ↔ 大模型")

            # 发送请求
            conn.request("POST", full_path, body=request_body, headers=self.forward_headers)

            # 获取响应
            response = conn.getresponse()

            if response.status != 200:
                error_msg = response.read().decode('utf-8')
                print(f"❌ 上游返回错误状态码：{response.status}")
                self.request_handler.wfile.write(f"data: {json.dumps({'error': error_msg})}\n\n".encode('utf-8'))

                # 记录失败的流式请求
                self._save_failed_stream_metrics(response.status, {"error": error_msg, "type": "upstream_error"})
                return

            print(f"✅ 上游响应状态：{response.status}")

            # 流式读取并转发
            self._stream_openai_response(response)

            # 保存指标（成功情况下status_code为200）
            self._save_stream_metrics(200)

        except Exception as e:
            print(f"\n❌ 流式转发异常：{e}")
            import traceback
            traceback.print_exc()

            # 记录异常失败的流式请求
            self._save_failed_stream_metrics(502, {"error": str(e), "type": "proxy_exception", "traceback": traceback.format_exc()})
        finally:
            conn.close()
            self._cleanup_connection()

    def handle_anthropic_stream(self):
        """处理Anthropic格式的流式请求"""
        print("\n🌊 开始 Anthropic 流式转发（透传模式）")

        request_body = json.dumps(self.body_data).encode('utf-8')
        target_url = get_api_url("anthropic")
        parsed = urlparse(target_url)
        port = parsed.port if parsed.port else (443 if parsed.scheme == 'https' else 80)
        full_path = parsed.path.rstrip('/') + '/v1/messages'

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
            print("🔗 建立流式连接：客户端 ↔ 代理 ↔ Anthropic 上游")

            # 发送请求
            conn.request("POST", full_path, body=request_body, headers=self.forward_headers)

            # 获取响应
            response = conn.getresponse()

            if response.status != 200:
                error_msg = response.read().decode('utf-8')
                print(f"❌ 上游返回错误状态码：{response.status}")
                self.request_handler.wfile.write(
                    f"event: error\ndata: {json.dumps({'type': 'error', 'error': {'message': error_msg}})}\n\n".encode('utf-8')
                )

                # 记录失败的流式请求
                self._save_failed_stream_metrics(response.status, {"error": error_msg, "type": "upstream_error"})
                return

            print(f"✅ 上游响应状态：{response.status}")

            # 流式读取并转发
            self._stream_anthropic_response(response)

            # 保存指标（成功情况下status_code为200）
            self._save_stream_metrics(200)

        except Exception as e:
            print(f"\n❌ Anthropic 流式转发异常：{e}")
            import traceback
            traceback.print_exc()

            # 记录异常失败的流式请求
            self._save_failed_stream_metrics(502, {"error": str(e), "type": "proxy_exception", "traceback": traceback.format_exc()})
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
        print("✓ 响应头已发送，开始流式传输...")

    def _stream_openai_response(self, response):
        """流式传输OpenAI响应"""
        ft_buffer = ""

        try:
            while True:
                if self.response_first_byte_time is None:
                    self.response_first_byte_time = time.time()

                chunk = response.read1(4096)
                if not chunk:
                    print(f"\n📦 流结束：上游关闭连接")
                    break

                self.chunk_count += 1
                self.total_bytes += len(chunk)

                # 尝试从chunk中提取usage信息（每个chunk都检查）
                if self.input_tokens == 0 or self.output_tokens == 0:
                    self._extract_usage_from_openai_chunk(chunk)

                # 检测首token
                if not self.has_first_token:
                    self._detect_first_token_openai(chunk, ft_buffer)
                    ft_buffer = ""

                # 保存chunk数据用于日志记录
                self.stream_chunks.append(chunk.decode('utf-8', errors='ignore'))

                # 转发给客户端
                self._forward_chunk_to_client(chunk)

                # 检测流结束标记
                if b'[DONE]' in chunk:
                    if self.stream_complete_time is None:
                        self.stream_complete_time = time.time()
                        print(f"\n📦 检测到流结束标记 [DONE]")

        except http.client.IncompleteRead as e:
            print(f"\n⚠️  不完整读取：已接收 {e.partial} 字节")
        except (ConnectionResetError, BrokenPipeError) as e:
            print(f"\n⚠️  客户端连接中断：{e}")

    def _stream_anthropic_response(self, response):
        """流式传输Anthropic响应"""
        ft_buffer = ""

        try:
            while True:
                if self.response_first_byte_time is None:
                    self.response_first_byte_time = time.time()

                chunk = response.read1(4096)
                if not chunk:
                    print(f"\n📦 Anthropic 流结束")
                    break

                self.chunk_count += 1
                self.total_bytes += len(chunk)

                # 尝试从chunk中提取usage信息（每个chunk都检查）
                if self.input_tokens == 0 or self.output_tokens == 0:
                    self._extract_usage_from_anthropic_chunk(chunk)

                # 检测首token
                if not self.has_first_token:
                    self._detect_first_token_anthropic(chunk, ft_buffer)
                    ft_buffer = ""

                # 保存chunk数据用于日志记录
                self.stream_chunks.append(chunk.decode('utf-8', errors='ignore'))

                # 检测message_stop事件
                if b'event: message_stop' in chunk:
                    if self.stream_complete_time is None:
                        self.stream_complete_time = time.time()
                        print(f"\n📦 检测到 message_stop 事件")

                # 转发给客户端
                self._forward_chunk_to_client(chunk)

        except Exception as e:
            print(f"\n❌ 流式读取异常：{e}")

    def _extract_usage_from_openai_chunk(self, chunk: bytes):
        """从OpenAI chunk中提取usage信息"""
        try:
            chunk_str = chunk.decode('utf-8', errors='ignore')
            lines = chunk_str.split('\n')

            for line in lines:
                line = line.strip()
                if not line.startswith('data:'):
                    continue

                data_str = line[5:].strip()
                if not data_str or data_str == '[DONE]':
                    continue

                try:
                    data = json.loads(data_str)
                    # 提取usage信息（通常在最后一个chunk中）
                    if 'usage' in data:
                        usage = data.get('usage', {})
                        self.input_tokens = usage.get('prompt_tokens', 0)
                        self.output_tokens = usage.get('completion_tokens', 0)
                        print(f"\n✓ 检测到token使用: 输入={self.input_tokens}, 输出={self.output_tokens}")
                        return True  # 成功提取usage
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
        except Exception:
            pass
        return False

    def _detect_first_token_openai(self, chunk: bytes, buffer: str):
        """检测OpenAI格式的首token"""
        try:
            chunk_str = chunk.decode('utf-8', errors='ignore')
            buffer += chunk_str.replace('\r\n', '\n')

            while '\n\n' in buffer:
                event_text, buffer = buffer.split('\n\n', 1)
                if '[DONE]' in event_text or 'event: ping' in event_text:
                    continue

                for line in event_text.split('\n'):
                    line = line.strip()
                    if not line.startswith('data:'):
                        continue

                    data_str = line[5:].strip()
                    if not data_str or data_str == '[DONE]':
                        continue

                    try:
                        data = json.loads(data_str)
                        # 检测首token
                        for choice in data.get('choices', []):
                            delta = choice.get('delta', {})
                            content = delta.get('content', '')
                            if content:
                                self.first_token_time = time.time()
                                self.has_first_token = True
                                print(f"\n✓ 首token延迟: {(self.first_token_time - self.forward_start_time)*1000:.2f}ms")
                                return
                    except (json.JSONDecodeError, KeyError, TypeError):
                        pass

        except Exception:
            pass

    def _extract_usage_from_anthropic_chunk(self, chunk: bytes):
        """从Anthropic chunk中提取usage信息"""
        try:
            chunk_str = chunk.decode('utf-8', errors='ignore')
            lines = chunk_str.split('\n')

            current_event = None
            for line in lines:
                line = line.strip()
                if line.startswith('event:'):
                    current_event = line[6:].strip()
                elif line.startswith('data:'):
                    data_str = line[5:].strip()
                    if not data_str:
                        continue

                    try:
                        data = json.loads(data_str)
                        # 提取usage信息（通常在message_delta事件中）
                        if current_event == 'message_delta' and 'usage' in data:
                            usage = data.get('usage', {})
                            self.input_tokens = usage.get('input_tokens', 0)
                            self.output_tokens = usage.get('output_tokens', 0)
                            print(f"\n✓ 检测到token使用: 输入={self.input_tokens}, 输出={self.output_tokens}")
                            return True  # 成功提取usage
                    except (json.JSONDecodeError, TypeError):
                        pass
        except Exception:
            pass
        return False

    def _detect_first_token_anthropic(self, chunk: bytes, buffer: str):
        """检测Anthropic格式的首token"""
        try:
            chunk_str = chunk.decode('utf-8', errors='ignore')
            buffer += chunk_str.replace('\r\n', '\n')

            while '\n\n' in buffer:
                event_text, buffer = buffer.split('\n\n', 1)
                if 'event: message_stop' in event_text or 'event: ping' in event_text:
                    continue

                current_event = None
                for line in event_text.split('\n'):
                    line = line.strip()
                    if line.startswith('event:'):
                        current_event = line[6:].strip()
                    elif line.startswith('data:'):
                        data_str = line[5:].strip()
                        if not data_str:
                            continue

                        try:
                            data = json.loads(data_str)
                            # 检测首token
                            if current_event == 'content_block_delta':
                                delta = data.get('delta', {})
                                if (delta.get('type') == 'text_delta' and delta.get('text', '')) or \
                                   (delta.get('type') == 'thinking_delta' and delta.get('thinking', '')):
                                    self.first_token_time = time.time()
                                    self.has_first_token = True
                                    print(f"\n✓ 首token延迟: {(self.first_token_time - self.forward_start_time)*1000:.2f}ms")
                                    return
                        except (json.JSONDecodeError, TypeError):
                            pass

        except Exception:
            pass

    def _forward_chunk_to_client(self, chunk: bytes):
        """转发数据块给客户端"""
        try:
            if hasattr(self.request_handler, 'connection'):
                self.request_handler.connection.sendall(chunk)
            else:
                self.request_handler.wfile.write(chunk)
                self.request_handler.wfile.flush()

            print(f"✓ 转发数据块 #{self.chunk_count}: {len(chunk)} bytes (累计: {self.total_bytes} bytes)")
        except (ConnectionResetError, BrokenPipeError) as e:
            print(f"\n⚠️  客户端连接中断：{e}")
            raise

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

        print(f"\n📁 已保存流式响应: {self.chunk_count} 个数据块，总大小 {self.total_bytes} 字节")
        print(f"📊 Token统计: 输入={self.input_tokens}, 输出={self.output_tokens}")
        print("\n" + "="*80)
        if status_code == 200:
            print(f"✅ 流式转发完成")
        else:
            print(f"❌ 流式请求失败 (状态码: {status_code})")
        print(f"   总数据块：{self.chunk_count}")
        print(f"   总字节数：{self.total_bytes}")
        print("="*80 + "\n")

    def _save_failed_stream_metrics(self, status_code: int, error_data: dict):
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
            "failed_at": "stream_setup"
        }
        self.log_service.save_response_log(self.request_id, response_data, status_code)

        print(f"\n📁 已保存失败的流式请求 (状态码: {status_code})")
        print(f"   错误类型: {error_data.get('type', 'unknown')}")
        print("="*80 + "\n")

    def _cleanup_connection(self):
        """清理连接"""
        print("✓ 上游连接已关闭")
        print(f"✓ 总计发送 {self.total_bytes} 字节给客户端")

        try:
            if hasattr(self.request_handler.connection, 'shutdown'):
                self.request_handler.connection.shutdown(socket.SHUT_WR)
                print("✓ 已关闭连接写端，发送 EOF 给客户端")
                time.sleep(0.5)
        except Exception as e:
            print(f"⚠️  关闭写端时出错：{e}")
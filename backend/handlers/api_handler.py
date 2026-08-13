"""
API请求处理器
处理所有HTTP API请求
"""
import json
import time
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.config import Config
from backend.handlers.base import BaseAPIHandler
from backend.services.log_service import LogService
from backend.services.metrics_service import MetricsService
from backend.services.proxy_service import ProxyService
from backend.services.trace_service import TraceService
from backend.utils.logger import log_request_info, log_response_info
from backend.utils.helpers import detect_api_type, get_api_url, detect_tool_call, classify_proxy_exception


# 全局服务实例
log_service = LogService()
metrics_service = MetricsService()
proxy_service = ProxyService()
trace_service = TraceService()

# 全局状态
session_start_time = datetime.now()
last_request_time = None
request_counter = 0
lock = threading.Lock()


class APIHandler(BaseAPIHandler):
    """API请求处理器"""

    def do_GET(self):
        """处理GET请求"""
        from urllib.parse import urlparse

        request_id = self._get_request_id()
        request_received_time = time.time()

        parsed_path = urlparse(self.path)
        path = parsed_path.path

        headers = dict(self.headers.items())
        api_type = detect_api_type(path)
        log_request_info("GET", path, headers, {}, request_id, api_type)

        # 路由分发
        if path == "/":
            self._handle_health_check()
        elif path == "/dashboard":
            self._handle_dashboard()
        elif path.startswith("/static/"):
            self._handle_static_file(path)
        elif path.startswith("/logs/request/"):
            self._handle_request_log(path)
        elif path.startswith("/logs/response/"):
            self._handle_response_log(path)
        elif path == "/metrics":
            self._handle_get_metrics()
        elif path == "/metrics/summary":
            self._handle_get_metrics_summary()
        elif path == "/traces":
            self._handle_get_traces()
        elif path.startswith("/traces/"):
            self._handle_get_trace(path)
        elif path == "/v1/models":
            self._handle_models_forward(headers)
        else:
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

        from urllib.parse import urlparse
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        # 读取请求体
        body_data = self._read_request_body()
        headers = dict(self.headers.items())

        # 检测 API 类型
        api_type = detect_api_type(path)

        log_request_info("POST", path, headers, body_data, request_id, api_type)
        log_service.save_request_log(request_id, headers, body_data)

        # 路由分发
        if path == "/v1/chat/completions":
            self._handle_chat_completions(request_id, headers, body_data,
                                         request_received_time, inter_request_gap)
        elif path == "/v1/messages":
            self._handle_anthropic_messages(request_id, headers, body_data,
                                           request_received_time, inter_request_gap)
        elif path == "/traces":
            self._handle_save_trace(body_data)
        else:
            self._send_json_response(404, {"error": "Not found"})

    def do_DELETE(self):
        """处理DELETE请求"""
        request_id = self._get_request_id()

        from urllib.parse import urlparse
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        headers = dict(self.headers.items())
        api_type = detect_api_type(path)
        log_request_info("DELETE", path, headers, {}, request_id, api_type)

        if path == "/metrics":
            self._handle_clear_metrics()
        elif path == "/traces":
            self._handle_clear_traces()
        else:
            self._send_json_response(404, {"error": "Not found"})

    def _handle_health_check(self):
        """处理健康检查"""
        response_data = {
            "status": "ok",
            "message": "OpenClaw Proxy Server is running",
            "real_api_url": Config.REAL_API_URL,
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

    def _handle_dashboard(self):
        """处理Dashboard页面"""
        dashboard_path = Config.SCRIPT_DIR / "frontend" / "index.html"
        try:
            with open(dashboard_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            self._send_html_response(html_content)
            print(f"✓ Dashboard 已发送: {dashboard_path}")
        except FileNotFoundError:
            error_msg = f"index.html not found at {dashboard_path}"
            print(f"❌ {error_msg}")
            self._send_json_response(404, {"error": error_msg})

    def _handle_static_file(self, path: str):
        """处理静态文件请求"""
        file_path = path[8:]  # 去掉 /static/ 前缀

        # 安全检查
        if ".." in file_path or file_path.startswith("/"):
            self._send_json_response(403, {"error": "Forbidden"})
            return

        # 尝试多个可能的路径（优先frontend/static/）
        possible_paths = [
            Config.SCRIPT_DIR / "frontend" / "static" / file_path,
            Config.SCRIPT_DIR / "frontend" / "assets" / file_path,
        ]

        full_path = None
        for p in possible_paths:
            if p.exists():
                full_path = p
                break

        if full_path is None:
            self._send_json_response(404, {"error": f"File not found: {file_path}"})
            return

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

        self._send_file_response(str(full_path), content_type)

    def _handle_request_log(self, path: str):
        """处理请求日志获取"""
        request_id = path.split("/logs/request/")[1]
        log_data = log_service.get_request_log(request_id)
        if log_data is None:
            self._send_json_response(404, {"error": f"Request log not found: {request_id}"})
        else:
            self._send_json_response(200, log_data)

    def _handle_response_log(self, path: str):
        """处理响应日志获取"""
        request_id = path.split("/logs/response/")[1]
        log_data = log_service.get_response_log(request_id)
        if log_data is None:
            self._send_json_response(404, {"error": f"Response log not found: {request_id}"})
        else:
            self._send_json_response(200, log_data)

    def _handle_get_metrics(self):
        """处理获取指标"""
        with lock:
            response_data = {
                "session_start": session_start_time.isoformat(),
                "request_counter": request_counter,
                "metrics": metrics_service.get_recent_metrics()
            }
        self._send_json_response(200, response_data)

    def _handle_get_metrics_summary(self):
        """处理获取指标摘要"""
        with lock:
            response_data = {
                "session_start": session_start_time.isoformat(),
                **metrics_service.get_summary_stats()
            }
        self._send_json_response(200, response_data)

    def _handle_clear_metrics(self):
        """处理清除指标"""
        global request_counter, session_start_time
        with lock:
            metrics_service.clear_metrics()
            request_counter = 0
            session_start_time = datetime.now()
        self._send_json_response(200, {"status": "ok", "message": "性能数据已清除"})

    def _handle_save_trace(self, body_data):
        """POST /traces - 保存一条追踪记录"""
        if not isinstance(body_data, dict):
            self._send_json_response(400, {"error": "Request body must be a JSON object"})
            return
        if 'steps' not in body_data or not isinstance(body_data['steps'], list):
            self._send_json_response(400, {"error": "'steps' must be a non-empty array"})
            return
        storage_id = trace_service.save_trace(body_data)
        self._send_json_response(201, {"status": "ok", "storage_id": storage_id})

    def _handle_get_traces(self):
        """GET /traces - 获取所有追踪记录列表"""
        traces = trace_service.get_traces()
        self._send_json_response(200, {"traces": traces, "total": len(traces)})

    def _handle_get_trace(self, path):
        """GET /traces/<id> - 获取单条追踪记录"""
        storage_id = path.split("/traces/")[1]
        trace = trace_service.get_trace(storage_id)
        if trace is None:
            self._send_json_response(404, {"error": f"Trace not found: {storage_id}"})
        else:
            self._send_json_response(200, trace)

    def _handle_clear_traces(self):
        """DELETE /traces - 清空所有追踪记录"""
        trace_service.clear_traces()
        self._send_json_response(200, {"status": "ok", "message": "追踪数据已清除"})

    def _handle_models_forward(self, headers: dict):
        """处理模型列表转发"""
        try:
            forward_headers = proxy_service.prepare_forward_headers(headers, "openai")
            response, response_body = proxy_service.forward_request("GET", "/models", forward_headers, api_type="openai")

            response_data = json.loads(response_body.decode('utf-8'))
            self._send_json_response(response.status, response_data, dict(response.headers))
            log_response_info(response.status, dict(response.headers), path="/v1/models")

        except Exception as e:
            print(f"❌ 转发请求失败：{e}")
            status, type_, failed_at = classify_proxy_exception(e, "upstream_connect")
            self._send_json_response(status, {"error": str(e), "type": type_, "failed_at": failed_at})

    def _handle_chat_completions(self, request_id: str, headers: dict, body_data: dict,
                                request_received_time: float, inter_request_gap: Optional[float]):
        """处理OpenAI聊天补全请求"""
        from backend.services.stream_handler import StreamHandler

        is_stream = body_data.get("stream", False) if isinstance(body_data, dict) else False
        print(f"🔍 检测到stream参数: {is_stream}")  # 调试信息

        forward_headers = proxy_service.prepare_forward_headers(headers, "openai")
        forward_start_time = time.time()

        if is_stream:
            # 流式请求
            print(f"🌊 路由到流式处理器: {request_id}")  # 调试信息
            stream_handler = StreamHandler(self, request_id, forward_headers, body_data,
                                          request_received_time, forward_start_time,
                                          "openai", "/v1/chat/completions",
                                          log_service, metrics_service, proxy_service)
            stream_handler.handle_openai_stream()
        else:
            # 非流式请求
            print(f"📦 路由到标准处理器: {request_id}")  # 调试信息
            self._handle_standard_request(request_id, forward_headers, body_data,
                                        request_received_time, forward_start_time,
                                        inter_request_gap, "/v1/chat/completions", "openai", is_stream=False)

    def _handle_anthropic_messages(self, request_id: str, headers: dict, body_data: dict,
                                  request_received_time: float, inter_request_gap: Optional[float]):
        """处理Anthropic消息请求"""
        from backend.services.stream_handler import StreamHandler

        is_stream = body_data.get("stream", False) if isinstance(body_data, dict) else False
        forward_headers = proxy_service.prepare_forward_headers(headers, "anthropic")
        forward_start_time = time.time()

        if is_stream:
            # 流式请求
            stream_handler = StreamHandler(self, request_id, forward_headers, body_data,
                                          request_received_time, forward_start_time,
                                          "anthropic", "/v1/messages",
                                          log_service, metrics_service, proxy_service)
            stream_handler.handle_anthropic_stream()
        else:
            # 非流式请求
            self._handle_standard_request(request_id, forward_headers, body_data,
                                        request_received_time, forward_start_time,
                                        inter_request_gap, "/v1/messages", "anthropic", is_stream=False)

    def _handle_standard_request(self, request_id: str, forward_headers: dict, body_data: dict,
                               request_received_time: float, forward_start_time: float,
                               inter_request_gap: Optional[float], endpoint: str, api_type: str, is_stream: bool = False):
        """处理标准请求"""
        try:
            request_body = json.dumps(body_data).encode('utf-8')

            # 发送请求
            response, response_body = proxy_service.forward_request(
                "POST", endpoint, forward_headers, request_body, api_type=api_type
            )

            response_received_time = time.time()

            # 解析响应
            try:
                response_json = json.loads(response_body.decode('utf-8'))
                log_service.save_response_log(request_id, response_json, response.status)

                # 检测是否有工具调用
                has_tool_call = detect_tool_call(body_data, response_json)

                # 提取token使用量
                input_tokens, output_tokens = proxy_service.extract_token_usage(response_json, body_data)

                # 保存性能指标
                metrics = proxy_service.calculate_metrics(
                    request_received_time, forward_start_time, response_received_time,
                    inter_request_gap, response.status, has_tool_call,
                    input_tokens, output_tokens, endpoint, "POST", api_type, is_stream
                )
                metrics_service.save_metrics(request_id, metrics)

                self._send_json_response(response.status, response_json, dict(response.headers))
                log_response_info(response.status, dict(response.headers), response_body.decode('utf-8'), path=endpoint)

            except json.JSONDecodeError:
                log_service.save_response_log(request_id, response_body.decode('utf-8'), response.status)

                # 即使JSON解析失败，也要记录指标
                metrics = proxy_service.calculate_metrics(
                    request_received_time, forward_start_time, response_received_time,
                    inter_request_gap, response.status, False, 0, 0, endpoint, "POST", api_type, is_stream
                )
                metrics_service.save_metrics(request_id, metrics)

                self._send_json_response(response.status, {"raw_response": response_body.decode('utf-8')})

        except Exception as e:
            print(f"❌ 转发请求失败：{e}")
            traceback.print_exc()

            # 按上游通信上下文分类（forward_request 含 request/getresponse/read）
            status, type_, failed_at = classify_proxy_exception(e, "upstream_connect")

            # 记录失败的请求
            response_received_time = time.time()
            error_response = {
                "error": str(e),
                "type": type_,
                "traceback": traceback.format_exc(),
                "failed_at": failed_at
            }

            # 保存错误响应日志
            log_service.save_response_log(request_id, error_response, status)

            # 即使失败也要记录指标
            metrics = proxy_service.calculate_metrics(
                request_received_time, forward_start_time, response_received_time,
                inter_request_gap, status, False, 0, 0, endpoint, "POST", api_type, is_stream
            )
            metrics_service.save_metrics(request_id, metrics)

            self._send_json_response(status, error_response)
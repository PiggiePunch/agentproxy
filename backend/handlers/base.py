"""
基础HTTP请求处理器
"""
from http.server import BaseHTTPRequestHandler
from typing import Optional
import json


class BaseAPIHandler(BaseHTTPRequestHandler):
    """基础API处理器"""

    def log_message(self, format, *args):
        """禁用默认日志"""
        pass

    def _get_request_id(self):
        """生成请求ID"""
        from backend.utils.helpers import generate_request_id
        return generate_request_id()

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

    def _send_file_response(self, file_path: str, content_type: str = 'application/octet-stream'):
        """发送文件响应"""
        from pathlib import Path
        from backend.config import Config

        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            self._send_json_response(404, {"error": "File not found"})
            return

        try:
            with open(file_path_obj, 'rb') as f:
                file_content = f.read()

            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', len(file_content))
            self.send_header('Cache-Control', 'public, max-age=86400')
            self.end_headers()
            self.wfile.write(file_content)

        except Exception as e:
            self._send_json_response(500, {"error": f"Error reading file: {str(e)}"})

    def _send_html_response(self, html_content: str):
        """发送HTML响应"""
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(html_content.encode('utf-8')))
        self.end_headers()
        self.wfile.write(html_content.encode('utf-8'))

    def _parse_query_params(self, path: str) -> dict:
        """解析查询参数"""
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(path)
        params = {}
        if parsed.query:
            for key, values in parse_qs(parsed.query).items():
                params[key] = values[0] if len(values) == 1 else values
        return params

    def _get_path_component(self, path: str, index: int) -> Optional[str]:
        """获取路径组件"""
        parts = path.strip('/').split('/')
        if 0 <= index < len(parts):
            return parts[index]
        return None
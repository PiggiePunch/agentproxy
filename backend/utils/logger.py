"""
日志工具模块
提供统一的日志记录接口
"""
from datetime import datetime
from typing import Dict, Any


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


def log_request_info(method: str, path: str, headers: dict, body: dict, request_id: str, api_type: str = "openai"):
    """记录请求信息"""
    from urllib.parse import urlparse

    # 检查是否为内部管理请求（静默处理）
    internal_paths = ["/", "/dashboard", "/metrics", "/static"]
    is_internal_request = path in internal_paths or path.startswith("/metrics") or path.startswith("/static") or path.startswith("/dashboard")

    if is_internal_request:
        # 内部请求只打印简化信息
        print("⚙️ {} {} [{}]".format(method, path, datetime.now().strftime('%H:%M:%S')))
        return

    print("\n" + "="*80)
    print(f"📥 收到请求 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    print(f"请求ID: {request_id}")
    print("="*80)
    print(f"方法：{method}")
    print(f"路径：{path}")
    print(f"API 类型：{api_type}")

    # 根据类型显示转发目标
    from backend.config import Config
    if api_type == "anthropic":
        target_url = Config.ANTHROPIC_API_URL
    else:
        target_url = Config.REAL_API_URL
    print(f"转发目标：{target_url}")

    print("\n请求头:")
    print(sanitize_headers(headers))
    if body:
        print("\n请求体:")
        print(body)
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
    print(sanitize_headers(headers))
    if body:
        print("\n响应体:")
        if len(body) > 2000:
            print(f"{body[:2000]}...\n[响应体已截断，完整长度: {len(body)} 字符]")
        else:
            print(body)
    print("="*80)
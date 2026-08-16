#!/usr/bin/env python3
"""
OpenClaw Proxy Server - 主入口
重构后的标准Python项目结构
"""
import sys
import os
import threading
import time
from pathlib import Path
from http.server import ThreadingHTTPServer

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.config import Config
from backend.handlers.api_handler import APIHandler
from backend.services.log_service import LogService


def cleanup_old_logs(log_service: LogService):
    """清理旧日志文件"""
    print("检查并清理旧日志文件...")
    log_service.cleanup_old_logs(days_to_keep=Config.LOG_RETENTION_DAYS)


def periodic_cleanup(log_service: LogService):
    """定期清理旧日志的后台任务"""
    while True:
        try:
            time.sleep(24 * 60 * 60)  # 每24小时执行一次
            print("\n" + "="*80)
            print("执行定期日志清理...")
            print("="*80)
            log_service.cleanup_old_logs(days_to_keep=Config.LOG_RETENTION_DAYS)
        except Exception as e:
            print(f"定期清理失败: {e}")


def print_startup_info():
    """打印启动信息"""
    print("\n" + "="*80)
    print("OpenClaw 代理服务器启动中...")
    print("="*80)
    print(f"项目根目录: {Config.SCRIPT_DIR}")
    print(f"工作目录: {os.getcwd()}")
    print(f"日志目录: {Config.LOGS_DIR}")

    if Config.SCRIPT_DIR != Path(os.getcwd()):
        print(f"\n警告: 工作目录与项目目录不一致")
        print(f"   建议使用: cd {Config.SCRIPT_DIR}")

    print("\n配置信息:")
    config_info = Config.get_printable_config()
    for key, value in config_info.items():
        print(f"  {key}: {value}")

    print("\n重要提示:")
    print(f"  - 代理支持 OpenAI 和 Anthropic 两种 API 格式")
    print(f"  - 自动检测 API 类型并转发到对应的上游")
    print(f"  - 客户端的 Authorization 头会原封转发给真实 API")
    print(f"  - 上层应用可用 {Config.SESSION_HEADER} 请求头标记会话，未携带时按消息链自动推断")

    print(f"\n客户端配置:")
    print(f"  - OpenAI 格式: Base URL=http://{Config.SERVER_HOST}:{Config.SERVER_PORT}/v1, Endpoint=/chat/completions")
    print(f"  - Anthropic 格式: Base URL=http://{Config.SERVER_HOST}:{Config.SERVER_PORT}/v1, Endpoint=/messages")
    print(f"  - API Key: 填写真实 API 的 Key（会通过代理转发）")
    print(f"  - 模型 ID: 使用真实 API 支持的模型")

    print("\n已支持功能:")
    print("  - OpenAI API 格式支持（/v1/chat/completions）")
    print("  - Anthropic API 格式支持（/v1/messages）")
    print("  - 请求/响应拦截和日志")
    print("  - 流式和非流式转发")
    print("  - 请求和响应持久化保存")
    print("  - 性能监控和分析")
    print(f"  - 自动清理{Config.LOG_RETENTION_DAYS}天前的旧日志")

    print(f"\n日志存储位置:")
    print(f"  - 请求体：{Config.REQUESTS_DIR}")
    print(f"  - 响应体：{Config.RESPONSES_DIR}")
    print(f"  - 性能数据：{Config.METRICS_DIR}")

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


def run_server():
    """启动服务器"""
    # 初始化配置
    if not Config.init_directories():
        print("初始化失败，无法启动服务器")
        sys.exit(1)

    # 启动时清理旧日志
    log_service = LogService()
    cleanup_old_logs(log_service)

    # 打印启动信息
    print_startup_info()

    # 创建服务器
    server_address = (Config.SERVER_HOST, Config.SERVER_PORT)
    httpd = ThreadingHTTPServer(server_address, APIHandler)

    # 启动日志清理后台线程
    cleanup_thread = threading.Thread(target=periodic_cleanup, args=(log_service,), daemon=True)
    cleanup_thread.start()
    print("日志清理后台任务已启动（每24小时执行一次）\n")

    try:
        print(f"服务器正在监听 http://{Config.SERVER_HOST}:{Config.SERVER_PORT}")
        print("按 Ctrl+C 停止服务器\n")
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\n服务器已停止")
        httpd.server_close()


if __name__ == "__main__":
    run_server()
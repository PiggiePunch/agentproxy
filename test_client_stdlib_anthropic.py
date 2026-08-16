#!/usr/bin/env python3
"""
Anthropic 客户端测试脚本 - Python 3.8 标准库版本
测试 Anthropic Messages API 格式
无需安装任何第三方依赖
"""

import json
import os
import http.client
import socket
from urllib.parse import urlparse

# ============= 配置区域 =============
# 从环境变量读取配置
config = {
    "api_key": os.getenv("ANTHROPIC_AUTH_TOKEN", "sk-901dca08a8554e63a92ac3db751faa6e"),
    "model": os.getenv("ANTHROPIC_MODEL", "glm-5.2"),
    # 通过代理连接（推荐）
    "base_url": os.getenv("ANTHROPIC_BASE_URL", "http://localhost:8000/v1"),
    # 如果直连 Moonshot，使用：
    # "base_url": "https://api.moonshot.cn/anthropic/v1"
}

# 构建完整的 API URL
API_URL = f"{config['base_url']}/messages"


def _parse_api_url(api_url: str):
    """解析API URL"""
    parsed = urlparse(api_url)

    # 提取 host 和 path
    host = parsed.netloc

    # 处理默认端口
    if ':' in host:
        host, port = host.split(':')
        port = int(port)
    else:
        if parsed.scheme == 'https':
            port = 443
        else:
            port = 80

    # 构建请求路径
    path = parsed.path
    if parsed.query:
        path += "?" + parsed.query

    # 选择连接类型
    use_https = parsed.scheme == 'https'

    return host, port, path, use_https


def test_non_stream():
    """测试非流式请求"""
    print("\n" + "="*80)
    print("测试 1: 非流式单轮对话")
    print("="*80)

    url = API_URL
    headers = {
        "x-api-key": config["api_key"],
        "anthropic-version": "2023-06-01"
    }

    # Anthropic Messages API 格式
    data = {
        "model": config["model"],
        "max_tokens": 1024,
        "messages": [
            {"role": "user", "content": "你好，请用一句话介绍你自己"}
        ]
    }

    print(f"\n发送请求到：{url}")
    print(f"   模型：{data['model']}")
    print(f"   消息：{data['messages'][0]['content']}")
    print(f"   最大 tokens：{data['max_tokens']}")

    try:
        host, port, path, use_https = _parse_api_url(url)
        body = json.dumps(data).encode('utf-8')
        headers['Content-Type'] = 'application/json'

        if use_https:
            conn = http.client.HTTPSConnection(host, port, timeout=120)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=120)

        try:
            conn.request("POST", path, body=body, headers=headers)
            response = conn.getresponse()
            response_body = response.read().decode('utf-8')

            if response.status == 200:
                result = json.loads(response_body)

                # 解析 Anthropic 响应格式
                if result.get("type") == "message" and "content" in result:
                    # 提取文本内容
                    text_content = ""
                    for block in result["content"]:
                        if block.get("type") == "text":
                            text_content += block.get("text", "")

                    input_tokens = result.get("usage", {}).get("input_tokens", 0)
                    output_tokens = result.get("usage", {}).get("output_tokens", 0)

                    print(f"\n请求成功！")
                    print(f"   Message ID: {result.get('id', 'N/A')}")
                    print(f"   输入 tokens：{input_tokens}")
                    print(f"   输出 tokens：{output_tokens}")
                    print(f"   停止原因：{result.get('stop_reason', 'N/A')}")
                    print(f"\nAI 回复：")
                    print(f"   {text_content}")
                else:
                    print(f"\n响应格式异常：")
                    print(f"   {json.dumps(result, indent=2, ensure_ascii=False)}")

            else:
                print(f"\n请求失败：{response.status}")
                print(f"   {response_body}")

        finally:
            conn.close()

    except Exception as e:
        print(f"\n错误：{e}")
        import traceback
        traceback.print_exc()


def test_stream():
    """测试流式请求"""
    print("\n" + "="*80)
    print("测试 2: 流式单轮对话")
    print("="*80)

    url = API_URL
    headers = {
        "x-api-key": config["api_key"],
        "anthropic-version": "2023-06-01"
    }

    # Anthropic 流式请求格式
    data = {
        "model": config["model"],
        "max_tokens": 1024,
        "messages": [
            {"role": "user", "content": "请用3句话介绍一下 Kimi AI"}
        ],
        "stream": True
    }

    print(f"\n发送流式请求到：{url}")
    print(f"   模型：{data['model']}")
    print(f"   消息：{data['messages'][0]['content']}")
    print(f"   流式：{data['stream']}")
    print(f"\nAI 流式回复：")

    try:
        host, port, path, use_https = _parse_api_url(url)
        body = json.dumps(data).encode('utf-8')
        headers['Content-Type'] = 'application/json'

        if use_https:
            conn = http.client.HTTPSConnection(host, port, timeout=120)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=120)

        try:
            conn.request("POST", path, body=body, headers=headers)
            response = conn.getresponse()

            if response.status == 200:
                print("   ", end="", flush=True)

                chunk_num = 0
                total_received = 0
                message_started = False
                message_completed = False

                try:
                    while True:
                        chunk = response.read(8192).decode('utf-8', errors='ignore')
                        if not chunk:
                            print(f"\n[连接关闭] 共接收 {chunk_num} 个事件，{total_received} 字节")
                            break

                        chunk_num += 1
                        total_received += len(chunk)

                        # 解析 Anthropic SSE 格式
                        lines = chunk.split('\n')
                        current_event = None
                        current_data = None

                        for line in lines:
                            if line.startswith('event: '):
                                current_event = line[7:].strip()
                            elif line.startswith('data: '):
                                current_data = line[6:].strip()

                                # 当我们同时有 event 和 data 时处理
                                if current_event and current_data:
                                    try:
                                        event_data = json.loads(current_data)

                                        # 处理 message_start 事件
                                        if current_event == "message_start":
                                            message_started = True
                                            print(f"\n[消息开始: {event_data.get('message', {}).get('id', 'N/A')}]", end="")

                                        # 处理 content_block_delta 事件（流式内容）
                                        elif current_event == "content_block_delta":
                                            if "delta" in event_data:
                                                delta = event_data["delta"]
                                                if delta.get("type") == "text_delta":
                                                    text = delta.get("text", "")
                                                    if text:
                                                        print(text, end="", flush=True)

                                        # 处理 message_stop 事件
                                        elif current_event == "message_stop":
                                            message_completed = True
                                            print("\n[消息完成]")

                                        # 处理 error 事件
                                        elif current_event == "error":
                                            print(f"\n错误事件：{event_data}")

                                    except json.JSONDecodeError:
                                        pass

                                    current_event = None
                                    current_data = None

                except http.client.RemoteDisconnected as e:
                    print(f"\n远程断开连接：{e}")
                except Exception as e:
                    print(f"\n读取异常：{e}")

                if message_completed:
                    print("\n流式传输完成！")
                else:
                    print("\n流式传输未正常完成")

            else:
                response_body = response.read().decode('utf-8')
                print(f"\n请求失败：{response.status}")
                print(f"   {response_body}")

        finally:
            conn.close()

    except Exception as e:
        print(f"\n错误：{e}")
        import traceback
        traceback.print_exc()


def test_multi_turn():
    """测试多轮对话"""
    print("\n" + "="*80)
    print("测试 3: 多轮对话")
    print("="*80)

    url = API_URL
    headers = {
        "x-api-key": config["api_key"],
        "anthropic-version": "2023-06-01"
    }

    # 多轮对话历史
    messages = []

    conversations = [
        "我的名字叫张三",
        "我刚才说我叫什么名字？",
        "请给我推荐一本好书"
    ]

    print(f"\n开始 {len(conversations)} 轮对话...\n")

    for i, user_message in enumerate(conversations, 1):
        print(f"{'-'*40}")
        print(f"第 {i} 轮")
        print(f"{'-'*40}")

        # 添加用户消息
        messages.append({"role": "user", "content": user_message})
        print(f"用户：{user_message}")

        # 准备请求数据
        data = {
            "model": config["model"],
            "max_tokens": 1024,
            "messages": messages
        }

        try:
            host, port, path, use_https = _parse_api_url(url)
            body = json.dumps(data).encode('utf-8')
            headers['Content-Type'] = 'application/json'

            if use_https:
                conn = http.client.HTTPSConnection(host, port, timeout=120)
            else:
                conn = http.client.HTTPConnection(host, port, timeout=120)

            try:
                conn.request("POST", path, body=body, headers=headers)
                response = conn.getresponse()
                response_body = response.read().decode('utf-8')

                if response.status == 200:
                    result = json.loads(response_body)

                    # 提取助手回复
                    if result.get("type") == "message" and "content" in result:
                        assistant_message = ""
                        for block in result["content"]:
                            if block.get("type") == "text":
                                assistant_message += block.get("text", "")

                        # 添加助手回复到历史
                        messages.append({"role": "assistant", "content": assistant_message})

                        print(f"助手：{assistant_message}")
                    else:
                        print(f"响应格式异常")
                        return

                else:
                    print(f"请求失败：{response.status}")
                    print(f"   {response_body}")
                    return

            finally:
                conn.close()

        except Exception as e:
            print(f"错误：{e}")
            return

    print(f"\n{'-'*40}")
    print(f"多轮对话完成！共 {len(conversations)} 轮")
    print(f"{'-'*40}")


if __name__ == "__main__":
    print("\n" + "="*80)
    print("Anthropic 客户端测试 (标准库版本)")
    print("="*80)

    print("\n当前配置：")
    print(f"  API 地址：{config['base_url']}")
    print(f"  模型：{config['model']}")
    print(f"  API Key：{config['api_key'][:15]}...{config['api_key'][-4:]}")

    # 运行所有测试
    test_non_stream()
    test_stream()
    test_multi_turn()

    print("\n" + "="*80)
    print("所有测试完成！")
    print("="*80 + "\n")

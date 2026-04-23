#!/usr/bin/env python3
"""
DeepSeek 客户端测试脚本 - Python 3.8 标准库版本
无需安装任何第三方依赖
"""

import json
import urllib.request
import urllib.error
import http.client
import socket
from urllib.parse import urlparse

# ============= 配置区域 =============
config = {
    "llm_api_key": "sk-ef89f69a45e4421e9ea8bd967812adba",
    "llm_model": "deepseek-chat",
    "llm_api": "http://localhost:8000/v1/chat/completions"  # 通过代理连接
}

# 如果要测试直连 deepseek，修改上面的 llm_api 为：
# "llm_api": "https://api.deepseek.com/v1/chat/completions"  # 直连 deepseek


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


def _send_request(url: str, headers: dict, data: dict, stream: bool = False):
    """发送HTTP请求"""
    host, port, path, use_https = _parse_api_url(url)

    # 准备请求体
    body = json.dumps(data).encode('utf-8')

    # 添加Content-Type
    headers['Content-Type'] = 'application/json'

    # 选择连接类
    if use_https:
        conn = http.client.HTTPSConnection(host, port, timeout=30)
    else:
        conn = http.client.HTTPConnection(host, port, timeout=30)

    try:
        conn.request("POST", path, body=body, headers=headers)

        if stream:
            return conn, None  # 返回连接对象用于流式读取
        else:
            response = conn.getresponse()
            response_body = response.read().decode('utf-8')
            return response, response_body
    finally:
        if not stream:
            conn.close()


def test_non_stream():
    """测试非流式请求"""
    print("\n" + "="*80)
    print("测试 1: 非流式单轮对话")
    print("="*80)

    url = config["llm_api"]
    headers = {
        "Authorization": f"Bearer {config['llm_api_key']}"
    }

    data = {
        "model": config["llm_model"],
        "messages": [
            {"role": "user", "content": "你好，请用一句话介绍你自己"}
        ],
        "stream": False
    }

    print(f"\n📤 发送请求到：{url}")
    print(f"   模型：{data['model']}")
    print(f"   消息：{data['messages'][0]['content']}")
    print(f"   流式：{data['stream']}")

    try:
        response, response_body = _send_request(url, headers, data, stream=False)

        if response.status == 200:
            result = json.loads(response_body)
            content = result['choices'][0]['message']['content']
            tokens = result['usage']['total_tokens']

            print(f"\n✅ 请求成功！")
            print(f"   使用 tokens：{tokens}")
            print(f"\n📥 AI 回复：")
            print(f"   {content}")

        else:
            print(f"\n❌ 请求失败：{response.status}")
            print(f"   {response_body}")

    except Exception as e:
        print(f"\n❌ 错误：{e}")


def test_stream():
    """测试流式请求"""
    print("\n" + "="*80)
    print("测试 2: 流式单轮对话")
    print("="*80)

    url = config["llm_api"]
    headers = {
        "Authorization": f"Bearer {config['llm_api_key']}"
    }

    data = {
        "model": config["llm_model"],
        "messages": [
            {"role": "user", "content": "请用3句话介绍一下 DeepSeek"}
        ],
        "stream": True
    }

    print(f"\n📤 发送流式请求到：{url}")
    print(f"   模型：{data['model']}")
    print(f"   消息：{data['messages'][0]['content']}")
    print(f"   流式：{data['stream']}")
    print(f"\n📥 AI 流式回复：")

    try:
        host, port, path, use_https = _parse_api_url(url)

        # 准备请求体
        body = json.dumps(data).encode('utf-8')
        headers['Content-Type'] = 'application/json'

        # 选择连接类 - 增加超时时间到 120 秒
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
                received_done = False

                try:
                    while True:
                        chunk = response.read(8192).decode('utf-8', errors='ignore')
                        if not chunk:
                            print(f"\n[连接关闭] 共接收 {chunk_num} 个数据块，{total_received} 字节")
                            break

                        chunk_num += 1
                        total_received += len(chunk)
                        print(f"\n[数据块 #{chunk_num}: {len(chunk)} 字节]", end="", flush=True)

                        # 解析 SSE 格式
                        lines = chunk.split('\n')
                        for line in lines:
                            if line.startswith('data: '):
                                data_str = line[6:]  # 去掉 'data: ' 前缀
                                if data_str.strip() == '[DONE]':
                                    print("\n[收到结束标记]")
                                    received_done = True
                                    continue

                                try:
                                    chunk_data = json.loads(data_str)
                                    if 'choices' in chunk_data and len(chunk_data['choices']) > 0:
                                        delta = chunk_data['choices'][0].get('delta', {})
                                        content = delta.get('content', '')
                                        if content:
                                            print(content, end="", flush=True)
                                except json.JSONDecodeError:
                                    pass

                except http.client.RemoteDisconnected as e:
                    print(f"\n⚠️  远程断开连接：{e}")
                except Exception as e:
                    print(f"\n⚠️  读取异常：{e}")

                print(f"\n\n✅ 流式传输完成！共接收 {total_received} 字节，收到 [DONE]: {received_done}")

            else:
                response_body = response.read().decode('utf-8')
                print(f"\n❌ 请求失败：{response.status}")
                print(f"   {response_body}")

        finally:
            conn.close()

    except Exception as e:
        print(f"\n❌ 错误：{e}")


def test_multi_turn():
    """测试多轮对话"""
    print("\n" + "="*80)
    print("测试 3: 多轮对话")
    print("="*80)

    url = config["llm_api"]
    headers = {
        "Authorization": f"Bearer {config['llm_api_key']}"
    }

    # 多轮对话历史
    messages = [
        {"role": "system", "content": "你是一个有帮助的助手。"}
    ]

    conversations = [
        "我的名字叫张三",
        "我刚才说我叫什么名字？",
        "请给我推荐一本好书"
    ]

    print(f"\n开始 {len(conversations)} 轮对话...\n")

    for i, user_message in enumerate(conversations, 1):
        print(f"{'─'*40}")
        print(f"第 {i} 轮")
        print(f"{'─'*40}")

        # 添加用户消息
        messages.append({"role": "user", "content": user_message})
        print(f"👤 用户：{user_message}")

        # 发送请求
        data = {
            "model": config["llm_model"],
            "messages": messages,
            "stream": False
        }

        try:
            response, response_body = _send_request(url, headers, data, stream=False)

            if response.status == 200:
                result = json.loads(response_body)
                assistant_message = result['choices'][0]['message']['content']

                # 添加助手回复到历史
                messages.append({"role": "assistant", "content": assistant_message})

                print(f"🤖 助手：{assistant_message}")

            else:
                print(f"❌ 请求失败：{response.status}")
                print(f"   {response_body}")
                return

        except Exception as e:
            print(f"❌ 错误：{e}")
            return

    print(f"\n{'─'*40}")
    print(f"✅ 多轮对话完成！共 {len(conversations)} 轮")
    print(f"{'─'*40}")


if __name__ == "__main__":
    print("\n" + "="*80)
    print("DeepSeek 客户端测试 (标准库版本)")
    print("="*80)

    print("\n当前配置：")
    print(f"  API 地址：{config['llm_api']}")
    print(f"  模型：{config['llm_model']}")
    print(f"  API Key：{config['llm_api_key'][:15]}...{config['llm_api_key'][-4:]}")

    # 运行所有测试
    test_non_stream()
    test_stream()
    test_multi_turn()

    print("\n" + "="*80)
    print("所有测试完成！")
    print("="*80 + "\n")

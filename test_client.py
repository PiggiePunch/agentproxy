#!/usr/bin/env python3
"""
DeepSeek 客户端测试脚本 - 多轮对话
"""

import requests
import json

# ============= 配置区域 =============
# 真实 API 配置（当前配置）
config = {
    "llm_api_key": "sk-ef89f69a45e4421e9ea8bd967812adba",
    "llm_model": "deepseek-chat",
    "llm_api": "http://localhost:8000/v1/chat/completions"  # 通过代理连接
}

# 如果要测试直连 deepseek，修改上面的 llm_api 为：
# "llm_api": "https://api.deepseek.com/v1/chat/completions"  # 直连 deepseek


def test_non_stream():
    """测试非流式请求"""
    print("\n" + "="*80)
    print("测试 1: 非流式单轮对话")
    print("="*80)

    url = config["llm_api"]
    headers = {
        "Content-Type": "application/json",
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
        response = requests.post(url, headers=headers, json=data, timeout=30)

        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content']
            tokens = result['usage']['total_tokens']

            print(f"\n✅ 请求成功！")
            print(f"   使用 tokens：{tokens}")
            print(f"\n📥 AI 回复：")
            print(f"   {content}")

        else:
            print(f"\n❌ 请求失败：{response.status_code}")
            print(f"   {response.text}")

    except Exception as e:
        print(f"\n❌ 错误：{e}")


def test_stream():
    """测试流式请求"""
    print("\n" + "="*80)
    print("测试 2: 流式单轮对话")
    print("="*80)

    url = config["llm_api"]
    headers = {
        "Content-Type": "application/json",
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
        response = requests.post(url, headers=headers, json=data, stream=True, timeout=30)

        if response.status_code == 200:
            print("   ", end="", flush=True)
            for line in response.iter_lines():
                if line:
                    line_str = line.decode('utf-8')
                    if line_str.startswith('data: '):
                        data_str = line_str[6:]  # 去掉 'data: ' 前缀
                        if data_str.strip() == '[DONE]':
                            break

                        try:
                            chunk = json.loads(data_str)
                            if 'choices' in chunk and len(chunk['choices']) > 0:
                                delta = chunk['choices'][0].get('delta', {})
                                content = delta.get('content', '')
                                if content:
                                    print(content, end="", flush=True)
                        except json.JSONDecodeError:
                            pass

            print("\n\n✅ 流式传输完成！")

        else:
            print(f"\n❌ 请求失败：{response.status_code}")
            print(f"   {response.text}")

    except Exception as e:
        print(f"\n❌ 错误：{e}")


def test_multi_turn():
    """测试多轮对话"""
    print("\n" + "="*80)
    print("测试 3: 多轮对话")
    print("="*80)

    url = config["llm_api"]
    headers = {
        "Content-Type": "application/json",
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
            response = requests.post(url, headers=headers, json=data, timeout=30)

            if response.status_code == 200:
                result = response.json()
                assistant_message = result['choices'][0]['message']['content']

                # 添加助手回复到历史
                messages.append({"role": "assistant", "content": assistant_message})

                print(f"🤖 助手：{assistant_message}")

            else:
                print(f"❌ 请求失败：{response.status_code}")
                return

        except Exception as e:
            print(f"❌ 错误：{e}")
            return

    print(f"\n{'─'*40}")
    print(f"✅ 多轮对话完成！共 {len(conversations)} 轮")
    print(f"{'─'*40}")


def test_with_openai_library():
    """使用 OpenAI 库测试"""
    print("\n" + "="*80)
    print("测试 4: 使用 OpenAI Python 库")
    print("="*80)

    try:
        from openai import OpenAI

        # 提取 base_url（去掉 /chat/completions 后缀）
        api_url = config["llm_api"]
        if api_url.endswith("/chat/completions"):
            base_url = api_url[:-20]  # 去掉 "/chat/completions"
        else:
            base_url = api_url

        client = OpenAI(
            base_url=base_url,
            api_key=config["llm_api_key"]
        )

        print(f"\n📤 使用 OpenAI 库发送请求")
        print(f"   Base URL：{base_url}")
        print(f"   模型：{config['llm_model']}")

        # 非流式
        print(f"\n📥 非流式回复：")
        response = client.chat.completions.create(
            model=config["llm_model"],
            messages=[
                {"role": "user", "content": "用一句话介绍你自己"}
            ]
        )
        print(f"   {response.choices[0].message.content}")
        print(f"   Tokens: {response.usage.total_tokens}")

        # 流式
        print(f"\n📥 流式回复：")
        print("   ", end="", flush=True)
        stream = client.chat.completions.create(
            model=config["llm_model"],
            messages=[
                {"role": "user", "content": "请用2句话介绍 DeepSeek"}
            ],
            stream=True
        )
        for chunk in stream:
            if chunk.choices[0].delta.content:
                print(chunk.choices[0].delta.content, end="", flush=True)
        print("\n")

        print(f"\n✅ OpenAI 库测试完成！")

    except ImportError:
        print(f"\n⚠️  未安装 openai 库，跳过此测试")
        print(f"   安装命令：pip install openai")
    except Exception as e:
        print(f"\n❌ 错误：{e}")


if __name__ == "__main__":
    print("\n" + "="*80)
    print("DeepSeek 客户端测试")
    print("="*80)

    print("\n当前配置：")
    print(f"  API 地址：{config['llm_api']}")
    print(f"  模型：{config['llm_model']}")
    print(f"  API Key：{config['llm_api_key'][:15]}...{config['llm_api_key'][-4:]}")

    # 运行所有测试
    test_non_stream()
    test_stream()
    test_multi_turn()
    test_with_openai_library()

    print("\n" + "="*80)
    print("所有测试完成！")
    print("="*80 + "\n")

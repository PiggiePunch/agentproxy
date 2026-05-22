"""
格式转换工具模块
处理 Anthropic 和 OpenAI 格式之间的转换
"""
import json
from typing import Dict, Any


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
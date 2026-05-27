#!/usr/bin/env python3
"""
模拟 OpenClaw 插件回调 - 发送一次完整的对话追踪数据到 /traces 接口
基于用户提供的真实回调信息构建

用法: python3 test_trace_callback.py [服务器地址]
默认: http://localhost:8000
"""

import sys
import json
import requests

SERVER = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

trace_data = {
    "trace_id": "8cf7a3cc-646d-4613-ad95-7db6fb0b786d",
    "agent_id": "agent:main:dashboard:c7b0d780-eb3f-4e4f-8865-63b368b79556",
    "started_at": "2026-05-20T10:02:45.971",
    "duration_seconds": 21.6,
    "steps": [
        {
            "step_index": 1,
            "type": "run",
            "name": "main",
            "run_id": "9da71568",
            "offset_seconds": 0,
            "duration_seconds": 20.5,
            "depth": 0,
            "detail": {
                "tokens_in": 17000,
                "tokens_out": 778,
                "tokens_cache": 47100,
                "query": "帮我查查上海的日本料理",
                "reply_summary": "我来帮你查上海的日本料理推荐。抱歉，搜索功能暂时遇到验证码限制。\n\n基于内部知识，给你推荐几个上海热门区域的日料：\n\n## 上海热门日料区域推荐\n\n**陆家嘴地区：**\n- IFC国金中心 - 多家高端日料（寿司、铁板烧、居酒屋）\n- 正大广场 - 日式拉面、寿司、烤肉\n- 上海中心L+Mall - 牛角日本烧肉等\n\n**南京西路：**\n- 恒隆广场 - 私房日料、高端寿司\n- 梅龙镇广场 - 日式餐厅\n\n**新天地/淮海路：**\n- 新天地Style - 精品日料\n- IAPM环贸广场 - 多样化日料选择\n- K11 - 创意日料\n\n**静安寺：**\n- 久光百货 - 传统日式料理\n- 越洋广场 - 居酒屋、烤肉\n\n---\n\n你在哪个区域？想要哪种类型？\n- 拉面 / 寿司 / 铁板烧 / 居酒屋 / 寿喜烧\n- 预算？人均100以下 / 100-200 / 200+\n\n告诉我具体位置和偏好，我精准推荐"
            }
        },
        {
            "step_index": 2,
            "type": "model",
            "name": "custom-api-siliconflow-glm-4-7/Pro/zai-org/GLM-4.7",
            "offset_seconds": 1.1,
            "duration_seconds": 5.9,
            "depth": 1,
            "detail": {
                "ttft_seconds": 3.9,
                "bytes_request": 57900,
                "bytes_response": 133200,
                "in_context_query_chars": 150
            }
        },
        {
            "step_index": 3,
            "type": "tool",
            "name": "read",
            "offset_seconds": 7.2,
            "duration_seconds": 0.229,
            "depth": 1,
            "detail": {
                "skill": "/shanghai-foodie",
                "file": "~/.openclaw/workspace/skills/shanghai-foodie/SKILL.md",
                "result_summary": "Shanghai Foodie skill content: Query Shanghai Japanese restaurant recommendations using curl-based search and return top 5 options. Use ONLY when user asks for Japanese cuisine recommendations in Shanghai."
            }
        },
        {
            "step_index": 4,
            "type": "model",
            "name": "custom-api-siliconflow-glm-4-7/Pro/zai-org/GLM-4.7",
            "offset_seconds": 7.3,
            "duration_seconds": 3.8,
            "depth": 1,
            "detail": {
                "ttft_seconds": 1.0,
                "bytes_request": 64300,
                "bytes_response": 160600,
                "in_context_query_chars": 150
            }
        },
        {
            "step_index": 5,
            "type": "tool",
            "name": "exec",
            "offset_seconds": 11.2,
            "duration_seconds": 0.447,
            "depth": 1,
            "detail": {
                "command": "curl -s 'https://www.baidu.com/s?wd=上海日本料理推荐%20top%205' -H 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'",
                "result_summary": "Baidu returned captcha verification page (tuxing_v2.html)"
            }
        },
        {
            "step_index": 6,
            "type": "model",
            "name": "custom-api-siliconflow-glm-4-7/Pro/zai-org/GLM-4.7",
            "offset_seconds": 11.5,
            "duration_seconds": 2.7,
            "depth": 1,
            "detail": {
                "ttft_seconds": 0.775,
                "bytes_request": 65600,
                "bytes_response": 107200,
                "in_context_query_chars": 150
            }
        },
        {
            "step_index": 7,
            "type": "tool",
            "name": "exec",
            "offset_seconds": 14.3,
            "duration_seconds": 0.355,
            "depth": 1,
            "detail": {
                "command": "curl -s 'https://www.baidu.com/s?wd=上海日料店推荐' -H 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)'",
                "result_summary": "Baidu returned captcha verification page again (tuxing_v2.html)"
            }
        },
        {
            "step_index": 8,
            "type": "model",
            "name": "custom-api-siliconflow-glm-4-7/Pro/zai-org/GLM-4.7",
            "offset_seconds": 14.5,
            "duration_seconds": 7.1,
            "depth": 1,
            "detail": {
                "ttft_seconds": 1.7,
                "bytes_request": 66800,
                "bytes_response": 400400,
                "in_context_query_chars": 150
            }
        }
    ],
    "summary": {
        "model_calls": 4,
        "tool_calls": 3,
        "tokens_in": 17000,
        "tokens_out": 778,
        "tokens_cache": 47100,
        "model_time_seconds": 19.4,
        "top_tools": {"exec": 2, "read": 1}
    }
}

print(f"发送追踪数据到 {SERVER}/traces ...")
try:
    response = requests.post(f"{SERVER}/traces", json=trace_data, timeout=10)
    print(f"状态码: {response.status_code}")
    print(f"响应: {response.json()}")
except Exception as e:
    print(f"错误: {e}")
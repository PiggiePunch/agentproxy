from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.utils import get_openapi
import json
import time
import uuid
import asyncio
import httpx
from datetime import datetime
from typing import AsyncGenerator, Dict, List
import os
from pathlib import Path
import threading
from collections import defaultdict

app = FastAPI(title="OpenClaw Proxy Server")

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory="."), name="static")

# ============= 配置区域 =============
# 真正的大模型 API 地址（只需要配置这个）
# 可以通过环境变量 REAL_API_URL 配置，或者直接修改这里
REAL_API_URL = os.getenv("REAL_API_URL", "https://api.deepseek.com/v1")

# 是否启用详细日志
VERBOSE_LOGGING = os.getenv("VERBOSE_LOGGING", "true").lower() == "true"

# 日志存储目录
LOGS_DIR = Path("logs")
REQUESTS_DIR = LOGS_DIR / "requests"
RESPONSES_DIR = LOGS_DIR / "responses"
METRICS_DIR = LOGS_DIR / "metrics"

# 创建日志目录
LOGS_DIR.mkdir(exist_ok=True)
REQUESTS_DIR.mkdir(exist_ok=True)
RESPONSES_DIR.mkdir(exist_ok=True)
METRICS_DIR.mkdir(exist_ok=True)

# 需要转发的请求头列表（会从客户端请求中提取并发送给真实 API）
FORWARD_HEADERS = [
    "authorization",
    "content-type",
    "user-agent",
    "accept",
    "accept-encoding",
    "connection",
    "x-api-key",
    "x-openai-organization",
]

# 不需要转发的请求头（代理特定的头）
SKIP_HEADERS = [
    "host",
    "content-length",
    "transfer-encoding",
]

# 存储请求日志
request_logs = []

# 性能监控数据（内存中，重启清空）
performance_metrics = defaultdict(list)
session_start_time = datetime.now()
last_request_time = None
request_counter = 0
lock = threading.Lock()


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


def save_request_body(request_id: str, headers: dict, body: dict):
    """保存请求头和请求体到文件（包含完整 API Key）"""
    filename = REQUESTS_DIR / f"{request_id}.json"
    request_data = {
        "request_id": request_id,
        "timestamp": datetime.now().isoformat(),
        "headers": headers,  # 保存完整的请求头，包含 API Key
        "body": body
    }
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(request_data, f, ensure_ascii=False, indent=2)


def save_response_body(request_id: str, body: dict or str, status_code: int):
    """保存响应体到文件"""
    filename = RESPONSES_DIR / f"{request_id}.json"
    response_data = {
        "status_code": status_code,
        "body": body,
        "timestamp": datetime.now().isoformat()
    }
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(response_data, f, ensure_ascii=False, indent=2)


def save_metrics(request_id: str, metrics: dict):
    """保存性能指标到文件"""
    filename = METRICS_DIR / f"{request_id}.json"
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    # 同时保存到内存（用于看板）
    with lock:
        performance_metrics['requests'].append({
            'request_id': request_id,
            **metrics
        })


def log_request_info(method: str, path: str, headers: dict, body: dict, request_id: str):
    """记录请求信息"""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "request_id": request_id,
        "method": method,
        "path": path,
        "headers": sanitize_headers(headers),
        "body": body
    }
    request_logs.append(log_entry)

    # 打印到控制台
    print("\n" + "="*80)
    print(f"📥 收到请求 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    print(f"请求ID: {request_id}")
    print("="*80)
    print(f"方法：{method}")
    print(f"路径：{path}")
    print(f"转发目标：{REAL_API_URL}")
    print("\n请求头:")
    print(json.dumps(sanitize_headers(headers), indent=2, ensure_ascii=False))
    print("\n请求体:")
    print(json.dumps(body, indent=2, ensure_ascii=False))
    print("="*80)


def log_response_info(status_code: int, headers: dict, body: str = None):
    """记录响应信息"""
    print("\n" + "="*80)
    print(f"📤 收到响应 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    print("="*80)
    print(f"状态码：{status_code}")
    print("\n响应头:")
    print(json.dumps(sanitize_headers(headers), indent=2, ensure_ascii=False))
    if body and VERBOSE_LOGGING:
        print("\n响应体:")
        if len(body) > 2000:
            print(f"{body[:2000]}...\n[响应体已截断，完整长度: {len(body)} 字符]")
        else:
            print(body)
    print("="*80)


def prepare_forward_headers(request_headers: dict) -> dict:
    """准备转发给真实 API 的请求头"""
    forward_headers = {}

    for key, value in request_headers.items():
        key_lower = key.lower()

        if key_lower in SKIP_HEADERS:
            continue

        if key_lower in [h.lower() for h in FORWARD_HEADERS] or key_lower.startswith("x-"):
            forward_headers[key] = value

    # 更新 Host 头为目标地址
    if REAL_API_URL.startswith("http://"):
        host = REAL_API_URL[7:]
    elif REAL_API_URL.startswith("https://"):
        host = REAL_API_URL[8:]
    else:
        host = REAL_API_URL

    host = host.split("/")[0].split(":")[0]
    forward_headers["Host"] = host

    return forward_headers


async def forward_stream_response(client: httpx.AsyncClient, method: str, url: str,
                                   headers: dict, content: bytes, request_id: str) -> AsyncGenerator[bytes, None]:
    """转发流式响应 - 完全透明的流式转发"""
    chunk_count = 0
    total_bytes = 0

    print("\n" + "="*80)
    print("🌊 开始流式转发")
    print("="*80)

    try:
        timeout = httpx.Timeout(120.0, connect=10.0)

        async with client.stream(method, url, headers=headers, content=content, timeout=timeout) as response:
            print(f"状态码：{response.status_code}")
            print(f"Content-Type：{response.headers.get('content-type', 'N/A')}")
            print("="*80)

            async for chunk in response.aiter_bytes():
                chunk_count += 1
                total_bytes += len(chunk)

                if VERBOSE_LOGGING:
                    chunk_preview = chunk.decode('utf-8', errors='ignore')[:500]
                    print(f"📦 数据块 #{chunk_count} ({len(chunk)} bytes): {chunk_preview}")

                yield chunk

            print("\n" + "="*80)
            print(f"✅ 流式转发完成")
            print(f"   总数据块：{chunk_count}")
            print(f"   总字节数：{total_bytes}")
            print("="*80 + "\n")

    except httpx.TimeoutException as e:
        print(f"\n❌ 流式请求超时：{e}")
        raise
    except httpx.HTTPError as e:
        print(f"\n❌ 流式请求HTTP错误：{e}")
        raise
    except Exception as e:
        print(f"\n❌ 流式转发异常：{e}")
        import traceback
        traceback.print_exc()
        raise


async def forward_non_stream_response(client: httpx.AsyncClient, method: str, url: str,
                                       headers: dict, content: bytes, request_id: str) -> httpx.Response:
    """转发非流式请求"""
    response = await client.request(method, url, headers=headers, content=content, timeout=60.0)

    body = response.text if response.headers.get("content-type", "").startswith("application/json") else None
    log_response_info(response.status_code, dict(response.headers), body)

    return response


@app.get("/")
async def root():
    """健康检查端点"""
    return {
        "status": "ok",
        "message": "OpenClaw Proxy Server is running",
        "real_api_url": REAL_API_URL,
        "session_start": session_start_time.isoformat(),
        "endpoints": {
            "chat_completions": "/v1/chat/completions",
            "completions": "/v1/completions",
            "models": "/v1/models",
            "dashboard": "http://localhost:8000/static/dashboard.html",
            "metrics": "/metrics",
            "metrics_summary": "/metrics/summary"
        }
    }


@app.get("/dashboard")
async def dashboard():
    """看板页面"""
    from fastapi.responses import HTMLResponse
    with open("dashboard.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/v1/models")
async def list_models(request: Request):
    """转发模型列表请求"""
    request_id = f"req-{uuid.uuid4()}"
    headers = dict(request.headers)
    log_request_info("GET", "/v1/models", headers, {}, request_id)

    # 性能监控开始
    request_received_time = time.time()

    forward_headers = prepare_forward_headers(headers)
    url = f"{REAL_API_URL}/models"

    async with httpx.AsyncClient() as client:
        forward_start_time = time.time()
        response = await forward_non_stream_response(client, "GET", url, forward_headers, None, request_id)
        response_received_time = time.time()

        # 保存性能指标
        metrics = {
            "request_received_time": request_received_time,
            "forward_start_time": forward_start_time,
            "response_received_time": response_received_time,
            "proxy_processing_time": forward_start_time - request_received_time,
            "model_response_time": response_received_time - forward_start_time,
            "total_time": response_received_time - request_received_time,
            "endpoint": "/v1/models",
            "method": "GET"
        }
        save_metrics(request_id, metrics)

        # 保存响应体
        try:
            save_response_body(request_id, response.json(), response.status_code)
        except:
            save_response_body(request_id, response.text, response.status_code)

        return JSONResponse(
            content=response.json(),
            status_code=response.status_code,
            headers=dict(response.headers)
        )


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """转发聊天补全请求（完全支持流式和非流式）"""
    global request_counter, last_request_time

    request_id = f"req-{uuid.uuid4()}"

    try:
        # 性能监控：收到请求时间
        request_received_time = time.time()

        # 计算距上次请求的间隔
        inter_request_gap = None
        if last_request_time is not None:
            inter_request_gap = request_received_time - last_request_time

        last_request_time = request_received_time
        request_counter += 1

        # 获取请求体
        body = await request.json()
        is_stream = body.get("stream", False)

        # 记录请求
        headers = dict(request.headers)
        log_request_info("POST", "/v1/chat/completions", headers, body, request_id)

        # 保存请求头和请求体
        save_request_body(request_id, headers, body)

        if is_stream:
            print("\n🌊 检测到流式请求 (stream=true)")
            print("   客户端 → 代理 → 大模型（全程流式连接）")
            print("")

        # 准备转发请求
        forward_headers = prepare_forward_headers(headers)
        url = f"{REAL_API_URL}/chat/completions"
        content = json.dumps(body).encode("utf-8")

        # 性能监控：开始转发时间
        forward_start_time = time.time()

        limits = httpx.Limits(max_keepalive_connections=100, max_connections=100)
        timeout = httpx.Timeout(120.0, connect=10.0)

        if is_stream:
            print("🔗 建立流式连接：客户端 ↔ 代理 ↔ 大模型")
            print("")

            async def stream_generator():
                nonlocal request_received_time, forward_start_time
                response_first_byte_time = None
                stream_complete_time = None
                stream_chunks = []  # 收集所有流式数据块
                chunk_count = 0
                total_bytes = 0

                async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
                    async for chunk in forward_stream_response(client, "POST", url, forward_headers, content, request_id):
                        if response_first_byte_time is None:
                            response_first_byte_time = time.time()

                        # 收集数据块
                        chunk_count += 1
                        total_bytes += len(chunk)
                        stream_chunks.append({
                            "index": chunk_count,
                            "size": len(chunk),
                            "data": chunk.decode('utf-8', errors='ignore')
                        })

                        yield chunk

                # 流式传输完成，记录结束时间
                stream_complete_time = time.time()

                # 保存完整的流式性能指标
                metrics = {
                    "request_received_time": request_received_time,
                    "forward_start_time": forward_start_time,
                    "response_first_byte_time": response_first_byte_time,
                    "response_complete_time": stream_complete_time,
                    "proxy_processing_time": forward_start_time - request_received_time,
                    "time_to_first_byte": response_first_byte_time - forward_start_time,
                    "total_stream_time": stream_complete_time - forward_start_time,
                    "total_time": stream_complete_time - request_received_time,
                    "inter_request_gap": inter_request_gap,
                    "endpoint": "/v1/chat/completions",
                    "method": "POST",
                    "stream": True
                }
                save_metrics(request_id, metrics)

                # 保存响应数据
                response_data = {
                    "stream": True,
                    "status_code": 200,
                    "chunks": stream_chunks,
                    "total_chunks": chunk_count,
                    "total_bytes": total_bytes,
                    "first_byte_time": response_first_byte_time,
                    "complete_time": stream_complete_time,
                    "timestamp": datetime.now().isoformat()
                }
                save_response_body(request_id, response_data, 200)

                print(f"\n📁 已保存流式响应: {chunk_count} 个数据块，总大小 {total_bytes} 字节")
                print(f"   首字节时间: {(response_first_byte_time - forward_start_time)*1000:.2f}ms")
                print(f"   总传输时间: {(stream_complete_time - forward_start_time)*1000:.2f}ms")

            return StreamingResponse(
                stream_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                    "Content-Type": "text/event-stream",
                }
            )
        else:
            print("📦 非流式请求模式")

            async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
                response = await forward_non_stream_response(client, "POST", url, forward_headers, content, request_id)
                response_received_time = time.time()

                # 保存性能指标
                metrics = {
                    "request_received_time": request_received_time,
                    "forward_start_time": forward_start_time,
                    "response_received_time": response_received_time,
                    "proxy_processing_time": forward_start_time - request_received_time,
                    "model_response_time": response_received_time - forward_start_time,
                    "total_time": response_received_time - request_received_time,
                    "inter_request_gap": inter_request_gap,
                    "endpoint": "/v1/chat/completions",
                    "method": "POST",
                    "stream": False
                }
                save_metrics(request_id, metrics)

                # 保存响应体
                try:
                    response_body = response.json()
                    save_response_body(request_id, response_body, response.status_code)
                except:
                    save_response_body(request_id, response.text, response.status_code)

                return JSONResponse(
                    content=response.json(),
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )

    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析错误：{e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except httpx.TimeoutException:
        print(f"❌ 请求超时")
        raise HTTPException(status_code=504, detail="Request timeout")
    except httpx.HTTPError as e:
        print(f"❌ HTTP 错误：{e}")
        raise HTTPException(status_code=502, detail=f"Bad gateway: {str(e)}")
    except Exception as e:
        print(f"❌ 处理请求时出错：{e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics")
async def get_metrics():
    """获取性能监控数据"""
    with lock:
        return {
            "session_start": session_start_time.isoformat(),
            "request_counter": request_counter,
            "metrics": list(performance_metrics.get('requests', []))
        }


@app.get("/metrics/summary")
async def get_metrics_summary():
    """获取性能监控摘要"""
    with lock:
        requests_data = performance_metrics.get('requests', [])

        if not requests_data:
            return {
                "session_start": session_start_time.isoformat(),
                "total_requests": 0,
                "avg_total_time": 0,
                "avg_proxy_processing_time": 0,
                "avg_model_response_time": 0,
                "avg_inter_request_gap": 0
            }

        total_times = [r.get('total_time', 0) for r in requests_data if 'total_time' in r]
        proxy_times = [r.get('proxy_processing_time', 0) for r in requests_data if 'proxy_processing_time' in r]
        model_times = [r.get('model_response_time', r.get('time_to_first_byte', 0)) for r in requests_data]
        gap_times = [r.get('inter_request_gap', 0) for r in requests_data if r.get('inter_request_gap') is not None]

        return {
            "session_start": session_start_time.isoformat(),
            "total_requests": len(requests_data),
            "avg_total_time": sum(total_times) / len(total_times) if total_times else 0,
            "avg_proxy_processing_time": sum(proxy_times) / len(proxy_times) if proxy_times else 0,
            "avg_model_response_time": sum(model_times) / len(model_times) if model_times else 0,
            "avg_inter_request_gap": sum(gap_times) / len(gap_times) if gap_times else 0,
            "max_total_time": max(total_times) if total_times else 0,
            "min_total_time": min(total_times) if total_times else 0
        }


@app.delete("/metrics")
async def clear_metrics():
    """清除性能监控数据"""
    with lock:
        global performance_metrics, request_counter, session_start_time
        performance_metrics = defaultdict(list)
        request_counter = 0
        session_start_time = datetime.now()
    return {"status": "ok", "message": "性能数据已清除"}


if __name__ == "__main__":
    import uvicorn

    print("\n" + "="*80)
    print("🚀 OpenClaw 代理服务器启动中...")
    print("="*80)
    print("\n配置说明:")
    print(f"1. 真实 API 地址：{REAL_API_URL}")
    print(f"2. 可以通过环境变量 REAL_API_URL 修改")
    print(f"3. 代理监听地址：http://0.0.0.0:8000")
    print(f"\n⚠️  重要提示:")
    print(f"  - 代理只需要配置 API 地址，不需要配置 API Key")
    print(f"  - 客户端的 Authorization 头会原封转发给真实 API")
    print(f"\n客户端配置:")
    print(f"  - Base URL: http://localhost:8000/v1")
    print(f"  - API Key: 填写真实 API 的 Key（会通过代理转发）")
    print(f"  - 模型 ID: 使用真实 API 支持的模型")
    print("\n✨ 已支持功能:")
    print("  - ✓ 请求/响应拦截和日志")
    print("  - ✓ 流式和非流式转发")
    print("  - ✓ 请求和响应持久化保存")
    print("  - ✓ 性能监控和分析")
    print("  - ✓ 实时数据看板")
    print("\n📁 日志存储位置:")
    print(f"  - 请求体：{REQUESTS_DIR}")
    print(f"  - 响应体：{RESPONSES_DIR}")
    print(f"  - 性能数据：{METRICS_DIR}")
    print("\n🌐 访问看板:")
    print(f"  - http://localhost:8000/dashboard")
    print(f"\n可用端点:")
    print("  - GET  http://localhost:8000/              (健康检查)")
    print("  - GET  http://localhost:8000/dashboard      (数据看板)")
    print("  - GET  http://localhost:8000/metrics       (性能数据)")
    print("  - GET  http://localhost:8000/metrics/summary (性能摘要)")
    print("  - DELETE http://localhost:8000/metrics     (清除性能数据)")
    print("  - POST http://localhost:8000/v1/chat/completions (聊天补全)")
    print("\n所有请求和响应信息将在此控制台输出")
    print("="*80 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)

#!/usr/bin/env python3
"""
流式解析修复验证脚本（无第三方依赖，直接运行: python test_stream_chunk_split.py）

验证四个修复点：
1. TTFB：time_to_first_byte 应在上游首字节真实到达后才打点（能反映出上游的首字节延迟）
2. 跨 chunk：usage/首token 的 SSE 事件被拆分到多个 TCP chunk（含 UTF-8 多字节字符中间切断）时不漏检
3. Anthropic：input_tokens 从 message_start 事件提取，output_tokens 从 message_delta 事件提取
4. Anthropic 输入token = input_tokens + cache_creation_input_tokens + cache_read_input_tokens
   （agent 预置提示词走缓存，只取 input_tokens 会严重少算；流式/非流式均验证）

原理：
- 启动一个"假上游"SSE 服务器：先延迟 FIRST_BYTE_DELAY 秒再吐第一个字节，
  之后每个小片段之间间隔 FRAG_DELAY 秒写出，确保代理 read1() 每次只读到片段
- 以子进程方式启动代理（上游地址指向假上游）
- 客户端通过代理发起 OpenAI / Anthropic 两种流式请求，最后读取 /metrics 断言
"""
import http.client
import http.server
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

PROXY_PORT = 18090
UPSTREAM_PORT = 18091
FIRST_BYTE_DELAY = 0.35   # 假上游首字节延迟（秒），用于验证 TTFB
FRAG_DELAY = 0.05         # 片段间间隔（秒），确保事件被拆到不同 chunk

EXPECTED_OPENAI_INPUT = 123
EXPECTED_OPENAI_OUTPUT = 45
# Anthropic 输入侧：非缓存输入 77 + 缓存写入 15411 + 缓存读取 200
# （agent 预置系统提示词通常走 cache_creation/cache_read，必须三项相加）
ANTHROPIC_INPUT_BASE = 77
ANTHROPIC_CACHE_WRITE = 15411
ANTHROPIC_CACHE_READ = 200
EXPECTED_ANTHROPIC_INPUT = ANTHROPIC_INPUT_BASE + ANTHROPIC_CACHE_WRITE + ANTHROPIC_CACHE_READ
EXPECTED_ANTHROPIC_OUTPUT = 88


# ============= 假上游：构造被刻意拆分的 SSE 片段 =============

def build_openai_fragments():
    """OpenAI 格式 SSE，首token事件从'你'的UTF-8字节中间切开，usage事件JSON拦腰切开"""
    e_role = 'data: {"id":"chatcmpl-test","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant","content":""}}]}\n\n'
    e_first = 'data: {"id":"chatcmpl-test","choices":[{"index":0,"delta":{"content":"你好"}}]}\n\n'
    e_more = 'data: {"id":"chatcmpl-test","choices":[{"index":0,"delta":{"content":"世界"}}]}\n\n'
    e_usage = 'data: {"id":"chatcmpl-test","choices":[],"usage":{"prompt_tokens":%d,"completion_tokens":%d}}\n\n' % (
        EXPECTED_OPENAI_INPUT, EXPECTED_OPENAI_OUTPUT)
    e_done = 'data: [DONE]\n\n'

    b_first = e_first.encode('utf-8')
    cut_first = b_first.index('你好'.encode('utf-8')) + 1  # "你"(3字节)的第1、2字节之间

    b_usage = e_usage.encode('utf-8')
    cut_usage = len('data: {"id":"chatcmpl-test","choices":[],"usage":{"prompt_to'.encode('utf-8'))

    return [
        e_role.encode('utf-8'),
        b_first[:cut_first],
        b_first[cut_first:],
        e_more.encode('utf-8'),
        b_usage[:cut_usage],
        b_usage[cut_usage:],
        e_done.encode('utf-8'),
    ]


def build_anthropic_fragments():
    """Anthropic 格式 SSE，message_start/首token/message_delta 事件均被切开

    usage 模拟真实上游（如 GLM/dashscope Anthropic 兼容端点）：
    message_start 带完整输入侧分解（含缓存），message_delta 也带完整 usage。
    """
    e_start = ('event: message_start\n'
               'data: {"type":"message_start","message":{"id":"msg_test","type":"message","role":"assistant",'
               '"content":[],"model":"claude-test","usage":{"input_tokens":%d,'
               '"cache_creation_input_tokens":%d,"cache_read_input_tokens":%d,"output_tokens":1}}}\n\n') % (
        ANTHROPIC_INPUT_BASE, ANTHROPIC_CACHE_WRITE, ANTHROPIC_CACHE_READ)
    e_block_start = ('event: content_block_start\n'
                     'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n')
    e_delta = ('event: content_block_delta\n'
               'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"你好"}}\n\n')
    e_block_stop = 'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n'
    e_msg_delta = ('event: message_delta\n'
                   'data: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},'
                   '"usage":{"input_tokens":%d,"cache_creation_input_tokens":%d,'
                   '"cache_read_input_tokens":%d,"output_tokens":%d}}\n\n') % (
        ANTHROPIC_INPUT_BASE, ANTHROPIC_CACHE_WRITE, ANTHROPIC_CACHE_READ, EXPECTED_ANTHROPIC_OUTPUT)
    e_stop = 'event: message_stop\ndata: {"type":"message_stop"}\n\n'

    b_start = e_start.encode('utf-8')
    cut_start = b_start.index(b'cache_creation_input_tokens') + 8  # 缓存字段名中间切开

    b_delta = e_delta.encode('utf-8')
    cut_delta = b_delta.index('你好'.encode('utf-8')) + 1  # UTF-8 多字节字符中间切开

    b_md = e_msg_delta.encode('utf-8')
    cut_md = b_md.index(b'output_tokens') + 5  # usage JSON 切开

    return [
        b_start[:cut_start],
        b_start[cut_start:],
        e_block_start.encode('utf-8'),
        b_delta[:cut_delta],
        b_delta[cut_delta:],
        e_block_stop.encode('utf-8'),
        b_md[:cut_md],
        b_md[cut_md:],
        e_stop.encode('utf-8'),
    ]


class FakeUpstreamHandler(http.server.BaseHTTPRequestHandler):
    """假上游：延迟吐出首字节，并把SSE事件拆成小片段逐个写出"""

    def log_message(self, *args):
        pass

    def do_POST(self):
        if self.path.rstrip('/').endswith('/messages'):
            fragments = build_anthropic_fragments()
        else:
            fragments = build_openai_fragments()

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.end_headers()
        self.wfile.flush()

        time.sleep(FIRST_BYTE_DELAY)  # 模拟上游首字节延迟

        for frag in fragments:
            self.wfile.write(frag)
            self.wfile.flush()
            time.sleep(FRAG_DELAY)


# ============= 客户端工具 =============

def wait_for_proxy(timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{PROXY_PORT}/', timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def send_stream_request(path, body):
    conn = http.client.HTTPConnection('127.0.0.1', PROXY_PORT, timeout=30)
    try:
        conn.request('POST', path, body=json.dumps(body).encode('utf-8'),
                     headers={'Content-Type': 'application/json',
                              'Authorization': 'Bearer test-key'})
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def fetch_metrics():
    with urllib.request.urlopen(f'http://127.0.0.1:{PROXY_PORT}/metrics', timeout=5) as r:
        return json.loads(r.read().decode('utf-8'))['metrics']


def find_metric(metrics, api_type):
    for m in metrics:
        if m.get('api_type') == api_type and m.get('stream'):
            return m
    return None


# ============= 主流程 =============

def main():
    # 输出含emoji/特殊符号，Windows GBK控制台下会编码崩溃，强制UTF-8
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    failures = []

    def check(name, cond, detail=""):
        if cond:
            print(f"  [PASS] {name}")
        else:
            print(f"  [FAIL] {name} {detail}")
            failures.append(name)

    # ---- 非流式 token 提取（单测，无需启动服务）----
    from backend.services.proxy_service import ProxyService
    ps = ProxyService()

    print("[非流式 usage 提取]")
    # 真实上游返回的 Anthropic usage（agent 预置提示词走缓存写入）
    real_usage = {"cache_creation": {"ephemeral_5m_input_tokens": 15411}, "output_tokens": 30,
                  "cache_creation_input_tokens": 15411, "input_tokens": 6,
                  "cache_read_input_tokens": 0, "prompt_tokens_details": {"cached_tokens": 0}}
    inp, out = ps.extract_token_usage({"usage": real_usage})
    check("Anthropic usage 输入=6+15411+0（含缓存）", inp == 15417 and out == 30, f"(实际 {inp}/{out})")
    # 真实非流式样例：缓存为0时结果即 input_tokens 本身
    real_nonstream = {"cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                      "input_tokens": 19, "output_tokens": 584,
                      "prompt_tokens_details": {"cached_tokens": 0}}
    inp3, out3 = ps.extract_token_usage({"usage": real_nonstream})
    check("Anthropic 非流式样例 输入=19 输出=584", inp3 == 19 and out3 == 584, f"(实际 {inp3}/{out3})")
    # OpenAI 格式：prompt_tokens 本身已含缓存部分
    inp2, out2 = ps.extract_token_usage({"usage": {"prompt_tokens": 100, "completion_tokens": 20,
                                                   "prompt_tokens_details": {"cached_tokens": 80}}})
    check("OpenAI usage 直接取 prompt_tokens", inp2 == 100 and out2 == 20, f"(实际 {inp2}/{out2})")

    upstream = http.server.ThreadingHTTPServer(('127.0.0.1', UPSTREAM_PORT), FakeUpstreamHandler)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()

    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['REAL_API_URL'] = f'http://127.0.0.1:{UPSTREAM_PORT}/v1'
    env['ANTHROPIC_API_URL'] = f'http://127.0.0.1:{UPSTREAM_PORT}/anthropic'
    env['SERVER_HOST'] = '127.0.0.1'
    env['SERVER_PORT'] = str(PROXY_PORT)

    proxy_log = tempfile.TemporaryFile()
    proxy = subprocess.Popen([sys.executable, 'backend/main.py'], env=env,
                             cwd=str(PROJECT_ROOT),
                             stdout=proxy_log, stderr=subprocess.STDOUT)
    try:
        if not wait_for_proxy():
            print("代理启动失败")
            proxy_log.seek(0)
            print(proxy_log.read().decode('utf-8', errors='ignore')[-3000:])
            sys.exit(1)

        # ---- OpenAI 流式 ----
        status, openai_body = send_stream_request('/v1/chat/completions', {
            "model": "test-model", "stream": True,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "user", "content": "hi"}]
        })
        openai_text = openai_body.decode('utf-8', errors='ignore')

        # ---- Anthropic 流式 ----
        status2, anthropic_body = send_stream_request('/v1/messages', {
            "model": "claude-test", "stream": True, "max_tokens": 64,
            "messages": [{"role": "user", "content": "hi"}]
        })
        anthropic_text = anthropic_body.decode('utf-8', errors='ignore')

        time.sleep(1.5)  # 等待代理落库指标
        metrics = fetch_metrics()
        m_openai = find_metric(metrics, 'openai')
        m_anthropic = find_metric(metrics, 'anthropic')

        print("\n[客户端透传完整性]")
        check("OpenAI 流状态码 200", status == 200, f"(实际 {status})")
        check("OpenAI 内容完整透传", '你好' in openai_text and '世界' in openai_text and '[DONE]' in openai_text)
        check("Anthropic 流状态码 200", status2 == 200, f"(实际 {status2})")
        check("Anthropic 内容完整透传", '你好' in anthropic_text and 'message_stop' in anthropic_text)

        print("\n[OpenAI 指标]")
        if m_openai is None:
            check("找到 OpenAI 流式指标", False)
        else:
            check("找到 OpenAI 流式指标", True)
            check(f"input_tokens == {EXPECTED_OPENAI_INPUT}（usage事件被拆分仍可提取）",
                  m_openai['input_tokens'] == EXPECTED_OPENAI_INPUT, f"(实际 {m_openai['input_tokens']})")
            check(f"output_tokens == {EXPECTED_OPENAI_OUTPUT}",
                  m_openai['output_tokens'] == EXPECTED_OPENAI_OUTPUT, f"(实际 {m_openai['output_tokens']})")
            check("首token已检测到（事件跨chunk+UTF-8字节被切断）",
                  m_openai['first_token_latency'] > 0, f"(实际 {m_openai['first_token_latency']})")
            check(f"time_to_first_byte 反映上游延迟(>{FIRST_BYTE_DELAY - 0.05}s)",
                  m_openai['time_to_first_byte'] > FIRST_BYTE_DELAY - 0.05,
                  f"(实际 {m_openai['time_to_first_byte']:.3f}s)")

        print("\n[Anthropic 指标]")
        if m_anthropic is None:
            check("找到 Anthropic 流式指标", False)
        else:
            check("找到 Anthropic 流式指标", True)
            check(f"input_tokens == {EXPECTED_ANTHROPIC_INPUT}（input+缓存写入+缓存读取，message_delta完整usage未覆盖message_start值）",
                  m_anthropic['input_tokens'] == EXPECTED_ANTHROPIC_INPUT, f"(实际 {m_anthropic['input_tokens']})")
            check(f"output_tokens == {EXPECTED_ANTHROPIC_OUTPUT}（来自 message_delta，事件被拆分仍可提取）",
                  m_anthropic['output_tokens'] == EXPECTED_ANTHROPIC_OUTPUT, f"(实际 {m_anthropic['output_tokens']})")
            check("首token已检测到（事件跨chunk+UTF-8字节被切断）",
                  m_anthropic['first_token_latency'] > 0, f"(实际 {m_anthropic['first_token_latency']})")
            check(f"time_to_first_byte 反映上游延迟(>{FIRST_BYTE_DELAY - 0.05}s)",
                  m_anthropic['time_to_first_byte'] > FIRST_BYTE_DELAY - 0.05,
                  f"(实际 {m_anthropic['time_to_first_byte']:.3f}s)")

        if failures:
            print(f"\n{len(failures)} 项检查未通过: {failures}")
            print("\n----- 代理输出（尾部）-----")
            proxy_log.seek(0)
            print(proxy_log.read().decode('utf-8', errors='ignore')[-4000:])
            sys.exit(1)
        print("\n全部检查通过")

    finally:
        proxy.terminate()
        try:
            proxy.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proxy.kill()
        upstream.shutdown()


if __name__ == '__main__':
    main()

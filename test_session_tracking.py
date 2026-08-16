#!/usr/bin/env python3
"""
会话跟踪验证脚本（无第三方依赖，直接运行: python test_session_tracking.py）

验证会话识别的两种来源与前端所需字段：
1. 请求头携带 X-Session-Id 时直接使用（source=header）
2. 未携带时按消息前缀链自动推断（source=inferred）：
   - 多轮追加消息 -> 同一会话
   - 不同开头消息 -> 不同会话
   - 上下文截断导致前缀断裂 -> 按"系统提示+首条用户消息"退化匹配
3. session_id/session_source 写入 metrics 和请求日志文件
"""
import http.client
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

PROXY_PORT = 18092
UPSTREAM_PORT = 18093


class FakeUpstreamHandler(http.server.BaseHTTPRequestHandler):
    """假上游：返回非流式JSON响应"""

    def log_message(self, *args):
        pass

    def do_POST(self):
        if self.path.rstrip('/').endswith('/messages'):
            body = {"id": "msg_test", "type": "message", "role": "assistant",
                    "content": [{"type": "text", "text": "ok"}], "model": "claude-test",
                    "stop_reason": "end_turn", "stop_sequence": None,
                    "usage": {"input_tokens": 8, "output_tokens": 4}}
        else:
            body = {"id": "chatcmpl-test", "object": "chat.completion",
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": "ok"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        data = json.dumps(body).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


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


def send_request(path, body, session_id=None):
    conn = http.client.HTTPConnection('127.0.0.1', PROXY_PORT, timeout=30)
    try:
        headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer test-key'}
        if session_id:
            headers['X-Session-Id'] = session_id
        conn.request('POST', path, body=json.dumps(body).encode('utf-8'), headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def fetch_metrics():
    with urllib.request.urlopen(f'http://127.0.0.1:{PROXY_PORT}/metrics', timeout=5) as r:
        return json.loads(r.read().decode('utf-8'))['metrics']


def fetch_request_log(request_id):
    with urllib.request.urlopen(f'http://127.0.0.1:{PROXY_PORT}/logs/request/{request_id}', timeout=5) as r:
        return json.loads(r.read().decode('utf-8'))


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    failures = []

    def check(name, cond, detail=""):
        if cond:
            print(f"  [PASS] {name}")
        else:
            print(f"  [FAIL] {name} {detail}")
            failures.append(name)

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

        # ---- 按序发送请求 ----
        # 组1: 请求头显式携带会话ID
        send_request('/v1/chat/completions', {"model": "m", "messages": [{"role": "user", "content": "H-q1"}]},
                     session_id='user-sess-1')
        send_request('/v1/chat/completions', {"model": "m", "messages": [
            {"role": "user", "content": "H-q1"},
            {"role": "assistant", "content": "H-a1"},
            {"role": "user", "content": "H-q2"}]}, session_id='user-sess-1')
        # 组2: 无请求头，消息前缀链推断
        send_request('/v1/chat/completions', {"model": "m", "messages": [{"role": "user", "content": "A-q1"}]})
        send_request('/v1/chat/completions', {"model": "m", "messages": [
            {"role": "user", "content": "A-q1"},
            {"role": "assistant", "content": "A-a1"},
            {"role": "user", "content": "A-q2"}]})
        # 组3: 无请求头，不同开头 -> 新会话
        send_request('/v1/chat/completions', {"model": "m", "messages": [{"role": "user", "content": "B-q1"}]})
        # 组4: Anthropic 格式推断（system 为独立字段）
        send_request('/v1/messages', {"model": "claude-test", "max_tokens": 64, "system": "SYS-C",
                                      "messages": [{"role": "user", "content": "C-q1"}]})
        send_request('/v1/messages', {"model": "claude-test", "max_tokens": 64, "system": "SYS-C",
                                      "messages": [
                                          {"role": "user", "content": "C-q1"},
                                          {"role": "assistant", "content": "C-a1"},
                                          {"role": "user", "content": "C-q2"}]})
        # 组5: 上下文截断 -> 前缀断裂，按稳定头退化匹配
        send_request('/v1/chat/completions', {"model": "m", "messages": [
            {"role": "system", "content": "SYS-T"},
            {"role": "user", "content": "T-q1"},
            {"role": "assistant", "content": "T-a1"},
            {"role": "user", "content": "T-q2"},
            {"role": "assistant", "content": "T-a2"}]})
        send_request('/v1/chat/completions', {"model": "m", "messages": [
            {"role": "system", "content": "SYS-T"},
            {"role": "user", "content": "T-q1"},
            {"role": "assistant", "content": "T-summary（历史已压缩）"}]})
        # 组6: 两个会话交替到达，验证互不干扰、各自续接
        send_request('/v1/chat/completions', {"model": "m", "messages": [{"role": "user", "content": "X-q1"}]})
        send_request('/v1/chat/completions', {"model": "m", "messages": [{"role": "user", "content": "Y-q1"}]})
        send_request('/v1/chat/completions', {"model": "m", "messages": [
            {"role": "user", "content": "X-q1"},
            {"role": "assistant", "content": "X-a1"},
            {"role": "user", "content": "X-q2"}]})
        send_request('/v1/chat/completions', {"model": "m", "messages": [
            {"role": "user", "content": "Y-q1"},
            {"role": "assistant", "content": "Y-a1"},
            {"role": "user", "content": "Y-q2"}]})
        # 组7: agent 改写历史消息（cache_control 挪动、content 块数组与纯字符串互换）
        # 真实 agent 每轮都会把旧消息的 cache_control 移除并把块数组压成字符串，
        # 归一化指纹必须识别为同一会话
        send_request('/v1/messages', {"model": "claude-test", "max_tokens": 64, "system": "SYS-R",
                                      "messages": [{"role": "user", "content": [
                                          {"type": "text", "text": "R-q1",
                                           "cache_control": {"type": "ephemeral"}}]}]})
        send_request('/v1/messages', {"model": "claude-test", "max_tokens": 64, "system": "SYS-R",
                                      "messages": [
                                          {"role": "user", "content": "R-q1"},
                                          {"role": "assistant", "content": "R-a1"},
                                          {"role": "user", "content": [
                                              {"type": "text", "text": "R-q2",
                                               "cache_control": {"type": "ephemeral"}}]}]})

        time.sleep(1.0)
        metrics = fetch_metrics()
        check("共记录 15 条请求指标", len(metrics) == 15, f"(实际 {len(metrics)})")
        if len(metrics) != 15:
            sys.exit(1)
        m1, m2, m3, m4, m5, m6, m7, m8, m9, m10, m11, m12, m13, m14, m15 = metrics

        print("\n[请求头会话]")
        check("m1 会话ID = user-sess-1", m1['session_id'] == 'user-sess-1', f"(实际 {m1['session_id']})")
        check("m1 来源 = header", m1['session_source'] == 'header', f"(实际 {m1['session_source']})")
        check("m2 同会话（请求头优先，不受消息变化影响）", m2['session_id'] == 'user-sess-1')

        print("\n[消息链自动推断]")
        check("m3 推断出新会话（s- 前缀）",
              (m3['session_id'] or '').startswith('s-'), f"(实际 {m3['session_id']})")
        check("m3 来源 = inferred", m3['session_source'] == 'inferred', f"(实际 {m3['session_source']})")
        check("m4 追加消息后仍为同一会话", m4['session_id'] == m3['session_id'],
              f"(m3={m3['session_id']}, m4={m4['session_id']})")
        check("m5 不同开头 -> 不同会话",
              m5['session_id'] != m3['session_id'] and (m5['session_id'] or '').startswith('s-'))

        print("\n[Anthropic 格式推断]")
        check("m6 推断出新会话", (m6['session_id'] or '').startswith('s-') and m6['session_id'] != m3['session_id'])
        check("m7 追加消息后仍为同一会话（system 字段参与指纹链）", m7['session_id'] == m6['session_id'])

        print("\n[上下文截断退化匹配]")
        check("m8 推断出新会话", (m8['session_id'] or '').startswith('s-') and m8['session_id'] not in
              (m3['session_id'], m5['session_id'], m6['session_id']))
        check("m9 截断后仍归入同一会话（系统提示+首条用户消息匹配）", m9['session_id'] == m8['session_id'],
              f"(m8={m8['session_id']}, m9={m9['session_id']})")

        print("\n[多会话交替到达]")
        check("m10 推断出新会话X", (m10['session_id'] or '').startswith('s-') and m10['session_id'] not in
              (m3['session_id'], m5['session_id'], m6['session_id'], m8['session_id']))
        check("m11 推断出新会话Y（未与X合并）", (m11['session_id'] or '').startswith('s-')
              and m11['session_id'] != m10['session_id'])
        check("m12 X被Y插队后仍归入会话X", m12['session_id'] == m10['session_id'],
              f"(m10={m10['session_id']}, m12={m12['session_id']})")
        check("m13 Y续接仍归入会话Y", m13['session_id'] == m11['session_id'],
              f"(m11={m11['session_id']}, m13={m13['session_id']})")

        print("\n[agent改写历史消息]")
        check("m14 推断出新会话", (m14['session_id'] or '').startswith('s-') and m14['session_id'] not in
              (m3['session_id'], m5['session_id'], m6['session_id'], m8['session_id'],
               m10['session_id'], m11['session_id']))
        check("m15 历史消息被改写后仍归入同一会话（cache_control移除+块数组转字符串）",
              m15['session_id'] == m14['session_id'],
              f"(m14={m14['session_id']}, m15={m15['session_id']})")

        print("\n[请求日志落盘]")
        log3 = fetch_request_log(m3['request_id'])
        check("请求日志包含 session_id", log3.get('session_id') == m3['session_id'],
              f"(实际 {log3.get('session_id')})")

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

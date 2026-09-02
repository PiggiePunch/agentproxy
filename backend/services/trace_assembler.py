"""
TraceAssembler - 从代理流量自动重建对话追踪

不依赖 agent 主动上报，直接解析经过代理的 LLM 请求/响应报文，
按 session 归组、按"对话轮次(span)"切分，自动拼出模型调用与工具调用链路。

核心判定（对每个 session 的连续请求流）：
  - 新 span 开始：请求最后一条消息是"真实用户文本"（非 tool_result）
  - span 继续：   请求最后一条消息是 tool_result（Anthropic）/ role=tool（OpenAI）
  - span 结束：   某次模型响应不再包含 tool_use（最终回答）

兼容性处理：
  - 部分 agent 框架（如 jiuwenswarm）会在 messages 中注入动态标签消息
    （<system-reminder>、<prompt-attachment> 等），每条请求内容不同。
    识别时跳过纯注入消息，找到真实的用户/工具消息来分类和提取查询。
  - 部分框架将用户消息包装为 "你收到一条消息：\n{JSON}" 格式，
    提取时解析 JSON 取出 content 字段。

性能约束：
  - 只复用已解析的请求体 / 响应数据，不做额外反序列化
  - 组装发生在响应完成之后（与 metrics 统计同时），纯内存 dict 操作
  - per-session 状态有界，session 数超限淘汰最旧
"""
import json as _json
import re
import time
import threading
import uuid
from collections import OrderedDict
from datetime import datetime
from typing import Any, Dict, List, Optional

_INJECTED_TAG_RE = re.compile(
    r'<([a-z][\w-]*)(?:\s[^>]*)?>.*?</\1>\n?', re.DOTALL
)
_WRAPPER_RE = re.compile(
    r'^(?:你收到一条消息[^：:\n]*|You receive a new message[^：:\n]*)[：:]\s*\n?(.+)$',
    re.DOTALL
)


class TraceAssembler:
    """按 session 自动拼装对话追踪"""

    MAX_SESSIONS = 200
    # 单条 span 内最多保留的步骤数，防止异常长对话撑爆内存
    MAX_STEPS_PER_SPAN = 200
    # reply_summary / 工具输入输出的截断长度
    TEXT_CAP = 300

    def __init__(self, trace_service=None):
        self.trace_service = trace_service
        # session_id -> session 状态
        self.sessions: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self.lock = threading.Lock()

    # ---------- 对外入口 ----------

    def set_trace_service(self, trace_service):
        self.trace_service = trace_service

    def on_request(self, session_id: Optional[str], api_type: str,
                   body_data: dict, request_id: str, received_ts: float):
        """请求到达时调用（请求体已解析）。只记录轻量状态，不阻塞转发。"""
        if not session_id or not isinstance(body_data, dict):
            return
        try:
            messages = body_data.get('messages') or []
            if not messages:
                return
            kind = self._classify_last_message(messages, api_type)
            with self.lock:
                state = self._get_or_create_session(session_id)
                if kind == 'new_user_turn':
                    # 上一个 span 的最后一次响应必然是最终回答（或被放弃），先收尾
                    self._finalize_open_span(state)
                    self._start_span(state, messages, api_type, body_data, received_ts)
                else:
                    # 工具循环继续；若没有开放 span（边界情况）则补建
                    if state.get('span') is None:
                        self._start_span(state, messages, api_type, body_data, received_ts)
                    self._attach_tool_results(state, messages, api_type, received_ts)
                # 每个请求 = 一次模型调用，先挂一个待填充的 model step
                self._add_model_step(state, body_data, request_id, received_ts)
        except Exception:
            pass  # 追踪拼装失败绝不能影响代理转发

    def on_response(self, session_id: Optional[str], request_id: str,
                    has_tool_use: bool, input_tokens: int = 0, output_tokens: int = 0,
                    duration_seconds: float = 0.0, tool_uses: Optional[List[dict]] = None,
                    final_text: Optional[str] = None, ttft_seconds: float = 0.0,
                    bytes_request: int = 0, bytes_response: int = 0):
        """响应完成时调用。填充 model step，并按是否有 tool_use 决定收尾。"""
        if not session_id:
            return
        try:
            with self.lock:
                state = self.sessions.get(session_id)
                if not state or state.get('span') is None:
                    return
                span = state['span']
                self._fill_model_step(span, request_id, input_tokens, output_tokens,
                                      duration_seconds, ttft_seconds,
                                      bytes_request, bytes_response)
                span['tokens_in'] += input_tokens or 0
                span['tokens_out'] += output_tokens or 0
                if has_tool_use:
                    # 记录待配对的 tool_use，span 保持打开
                    span['pending_tool_uses'] = tool_uses or []
                    span['model_calls'] = span.get('model_calls', 0)
                    # 记录工具开始执行的时刻（tool_use 响应完成时），用于计算工具耗时
                    span['tool_wait_start_ts'] = time.time()
                else:
                    if final_text:
                        span['reply_summary'] = self._cap(final_text)
                    self._finalize_open_span(state)
        except Exception:
            pass

    # ---------- 注入标签处理 ----------

    @staticmethod
    def _strip_injected_tags(text: str) -> str:
        return _INJECTED_TAG_RE.sub('', text)

    @classmethod
    def _msg_real_content(cls, msg: dict) -> str:
        content = msg.get('content', '')
        if isinstance(content, list):
            parts = []
            for b in content:
                if isinstance(b, dict) and b.get('type') == 'text':
                    parts.append(b.get('text', ''))
            content = '\n'.join(parts)
        return cls._strip_injected_tags(str(content)).strip()

    @classmethod
    def _is_injected_only(cls, msg: dict) -> bool:
        role = msg.get('role', '')
        if role in ('tool', 'assistant'):
            return False
        if msg.get('tool_call_id') or msg.get('tool_calls'):
            return False
        if msg.get('content') and isinstance(msg['content'], list):
            for b in msg['content']:
                if isinstance(b, dict) and b.get('type') == 'tool_result':
                    return False
        return cls._msg_real_content(msg) == ''

    @classmethod
    def _find_last_real_message(cls, messages: List[dict]) -> Optional[dict]:
        for msg in reversed(messages):
            if not cls._is_injected_only(msg):
                return msg
        return None

    @classmethod
    def _unwrap_user_content(cls, text: str) -> str:
        m = _WRAPPER_RE.match(text)
        if not m:
            return text
        json_str = m.group(1).strip()
        try:
            data = _json.loads(json_str)
            if isinstance(data, dict):
                return data.get('content', text)
        except (_json.JSONDecodeError, ValueError):
            pass
        return text

    # ---------- session / span 生命周期 ----------

    def _get_or_create_session(self, session_id: str) -> Dict[str, Any]:
        if session_id in self.sessions:
            self.sessions.move_to_end(session_id)
            return self.sessions[session_id]
        state = {'session_id': session_id, 'span': None}
        self.sessions[session_id] = state
        while len(self.sessions) > self.MAX_SESSIONS:
            # 淘汰最旧 session；若其仍有未收尾 span，先落盘
            _, old = self.sessions.popitem(last=False)
            self._finalize_open_span(old)
        return state

    def _start_span(self, state: Dict[str, Any], messages: List[dict],
                    api_type: str, body_data: dict, received_ts: float):
        query = self._extract_user_query(messages, api_type)
        state['span'] = {
            'trace_id': str(uuid.uuid4()),
            'started_ts': received_ts,
            'started_at': datetime.fromtimestamp(received_ts).isoformat(),
            'model': body_data.get('model', ''),
            'user_query': query,
            'steps': [],
            'tokens_in': 0,
            'tokens_out': 0,
            'model_calls': 0,
            'tool_calls': 0,
            'model_time': 0.0,
            'pending_tool_uses': [],
            'reply_summary': '',
            'top_tools': {},
        }
        # run 步骤作为 span 根节点
        state['span']['steps'].append({
            'type': 'run',
            'name': '对话轮次',
            'depth': 0,
            'offset_seconds': 0,
            'duration_seconds': 0,
            'detail': {'query': self._cap(query)},
        })

    def _finalize_open_span(self, state: Dict[str, Any]):
        span = state.get('span')
        if span is None:
            return
        state['span'] = None
        if not span['steps']:
            return
        self._save_span(state['session_id'], span)

    def _save_span(self, session_id: str, span: Dict[str, Any]):
        if self.trace_service is None:
            return
        # 去重：若这段对话的时间窗口已被 agent 上报的 trace 覆盖，就不再产出自动 trace
        span_end_ts = time.time()
        try:
            if self.trace_service.has_agent_trace_in_window(span['started_ts'], span_end_ts):
                return
        except Exception:
            pass

        duration = span_end_ts - span['started_ts']
        # 回填 run 步骤耗时与 token
        run_step = span['steps'][0]
        run_step['duration_seconds'] = round(duration, 3)
        run_step['detail'].update({
            'tokens_in': span['tokens_in'],
            'tokens_out': span['tokens_out'],
            'reply_summary': span.get('reply_summary', ''),
        })

        trace_data = {
            'trace_id': span['trace_id'],
            'agent_id': f'auto:{session_id}',
            'session_id': session_id,
            'source': 'auto',
            'started_at': span['started_at'],
            'duration_seconds': round(duration, 3),
            'steps': span['steps'],
            'summary': {
                'model_calls': span['model_calls'],
                'tool_calls': span['tool_calls'],
                'tokens_in': span['tokens_in'],
                'tokens_out': span['tokens_out'],
                'model_time_seconds': round(span['model_time'], 3),
                'top_tools': span['top_tools'],
            },
        }
        self.trace_service.save_trace(trace_data)

    # ---------- 步骤构建 ----------

    def _add_model_step(self, state: Dict[str, Any], body_data: dict,
                        request_id: str, received_ts: float):
        span = state.get('span')
        if span is None:
            return
        if len(span['steps']) >= self.MAX_STEPS_PER_SPAN:
            return
        span['model_calls'] += 1
        step = {
            'type': 'model',
            'name': body_data.get('model', 'model'),
            'depth': 1,
            'offset_seconds': round(received_ts - span['started_ts'], 3),
            'duration_seconds': 0,
            'request_id': request_id,
            'started_ts': received_ts,
            'detail': {},
        }
        span['steps'].append(step)
        span['last_model_request_id'] = request_id

    def _fill_model_step(self, span: Dict[str, Any], request_id: str,
                         input_tokens: int, output_tokens: int, duration_seconds: float,
                         ttft_seconds: float = 0.0, bytes_request: int = 0,
                         bytes_response: int = 0):
        # 找到对应 request_id 的 model step（通常是最后一个）
        target = None
        for step in reversed(span['steps']):
            if step.get('type') == 'model' and step.get('request_id') == request_id:
                target = step
                break
        if target is None:
            return
        target['duration_seconds'] = round(duration_seconds, 3)
        target['detail'] = {
            'tokens_in': input_tokens,
            'tokens_out': output_tokens,
            'ttft_seconds': round(ttft_seconds, 3) if ttft_seconds else 0,
            'bytes_request': bytes_request or 0,
            'bytes_response': bytes_response or 0,
        }
        span['model_time'] += duration_seconds or 0

    def _attach_tool_results(self, state: Dict[str, Any], messages: List[dict],
                             api_type: str, received_ts: float):
        span = state.get('span')
        if span is None:
            return
        pending = span.get('pending_tool_uses') or []
        results = self._extract_tool_results(messages, api_type)
        # 工具耗时 = 上次 tool_use 响应完成 -> 本次 tool_result 请求到达
        wait_start = span.get('tool_wait_start_ts')
        tool_duration = max(0.0, received_ts - wait_start) if wait_start else 0.0
        tool_offset = (wait_start - span['started_ts']) if wait_start else (received_ts - span['started_ts'])
        for i, res in enumerate(results):
            if len(span['steps']) >= self.MAX_STEPS_PER_SPAN:
                break
            # 尽量按 id 配对，配不上就按序取
            name = res.get('name') or ''
            if not name and i < len(pending):
                name = pending[i].get('name', 'tool')
            span['tool_calls'] += 1
            span['top_tools'][name] = span['top_tools'].get(name, 0) + 1
            span['steps'].append({
                'type': 'tool',
                'name': name or 'tool',
                'depth': 1,
                'offset_seconds': round(max(0.0, tool_offset), 3),
                'duration_seconds': round(tool_duration, 3),
                'detail': {
                    'result_summary': self._cap(res.get('content', '')),
                },
            })
        # 配对完成后清空 pending
        span['pending_tool_uses'] = []
        span.pop('tool_wait_start_ts', None)

    # ---------- 报文解析 ----------

    def _classify_last_message(self, messages: List[dict], api_type: str) -> str:
        msg = self._find_last_real_message(messages)
        if msg is None:
            return 'new_user_turn'
        role = msg.get('role', '')
        if api_type == 'anthropic':
            if role != 'user':
                return 'new_user_turn'
            content = msg.get('content')
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'tool_result':
                        return 'tool_continuation'
            return 'new_user_turn'
        if role == 'tool' or msg.get('tool_call_id'):
            return 'tool_continuation'
        return 'new_user_turn'

    def _extract_user_query(self, messages: List[dict], api_type: str) -> str:
        msg = self._find_last_real_message(messages)
        if msg is None:
            return ''
        content = msg.get('content', '')
        if isinstance(content, str):
            return self._unwrap_user_content(content)
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'text':
                    parts.append(block.get('text', ''))
            text = '\n'.join(parts)
            return self._unwrap_user_content(text)
        return ''

    def _extract_tool_results(self, messages: List[dict], api_type: str) -> List[dict]:
        results = []
        if api_type == 'anthropic':
            msg = self._find_last_real_message(messages) or (messages[-1] if messages else {})
            content = msg.get('content')
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'tool_result':
                        results.append({
                            'tool_use_id': block.get('tool_use_id', ''),
                            'content': self._block_text(block.get('content', '')),
                        })
            return results
        # openai：末尾可能连续多条 role=tool，跳过纯注入消息
        for msg in reversed(messages):
            if msg.get('role') == 'tool':
                results.append({
                    'name': msg.get('name', ''),
                    'tool_call_id': msg.get('tool_call_id', ''),
                    'content': self._block_text(msg.get('content', '')),
                })
            elif self._is_injected_only(msg):
                continue
            else:
                break
        results.reverse()
        return results

    @staticmethod
    def _block_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'text':
                    parts.append(block.get('text', ''))
            return '\n'.join(parts)
        return str(content)

    def _cap(self, text: Any) -> str:
        s = str(text) if text is not None else ''
        return s if len(s) <= self.TEXT_CAP else s[:self.TEXT_CAP] + '…'


# 全局单例
trace_assembler = TraceAssembler()

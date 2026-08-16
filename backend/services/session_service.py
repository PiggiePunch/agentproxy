"""
会话识别服务模块
区分上层应用多个 session 发来的请求

两种识别来源：
1. 请求头（准确）：上层应用通过 SESSION_HEADER 显式携带会话ID
2. 自动推断（兜底）：同一会话的多轮请求 messages 数组按前缀增长，
   据此做消息指纹链匹配；上下文被截断导致前缀断裂时，
   退化为"系统提示词 + 首条用户消息"稳定头匹配
"""
import hashlib
import json
import threading
import time
import uuid
from typing import Optional, Tuple

from backend.config import Config


class SessionService:
    """会话识别服务"""

    def __init__(self):
        self.lock = threading.Lock()
        # session_id -> {"chain": [...], "head_key": str, "last_seen": float}
        # 只保存自动推断出的会话；请求头会话无需状态
        self.sessions = {}
        self.max_sessions = 200

    def resolve(self, headers: dict, body_data) -> Tuple[Optional[str], Optional[str]]:
        """解析会话ID，返回 (session_id, source)，source 为 'header' 或 'inferred'"""
        session_id = self._from_header(headers)
        if session_id:
            return session_id, "header"

        session_id = self._infer(body_data)
        if session_id:
            return session_id, "inferred"

        return None, None

    def _from_header(self, headers: dict) -> Optional[str]:
        """从请求头读取会话ID（大小写不敏感）"""
        target = Config.SESSION_HEADER.lower()
        for key, value in headers.items():
            if key.lower() == target:
                value = (value or '').strip()
                return value or None
        return None

    def _infer(self, body_data) -> Optional[str]:
        """基于消息指纹链推断会话归属"""
        if not isinstance(body_data, dict):
            return None
        messages = body_data.get('messages')
        if not isinstance(messages, list) or not messages:
            return None

        chain = self._build_chain(body_data, messages)
        if not chain:
            return None
        head_key = self._build_head_key(body_data, messages)

        now = time.time()
        with self.lock:
            # 1) 前缀链匹配：已有会话的消息链是当前请求的前缀（含重试的完全相等），取最长匹配
            best_sid, best_len = None, -1
            for sid, info in self.sessions.items():
                prev = info['chain']
                if len(prev) <= len(chain) and chain[:len(prev)] == prev:
                    if len(prev) > best_len:
                        best_sid, best_len = sid, len(prev)

            # 2) 退化匹配：上下文截断导致前缀断裂时，按稳定头（系统提示+首条用户消息）匹配
            if best_sid is None and head_key:
                for sid, info in self.sessions.items():
                    if info.get('head_key') == head_key:
                        best_sid = sid
                        break

            if best_sid is not None:
                self.sessions[best_sid]['chain'] = chain
                self.sessions[best_sid]['last_seen'] = now
                return best_sid

            # 3) 新会话
            sid = f"s-{uuid.uuid4().hex[:8]}"
            self.sessions[sid] = {"chain": chain, "head_key": head_key, "last_seen": now}
            if len(self.sessions) > self.max_sessions:
                oldest = min(self.sessions, key=lambda k: self.sessions[k]['last_seen'])
                del self.sessions[oldest]
            return sid

    def _fingerprint(self, item) -> str:
        """对单条消息/系统提示词生成指纹"""
        try:
            raw = json.dumps(item, sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            raw = repr(item)
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]

    def _normalize_message(self, msg):
        """把单条消息归一化为稳定结构，用于指纹计算

        agent 会在轮次之间改写历史消息：挪动/移除 cache_control、把 content
        块数组压成纯字符串、剥离 thinking/reasoning 等。直接对原始消息做指纹
        会因此漂移，导致会话链断裂，必须先归一化到纯语义字段。
        """
        if not isinstance(msg, dict):
            return msg
        norm = {'role': msg.get('role')}

        content = self._normalize_content(msg.get('content'))
        if content is not None:
            norm['content'] = content

        # tool_calls（OpenAI格式）：arguments 的 JSON 字符串解析为对象，消除序列化差异
        tool_calls = msg.get('tool_calls')
        if isinstance(tool_calls, list):
            norm_calls = []
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    norm_calls.append(tc)
                    continue
                tcc = {k: v for k, v in tc.items() if k != 'cache_control'}
                fn = tcc.get('function')
                if isinstance(fn, dict):
                    fn = dict(fn)
                    if isinstance(fn.get('arguments'), str):
                        try:
                            fn['arguments'] = json.loads(fn['arguments'])
                        except (json.JSONDecodeError, ValueError):
                            pass
                    tcc['function'] = fn
                norm_calls.append(tcc)
            norm['tool_calls'] = norm_calls

        for key in ('tool_call_id', 'name'):
            if key in msg:
                norm[key] = msg[key]

        return norm

    def _normalize_content(self, content):
        """归一化消息内容：剥离 cache_control 等易变字段，统一块/字符串表示

        单个 text 块与纯文本字符串视为等价；thinking/reasoning 块为模型派生
        内容，agent 轮次间常剥离或改写，不参与指纹。
        """
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return content

        blocks = []
        for b in content:
            if not isinstance(b, dict):
                blocks.append(b)
                continue
            btype = b.get('type')
            if btype == 'text':
                blocks.append({'type': 'text', 'text': b.get('text', '')})
            elif btype == 'tool_use':
                blocks.append({'type': 'tool_use', 'id': b.get('id'),
                               'name': b.get('name'), 'input': b.get('input')})
            elif btype == 'tool_result':
                blocks.append({'type': 'tool_result', 'tool_use_id': b.get('tool_use_id'),
                               'content': self._normalize_content(b.get('content'))})
            elif btype in ('thinking', 'redacted_thinking', 'reasoning'):
                continue
            elif btype == 'image':
                source = b.get('source') or {}
                blocks.append({'type': 'image', 'source_type': source.get('type'),
                               'media_type': source.get('media_type')})
            else:
                blocks.append({k: v for k, v in b.items() if k != 'cache_control'})

        # 单个 text 块与纯文本字符串等价（agent 常在轮次间互换这两种形式）
        if len(blocks) == 1 and isinstance(blocks[0], dict) and blocks[0].get('type') == 'text':
            return blocks[0]['text']
        return blocks

    def _build_chain(self, body_data: dict, messages: list) -> list:
        """构建消息指纹链（Anthropic 的 system 字段置于链首）"""
        chain = []
        system = body_data.get('system')
        if system:
            chain.append(self._fingerprint(self._normalize_content(system)))
        for msg in messages:
            chain.append(self._fingerprint(self._normalize_message(msg)))
        return chain

    def _build_head_key(self, body_data: dict, messages: list) -> Optional[str]:
        """构建稳定头：系统提示词 + 首条用户消息（中段上下文被截断时仍然存在）"""
        system = body_data.get('system')
        if system:
            system = self._normalize_content(system)
        else:
            for msg in messages:
                if isinstance(msg, dict) and msg.get('role') in ('system', 'developer'):
                    system = self._normalize_content(msg.get('content'))
                    break

        first_user = None
        for msg in messages:
            if isinstance(msg, dict) and msg.get('role') == 'user':
                first_user = self._normalize_message(msg)
                break

        if system is None and first_user is None:
            return None
        return self._fingerprint([system, first_user])

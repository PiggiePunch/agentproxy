"""
Trace服务模块
存储和管理对话追踪数据
"""
import json
import uuid
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional

from backend.config import Config
from backend.models.request import ConversationTrace


class TraceService:
    """Trace服务类 - 存储和检索对话追踪数据"""

    def __init__(self):
        self.traces_dir = Config.TRACES_DIR
        self.traces: List[Dict[str, Any]] = []
        self.lock = threading.Lock()
        self.max_traces = 200
        # 一旦有 agent 通过 POST /traces 主动上报，就抑制代理侧自动拼装，
        # 避免同一对话产生重复 trace（自动解析仅作为未上报时的补充）
        self.agent_reported = False
        # 最近一次 agent 上报的时间戳（用于时间窗口去重）
        self.last_agent_report_ts = 0.0

    def mark_agent_reported(self):
        """标记已有 agent 主动上报 trace"""
        import time as _time
        self.agent_reported = True
        self.last_agent_report_ts = _time.time()

    def has_agent_trace_in_window(self, start_ts: float, end_ts: float) -> bool:
        """判断 [start_ts, end_ts] 时间窗口内是否已有 agent 上报的 trace。

        用于自动拼装去重：若某段对话已经被 agent 主动上报覆盖，
        就不再产出重复的自动 trace。
        """
        from datetime import datetime as _dt
        with self.lock:
            for t in self.traces:
                if t.get('source', 'agent') != 'agent':
                    continue
                started = t.get('started_at') or t.get('received_at') or ''
                try:
                    a_start = _dt.fromisoformat(started).timestamp()
                except Exception:
                    continue
                a_end = a_start + float(t.get('duration_seconds') or 0)
                # 时间区间有交集即视为已覆盖
                if a_start <= end_ts and a_end >= start_ts:
                    return True
        return False

    def save_trace(self, trace_data: Dict[str, Any]) -> str:
        """保存一条对话追踪记录。返回服务器端存储ID。"""
        # agent 主动上报（source != auto）时，标记已上报
        if trace_data.get('source', 'agent') != 'auto':
            import time as _time
            self.agent_reported = True
            self.last_agent_report_ts = _time.time()

        storage_id = str(uuid.uuid4())

        trace = ConversationTrace(storage_id, trace_data)
        trace_dict = trace.to_dict()

        # 持久化到文件
        filename = self.traces_dir / f"{storage_id}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(trace_dict, f, ensure_ascii=False, indent=2)

        with self.lock:
            self.traces.append(trace_dict)
            # 超过上限时移除最老的记录
            if len(self.traces) > self.max_traces:
                removed = self.traces.pop(0)
                # 删除对应的文件
                old_file = self.traces_dir / f"{removed['storage_id']}.json"
                if old_file.exists():
                    old_file.unlink()

        return storage_id

    def get_traces(self) -> List[Dict[str, Any]]:
        """获取所有追踪记录（按时间倒序）。"""
        with self.lock:
            return list(reversed(self.traces))

    def get_trace(self, storage_id: str) -> Optional[Dict[str, Any]]:
        """获取单条追踪记录。"""
        with self.lock:
            for trace in self.traces:
                if trace['storage_id'] == storage_id:
                    return trace

        # 内存中没找到，尝试从文件读取
        filename = self.traces_dir / f"{storage_id}.json"
        if filename.exists():
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)

        return None

    def clear_traces(self):
        """清空所有追踪记录。"""
        with self.lock:
            self.traces = []

        # 删除所有文件
        for filename in self.traces_dir.glob("*.json"):
            filename.unlink()
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

    def save_trace(self, trace_data: Dict[str, Any]) -> str:
        """保存一条对话追踪记录。返回服务器端存储ID。"""
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
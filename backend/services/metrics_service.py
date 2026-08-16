"""
指标服务模块
收集和管理性能指标
"""
import json
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from backend.config import Config
from backend.models.request import RequestMetrics


class MetricsService:
    """指标服务类"""

    def __init__(self):
        self.metrics_dir = Config.METRICS_DIR
        self.performance_metrics = defaultdict(list)
        self.lock = threading.Lock()
        self.max_recent_requests = Config.MAX_RECENT_REQUESTS

        # 累计统计数据
        self.cumulative_stats = {
            'total_requests': 0,
            'total_time_sum': 0.0,
            'total_proxy_time_sum': 0.0,
            'total_model_time_sum': 0.0,
            'success_requests': 0,
            'failed_requests': 0,
            'inter_request_gaps': [],
            'max_total_time': 0.0,
            'min_total_time': float('inf')
        }

    def save_metrics(self, request_id: str, metrics: Dict[str, Any]) -> bool:
        """保存性能指标到文件和内存"""
        try:
            # 确保metrics包含request_id
            metrics['request_id'] = request_id

            # 保存到文件
            filename = self.metrics_dir / f"{request_id}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(metrics, f, ensure_ascii=False, indent=2)

            with self.lock:
                # 添加到最近请求列表
                self.performance_metrics['requests'].append({
                    'request_id': request_id,
                    **metrics
                })

                # 如果超过最大数量，移除最老的记录
                if len(self.performance_metrics['requests']) > self.max_recent_requests:
                    self.performance_metrics['requests'].pop(0)

                # 更新累计统计数据
                self._update_cumulative_stats(metrics)

            return True

        except Exception as e:
            print(f"保存指标失败: {e}")
            return False

    def _update_cumulative_stats(self, metrics: Dict[str, Any]):
        """更新累计统计数据"""
        self.cumulative_stats['total_requests'] += 1

        # 累加时间数据
        if 'total_time' in metrics:
            self.cumulative_stats['total_time_sum'] += metrics['total_time']
        if 'proxy_processing_time' in metrics:
            self.cumulative_stats['total_proxy_time_sum'] += metrics['proxy_processing_time']
        if 'model_response_time' in metrics:
            self.cumulative_stats['total_model_time_sum'] += metrics['model_response_time']
        elif 'time_to_first_byte' in metrics:
            self.cumulative_stats['total_model_time_sum'] += metrics['time_to_first_byte']

        # 更新成功/失败统计
        status_code = metrics.get('status_code', 200)
        if status_code == 200:
            self.cumulative_stats['success_requests'] += 1
        else:
            self.cumulative_stats['failed_requests'] += 1

        # 记录请求间隔
        if 'inter_request_gap' in metrics and metrics['inter_request_gap']:
            self.cumulative_stats['inter_request_gaps'].append(metrics['inter_request_gap'])

        # 更新最大最小响应时间
        if 'total_time' in metrics:
            total_time = metrics['total_time']
            if total_time > self.cumulative_stats['max_total_time']:
                self.cumulative_stats['max_total_time'] = total_time
            if total_time < self.cumulative_stats['min_total_time']:
                self.cumulative_stats['min_total_time'] = total_time

    def get_recent_metrics(self) -> List[Dict[str, Any]]:
        """获取最近的指标数据"""
        with self.lock:
            return list(self.performance_metrics.get('requests', []))

    def get_summary_stats(self) -> Dict[str, Any]:
        """获取摘要统计信息"""
        with self.lock:
            total = self.cumulative_stats['total_requests']

            if total == 0:
                return {
                    "total_requests": 0,
                    "avg_total_time": 0,
                    "avg_proxy_processing_time": 0,
                    "avg_model_response_time": 0,
                    "success_requests": 0,
                    "failed_requests": 0,
                    "success_rate": 0,
                    "avg_inter_request_gap": 0,
                    "max_total_time": 0,
                    "min_total_time": 0
                }
            else:
                success = self.cumulative_stats['success_requests']
                failed = self.cumulative_stats['failed_requests']
                success_rate = (success / total * 100) if total > 0 else 0

                return {
                    "total_requests": total,
                    "avg_total_time": self.cumulative_stats['total_time_sum'] / total if total > 0 else 0,
                    "avg_proxy_processing_time": self.cumulative_stats['total_proxy_time_sum'] / total if total > 0 else 0,
                    "avg_model_response_time": self.cumulative_stats['total_model_time_sum'] / total if total > 0 else 0,
                    "success_requests": success,
                    "failed_requests": failed,
                    "success_rate": success_rate,
                    "avg_inter_request_gap": sum(self.cumulative_stats['inter_request_gaps']) / len(self.cumulative_stats['inter_request_gaps']) if self.cumulative_stats['inter_request_gaps'] else 0,
                    "max_total_time": self.cumulative_stats['max_total_time'],
                    "min_total_time": self.cumulative_stats['min_total_time'] if self.cumulative_stats['min_total_time'] != float('inf') else 0
                }

    def clear_metrics(self):
        """清空所有指标数据"""
        with self.lock:
            self.performance_metrics = defaultdict(list)
            self.cumulative_stats = {
                'total_requests': 0,
                'total_time_sum': 0.0,
                'total_proxy_time_sum': 0.0,
                'total_model_time_sum': 0.0,
                'success_requests': 0,
                'failed_requests': 0,
                'inter_request_gaps': [],
                'max_total_time': 0.0,
                'min_total_time': float('inf')
            }
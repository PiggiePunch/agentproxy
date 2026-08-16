"""
日志服务模块
处理请求/响应日志的存储和检索
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from backend.config import Config
from backend.models.request import RequestLog, ResponseLog


class LogService:
    """日志服务类"""

    def __init__(self):
        self.requests_dir = Config.REQUESTS_DIR
        self.responses_dir = Config.RESPONSES_DIR
        self.metrics_dir = Config.METRICS_DIR

    def save_request_log(self, request_id: str, headers: dict, body: dict,
                         session_id: str = None) -> bool:
        """保存请求日志"""
        try:
            filename = self.requests_dir / f"{request_id}.json"
            request_data = {
                "request_id": request_id,
                "timestamp": datetime.now().isoformat(),
                "headers": headers,
                "body": body
            }
            if session_id:
                request_data["session_id"] = session_id
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(request_data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存请求日志失败: {e}")
            return False

    def save_response_log(self, request_id: str, body: Any, status_code: int) -> bool:
        """保存响应日志"""
        try:
            filename = self.responses_dir / f"{request_id}.json"
            response_data = {
                "status_code": status_code,
                "body": body,
                "timestamp": datetime.now().isoformat()
            }
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(response_data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存响应日志失败: {e}")
            return False

    def get_request_log(self, request_id: str) -> Optional[Dict[str, Any]]:
        """获取请求日志"""
        try:
            filename = self.requests_dir / f"{request_id}.json"
            if not filename.exists():
                return None

            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"读取请求日志失败: {e}")
            return None

    def get_response_log(self, request_id: str) -> Optional[Dict[str, Any]]:
        """获取响应日志"""
        try:
            filename = self.responses_dir / f"{request_id}.json"
            if not filename.exists():
                return None

            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"读取响应日志失败: {e}")
            return None

    def cleanup_old_logs(self, days_to_keep: int = 3) -> int:
        """清理旧日志文件"""
        try:
            from datetime import timedelta
            cutoff_time = datetime.now() - timedelta(days=days_to_keep)
            total_deleted = 0

            # 清理三个子目录
            for subdir_name, subdir_path in [
                ("请求日志", self.requests_dir),
                ("响应日志", self.responses_dir),
                ("性能指标", self.metrics_dir)
            ]:
                if not subdir_path.exists():
                    continue

                deleted_count = 0
                try:
                    for file_path in subdir_path.glob("*.json"):
                        if file_path.stat().st_mtime < cutoff_time.timestamp():
                            file_path.unlink()
                            deleted_count += 1
                            total_deleted += 1

                    if deleted_count > 0:
                        print(f"  已清理 {subdir_name}: {deleted_count} 个文件")
                except Exception as e:
                    print(f"  清理 {subdir_name} 时出错: {e}")

            if total_deleted > 0:
                print(f"日志清理完成: 共删除 {total_deleted} 个 {days_to_keep} 天前的旧文件")
            else:
                print(f"日志清理完成: 无需删除的旧文件")

            return total_deleted

        except Exception as e:
            print(f"日志清理失败: {e}")
            return 0
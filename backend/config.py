"""
配置管理模块
集中管理所有配置参数
"""
import os
from pathlib import Path

# ============= 基础配置 =============
class Config:
    """基础配置类"""

    # API配置
    REAL_API_URL = os.getenv("REAL_API_URL", "https://api.deepseek.com")
    ANTHROPIC_API_URL = os.getenv("ANTHROPIC_API_URL", "https://dashscope.aliyuncs.com/apps/anthropic")

    # 服务器配置
    SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
    SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))

    # 日志配置
    VERBOSE_LOGGING = os.getenv("VERBOSE_LOGGING", "true").lower() == "true"
    LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "3"))

    # 性能配置
    MAX_RECENT_REQUESTS = int(os.getenv("MAX_RECENT_REQUESTS", "100"))

    # 路径配置
    SCRIPT_DIR = Path(__file__).parent.parent.resolve()
    LOGS_DIR = SCRIPT_DIR / "logs"
    REQUESTS_DIR = LOGS_DIR / "requests"
    RESPONSES_DIR = LOGS_DIR / "responses"
    METRICS_DIR = LOGS_DIR / "metrics"
    TRACES_DIR = LOGS_DIR / "traces"

    @classmethod
    def init_directories(cls):
        """初始化所需的目录"""
        try:
            cls.LOGS_DIR.mkdir(exist_ok=True)
            cls.REQUESTS_DIR.mkdir(exist_ok=True)
            cls.RESPONSES_DIR.mkdir(exist_ok=True)
            cls.METRICS_DIR.mkdir(exist_ok=True)
            cls.TRACES_DIR.mkdir(exist_ok=True)
            print(f"日志目录初始化成功: {cls.LOGS_DIR}")
            return True
        except PermissionError as e:
            print(f"创建日志目录失败（权限不足）: {e}")
            return False
        except Exception as e:
            print(f"创建日志目录失败: {e}")
            return False

    @classmethod
    def get_printable_config(cls):
        """获取可打印的配置信息"""
        return {
            "REAL_API_URL": cls.REAL_API_URL,
            "ANTHROPIC_API_URL": cls.ANTHROPIC_API_URL,
            "SERVER_HOST": cls.SERVER_HOST,
            "SERVER_PORT": cls.SERVER_PORT,
            "LOG_RETENTION_DAYS": cls.LOG_RETENTION_DAYS
        }

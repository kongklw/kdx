"""WebSocket 生产级配置 (集中管理, 各 WS 接口共享单一来源)。

从环境变量读取; 生产可由 Settings 注入覆盖。新增 WS 接口无需重复定义参数。
"""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

# 保证任意 import 顺序下 .env 已加载 (与 core.config 同样的自举策略)
load_dotenv()


@dataclass(frozen=True)
class WSConfig:
    max_connections: int            # 单进程全局并发连接上限: 防 OOM/FD 耗尽/DDoS
    max_connections_per_user: int  # 单用户并发上限: 防会话堆积/恶意占用
    idle_timeout: int              # 空闲踢出 (秒): 清理半开/僵尸连接
    max_message_size: int          # 单帧上限 (字节): 下游保护; 真正帧级限制见 uvicorn --ws-max-size
    allowed_origins: tuple         # 允许的 Origin; 空=不校验 (App/小程序无 Origin 头)


def get_ws_config() -> WSConfig:
    """读取环境变量构造 WSConfig (运行期单次读取即可, 修改需重启)。"""
    raw_origins = os.getenv("WS_ALLOWED_ORIGINS", "")
    origins = tuple(o.strip() for o in raw_origins.split(",") if o.strip())
    return WSConfig(
        max_connections=int(os.getenv("WS_MAX_CONNECTIONS", "1000")),
        max_connections_per_user=int(os.getenv("WS_MAX_CONN_PER_USER", "3")),
        idle_timeout=int(os.getenv("WS_IDLE_TIMEOUT", "600")),
        max_message_size=int(os.getenv("WS_MAX_MESSAGE_SIZE", str(1024 * 1024))),
        allowed_origins=origins,
    )
